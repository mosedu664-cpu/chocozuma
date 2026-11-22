# -*- coding: utf-8 -*-
"""Real material cost per product, from posted vendor bills and BoMs.

Never uses the stored standard price as a real source: it is only a flagged
fallback. Read-only: this model writes nothing.
"""
from datetime import timedelta

from odoo import api, fields, models

SUSPECT_RATIO = 8.0  # invoice unit cost >= 8x or <= 1/8 of Odoo cost = unit error
# one bill line whose unit cost is >= 5x or <= 1/5 of the product's median bill unit cost is a unit error
# (e.g. "20 KG x 5,750" for 20 bags of 10 kg, "160 Units x 266.5" for 160 packs of 12 bottles): left out
LINE_OUTLIER = 5.0


class CzRealCost(models.AbstractModel):
    _name = "cz.real.cost"
    _description = "Choco Zuma real cost engine"

    @api.model
    def _conv(self, qty, from_uom, to_uom):
        """Convert qty between two units of the same category, else None."""
        if not from_uom or not to_uom:
            return None
        if from_uom.id == to_uom.id:
            return qty
        if from_uom.category_id.id != to_uom.category_id.id:
            return None
        if not from_uom.factor:
            return None
        return qty / from_uom.factor * to_uom.factor

    @api.model
    def _bill_lines(self, date_from, date_to):
        """Posted vendor bill lines in the window, as (product_id, partner_id, company_id, date, qty in product unit, balance)."""
        rows = self.env["account.move.line"].search_read([
            ("move_id.move_type", "=", "in_invoice"),
            ("move_id.state", "=", "posted"),
            ("display_type", "=", "product"),
            ("product_id", "!=", False),
            ("quantity", ">", 0),
            ("balance", ">", 0),
            ("move_id.invoice_date", ">=", date_from),
            ("move_id.invoice_date", "<", date_to),
        ], ["product_id", "product_uom_id", "partner_id", "company_id", "quantity", "balance", "invoice_date"])
        products = {p.id: p for p in self.env["product.product"].browse(list({r["product_id"][0] for r in rows}))}
        uoms = {u.id: u for u in self.env["uom.uom"].browse(list({r["product_uom_id"][0] for r in rows if r["product_uom_id"]}))}
        out = []
        for r in rows:
            p = products[r["product_id"][0]]
            q = self._conv(r["quantity"], uoms.get(r["product_uom_id"][0]) if r["product_uom_id"] else None, p.uom_id)
            if q is None or q <= 0:
                continue
            out.append((p.id, r["partner_id"][0] if r["partner_id"] else 0, r["company_id"][0],
                        fields.Date.to_date(r["invoice_date"]), q, r["balance"]))
        return out

    @staticmethod
    def _clean_lines(lines):
        """Drop the bill lines whose unit cost is far from the product's median line unit cost (unit errors)."""
        units = {}
        for pid, _partner, _company, _date, q, bal in lines:
            units.setdefault(pid, []).append(bal / q)
        ref = {}
        for pid, vals in units.items():
            vals.sort()
            m = len(vals) // 2
            ref[pid] = vals[m] if len(vals) % 2 else (vals[m - 1] + vals[m]) / 2.0
        kept, dropped = [], {}
        for line in lines:
            pid, q, bal = line[0], line[4], line[5]
            r = ref.get(pid) or 0.0
            u = bal / q
            if r > 0 and (u / r >= LINE_OUTLIER or u / r <= 1.0 / LINE_OUTLIER):
                dropped[pid] = dropped.get(pid, 0) + 1
                continue
            kept.append(line)
        return kept, dropped

    @staticmethod
    def _weighted(lines, date_from, date_to, partners, inside, company_ids=None):
        """Weighted unit cost per product over the kept lines of one window and partner group."""
        acc = {}
        for pid, partner, company, date, q, bal in lines:
            if not (date_from <= date < date_to):
                continue
            if (partner in partners) != inside:
                continue
            if company_ids is not None and company not in company_ids:
                continue
            row = acc.setdefault(pid, [0.0, 0.0])
            row[0] += q
            row[1] += bal
        return {pid: v[1] / v[0] for pid, v in acc.items() if v[0] > 0}

    @api.model
    def _bill_costs(self, date_from, date_to, partner_domain, company_ids=None):
        """Weighted unit cost per product from posted vendor bill lines."""
        domain = [
            ("move_id.move_type", "=", "in_invoice"),
            ("move_id.state", "=", "posted"),
            ("display_type", "=", "product"),
            ("product_id", "!=", False),
            ("quantity", ">", 0),
            ("balance", ">", 0),
            ("move_id.invoice_date", ">=", date_from),
            ("move_id.invoice_date", "<", date_to),
        ] + partner_domain
        if company_ids:
            domain.append(("company_id", "in", company_ids))
        groups = self.env["account.move.line"]._read_group(
            domain, ["product_id", "product_uom_id"], ["quantity:sum", "balance:sum"]
        )
        acc = {}
        for product, uom, qty, balance in groups:
            q = self._conv(qty, uom, product.uom_id)
            if q is None or q <= 0:
                continue
            row = acc.setdefault(product.id, [0.0, 0.0])
            row[0] += q
            row[1] += balance
        return {pid: v[1] / v[0] for pid, v in acc.items() if v[0] > 0}

    @api.model
    def compute(self, date_to=None, days=90):
        """Return {product_id: {'cost', 'source', 'invoice_share', 'missing', 'suspect'}}.

        source: B = BoM, F = bills (window), O = older bills, T = group transfer
        bills, S = Odoo cost only (no real source), N = no cost at all.
        """
        self = self.sudo()
        companies = self.env["res.company"].search([])
        self = self.with_context(allowed_company_ids=companies.ids, active_test=False)
        date_to = fields.Date.to_date(date_to) or fields.Date.context_today(self)
        date_to = date_to + timedelta(days=1)
        d_win = date_to - timedelta(days=days)
        d_old = date_to - timedelta(days=365)

        group_partners = self.env["res.partner"].search(
            ["|", ("id", "in", companies.partner_id.ids), ("parent_id", "in", companies.partner_id.ids)]
        ).ids
        branch_companies = companies.filtered(lambda c: c.partner_id.id in group_partners).ids
        # every bill line of the year, unit errors removed against the product's median line unit cost
        lines, _dropped = self._clean_lines(self._bill_lines(d_old, date_to))
        gp = set(group_partners)
        ext_win = self._weighted(lines, d_win, date_to, gp, False)
        ext_old = self._weighted(lines, d_old, d_win, gp, False)
        transfer = self._weighted(lines, d_win, date_to, gp, True, set(branch_companies))

        products = self.env["product.product"].search([])
        prod = {p.id: p for p in products}
        # Odoo stored cost: first company where it is set
        odoo_cost = {}
        for company in companies:
            for p in products.with_company(company):
                if p.standard_price and p.id not in odoo_cost:
                    odoo_cost[p.id] = p.standard_price

        boms = self.env["mrp.bom"].search([("active", "=", True)])
        by_variant, by_tmpl = {}, {}
        for bom in boms:
            if not any(line.product_qty > 0 for line in bom.bom_line_ids):
                continue
            if bom.product_id:
                by_variant.setdefault(bom.product_id.id, []).append(bom)
            else:
                by_tmpl.setdefault(bom.product_tmpl_id.id, []).append(bom)

        def bom_rank(bom):
            return (bom.company_id.id or 10 ** 6, bom.sequence, bom.id)

        def bom_of(p):
            cands = by_variant.get(p.id) or by_tmpl.get(p.product_tmpl_id.id) or []
            # branch recipes (higher company id than the centre) first, then the centre
            return sorted(cands, key=lambda b: (0 if b.company_id.id == 2 else 1,) + bom_rank(b))[0] if cands else None

        memo = {}

        def cost(pid, stack):
            if pid in memo:
                return memo[pid]
            p = prod.get(pid)
            if not p or pid in stack:
                return {"cost": None, "inv": 0.0, "fill": 0.0, "source": "N", "missing": [str(pid)], "suspect": 0}
            bom = bom_of(p)
            if bom:
                inv = fill = 0.0
                missing, suspect = [], 0
                bom_qty = self._conv(bom.product_qty, bom.product_uom_id, p.uom_id) or bom.product_qty or 1.0
                for line in bom.bom_line_ids:
                    if line.product_qty <= 0:
                        continue
                    comp = line.product_id
                    sub = cost(comp.id, stack + [pid])
                    q = self._conv(line.product_qty, line.product_uom_id, comp.uom_id)
                    if q is None:
                        missing.append("%s(uom)" % (comp.default_code or comp.display_name))
                        continue
                    suspect += sub["suspect"]
                    inv += q * sub["inv"]
                    fill += q * sub["fill"]
                    if sub["cost"] is None:
                        missing += sub["missing"]
                inv /= bom_qty
                fill /= bom_qty
                res = {
                    "cost": None if missing else inv + fill,
                    "inv": inv, "fill": fill, "source": "B",
                    "missing": sorted(set(missing)), "suspect": suspect,
                }
            else:
                od = odoo_cost.get(pid, 0.0)
                c, src = None, "N"
                if pid in ext_win:
                    c, src = ext_win[pid], "F"
                elif pid in ext_old:
                    c, src = ext_old[pid], "O"
                elif pid in transfer:
                    c, src = transfer[pid], "T"
                if c is not None and od > 0 and (c / od >= SUSPECT_RATIO or c / od <= 1.0 / SUSPECT_RATIO):
                    res = {"cost": od, "inv": 0.0, "fill": od, "source": "S", "missing": [], "suspect": 1}
                elif c is not None:
                    res = {"cost": c, "inv": c, "fill": 0.0, "source": src, "missing": [], "suspect": 0}
                elif od > 0:
                    res = {"cost": od, "inv": 0.0, "fill": od, "source": "S", "missing": [], "suspect": 0}
                else:
                    res = {"cost": None, "inv": 0.0, "fill": 0.0, "source": "N",
                           "missing": [p.default_code or p.display_name], "suspect": 0}
            memo[pid] = res
            return res

        out = {}
        for pid in prod:
            r = cost(pid, [])
            share = (r["inv"] / r["cost"]) if r["cost"] else 0.0
            out[pid] = {
                "cost": r["cost"], "source": r["source"], "invoice_share": share,
                "missing": r["missing"], "suspect": r["suspect"],
            }
        return out
