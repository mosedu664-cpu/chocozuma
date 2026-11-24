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

    def action_pos_order_paid(self):
        res = super().action_pos_order_paid()
        try:
            for order in self.filtered("uuid"):
                rewards = self.env["cz.loyalty.reward"].sudo().search(
                    [("used_order_uuid", "=", order.uuid), ("state", "=", "used"), ("used_order_id", "=", False)])
                if rewards:
                    rewards.write({"used_order_id": order.id, "used_order_ref": order.pos_reference})
        except Exception:
            _logger.exception("cz_loyalty: could not link the gift to its order (payment is unaffected)")
        return res

    def action_pos_order_cancel(self):
        res = super().action_pos_order_cancel()
        try:
            uuids = [u for u in self.filtered(lambda o: o.state == "cancel").mapped("uuid") if u]
            if uuids:
                self.env["cz.loyalty.reward"].sudo().search(
                    [("used_order_uuid", "in", uuids), ("state", "=", "used")]
                ).write({"state": "issued", "used_at": False, "used_config_id": False, "used_company_id": False,
                         "used_order_uuid": False, "used_order_ref": False, "used_by_id": False, "used_order_id": False})
        except Exception:
            _logger.exception("cz_loyalty: could not release the gift of a cancelled order")
        return res

    def _cz_loyalty_wa_link(self):
        """wa.me link printed as QR on the receipt (Increment 2)."""
        self.ensure_one()
        cfg = self.env["cz.loyalty.config"].get()
        if not (self.cz_loyalty_code and cfg.shop_number):
            return False
        number = "".join(c for c in cfg.shop_number if c.isdigit())
        return f"https://wa.me/{number}?text=Kakao%20Hazinesi%20%E2%9C%A6%20ZUMA-{self.cz_loyalty_code}"


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    cz_reward_token = fields.Char(string="Kakao gift code", copy=False, index=True)

    @api.model
    def _load_pos_data_fields(self, config_id):
        return super()._load_pos_data_fields(config_id) + ["cz_reward_token"]
