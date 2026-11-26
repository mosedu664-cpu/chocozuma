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
WHERE_LABEL = {"fridge": "Soğuk 0-4 °C", "room": "Oda sıcaklığı, kuru yer"}
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
        produced_txt = local.strftime("%d.%m.%Y %H:%M")
        batch = _zpl_text(ref.split("/", 1)[1] if ref.count("/") >= 2 else ref)  # CKWH/MO/05607 -> MO/05607
        allergens = ", ".join(
            t.name.split("·", 1)[1].strip() for t in self.product_tag_ids
            if t.name.startswith("İÇERİR") and "·" in t.name)
        line = {
            "code": tmpl.default_code or "", "name": tmpl.name, "ref": ref,
            "produced": produced_txt, "allergens": allergens,
            "ok": bool(fresh), "has_frozen": bool(frozen and fresh),
            "fresh_txt": "", "frozen_txt": "", "fresh_zpl": "", "frozen_zpl": "",
        }
        if self.tracking != "none":
            line.update(ok=False, msg="Bu ürün lot ile takip ediliyor: önce üretim emrinde lot oluşturun, "
                                      "etiket lot bilgisiyle (lot + SKT) basılır.")
            return line
        if not fresh:
            return line

        def zpl(skt_line, store_line, skt_txt, thaw_box=False):
            # Same grid as the B2B lot label (cz.label_lot_zpl_55x40): text left, QR right, barcode bottom.
            z = [
                "^XA^CI28^PW440^LL320^LH0,0^MNY^MMT^PR3^MD10",
                "^FO20,16^A0N,24,22^FD%s^FS" % code,
                "^FO296,16^A0N,24,22^FDCHOCO ZUMA^FS",
                "^FO20,48^A0N,32,28^FB400,2,2,L^FD%s^FS" % name,
                "^FO20,%d^GB400,2,2^FS" % (118 + d),
                "^FO20,%d^A0N,22,20^FDParti: %s^FS" % (128 + d, _zpl_text(ref)),
                "^FO20,%d^A0N,22,20^FDÜretim: %s^FS" % (152 + d, produced_txt),
                skt_line % (178 + d),
                "^FO20,%d^A0N,22,20^FD%s^FS" % (216 + d, store_line),
            ]
            y = 242 + d  # free rows above the barcode (barcode starts at 266)
            if thaw_box and y + 22 <= 264:
                z.append("^FO20,%d^A0N,22,20^FDDondurucudan çıkış: ___/___/______^FS" % y)
                y += 26
            if allergens and y + 17 <= 264:
                z.append("^FO20,%d^A0N,17,16^FB300,1,0,L^FDAlerjen: %s^FS" % (y, _zpl_text(allergens)))
            z += [
                "^FO330,%d^BQN,2,3^FDLA,%s|%s|SKT %s^FS" % (116 + d, code, batch, skt_txt),
                "^FO20,266^BY2,2.5,34^BCN,34,N,N,N^FD%s^FS" % batch,
                "^FO344,262^A0N,36,32^FD#K#^FS",
                "^XZ",
            ]
            return "\n".join(z)

        skt = (local + timedelta(days=fresh)).strftime("%d.%m.%Y")
        line["fresh_txt"] = "SKT %s · %s" % (skt, WHERE_SHORT[where])
        line["fresh_zpl"] = zpl("^FO20,%%d^A0N,34,30^FDSKT: %s^FS" % skt, WHERE_LABEL[where], skt)
        if frozen:
            fskt = (local + timedelta(days=frozen)).strftime("%d.%m.%Y")
            line["frozen_txt"] = "Donuk SKT %s · çözünce %d gün (%s)" % (
                fskt, fresh, WHERE_SHORT[where].lower())
            line["frozen_zpl"] = zpl(
                "^FO20,%%d^A0N,30,26^FDDonuk SKT: %s^FS" % fskt,
                "Çözünce: %d gün · %s" % (fresh, WHERE_SHORT[where]), fskt, thaw_box=True)
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

    def action_cz_print_label(self):
        """One button for every MO: a lot-tracked product (B2B CZ-...) opens the existing lot label
        (cz.lot_rawbt, with lot / SKT from the lot); every other product opens the kitchen label."""
        self.ensure_one()
        if self.product_id.tracking != "none" and self.lot_producing_id:
            lot_report = self.env["ir.actions.report"].sudo().search(
                [("report_name", "=", "cz.lot_rawbt")], limit=1)
            if lot_report:
                return lot_report.report_action(self.lot_producing_id)
        return self.env.ref("cz_inventory_dashboard.action_report_cz_mo_label").report_action(self)

