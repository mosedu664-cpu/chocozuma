# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CzCashSafe(models.Model):
    """Branch safe (küçük kasa).

    The safe is a normal Odoo cash journal; this model adds the responsible
    manager, the live balance, counts and the link to the POS it is fed by.
    """
    _name = 'cz.cash.safe'
    _description = 'Branch Safe (Küçük Kasa)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    journal_id = fields.Many2one(
        'account.journal', string='Safe Journal', required=True, check_company=True,
        domain="[('type', '=', 'cash'), ('company_id', '=', company_id)]",
        help="Cash journal that represents the physical safe.")
    account_id = fields.Many2one(related='journal_id.default_account_id', string='Safe Account')
    transfer_account_id = fields.Many2one(
        'account.account', string='Transfer Clearing Account', required=True, check_company=True,
        domain="[('company_ids', 'in', company_id), ('deprecated', '=', False)]",
        help="Both legs of a drawer→safe transfer hit this account so it always nets to zero.")
    responsible_id = fields.Many2one('res.users', string='Responsible (Manager)', required=True, tracking=True)
    pos_config_ids = fields.One2many('pos.config', 'cz_safe_id', string='Fed by POS')

    balance = fields.Monetary(compute='_compute_balance', currency_field='currency_id', string='Book Balance')
    balance_date = fields.Datetime(compute='_compute_balance')
    last_count_date = fields.Date(readonly=True, tracking=True)
    last_count_amount = fields.Monetary(readonly=True, currency_field='currency_id', tracking=True)
    last_count_difference = fields.Monetary(readonly=True, currency_field='currency_id', tracking=True)
    max_balance_alert = fields.Monetary(
        string='Alert above', currency_field='currency_id', default=0.0,
        help="Alert the responsible when the safe holds more than this (bank deposit due). 0 = off.")
    move_ids = fields.One2many('cz.cash.safe.move', 'safe_id', string='Movements')
    pending_move_count = fields.Integer(compute='_compute_pending_move_count')

    _sql_constraints = [
        ('journal_uniq', 'unique(journal_id)', 'A journal can only be one safe.'),
    ]

    def _balance_domain(self):
        self.ensure_one()
        return [
            ('journal_id', '=', self.journal_id.id),
            ('account_id', '=', self.account_id.id),
            ('parent_state', '=', 'posted'),
            ('company_id', '=', self.company_id.id),
        ]

    @api.depends('journal_id')
    def _compute_balance(self):
        AML = self.env['account.move.line'].sudo()
        for safe in self:
            if not safe.journal_id:
                safe.balance = 0.0
                safe.balance_date = False
                continue
            res = AML._read_group(safe._balance_domain(), aggregates=['balance:sum'])
            safe.balance = res[0][0] or 0.0
            safe.balance_date = fields.Datetime.now()

    def _compute_pending_move_count(self):
        groups = self.env['cz.cash.safe.move']._read_group(
            [('safe_id', 'in', self.ids), ('state', '=', 'draft')], ['safe_id'], ['__count'])
        counts = {safe.id: count for safe, count in groups}
        for safe in self:
            safe.pending_move_count = counts.get(safe.id, 0)

    def action_open_ledger(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Safe Ledger — %s', self.name),
            'res_model': 'account.move.line',
            'view_mode': 'list,pivot',
            'domain': self._balance_domain(),
            'context': {'search_default_group_by_date': 0, 'create': 0, 'edit': 0},
        }

    def action_open_moves(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Safe Movements — %s', self.name),
            'res_model': 'cz.cash.safe.move',
            'view_mode': 'list,form',
            'domain': [('safe_id', '=', self.id)],
            'context': {'default_safe_id': self.id},
        }

    def action_count(self):
        """Open the count wizard (a plain safe move of type 'count')."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Count Safe — %s', self.name),
            'res_model': 'cz.cash.safe.move',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_safe_id': self.id, 'default_move_type': 'count',
                        'default_amount': self.balance},
        }

    def _check_alerts(self):
        """Called by cron: high balance / stale count."""
        for safe in self:
            msgs = []
            if safe.max_balance_alert and safe.balance > safe.max_balance_alert:
                msgs.append(_("Safe balance %(bal)s exceeds the alert threshold %(thr)s — bank deposit due.",
                              bal=safe.currency_id.format(safe.balance), thr=safe.currency_id.format(safe.max_balance_alert)))
            if not safe.last_count_date or (fields.Date.today() - safe.last_count_date).days > 7:
                msgs.append(_("Safe has not been counted for more than 7 days."))
            if msgs:
                safe.message_post(body=Markup('<br/>').join(msgs), partner_ids=safe.responsible_id.partner_id.ids,
                                  subtype_xmlid='mail.mt_comment')
