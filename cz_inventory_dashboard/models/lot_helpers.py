# -*- coding: utf-8 -*-
"""Lot help for the kitchen (B2B CZ- products are lot tracked).

What the data showed (Oct–Nov 2026): the chef produces and ships within minutes, and keeps the
lot Odoo proposes on the delivery. Odoo had reserved an *older* lot when the delivery was
confirmed, the chef typed the real quantity on that line, and the old lot went negative while
the fresh lot stayed "in stock" (e.g. CKWH/OUT/02830: 4 × lot 241 that held 1). Several MOs a
day for the same product also made 2–4 lots per product per day.

1. One lot per product per day: a new MO of the same product the same (Istanbul) day reuses the
   lot of the earlier MO instead of opening a new one.
2. On validation of a transfer out of internal stock, a lot line asking for more than the lot
   holds is completed automatically from the other non-expired lots of the same product (oldest
   first — the same order Odoo reserves in). The change is written in the transfer's chatter.
   If the lots together do not hold enough, the transfer is stopped with a clear Turkish message.
"""
from collections import defaultdict
from datetime import datetime, time

import pytz

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero, float_round

TZ = "Europe/Istanbul"


def _n(qty, rounding):
    return "%g" % float_round(qty, precision_rounding=rounding)


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    def _cz_today_lot(self):
        self.ensure_one()
        tz = pytz.timezone(TZ)
        start = tz.localize(datetime.combine(fields.Datetime.now().replace(tzinfo=pytz.utc).astimezone(tz).date(), time.min))
        start_utc = start.astimezone(pytz.utc).replace(tzinfo=None)
        other = self.search([
            ("id", "!=", self.id),
            ("product_id", "=", self.product_id.id),
            ("company_id", "=", self.company_id.id),
            ("state", "!=", "cancel"),
            ("lot_producing_id", "!=", False),
            ("lot_producing_id.create_date", ">=", start_utc),
        ], order="id desc", limit=1)
        return other.lot_producing_id

    def _set_lot_producing(self):
        self.ensure_one()
        if self.product_id.tracking == "lot":
            lot = self._cz_today_lot()
            if lot:
                self.lot_producing_id = lot
                return
        return super()._set_lot_producing()


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _cz_fix_lot_lines(self):
        Quant = self.env["stock.quant"].sudo()
        Lot = self.env["stock.lot"].sudo()
        now = fields.Datetime.now()
        problems = []
        for picking in self:
            if picking.state in ("done", "cancel") or picking.location_id.usage != "internal":
                continue
            any_picked = bool(picking.move_ids.filtered("picked"))
            lines = picking.move_line_ids.filtered(
                lambda ml: ml.lot_id and ml.product_id.tracking == "lot" and ml.quantity > 0
                and (ml.picked or not any_picked))
            notes = []
            for product, plines in lines.grouped("product_id").items():
                rounding = product.uom_id.rounding
                quants = Quant.search([("product_id", "=", product.id),
                                       ("location_id", "child_of", picking.location_id.id),
                                       ("lot_id", "!=", False)])
                have = defaultdict(float)
                for q in quants:
                    have[q.lot_id] += q.quantity
                need = defaultdict(float)
                for ml in plines:
                    need[ml.lot_id] += ml.product_uom_id._compute_quantity(ml.quantity, product.uom_id, rounding_method="HALF-UP")
                excess = 0.0
                for lot, qty in need.items():
                    over = qty - max(have[lot], 0.0)
                    if float_compare(over, 0, precision_rounding=rounding) <= 0:
                        continue
                    excess += over
                    # take the excess off this lot's lines, last line first
                    for ml in plines.filtered(lambda l: l.lot_id == lot).sorted("id", reverse=True):
                        if float_is_zero(over, precision_rounding=rounding):
                            break
                        q = ml.product_uom_id._compute_quantity(ml.quantity, product.uom_id, rounding_method="HALF-UP")
                        cut = min(q, over)
                        over -= cut
                        need[lot] -= cut
                        left = q - cut
                        if float_is_zero(left, precision_rounding=rounding) and len(plines.filtered(lambda l: l.lot_id == lot)) > 1:
                            ml.quantity = 0
                        else:
                            ml.quantity = product.uom_id._compute_quantity(left, ml.product_uom_id)
                if float_is_zero(excess, precision_rounding=rounding):
                    continue
                template = plines[0]
                candidates = Lot.browse([l.id for l in have]).filtered(
                    lambda l: not l.expiration_date or l.expiration_date >= now).sorted(lambda l: (l.create_date, l.id))
                moved = []
                for lot in candidates:
                    free = have[lot] - need[lot]
                    if float_compare(free, 0, precision_rounding=rounding) <= 0:
                        continue
                    take = min(free, excess)
                    q_loc = quants.filtered(lambda q: q.lot_id == lot and q.quantity > 0).sorted("quantity", reverse=True)[:1]
                    template.copy({
                        "lot_id": lot.id,
                        "quantity": product.uom_id._compute_quantity(take, template.product_uom_id),
                        "location_id": (q_loc.location_id or template.location_id).id,
                    })
                    need[lot] += take
                    excess -= take
                    moved.append("%s × %s" % (_n(take, rounding), lot.name))
                    if float_is_zero(excess, precision_rounding=rounding):
                        break
                if not float_is_zero(excess, precision_rounding=rounding):
                    stock_txt = ", ".join("%s: %s" % (l.name, _n(q, rounding))
                                          for l, q in have.items() if q > 0) or _("hiç yok")
                    problems.append(_("%(p)s: lotlarda yeterli stok yok, %(x)s %(u)s eksik. Stoktaki lotlar: %(s)s. "
                                      "Önce üretim emrini bitirin (lot oluşsun) veya miktarı düzeltin.",
                                      p=product.display_name, x=_n(excess, rounding),
                                      u=product.uom_id.name, s=stock_txt))
                elif moved:
                    notes.append("%s → %s" % (product.display_name, ", ".join(moved)))
            lines.filtered(lambda ml: float_is_zero(ml.quantity, precision_rounding=ml.product_uom_id.rounding)).unlink()
            if notes and not problems:
                picking.message_post(body=_("Lot otomatik düzeltildi (seçilen lotta yeterli stok yoktu): %s", "; ".join(notes)))
        if problems:
            raise UserError(_("Transfer doğrulanmadı:") + "\n• " + "\n• ".join(problems))
