# -*- coding: utf-8 -*-
import logging
from datetime import datetime, time, timedelta

import pytz
from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.tools import html2plaintext

from .tools import GIFT_NAMES, MESSAGES, bean_row, extract_code, fmt_token, keyword_intent, normalize_phone

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
        super().init()
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
        if member and intent == "code":
            return self._finish("code", self._codes_text(cfg, member), member)
        # Anything else is a normal conversation (e.g. a home order): leave it to the staff.
        self.write({"state": "ignored", "result": "conversation", "member_id": member.id or False})

    def _handle_code(self, cfg, code):
        Order = self.env["pos.order"].sudo()
        order = Order.search([("cz_loyalty_code", "=", code)], limit=1)
        age = fields.Datetime.now() - self.received_at
        window = timedelta(hours=cfg.code_valid_hours)
        if not order:
            # The order may still be syncing from the POS: look once more in 2 minutes, then give up.
            if self.state != "pending":
                return self._finish("pending_sync", False, state="pending",
                                    next_at=fields.Datetime.now() + timedelta(minutes=2))
            return self._finish("invalid", MESSAGES["invalid"])
        if order.state not in PAID_STATES:
            # Bill printed but not paid yet: tell the guest once, then wait until it is paid.
            if order.state == "cancel" or age >= window:
                return self._finish("invalid", MESSAGES["invalid"])
            if self.result != "pending":
                return self._finish("pending", MESSAGES["pending"], state="pending",
                                    next_at=fields.Datetime.now() + timedelta(minutes=PENDING_RETRY_MIN))
            self.next_attempt_at = fields.Datetime.now() + timedelta(minutes=PENDING_RETRY_MIN)
            return
        self.pos_order_id = order.id
        if order.config_id not in cfg.pos_config_ids:
            return self._finish("invalid", MESSAGES["invalid"])
        if self.received_at - order.date_order > window:
            return self._finish("expired", MESSAGES["expired"])
        if order.amount_total < cfg.min_order_amount:
            return self._finish("small_order", MESSAGES["small_order"])
        if self._is_refunded(order):
            return self._finish("refunded", MESSAGES["invalid"])
        Ledger = self.env["cz.loyalty.ledger"].sudo()
        if Ledger.search_count([("pos_order_id", "=", order.id), ("kind", "=", "earn")]):
            return self._finish("used", MESSAGES["used"])
        member, is_new = self.env["cz.loyalty.member"]._find_or_create(self.phone, self._profile_name())
        if member.blocked:
            return self._finish("blocked", False, member)
        skip_daily = cfg.mode == "test" and cfg.test_skip_daily_limit
        if not skip_daily and Ledger.search_count([
                ("member_id", "=", member.id), ("kind", "=", "earn"), ("create_date", ">=", self._local_day_start_utc())]):
            return self._finish("daily", MESSAGES["daily"], member)
        before = member.beans
        base = {"member_id": member.id, "pos_order_id": order.id, "pos_config_id": order.config_id.id,
                "company_id": order.company_id.id}
        Ledger.create(dict(base, kind="earn", beans=1))
        first_ever = is_new or not member.first_visit
        if first_ever and cfg.welcome_beans > 0:
            Ledger.create({"member_id": member.id, "kind": "welcome", "beans": cfg.welcome_beans, "note": "Hoş geldin tanesi"})
        now = fields.Datetime.now()
        member.write({"last_visit": now, "first_visit": member.first_visit or now})
        after = member.beans
        texts, result = [], "credited"
        if before < cfg.small_at <= after and after < cfg.cycle_len and not member.reward_ids.filtered(
                lambda r: r.kind == "small" and r.cycle == member.cycles_done and r.state != "cancelled"):
            reward = self.env["cz.loyalty.reward"]._issue(member, "small")
            texts.append(MESSAGES["gift_small"].format(token=fmt_token(reward.token), expiry=self._fmt_date(reward.expires_at)))
            result = "gift_small"
        elif after >= cfg.cycle_len:
            reward = self.env["cz.loyalty.reward"]._issue(member, "big")
            texts.append(MESSAGES["gift_big"].format(token=fmt_token(reward.token), expiry=self._fmt_date(reward.expires_at)))
            result = "gift_big"
        else:
            key = "welcome" if first_ever else "credit"
            texts.append(MESSAGES[key].format(name=(" " + member.name) if member.name else "", **self._progress(cfg, after)))
        if first_ever:
            member.awaiting_consent = True
            texts.append(MESSAGES["consent"].format(kvkk_url=cfg.kvkk_url or ""))
            result += "_new"
        return self._finish(result, texts, member)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _progress(cfg, beans):
        small = beans < cfg.small_at
        target = cfg.small_at if small else cfg.cycle_len
        return {"row": bean_row(beans, cfg.small_at, cfg.cycle_len), "gift": GIFT_NAMES["small" if small else "big"],
                "left": max(target - beans, 0), "beans": beans}

    def _balance_text(self, cfg, member):
        text = MESSAGES["balance"].format(**self._progress(cfg, member.beans))
        ready = member.reward_ids.filtered(lambda r: r.state == "issued")
        for r in ready:
            text += "\n" + MESSAGES["code_line"].format(gift=GIFT_NAMES[r.kind], token=fmt_token(r.token), expiry=self._fmt_date(r.expires_at))
        return text

    def _codes_text(self, cfg, member):
        ready = member.reward_ids.filtered(lambda r: r.state == "issued")
        if not ready:
            return MESSAGES["no_code"].format(**self._progress(cfg, member.beans))
        return "\n".join(MESSAGES["code_line"].format(gift=GIFT_NAMES[r.kind], token=fmt_token(r.token),
                                                      expiry=self._fmt_date(r.expires_at)) for r in ready)

    def _channel(self):
        msg = self.wa_message_id
        Channel = self.env["discuss.channel"].sudo()
        if not msg:
            return Channel
        mm = msg.mail_message_id
        if mm and mm.model == "discuss.channel":
            channel = Channel.browse(mm.res_id).exists()
            if channel:
                return channel
        return Channel.search([
            ("channel_type", "=", "whatsapp"),
            ("wa_account_id", "=", msg.wa_account_id.id),
            ("whatsapp_number", "=", msg.mobile_number),
        ], limit=1)

    def _profile_name(self):
        """First name from the guest's WhatsApp profile (Odoo stores it on the conversation's partner)."""
        try:
            channel = self._channel()
            return channel.whatsapp_partner_id.name if channel and "whatsapp_partner_id" in channel._fields else False
        except Exception:  # noqa: BLE001 — a missing name must never block a credit
            return False

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

    def _finish(self, result, texts, member=False, state="done", next_at=False):
        vals = {"result": result, "state": state, "error": False}
        if member:
            vals["member_id"] = member.id
        if next_at:
            vals["next_attempt_at"] = next_at
        self.write(vals)
        if isinstance(texts, str):
            texts = [texts]
        for text in texts or []:
            self._send_reply(text)

    def _send_reply(self, text):
        self.reply_text = (self.reply_text + "\n\n— — —\n\n" if self.reply_text else "") + text
        if self.simulated or not self.wa_message_id:
            return
        channel = self._channel()
        if not channel:
            raise RuntimeError("No WhatsApp conversation found for %s" % self.wa_message_id.mobile_number)
        body = Markup("<br/>").join(escape(line) for line in text.split("\n"))
        channel.message_post(body=body, message_type="whatsapp_message", subtype_xmlid="mail.mt_comment")
