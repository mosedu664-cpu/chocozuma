# -*- coding: utf-8 -*-
import re
from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from . import brief_render, kitchen_render, marketing_data, marketing_render, orders_render

PAID = ("paid", "done", "invoiced")
PLATFORM_RE = re.compile(r"trendyol|yemek|getir", re.I)
STAFF_RE = re.compile(r"personel", re.I)
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
KS_BODY = (
    "Günaydın, Choco Zuma mutfak ve depo stok raporu hazır: {{1}}.\n"
    "Bugünün uyarıları: {{2}}.\n"
    "Takip edilen {{3}} ürünün mutfak ve depo stoğu, ne üretileceği ve depodan ne getirileceği ekteki PDF dosyasında."
)


class CzWaReport(models.Model):
    _name = "cz.wa.report"
    _description = "Choco Zuma WhatsApp report"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Selection(
        [("ceo_daily", "CEO Daily Brief"), ("marketing", "Marketing Report (TR)"),
         ("kitchen_stock", "Mutfak & Depo Stok Raporu (TR)"),
         ("orders_daily", "Dünkü Siparişler (TR)")], required=True, default="ceo_daily")
    warehouse_ids = fields.Many2many("stock.warehouse", string="Warehouses",
                                     help="Yesterday's orders report: sale orders of these warehouses.")
    show_prices = fields.Boolean("Show amounts", help="Yesterday's orders report: amounts and invoice status (accounting).")
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
    def _session_stats(self, session, costs):
        """KPIs of one closed POS session (= one business day of one branch)."""
        Order = self.env["pos.order"]
        orders = Order.search([("session_id", "=", session.id)])
        paid = orders.filtered(lambda o: o.state in PAID)
        cancelled = orders.filtered(lambda o: o.state == "cancel")
        has_table = "table_id" in Order._fields
        has_emp = "employee_id" in Order._fields
        has_reason = "cancel_reason_code" in Order._fields

        def floor_name(order):
            if has_table and order.table_id:
                return (order.table_id.floor_id.name or order.table_id.display_name or "").strip()
            return ""

        staff_orders = paid.filtered(lambda o: STAFF_RE.search(floor_name(o)))
        sales = paid - staff_orders
        res = {
            "branch": session.config_id.name,
            "session": session.name,
            "orders": len(paid),
            "net": sum(paid.mapped("amount_total")) - sum(paid.mapped("amount_tax")),
            "gross": sum(paid.mapped("amount_total")),
            "cash_diff": session.cash_register_difference,
        }
        # channels
        channels = {}
        for o in sales:
            name = floor_name(o) or "(counter)"
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
            row = products.setdefault(line.product_id.id, [line.product_id.name or "", 0.0, 0.0, 0.0, 0.0])
            row[1] += line.qty
            row[2] += line.price_subtotal
            if c is not None and line.price_subtotal > 0 and c * line.qty <= line.price_subtotal * 3:
                real += c * line.qty
                cov += line.price_subtotal
                row[3] += line.price_subtotal
                row[4] += c * line.qty
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
            cur = self._session_stats(sessions[0], costs)
            cur["stop_at"] = sessions[0].stop_at
            if len(sessions) > 1:
                prev = sessions[1]
                prev_orders = self.env["pos.order"].search([("session_id", "=", prev.id), ("state", "in", PAID)])
                cur["prev_net"] = sum(prev_orders.mapped("amount_total")) - sum(prev_orders.mapped("amount_tax"))
            else:
                cur["prev_net"] = 0.0
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
        Line = env["pos.order.line"]
        line_fields = ["order_id", "product_id", "qty", "price_subtotal", "price_unit"]
        if "is_reward_line" in Line._fields:
            line_fields += ["is_reward_line", "reward_id"]
        lines = Line.search_read([("order_id", "in", [o["id"] for o in orders])], line_fields)
        products = env["product.product"].with_context(active_test=False, lang="tr_TR").browse(list({l["product_id"][0] for l in lines if l["product_id"]}))
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
                "net_text": kitchen_render.summary(snap),
                "orders_text": str(len(snap["rows"])),
                "html": kitchen_render.render_html(snap),
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
        for o in orders:
            pick = o.picking_ids.filtered(lambda p: p.picking_type_code == "outgoing" and p.state != "cancel")
            deliver = o.commitment_date or (min(pick.mapped("scheduled_date")) if pick else False)
            states = set(pick.mapped("state"))
            delivery = "done" if states == {"done"} else next((s for s in ("confirmed", "waiting", "partially_available", "assigned") if s in states), False)
            lines = []
            for l in o.order_line.filtered(lambda l: not l.display_type and l.product_id):
                p = l.product_id
                lines.append({"code": p.default_code or "", "name": p.with_context(lang="tr_TR").name, "qty": l.product_uom_qty,
                              "uom": l.product_uom.name, "subtotal": l.price_subtotal})
                agg = products.setdefault(p.id, {"code": p.default_code or "", "name": p.with_context(lang="tr_TR").name,
                                                 "uom": p.uom_id.name, "qty": 0.0, "orders": set()})
                agg["qty"] += l.product_uom._compute_quantity(l.product_uom_qty, p.uom_id, raise_if_failure=False)
                agg["orders"].add(o.id)
            out.append({
                "name": o.name, "partner": o.partner_id.commercial_partner_id.name or o.partner_id.name,
                "time": self._local(o.date_order).strftime("%d.%m %H:%M"),
                "deliver_on": self._local(deliver).strftime("%d.%m %H:%M") if deliver else "",
                "ref": o.client_order_ref or "", "by": o.create_uid.name if o.create_uid.name not in ("OdooBot",) else "otomatik",
                "lines": lines, "untaxed": o.amount_untaxed, "total": o.amount_total,
                "invoice_status": o.invoice_status, "delivery": delivery,
            })
        # unusual quantity: a line ≥ 10× the product's median order quantity of the last 90 days (×1000 typos)
        unusual = []
        if products:
            hist = defaultdict(list)
            SOL = self.env["sale.order.line"].sudo().with_context(allowed_company_ids=SO.env.context["allowed_company_ids"])
            for l in SOL.search([("product_id", "in", list(products)), ("order_id.state", "in", ("sale", "done")),
                                 ("order_id.date_order", ">=", start - timedelta(days=90)), ("order_id", "not in", orders.ids)]):
                hist[l.product_id.id].append(l.product_uom._compute_quantity(l.product_uom_qty, l.product_id.uom_id, raise_if_failure=False))
            for o_rec, o in zip(orders, out):
                for l in o_rec.order_line.filtered(lambda l: not l.display_type and l.product_id):
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
            st = stock.get(pid, 0.0)
            prod_rows.append(dict(a, orders=len(a["orders"]), stock=st, short=max(0.0, a["qty"] - max(st, 0.0))))
        prod_rows.sort(key=lambda x: (-(x["short"] > 0), x["code"] or x["name"]))
        return {
            "title": self.name, "day": day.isoformat(), "day_txt": day.strftime("%d.%m.%Y"),
            "warehouses": ", ".join(whs.mapped("name")), "show_prices": self.show_prices,
            "orders": out, "products": prod_rows,
            "untaxed": sum(orders.mapped("amount_untaxed")), "total": sum(orders.mapped("amount_total")),
            "to_invoice": sum(1 for o in out if o["invoice_status"] == "to invoice"),
            "unusual": unusual,
        }

    @api.model
    def _cz_setup_daily_reports(self):
        """Idempotent (runs at install/upgrade): the yesterday's-orders reports per warehouse and the
        chefs' numbers on the kitchen stock report. Never overwrites numbers someone edited later."""
        Wh = self.env["stock.warehouse"].sudo().with_context(active_test=False)
        mo = "+905444436338"
        chefs = "+905458682649, +905357730567"
        accountant = "+905051193196"
        specs = [
            ("CKWH", "Dünkü Siparişler — Mutfak", False, "%s, %s" % (mo, chefs), 40),
            ("WH", "Dünkü Siparişler — Ana Depo (Muhasebe)", True, "%s, %s" % (mo, accountant), 41),
        ]
        for code, name, prices, phones, seq in specs:
            wh = Wh.search([("code", "=", code)], limit=1)
            if not wh or self.sudo().with_context(active_test=False).search_count(
                    [("code", "=", "orders_daily"), ("warehouse_ids", "in", wh.ids)]):
                continue
            self.sudo().create({"name": name, "code": "orders_daily", "warehouse_ids": [(6, 0, wh.ids)],
                                "show_prices": prices, "phone_numbers": phones, "sequence": seq, "send_hour": 7.5})
        for rep in self.sudo().search([("code", "=", "kitchen_stock")]):
            if (rep.phone_numbers or "").replace(" ", "") == mo:
                rep.phone_numbers = "%s, %s" % (mo, chefs)

    def _kitchen_snapshot(self):
        return self.env["stock.warehouse"].sudo()._cz_kitchen_snapshot()

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
        if self.code == "orders_daily":
            return Markup(orders_render.render_html(self._orders_data()))
        if self.code == "kitchen_stock":
            return Markup(kitchen_render.render_html(self._kitchen_snapshot()))
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
                if report.code == "orders_daily":
                    report.write({"preview_text": orders_render.render_text(report._orders_data()),
                                  "preview_date": fields.Datetime.now()})
                    log.write({"note": "ok"})
                    continue
                if report.code == "kitchen_stock":
                    report.write({"preview_text": kitchen_render.render_text(report._kitchen_snapshot()),
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
                              ("21.11.2026", "2 sipariş için üretilecek, 3 üretilmeli, 1 depodan getirilmeli", "187")),
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
        for report in self.search([("code", "in", ("kitchen_stock", "orders_daily")), ("wa_template_id.status", "=", "approved")]):
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
               "orders_daily": "action_report_orders"}.get(self.code, "action_report_ceo_brief")
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
