# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

from .tools import new_order_code

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = "pos.order"

    cz_loyalty_code = fields.Char(string="Kakao code", copy=False, readonly=True, index=True)

    def init(self):
        super().init()
        self.env.cr.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS pos_order_cz_loyalty_code_uniq "
            "ON pos_order (cz_loyalty_code) WHERE cz_loyalty_code IS NOT NULL"
        )

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        # Never block a POS sync: any failure here only means "no code on this receipt".
        try:
            cfg = self.env["cz.loyalty.config"].get()
            if cfg.mode != "off" and cfg.pos_config_ids:
                for order in orders.filtered(lambda o: not o.cz_loyalty_code and o.config_id in cfg.pos_config_ids):
                    with self.env.cr.savepoint():
                        order.sudo().cz_loyalty_code = new_order_code()
        except Exception:
            _logger.exception("cz_loyalty: code generation failed (sale is unaffected)")
        return orders

    def _cz_loyalty_wa_link(self):
        """wa.me link printed as QR on the receipt (Increment 2)."""
        self.ensure_one()
        cfg = self.env["cz.loyalty.config"].get()
        if not (self.cz_loyalty_code and cfg.shop_number):
            return False
        number = "".join(c for c in cfg.shop_number if c.isdigit())
        return f"https://wa.me/{number}?text=Kakao%20Hazinesi%20%E2%9C%A6%20ZUMA-{self.cz_loyalty_code}"
