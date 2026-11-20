# -*- coding: utf-8 -*-
"""Mutfak İş Kartı — the chefs' one-page morning work card (Turkish), pure-Python HTML, no Odoo import.

One message replaces the separate stock and kitchen-orders reports. Page 1 is written in the order the
work is done and printed to be ticked: ① produce, ② move between kitchen and depot, ③ today's
shipments, ④ watch-outs, then a signature line. Following pages are reference only: the full
production list, the full stock table and yesterday's orders.

Input: ``snap`` = ``stock.warehouse._cz_kitchen_snapshot()`` with ``snap["orders"]`` = the kitchen-only
``cz.wa.report._orders_data()`` (open delivery moves from the kitchen, stock = kitchen + depot).
"""
from datetime import datetime, timedelta

from . import kitchen_render as kr
from .marketing_render import CSS, FONTS, WD, h, header
from .orders_render import ORDER_CSS, _order_card

MAX_PRODUCE, MAX_SHIP = 12, 10

WC_CSS = """
.mk .tiles td{padding:0 3px;} .mk .tiles td:first-child{padding-left:0;} .mk .tiles td:last-child{padding-right:0;}
.mk .tile{border:1px solid #e3d6bd;background:#fdfaf4;padding:6px 9px 5px 9px;margin-top:9px;}
.mk .tile .l{font-size:10px;color:#7a6652;} .mk .tile .v{font-family:'CZMessiri','CZLatin',sans-serif;font-size:21px;line-height:1.2;font-weight:bold;color:#1c110a;white-space:nowrap;}
.mk .tile .s{font-size:9.5px;color:#7a6652;}
.mk .tile.red{background:#fbeee7;border-color:#e2b9a6;} .mk .tile.red .l,.mk .tile.red .v,.mk .tile.red .s{color:#b5532e;}
.mk .tile.amb{background:#fdf3dc;border-color:#ecd39a;} .mk .tile.amb .l,.mk .tile.amb .v,.mk .tile.amb .s{color:#9a6a07;}
.mk .tile.ok{background:#eef7ee;border-color:#bfe0bf;} .mk .tile.ok .l,.mk .tile.ok .v,.mk .tile.ok .s{color:#1e8449;}
.mk .sec{margin:13px 0 2px 0;}
.mk .sec td{vertical-align:middle;}
.mk .sec .n{width:24px;}
.mk .sec .n div{width:20px;height:20px;line-height:20px;text-align:center;background:#1c110a;color:#c9a24a;font-weight:bold;font-size:12px;border-radius:10px;}
.mk .sec .t{font-family:'CZMessiri','CZLatin',sans-serif;font-weight:bold;font-size:15px;color:#1c110a;}
.mk .sec .t small{font-family:'CZLatin',sans-serif;font-weight:normal;font-size:10.5px;color:#7a6652;}
.mk .wl td{border-top:1px solid #eadfca !important;padding:5px 0 4px 0;vertical-align:middle;}
.mk .wl td.cb{width:24px;} .mk .wl td.cb div{width:13px;height:13px;border:1.6px solid #1c110a;border-radius:2px;}
.mk .wl td.it{font-size:12px;} .mk .wl td.it .c{color:#7a6652;font-size:10.5px;} .mk .wl td.it .sb{font-size:10px;color:#7a6652;}
.mk .wl td.qt{width:112px;text-align:right;white-space:nowrap;font-family:'CZMessiri','CZLatin',sans-serif;font-weight:bold;font-size:16px;color:#1c110a;padding-right:10px;}
.mk .wl td.qt span{font-family:'CZLatin',sans-serif;font-weight:normal;font-size:10.5px;color:#7a6652;}
.mk .wl td.tg{width:128px;}
.mk .tg span{display:inline-block;font-size:10px;padding:1px 7px;border-radius:9px;background:#f1ece2;color:#5f4b3a;white-space:nowrap;}
.mk .tg span.red{background:#fbeee7;color:#b5532e;font-weight:bold;} .mk .tg span.amb{background:#fdf3dc;color:#9a6a07;}
.mk .tg span.ok{background:#eef7ee;color:#1e8449;}
.mk .more{font-size:10px;color:#7a6652;padding:3px 0 0 24px;}
.mk .none{font-size:11px;color:#1e8449;padding:4px 0 0 24px;}
.mk .watch div{padding:2px 0 2px 24px;font-size:11px;}
.mk .watch b.r{color:#b5532e;}
.mk .sign{margin-top:16px;border-top:2px solid #1c110a;padding-top:7px;font-size:11px;color:#5f4b3a;}
.mk .sign td{width:33%;}
"""


