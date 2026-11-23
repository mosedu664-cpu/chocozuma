# -*- coding: utf-8 -*-
import re
from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from . import branch_render, brief_render, kitchen_render, marketing_data, marketing_render, orders_render, workcard_render

PAID = ("paid", "done", "invoiced")
PLATFORM_RE = re.compile(r"trendyol|yemek|getir", re.I)
STAFF_RE = re.compile(r"personel", re.I)
# platform orders created by cz_platform_orders have no table: the channel comes from the generic partner
# ("*TRENDYOL", "!TRENDYOL YEMEK", "*YEMEKSEPETI", "!YEMEK SEPETİ", "*GETİR")
PLATFORM_PARTNERS = (("trendyol", "Trendyol Go"), ("sepet", "Yemeksepeti"), ("getir", "Getir"), ("migros", "Migros Yemek"))


def platform_of(partner_name):
    """Platform channel of a generic platform customer (name starting with * or !), else None."""
    name = (partner_name or "").strip()
    if name[:1] not in ("*", "!"):
        return None
    key = re.sub(r"[^a-z]", "", name.casefold().replace("i̇", "i").replace("ı", "i"))
    for word, channel in PLATFORM_PARTNERS:
        if word in key:
            return channel
    return None


TZ = pytz.timezone("Europe/Istanbul")
CHANNELS = {
    "salon": "Salon", "teras": "Teras", "whatsapp": "WhatsApp", "yemeksepeti": "Yemeksepeti",
    "trendyolgo": "Trendyol Go", "trendyol": "Trendyol Go", "getir": "Getir", "migrosyemek": "Migros Yemek",
    "personel": "STAFF", "pazarlama": "MKT",
}
MK_BODY = (
    "Merhaba, Choco Zuma pazarlama raporu hazır: {{1}} iş günü.\n"
    "Kayaşehir ve Metrokent toplam net satış {{2}} TL, {{3}} sipariş.\n"
    "Günlük, haftalık, aylık ayrıntılar ve müşteri bilgileri ekteki PDF dosyasında."
)
OR_BODY = (
    "Merhaba, Choco Zuma dünkü siparişler raporu: {{1}}.\n"
    "Özet: {{2}}.\n"
    "Toplam {{3}} kalemin müşteri müşteri ayrıntısı ekteki PDF dosyasında."
)
BR_BODY = (
    "Merhaba, Choco Zuma şube raporu hazır: {{1}}.\n"
    "Net satış: {{2}}.\n"
    "Bugün yapılacaklar: {{3}}. Ayrıntılar ekteki tek sayfada."
)
KS_BODY = (
    "Günaydın, mutfak için bugünün işi hazır: {{1}}.\n"
    "Bugün: {{2}}.\n"
    "Üretilecekler, gönderilecekler ve {{3}} hazır ürünün mutfak ve depo stoğu ekteki tek sayfada."
)


