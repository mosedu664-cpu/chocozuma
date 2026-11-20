# -*- coding: utf-8 -*-
"""Daily kitchen + depot stock report (Turkish) — pure-Python HTML renderer, no Odoo import.

Input: the snapshot of ``stock.warehouse._cz_kitchen_snapshot()`` (module cz_inventory_dashboard),
the same data the chefs see on the "Mutfak & Depo Stok" screen.
Page 1 = decisions for today (alerts with the exact quantity to act on); following pages =
the full stock table, kitchen | depot freezer | depot chiller side by side.
"""
from datetime import datetime

from .marketing_render import CSS, FONTS, WD, h, header, notes

FAMILY = [("1_b2b", "B2B Hazır Ürünler"), ("2_semi", "Yarı Mamul (Mutfak)"), ("3_other", "Diğer — depoda olanlar")]

EXTRA_CSS = """
.mk .ok{background:#eef7ee;border:1px solid #bfe0bf;border-left:5px solid #1e8449;padding:7px 11px;margin-top:8px;}
.mk .ok .t{font-family:'CZMessiri','CZLatin',sans-serif;font-weight:bold;color:#1e8449;font-size:13px;}
.mk .dat{background:#f3f1fd;border:1px solid #cfc8f3;border-left:5px solid #6c5ce7;padding:7px 11px;margin-top:8px;}
.mk .dat .t{font-family:'CZMessiri','CZLatin',sans-serif;font-weight:bold;color:#6c5ce7;font-size:13px;}
.mk .dat div.i,.mk .ok div.i{padding:1px 0;}
.mk .st2{font-family:'CZMessiri','CZLatin',sans-serif;font-weight:bold;font-size:14px;color:#1c110a;margin:12px 0 2px 0;
  border-bottom:2px solid #c9a24a;padding-bottom:2px;}
.mk .tb td,.mk .tb th{padding:3px 5px;font-size:10.5px;border-bottom:1px dotted #e3d6bd !important;}
.mk .tb th{font-size:9.5px;color:#7a6652;text-align:right;white-space:nowrap;border-bottom:1px solid #c9a24a !important;}
.mk .tb th.l{text-align:left;}
.mk .tb td.nm{width:34%;}
.mk .tb td.nm .c{color:#7a6652;font-size:9.5px;}
.mk .tb td.nm .u{color:#7a6652;font-size:9px;}
.mk .tb td.n{text-align:right;white-space:nowrap;}
.mk .tb td.z{text-align:right;color:#c8bba4;}
.mk .tb td.dep{text-align:right;color:#1f6f8b;font-weight:bold;white-space:nowrap;}
.mk .tb td.tot{text-align:right;font-weight:bold;white-space:nowrap;}
.mk .tb td.neg{text-align:right;color:#6c5ce7;font-weight:bold;white-space:nowrap;}
.mk .tb td.bad{text-align:right;color:#b5532e;font-weight:bold;white-space:nowrap;}
.mk .tb td.warn{text-align:right;color:#b9770e;font-weight:bold;white-space:nowrap;}
.mk .tb tr.fl td.nm{font-weight:bold;}
.mk .b{font-weight:bold;}
"""


def q(v):
    """Quantity in Turkish style: 1.234,5 — up to 2 decimals, trailing zeros removed."""
    if v is None:
        return "–"
    a = abs(v)
    d = 0 if a >= 100 else (1 if a >= 10 else 2)
    s = ("{:,.%df}" % d).format(v)
    if d:
        s = s.rstrip("0").rstrip(".")
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def age(r):
    vals = [a for a in (r.get("age_kitchen"), r.get("age_depot")) if a is not None]
    if not vals:
        return None
    return max(vals)


def age_txt(r):
    a = age(r)
    if a is None:
        return "–"
    return "bugün" if a < 1 else "%d g" % int(a)


def label(r):
    return "<b>%s</b> %s" % (h(r["code"]), h(r["name"])) if r["code"] else "<b>%s</b>" % h(r["name"])


def summary(snap):
    """One line for the WhatsApp template ({{2}}) — no line breaks allowed there."""
    a = snap["alerts"]
    parts = []
    for key, txt in (("shortage", "siparişe yetmiyor"), ("produce", "üretilmeli"), ("fetch", "depodan getirilmeli")):
        if a[key]:
            parts.append("%d %s" % (len(a[key]), txt))
    shelf = len(a["expired"]) + len(a["expiring"])
    if shelf:
        parts.append("%d raf ömrü uyarısı" % shelf)
    if a["transit"]:
        parts.append("%d bekleyen transfer" % len(a["transit"]))
    return ", ".join(parts) if parts else "acil uyarı yok"


def stocked(rows, key):
    return sum(1 for r in rows if r[key] > 0)


