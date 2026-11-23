# -*- coding: utf-8 -*-
"""Daily branch manager report (Turkish) — pure-Python renderer, no Odoo import.

One page, Kayaşehir | Metrokent side by side. Order of a column = order of the manager's day:
1. the day against its target and the month pace, 2. what to do today (red items only),
3. control: leakage in TL (discounts by reason, ikram vs cap, staff, cancels, open orders),
4. channels, 5. load by hour (staffing), 6. top items.
Cash differences, refunds and cashier rankings stay in the CEO brief (policy of 21.11.2026).
"""
from .marketing_render import CSS, FONTS, WD, h, header, notes

REASON = {
    "IKRAM": "İkram (yönetim/misafir)", "PERSONEL": "Personel indirimi", "SADAKAT": "Sadakat",
    "SIKAYET": "Şikayet telafisi", "KAMPANYA": "Kampanya", "PLATFORM": "Platform fiyat farkı",
    "DAIMI": "Daimi müşteri", "FIYAT": "Fiyat düzeltme", "OTHER": "Diğer", "": "SEBEPSİZ",
}

EXTRA = """
.mk .act{background:#fbeee7;border:1px solid #e2b9a6;border-left:5px solid #b5532e;padding:7px 11px;margin-top:8px;}
.mk .act .t{font-family:'CZMessiri','CZLatin',sans-serif;font-weight:bold;color:#b5532e;font-size:13px;}
.mk .good{background:#eef7ee;border:1px solid #bfe0bf;border-left:5px solid #1e8449;padding:7px 11px;margin-top:8px;}
.mk .good .t{font-family:'CZMessiri','CZLatin',sans-serif;font-weight:bold;color:#1e8449;font-size:13px;}
.mk .act div.i,.mk .good div.i{padding:1.5px 0;}
.mk .tb td{padding:2.5px 4px;font-size:10.5px;border-bottom:1px dotted #e3d6bd !important;}
.mk .tb td.n{text-align:right;white-space:nowrap;}
.mk .tb td.r{text-align:right;white-space:nowrap;color:#b5532e;font-weight:bold;}
.mk .tb td.g{text-align:right;white-space:nowrap;color:#1e8449;font-weight:bold;}
.mk .tb td.m{color:#7a6652;font-size:9.5px;text-align:right;white-space:nowrap;padding-right:8px;}
.mk .bar2{height:7px;background:#efe6d3;margin-top:3px;}
.mk .bar2 div{height:7px;}
.mk .hr td{text-align:center;font-size:9px;padding:1px 0;}
"""


def num(v):
    return "{:,.0f}".format(round(v or 0)).replace(",", ".")


def tl(v):
    return "%s TL" % num(v)


def pct(v):
    return "%%%s" % ("{:.0f}".format(v) if v is not None else "–")


def chg(cur, prev):
    if not prev:
        return "–"
    v = (cur - prev) / float(prev) * 100.0
    return "%s%.0f%%" % ("+" if v >= 0 else "−", abs(v))


def day_txt(d):
    return d.strftime("%d.%m.%Y")


def summary(data):
    """WhatsApp template {{2}}: one line, both branches."""
    parts = []
    for b in data["branches"]:
        t = (" (hedef %%%.0f)" % b["target_pct"]) if b.get("target_pct") is not None else ""
        parts.append("%s %s%s" % (b["short"], tl(b["net"]), t))
    return " · ".join(parts) or "satış yok"


def actions_count(data):
    n = sum(len(b["actions"]) for b in data["branches"])
    return "%d madde" % n if n else "kritik konu yok"


