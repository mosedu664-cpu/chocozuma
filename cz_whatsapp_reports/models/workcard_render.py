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
    now, produce, ship, stock, expired = _simple(snap)
    parts = ["%d ürün üretilecek" % len(produce) if produce else "üretilecek ürün yok",
             "%d sipariş gönderilecek" % len(ship) if ship else "bugün gönderilecek sipariş yok"]
    if expired:
        parts.append("%d ürünün süresi doldu" % len(expired))
    return ", ".join(parts)


def render_text(snap):
    now, produce, ship, stock, expired = _simple(snap)
    lines = ["Mutfak · Bugünün işi · %s" % now.strftime("%d.%m.%Y"), summary(snap)]
    lines += ["Üret: %s %s %s (%s, %s)" % (x["name"], x["qty"], x["uom"], x["who"], x["when"]) for x in produce]
    lines += ["Gönder: %s — %s (%s)" % (x["who"], "hazır" if not x["missing"] else "%d eksik" % x["missing"], x["when"]) for x in ship]
    return "\n".join(lines)


def _simple(snap):
    """The whole card in three plain lists: produce (who, when), ship (who, ready?), ready stock (kitchen | depot)."""
    od = snap["orders"]
    now = _dt(od["now_local"])
    partner_of = {sh["name"]: sh["partner"] for sh in od["shipments"]}

    def when(due, late):
        d = _dt(due)
        if not d or late or d.date() <= now.date():
            return ("red", "Bugün") if d and not late else ("red", "Hemen")
        if d.date() == now.date() + timedelta(days=1):
            return ("", "Yarın")
        return ("", d.strftime("%d.%m"))

    def short_name(n):
        """'TONALLI GIDA SANAYI TICARET LTD' → 'Tonalli Gıda'; 'Ynéde Coffee — Muhammet' → 'Ynéde Coffee'."""
        n = (n or "").split(" — ")[0].split(",")[0].strip()
        words = n.split()
        short = " ".join(words[:2]) if len(words) > 2 else n
        return short  # kept as written in Odoo (automatic case changes break Turkish and brand names)

    produce = []
    for x in sorted((x for x in od["products"] if x["made"] and x["short"] > 0),
                    key=lambda x: (not x["late"], x["due"] or "9999", x["code"])):
        who = sorted({short_name(partner_of.get(n, n)) for n in x["names"]})
        cls, w = when(x["due"], x["late"])
        produce.append({"name": x["name"], "qty": kr.q(x["short"]), "uom": x["uom"], "who": ", ".join(who[:2]) + (" +%d" % (len(who) - 2) if len(who) > 2 else ""),
                        "cls": cls, "when": w})
    ship, by_who = [], {}
    for sh in od["shipments"]:
        cls, w = when(sh["due"], sh["late"])
        if w not in ("Hemen", "Bugün"):
            continue
        who = short_name(sh["partner"])
        if who in by_who:  # one line per customer, however many orders
            x = by_who[who]
            x["lines"] += sh["lines"]
            x["missing"] += len(sh["missing"])
            if w == "Hemen":
                x["cls"], x["when"] = cls, w
            continue
        by_who[who] = {"who": who, "lines": sh["lines"], "cls": cls, "when": w, "missing": len(sh["missing"])}
        ship.append(by_who[who])
    ship.sort(key=lambda x: (x["when"] != "Hemen", x["missing"] == 0))
    stock = [r for r in snap["rows"] if r["family"] == "1_b2b" and (r["kitchen"] > 0 or r["depot"] > 0)]
    stock.sort(key=lambda r: r["name"])
    expired = [r for r in snap["rows"] if r["id"] in snap["alerts"]["expired"]]
    return now, produce, ship, stock, expired