def alert_lines(snap):
    by_id = {r["id"]: r for r in snap["rows"]}
    a = snap["alerts"]

    def rows_of(key, sort=None):
        rs = [by_id[i] for i in a[key] if i in by_id]
        return sorted(rs, key=sort) if sort else rs

    out = {}
    out["shortage"] = [
        "%s — 2 gün içinde gereken <b>%s</b>, stok %s → eksik <b>%s %s</b>"
        % (label(r), q(r["demand"]), q(r["total"]), q(r["short"]), h(r["uom"]))
        for r in rows_of("shortage", lambda r: -(r["short"] / (r["demand"] or 1)))
    ]
    out["produce"] = [
        "%s — stok %s / hedef en az %s → <b>%s %s üret</b>"
        % (label(r), q(r["total"]), q(r["min"]), q(r["to_make"]), h(r["uom"]))
        for r in rows_of("produce")
    ]
    out["fetch"] = [
        "%s — mutfakta %s (günde %s kullanılıyor), depoda %s → <b>%s %s getir</b>"
        % (label(r), q(r["kitchen"]), q(r["kitchen_use_day"]), q(r["depot"]), q(r["fetch"]), h(r["uom"]))
        for r in rows_of("fetch")
    ]
    out["shelf"] = [
        "%s — en eski parti <b>%s</b>, raf ömrü %d gün%s"
        % (label(r), age_txt(r), r["shelf"], " · <b>SÜRESİ DOLDU</b>" if "expired" in r["flags"] else "")
        for r in rows_of("expired") + rows_of("expiring")
    ]
    out["transit"] = [
        "<b>%s</b> (%s) — %d saattir doğrulanmadı, %d satır" % (h(t["name"]), h(t["type"]), t["hours"], t["lines"])
        for t in a["transit"]
    ]
    out["depot_consumed"] = [
        "%s — %s %s, %s" % (h(c["product"]), q(c["qty"]), h(c["uom"]), h(c["mo"]))
        for c in a["depot_consumed"][:12]
    ]
    neg = rows_of("negative")
    out["negative"] = [
        "%s — mutfak %s%s" % (label(r), q(r["kitchen"]), (", depo %s" % q(r["depot"])) if r["depot"] else "")
        for r in sorted(neg, key=lambda r: r["kitchen"] + r["depot"])[:15]
    ]
    out["negative_more"] = max(0, len(neg) - 15)
    out["no_zone"] = [label(by_id[i]) for i in a["no_zone"] if i in by_id]
    return out


def table(rows):
    p = ['<table class="tb"><tr><th class="l">Ürün</th><th>Mutfak</th><th>Depo Dondurucu</th><th>Depo Soğuk</th>'
         '<th>Toplam</th><th>Rezerve</th><th>Günlük çıkış</th><th>Kaç gün</th><th>En eski</th></tr>']
    for r in rows:
        def cell(v, cls_pos="n"):
            if v < 0:
                return '<td class="neg">%s</td>' % q(v)
            if not v:
                return '<td class="z">–</td>'
            return '<td class="%s">%s</td>' % (cls_pos, q(v))

        days = r["days"]
        dcls = "z" if days is None else ("bad" if days < 1 else ("warn" if days < 2 else "n"))
        a = age(r)
        acls = "n"
        if r["shelf"] and a is not None:
            acls = "bad" if a >= r["shelf"] else ("warn" if a >= 0.75 * r["shelf"] else "n")
        depot_chill = r["chill"] + r["depot_other"]
        p.append(
            '<tr class="%s"><td class="nm"><span class="c">%s</span> %s <span class="u">· %s</span></td>%s%s%s%s%s%s<td class="%s">%s</td><td class="%s">%s</td></tr>'
            % ("fl" if r["flags"] else "", h(r["code"]), h(r["name"]), h(r["uom"]),
               cell(r["kitchen"]), cell(r["freezer"], "dep"), cell(depot_chill, "dep"), cell(r["total"], "tot"),
               cell(r["reserved"]), cell(r["use_day"]), dcls, "–" if days is None else q(days), acls, age_txt(r))
        )
    p.append("</table>")
    return "".join(p)


