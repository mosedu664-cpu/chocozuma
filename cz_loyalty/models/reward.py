# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from .tools import new_reward_token


class CzLoyaltyReward(models.Model):
    _name = "cz.loyalty.reward"
    _description = "Kakao Hazinesi reward (Zuma Sürprizi)"
    _order = "id desc"
    _rec_name = "token"

    member_id = fields.Many2one("cz.loyalty.member", required=True, ondelete="cascade", index=True)
    token = fields.Char(required=True, index=True, copy=False)
    kind = fields.Selection([("small", "Şefin İkramı"), ("big", "Hazine Tabağı")], required=True, default="small")
    cycle = fields.Integer(help="Member cycle number this gift belongs to")
    state = fields.Selection(
        [("issued", "Ready"), ("used", "Used"), ("expired", "Expired"), ("cancelled", "Cancelled")],
        default="issued", required=True, index=True,
    )
    expires_at = fields.Datetime(required=True)
    used_at = fields.Datetime()
    used_order_id = fields.Many2one("pos.order", ondelete="set null")
    used_order_uuid = fields.Char(index=True, help="POS order the gift was added to (known before the order is saved)")
    used_order_ref = fields.Char(string="Receipt")
    used_by_id = fields.Many2one("res.users", string="Redeemed by")
    used_config_id = fields.Many2one("pos.config", string="Used in branch")
    used_company_id = fields.Many2one("res.company", string="Redeeming company")
    origin_ledger_ids = fields.One2many("cz.loyalty.ledger", "reward_id")

    _sql_constraints = [("token_uniq", "unique(token)", "Reward token must be unique.")]

    @api.model
    def _issue(self, member, kind):
        cfg = self.env["cz.loyalty.config"].get()
        token = new_reward_token()
        while self.sudo().search_count([("token", "=", token)]):
            token = new_reward_token()
        reward = self.sudo().create({
            "member_id": member.id,
            "token": token,
            "kind": kind,
            "cycle": member.cycles_done,
            "expires_at": fields.Datetime.now() + timedelta(days=cfg.reward_valid_days),
        })
        if kind == "big":
            self.env["cz.loyalty.ledger"].sudo().create({
                "member_id": member.id, "kind": "bowl", "beans": -cfg.cycle_len,
                "reward_id": reward.id, "note": "Pouch full",
            })
        return reward

    # ------------------------------------------------------------------ POS
    @api.model
    def pos_redeem(self, token, config_id, order_uuid=False, order_ref=False):
        """Cashier scanned or typed a gift code. One call decides and books it; a code can be used once."""
        token = "".join(c for c in str(token or "") if c.isdigit())
        cfg = self.env["cz.loyalty.config"].get()
        config = self.env["pos.config"].sudo().browse(int(config_id)).exists()
        if cfg.mode == "off" or not config or config not in cfg.pos_config_ids:
            return {"ok": False, "message": "Kakao Hazinesi bu kasada açık değil."}
        if not token:
            return {"ok": False, "message": "Kod okunamadı."}
        self.env.cr.execute("SELECT id FROM cz_loyalty_reward WHERE token = %s FOR UPDATE", (token,))
        row = self.env.cr.fetchone()
        if not row:
            return {"ok": False, "message": "Bu kod bulunamadı. Rakamları misafirin mesajından kontrol edin."}
        reward = self.sudo().browse(row[0])
        gift = dict(self._fields["kind"].selection)[reward.kind]
        if reward.state == "used":
            if order_uuid and reward.used_order_uuid == order_uuid:
                return {"ok": False, "message": "%s bu siparişe zaten eklendi." % gift}
            when = fields.Datetime.context_timestamp(self.with_context(tz="Europe/Istanbul"), reward.used_at).strftime("%d.%m.%Y %H:%M") if reward.used_at else ""
            return {"ok": False, "message": "Bu ikram daha önce kullanılmış (%s, %s)." % (when, reward.used_config_id.name or "-")}
        if reward.state == "cancelled":
            return {"ok": False, "message": "Bu ikram iptal edilmiş."}
        if reward.state == "expired" or reward.expires_at < fields.Datetime.now():
            return {"ok": False, "message": "Bu ikramın süresi dolmuş."}
        product = cfg.reward_small_product_id if reward.kind == "small" else cfg.reward_big_product_id
        if not product:
            return {"ok": False, "message": "%s ürünü ayarlanmamış. Yöneticiye haber verin." % gift}
        reward.write({
            "state": "used", "used_at": fields.Datetime.now(), "used_config_id": config.id,
            "used_company_id": config.company_id.id, "used_order_uuid": order_uuid or False,
            "used_order_ref": order_ref or False, "used_by_id": self.env.uid,
        })
        return {"ok": True, "kind": reward.kind, "gift_name": gift, "product_id": product.id, "token": token}

    @api.model
    def pos_release(self, token, order_uuid):
        """The gift line was removed before payment: the code becomes usable again."""
        token = "".join(c for c in str(token or "") if c.isdigit())
        if not token or not order_uuid:
            return False
        reward = self.sudo().search([("token", "=", token), ("state", "=", "used"), ("used_order_uuid", "=", order_uuid)], limit=1)
        if not reward:
            return False
        order = self.env["pos.order"].sudo().search([("uuid", "=", order_uuid)], limit=1)
        if order and order.state in ("paid", "done", "invoiced"):
            return False
        reward.write({"state": "issued", "used_at": False, "used_config_id": False, "used_company_id": False,
                      "used_order_uuid": False, "used_order_ref": False, "used_by_id": False, "used_order_id": False})
        return True

    def action_mark_used_manual(self):
        """Back-office fallback (e.g. POS scan unavailable). Increment 2 does this from the POS."""
        for r in self:
            if r.state != "issued":
                raise UserError("Only a ready reward can be marked as used.")
            r.write({"state": "used", "used_at": fields.Datetime.now()})

    @api.model
    def _cron_expire(self):
        self.sudo().search([("state", "=", "issued"), ("expires_at", "<", fields.Datetime.now())]).write({"state": "expired"})