def _dt(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M") if s else None


def _due_tag(due, late, now):
    d = _dt(due)
    if not d:
        return "", "tarihsiz"
    if late:
        return "red", "gecikmiş · %s" % d.strftime("%d.%m")
    if d.date() == now.date():
        return "red", "bugün %s" % d.strftime("%H:%M")
    if d.date() == now.date() + timedelta(days=1):
        return "amb", "yarın %s" % d.strftime("%H:%M")
    return "", "%s %s" % (WD[d.weekday()][:3], d.strftime("%d.%m"))


def _item(code, name):
    return ('<span class="c">%s</span> %s' % (h(code), h(name))) if code else h(name)


def _row(main, sub, qty, uom, tag_cls, tag):
    return ('<tr><td class="cb"><div></div></td><td class="it">%s%s</td><td class="qt">%s <span>%s</span></td>'
            '<td class="tg"><span class="%s">%s</span></td></tr>'
            % (main, ('<div class="sb">%s</div>' % sub) if sub else "", qty, h(uom), tag_cls, h(tag)))


def _sec(n, title, hint=""):
    return ('<table class="sec"><tr><td class="n"><div>%s</div></td><td class="t">%s%s</td></tr></table>'
            % (n, title, (" <small>— %s</small>" % hint) if hint else ""))


def build(snap):
    """Every list of the card, computed once (shared by the PDF, the preview text and the WhatsApp line)."""
    od = snap["orders"]
    now = _dt(od["now_local"])
    by_id = {r["id"]: r for r in snap["rows"]}
    al = snap["alerts"]

    # ① produce — orders first (earliest delivery first), then stock needs the orders don't already cover
    produce = []
    for x in sorted((x for x in od["products"] if x["made"] and x["short"] > 0),
                    key=lambda x: (not x["late"], x["due"] or "9999", x["code"])):
        cls, tag = _due_tag(x["due"], x["late"], now)
        names = ", ".join(x["names"][:3]) + (" +%d" % (len(x["names"]) - 3) if len(x["names"]) > 3 else "")
        produce.append({"code": x["code"], "main": _item(x["code"], x["name"]), "qty": kr.q(x["short"]), "uom": x["uom"],
                        "sub": "teslim edilecek %s · stok %s · %s" % (kr.q(x["qty"]), kr.q(x["stock"]), h(names)),
                        "cls": cls, "tag": tag})
    covered = {p["code"] for p in produce}
    for i in al["shortage"]:
        r = by_id.get(i)
        if r and r["code"] not in covered:
            covered.add(r["code"])
            produce.append({"code": r["code"], "main": _item(r["code"], r["name"]), "qty": kr.q(r["short"]), "uom": r["uom"],
                            "sub": "2 gün içinde gereken %s (üretim / şube transferi) · stok %s" % (kr.q(r["demand"]), kr.q(r["total"])),
                            "cls": "amb", "tag": "2 gün içinde"})
    for i in al["produce"]:
        r = by_id.get(i)
        if r and r["code"] not in covered:
            covered.add(r["code"])
            produce.append({"code": r["code"], "main": _item(r["code"], r["name"]), "qty": kr.q(r["to_make"]), "uom": r["uom"],
                            "sub": "hedef stok altında · stok %s, en az %s" % (kr.q(r["total"]), kr.q(r["min"])),
                            "cls": "", "tag": "stok için"})

    # ② move
    move = []
    for i in al["fetch"]:
        r = by_id.get(i)
        if r:
            src = "Dondurucu" if r["freezer"] >= r["chill"] else "Soğuk Oda"
            move.append({"main": "Depodan getir · " + _item(r["code"], r["name"]), "qty": kr.q(r["fetch"]), "uom": r["uom"],
                         "sub": "%s → Mutfak · mutfakta %s, günde %s kullanılıyor" % (src, kr.q(r["kitchen"]), kr.q(r["kitchen_use_day"])),
                         "cls": "", "tag": "üretimden önce"})
    for t in al["transit"]:
        move.append({"main": "Bekleyen transferi tamamla · <b>%s</b>" % h(t["name"]), "qty": str(t["lines"]), "uom": "satır",
                     "sub": "%s · %d saattir doğrulanmadı" % (h(t["type"]), t["hours"]), "cls": "red", "tag": "Odoo'da doğrula"})

    # ③ ship — due today or late (or undated); later ones are counted
    today, later = [], []
    for s in od["shipments"]:
        d = _dt(s["due"])
        (today if (s["late"] or not d or d.date() <= now.date()) else later).append(s)
    ship = []
    for s in sorted(today, key=lambda s: (not s["late"], s["due"] or "")):
        d = _dt(s["due"])
        when = (d.strftime("%H:%M") if d.date() == now.date() else d.strftime("%d.%m")) if d else "–"
        partner = s["partner"] if len(s["partner"]) <= 34 else s["partner"][:32].rstrip() + "…"
        if s["missing"]:
            cls, tag = "red", "eksik: %s" % ", ".join(s["missing"][:3]) + (" +%d" % (len(s["missing"]) - 3) if len(s["missing"]) > 3 else "")
        else:
            cls, tag = "ok", "hazır"
        late_txt = ""
        if s["late"] and d:
            days = (now.date() - d.date()).days
            late_txt = "<b style=\"color:#b5532e;\">%s</b> · " % ("gecikmiş, %d gün" % days if days else "saati geçti")
        ship.append({"main": "<b>%s</b> · %s" % (h(partner), h(s["name"])), "qty": h(when), "uom": "",
                     "sub": late_txt + "%d kalem%s" % (s["lines"], (" · %d tanesi rafta yok" % len(s["missing"])) if s["missing"] else " · hepsi rezerve"),
                     "cls": cls, "tag": tag, "late": s["late"]})

    # ④ watch-outs
    watch = []
    for i in al["expired"]:
        r = by_id.get(i)
        if r:
            watch.append('<b class="r">Süresi doldu</b> · %s — en eski parti %s (raf ömrü %d gün): kullanma / fire kaydı'
                         % (_item(r["code"], r["name"]), kr.age_txt(r), r["shelf"]))
    for i in al["expiring"]:
        r = by_id.get(i)
        if r:
            watch.append("Önce bunu kullan · %s — en eski parti %s (raf ömrü %d gün)" % (_item(r["code"], r["name"]), kr.age_txt(r), r["shelf"]))
    for u in od.get("unusual") or []:
        watch.append('<b class="r">Miktarı kontrol et</b> · %s %s — %s %s (normali ~%s): üretmeden önce muhasebeye sor'
                     % (h(u["order"]), h(u["code"]), kr.q(u["qty"]), h(u["uom"]), kr.q(u["median"])))
    if al["depot_consumed"]:
        watch.append("Depodan doğrudan üretime %d tüketim — Depo → Mutfak transferi unutulmuş olabilir" % len(al["depot_consumed"]))
    if al["no_zone"]:
        watch.append("Depo bölgesi seçilmemiş: %s" % ", ".join(h(by_id[i]["code"] or by_id[i]["name"]) for i in al["no_zone"][:6] if i in by_id))
    for name in od.get("draft_deliveries") or []:
        watch.append("%s — teslimatı taslakta kalmış: teslim et veya iptal ettir" % h(name))
    if al["negative"]:
        watch.append("Eksi stok %d ürün — sayımda düzelecek (liste 2. sayfada)" % len(al["negative"]))

    late_ship = sum(1 for s in ship if s["late"])
    return {"now": now, "produce": produce, "move": move, "ship": ship, "later": later, "late_ship": late_ship,
            "watch": watch, "orders": od}


def summary(snap):
    """One line for the WhatsApp template ({{2}}) — no line breaks."""
    b = build(snap)
    parts = []
    if b["produce"]:
        parts.append("%d ürün üretilecek" % len(b["produce"]))
    if b["ship"]:
        parts.append("%d sevkiyat%s" % (len(b["ship"]), (" (%d gecikmiş)" % b["late_ship"]) if b["late_ship"] else ""))
    fetch = sum(1 for m in b["move"] if m["main"].startswith("Depodan"))
    if fetch:
        parts.append("%d depodan getirilecek" % fetch)
    if len(b["move"]) > fetch:
        parts.append("%d bekleyen transfer" % (len(b["move"]) - fetch))
    if snap["alerts"]["expired"]:
        parts.append("%d süresi dolan parti" % len(snap["alerts"]["expired"]))
    return ", ".join(parts) if parts else "acil iş yok, stok siparişlere yetiyor"


def render_text(snap):
    b = build(snap)
    lines = ["Choco Zuma · Mutfak iş kartı · %s" % snap["as_of"], "Bugün: %s" % summary(snap)]
    if b["produce"]:
        lines.append("Üret: " + ", ".join("%s %s" % (p["code"], p["qty"]) for p in b["produce"][:10]))
    if b["ship"]:
        lines.append("Sevkiyat: " + ", ".join("%s%s" % (s["main"].split("·")[-1].strip(), " (eksik)" if s["cls"] == "red" else "")
                                               for s in b["ship"][:8]))
    return "\n".join(lines)


def render_html(snap, font_base="/cz_whatsapp_reports/static/src/fonts/", zoom=0.9):
    b = build(snap)
    now = b["now"]
    od = b["orders"]
    p = ["<style>%s%s%s%s%s</style>" % (FONTS % {"base": font_base}, CSS, kr.EXTRA_CSS, ORDER_CSS, WC_CSS),
         '<div class="mk" style="zoom:%s;">' % zoom, '<div class="page">']
    p.append(header("Choco Zuma", "Mutfak İş Kartı · Merkez Mutfak", WD[now.weekday()], "%s · %s" % (now.strftime("%d.%m.%Y"), now.strftime("%H:%M"))))
    p.append('<div class="wrap">')

    n_prod, n_ship, n_move, n_watch = len(b["produce"]), len(b["ship"]), len(b["move"]), len(b["watch"])
    tiles = [
        ("red" if n_prod else "ok", "Üretilecek", "%d ürün" % n_prod, "sipariş ve stok için"),
        ("red" if b["late_ship"] else ("" if n_ship else "ok"), "Bugün sevkiyat", "%d" % n_ship,
         ("%d gecikmiş" % b["late_ship"]) if b["late_ship"] else ("sonraki günler: %d" % len(b["later"]))),
        ("amb" if n_move else "", "Taşınacak", "%d" % n_move, "mutfak ↔ depo"),
        ("amb" if n_watch else "ok", "Dikkat", "%d" % n_watch, "raf ömrü, kontrol, sayım"),
    ]
    p.append('<table class="tiles"><tr>%s</tr></table>' % "".join(
        '<td><div class="tile %s"><div class="l">%s</div><div class="v">%s</div><div class="s">%s</div></div></td>' % t for t in tiles))

    p.append(_sec(1, "Önce bunları üret", "en erken teslim üstte; miktar = teslim edilecek − mutfak+depo stoku"))
    if b["produce"]:
        p.append('<table class="wl">%s</table>' % "".join(_row(x["main"], x["sub"], x["qty"], x["uom"], x["cls"], x["tag"])
                                                       for x in b["produce"][:MAX_PRODUCE]))
        if n_prod > MAX_PRODUCE:
            p.append('<div class="more">+ %d ürün daha — tam liste 2. sayfada</div>' % (n_prod - MAX_PRODUCE))
    else:
        p.append('<div class="none">Üretilecek acil ürün yok — stok tüm siparişlere yetiyor.</div>')

    p.append(_sec(2, "Taşı", "transferi Odoo'da da yap: Mutfak &amp; Depo Stok ekranı"))
    if b["move"]:
        p.append('<table class="wl">%s</table>' % "".join(_row(x["main"], x["sub"], x["qty"], x["uom"], x["cls"], x["tag"]) for x in b["move"]))
    else:
        p.append('<div class="none">Taşınacak bir şey yok.</div>')

    p.append(_sec(3, "Bugün çıkacak sevkiyatlar", "gecikmişler üstte; \"eksik\" = rafta rezerve edilemeyen kalem"))
    if b["ship"]:
        p.append('<table class="wl">%s</table>' % "".join(_row(x["main"], x["sub"], x["qty"], x["uom"], x["cls"], x["tag"])
                                                       for x in b["ship"][:MAX_SHIP]))
        if n_ship > MAX_SHIP:
            p.append('<div class="more">+ %d sevkiyat daha</div>' % (n_ship - MAX_SHIP))
    else:
        p.append('<div class="none">Bugün çıkacak sevkiyat yok.</div>')
    if b["later"]:
        p.append('<div class="more">Sonraki günler: %s</div>' % ", ".join(
            "%s %s" % (h(s["name"]), _dt(s["due"]).strftime("%d.%m")) for s in b["later"][:8] if s["due"]))

    if b["watch"]:
        p.append(_sec(4, "Dikkat"))
        p.append('<div class="watch">%s</div>' % "".join("<div>• %s</div>" % w for w in b["watch"][:8]))

    p.append('<table class="sign"><tr><td>Şef: ______________</td><td>Başlama: ________</td>'
             '<td>Bitiş: ________</td></tr></table>')
    p.append("</div>")
    p.append('<div class="foot">Kaynak: Odoo, %s. Siparişler: onaylı satış siparişlerinin Merkez Mutfak\'tan çıkacak açık teslimatları '
             '(teslim edilmemiş tüm siparişler, dropship ve taslak teslimatlar hariç). Stok: Merkez Mutfak (mutfak + depo dondurucu + soğuk oda). '
             '"Hazır" = Odoo\'da rafta rezerve edildi.</div>' % h(snap["as_of"]))
    p.append("</div>")

    # page 2 — reference: full production list, negatives, full stock table
    p.append('<div class="page pb">')
    p.append(header("Choco Zuma", "Mutfak İş Kartı · Referans", "tam liste", h(snap["as_of"])))
    p.append('<div class="wrap">')
    if n_prod > MAX_PRODUCE:
        p.append('<div class="st2">Üretilecek — tam liste (%d ürün)</div>' % n_prod)
        p.append('<table class="wl">%s</table>' % "".join(_row(x["main"], x["sub"], x["qty"], x["uom"], x["cls"], x["tag"]) for x in b["produce"]))
    al = kr.alert_lines(snap)
    if al["negative"]:
        more = (" · ve %d ürün daha" % al["negative_more"]) if al["negative_more"] else ""
        p.append('<div class="dat"><div class="t">Eksi stok — sayımda düzelecek (%d ürün)</div>%s<div class="i" style="color:#7a6652;">'
                 'Eksi stok = üretim veya transfer kaydı eksik.%s</div></div>'
                 % (len(snap["alerts"]["negative"]), "".join('<div class="i">• %s</div>' % x for x in al["negative"]), more))
    rows = snap["rows"]
    for fam, title in kr.FAMILY:
        live = [r for r in rows if r["family"] == fam and (r["total"] or r["kitchen"] or r["depot"] or r["use_day"] or r["demand"])]
        if live:
            p.append('<div class="st2">%s <small style="font-weight:normal;font-size:10px;color:#7a6652;">%d ürün</small></div>' % (title, len(live)))
            p.append(kr.table(live))
    p.append("</div>")
    p.append(kr._foot(snap))
    p.append("</div>")

    # page 3 — yesterday's orders as they came in (kitchen lines only)
    if od["orders"]:
        p.append('<div class="page pb">')
        p.append(header("Choco Zuma", "Dünkü siparişler · mutfak kalemleri", "referans", h(od["day_txt"])))
        half = (len(od["orders"]) + 1) // 2
        p.append('<div class="wrap"><div class="colL">%s</div><div class="colR">%s</div><div class="clr"></div></div>'
                 % ("".join(_order_card(o, False) for o in od["orders"][:half]), "".join(_order_card(o, False) for o in od["orders"][half:])))
        p.append("</div>")
    p.append("</div>")
    return "".join(p)
