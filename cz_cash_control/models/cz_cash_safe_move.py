# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CzCashSafeMove(models.Model):
    """A movement of the branch safe, entered by the responsible manager.

    Nothing touches the books until the accountant approves; approval creates
    a statement line in the safe journal with the category counterpart.
    """
    _name = 'cz.cash.safe.move'
    _description = 'Safe Movement'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(string='Reference', readonly=True, copy=False, default='/')
    safe_id = fields.Many2one('cz.cash.safe', required=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='safe_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='safe_id.currency_id')
    date = fields.Date(required=True, default=fields.Date.context_today)
    move_type = fields.Selection([
        ('in', 'Cash in (from drawer / bank)'),
        ('out', 'Cash out (payment)'),
        ('count', 'Physical count'),
    ], required=True, default='out')
    amount = fields.Monetary(required=True, currency_field='currency_id',
                             help="For a count: the amount physically found in the safe.")
    category_id = fields.Many2one(
        'cz.cash.category', check_company=True,
        domain="[('company_id', '=', company_id), ('kind', 'in', ('expense', 'advance', 'other', 'cash_in'))]")
    partner_id = fields.Many2one('res.partner', string='Paid to / received from')
    employee_id = fields.Many2one('hr.employee', string='Employee')
    note = fields.Char(string='Description', required=True)
    receipt_ref = fields.Char(string='Receipt / Fiş No')
    attachment_ids = fields.Many2many('ir.attachment', string='Receipt scan')
    origin_day_id = fields.Many2one('cz.cash.day', string='From daily sheet', readonly=True, ondelete='set null')
    statement_line_id = fields.Many2one('account.bank.statement.line', readonly=True, copy=False)
    count_difference = fields.Monetary(readonly=True, currency_field='currency_id')
    state = fields.Selection([
        ('draft', 'To approve'),
        ('approved', 'Approved'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True, index=True)
    approved_by = fields.Many2one('res.users', readonly=True)
    approved_at = fields.Datetime(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('cz.cash.safe.move') or '/'
        return super().create(vals_list)

    @api.constrains('amount', 'move_type')
    def _check_amount(self):
        for move in self:
            if move.move_type != 'count' and move.amount <= 0:
                raise ValidationError(_("Amount must be positive."))
            if move.move_type == 'count' and move.amount < 0:
                raise ValidationError(_("Counted amount cannot be negative."))

    @api.constrains('category_id', 'move_type')
    def _check_category(self):
        for move in self:
            if move.move_type == 'out' and not move.category_id:
                raise ValidationError(_("A category is required for a cash out from the safe."))

    def write(self, vals):
        protected = {'amount', 'date', 'move_type', 'category_id', 'safe_id'}
        if protected & set(vals) and any(m.state == 'approved' for m in self):
            raise UserError(_("An approved safe movement cannot be modified. Cancel it and create a new one."))
        return super().write(vals)

    def unlink(self):
        if any(m.state == 'approved' for m in self):
            raise UserError(_("Approved safe movements cannot be deleted."))
        return super().unlink()

    # ------------------------------------------------------------------ actions
    def action_approve(self):
        for move in self:
            if move.state != 'draft':
                continue
            if move.move_type == 'count':
                move._approve_count()
            else:
                move._approve_cash()
            move.write({'state': 'approved', 'approved_by': self.env.uid, 'approved_at': fields.Datetime.now()})
        return True

    def action_cancel(self):
        for move in self:
            if move.state == 'approved':
                if move.statement_line_id:
                    st_line = move.statement_line_id.sudo()
                    st_line.line_ids.remove_move_reconcile()
                    st_line.move_id.button_draft()
                    st_line.with_context(force_delete=True).unlink()
                    move.statement_line_id = False
            move.state = 'cancelled'
        return True

    def action_reset_draft(self):
        self.filtered(lambda m: m.state == 'cancelled').write({'state': 'draft', 'statement_line_id': False})

    def _statement_line_vals(self, amount, counterpart_account, label):
        self.ensure_one()
        return {
            'journal_id': self.safe_id.journal_id.id,
            'date': self.date,
            'amount': amount,
            'payment_ref': label,
            'partner_id': self.partner_id.id or self.employee_id.work_contact_id.id or False,
            'counterpart_account_id': counterpart_account.id,
            'cz_safe_move_id': self.id,
            'cz_category_id': self.category_id.id,
            'cz_employee_id': self.employee_id.id,
        }

    def _approve_cash(self):
        self.ensure_one()
        sign = 1 if self.move_type == 'in' else -1
        account = self.category_id.account_id if self.category_id else self.safe_id.transfer_account_id
        if not account:
            raise UserError(_("No counterpart account: set a category or a transfer account on the safe."))
        code = self.category_id.code if self.category_id else 'TRANSFER'
        label = f"[{code}] {self.note}"
        if self.employee_id:
            label += f" — {self.employee_id.name}"
        if self.receipt_ref:
            label += f" (fiş {self.receipt_ref})"
        st_line = self.env['account.bank.statement.line'].sudo().create(
            self._statement_line_vals(sign * self.amount, account, label))
        self.statement_line_id = st_line

    def _approve_count(self):
        """Book the count difference to the journal's profit/loss account."""
        self.ensure_one()
        safe = self.safe_id
        diff = self.currency_id.round(self.amount - safe.balance)
        self.count_difference = diff
        if not self.currency_id.is_zero(diff):
            journal = safe.journal_id
            account = journal.profit_account_id if diff > 0 else journal.loss_account_id
            if not account:
                raise UserError(_("Define profit/loss accounts on journal %s.", journal.display_name))
            label = _("Safe count difference (%(kind)s) — %(note)s",
                      kind=_("surplus") if diff > 0 else _("shortage"), note=self.note)
            self.statement_line_id = self.env['account.bank.statement.line'].sudo().create(
                self._statement_line_vals(diff, account, label))
        safe.sudo().write({
            'last_count_date': self.date,
            'last_count_amount': self.amount,
            'last_count_difference': diff,
        })
        safe.message_post(body=_("Safe counted by %(user)s: %(amt)s (difference %(diff)s).",
                                 user=self.env.user.name, amt=self.currency_id.format(self.amount),
                                 diff=self.currency_id.format(diff)))
