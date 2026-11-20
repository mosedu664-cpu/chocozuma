# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.tools import normalize_phone


class CzLoyaltySimulate(models.TransientModel):
    _name = "cz.loyalty.simulate"
    _description = "Kakao Hazinesi: simulate an incoming WhatsApp message"

    phone = fields.Char(required=True, help="Must be in the test phones list when the mode is Test")
    pos_order_id = fields.Many2one("pos.order", string="Receipt", domain=[("cz_loyalty_code", "!=", False)],
                                   help="Pick a receipt to put its code in the message")
    text = fields.Char(string="Message")
    result = fields.Char(readonly=True)
    reply_text = fields.Text(string="Reply the guest would receive", readonly=True)

    @api.onchange("pos_order_id")
    def _onchange_order(self):
        if self.pos_order_id.cz_loyalty_code:
            self.text = f"Kakao Hazinesi ✦ ZUMA-{self.pos_order_id.cz_loyalty_code}"

    def action_run(self):
        self.ensure_one()
        phone = normalize_phone(self.phone)
        if not phone:
            raise UserError("Invalid phone number.")
        if not self.text:
            raise UserError("Write a message or pick a receipt.")
        rec = self.env["cz.loyalty.inbound"].sudo().create({
            "simulated": True, "mobile_raw": self.phone, "phone": phone, "body": self.text,
        })
        rec._process()
        self.write({"result": f"{rec.state} / {rec.result or '-'}", "reply_text": rec.reply_text or "(no reply)"})
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "new"}

    def action_assign_codes(self):
        """Staging helper: give a code to recent paid orders that have none (e.g. orders copied from production)."""
        from ..models.tools import new_order_code
        cfg = self.env["cz.loyalty.config"].get()
        orders = self.env["pos.order"].sudo().search([
            ("cz_loyalty_code", "=", False), ("state", "in", ("paid", "done", "invoiced")),
            ("config_id", "in", cfg.pos_config_ids.ids),
        ], order="id desc", limit=20)
        for o in orders:
            o.cz_loyalty_code = new_order_code()
        self.result = f"{len(orders)} receipts got a code"
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "new"}