class CzWaReport(models.Model):
    _name = "cz.wa.report"
    _description = "Choco Zuma WhatsApp report"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Selection(
        [("ceo_daily", "CEO Daily Brief"), ("marketing", "Marketing Report (TR)"),
         ("kitchen_stock", "Mutfak & Depo Stok Raporu (TR)"),
         ("orders_daily", "Dünkü Siparişler (TR)"),
         ("branch_daily", "Şube Raporu (TR)")], required=True, default="ceo_daily")
    targets_text = fields.Char(
        string="Monthly targets (TL)", default="6:4300000, 13:2200000",
        help="Branch report: monthly net sales target per POS, as pos_config_id:amount separated by commas.")
    ikram_cap_pct = fields.Float(
        string="İkram cap (% of net, at cost)", default=2.5,
        help="Branch report: daily ikram cost above this share of net sales is flagged (plan: 2.5 → 2.0 → 1.5 → 1.0).")
    warehouse_ids = fields.Many2many("stock.warehouse", string="Warehouses",
                                     help="Yesterday's orders report: sale orders of these warehouses.")
    show_prices = fields.Boolean("Show amounts", help="Yesterday's orders report: amounts and invoice status (accounting).")
    kitchen_only = fields.Boolean(
        "Kitchen lines only", help="Yesterday's orders report: keep only the lines delivered from the Central Kitchen "
        "(kitchen products, also when the order was entered on another warehouse); dropship and other warehouses' lines are left out.")
    setup_key = fields.Char(readonly=True, copy=False)
    send_hour = fields.Float(
        string="Send at (Istanbul)", default=7.5,
        help="Kitchen stock report: sent once a day at or after this hour (7.5 = 07:30).")
    report_day = fields.Date(
        string="Report day (test)", help="Leave empty: the last business day whose sessions are closed. "
        "Only used by Preview and PDF; scheduled sending always uses the last closed day.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    config_ids = fields.Many2many("pos.config", string="Branches (POS)")
    partner_ids = fields.Many2many("res.partner", string="Recipients")
    cost_days = fields.Integer(string="Invoice window (days)", default=90)
    cancel_alert_amount = fields.Float(string="Single cancel alert (TL)", default=2000.0)
    cashier_share_alert = fields.Float(string="One-cashier share alert (%)", default=80.0)
    phone_numbers = fields.Char(
        string="WhatsApp numbers", default="+905444436338",
        help="International format, separated by commas. Added to the mobiles of the recipients.")
    wa_template_id = fields.Many2one("whatsapp.template", string="WhatsApp template", readonly=True, copy=False)
    wa_template_status = fields.Selection(related="wa_template_id.status", string="Template status")
    preview_text = fields.Text(readonly=True)
    preview_date = fields.Datetime(readonly=True)
    log_ids = fields.One2many("cz.wa.report.log", "report_id")

    # ------------------------------------------------------------------ data
    def _day_orders(self, config, day):
        """All orders of one branch whose creation falls in the business day (06:00 -> 06:00 Istanbul)."""
        return self.env["pos.order"].search([
            ("config_id", "=", config.id),
            ("create_date", ">=", self._utc(day)), ("create_date", "<", self._utc(day + timedelta(days=1))),
        ])

    def _session_stats(self, config, day, costs):
        """KPIs of one branch for one business day, over every session of that day.
        (A night with several short sessions, e.g. test sessions after closing, must not replace the real day.)"""
        Order = self.env["pos.order"]
        orders = self._day_orders(config, day)
        sessions = self.env["pos.session"].search([
            ("config_id", "=", config.id), ("state", "=", "closed"),
            ("stop_at", ">=", self._utc(day)), ("stop_at", "<", self._utc(day + timedelta(days=1))),
        ])
        paid = orders.filtered(lambda o: o.state in PAID)
        cancelled = orders.filtered(lambda o: o.state == "cancel")
        has_table = "table_id" in Order._fields
        has_emp = "employee_id" in Order._fields
        has_reason = "cancel_reason_code" in Order._fields

        def floor_name(order):
            if has_table and order.table_id:
                return (order.table_id.floor_id.name or order.table_id.display_name or "").strip()
            return platform_of(order.partner_id.name) or ""

        staff_orders = paid.filtered(lambda o: STAFF_RE.search(floor_name(o)))
        sales = paid - staff_orders
        used = paid.mapped("session_id")
        # cash: only the sessions that sold that day (empty test sessions opened after closing are left out);
        # a session closed with 0 counted while cash was expected was not counted, which is not a shortage
        real_sessions = sessions & used
        uncounted = real_sessions.filtered(
            lambda s: not s.cash_register_balance_end_real and (s.cash_register_balance_end or 0.0) > 0)
        res = {
            "branch": config.name,
            "session": ", ".join(used.sorted("id").mapped("name")) or ", ".join(sessions.mapped("name")),
            "orders": len(paid),
            "net": sum(paid.mapped("amount_total")) - sum(paid.mapped("amount_tax")),
            "gross": sum(paid.mapped("amount_total")),
            "cash_diff": sum((real_sessions - uncounted).mapped("cash_register_difference")),
            "cash_uncounted": sum(uncounted.mapped("cash_register_balance_end")),
        }
        # channels
        channels = {}
        channel_label = {"MKT": "Pazarlama", "ERR": "Hatalı sipariş"}
        for o in sales:
            name = self._channel(floor_name(o))
            name = channel_label.get(name, name)
            row = channels.setdefault(name, [0, 0.0])
            row[0] += 1
            row[1] += o.amount_total - o.amount_tax
        res["channels"] = sorted(channels.items(), key=lambda kv: -kv[1][1])
        res["sales_net"] = sum(v[1] for v in channels.values())
        res["platform_net"] = sum(v[1] for k, v in channels.items() if PLATFORM_RE.search(k))
        # cashiers
        cashiers = {}
        if has_emp:
            for o in paid:
                row = cashiers.setdefault(o.employee_id.name or "-", [0, 0.0, 0])
                row[0] += 1
                row[1] += o.amount_total - o.amount_tax
            for o in cancelled:
                cashiers.setdefault(o.employee_id.name or "-", [0, 0.0, 0])[2] += 1
        res["cashiers"] = sorted(cashiers.items(), key=lambda kv: -kv[1][1])
        # cancels / refunds
        res["cancel_n"] = len(cancelled)
        res["cancel_value"] = sum(cancelled.mapped("amount_total"))
        res["cancel_no_reason"] = len(cancelled.filtered(lambda o: not o.cancel_reason_code)) if has_reason else 0
        res["cancel_max"] = max(cancelled.mapped("amount_total") or [0.0])
        refunds = paid.filtered(lambda o: o.amount_total < 0)
        res["refund_n"] = len(refunds)
        res["refund_value"] = -sum(refunds.mapped("amount_total"))
        amounts = [round(-o.amount_total, 2) for o in refunds]
        res["refund_dupes"] = sorted({a for a in amounts if amounts.count(a) > 1})
        # lines: real margin, discounts, staff meals
        Line = self.env["pos.order.line"]
        has_reward = "is_reward_line" in Line._fields
        cov = real = disc = reward = staff_value = 0.0
        staff_items = 0
        staff_ids = set(staff_orders.ids)
        products = {}
        has_combo = "combo_parent_id" in Line._fields
        combo_extra = []  # cost of the items given inside a box at price 0 (chocolates of Share Box, Aztec Box)
        for line in Line.search([("order_id", "in", paid.ids)]):
            if line.order_id.id in staff_ids:
                staff_items += 1
                staff_value += line.product_id.lst_price * line.qty
                continue
            if has_reward and line.is_reward_line:
                reward += -line.price_subtotal
                continue
            if line.price_subtotal < 0 and line.qty > 0:
                disc += -line.price_subtotal
                continue
            c = (costs.get(line.product_id.id) or {}).get("cost")
            if not line.price_subtotal:
                if has_combo and line.combo_parent_id and c is not None and line.qty > 0:
                    combo_extra.append((marketing_data.clean_name(line.combo_parent_id.product_id.name or ""), c * line.qty))
                continue
            # one row per menu item: "Zuma Roll", "Zuma Roll (P)", "Zuma Roll (P O)", "Zuma Roll (T)" together
            pname = marketing_data.clean_name(line.product_id.name or "")
            row = products.setdefault(pname, [pname, 0.0, 0.0, 0.0, 0.0])
            row[1] += line.qty
            row[2] += line.price_subtotal
            if c is not None and line.price_subtotal > 0 and c * line.qty <= line.price_subtotal * 3:
                real += c * line.qty
                cov += line.price_subtotal
                row[3] += line.price_subtotal
                row[4] += c * line.qty
        for name, value in combo_extra:
            row = products.get(name)
            if row and row[3] > 0:  # the box itself is costed: add what was given inside it
                row[4] += value
                real += value
        top = sorted(products.values(), key=lambda r: -r[2])[:5]
        res["top"] = [
            (r[0], r[1], r[2], ((r[3] - r[4]) / r[3] * 100.0) if r[3] and r[3] >= r[2] * 0.5 else None)
            for r in top if r[2] > 0
        ]
        res.update(
            covered_net=cov, real_cost=real,
            real_margin=((cov - real) / cov * 100.0) if cov else None,
            discount=disc, reward=reward,
            staff_orders=len(staff_orders), staff_items=staff_items, staff_value=staff_value,
        )
        return res

    def _last_sessions(self, config, count=2):
        return self.env["pos.session"].search(
            [("config_id", "=", config.id), ("state", "=", "closed")], order="stop_at desc", limit=count
        )

    def _ceo_brief_data(self, fresh_since=None):
        """fresh_since: ignore branches whose last closed session is older (scheduled run)."""
        self.ensure_one()
        companies = self.env["res.company"].sudo().search([])
        self = self.sudo().with_context(allowed_company_ids=companies.ids)
        if not self.config_ids:
            raise UserError(_("Choose at least one POS branch on the report."))
        costs = self.env["cz.real.cost"].compute(days=self.cost_days or 90)
        branches = []
        skipped = []
        for config in self.config_ids:
            sessions = self._last_sessions(config)
            if not sessions:
                continue
            if fresh_since and sessions[0].stop_at and sessions[0].stop_at < fresh_since:
                skipped.append(config.name)
                continue
            day = self._business_day(sessions[0].stop_at)
            cur = self._session_stats(config, day, costs)
            cur["stop_at"] = sessions[0].stop_at
            prev_orders = self._day_orders(config, day - timedelta(days=1)).filtered(lambda o: o.state in PAID)
            cur["prev_net"] = sum(prev_orders.mapped("amount_total")) - sum(prev_orders.mapped("amount_tax"))
            branches.append(cur)
        return {"branches": branches, "skipped": skipped}

    # ------------------------------------------------------- marketing data
    @staticmethod
    def _channel(floor_name):
        key = re.sub(r"\s+", "", floor_name or "").lower()
        if not key:
            return "Tezgah"
        if key.startswith("hatal"):
            return "ERR"
        return CHANNELS.get(key, (floor_name or "").strip().title())

    @staticmethod
    def _utc(day, hour=6):
        local = TZ.localize(datetime.combine(day, time(hour)))
        return local.astimezone(pytz.utc).replace(tzinfo=None)

    @staticmethod
    def _local(dt):
        return pytz.utc.localize(dt).astimezone(TZ).replace(tzinfo=None)

    def _business_day(self, dt):
        return (self._local(dt) - timedelta(hours=6)).date()

    def _marketing_orders(self, config, start, end):
        """Orders of one branch between two business days (dates, inclusive), reduced for marketing_data."""
        env = self.env
        orders = env["pos.order"].search_read(
            [("config_id", "=", config.id), ("state", "in", PAID),
             ("create_date", ">=", self._utc(start)), ("create_date", "<", self._utc(end + timedelta(days=1)))],
            ["create_date", "amount_total", "amount_tax", "table_id", "partner_id"])
        tables = env["restaurant.table"].with_context(active_test=False).browse(
            list({o["table_id"][0] for o in orders if o["table_id"]}))
        floor = {t.id: (t.floor_id.name or "") for t in tables}
        partners = env["res.partner"].with_context(active_test=False).browse(
            list({o["partner_id"][0] for o in orders if o["partner_id"]}))
        generic = {p.id for p in partners if (p.name or "").strip()[:1] in ("*", "!")}
        pname = {p.id: p.name or "" for p in partners}
        Line = env["pos.order.line"]
        line_fields = ["order_id", "product_id", "qty", "price_subtotal", "price_unit"]
        if "is_reward_line" in Line._fields:
            line_fields += ["is_reward_line", "reward_id"]
        lines = Line.search_read([("order_id", "in", [o["id"] for o in orders])], line_fields)
        # product names: the English names are the official menu names since the 22.11.2026 POS redesign
        products = env["product.product"].with_context(active_test=False, lang="en_US").browse(list({l["product_id"][0] for l in lines if l["product_id"]}))
        pinfo = {}
        for p in products:
            # families are read from the English category names (the Turkish translations differ)
            cats = [c.name or "" for c in p.with_context(lang="en_US").pos_categ_ids] if "pos_categ_ids" in p._fields else []
            name = marketing_data.clean_name(p.name)
            pinfo[p.id] = (name, marketing_data.family(name, cats), marketing_data.is_extra(name, cats))
        rewards = {}
        if "is_reward_line" in Line._fields:
            rw = env["loyalty.reward"].with_context(active_test=False).browse(list({l["reward_id"][0] for l in lines if l.get("reward_id")}))
            rewards = {r.id: (r.program_id.name or r.description or "") for r in rw}
        out = {}
        for o in orders:
            local = self._local(o["create_date"])
            channel = self._channel(floor.get(o["table_id"][0]) if o["table_id"] else "")
            partner = o["partner_id"][0] if o["partner_id"] else 0
            platform = platform_of(pname.get(partner))
            if platform and channel not in ("STAFF", "MKT", "ERR"):
                channel = platform
            out[o["id"]] = {
                "day": (local - timedelta(hours=6)).date().isoformat(),
                "hour": local.hour + (24 if local.hour < 6 else 0),
                "ch": channel,
                "net": o["amount_total"] - o["amount_tax"],
                "tot": o["amount_total"],
                "partner": 0 if partner in generic else partner,
                "lines": [],
            }
        mk_lines = [l["id"] for l in lines if out[l["order_id"][0]]["ch"] == "MKT"]
        list_value = {}
        for line in Line.browse(mk_lines):
            taxes = line.tax_ids_after_fiscal_position
            total = line.price_unit * line.qty
            if taxes:
                total = taxes.compute_all(line.price_unit, line.order_id.currency_id, line.qty, product=line.product_id)["total_excluded"]
            list_value[line.id] = total
        for l in lines:
            name, fam, extra = pinfo.get(l["product_id"][0] if l["product_id"] else 0, ("", "Diğer", False))
            out[l["order_id"][0]]["lines"].append({
                "name": name, "fam": fam, "extra": extra, "qty": l["qty"], "sub": l["price_subtotal"],
                "reward": bool(l.get("is_reward_line")),
                "program": rewards.get(l["reward_id"][0], "") if l.get("reward_id") else "",
                "list": list_value.get(l["id"], 0.0),
            })
        return list(out.values())

    def _first_days(self, partner_ids):
        """Business day of each customer's first ever paid order (all branches)."""
        if not partner_ids:
            return {}
        groups = self.env["pos.order"]._read_group(
            [("partner_id", "in", list(partner_ids)), ("state", "in", PAID)], ["partner_id"], ["create_date:min"])
        return {p.id: self._business_day(first).isoformat() for p, first in groups if first}

    def _marketing_last_day(self, fresh_since=None):
        """(business day, skipped branch names) from the last closed sessions of the branches."""
        stops, skipped = [], []
        for config in self.config_ids:
            sessions = self._last_sessions(config, count=1)
            if not sessions or (fresh_since and sessions.stop_at and sessions.stop_at < fresh_since):
                skipped.append(config.name)
                continue
            stops.append(sessions.stop_at)
        return (self._business_day(max(stops)) if stops else None), skipped

    def _marketing_data(self, day=None):
        self.ensure_one()
        companies = self.env["res.company"].sudo().search([])
        self = self.sudo().with_context(allowed_company_ids=companies.ids)
        if not self.config_ids:
            raise UserError(_("Choose the POS branches on the report."))
        if not day:
            day = self.report_day or self._marketing_last_day()[0]
        if not day:
            raise UserError(_("No closed POS session found."))
        D = day.isoformat()
        start = marketing_data.window_start(D)
        branches, partners = {}, set()
        for i, config in enumerate(self.config_ids.sorted("id")):
            orders = self._marketing_orders(config, start, day)
            partners |= {o["partner"] for o in orders if o["partner"] and o["ch"] == "WhatsApp"}
            name = (config.name or "").replace("Choco Zuma", "").strip()
            name = name[:1].upper() + name[1:] if name else config.display_name
            branches["%02d" % i] = {"name": name, "orders": orders}
        first = self._first_days(partners)
        for b in branches.values():
            b["first_day"] = first
        return marketing_data.build(D, branches)

    def get_marketing_data(self, day=None):
        """JSON of the marketing view-model (used to cross-check the report from the browser)."""
        self.ensure_one()
        if not self.env.user.has_group("base.group_system"):
            raise UserError(_("Only administrators."))
        return self._marketing_data(fields.Date.to_date(day) if day else None)

    def _marketing_text(self, data):
        d = data["D"]
        lines = ["Choco Zuma · Pazarlama Raporu · %s" % ".".join(reversed(d.split("-")))]
        for b in [data["br"][k] for k in sorted(data["br"])]:
            day = b["day"]
            pct = brief_render.pct_change(day["net"], b["avg4"][0])[0] if b["avg4"][2] else "-"
            lines.append("%s: net %s TL, %s sipariş, 4 hafta ortalamasına göre %s" % (
                b["name"], marketing_render.num(day["net"]), day["n"], pct))
        return "\n".join(lines)

    def _payload(self, data=None):
        """What one send needs: business day text, totals for the template and the PDF html."""
        self.ensure_one()
        if self.code == "branch_daily":
            bd = data or self._branch_data()
            return {
                "day": branch_render.day_txt(bd["day"]),
                "net_text": branch_render.summary(bd),
                "orders_text": branch_render.actions_count(bd),
                "html": branch_render.render_html(bd),
            }
        if self.code == "orders_daily":
            od = data or self._orders_data()
            return {
                "day": od["day_txt"],
                "net_text": orders_render.summary(od),
                "orders_text": str(sum(len(o["lines"]) for o in od["orders"])),
                "html": orders_render.render_html(od),
            }
        if self.code == "kitchen_stock":
            snap = data or self._kitchen_snapshot()
            return {
                "day": snap["as_of"][:10],
                "net_text": workcard_render.summary(snap) if snap.get("orders") else kitchen_render.summary(snap),
                "orders_text": str(len(workcard_render._simple(snap)[3]) if snap.get("orders") else len(snap["rows"])),
                "html": workcard_render.render_html(snap) if snap.get("orders") else kitchen_render.render_html(snap),
            }
        if self.code == "marketing":
            data = data or self._marketing_data()
            total = sum(b["day"]["net"] for b in data["br"].values())
            orders = sum(b["day"]["n"] for b in data["br"].values())
            return {
                "day": ".".join(reversed(data["D"].split("-"))),
                "net_text": marketing_render.num(total),
                "orders_text": str(orders),
                "html": marketing_render.render_html(data),
            }
        if not data["branches"]:
            raise UserError(_("No closed POS session found."))
        vm = self._ceo_brief_vm(data)
        return {
            "day": vm["date"], "net_text": brief_render.money(vm["net"]), "orders_text": str(vm["orders"]),
            "html": brief_render.render_html(vm),
        }

    # ---------------------------------------------------------- branch report
    def _branch_targets(self):
        out = {}
        for part in re.split(r"[,;\n]", self.targets_text or ""):
            if ":" not in part:
                continue
            key, val = part.split(":", 1)
            try:
                out[int(key.strip())] = float(re.sub(r"[^\d.]", "", val) or 0)
            except ValueError:
                continue
        return out

    def _daily_net(self, config, start, end):
        """{business day: net of paid orders} for one branch, days start..end inclusive."""
        rows = self.env["pos.order"].search_read([
            ("config_id", "=", config.id), ("state", "in", PAID),
            ("create_date", ">=", self._utc(start)), ("create_date", "<", self._utc(end + timedelta(days=1))),
        ], ["create_date", "amount_total", "amount_tax"])
        out = {}
        for r in rows:
            d = self._business_day(r["create_date"])
            out[d] = out.get(d, 0.0) + r["amount_total"] - r["amount_tax"]
        return out

    def _hour_counts(self, config, day):
        """{local hour (+24 before 06:00): sales orders} (staff floor left out)."""
        out = {}
        for o in self._day_orders(config, day).filtered(lambda o: o.state in PAID and o.amount_total > 0):
            if o.table_id and STAFF_RE.search(o.table_id.floor_id.name or ""):
                continue
            local = self._local(o.create_date)
            hr = local.hour + (24 if local.hour < 6 else 0)
            out[hr] = out.get(hr, 0) + 1
        return out

    def _branch_one(self, config, day, costs, targets):
        st = self._session_stats(config, day, costs)
        Line = self.env["pos.order.line"]
        orders = self._day_orders(config, day)
        paid = orders.filtered(lambda o: o.state in PAID)
        has_code = "discount_reason_code" in Line._fields
        has_reward = "is_reward_line" in Line._fields
        has_combo = "combo_parent_id" in Line._fields
        # discounts by reason, ikram at cost
        reasons, no_reason = {}, []
        order_cost, order_gross, ikram_disc = {}, {}, {}
        ikram_items_cost = 0.0
        for line in Line.search([("order_id", "in", paid.ids)]):
            if has_reward and line.is_reward_line:
                continue
            code = (line.discount_reason_code or "") if has_code else ""
            o = line.order_id
            value = 0.0
            if line.price_subtotal < 0 and line.qty > 0:  # discount product line
                value = -line.price_subtotal
            elif line.discount and line.price_subtotal > 0 and line.discount < 100:  # % discount on the line
                value = line.price_subtotal / (1 - line.discount / 100.0) * line.discount / 100.0
            elif line.discount >= 100 and line.qty > 0:  # 100% discount: value at the line's list price
                value = abs(line.price_unit * line.qty) / 1.1
            if value:
                row = reasons.setdefault(code, [0.0, 0])
                row[0] += value
                row[1] += 1
                if not code:
                    no_reason.append((o.name or o.pos_reference or "", o.employee_id.name if "employee_id" in o._fields else "", value))
                if code == "IKRAM":
                    ikram_disc[o.id] = ikram_disc.get(o.id, 0.0) + value
            c = (costs.get(line.product_id.id) or {}).get("cost")
            if line.price_subtotal > 0 and c is not None:
                order_cost[o.id] = order_cost.get(o.id, 0.0) + c * line.qty
                order_gross[o.id] = order_gross.get(o.id, 0.0) + line.price_subtotal / (1 - min(line.discount, 99.0) / 100.0)
            elif not line.price_subtotal and line.qty > 0 and c is not None and not (has_combo and line.combo_parent_id):
                name = (line.product_id.name or "").lower()
                cats = " ".join(line.product_id.pos_categ_ids.mapped("name")).lower() if "pos_categ_ids" in line.product_id._fields else ""
                if "ikram" in name or "complimentary" in name or "ikram" in cats:
                    ikram_items_cost += c * line.qty
        ratio = (sum(order_cost.values()) / sum(order_gross.values())) if sum(order_gross.values()) else 0.3
        ikram_cost = ikram_items_cost + sum(
            v * ((order_cost.get(oid, 0.0) / order_gross[oid]) if order_gross.get(oid) else ratio) for oid, v in ikram_disc.items())
        # open orders left at closing, cancels without a reason
        drafts = orders.filtered(lambda o: o.state == "draft" and o.amount_total > 0)
        has_reason = "cancel_reason_code" in orders._fields
        cancels_nr = orders.filtered(lambda o: o.state == "cancel" and has_reason and not o.cancel_reason_code)
        # target and month pace
        month_start = day.replace(day=1)
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        hist = self._daily_net(config, min(day - timedelta(days=56), month_start), day)
        wd = {}
        for d, v in hist.items():
            if day - timedelta(days=56) <= d < day and v > 0:
                wd.setdefault(d.weekday(), []).append(v)
        avg_wd = {k: sum(v) / len(v) for k, v in wd.items()}
        month_days = [month_start + timedelta(days=i) for i in range((month_end - month_start).days + 1)]
        T = targets.get(config.id) or 0.0
        denom = sum(avg_wd.get(d.weekday(), 0.0) for d in month_days)

        def tday(d):
            return T * avg_wd.get(d.weekday(), 0.0) / denom if (T and denom) else 0.0

        mtd = sum(v for d, v in hist.items() if month_start <= d <= day)
        mtd_target = sum(tday(d) for d in month_days if d <= day)
        left = [d for d in month_days if d > day]
        last28 = [hist.get(day - timedelta(days=i), 0.0) for i in range(28)]
        same = [hist[day - timedelta(days=7 * k)] for k in range(1, 5) if hist.get(day - timedelta(days=7 * k))]
        # load by hour against the same weekday of the last 4 weeks
        hours_now = self._hour_counts(config, day)
        base = {}
        for k in range(1, 5):
            for hr, n in self._hour_counts(config, day - timedelta(days=7 * k)).items():
                base[hr] = base.get(hr, 0) + n / 4.0
        span = sorted(set(hours_now) | {hr for hr, v in base.items() if v >= 0.5})
        hours = [(hr, hours_now.get(hr, 0), base.get(hr, 0.0)) for hr in range(span[0], span[-1] + 1)] if span else []
        net = st["net"]
        sales_net = st.get("sales_net") or 0.0
        name = (config.name or "").replace("Choco Zuma", "").strip()
        b = {
            "name": config.name, "short": (name[:1].upper() + name[1:]) if name else config.name,
            "net": net, "orders": st["orders"], "basket": (sales_net / max(1, st["orders"] - st["staff_orders"])) if st["orders"] else 0.0,
            "sales_net": sales_net,
            "lw": hist.get(day - timedelta(days=7), 0.0), "avg4": (sum(same) / len(same)) if same else 0.0,
            "target_day": tday(day), "target_pct": (net / tday(day) * 100.0) if tday(day) else None,
            "next_target": tday(day + timedelta(days=1)),
            "month_target": T, "mtd": mtd, "mtd_days": (day - month_start).days + 1,
            "mtd_pct": (mtd / T * 100.0) if T else 0.0, "mtd_expected_pct": (mtd_target / T * 100.0) if T else 0.0,
            "days_left": len(left), "need_per_day": ((T - mtd) / len(left)) if (T and left) else 0.0,
            "avg_daily": sum(last28) / 28.0,
            "discounts": sorted(((k, v[0], v[1]) for k, v in reasons.items()), key=lambda r: -r[1]),
            "discount_total": sum(v[0] for v in reasons.values()),
            "no_reason": sorted(no_reason, key=lambda r: -r[2]),
            "ikram_cost": ikram_cost, "ikram_cap_pct": self.ikram_cap_pct or 0.0,
            "ikram_cap": (self.ikram_cap_pct or 0.0) / 100.0 * max(net, 0.0),
            "staff_orders": st["staff_orders"], "staff_value": st["staff_value"],
            "cancel_n": st["cancel_n"], "cancel_value": st["cancel_value"], "cancel_no_reason": st["cancel_no_reason"],
            "cancels_nr": [(o.name or o.pos_reference or "/", o.employee_id.name if "employee_id" in o._fields else "", o.amount_total)
                           for o in cancels_nr.sorted(lambda o: -o.amount_total)],
            "open_n": len(drafts), "open_value": sum(drafts.mapped("amount_total")),
            "channels": [(k, v[0], v[1]) for k, v in st["channels"]],
            "hours": hours, "top": st["top"],
        }
        b["discount_pct"] = (b["discount_total"] / net * 100.0) if net else 0.0
        b["actions"] = self._branch_actions(b)
        return b

    @staticmethod
    def _branch_actions(b):
        """Red items only, the largest TL impact first (at most 5)."""
        acts = []
        if b["target_pct"] is not None and b["target_pct"] < 85:
            acts.append((b["target_day"] - b["net"], "Satış günlük hedefin %%%.0f'inde kaldı (eksik %s). Bugünün hedefi %s." % (
                b["target_pct"], branch_render.tl(b["target_day"] - b["net"]), branch_render.tl(b["next_target"]))))
        nr = sum(v for _o, _e, v in b["no_reason"])
        if nr:
            who = ", ".join(sorted({e for _o, e, _v in b["no_reason"] if e})) or "kasiyer bilinmiyor"
            acts.append((nr, "Sebepsiz indirim %s (%d satır; %s): sebebi girilsin, kasiyerle konuşulsun." % (
                branch_render.tl(nr), len(b["no_reason"]), who)))
        if b["ikram_cost"] > b["ikram_cap"] and b["ikram_cost"] > 0:
            acts.append((b["ikram_cost"] - b["ikram_cap"], "İkram sınırı aşıldı: %s (sınır %s). Bugün ikram onayla verilsin." % (
                branch_render.tl(b["ikram_cost"]), branch_render.tl(b["ikram_cap"]))))
        if b["cancel_no_reason"]:
            val = sum(v for _o, _e, v in b["cancels_nr"])
            who = ", ".join(sorted({e for _o, e, _v in b["cancels_nr"] if e})) or "kasiyer bilinmiyor"
            acts.append((val, "%d iptalin sebebi girilmemiş (%s; %s)." % (b["cancel_no_reason"], branch_render.tl(val), who)))
        if b["open_n"]:
            acts.append((b["open_value"], "Kapanışta %d sipariş açık kaldı (%s): ödendiyse kapatılsın, değilse sebepli iptal edilsin." % (
                b["open_n"], branch_render.tl(b["open_value"]))))
        busy = [hr for hr, v, avg in b["hours"] if avg >= 3 and v > avg * 1.3]
        if busy:
            acts.append((0.0, "Yoğun saat: %s normalin %%130 üstündeydi — bugün o saatlere kadro planlansın." % (
                ", ".join("%02d:00" % (hr % 24) for hr in busy[:3]))))
        if b["need_per_day"] and b["avg_daily"] and b["need_per_day"] > b["avg_daily"] * 1.15:
            acts.append((0.0, "Ay hedefi için kalan günlerde günde %s gerekiyor (son 4 hafta ort. %s)." % (
                branch_render.tl(b["need_per_day"]), branch_render.tl(b["avg_daily"]))))
        acts.sort(key=lambda a: -a[0])
        return [{"value": v, "text": t} for v, t in acts[:5]]

    def _branch_data(self, day=None):
        self.ensure_one()
        companies = self.env["res.company"].sudo().search([])
        self = self.sudo().with_context(allowed_company_ids=companies.ids)
        if not self.config_ids:
            raise UserError(_("Choose the POS branches on the report."))
        day = day or self.report_day or self._orders_day()
        costs = self.env["cz.real.cost"].compute(days=self.cost_days or 90)
        targets = self._branch_targets()
        return {"day": day, "branches": [self._branch_one(c, day, costs, targets) for c in self.config_ids.sorted("id")]}

    def get_branch_data(self, day=None):
        """JSON of the branch report (cross-check from the browser)."""
        self.ensure_one()
        if not self.env.user.has_group("base.group_system"):
            raise UserError(_("Only administrators."))
        data = self._branch_data(fields.Date.to_date(day) if day else None)
        data["day"] = data["day"].isoformat()
        return data

    # ---------------------------------------------------- yesterday's orders
    def _orders_day(self, local_now=None):
        """Business day reported: yesterday (06:00 → 06:00 Istanbul)."""
        if local_now is None:
            local_now = fields.Datetime.context_timestamp(self.with_context(tz="Europe/Istanbul"), fields.Datetime.now())
        return (local_now - timedelta(hours=6)).date() - timedelta(days=1)

    def _orders_data(self, day=None):
        self.ensure_one()
        day = day or self.report_day or self._orders_day()
        start, end = self._utc(day), self._utc(day + timedelta(days=1))
        whs = self.warehouse_ids.sudo()
        SO = self.env["sale.order"].sudo().with_context(allowed_company_ids=whs.company_id.ids or self.env.companies.ids)
        orders = SO.search([("state", "in", ("sale", "done")), ("warehouse_id", "in", whs.ids),
                            ("date_order", ">=", start), ("date_order", "<", end)], order="date_order, id")
        out, products = [], {}
        ck_ids = set()
        if self.kitchen_only:
            ck = self.env["stock.warehouse"].sudo()._cz_locations()["stock"]
            ck_ids = set(self.env["stock.location"].sudo().search([("id", "child_of", ck.id)]).ids)

        def keep(line):
            if not self.kitchen_only:
                return True
            moves = line.move_ids.filtered(lambda m: m.state != "cancel")
            if moves:
                return any(m.location_id.id in ck_ids for m in moves)
            return bool(line.product_id.sudo().bom_count)

        def open_qty(line):
            """What is really still to deliver for this line, in the product's unit: the open (not done, not cancelled)
            delivery moves — so partial deliveries, cancelled backorders, merged lines and lines without any
            delivery are never counted twice or counted at all; dropship moves (supplier → customer) are left out."""
            moves = line.move_ids.filtered(lambda m: m.state not in ("draft", "done", "cancel") and m.location_id.usage != "supplier")
            if self.kitchen_only:
                moves = moves.filtered(lambda m: m.location_id.id in ck_ids)
            return sum(moves.mapped("product_qty"))

        now = fields.Datetime.now()
        shipments = []

        def track(o, l, p, remaining, due, agg):
            agg["qty"] += remaining
            agg["orders"].add(o.id)
            agg["names"].add(o.name)
            if due and (not agg["due"] or due < agg["due"]):
                agg["due"] = due

        def shipment(o, open_lines, due):
            """One delivery to make: ready when every open move of its lines is reserved (stock is on the shelf)."""
            missing = []
            for l in open_lines:
                mv = l.move_ids.filtered(lambda m: m.state not in ("draft", "done", "cancel") and m.location_id.usage != "supplier")
                if self.kitchen_only:
                    mv = mv.filtered(lambda m: m.location_id.id in ck_ids)
                if any(m.state != "assigned" for m in mv):
                    missing.append(l.product_id.default_code or l.product_id.with_context(lang="tr_TR").name)
            shipments.append({
                "name": o.name, "partner": o.partner_id.commercial_partner_id.name or o.partner_id.name,
                "due": self._local(due).strftime("%Y-%m-%d %H:%M") if due else "", "late": bool(due and due < now),
                "lines": len(open_lines), "missing": missing,
            })

        kept = SO.browse()
        for o in orders:
            sale_lines = o.order_line.filtered(
                lambda l: not l.display_type and l.product_id and l.product_id.type != "service" and keep(l))
            if not sale_lines:
                continue
            kept |= o
            pick = o.picking_ids.filtered(lambda p: p.picking_type_code == "outgoing" and p.state != "cancel")
            deliver = o.commitment_date or (min(pick.mapped("scheduled_date")) if pick else False)
            states = set(pick.mapped("state"))
            delivery = "done" if states == {"done"} else next((s for s in ("confirmed", "waiting", "partially_available", "assigned") if s in states), False)
            lines, open_lines = [], []
            for l in sale_lines:
                p = l.product_id
                lines.append({"code": p.default_code or "", "name": p.with_context(lang="tr_TR").name, "qty": l.product_uom_qty,
                              "uom": l.product_uom.name, "subtotal": l.price_subtotal})
                agg = products.setdefault(p.id, {"code": p.default_code or "", "name": p.with_context(lang="tr_TR").name,
                                                 "uom": p.uom_id.name, "qty": 0.0, "orders": set(), "names": set(), "due": False,
                                                 "made": bool(p.sudo().bom_count)})
                remaining = open_qty(l)
                if remaining > 0:
                    track(o, l, p, remaining, deliver, agg)
                    open_lines.append(l)
            if open_lines:
                shipment(o, open_lines, deliver)
            out.append({
                "name": o.name, "partner": o.partner_id.commercial_partner_id.name or o.partner_id.name,
                "time": self._local(o.date_order).strftime("%d.%m %H:%M"),
                "deliver_on": self._local(deliver).strftime("%d.%m %H:%M") if deliver else "",
                "ref": o.client_order_ref or "", "by": o.create_uid.name if o.create_uid.name not in ("OdooBot",) else "otomatik",
                "lines": lines, "untaxed": o.amount_untaxed, "total": o.amount_total,
                "invoice_status": o.invoice_status, "delivery": delivery,
            })
        # still open from earlier days (not delivered yet), dropship lines excluded — nothing is forgotten
        # (earlier days, and orders already confirmed after the window closed — e.g. 06:00–07:30 this morning)
        open_out, drafts = [], []
        open_orders = SO.search([("state", "=", "sale"), ("warehouse_id", "in", whs.ids),
                                 "|", ("date_order", "<", start), ("date_order", ">=", end),
                                 ("picking_ids.state", "in", ("draft", "assigned", "confirmed", "waiting", "partially_available"))],
                                order="date_order, id")
        for o in open_orders:
            if any(pk.state == "draft" and pk.picking_type_code == "outgoing" for pk in o.picking_ids):
                drafts.append(o.name)  # a delivery left in draft is never shipped as is: flagged, not counted
            rows, open_lines = [], []
            pick = o.picking_ids.filtered(lambda pk: pk.state not in ("done", "cancel") and pk.picking_type_code == "outgoing")
            due = min(pick.mapped("scheduled_date")) if pick else (o.commitment_date or o.date_order)
            for l in o.order_line.filtered(lambda l: not l.display_type and l.product_id and l.product_id.type != "service" and keep(l)):
                remaining = open_qty(l)
                if remaining <= 0:
                    continue  # delivered, nothing planned, or dropship (supplier → customer)
                p = l.product_id
                rows.append({"code": p.default_code or "", "name": p.with_context(lang="tr_TR").name,
                             "qty": remaining, "uom": p.uom_id.name})
                agg = products.setdefault(p.id, {"code": p.default_code or "", "name": p.with_context(lang="tr_TR").name,
                                                 "uom": p.uom_id.name, "qty": 0.0, "orders": set(), "names": set(), "due": False,
                                                 "made": bool(p.sudo().bom_count)})
                track(o, l, p, remaining, due, agg)
                open_lines.append(l)
            if not rows:
                continue
            shipment(o, open_lines, due)
            open_out.append({
                "name": o.name, "partner": o.partner_id.commercial_partner_id.name or o.partner_id.name,
                "time": self._local(o.date_order).strftime("%d.%m %H:%M"), "deliver_on": self._local(due).strftime("%d.%m %H:%M"),
                "days": (now - o.date_order).days, "late": due < now, "lines": rows, "new": o.date_order >= end,
            })
        open_out.sort(key=lambda x: (not x["late"], -x["days"]))
        # delivered but not invoiced (accounting copy only)
        uninvoiced = []
        if self.show_prices:
            for o in SO.search([("state", "=", "sale"), ("warehouse_id", "in", whs.ids), ("invoice_status", "=", "to invoice"),
                                ("date_order", "<", end)], order="date_order, id"):
                uninvoiced.append({"name": o.name, "partner": o.partner_id.commercial_partner_id.name or o.partner_id.name,
                                   "days": (now - o.date_order).days, "amount": o.amount_to_invoice or o.amount_total})

        # unusual quantity: a line ≥ 10× the product's median order quantity of the last 90 days (×1000 typos)
        unusual = []
        if products:
            hist = defaultdict(list)
            SOL = self.env["sale.order.line"].sudo().with_context(allowed_company_ids=SO.env.context["allowed_company_ids"])
            for l in SOL.search([("product_id", "in", list(products)), ("order_id.state", "in", ("sale", "done")),
                                 ("order_id.date_order", ">=", start - timedelta(days=90)), ("order_id", "not in", orders.ids)]):
                hist[l.product_id.id].append(l.product_uom._compute_quantity(l.product_uom_qty, l.product_id.uom_id, raise_if_failure=False))
            for o_rec, o in zip(kept, out):
                for l in o_rec.order_line.filtered(lambda l: not l.display_type and l.product_id and keep(l)):
                    h = sorted(x for x in hist.get(l.product_id.id, []) if x > 0)
                    if len(h) < 3:
                        continue
                    med = h[len(h) // 2]
                    qty = l.product_uom._compute_quantity(l.product_uom_qty, l.product_id.uom_id, raise_if_failure=False)
                    if med > 0 and qty >= 10 * med:
                        unusual.append({"order": o["name"], "partner": o["partner"], "code": l.product_id.default_code or "",
                                        "name": l.product_id.with_context(lang="tr_TR").name, "qty": qty,
                                        "uom": l.product_id.uom_id.name, "median": med, "ratio": qty / med,
                                        "subtotal": l.price_subtotal})
        stock = {}
        if products and not self.show_prices:
            try:
                ck = self.env["stock.warehouse"].sudo()._cz_locations()["stock"]
                for p in self.env["product.product"].sudo().browse(list(products)).with_context(location=ck.id):
                    stock[p.id] = p.qty_available
            except UserError:
                stock = {}
        prod_rows = []
        for pid, a in products.items():
            if a["qty"] <= 0:
                continue  # already delivered — nothing left to prepare
            st = stock.get(pid, 0.0)
            short = max(0.0, a["qty"] - max(st, 0.0)) if a["made"] else 0.0
            prod_rows.append(dict(a, orders=len(a["orders"]), names=sorted(a["names"]), stock=st, short=short,
                                  due=self._local(a["due"]).strftime("%Y-%m-%d %H:%M") if a["due"] else "",
                                  late=bool(a["due"] and a["due"] < now)))
        prod_rows.sort(key=lambda x: (-(x["short"] > 0), x["code"] or x["name"]))
        return {
            "title": self.name, "day": day.isoformat(), "day_txt": day.strftime("%d.%m.%Y"),
            "warehouses": ", ".join(whs.mapped("name")), "show_prices": self.show_prices,
            "orders": out, "products": prod_rows,
            "untaxed": sum(kept.mapped("amount_untaxed")), "total": sum(kept.mapped("amount_total")),
            "to_invoice": sum(1 for o in out if o["invoice_status"] == "to invoice"),
            "unusual": unusual,
            "kitchen_only": self.kitchen_only,
            "open_orders": open_out,
            "uninvoiced": uninvoiced,
            "shipments": sorted(shipments, key=lambda x: (x["due"] or "9999")),
            "now_local": self._local(now).strftime("%Y-%m-%d %H:%M"),
            "draft_deliveries": drafts,
        }

    @api.model
    def _cz_setup_daily_reports(self):
        """Idempotent (runs at install/upgrade): the yesterday's-orders reports per warehouse and the
        chefs' numbers on the kitchen stock report. Never overwrites numbers someone edited later."""
        Wh = self.env["stock.warehouse"].sudo().with_context(active_test=False)
        mo = "+905444436338"
        chefs = "+905458682649, +905357730567"
        accountant = "+905051193196"
        whs = Wh.search([("code", "in", ("CKWH", "WH"))])
        specs = [
            # chefs: kitchen lines of every order (B2B orders entered on the main warehouse included), no amounts
            ("orders_kitchen", "Dünkü Siparişler — Mutfak (Şefler)", False, True, "%s, %s" % (mo, chefs), 40),
            # CEO + accounting: every order of both warehouses, with amounts and invoice status
            ("orders_all", "Dünkü Siparişler — Mutfak + Depo (Muhasebe)", True, False, "%s, %s" % (mo, accountant), 41),
        ]
        for key, name, prices, kitchen_only, phones, seq in specs:
            if not whs or self.sudo().with_context(active_test=False).search_count([("setup_key", "=", key)]):
                continue
            self.sudo().create({"name": name, "code": "orders_daily", "warehouse_ids": [(6, 0, whs.ids)],
                                "show_prices": prices, "kitchen_only": kitchen_only, "phone_numbers": phones,
                                "sequence": seq, "send_hour": 7.5, "setup_key": key})
        for rep in self.sudo().search([("code", "=", "kitchen_stock")]):
            if (rep.phone_numbers or "").replace(" ", "") == mo:
                rep.phone_numbers = "%s, %s" % (mo, chefs)
        # v2 (one work card for the chefs): the stock report also carries the kitchen orders; the separate
        # kitchen orders report is archived (its numbers were the same people)
        Rep = self.sudo().with_context(active_test=False)
        ICP = self.env["ir.config_parameter"].sudo()
        if whs and not ICP.get_param("cz_whatsapp_reports.workcard_v1"):
            for rep in Rep.search([("code", "=", "kitchen_stock")]):
                rep.write({"kitchen_only": True, "warehouse_ids": [(6, 0, whs.ids)], "show_prices": False,
                           "name": "Mutfak İş Kartı (Şefler)"})
            Rep.search([("setup_key", "=", "orders_kitchen")]).write({"active": False})
            ICP.set_param("cz_whatsapp_reports.workcard_v1", "1")

    def _kitchen_snapshot(self):
        snap = self.env["stock.warehouse"].sudo()._cz_kitchen_snapshot()
        if self.kitchen_only and self.warehouse_ids:
            snap["orders"] = self._orders_data()  # one work card: stock + the kitchen part of every open order
        return snap

    def get_kitchen_snapshot(self):
        """JSON of the kitchen/depot snapshot (cross-check from the browser)."""
        self.ensure_one()
        if not self.env.user.has_group("base.group_system"):
            raise UserError(_("Only administrators."))
        return self._kitchen_snapshot()

    # ------------------------------------------------------------- rendering
    def _ceo_brief_vm(self, data):
        """Plain view-model (numbers and names only) shared by text and PDF."""
        self.ensure_one()
        br = data["branches"]
        net = sum(b["net"] for b in br)
        prev = sum(b["prev_net"] for b in br)
        day = fields.Datetime.context_timestamp(self, max(b["stop_at"] for b in br)) - timedelta(hours=6)
        pct, direction = brief_render.pct_change(net, prev)
        vm = {
            "date": day.strftime("%d/%m/%Y"),
            "net": net,
            "orders": sum(b["orders"] for b in br),
            "pct": pct,
            "dir": direction,
            "cost_days": self.cost_days or 90,
            "branches": [],
            "alerts": [],
        }
        for b in br:
            bpct, bdir = brief_render.pct_change(b["net"], b["prev_net"])
            vm["branches"].append({
                "name": b["branch"],
                "session": b["session"],
                "net": b["net"],
                "orders": b["orders"],
                "avg": (b["net"] / b["orders"]) if b["orders"] else 0.0,
                "pct": bpct,
                "dir": bdir,
                "margin": b["real_margin"],
                "real_cost": b["real_cost"],
                "covered": b["covered_net"],
                "platform": b["platform_net"],
                "platform_share": (b["platform_net"] / b["sales_net"] * 100.0) if b["sales_net"] else 0.0,
                "cancel_n": b["cancel_n"],
                "cancel_value": b["cancel_value"],
                "cancel_no_reason": b["cancel_no_reason"],
                "refund_n": b["refund_n"],
                "refund_value": b["refund_value"],
                "discount": b["discount"],
                "reward": b["reward"],
                "staff_orders": b["staff_orders"],
                "staff_items": b["staff_items"],
                "staff_value": b["staff_value"],
                "cash_diff": b["cash_diff"],
                "cash_uncounted": b.get("cash_uncounted") or 0.0,
                "channels": [(k, v[0], v[1]) for k, v in b["channels"][:6]],
                "cashiers": [(k, v[0], v[1], v[2]) for k, v in b["cashiers"][:5]],
                "top": b["top"],
            })
            if b["refund_dupes"]:
                amounts = " / ".join("%s TL" % brief_render.money(a) for a in b["refund_dupes"])
                vm["alerts"].append({"branch": b["branch"], "text": "مرتجعات بمبالغ مكررة: {amt}", "vals": {"amt": amounts}})
            if b["cancel_max"] >= (self.cancel_alert_amount or 0.0) > 0:
                vm["alerts"].append({
                    "branch": b["branch"], "text": "إلغاء واحد بقيمة {amt}",
                    "vals": {"amt": "%s TL" % brief_render.money(b["cancel_max"])},
                })
            if b["cancel_no_reason"]:
                vm["alerts"].append({
                    "branch": b["branch"], "text": "إلغاءات بلا سبب مسجل: {n}", "vals": {"n": str(b["cancel_no_reason"])},
                })
            if b["cashiers"] and b["orders"]:
                top_name, top = b["cashiers"][0]
                share = top[0] / b["orders"] * 100.0
                if share >= (self.cashier_share_alert or 101.0):
                    vm["alerts"].append({
                        "branch": b["branch"], "text": "الكاشير {name} سجّل {share} من الطلبات",
                        "vals": {"name": top_name, "share": "%.0f%%" % share},
                    })
        for name in data.get("skipped") or []:
            vm["alerts"].insert(0, {"branch": name, "text": "لا توجد جلسة مغلقة لهذا اليوم، والفرع غير مشمول في هذا الموجز"})
        vm["alerts"] = vm["alerts"][:6]
        return vm

    def _ceo_brief_html(self):
        """HTML body of the PDF brief (used by the QWeb report)."""
        self.ensure_one()
        if self.code == "branch_daily":
            return Markup(branch_render.render_html(self._branch_data()))
        if self.code == "orders_daily":
            return Markup(orders_render.render_html(self._orders_data()))
        if self.code == "kitchen_stock":
            snap = self._kitchen_snapshot()
            return Markup(workcard_render.render_html(snap) if snap.get("orders") else kitchen_render.render_html(snap))
        if self.code == "marketing":
            return Markup(marketing_render.render_html(self._marketing_data()))
        data = self._ceo_brief_data()
        if not data["branches"]:
            raise UserError(_("No closed POS session found."))
        return Markup(brief_render.render_html(self._ceo_brief_vm(data)))

    def action_preview(self):
        for report in self:
            log = self.env["cz.wa.report.log"].create({"report_id": report.id, "state": "preview"})
            try:
                if report.code == "branch_daily":
                    report.write({"preview_text": branch_render.render_text(report._branch_data()),
                                  "preview_date": fields.Datetime.now()})
                    log.write({"note": "ok"})
                    continue
                if report.code == "orders_daily":
                    report.write({"preview_text": orders_render.render_text(report._orders_data()),
                                  "preview_date": fields.Datetime.now()})
                    log.write({"note": "ok"})
                    continue
                if report.code == "kitchen_stock":
                    snap = report._kitchen_snapshot()
                    report.write({"preview_text": workcard_render.render_text(snap) if snap.get("orders") else kitchen_render.render_text(snap),
                                  "preview_date": fields.Datetime.now()})
                    log.write({"note": "ok"})
                    continue
                if report.code == "marketing":
                    report.write({"preview_text": report._marketing_text(report._marketing_data()),
                                  "preview_date": fields.Datetime.now()})
                    log.write({"note": "ok"})
                    continue
                data = report._ceo_brief_data()
                if data["branches"]:
                    text = brief_render.render_text(report._ceo_brief_vm(data))
                else:
                    text = _("No closed POS session found.")
                report.write({"preview_text": text, "preview_date": fields.Datetime.now()})
                log.write({"note": "ok"})
            except UserError:
                raise
            except Exception as err:  # keep the reason for review, then surface it
                log.write({"state": "error", "note": str(err)[:2000]})
                self.env.cr.commit()
                raise
        return True

    # --------------------------------------------------------------- sending
    WA_BODY = (
        "مرحباً، هذا الموجز اليومي لتشوكو زوما عن يوم العمل {{1}}.\n"
        "صافي مبيعات المجموعة {{2}} ليرة من {{3}} طلب.\n"
        "التفاصيل الكاملة في الملف المرفق."
    )

    def action_create_wa_template(self):
        """Create the WhatsApp template record (draft). It is submitted to Meta from the WhatsApp app."""
        self.ensure_one()
        if self.wa_template_id:
            raise UserError(_("The WhatsApp template already exists."))
        account = self.env["whatsapp.account"].search([], limit=1)
        if not account:
            raise UserError(_("No WhatsApp account is configured."))
        spec = {
            "ceo_daily": ("CZ CEO Daily Brief", "cz_ceo_daily_brief", "ar", "action_report_ceo_brief_log", self.WA_BODY,
                          ("18/11/2026", "200,983", "230")),
            "marketing": ("CZ Marketing Report", "cz_marketing_daily", "tr", "action_report_marketing_log", MK_BODY,
                          ("18.11.2026", "199.788", "217")),
            "kitchen_stock": ("CZ Kitchen Stock Report", "cz_kitchen_stock_daily", "tr", "action_report_kitchen_log", KS_BODY,
                              ("21.11.2026", "8 ürün üretilecek, 3 sipariş gönderilecek", "37")),
            "branch_daily": ("CZ Branch Daily", "cz_branch_daily", "tr", "action_report_branch_log", BR_BODY,
                             ("22.11.2026", "Kayaşehir 142.820 TL (hedef %97) · Metrokent 76.025 TL (hedef %103)", "3 madde")),
            "orders_daily": ("CZ Orders Daily", "cz_orders_daily", "tr", "action_report_orders_log", OR_BODY,
                             ("20.11.2026", "11 sipariş, 4 müşteri, toplam 61.240 TL (KDV hariç)", "96")),
        }[self.code]
        existing = self.env["whatsapp.template"].search([("template_name", "=", spec[1]), ("wa_account_id", "=", account.id)], limit=1)
        if existing:  # one template serves every report of the same kind (kitchen and accounting copies)
            self.wa_template_id = existing.id
            return {"type": "ir.actions.act_window", "res_model": "whatsapp.template",
                    "res_id": existing.id, "view_mode": "form", "target": "current"}
        template = self.env["whatsapp.template"].create({
            "name": spec[0],
            "template_name": spec[1],
            "wa_account_id": account.id,
            "model_id": self.env["ir.model"]._get_id("cz.wa.report.log"),
            "phone_field": "mobile",
            "lang_code": spec[2],
            "template_type": "utility",
            "header_type": "document",
            "report_id": self.env.ref("cz_whatsapp_reports.%s" % spec[3]).id,
            "body": spec[4],
            "footer_text": "Choco Zuma Reports",
        })
        wanted = {
            "{{1}}": ("business_day", spec[5][0]),
            "{{2}}": ("net_text", spec[5][1]),
            "{{3}}": ("orders_text", spec[5][2]),
        }
        Variable = self.env["whatsapp.template.variable"]
        for name, (field_name, demo) in wanted.items():
            vals = {"field_type": "field", "field_name": field_name, "demo_value": demo}
            var = template.variable_ids.filtered(lambda v: v.name == name and v.line_type == "body")
            if var:
                var.write(vals)
            else:
                Variable.create(dict(vals, name=name, line_type="body", wa_template_id=template.id))
        self.wa_template_id = template.id
        return {
            "type": "ir.actions.act_window", "res_model": "whatsapp.template",
            "res_id": template.id, "view_mode": "form", "target": "current",
        }

    def _recipient_numbers(self):
        self.ensure_one()
        numbers = []
        for partner in self.partner_ids:
            number = partner.mobile or partner.phone
            if number:
                numbers.append((partner.id, number))
        for number in (self.phone_numbers or "").replace(";", ",").split(","):
            number = number.strip()
            if number:
                numbers.append((False, number))
        seen, out = set(), []
        for partner_id, number in numbers:
            key = re.sub(r"\D", "", number)
            if key and key not in seen:
                seen.add(key)
                out.append((partner_id, number))
        return out

    def _send_brief(self, data):
        """One log per recipient, then one WhatsApp template message per log."""
        self.ensure_one()
        template = self.wa_template_id
        if not template:
            raise UserError(_("Create the WhatsApp template first."))
        if template.status != "approved":
            raise UserError(_("The WhatsApp template is not approved by Meta yet (status: %s).", template.status))
        recipients = self._recipient_numbers()
        if not recipients:
            raise UserError(_("No WhatsApp number on the report."))
        pay = self._payload(data)
        Log = self.env["cz.wa.report.log"]
        logs = Log.create([{
            "report_id": self.id,
            "state": "sent",
            "partner_id": partner_id,
            "mobile": number,
            "business_day": pay["day"],
            "net_text": pay["net_text"],
            "orders_text": pay["orders_text"],
            "brief_html": pay["html"],
        } for partner_id, number in recipients])
        composer = self.env["whatsapp.composer"].with_context(active_model=Log._name, active_ids=logs.ids).create({
            "res_model": Log._name,
            "res_ids": str(logs.ids),
            "wa_template_id": template.id,
        })
        composer._send_whatsapp_template(force_send_by_cron=False)
        messages = self.env["whatsapp.message"].sudo().search([
            ("mail_message_id.model", "=", Log._name), ("mail_message_id.res_id", "in", logs.ids),
        ])
        by_log = {m.mail_message_id.res_id: m for m in messages}
        for log in logs:
            message = by_log.get(log.id)
            if not message:
                log.write({"state": "error", "note": "no WhatsApp message was created"})
            elif message.state in ("error", "bounced", "cancel"):
                log.write({"state": "error", "note": "%s: %s" % (message.failure_type or message.state, message.failure_reason or "")})
            else:
                log.write({"note": "WhatsApp: %s" % message.state})
        return logs

    def action_send_now(self):
        self.ensure_one()
        if self.code == "kitchen_stock":
            data = self._kitchen_snapshot()
        elif self.code == "orders_daily":
            data = self._orders_data()
        elif self.code == "branch_daily":
            data = self._branch_data()
        else:
            data = self._marketing_data() if self.code == "marketing" else self._ceo_brief_data()
        logs = self._send_brief(data)
        failed = logs.filtered(lambda l: l.state == "error")
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {
                "title": _("WhatsApp"),
                "message": _("%(ok)s sent, %(ko)s failed. See the Log tab.", ok=len(logs - failed), ko=len(failed)),
                "type": "warning" if failed else "success", "sticky": bool(failed),
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    @api.model
    def _cron_send_daily(self):
        """Runs every 30 minutes; sends each report once per business day, after its branches closed."""
        now = fields.Datetime.now()
        fresh_since = now - timedelta(hours=10)
        local_now = fields.Datetime.context_timestamp(self.with_context(tz="Europe/Istanbul"), now)
        local_hour = local_now.hour
        for report in self.search([("code", "in", ("kitchen_stock", "orders_daily", "branch_daily")), ("wa_template_id.status", "=", "approved")]):
            try:
                if local_now.hour + local_now.minute / 60.0 < (report.send_hour or 0):
                    continue
                day = local_now.date() if report.code == "kitchen_stock" else report._orders_day(local_now)
                if self.env["cz.wa.report.log"].search_count([
                    ("report_id", "=", report.id), ("business_day", "=", day.strftime("%d.%m.%Y")), ("state", "=", "sent"),
                ]):
                    continue
                if report.code == "kitchen_stock":
                    report._send_brief(report._kitchen_snapshot())
                elif report.code == "branch_daily":
                    report._send_brief(report._branch_data(day))
                else:
                    report._send_brief(report._orders_data(day))
                self.env.cr.commit()
            except Exception as err:
                self.env.cr.rollback()
                self.env["cz.wa.report.log"].create({"report_id": report.id, "state": "error", "note": "cron: %s" % str(err)[:1500]})
                self.env.cr.commit()
        for report in self.search([("code", "=", "marketing"), ("wa_template_id.status", "=", "approved")]):
            try:
                day, skipped = report._marketing_last_day(fresh_since=fresh_since)
                if not day or (skipped and not (4 <= local_hour < 12)):
                    continue
                if self.env["cz.wa.report.log"].search_count([
                    ("report_id", "=", report.id), ("business_day", "=", day.strftime("%d.%m.%Y")), ("state", "=", "sent"),
                ]):
                    continue
                report._send_brief(report._marketing_data(day))
                self.env.cr.commit()
            except Exception as err:
                self.env.cr.rollback()
                self.env["cz.wa.report.log"].create({"report_id": report.id, "state": "error", "note": "cron: %s" % str(err)[:1500]})
                self.env.cr.commit()
        for report in self.search([("code", "=", "ceo_daily"), ("wa_template_id.status", "=", "approved")]):
            try:
                data = report._ceo_brief_data(fresh_since=fresh_since)
                if not data["branches"]:
                    continue
                if data["skipped"] and not (4 <= local_hour < 12):
                    continue  # a branch is still open: wait for it until 04:00
                day = report._ceo_brief_vm(data)["date"]
                if self.env["cz.wa.report.log"].search_count(
                    [("report_id", "=", report.id), ("business_day", "=", day), ("state", "=", "sent")]
                ):
                    continue
                report._send_brief(data)
                self.env.cr.commit()
            except Exception as err:
                self.env.cr.rollback()
                self.env["cz.wa.report.log"].create({"report_id": report.id, "state": "error", "note": "cron: %s" % str(err)[:1500]})
                self.env.cr.commit()

    def action_print_pdf(self):
        self.ensure_one()
        ref = {"marketing": "action_report_marketing", "kitchen_stock": "action_report_kitchen",
               "orders_daily": "action_report_orders", "branch_daily": "action_report_branch"}.get(self.code, "action_report_ceo_brief")
        return self.env.ref("cz_whatsapp_reports.%s" % ref).report_action(self)


class ReportCeoBrief(models.AbstractModel):
    _name = "report.cz_whatsapp_reports.report_ceo_brief"
    _description = "CEO daily brief (PDF)"

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["cz.wa.report"].browse(docids)
        return {
            "doc_ids": docids,
            "doc_model": "cz.wa.report",
            "docs": docs,
            "briefs": {doc.id: doc._ceo_brief_html() for doc in docs},
        }


class CzWaReportLog(models.Model):
    _name = "cz.wa.report.log"
    _inherit = ["mail.thread"]
    _description = "Choco Zuma WhatsApp report log"
    _order = "id desc"
    _rec_name = "business_day"

    report_id = fields.Many2one("cz.wa.report", required=True, ondelete="cascade")
    state = fields.Selection([("preview", "Preview"), ("sent", "Sent"), ("error", "Error")], default="preview")
    note = fields.Text()
    partner_id = fields.Many2one("res.partner")
    mobile = fields.Char()
    business_day = fields.Char()
    net_text = fields.Char()
    orders_text = fields.Char()
    brief_html = fields.Text()


class ReportCeoBriefLog(models.AbstractModel):
    _name = "report.cz_whatsapp_reports.report_ceo_brief_log"
    _description = "CEO daily brief sent by WhatsApp (PDF)"

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["cz.wa.report.log"].browse(docids)
        briefs = {}
        for doc in docs:
            briefs[doc.id] = Markup(doc.brief_html) if doc.brief_html else doc.report_id._ceo_brief_html()
        return {"doc_ids": docids, "doc_model": "cz.wa.report.log", "docs": docs, "briefs": briefs}
