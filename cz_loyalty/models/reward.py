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
    state = fields.Selection(
        [("issued", "Ready"), ("used", "Used"), ("expired", "Expired"), ("cancelled", "Cancelled")],
        default="issued", required=True, index=True,
    )
    expires_at = fields.Datetime(required=True)
    used_at = fields.Datetime()
    used_order_id = fields.Many2one("pos.order", ondelete="set null")
    used_config_id = fields.Many2one("pos.config", string="Used in branch")
    used_company_id = fields.Many2one("res.company", string="Redeeming company")
    origin_ledger_ids = fields.One2many("cz.loyalty.ledger", "reward_id")

    _sql_constraints = [("token_uniq", "unique(token)", "Reward token must be unique.")]

    @api.model
    def _issue(self, member):
        cfg = self.env["cz.loyalty.config"].get()
        token = new_reward_token()
        while self.sudo().search_count([("token", "=", token)]):
            token = new_reward_token()
        reward = self.sudo().create({
            "member_id": member.id,
            "token": token,
            "expires_at": fields.Datetime.now() + timedelta(days=cfg.reward_valid_days),
        })
        self.env["cz.loyalty.ledger"].sudo().create({
            "member_id": member.id, "kind": "bowl", "beans": -cfg.visits_per_reward,
            "reward_id": reward.id, "note": "Bowl full",
        })
        return reward

    def action_mark_used_manual(self):
        """Back-office fallback (e.g. POS scan unavailable). Increment 2 does this from the POS."""
        for r in self:
            if r.state != "issued":
                raise UserError("Only a ready reward can be marked as used.")
            r.write({"state": "used", "used_at": fields.Datetime.now()})

    @api.model
    def _cron_expire(self):
        self.sudo().search([("state", "=", "issued"), ("expires_at", "<", fields.Datetime.now())]).write({"state": "expired"})
