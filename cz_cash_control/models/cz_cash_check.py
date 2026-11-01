# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class CzCashCheck(models.Model):
    """Mid-day drawer check (X-count): a blind count of the drawer during an open
    session, authorised by a manager PIN. Nothing is posted and the session stays
    open; the record is an immutable audit trail (who, when, counted, expected).
    """
    _name = 'cz.cash.check'
    _description = 'Mid-day Drawer Check'
    _order = 'check_time desc, id desc'
    _check_company_auto = True

    name = fields.Char(string='Reference', readonly=True, copy=False, default='/')
    session_id = fields.Many2one('pos.session', string='POS Session', required=True, readonly=True,
                                 index=True, ondelete='cascade')
    config_id = fields.Many2one(related='session_id.config_id', store=True, string='Point of Sale')
    company_id = fields.Many2one(related='session_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='session_id.currency_id')
    day_id = fields.Many2one('cz.cash.day', string='Daily Cash Sheet', readonly=True, index=True, ondelete='set null')
    check_time = fields.Datetime(string='Time', required=True, readonly=True, default=fields.Datetime.now)
    check_type = fields.Selection([
        ('handover', 'Shift handover'),
        ('spot', 'Spot check'),
    ], string='Type', required=True, readonly=True, default='spot')
    cashier_name = fields.Char(string='Cashier', readonly=True)
    manager_id = fields.Many2one('hr.employee', string='Authorised by', readonly=True)
    opening = fields.Monetary(string='Opening', currency_field='currency_id', readonly=True)
    cash_sales = fields.Monetary(string='Cash sales so far', currency_field='currency_id', readonly=True)
    cash_moves = fields.Monetary(string='Cash in/out so far', currency_field='currency_id', readonly=True)
    expected = fields.Monetary(string='Expected', currency_field='currency_id', readonly=True)
    counted = fields.Monetary(string='Counted', currency_field='currency_id', readonly=True)
    difference = fields.Monetary(string='Difference', currency_field='currency_id', readonly=True,
                                 help="Counted − expected. Negative = shortage.")
    note = fields.Char(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('cz.cash.check') or '/'
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get('cz_check_system') and not self.env.is_superuser():
            raise UserError(_("Drawer checks are an audit trail and cannot be modified."))
        return super().write(vals)

    def unlink(self):
        if not self.env.user.has_group('cz_cash_control.group_cz_cash_admin'):
            raise UserError(_("Drawer checks are an audit trail and cannot be deleted."))
        return super().unlink()