def render_html(snap, font_base="/cz_whatsapp_reports/static/src/fonts/", zoom=0.75):
    rows = snap["rows"]
    dt = datetime.strptime(snap["as_of"], "%d.%m.%Y %H:%M")
    al = alert_lines(snap)
    urgent = len(snap["alerts"]["shortage"]) + len(snap["alerts"]["produce"]) + len(snap["alerts"]["expired"])
    p = ["<style>%s%s%s</style>" % (FONTS % {"base": font_base}, CSS, EXTRA_CSS), '<div class="mk" style="zoom:%s;">' % zoom]
    p.append('<div class="page">')
    p.append(header("Choco Zuma", "Mutfak &amp; Depo Stok Raporu · Bugün yapılacaklar", WD[dt.weekday()], h(snap["as_of"])))

    kpis = [
        ("Takip edilen ürün", str(len(rows)), "şef takibi + depodaki her ürün"),
        ("Mutfakta stoklu", str(stocked(rows, "kitchen")), "ürün çeşidi"),
        ("Depoda stoklu", str(sum(1 for r in rows if r["depot"] > 0)),
         "%d dondurucu · %d soğuk oda" % (stocked(rows, "freezer"), stocked(rows, "chill"))),
        ("Acil uyarı", str(urgent), "yetmiyor + üretilmeli + süresi dolan"),
    ]
    cells = "".join('<td><div class="kpi"><div class="kl">%s</div><div class="kv">%s</div><div class="ks">%s</div></div></td>'
                    % (h(a), h(b), h(c)) for a, b, c in kpis)
    p.append('<div class="wrap"><table class="kpis"><tr>%s</tr></table>' % cells)

    left, right = [], []
    left.append(notes("ins", "Siparişe yetmiyor — önümüzdeki 2 gün", al["shortage"]))
    left.append(notes("ins", "Üretilmeli — hedef stok altında", al["produce"]))
    left.append(notes("ins", "Raf ömrü", al["shelf"]))
    right.append(notes("act", "Depodan mutfağa getir", al["fetch"]))
    right.append(notes("act", "Bekleyen Mutfak ↔ Depo transferleri", al["transit"]))
    if al["depot_consumed"]:
        right.append(notes("act", "Üretimde doğrudan depodan tüketildi — transfer kaydı unutulmuş olabilir", al["depot_consumed"]))
    if not any(al[k] for k in ("shortage", "produce", "shelf", "fetch", "transit")):
        left.insert(0, '<div class="ok"><div class="t">Bugün acil uyarı yok</div><div class="i">Tüm siparişler stokla karşılanıyor, '
                       'hedef altı ürün ve süresi dolan parti yok.</div></div>')
    if al["negative"]:
        more = (" · ve %d ürün daha (tam liste tabloda)" % al["negative_more"]) if al["negative_more"] else ""
        right.append('<div class="dat"><div class="t">Eksi stok — sayım gerekli (%d ürün)</div>%s<div class="i" style="color:#7a6652;">'
                     'Eksi stok, üretim veya transfer kaydı eksik demektir. Sayımdan sonra bu liste boşalır.%s</div></div>'
                     % (len(snap["alerts"]["negative"]), "".join('<div class="i">• %s</div>' % x for x in al["negative"]), more))
    if al["no_zone"]:
        right.append('<div class="dat"><div class="t">Depo bölgesi seçilmemiş</div><div class="i">%s</div></div>' % ", ".join(al["no_zone"][:12]))
    p.append('<div class="colL">%s</div><div class="colR">%s</div><div class="clr"></div></div>' % ("".join(left), "".join(right)))
    p.append(_foot(snap) + "</div>")

    p.append('<div class="page pb">')
    p.append(header("Choco Zuma", "Mutfak &amp; Depo Stok Raporu · Tam liste", "mutfak | depo yan yana", h(snap["as_of"])))
    p.append('<div class="wrap">')
    for fam, title in FAMILY:
        fam_rows = [r for r in rows if r["family"] == fam]
        live = [r for r in fam_rows if r["total"] or r["kitchen"] or r["depot"] or r["use_day"] or r["demand"]]
        if not live:
            continue
        idle = len(fam_rows) - len(live)
        p.append('<div class="st2">%s <small style="font-weight:normal;font-size:10px;color:#7a6652;">%d ürün%s</small></div>'
                 % (title, len(live), (" · stoksuz ve hareketsiz %d ürün gösterilmedi" % idle) if idle else ""))
        p.append(table(live))
    p.append("</div>" + _foot(snap) + "</div></div>")
    return "".join(p)


def _foot(snap):
    return ('<div class="foot">Kaynak: Odoo stok (canlı, %s). Mutfak = Merkez Mutfak rafları; Depo = ana depodaki mutfak ürünleri '
            '(dondurucu, soğuk oda). Günlük çıkış: son %d günde mutfak+depodan çıkan miktar (sipariş, üretim tüketimi, fire) ÷ %d; '
            'sayım düzeltmeleri hariç. "Kaç gün" = toplam stok ÷ günlük çıkış. "En eski" = rafta en uzun duran partinin yaşı. '
            'Hedef stok: Odoo ikmal kuralları (en az / en çok). Miktarlar ürünün kendi biriminde.</div>'
            % (h(snap["as_of"]), snap["usage_days"], snap["usage_days"]))


def render_text(snap):
    a = snap["alerts"]
    lines = ["Choco Zuma · Mutfak & Depo Stok · %s" % snap["as_of"], "Uyarılar: %s" % summary(snap)]
    by_id = {r["id"]: r for r in snap["rows"]}
    for key, title in (("shortage", "Siparişe yetmiyor"), ("produce", "Üretilmeli"), ("fetch", "Depodan getir")):
        if a[key]:
            names = ", ".join((by_id[i]["code"] or by_id[i]["name"]) for i in a[key][:8] if i in by_id)
            lines.append("%s: %s" % (title, names))
    lines.append("Eksi stok (sayım gerekli): %d ürün" % len(a["negative"]))
    return "\n".join(lines)
