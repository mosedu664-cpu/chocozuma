# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    # Read-only mirrors of the Kakao Hazinesi settings, loaded with the POS so the receipt can print the banknote.
    cz_loyalty_receipt = fields.Boolean(compute="_compute_cz_loyalty")
    cz_loyalty_redeem = fields.Boolean(compute="_compute_cz_loyalty")
    cz_loyalty_hint = fields.Boolean(compute="_compute_cz_loyalty")
    cz_loyalty_wa_number = fields.Char(compute="_compute_cz_loyalty")
    cz_loyalty_min_amount = fields.Float(compute="_compute_cz_loyalty")
    cz_loyalty_valid_hours = fields.Integer(compute="_compute_cz_loyalty")
    cz_loyalty_excluded_partners = fields.Char(compute="_compute_cz_loyalty")
    cz_loyalty_launch = fields.Char(compute="_compute_cz_loyalty")

    def _compute_cz_loyalty(self):
        cfg = self.env["cz.loyalty.config"].get()
        number = "".join(c for c in (cfg.shop_number or "") if c.isdigit())
        excluded = ",".join(str(i) for i in cfg._platform_partner_ids())
        for config in self:
            config.cz_loyalty_receipt = bool(
                cfg.mode != "off" and cfg.print_on_receipt and number and config in cfg.pos_config_ids)
            config.cz_loyalty_hint = bool(cfg.cashier_hint)
            config.cz_loyalty_redeem = bool(cfg.mode != "off" and config in cfg.pos_config_ids)
            config.cz_loyalty_wa_number = number
            config.cz_loyalty_min_amount = cfg.min_order_amount
            config.cz_loyalty_valid_hours = cfg.code_valid_hours
            config.cz_loyalty_excluded_partners = excluded
            config.cz_loyalty_launch = cfg.launch_date.isoformat() if cfg.launch_date else ""
