# -*- coding: utf-8 -*-
import re
from datetime import timedelta

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from . import brief_render

PAID = ("paid", "done", "invoiced")
PLATFORM_RE = re.compile(r"trendyol|yemek|getir", re.I)
STAFF_RE = re.compile(r"personel", re.I)


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
        vm["alerts"] = vm["alerts"][:6]
        return vm

    def _ceo_brief_html(self):
        """HTML body of the PDF brief (used by the QWeb report)."""
        self.ensure_one()
        data = self._ceo_brief_data()
        if not data["branches"]:
            raise UserError(_("No closed POS session found."))
        return Markup(brief_render.render_html(self._ceo_brief_vm(data)))

    def action_preview(self):
        for report in self:
            log = self.env["cz.wa.report.log"].create({"report_id": report.id, "state": "preview"})
            try:
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

    def action_print_pdf(self):
        self.ensure_one()
        return self.env.ref("cz_whatsapp_reports.action_report_ceo_brief").report_action(self)


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
    _description = "Choco Zuma WhatsApp report log"
    _order = "id desc"

    report_id = fields.Many2one("cz.wa.report", required=True, ondelete="cascade")
    state = fields.Selection([("preview", "Preview"), ("sent", "Sent"), ("error", "Error")], default="preview")
    note = fields.Text()
