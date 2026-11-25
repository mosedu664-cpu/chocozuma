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
            for order in self:
                # By the code on the line, not by the order it was first added to: the line may have been
                # moved to another bill (split, table transfer) before payment.
                tokens = [t for t in order.lines.mapped("cz_reward_token") if t]
                if tokens:
                    self.env["cz.loyalty.reward"].sudo().search(
                        [("token", "in", tokens), ("state", "=", "used")]
                    ).write({"used_order_id": order.id, "used_order_ref": order.pos_reference,
                             "used_order_uuid": order.uuid, "used_config_id": order.config_id.id,
                             "used_company_id": order.company_id.id})
        except Exception:
            _logger.exception("cz_loyalty: could not link the gift to its order (payment is unaffected)")
        return res

    def write(self, vals):
        res = super().write(vals)
        # Whatever cancels an order (POS, back office, another module): its gift code is usable again.
        if vals.get("state") == "cancel":
            try:
                uuids = [u for u in self.mapped("uuid") if u]
                rewards = self.env["cz.loyalty.reward"].sudo().search(
                    [("used_order_uuid", "in", uuids), ("state", "=", "used")]) if uuids else self.env["cz.loyalty.reward"]
                for reward in rewards:
                    elsewhere = self.env["pos.order.line"].sudo().search_count([
                        ("cz_reward_token", "=", reward.token), ("order_id", "not in", self.ids),
                        ("order_id.state", "!=", "cancel")])
                    if not elsewhere:
                        reward.write({"state": "issued", "used_at": False, "used_config_id": False,
                                      "used_company_id": False, "used_order_uuid": False, "used_order_ref": False,
                                      "used_by_id": False, "used_order_id": False})
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
