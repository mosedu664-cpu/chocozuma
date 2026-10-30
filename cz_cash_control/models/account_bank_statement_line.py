# -*- coding: utf-8 -*-
from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    cz_category_id = fields.Many2one('cz.cash.category', string='Cash Category', index=True, copy=False)
    cz_employee_id = fields.Many2one('hr.employee', string='Staff', copy=False)
    cz_receipt_ref = fields.Char(string='Receipt / Fiş No', copy=False)
    cz_day_id = fields.Many2one('cz.cash.day', string='Daily Cash Sheet', index=True, copy=False, ondelete='set null')
    cz_safe_move_id = fields.Many2one('cz.cash.safe.move', string='Safe Movement', copy=False, ondelete='set null')
    cz_approved = fields.Boolean(string='Approved by accountant', copy=False, default=False)
    cz_pos_cashier = fields.Char(string='Cashier', copy=False, help="Employee logged in the POS when the movement was made.")
    cz_manager_pin_ok = fields.Boolean(string='Manager PIN given', copy=False)

    def _cz_set_counterpart(self, account, label=None):
        """Replace the suspense leg of a posted statement line with the given account.

        Mirrors what Odoo's own reconciliation widget / action_undo_reconciliation do,
        so the move stays balanced and the line becomes 'reconciled'.
        """
        for st_line in self:
            if not account:
                raise UserError(_("No counterpart account for %s.", st_line.payment_ref))
            st_line.line_ids.remove_move_reconcile()
            vals = st_line._prepare_move_line_default_vals(counterpart_account_id=account.id)
            if label:
                for v in vals:
                    if v.get('account_id') == account.id:
                        v['name'] = label
            st_line.with_context(force_delete=True, skip_readonly_check=True).write({
                'line_ids': [Command.clear()] + [Command.create(v) for v in vals],
            })
        return True

    def write(self, vals):
        # Cashier-side fields are frozen once the accountant approved the day.
        frozen = {'amount', 'payment_ref', 'date', 'cz_category_id', 'cz_employee_id'}
        if frozen & set(vals) and not self.env.context.get('cz_approval') \
                and any(l.cz_approved for l in self):
            raise UserError(_("This cash movement was approved by the accountant and can no longer be modified."))
        return super().write(vals)

    def unlink(self):
        if any(l.cz_approved for l in self) and not self.env.context.get('force_delete'):
            raise UserError(_("Approved cash movements cannot be deleted."))
        return super().unlink()
