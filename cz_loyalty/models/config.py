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
    visits_per_reward = fields.Integer(default=5, required=True, tracking=True)
    code_valid_hours = fields.Integer(default=48, required=True, tracking=True)
    reward_valid_days = fields.Integer(default=30, required=True, tracking=True)
    min_order_amount = fields.Float(default=250.0, tracking=True, help="Orders below this total earn nothing.")
    reward_product_id = fields.Many2one(
        "product.product", string="Reward product (Zuma Sürprizi)", tracking=True,
        help="The off-menu dish given every N visits. It must be available in every branch POS.",
    )
    kvkk_url = fields.Char(string="KVKK notice URL", default="https://b2b.chocozuma.com/kvkk-aydinlatma-metni")
    alert_partner_ids = fields.Many2many("res.partner", string="Alert recipients")

    @api.model
    def get(self):
        cfg = self.sudo().search([], limit=1)
        if not cfg:
            cfg = self.sudo().create({})
        return cfg

    @api.constrains("visits_per_reward", "code_valid_hours", "reward_valid_days")
    def _check_positive(self):
        for rec in self:
            if rec.visits_per_reward < 1 or rec.code_valid_hours < 1 or rec.reward_valid_days < 1:
                raise UserError("Visits per reward, code validity and reward validity must be at least 1.")

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
