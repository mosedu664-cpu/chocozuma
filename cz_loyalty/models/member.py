# -*- coding: utf-8 -*-
from odoo import api, fields, models


class CzLoyaltyMember(models.Model):
    _name = "cz.loyalty.member"
    _description = "Kakao Hazinesi member (one wallet per phone, all branches)"
    _order = "last_visit desc, id desc"
    _rec_name = "display_label"

    phone = fields.Char(required=True, index=True, help="Normalised +90XXXXXXXXXX")
    partner_id = fields.Many2one("res.partner", ondelete="restrict", index=True)
    name = fields.Char(string="First name")
    display_label = fields.Char(compute="_compute_display_label")
    ledger_ids = fields.One2many("cz.loyalty.ledger", "member_id")
    reward_ids = fields.One2many("cz.loyalty.reward", "member_id")
    beans = fields.Integer(compute="_compute_beans", store=True, help="Beans in the current bowl")
    total_visits = fields.Integer(compute="_compute_beans", store=True)
    rewards_issued = fields.Integer(compute="_compute_beans", store=True)
    first_visit = fields.Datetime()
    last_visit = fields.Datetime(index=True)
    awaiting_name = fields.Boolean(default=False)
    awaiting_consent = fields.Boolean(default=False)
    marketing_optin = fields.Boolean(string="Marketing consent")
    marketing_optin_date = fields.Datetime()
    blocked = fields.Boolean(help="Blocked members never earn (fraud review).")

    _sql_constraints = [("phone_uniq", "unique(phone)", "One wallet per phone number.")]

    @api.depends("name", "phone")
    def _compute_display_label(self):
        for m in self:
            m.display_label = f"{m.name or '—'} ({m.phone})"

    @api.depends("ledger_ids.beans", "ledger_ids.kind")
    def _compute_beans(self):
        target = self.env["cz.loyalty.config"].get().visits_per_reward or 5
        for m in self:
            earned = sum(m.ledger_ids.filtered(lambda l: l.kind in ("earn", "reverse", "manual", "migration")).mapped("beans"))
            spent = -sum(m.ledger_ids.filtered(lambda l: l.kind == "bowl").mapped("beans"))
            m.total_visits = len(m.ledger_ids.filtered(lambda l: l.kind == "earn"))
            m.rewards_issued = spent // target if target else 0
            m.beans = max(earned - spent, 0)

    @api.model
    def _find_or_create(self, phone):
        member = self.sudo().search([("phone", "=", phone)], limit=1)
        if member:
            return member, False
        Partner = self.env["res.partner"].sudo()
        partner = Partner.search([("phone_sanitized", "=", phone)], limit=1)
        if not partner:
            tail = phone[-10:]
            partner = Partner.search(["|", ("mobile", "like", tail), ("phone", "like", tail)], limit=1)
        if not partner:
            partner = Partner.create({"name": phone, "mobile": phone, "company_id": False})
        return self.sudo().create({"phone": phone, "partner_id": partner.id, "name": False if partner.name == phone else partner.name.split(" ")[0]}), True


class CzLoyaltyLedger(models.Model):
    _name = "cz.loyalty.ledger"
    _description = "Kakao Hazinesi bean movement"
    _order = "id desc"

    member_id = fields.Many2one("cz.loyalty.member", required=True, ondelete="cascade", index=True)
    kind = fields.Selection(
        [("earn", "Visit"), ("reverse", "Refund reversal"), ("bowl", "Bowl full (reward issued)"),
         ("manual", "Manual correction"), ("migration", "Migration")],
        required=True,
    )
    beans = fields.Integer(required=True)
    pos_order_id = fields.Many2one("pos.order", index=True, ondelete="set null")
    pos_config_id = fields.Many2one("pos.config", string="Branch")
    company_id = fields.Many2one("res.company", string="Issuing company", help="Company whose sale earned the bean")
    reward_id = fields.Many2one("cz.loyalty.reward")
    note = fields.Char()

    def init(self):
        # One earn line per receipt, enforced by the database (idempotency guarantee).
        self.env.cr.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS cz_loyalty_ledger_earn_once "
            "ON cz_loyalty_ledger (pos_order_id) WHERE kind = 'earn'"
        )