def render_text(data):
    out = ["Choco Zuma · Şube Raporu · %s (%s)" % (day_txt(data["day"]), WD[data["day"].weekday()])]
    for b in data["branches"]:
        out.append("")
        out.append("— %s —" % b["short"])
        line = "Net satış %s" % tl(b["net"])
        if b.get("target_pct") is not None:
            line += " · günlük hedef %%%.0f (hedef %s)" % (b["target_pct"], tl(b["target_day"]))
        out.append(line)
        out.append("Sipariş %s · ort. sepet %s · geçen hafta aynı gün %s" % (b["orders"], tl(b["basket"]), chg(b["net"], b["lw"])))
        if b.get("month_target"):
            out.append("Ay başından %s · aylık hedef %%%.0f · kalan günlerde günlük gereken %s" % (
                tl(b["mtd"]), b["mtd_pct"], tl(b["need_per_day"])))
        if b["actions"]:
            out.append("Bugün yapılacaklar:")
            for i, a in enumerate(b["actions"], 1):
                out.append("%d) %s" % (i, a["text"]))
        else:
            out.append("Kontrol: sorun yok.")
    return "\n".join(out)


def _row(label, value, meta="", cls="n"):
    return '<tr><td>%s</td><td class="m">%s</td><td class="%s">%s</td></tr>' % (h(label), h(meta), cls, h(value))


