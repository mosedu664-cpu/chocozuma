# -*- coding: utf-8 -*-
"""Kitchen product labels (55 × 40 mm, Zebra via the RawBT Android app).

Why not lots: kitchen products (KM-/PM-...) are shared with the branch companies; turning on
lot tracking would force lots on their receipts, BOMs and counts. The label carries the
manufacturing order number as the batch reference instead, and Odoo computes every date:

* fresh product   → "SKT: <production + fresh days>" + where to keep it
* frozen product  → "Dondurucu SKT: <production + freezer days>" + "Çözünce N gün" and an
                    empty "Çıkış: __.__" box the branch fills when it takes it out.

The label shelf lives are separate from ``cz_shelf_days`` on purpose: that field drives the
"expired" alerts of the chefs' daily WhatsApp stock report.
"""
import json
from datetime import timedelta

import pytz

from odoo import api, fields, models

TZ = "Europe/Istanbul"

# Chef's sheet (scan 26.11.2026). code: (fresh days, where, freezer days; 0 = not frozen).
# Fresh days count from the production date (section 1) or from leaving the freezer (section 2).
# KM-016 / KM-034: the chef wrote 20-25, B2B CZ-SS-01 has 14 → the conservative 20 until confirmed.
LABEL_SHELF_LIFE = {
    # section 1 — fresh, from the production date
    "PM-008": (6, "fridge", 0), "PM-004": (7, "fridge", 0), "PM-023": (7, "fridge", 0),
    "PM-007": (8, "fridge", 0), "KM-059": (8, "fridge", 0), "PM-006": (8, "fridge", 0),
    "PM-012": (8, "fridge", 0), "KM-047": (8, "fridge", 0), "KM-001": (8, "fridge", 0),
    "KM-002": (8, "fridge", 0), "KM-057": (8, "fridge", 0), "KM-014": (8, "fridge", 0),
    "KM-031": (8, "fridge", 0), "KM-033": (8, "fridge", 0),
    "KM-007": (10, "fridge", 0), "KM-018": (10, "fridge", 0), "KM-004": (25, "fridge", 0),
    "KM-016": (20, "fridge", 0), "KM-034": (20, "fridge", 0),
    "KM-060": (30, "fridge", 0), "KM-053": (3, "fridge", 0),
    "KM-074": (20, "room", 0), "RM-029": (90, "room", 0), "PM-011": (90, "room", 0),
    "CZ-HM-01": (90, "room", 0),
    # section 2 — frozen; fresh days count from leaving the freezer
    "KM-005": (3, "room", 180), "PM-009": (3, "room", 180), "KM-017": (20, "room", 180),
    "KM-087": (8, "fridge", 90), "KM-091": (8, "fridge", 90), "KM-042": (20, "fridge", 180),
    "PM-002": (8, "fridge", 180), "KM-088": (8, "fridge", 180), "KM-089": (8, "fridge", 180),
    "KM-092": (20, "fridge", 180),
    "KM-037": (3, "fridge", 180), "KM-038": (3, "fridge", 180), "KM-093": (3, "fridge", 180),
    "KM-103": (3, "fridge", 180), "KM-104": (3, "fridge", 180), "KM-105": (3, "fridge", 180),
    "KM-035": (3, "fridge", 180), "KM-052": (3, "fridge", 180),
    "KM-003": (2, "fridge", 90), "KM-049": (2, "fridge", 90), "SB-002": (3, "fridge", 180),
    "KM-056": (10, "fridge", 90), "PM-015": (3, "fridge", 90), "KM-032": (2, "fridge", 90),
    "KM-048": (2, "fridge", 90), "KM-077": (3, "fridge", 30), "KM-086": (5, "fridge", 90),
    "KM-090": (5, "fridge", 90), "KM-082": (3, "fridge", 90), "KM-078": (3, "fridge", 90),
}

WHERE_FULL = {"fridge": "Buzdolabında saklayın (+4 °C)", "room": "Oda sıcaklığında, kuru yerde"}
WHERE_SHORT = {"fridge": "Buzdolabı", "room": "Oda sıcaklığı"}


def _zpl_text(value):
    """ZPL field data must not contain the control characters ^ and ~."""
    return " ".join(str(value or "").replace("^", " ").replace("~", " ").split())


