# -*- coding: utf-8 -*-
"""Real material cost per product, from posted vendor bills and BoMs.

Never uses the stored standard price as a real source: it is only a flagged
fallback. Read-only: this model writes nothing.
"""
from datetime import timedelta

from odoo import api, fields, models

SUSPECT_RATIO = 8.0  # invoice unit cost >= 8x or <= 1/8 of Odoo cost = unit error


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
        ext = [("partner_id", "not in", group_partners)]
        ext_win = self._bill_costs(d_win, date_to, ext)
        ext_old = self._bill_costs(d_old, d_win, ext)
        branch_companies = companies.filtered(lambda c: c.partner_id.id in group_partners).ids
        transfer = self._bill_costs(d_win, date_to, [("partner_id", "in", group_partners)], branch_companies)

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
