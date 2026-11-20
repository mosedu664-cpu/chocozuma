# -*- coding: utf-8 -*-
import logging
from datetime import datetime, time, timedelta

import pytz
from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.tools import html2plaintext

from .tools import MESSAGES, extract_code, keyword_intent, normalize_phone

_logger = logging.getLogger(__name__)

TZ = pytz.timezone("Europe/Istanbul")
BACKOFF_MIN = [1, 5, 15, 60, 240]
PENDING_RETRY_MIN = 10
PAID_STATES = ("paid", "done", "invoiced")


class CzLoyaltyInbound(models.Model):
    _name = "cz.loyalty.inbound"
    _description = "Kakao Hazinesi inbound message queue"
    _order = "id desc"

    wa_message_id = fields.Many2one("whatsapp.message", ondelete="set null", index=True)
    msg_uid = fields.Char(index=True, help="Meta message id; Meta can deliver the same message twice")
    mobile_raw = fields.Char()
    phone = fields.Char(index=True)
    body = fields.Text()
    received_at = fields.Datetime(default=fields.Datetime.now, required=True)
    simulated = fields.Boolean(help="Created by the Simulate wizard: nothing is sent to WhatsApp")
    state = fields.Selection(
        [("queued", "Queued"), ("pending", "Waiting for receipt"), ("done", "Done"),
         ("ignored", "Ignored"), ("failed", "Retrying"), ("dead", "Failed — check")],
        default="queued", required=True, index=True,
    )
    result = fields.Char(help="Decision code: credited, reward, used, expired, invalid, daily, small, ...")
    member_id = fields.Many2one("cz.loyalty.member", ondelete="set null")
    pos_order_id = fields.Many2one("pos.order", ondelete="set null")
    reply_text = fields.Text()
    attempts = fields.Integer(default=0)
    next_attempt_at = fields.Datetime(default=fields.Datetime.now)
    error = fields.Text()

    def init(self):
        self.env.cr.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS cz_loyalty_inbound_msg_uid "
            "ON cz_loyalty_inbound (msg_uid) WHERE msg_uid IS NOT NULL"
        )

    # ------------------------------------------------------------------ enqueue
    @api.model
    def _enqueue(self, wa_messages):
        cfg = self.env["cz.loyalty.config"].get()
        if cfg.mode == "off":
            return False
        created = False
        for msg in wa_messages:
            if cfg.wa_account_ids and msg.wa_account_id not in cfg.wa_account_ids:
                continue
            if msg.msg_uid and self.search_count([("msg_uid", "=", msg.msg_uid)]):
                continue
            self.create({
                "wa_message_id": msg.id,
                "msg_uid": msg.msg_uid or False,
                "mobile_raw": msg.mobile_number,
                "phone": normalize_phone(msg.mobile_number),
                "body": html2plaintext(msg.body or "").strip(),
            })
            created = True
        return created

    # ------------------------------------------------------------------ cron
    @api.model
    def _cron_process(self, limit=50):
        self.env.cr.execute(
            """SELECT id FROM cz_loyalty_inbound
               WHERE state IN ('queued', 'pending', 'failed')
                 AND (next_attempt_at IS NULL OR next_attempt_at <= now() AT TIME ZONE 'UTC')
               ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED""",
            (limit,),
        )
        ids = [r[0] for r in self.env.cr.fetchall()]
        for rec in self.browse(ids):
            try:
                with self.env.cr.savepoint():
                    rec._process()
            except Exception as e:  # noqa: BLE001 — logged and retried, never lost
                _logger.exception("cz_loyalty: inbound %s failed", rec.id)
                rec._schedule_retry(str(e))
            self.env.cr.commit()

    def _schedule_retry(self, error):
        self.ensure_one()
        attempts = self.attempts + 1
        if attempts > len(BACKOFF_MIN):
            self.write({"state": "dead", "attempts": attempts, "error": error})
            return
        self.write({
            "state": "failed", "attempts": attempts, "error": error,
            "next_attempt_at": fields.Datetime.now() + timedelta(minutes=BACKOFF_MIN[attempts - 1]),
        })

    # ------------------------------------------------------------------ logic
    def _process(self):
        self.ensure_one()
        cfg = self.env["cz.loyalty.config"].get()
        if not cfg.is_allowed(self.phone):
            self.write({"state": "ignored", "result": "staff" if cfg.is_staff(self.phone) else "not_allowed"})
            return
        code = extract_code(self.body)
        if code:
            return self._handle_code(cfg, code)
        member = self.env["cz.loyalty.member"].sudo().search([("phone", "=", self.phone)], limit=1)
        intent = keyword_intent(self.body)
        if member and intent == "optin":
            member.write({"marketing_optin": True, "marketing_optin_date": fields.Datetime.now(), "awaiting_consent": False})
            return self._finish("optin", MESSAGES["optin"], member)
        if member and intent == "optout":
            member.write({"marketing_optin": False, "awaiting_consent": False})
            return self._finish("optout", MESSAGES["optout"], member)
        if member and intent == "balance":
            return self._finish("balance", self._balance_text(cfg, member), member)
        if member and member.awaiting_name and 0 < len(self.body) <= 40 and "\n" not in self.body:
            name = self.body.strip().split(" ")[0].capitalize()
            member.write({"name": name, "awaiting_name": False, "awaiting_consent": True})
            text = MESSAGES["name_thanks"].format(name=name, target=cfg.visits_per_reward)
            text += "\n\n" + MESSAGES["consent"].format(kvkk_url=cfg.kvkk_url)
            return self._finish("name", text, member)
        # Anything else is a normal conversation (e.g. a home order): leave it to the staff.
        self.write({"state": "ignored", "result": "conversation", "member_id": member.id or False})

    def _handle_code(self, cfg, code):
        Order = self.env["pos.order"].sudo()
        order = Order.search([("cz_loyalty_code", "=", code)], limit=1)
        age = fields.Datetime.now() - self.received_at
        window = timedelta(hours=cfg.code_valid_hours)
        if not order or order.state not in PAID_STATES:
            # The receipt may still be syncing from the POS: wait, then decide.
            if age < window and self.state != "pending":
                return self._finish("pending", MESSAGES["pending"], state="pending",
                                    next_at=fields.Datetime.now() + timedelta(minutes=PENDING_RETRY_MIN))
            if age < window:
                self.next_attempt_at = fields.Datetime.now() + timedelta(minutes=PENDING_RETRY_MIN)
                return
            return self._finish("invalid", MESSAGES["invalid"])
        self.pos_order_id = order.id
        if order.config_id not in cfg.pos_config_ids:
            return self._finish("invalid", MESSAGES["invalid"])
        if self.received_at - order.date_order > window:
            return self._finish("expired", MESSAGES["expired"])
        if order.amount_total < cfg.min_order_amount:
            return self._finish("small", MESSAGES["small"])
        if self._is_refunded(order):
            return self._finish("refunded", MESSAGES["invalid"])
        Ledger = self.env["cz.loyalty.ledger"].sudo()
        if Ledger.search_count([("pos_order_id", "=", order.id), ("kind", "=", "earn")]):
            return self._finish("used", MESSAGES["used"])
        member, is_new = self.env["cz.loyalty.member"]._find_or_create(self.phone)
        if member.blocked:
            return self._finish("blocked", False, member)
        start_utc = self._local_day_start_utc()
        if Ledger.search_count([("member_id", "=", member.id), ("kind", "=", "earn"), ("create_date", ">=", start_utc)]):
            return self._finish("daily", MESSAGES["daily"], member)
        Ledger.create({
            "member_id": member.id, "kind": "earn", "beans": 1, "pos_order_id": order.id,
            "pos_config_id": order.config_id.id, "company_id": order.company_id.id,
        })
        now = fields.Datetime.now()
        member.write({"last_visit": now, "first_visit": member.first_visit or now})
        member.invalidate_recordset(["beans"])
        target = cfg.visits_per_reward
        if member.beans >= target:
            reward = self.env["cz.loyalty.reward"]._issue(member)
            text = MESSAGES["reward"].format(name=member.name or "", token=reward.token, expiry=self._fmt_date(reward.expires_at))
            return self._finish("reward", text, member)
        if is_new:
            member.awaiting_name = True
            return self._finish("credited_new", MESSAGES["welcome"].format(beans=member.beans, target=target), member)
        return self._finish("credited", MESSAGES["credit"].format(beans=member.beans, target=target), member)

    # ------------------------------------------------------------------ helpers
    def _balance_text(self, cfg, member):
        text = MESSAGES["balance"].format(beans=member.beans, target=cfg.visits_per_reward)
        ready = member.reward_ids.filtered(lambda r: r.state == "issued")[:1]
        if ready:
            text += "\n" + MESSAGES["balance_reward"].format(token=ready.token, expiry=self._fmt_date(ready.expires_at))
        return text

    def _is_refunded(self, order):
        Line = self.env["pos.order.line"].sudo()
        if "refunded_orderline_id" not in Line._fields:
            return False
        return bool(Line.search_count([("refunded_orderline_id", "in", order.lines.ids)]))

    @staticmethod
    def _local_day_start_utc():
        local_now = datetime.now(TZ)
        start = TZ.localize(datetime.combine(local_now.date(), time(6, 0)))
        if local_now < start:  # business day runs 06:00 → 06:00 (late-night tables)
            start -= timedelta(days=1)
        return start.astimezone(pytz.utc).replace(tzinfo=None)

    @staticmethod
    def _fmt_date(dt):
        return pytz.utc.localize(dt).astimezone(TZ).strftime("%d.%m.%Y") if dt else ""

    def _finish(self, result, text, member=False, state="done", next_at=False):
        vals = {"result": result, "state": state, "error": False}
        if member:
            vals["member_id"] = member.id
        if next_at:
            vals["next_attempt_at"] = next_at
        self.write(vals)
        if text:
            self._send_reply(text)

    def _send_reply(self, text):
        self.reply_text = text
        if self.simulated or not self.wa_message_id:
            return
        msg = self.wa_message_id
        Channel = self.env["discuss.channel"].sudo()
        channel = Channel
        mm = msg.mail_message_id
        if mm and mm.model == "discuss.channel":
            channel = Channel.browse(mm.res_id).exists()
        if not channel:
            channel = Channel.search([
                ("channel_type", "=", "whatsapp"),
                ("wa_account_id", "=", msg.wa_account_id.id),
                ("whatsapp_number", "=", msg.mobile_number),
            ], limit=1)
        if not channel:
            raise RuntimeError("No WhatsApp conversation found for %s" % msg.mobile_number)
        body = Markup("<br/>").join(escape(line) for line in text.split("\n"))
        channel.message_post(body=body, message_type="whatsapp_message", subtype_xmlid="mail.mt_comment")