class ProductTemplate(models.Model):
    _inherit = "product.template"

    cz_lbl_fresh_days = fields.Integer(
        "Etiket: taze ömür (gün)",
        help="Fresh days printed on the label: from the production date, or — for a frozen "
             "product — from the moment it leaves the freezer.")
    cz_lbl_fresh_where = fields.Selection(
        [("fridge", "Buzdolabı (+4 °C)"), ("room", "Oda sıcaklığı")], string="Etiket: saklama")
    cz_lbl_frozen_days = fields.Integer(
        "Etiket: dondurucu ömrü (gün)", help="0 = this product is not frozen.")

    @api.model
    def _cz_setup_label_shelf_life(self):
        """Idempotent: fills the chef's numbers only on products that have no label values yet."""
        tmpls = self.sudo().with_context(active_test=False).search(
            [("default_code", "in", list(LABEL_SHELF_LIFE))])
        for tmpl in tmpls:
            if tmpl.cz_lbl_fresh_days or tmpl.cz_lbl_frozen_days or tmpl.cz_lbl_fresh_where:
                continue
            fresh, where, frozen = LABEL_SHELF_LIFE[tmpl.default_code]
            tmpl.write({"cz_lbl_fresh_days": fresh, "cz_lbl_fresh_where": where,
                        "cz_lbl_frozen_days": frozen})

    # ------------------------------------------------------------------ label
    def _cz_label_line(self, produced_utc, ref):
        """Everything the print page needs for one product: texts for the screen and two ZPLs."""
        self.ensure_one()
        tz = pytz.timezone(self.env.user.tz or TZ)
        local = pytz.utc.localize(produced_utc).astimezone(tz).replace(tzinfo=None)
        ref = ref or local.strftime("%y%m%d-%H%M")
        tmpl = self.with_context(lang="tr_TR")
        code, name = _zpl_text(tmpl.default_code), _zpl_text(tmpl.name)
        fresh, frozen = self.cz_lbl_fresh_days, self.cz_lbl_frozen_days
        where = self.cz_lbl_fresh_where or "fridge"
        d = -30 if len(name) <= 26 else 0
        head = (
            "^XA^CI28^PW440^LL320^LH0,0^MNY^MMT^PR3^MD10\n"
            "^FO20,14^A0N,24,22^FD%s^FS\n"
            "^FO296,14^A0N,24,22^FDCHOCO ZUMA^FS\n"
            "^FO20,44^A0N,30,26^FB400,2,0,L^FD%s^FS\n"
            "^FO20,%d^GB400,2,2^FS\n"
            "^FO20,%d^A0N,22,20^FDÜretim: %s^FS\n"
        ) % (code, name, 108 + d, 116 + d, local.strftime("%d.%m.%Y %H:%M"))
        foot = (
            "^FO20,266^A0N,22,20^FDParti: %s^FS\n"
            "^FO344,262^A0N,36,32^FD#K#^FS\n^XZ"
        ) % _zpl_text(ref)
        line = {
            "code": tmpl.default_code or "", "name": tmpl.name, "ref": ref,
            "produced": local.strftime("%d.%m.%Y %H:%M"),
            "ok": bool(fresh), "has_frozen": bool(frozen and fresh),
            "fresh_txt": "", "frozen_txt": "", "fresh_zpl": "", "frozen_zpl": "",
        }
        if not fresh:
            return line
        skt = (local + timedelta(days=fresh)).strftime("%d.%m.%Y")
        line["fresh_txt"] = "SKT %s · %s" % (skt, WHERE_SHORT[where])
        line["fresh_zpl"] = head + (
            "^FO20,%d^A0N,40,34^FDSKT: %s^FS\n"
            "^FO20,%d^A0N,24,22^FD%s^FS\n"
        ) % (142 + d, skt, 188 + d, WHERE_FULL[where]) + foot
        if frozen:
            fskt = (local + timedelta(days=frozen)).strftime("%d.%m.%Y")
            line["frozen_txt"] = "Dondurucu SKT %s · çözünce %d gün (%s)" % (
                fskt, fresh, WHERE_SHORT[where].lower())
            line["frozen_zpl"] = head + (
                "^FO20,%d^A0N,30,26^FDDondurucu SKT: %s^FS\n"
                "^FO20,%d^A0N,24,22^FDÇözünce %d gün · %s^FS\n"
                "^FO20,%d^A0N,22,20^FDÇıkış: ____.____.______^FS\n"
            ) % (142 + d, fskt, 178 + d, fresh, WHERE_SHORT[where], 210 + d) + foot
        return line

    def _cz_label_lines(self):
        now = fields.Datetime.now()
        return [t._cz_label_line(now, None) for t in self]

    def cz_label_json(self):
        return json.dumps(self._cz_label_lines())


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    def _cz_label_lines(self):
        lines = []
        for mo in self:
            produced = mo.date_finished if mo.state == "done" and mo.date_finished else fields.Datetime.now()
            lines.append(mo.product_id.product_tmpl_id._cz_label_line(produced, mo.name))
        return lines

    def cz_label_json(self):
        return json.dumps(self._cz_label_lines())
