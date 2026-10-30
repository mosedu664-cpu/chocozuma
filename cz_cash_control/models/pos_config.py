# -*- coding: utf-8 -*-
from odoo import api, fields, models


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
    cz_opening_float = fields.Float(string='Standard opening float', default=2000.0,
                                    help="Expected cash left in the drawer at closing (devir).")
    cz_accountant_ids = fields.Many2many('res.users', 'cz_pos_config_accountant_rel', 'config_id', 'user_id',
                                         string='Accountants to notify')
    cz_manager_ids = fields.Many2many('res.users', 'cz_pos_config_manager_rel', 'config_id', 'user_id',
                                      string='Managers to notify')
