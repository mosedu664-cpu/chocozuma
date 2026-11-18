# -*- coding: utf-8 -*-
import re
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

PAID = ("paid", "done", "invoiced")
PLATFORM_RE = re.compile(r"trendyol|yemek|getir", re.I)
STAFF_RE = re.compile(r"personel", re.I)


def _money(v):
    return "{:,.0f}".format(v or 0.0)


def _pct(a, b):
    if not b:
        return "-"
    v = (a - b) / b * 100.0
    return "%s%.0f%%" % ("+" if v >= 0 else "−", abs(v))


class CzWaReport(models.Model):
    _name = "cz.wa.report"
    _description = "Choco Zuma WhatsApp report"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Selection([("ceo_daily", "CEO Daily Brief")], required=True, default="ceo_daily")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    config_ids = fields.Many2many("pos.config", string="Branches (POS)")
    partner_ids = fields.Many2many("res.partner", string="Recipients")
    cost_days = fields.Integer(string="Invoice window (days)", default=90)
    cancel_alert_amount = fields.Float(string="Single cancel alert (TL)", default=2000.0)
    cashier_share_alert = fields.Float(string="One-cashier share alert (%)", default=80.0)
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
            row[1] += o.amount_total
        res["channels"] = sorted(channels.items(), key=lambda kv: -kv[1][1])
        res["platform_gross"] = sum(v[1] for k, v in channels.items() if PLATFORM_RE.search(k))
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
            if c is not None and line.price_subtotal > 0 and c * line.qty <= line.price_subtotal * 3:
                real += c * line.qty
                cov += line.price_subtotal
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

    def _ceo_brief_data(self):
        self.ensure_one()
        companies = self.env["res.company"].sudo().search([])
        self = self.sudo().with_context(allowed_company_ids=companies.ids)
        if not self.config_ids:
            raise UserError(_("Choose at least one POS branch on the report."))
        costs = self.env["cz.real.cost"].compute(days=self.cost_days or 90)
        branches = []
        for config in self.config_ids:
            sessions = self._last_sessions(config)
            if not sessions:
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
        return {"branches": branches}

    # ------------------------------------------------------------- rendering
    def _ceo_brief_text(self, data):
        self.ensure_one()
        br = data["branches"]
        if not br:
            return _("No closed POS session found.")
        net = sum(b["net"] for b in br)
        orders = sum(b["orders"] for b in br)
        prev = sum(b["prev_net"] for b in br)
        day = fields.Datetime.context_timestamp(self, max(b["stop_at"] for b in br)) - timedelta(hours=6)
        lines = [
            "تشوكو زوما · موجز %s" % day.strftime("%d/%m/%Y"),
            "",
            "المجموعة: %s ₺ صافي · %s طلباً · عن اليوم السابق %s" % (_money(net), orders, _pct(net, prev)),
            "",
        ]
        alerts = []
        for b in br:
            margin = ("%.1f%%" % b["real_margin"]) if b["real_margin"] is not None else "غير متاح"
            lines += [
                "%s (%s)" % (b["branch"], b["session"]),
                "  الصافي %s ₺ · %s طلباً · متوسط %s ₺ · عن اليوم السابق %s"
                % (_money(b["net"]), b["orders"], _money(b["net"] / b["orders"]) if b["orders"] else "-", _pct(b["net"], b["prev_net"])),
                "  الهامش الحقيقي للمواد: %s (تكلفة %s ₺ على مبيعات %s ₺)" % (margin, _money(b["real_cost"]), _money(b["covered_net"])),
                "  المنصات: %s ₺ (%s)" % (_money(b["platform_gross"]), ("%.1f%%" % (b["platform_gross"] / b["gross"] * 100.0)) if b["gross"] else "-"),
                "  الإلغاءات: %s طلباً · %s ₺ · بلا سبب %s" % (b["cancel_n"], _money(b["cancel_value"]), b["cancel_no_reason"]),
                "  المرتجعات: %s · %s ₺" % (b["refund_n"], _money(b["refund_value"])),
                "  خصومات %s ₺ · ولاء %s ₺" % (_money(b["discount"]), _money(b["reward"])),
                "  وجبات الموظفين: %s طلبات · %s صنفاً · %s ₺ بسعر القائمة" % (b["staff_orders"], b["staff_items"], _money(b["staff_value"])),
                "  فرق الكاش: %s ₺" % _money(b["cash_diff"]),
                "  القنوات: " + " · ".join("%s %s ₺ (%s)" % (k, _money(v[1]), v[0]) for k, v in b["channels"][:6]),
                "  الكاشيرية: " + " · ".join("%s %s طلباً %s ₺ إلغاء %s" % (k, v[0], _money(v[1]), v[2]) for k, v in b["cashiers"][:5]),
                "",
            ]
            if b["refund_dupes"]:
                alerts.append("%s: مرتجعات بمبالغ مكررة (%s ₺)" % (b["branch"], "، ".join(_money(a) for a in b["refund_dupes"])))
            if b["cancel_max"] >= (self.cancel_alert_amount or 0.0) > 0:
                alerts.append("%s: إلغاء واحد بقيمة %s ₺" % (b["branch"], _money(b["cancel_max"])))
            if b["cashiers"] and b["orders"]:
                top_name, top = b["cashiers"][0]
                share = top[0] / b["orders"] * 100.0
                if share >= (self.cashier_share_alert or 101.0):
                    alerts.append("%s: %s سجّل %.0f%% من الطلبات" % (b["branch"], top_name, share))
        if alerts:
            lines += ["تنبيهات:"] + ["  %s. %s" % (i + 1, a) for i, a in enumerate(alerts[:3])]
        return "\n".join(lines)

    def action_preview(self):
        for report in self:
            log = self.env["cz.wa.report.log"].create({"report_id": report.id, "state": "preview"})
            try:
                data = report._ceo_brief_data()
                text = report._ceo_brief_text(data)
                report.write({"preview_text": text, "preview_date": fields.Datetime.now()})
                log.write({"note": "ok"})
            except UserError:
                raise
            except Exception as err:  # keep the reason for review, then surface it
                log.write({"state": "error", "note": str(err)[:2000]})
                self.env.cr.commit()
                raise
        return True


class CzWaReportLog(models.Model):
    _name = "cz.wa.report.log"
    _description = "Choco Zuma WhatsApp report log"
    _order = "id desc"

    report_id = fields.Many2one("cz.wa.report", required=True, ondelete="cascade")
    state = fields.Selection([("preview", "Preview"), ("sent", "Sent"), ("error", "Error")], default="preview")
    note = fields.Text()
