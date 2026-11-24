# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError

from .tools import normalize_phone


class CzLoyaltyConfig(models.Model):
    _name = "cz.loyalty.config"
    _description = "Kakao Hazinesi settings"
    _inherit = ["mail.thread"]

    name = fields.Char(default="Kakao Hazinesi", required=True)
    mode = fields.Selection(
        [("off", "Off"), ("test", "Test (whitelisted phones only)"), ("live", "Live")],
        default="off", required=True, tracking=True,
        help="Off: nothing is credited or sent. Test: only the phones below get credits and replies. Live: everyone.",
    )
    test_phones = fields.Text(
        string="Test phones", tracking=True,
        help="One phone per line or comma separated. Used in Test mode only.",
    )
    staff_phones = fields.Text(
        string="Staff phones (never earn)", tracking=True,
        help="Employees' phones: they can never earn beans, in any mode.",
    )
    pos_config_ids = fields.Many2many("pos.config", string="Branches (POS)", tracking=True)
    wa_account_ids = fields.Many2many("whatsapp.account", string="WhatsApp accounts", tracking=True)
    shop_number = fields.Char(string="Shop WhatsApp number", help="Number printed on receipts, e.g. +905392231801")
    small_at = fields.Integer(string="Small gift at (visits)", default=4, required=True, tracking=True)
    cycle_len = fields.Integer(string="Big gift at (visits)", default=8, required=True, tracking=True)
    welcome_beans = fields.Integer(string="Welcome beans (first scan only)", default=1, tracking=True)
    code_valid_hours = fields.Integer(default=72, required=True, tracking=True)
    reward_valid_days = fields.Integer(default=60, required=True, tracking=True)
    min_order_amount = fields.Float(default=300.0, tracking=True, help="Orders below this total earn nothing.")
    reward_small_product_id = fields.Many2one(
        "product.product", string="Small gift product (Şefin İkramı)", tracking=True,
        help="Off-menu dish at the small threshold. Must be available in every branch POS.")
    reward_big_product_id = fields.Many2one(
        "product.product", string="Big gift product (Hazine Tabağı)", tracking=True,
        help="Off-menu dish at the big threshold. Must be available in every branch POS.")
    test_skip_daily_limit = fields.Boolean(
        string="Test mode: allow several beans per day", default=True, tracking=True,
        help="Only applies in Test mode, so a full cycle can be tested in one sitting.")
    print_on_receipt = fields.Boolean(
        string="Print the cacao banknote on receipts", tracking=True,
        help="Adds the banknote with the QR code under every eligible receipt and bill of the branches above. "
             "Switch it on only when guests can really use it (mode Live), or on staging.")
    kvkk_url = fields.Char(string="KVKK notice URL", default="https://b2b.chocozuma.com/kvkk-aydinlatma-metni")
    alert_partner_ids = fields.Many2many("res.partner", string="Alert recipients")

    @api.model
    def get(self):
        cfg = self.sudo().search([], limit=1)
        if not cfg:
            cfg = self.sudo().create({})
        return cfg

    def _platform_partner_ids(self):
        """POS customers that stand for a delivery platform (*TRENDYOL, ...): their orders never earn."""
        if "cz.platform.account" not in self.env:
            return []
        accounts = self.env["cz.platform.account"].sudo().with_context(active_test=False).search([("partner_id", "!=", False)])
        return accounts.mapped("partner_id").ids

    @api.constrains("small_at", "cycle_len", "code_valid_hours", "reward_valid_days")
    def _check_positive(self):
        for rec in self:
            if rec.small_at < 1 or rec.cycle_len <= rec.small_at or rec.code_valid_hours < 1 or rec.reward_valid_days < 1:
                raise UserError("Small gift must be at 1 or more visits, the big gift later than the small one, and validities at least 1.")

    @staticmethod
    def _phone_set(text):
        out = set()
        for chunk in (text or "").replace(",", "\n").splitlines():
            p = normalize_phone(chunk.strip())
            if p:
                out.add(p)
        return out

    def is_allowed(self, phone):
        """May this phone earn and receive replies right now?"""
        self.ensure_one()
        if self.mode == "off" or not phone:
            return False
        if phone in self._phone_set(self.staff_phones):
            return False
        if self.mode == "test":
            return phone in self._phone_set(self.test_phones)
        return True

    def is_staff(self, phone):
        self.ensure_one()
        return phone in self._phone_set(self.staff_phones)