SIMPLE_CSS = """
.wc{font-family:'CZLatin','DejaVu Sans',sans-serif;color:#1c110a;padding:0 30px;}
.wc .top{border-bottom:3px solid #1c110a;padding:14px 0 8px 0;}
.wc .top td{vertical-align:bottom;}
.wc .ttl{font-family:'CZMessiri','CZLatin',sans-serif;font-size:26px;font-weight:bold;}
.wc .dt{text-align:right;font-size:15px;}
.wc h2{font-family:'CZMessiri','CZLatin',sans-serif;font-size:18px;margin:12px 0 3px 0;}
.wc h2 small{font-family:'CZLatin',sans-serif;font-weight:normal;font-size:12px;color:#7a6652;}
.wc table{width:100%;border-collapse:collapse;}
.wc table,.wc thead,.wc tbody{border:0 none !important;outline:0 !important;}
.wc tr,.wc td,.wc th{border-left:0 none !important;border-right:0 none !important;border-top:0 none !important;}
.wc .top td,.wc .sig td{border:0 none !important;}
.wc .l td{border-bottom:1px solid #e3d6bd;padding:4px 4px;font-size:13px;vertical-align:middle;}
.wc .l td.cb{width:26px;} .wc .l td.cb div{width:16px;height:16px;border:2px solid #1c110a;}
.wc .l td.q{width:95px;text-align:right;font-size:16px;font-weight:bold;white-space:nowrap;}
.wc .l td.q span{font-size:11px;font-weight:normal;color:#7a6652;}
.wc .l td.w{width:62px;text-align:right;font-weight:bold;}
.wc .l td.w.red{color:#c0392b;}
.wc .l td.who{color:#5f4b3a;font-size:12.5px;width:150px;}
.wc .ok{color:#1e8449;font-weight:bold;} .wc .bad{color:#c0392b;font-weight:bold;}
.wc .none{color:#1e8449;font-size:14px;padding:6px 4px;}
.wc .s td{border-bottom:1px solid #eee4d0;padding:3px 4px;font-size:12px;}
.wc .s th{font-size:11px;color:#7a6652;text-align:right;padding:2px 4px;border-bottom:1.5px solid #1c110a;}
.wc .s th.l,.wc .s td.l{text-align:left;}
.wc .s td.n{text-align:right;width:80px;} .wc .s td.z{text-align:right;width:80px;color:#c8bba4;}
.wc .warn{margin-top:14px;padding:8px 10px;border:2px solid #c0392b;color:#c0392b;font-size:13px;font-weight:bold;}
.wc .sig{margin-top:22px;font-size:13px;color:#5f4b3a;} .wc .sig td{width:50%;}
"""


def render_html(snap, font_base="/cz_whatsapp_reports/static/src/fonts/", zoom=1.0):
    """ONE page, three lists, nothing a chef has to interpret."""
    now, produce, ship, stock, expired = _simple(snap)
    p = ["<style>%s%s</style>" % (FONTS % {"base": font_base}, SIMPLE_CSS), '<div class="wc" style="zoom:%s;">' % zoom]
    p.append('<table class="top"><tr><td class="ttl">Mutfak · Bugünün işi</td><td class="dt">%s %s</td></tr></table>'
             % (WD[now.weekday()], now.strftime("%d.%m.%Y")))

    p.append("<h2>1. Üret <small>— siparişler için eksik olan</small></h2>")
    if produce:
        p.append('<table class="l">%s</table>' % "".join(
            '<tr><td class="cb"><div></div></td><td>%s</td><td class="who">%s</td><td class="q">%s <span>%s</span></td><td class="w %s">%s</td></tr>'
            % (h(x["name"]), h(x["who"]), x["qty"], h(x["uom"]), x["cls"], x["when"]) for x in produce))
    else:
        p.append('<div class="none">Üretilecek bir şey yok — stok tüm siparişlere yetiyor.</div>')

    p.append("<h2>2. Gönder <small>— bugün çıkacak siparişler</small></h2>")
    if ship:
        p.append('<table class="l">%s</table>' % "".join(
            '<tr><td class="cb"><div></div></td><td>%s</td><td class="who">%d ürün</td><td class="q" style="font-size:14px;">%s</td><td class="w %s">%s</td></tr>'
            % (h(x["who"]), x["lines"], '<span class="ok">hazır</span>' if not x["missing"] else '<span class="bad">%d eksik</span>' % x["missing"],
               x["cls"], x["when"]) for x in ship))
    else:
        p.append('<div class="none">Bugün çıkacak sipariş yok.</div>')

    p.append("<h2>3. Hazır ürün stoğu <small>— mutfak ve depo</small></h2>")
    if stock:
        p.append('<table class="s"><tr><th class="l">Ürün</th><th>Mutfak</th><th>Depo</th></tr>%s</table>' % "".join(
            '<tr><td class="l">%s <span style="color:#7a6652;font-size:11px;">%s</span></td>%s%s</tr>'
            % (h(r["name"]), h(r["uom"]),
               ('<td class="n">%s</td>' % kr.q(r["kitchen"])) if r["kitchen"] > 0 else '<td class="z">–</td>',
               ('<td class="n"><b>%s</b></td>' % kr.q(r["depot"])) if r["depot"] > 0 else '<td class="z">–</td>') for r in stock))
    else:
        p.append('<div class="none" style="color:#7a6652;">Hazır ürün stoğu yok.</div>')

    if expired:
        p.append('<div class="warn">Süresi doldu, kullanma: %s</div>' % ", ".join(h(r["name"]) for r in expired[:5]))
    p.append('<table class="sig"><tr><td>Şef: ____________________</td><td>Bitiş saati: __________</td></tr></table>')
    p.append("</div>")
    return "".join(p)
