# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _


class PosConfig(models.Model):
    _inherit = 'pos.config'

    cz_cash_control = fields.Boolean(string='Choco Zuma Cash Control', default=False,
                                     help="Enable categorised cash-outs, blind count and the daily cash sheet for this POS.")
    cz_safe_id = fields.Many2one('cz.cash.safe', string='Branch Safe', check_company=True,
                                 domain="[('company_id', '=', company_id)]",
                                 help="Drawer→safe transfers approved on the daily sheet are mirrored into this safe.")
    cz_blind_count = fields.Boolean(string='Blind cash count at closing', default=True,
                                    help="Hide the expected cash and the difference from the cashier while counting.")
    cz_zero_count_pin = fields.Boolean(string='Manager PIN when count is 0', default=True)
    cz_diff_pin_above = fields.Float(string='Manager PIN when |difference| above', default=50.0,
                                     help="Closing with a bigger difference requires a manager PIN and a closing note.")
    cz_cash_out_pin_above = fields.Float(string='Manager PIN for any cash out above', default=5000.0,
                                         help="Independent of the category rules. 0 = off.")
    cz_enable_eod = fields.Boolean(string='"Gün Sonu" button at closing', default=False,
                                   help="Show the one-PIN 'empty the whole drawer into the safe and close at 0' button in the "
                                        "closing popup. Off: the cashier only counts; transfers to the safe are recorded with "
                                        "Masraf → 'Küçük Kasaya Aktar'.")
    cz_show_recent = fields.Boolean(string='"Recent movements" chips in the cash popup', default=False,
                                    help="One-tap repeat of the last movements. Off by default (Mo: not practical).")
    cz_drawer_alert_above = fields.Float(string='Alert when drawer holds more than overnight', default=10000.0,
                                         help="Warn on the daily sheet when more than this stays in the drawer after closing. 0 = off.")
    cz_opening_float = fields.Float(string='Standard opening float', default=2000.0,
                                    help="Expected cash left in the drawer at closing (devir).")
    cz_accountant_ids = fields.Many2many('res.users', 'cz_pos_config_accountant_rel', 'config_id', 'user_id',
                                         string='Accountants to notify')
    cz_manager_ids = fields.Many2many('res.users', 'cz_pos_config_manager_rel', 'config_id', 'user_id',
                                      string='Managers to notify')
    cz_large_amount_alert = fields.Float(
        string='Alert the owners above', default=0.0,
        help="A payment from the drawer or from the safe above this amount is still accepted, but the owners are "
             "notified at once (drawer payments are also flagged on the daily sheet). 0 = no alert.")
    cz_owner_ids = fields.Many2many('res.users', 'cz_pos_config_owner_rel', 'config_id', 'user_id',
                                    string='Owners to alert (large payments)')
    cz_digest_lang = fields.Selection([('ar', 'العربية'), ('tr', 'Türkçe'), ('en', 'English')],
                                      string='Language of the daily approval digest', default='ar', required=True)
    cz_staff = fields.Json(compute='_compute_cz_staff', string='Staff selectable on cash movements',
                           help="Sent to the POS: every active employee of the branch, whether or not they may log in "
                                "to the POS. System administrators are left out — an expense is never 'for ADMIN'.")

    def _cz_staff_employees(self):
        """Employees a cashier may pick on a movement (taxi, food, advance…): the whole branch,
        not only the few people allowed to log in to the POS. Administrator accounts are excluded."""
        self.ensure_one()
        employees = self.env['hr.employee'].sudo().with_context(active_test=True).search(
            [('company_id', 'in', [self.company_id.id, False])])
        return employees.filtered(lambda e: not e.cz_shared_login and not (
            e.user_id and e.user_id.has_group('base.group_system'))).sorted('name')

    def _compute_cz_staff(self):
        for cfg in self:
            cfg.cz_staff = [{'id': e.id, 'name': e.name} for e in cfg._cz_staff_employees()] if cfg.cz_cash_control else []

    # ----------------------------------------------------------------- dashboard (not stored)
    cz_today_day_id = fields.Many2one('cz.cash.day', compute='_compute_cz_dashboard', string="Today's sheet")
    cz_today_cash_sales = fields.Monetary(compute='_compute_cz_dashboard', currency_field='currency_id', string="Today: cash sales")
    cz_today_expenses = fields.Monetary(compute='_compute_cz_dashboard', currency_field='currency_id', string="Today: drawer expenses")
    cz_today_safe_transfers = fields.Monetary(compute='_compute_cz_dashboard', currency_field='currency_id', string="Today: to safe")
    cz_today_state = fields.Selection([('none', 'No session'), ('open', 'Open'), ('to_approve', 'To approve'), ('approved', 'Approved')],
                                      compute='_compute_cz_dashboard')
    cz_safe_balance = fields.Monetary(related='cz_safe_id.balance', string='Safe balance')
    cz_pending_count = fields.Integer(compute='_compute_cz_dashboard', string='Sheets waiting approval')
    cz_pending_amount = fields.Monetary(compute='_compute_cz_dashboard', currency_field='currency_id', string='Unposted expenses')
    cz_alert_count = fields.Integer(compute='_compute_cz_dashboard', string='Open alerts')
    cz_alert_level = fields.Selection([('ok', 'OK'), ('warning', 'Warning'), ('danger', 'Critical')], compute='_compute_cz_dashboard')
    cz_month_expenses = fields.Monetary(compute='_compute_cz_dashboard', currency_field='currency_id', string='Expenses (30 days)')
    cz_last_difference = fields.Monetary(compute='_compute_cz_dashboard', currency_field='currency_id', string='Last closing difference')

    def _compute_cz_dashboard(self):
        Day = self.env['cz.cash.day'].sudo()
        today = fields.Date.context_today(self)
        since = today - timedelta(days=30)
        for cfg in self:
            # "today" = today's sheet, or the latest sheet still open / waiting for approval
            # (the business day may be yesterday: sessions opened before 04:00, late closings)
            day = Day.search(['&', ('config_id', '=', cfg.id), '|', ('date', '=', today), ('state', 'in', ('open', 'to_approve'))],
                             order='date desc, seq desc', limit=1)
            pending = Day.search([('config_id', '=', cfg.id), ('state', 'in', ('open', 'to_approve'))])
            last_closed = Day.search([('config_id', '=', cfg.id), ('state', 'in', ('to_approve', 'approved'))],
                                     order='date desc, seq desc', limit=1)
            month = Day.search([('config_id', '=', cfg.id), ('date', '>=', since)])
            cfg.cz_today_day_id = day
            cfg.cz_today_cash_sales = day.cash_sales
            cfg.cz_today_expenses = day.expense_total
            cfg.cz_today_safe_transfers = day.safe_transfer_total
            cfg.cz_today_state = day.state if day else 'none'
            cfg.cz_pending_count = len(pending)
            cfg.cz_pending_amount = sum(pending.mapped('expense_total'))
            cfg.cz_alert_count = sum(pending.mapped('alert_count'))
            levels = set(pending.mapped('alert_level'))
            cfg.cz_alert_level = 'danger' if 'danger' in levels else ('warning' if 'warning' in levels else 'ok')
            cfg.cz_month_expenses = sum(month.mapped('expense_total'))
            cfg.cz_last_difference = last_closed.difference

    def action_cz_open_today(self):
        self.ensure_one()
        if self.cz_today_day_id:
            return {'type': 'ir.actions.act_window', 'res_model': 'cz.cash.day', 'res_id': self.cz_today_day_id.id,
                    'view_mode': 'form', 'target': 'current'}
        return self.action_cz_open_days()

    def action_cz_open_days(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('cz_cash_control.action_cz_cash_day')
        action['domain'] = [('config_id', '=', self.id)]
        action['context'] = {'search_default_to_approve': 1, 'default_config_id': self.id}
        return action

    def action_cz_open_safe(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'cz.cash.safe', 'res_id': self.cz_safe_id.id,
                'view_mode': 'form', 'target': 'current'}

    def action_cz_open_graph(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('cz_cash_control.action_cz_cash_day_line_graph')
        action['domain'] = [('config_id', '=', self.id)]
        return action