def _column(b):
    p = ['<div class="bt">%s</div>' % h(b["short"])]
    # 1. the day
    tp = b.get("target_pct")
    color = "#1e8449" if tp is not None and tp >= 100 else ("#b9770e" if tp is not None and tp >= 85 else "#b5532e")
    k = ['<td><div class="kpi"><div class="kl">Net satış (KDV hariç)</div><div class="kv">%s</div>'
         '<div class="ks">geçen hafta aynı gün %s · 4 hf ort. %s</div></div></td>' % (tl(b["net"]), chg(b["net"], b["lw"]), chg(b["net"], b["avg4"])),
         '<td><div class="kpi"><div class="kl">Günlük hedef</div><div class="kv" style="color:%s">%s</div>'
         '<div class="ks">hedef %s</div></div></td>' % (color, pct(tp) if tp is not None else "–", tl(b["target_day"]) if b["target_day"] else "tanımsız"),
         '<td><div class="kpi"><div class="kl">Sipariş · ort. sepet</div><div class="kv">%s</div>'
         '<div class="ks">ort. sepet %s</div></div></td>' % (b["orders"], tl(b["basket"]))]
    p.append('<table class="kpis" style="table-layout:fixed;"><tr>%s</tr></table>' % "".join(k))
    if b.get("month_target"):
        w = max(2, min(100, int(round(b["mtd_pct"] or 0))))
        exp = max(0, min(100, int(round(b["mtd_expected_pct"] or 0))))
        bar_color = "#1e8449" if b["mtd_pct"] >= b["mtd_expected_pct"] else "#b5532e"
        p.append(
            '<div class="box"><div class="st">Ay hedefi <small>%s</small></div>'
            '<table class="tb">%s%s%s</table>'
            '<div class="bar2"><div style="width:%d%%;background:%s"></div></div>'
            '<div class="note">Bugüne kadar olması gereken: %%%d · olan: %%%.0f</div></div>' % (
                tl(b["month_target"]),
                _row("Ay başından net satış", tl(b["mtd"]), "%d gün" % b["mtd_days"]),
                _row("Hedefe kalan", tl(max(0.0, b["month_target"] - b["mtd"])), "%d gün kaldı" % b["days_left"]),
                _row("Kalan günlerde günlük gereken", tl(b["need_per_day"]),
                     "son 4 haftanın günlük ort. %s" % tl(b["avg_daily"]),
                     "r" if b["need_per_day"] > b["avg_daily"] * 1.05 else "g"),
                w, bar_color, exp, b["mtd_pct"]))
    # 2. today's actions
    if b["actions"]:
        p.append(notes("act", "Bugün yapılacaklar", [h(a["text"]) for a in b["actions"]]))
    else:
        p.append(notes("good", "Kontrol", ["Dün kontrol edilen konularda sorun yok."]))
    # 3. control
    rows = []
    for code, val, n in b["discounts"]:
        rows.append(_row(REASON.get(code, code), tl(val), "%d satır" % n, "r" if code == "" else "n"))
    rows.append(_row("İkram (maliyet)", tl(b["ikram_cost"]), "sınır %s = net satış × %%%s" % (
        tl(b["ikram_cap"]), ("%.1f" % b["ikram_cap_pct"]).replace(".", ",")), "r" if b["ikram_cost"] > b["ikram_cap"] else "g"))
    rows.append(_row("Personel yemeği", "%d sipariş" % b["staff_orders"], "menü fiyatıyla %s" % tl(b["staff_value"])))
    rows.append(_row("İptal", "%d · %s" % (b["cancel_n"], tl(b["cancel_value"])),
                     "%d tanesinin sebebi yok" % b["cancel_no_reason"] if b["cancel_no_reason"] else "hepsi sebepli",
                     "r" if b["cancel_no_reason"] else "n"))
    rows.append(_row("Kapanışta açık kalan sipariş", "%d · %s" % (b["open_n"], tl(b["open_value"])), "",
                     "r" if b["open_n"] else "g"))
    p.append('<div class="box"><div class="st">Kontrol <small>kaçak = indirim + ikram + iptal</small></div>'
             '<table class="tb">%s</table><div class="note">Toplam indirim %s · net satışa oranı %%%s</div></div>' % (
                 "".join(rows), tl(b["discount_total"]), ("%.1f" % b["discount_pct"]).replace(".", ",")))
    # 4. channels
    rows = [_row(name, tl(net), "%d sipariş · %%%.0f" % (n, (net / b["sales_net"] * 100.0) if b["sales_net"] else 0))
            for name, n, net in b["channels"]]
    p.append('<div class="box"><div class="st">Kanallar</div><table class="tb">%s</table></div>' % "".join(rows))
    # 5. hours
    if b["hours"]:
        mx = max(v for _hr, v, _a in b["hours"]) or 1
        cells, labels = [], []
        for hr, v, avg in b["hours"]:
            hi = avg and v > avg * 1.3
            lo = avg and v < avg * 0.7
            col = "#b5532e" if hi else ("#c8bba4" if lo else "#c9a24a")
            cells.append('<td style="vertical-align:bottom;height:46px;"><div style="background:%s;height:%dpx;margin:0 1px;"></div></td>' % (
                col, max(2, int(round(v / float(mx) * 44)))))
            labels.append("<td>%02d<br/>%d</td>" % (hr % 24, v))
        p.append('<div class="box"><div class="st">Saatlik sipariş <small>kırmızı: normalin %%130 üstü · gri: %%70 altı</small></div>'
                 '<table class="hr" style="table-layout:fixed;"><tr>%s</tr><tr>%s</tr></table></div>' % ("".join(cells), "".join(labels)))
    # 6. top items
    rows = [_row(name, tl(net), "%s adet" % num(qty)) for name, qty, net, _m in b["top"][:5]]
    p.append('<div class="box"><div class="st">En çok satan 5 ürün</div><table class="tb">%s</table></div>' % "".join(rows))
    return "".join(p)


def render_html(data, font_base="/cz_whatsapp_reports/static/src/fonts/", zoom=0.75):
    d = data["day"]
    br = data["branches"]
    p = ["<style>%s%s%s</style>" % (FONTS % {"base": font_base}, CSS, EXTRA), '<div class="mk" style="zoom:%s;">' % zoom]
    p.append('<div class="page">')
    p.append(header("Choco Zuma", "Şube Raporu · Günlük", WD[d.weekday()], day_txt(d)))
    cols = ['<div class="colL">%s</div>' % _column(br[0])] if br else []
    if len(br) > 1:
        cols.append('<div class="colR">%s</div>' % _column(br[1]))
    p.append('<div class="wrap">%s<div class="clr"></div></div>' % "".join(cols))
    p.append('<div class="foot">Kaynak: Odoo POS. Tutarlar KDV hariç net TL; gün 06:00\'da başlar. Günlük hedef aylık hedefin, '
             'son 8 haftanın gün ağırlığına göre dağıtılmasıdır. İkram = ikram ürünlerinin maliyeti + "İkram" sebepli '
             'indirimlerin maliyeti. Kasa farkı, iadeler ve kasiyer sıralaması yönetim raporundadır.</div>')
    p.append("</div></div>")
    return "".join(p)
