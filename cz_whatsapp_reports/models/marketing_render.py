# -*- coding: utf-8 -*-
"""Marketing report (Turkish) - pure-Python HTML renderer, no Odoo import.

Input: the view-model built by marketing_data.build() (see that module for keys).
Layout rules for wkhtmltopdf: floats for columns, no nested tables in percentage
cells, every table border reset (no hairlines), no flexbox.
"""
from datetime import date, timedelta
from html import escape

WD = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
WD_SHORT = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
WD_PLURAL = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
DAYPARTS = [("Sabah", "11'e kadar"), ("Öğle", "11–15"), ("İkindi", "15–18"), ("Akşam", "18–22"), ("Gece", "22 sonrası")]
PLATFORMS = ("Trendyol Go", "Yemeksepeti", "Getir")
HOURS = list(range(9, 25))


def h(s):
    return escape(str(s))


def num(v):
    return "{:,.0f}".format(round(v or 0)).replace(",", ".")


def pct1(v):
    return ("%.1f" % v).replace(".", ",")


def tl(v):
    return '%s <span class="u">TL</span>' % num(v)


def chg(cur, prev):
    if not prev:
        return "–", "na"
    v = (cur - prev) / float(prev) * 100.0
    if abs(v) < 0.5:
        return "0%", "na"
    return ("%s%.0f%%" % ("+" if v > 0 else "−", abs(v))), ("up" if v > 0 else "down")


def chg_html(cur, prev):
    text, cls = chg(cur, prev)
    return '<span class="%s">%s</span>' % (cls, text)


def share(part, total):
    return (part / float(total) * 100.0) if total else 0.0


def iso_date(iso):
    y, m, d = [int(x) for x in iso.split("-")]
    return date(y, m, d)


def d_fmt(iso):
    return iso_date(iso).strftime("%d.%m.%Y")


def dm(iso):
    return iso_date(iso).strftime("%d.%m")


def js_to_mon(js):
    """JS getUTCDay index (0=Sunday) -> Monday-first index."""
    return (js + 6) % 7


def visible_dayparts(b):
    """Dayparts with at least 0.5% of the last 28 days' in-store sales (a branch closed in the morning shows no 'Sabah')."""
    tot = sum(v[0] for v in b["dp28"].values()) or 1
    return [(n, hr) for n, hr in DAYPARTS if share(b["dp28"].get(n, [0, 0])[0], tot) >= 0.5]


def avg_basket(x):
    return x["net"] / float(x["n"] or 1)


# ------------------------------------------------------------------ insights
def insights_day(b, wd_name):
    out = []
    day, avg4 = b["day"], b["avg4"]
    if avg4[2]:
        out.append("Net satış %s TL; son %s %s ortalamasına göre <b>%s</b>." % (num(day["net"]), avg4[2], wd_name, chg(day["net"], avg4[0])[0]))
    dps = visible_dayparts(b)
    dp = day["dp"]
    tot = sum(dp.get(n, [0, 0])[0] for n, _ in dps)
    if tot:
        best = max(dps, key=lambda x: dp.get(x[0], [0, 0])[0])
        out.append("Mağaza içi satışın <b>%%%.0f</b>'i %s (%s) diliminde." % (share(dp[best[0]][0], tot), best[0], best[1]))
    ch = day["ch"]
    lw = b["lw"]["ch"]
    moves = [(c[0] - lw.get(n, [0])[0], n) for n, c in ch.items() if n not in PLATFORMS]
    if moves:
        mv = max(moves, key=lambda x: abs(x[0]))
        if abs(mv[0]) >= 3000:
            out.append("Geçen %s göre en büyük kanal değişimi: <b>%s</b> %s%s TL." % (
                wd_name, mv[1], "+" if mv[0] > 0 else "−", num(abs(mv[0]))))
    if day["top"]:
        t = day["top"][0]
        out.append("Günün yıldızı: <b>%s</b> (%s adet, %s TL)." % (h(t[0]), num(t[1]), num(t[2])))
    return out


def insights_week(b):
    out = []
    w1, w0 = b["w1"], b["w0"]
    out.append("Haftalık net satış %s TL (önceki 7 güne göre <b>%s</b>), sipariş %s." % (num(w1["net"]), chg(w1["net"], w0["net"])[0], num(w1["n"])))
    if b["up"]:
        u = b["up"][0]
        out.append("En çok yükselen: <b>%s</b> (+%s TL; %s → %s adet)." % (h(u[0]), num(u[1]), num(u[3]), num(u[2])))
    if b["down"]:
        dn = b["down"][0]
        out.append("En çok düşen: <b>%s</b> (−%s TL; %s → %s adet)." % (h(dn[0]), num(abs(dn[1])), num(dn[3]), num(dn[2])))
    wd = [x[0] for x in b["wdavg"]]
    order = sorted([i for i in range(7) if b["wdavg"][i][1]], key=lambda i: wd[i])
    if order:
        out.append("Son 4 haftada en zayıf gün <b>%s</b> (ort. %s TL), en güçlü gün <b>%s</b> (ort. %s TL)." % (
            WD[js_to_mon(order[0])], num(wd[order[0]]), WD[js_to_mon(order[-1])], num(wd[order[-1]])))
    cells = []
    for js in range(7):
        for i, hour in enumerate(HOURS):
            cells.append((b["heat"][js][i], js, hour))
    cells.sort(reverse=True)
    peaks = ", ".join("%s %02d:00" % (WD_SHORT[js_to_mon(js)], hour % 24) for v, js, hour in cells[:3])
    out.append("Mağaza içi en yoğun saatler: <b>%s</b>." % peaks)
    return out


def insights_month(b):
    out = []
    m1, m0 = b["m1"], b["m0"]
    per1 = m1["net"] / float(m1["days"] or 1)
    per0 = m0["net"] / float(m0["days"] or 1)
    out.append("Günlük ortalama net satış %s TL; geçen ayın aynı günlerine göre <b>%s</b>." % (num(per1), chg(per1, per0)[0]))
    fams = []
    for name, val in m1["fam"].items():
        prev = m0["fam"].get(name, 0)
        if prev and name != "Diğer" and val >= 20000:
            fams.append(((val / float(m1["days"] or 1)) / (prev / float(m0["days"] or 1)) - 1.0, name))
    if fams:
        fams.sort()
        low = "en çok gerileyen" if fams[0][0] < 0 else "en az büyüyen"
        out.append("Ürün aileleri (günlük ortalama): en çok büyüyen <b>%s</b> (%+.0f%%), %s <b>%s</b> (%+.0f%%)." % (
            fams[-1][1], fams[-1][0] * 100, low, fams[0][1], fams[0][0] * 100))
    if m1.get("best") and m1.get("worst"):
        out.append("En iyi gün %s %s (%s TL), en zayıf gün %s %s (%s TL)." % (
            dm(m1["best"][0]), WD_SHORT[iso_date(m1["best"][0]).weekday()], num(m1["best"][1]),
            dm(m1["worst"][0]), WD_SHORT[iso_date(m1["worst"][0]).weekday()], num(m1["worst"][1])))
    if m1.get("shortDays"):
        out.append("Kısa açık kalan gün (%s) en iyi / en zayıf gün seçimine alınmadı." % ", ".join(dm(d) for d in m1["shortDays"]))
    return out


def team_notes(data):
    """Cross-branch, data-driven points (last 30 days)."""
    out = []
    brs = [data["br"][k] for k in sorted(data["br"])]
    for b in brs:
        d30 = b["d30"]
        if d30["room"] >= 200 and share(d30["roomReg"], d30["room"]) < 2:
            out.append("<b>%s</b>: Salon/Teras/Tezgah'ta son 30 günde %s siparişin yalnızca %s'inde müşteri kaydı var. "
                       "Müşteri verisi (yeni, tekrar gelen, sadakat) bugün yalnızca WhatsApp siparişlerinden geliyor." % (
                           h(b["name"]), num(d30["room"]), num(d30["roomReg"])))
    for b in brs:
        d30 = b["d30"]
        rew_n = sum(v[0] for v in d30["rew"].values())
        if rew_n:
            wa = sum(v[2].get("WhatsApp", 0) for v in d30["rew"].values())
            out.append("<b>%s</b>: son 30 günde %s sadakat ödülü kullanıldı (%s TL), bunların %s'i WhatsApp siparişinde." % (
                h(b["name"]), num(rew_n), num(sum(v[1] for v in d30["rew"].values())), num(wa)))
        elif b["d30"]["n"] >= 200:
            out.append("<b>%s</b>: son 30 günde sadakat ödülü kullanımı yok; şubede çalışan bir sadakat programı görünmüyor." % h(b["name"]))
    for b in brs:
        dps = [n for n, _ in visible_dayparts(b)]
        if "Sabah" in dps:
            tot = sum(v[0] for v in b["dp28"].values()) or 1
            s = share(b["dp28"]["Sabah"][0], tot)
            if s < 6:
                out.append("<b>%s</b>: açılıştan 11:00'e kadar olan dilim son 28 günde mağaza içi satışın yalnızca %%%s'i." % (h(b["name"]), pct1(s)))
    for b in brs:
        if b["pairs"]:
            p = b["pairs"][0]
            out.append("<b>%s</b>: en sık birlikte alınan ikili <b>%s</b> (son 30 günde %s sipariş)." % (h(b["name"]), h(p[0]), num(p[1])))
    return out


# ---------------------------------------------------------------------- css
CSS = """
html,body{margin:0;padding:0;background:#ffffff;}
.container,.container-fluid{padding:0 !important;margin:0 !important;max-width:none !important;width:100% !important;}
.mk{font-family:'CZLatin','DejaVu Sans',sans-serif;font-size:11.5px;line-height:1.45;color:#2a1b12;background:#ffffff;text-align:left;direction:ltr;}
.mk table{border-collapse:collapse;width:100%;}
.mk table,.mk thead,.mk tbody,.mk tr,.mk td,.mk th{border:0 none !important;}
.mk td,.mk th{padding:0;vertical-align:top;text-align:left;font-weight:normal;}
.mk .page{padding:0 0 10px 0;}
.mk .pb{page-break-before:always;}
.mk .head{background:#1c110a;color:#f7f1e6;padding:16px 34px 12px 34px;border-bottom:4px solid #c9a24a;}
.mk .brand{font-family:'CZMessiri','CZLatin',sans-serif;font-size:26px;line-height:1.2;color:#c9a24a;font-weight:bold;}
.mk .sub{font-size:12px;color:#e7dcc6;}
.mk .tag{font-family:'CZMessiri','CZLatin',sans-serif;font-size:20px;font-weight:bold;color:#f7f1e6;text-align:right;}
.mk .tagl{font-size:11px;color:#c9a24a;text-align:right;}
.mk .wrap{padding:12px 34px 0 34px;}
.mk .colL{float:left;width:49.3%;}
.mk .colR{float:right;width:49.3%;}
.mk .clr{clear:both;height:0;font-size:0;line-height:0;}
.mk .bt{background:#1c110a;color:#c9a24a;padding:6px 12px;font-size:15px;font-weight:bold;border-left:5px solid #c9a24a;}
.mk .box{background:#fdfaf4;border:1px solid #e3d6bd;padding:8px 11px 7px 11px;margin-top:8px;}
.mk .st{font-family:'CZMessiri','CZLatin',sans-serif;font-weight:bold;font-size:13px;color:#1f8a84;border-bottom:1px solid #e3d6bd;padding-bottom:2px;margin-bottom:3px;}
.mk .st small{font-family:'CZLatin',sans-serif;font-weight:normal;font-size:10px;color:#7a6652;}
.mk .kpis td{padding:0 3px;} .mk .kpis td:first-child{padding-left:0;} .mk .kpis td:last-child{padding-right:0;}
.mk .kpi{background:#fdfaf4;border:1px solid #e3d6bd;border-top:3px solid #c9a24a;padding:6px 8px 5px 8px;margin-top:8px;}
.mk .kl{font-size:10px;color:#7a6652;}
.mk .kv{font-family:'CZMessiri','CZLatin',sans-serif;font-size:18px;line-height:1.25;font-weight:bold;color:#1c110a;white-space:nowrap;}
.mk .ks{font-size:10px;color:#7a6652;}
.mk .u{font-size:10px;color:#7a6652;font-weight:normal;}
.mk .up{color:#1f8a84;font-weight:bold;} .mk .down{color:#b5532e;font-weight:bold;} .mk .na{color:#7a6652;}
.mk .r td{padding:2.5px 0;border-bottom:1px dotted #e3d6bd !important;font-size:11px;}
.mk .r td.f,.mk .hd td.f{width:46%;}
.mk .r td.v{text-align:right;white-space:nowrap;font-weight:bold;padding-left:8px;}
.mk .r td.m{text-align:right;white-space:nowrap;color:#7a6652;padding-left:8px;}
.mk .hd td{font-size:9.5px;color:#7a6652;padding-bottom:1px;}
.mk .hd td.m,.mk .hd td.v{text-align:right;padding-left:8px;white-space:nowrap;}
.mk .bar{height:4px;background:#efe6d3;margin-top:1px;}
.mk .bar div{height:4px;background:#c9a24a;}
.mk .ins{background:#fbeee7;border:1px solid #e2b9a6;border-left:5px solid #b5532e;padding:7px 11px;margin-top:8px;}
.mk .ins .t{font-family:'CZMessiri','CZLatin',sans-serif;font-weight:bold;color:#b5532e;font-size:13px;}
.mk .ins div.i{padding:1px 0;}
.mk .act{background:#eaf5f4;border:1px solid #b9dcd9;border-left:5px solid #1f8a84;padding:7px 11px;margin-top:8px;}
.mk .act .t{font-family:'CZMessiri','CZLatin',sans-serif;font-weight:bold;color:#1f8a84;font-size:13px;}
.mk .act div.i{padding:1px 0;}
.mk .chart{table-layout:fixed;}
.mk .chart td{vertical-align:bottom;padding:0 1px;text-align:center;}
.mk .chart .b{background:#d9c9a8;width:100%;}
.mk .chart .b.w{background:#c9a24a;}
.mk .chart .b.t{background:#b5532e;}
.mk .chart .b.s{background:#ece4d4;}
.mk .cl td{font-size:8px;color:#7a6652;text-align:center;padding-top:1px;}
.mk .heat td{font-size:8.5px;text-align:center;padding:2px 0;color:#2a1b12;}
.mk .heat td.l{text-align:left;color:#7a6652;padding-right:4px;width:26px;}
.mk .note{font-size:9.5px;color:#7a6652;margin-top:3px;}
.mk .foot{margin:10px 34px 0 34px;padding:6px 0 0 0;border-top:1px solid #d9c9a8;font-size:9.5px;color:#7a6652;}
"""

FONTS = """
@font-face{font-family:'CZMessiri';font-weight:bold;src:url('%(base)sElMessiri-Bold.ttf') format('truetype');}
@font-face{font-family:'CZLatin';font-weight:normal;src:url('%(base)sLatin-Regular.ttf') format('truetype');}
@font-face{font-family:'CZLatin';font-weight:bold;src:url('%(base)sLatin-Bold.ttf') format('truetype');}
"""


# ------------------------------------------------------------------ blocks
def kpis(cells):
    widths = ["40%", "27%", "33%"]
    tds = "".join(
        '<td style="width:%s"><div class="kpi"><div class="kl">%s</div><div class="kv">%s</div><div class="ks">%s</div></div></td>'
        % ((widths[i],) + tuple(c))
        for i, c in enumerate(cells)
    )
    return '<table class="kpis" style="table-layout:fixed;"><tr>%s</tr></table>' % tds


def rows(items, head=None):
    """items: (label, value_html, muted_html, bar_percent or None)"""
    out = []
    if head:
        out.append('<tr class="hd"><td class="f">%s</td><td class="m">%s</td><td class="v">%s</td></tr>' % head)
    for label, value, muted, bar in items:
        b = '<div class="bar"><div style="width:%d%%"></div></div>' % max(1, min(100, int(round(bar)))) if bar is not None else ""
        out.append('<tr class="r"><td class="f">%s%s</td><td class="m">%s</td><td class="v">%s</td></tr>' % (label, b, muted or "", value))
    return "<table>%s</table>" % "".join(out)


def box(title, body, small="", note=""):
    s = " <small>%s</small>" % small if small else ""
    n = '<div class="note">%s</div>' % note if note else ""
    return '<div class="box"><div class="st">%s%s</div>%s%s</div>' % (title, s, body, n)


def notes(cls, title, lines):
    if not lines:
        return ""
    return '<div class="%s"><div class="t">%s</div>%s</div>' % (cls, title, "".join('<div class="i">• %s</div>' % x for x in lines))


def dayparts_block(b, cur, prev, prev_label):
    parts = visible_dayparts(b)
    tot = sum(cur.get(n, [0, 0])[0] for n, _ in parts) or 1
    items = []
    for name, hours in parts:
        c = cur.get(name, [0, 0])
        p = (prev or {}).get(name, [0, 0])
        items.append(("%s <span class='na'>%s</span>" % (name, hours), tl(c[0]),
                      "%%%.0f · %s" % (share(c[0], tot), chg_html(c[0], p[0])), share(c[0], tot)))
    return rows(items, ("Dilim (mağaza içi)", "pay · %s" % prev_label, "net"))


def channels_block(cur, prev, prev_label, cur_days=1, prev_days=1, basket=0.0):
    """cur/prev: {channel: [net, orders, days_with_sales]}. Returns (html, footnote)."""
    tot = sum(v[0] for v in cur.values()) or 1
    items, foot = [], ""
    for name, c in sorted(cur.items(), key=lambda kv: -kv[1][0]):
        if prev is None:
            lump = name in PLATFORMS and c[1] and basket and (c[0] / float(c[1])) > 2.5 * basket
            extra = "toplu giriş" if lump else "%s sip." % num(c[1])
        else:
            p = prev.get(name, [0, 0, 0])
            if p[2] < 0.5 * c[2]:
                extra = "–*"
                foot = "* Önceki dönemde bu kanalda kayıt eksik (satış olan gün sayısı yarıdan az); karşılaştırma yapılmadı."
            else:
                extra = chg_html(c[0] / float(cur_days or 1), p[0] / float(prev_days or 1))
        items.append((h(name), tl(c[0]), "%%%.0f · %s" % (share(c[0], tot), extra), share(c[0], tot)))
    return rows(items, ("Kanal", "pay · %s" % prev_label, "net")), foot


def families_block(cur, prev, prev_label, cur_days=1, prev_days=1):
    tot = sum(cur.values()) or 1
    items = []
    for name, v in sorted(cur.items(), key=lambda kv: -kv[1]):
        if (name == "Diğer" and share(v, tot) < 2) or share(v, tot) < 0.5:
            continue
        extra = ""
        if prev is not None:
            extra = " · " + chg_html(v / float(cur_days or 1), prev.get(name, 0) / float(prev_days or 1))
        items.append((h(name), tl(v), "%%%.0f%s" % (share(v, tot), extra), share(v, tot)))
    return rows(items, ("Ürün ailesi", "pay%s" % ((" · " + prev_label) if prev is not None else ""), "net"))


def chart28(series):
    mx = max([s[1] for s in series] or [1]) or 1
    bars, labels = [], []
    n = len(series)
    for i, s in enumerate(series):
        dt = iso_date(s[0])
        cls = "b t" if i == n - 1 else ("b s" if s[3] else ("b w" if i >= n - 7 else "b"))
        hgt = max(1, int(round(s[1] / float(mx) * 62)))
        bars.append('<td><div class="%s" style="height:%dpx;"></div></td>' % (cls, hgt))
        labels.append("<td>%s<br/>%d</td>" % (WD_SHORT[dt.weekday()][:2], dt.day))
    return '<table class="chart"><tr>%s</tr><tr class="cl">%s</tr></table>' % ("".join(bars), "".join(labels))


def heat_block(heat):
    mx = max(max(r) for r in heat) or 1
    out = ['<tr><td class="l"></td>%s</tr>' % "".join("<td>%02d</td>" % (hr % 24) for hr in HOURS)]
    for mon_first in range(7):
        js = (mon_first + 1) % 7
        tds = []
        for v in heat[js]:
            a = v / float(mx)
            r = int(247 + (181 - 247) * a)
            g = int(241 + (83 - 241) * a)
            bl = int(230 + (46 - 230) * a)
            color = "#ffffff" if a > 0.6 else "#2a1b12"
            tds.append('<td style="background:#%02x%02x%02x;color:%s;">%s</td>' % (r, g, bl, color, ("%.0f" % (v / 10.0)) if v >= 5 else ""))
        out.append('<tr><td class="l">%s</td>%s</tr>' % (WD_SHORT[mon_first], "".join(tds)))
    return '<table class="heat">%s</table>' % "".join(out)


def movers_block(up, down):
    items = [(h(x[0]), '<span class="up">+%s</span>' % num(x[1]), "%s → %s adet" % (num(x[3]), num(x[2])), None) for x in up]
    items += [(h(x[0]), '<span class="down">−%s</span>' % num(abs(x[1])), "%s → %s adet" % (num(x[3]), num(x[2])), None) for x in down]
    if not items:
        return '<div class="note">Belirgin değişim yok.</div>'
    return rows(items, ("Ürün", "önceki → bu hafta", "fark TL"))


def header(title, sub, tag_label, tag):
    return (
        '<div class="head"><table><tr><td><div class="brand">%s</div><div class="sub">%s</div></td>'
        '<td style="width:270px;vertical-align:bottom;"><div class="tagl">%s</div><div class="tag">%s</div></td></tr></table></div>'
        % (title, sub, tag_label, tag)
    )


# -------------------------------------------------------------------- pages
def page_day(data, b):
    day, lw, avg4 = b["day"], b["lw"], b["avg4"]
    wd = WD_PLURAL[iso_date(data["D"]).weekday()]
    p = ['<div class="bt">%s</div>' % h(b["name"])]
    lw_txt = "geçen %s %s" % (wd, chg_html(day["net"], lw["net"])) if not lw.get("short") else "geçen hafta kısa gün"
    p.append(kpis([
        ("Net satış", tl(day["net"]), "%s · 4 hf ort. %s" % (lw_txt, chg_html(day["net"], avg4[0]))),
        ("Sipariş", num(day["n"]), "geçen hafta %s" % chg_html(day["n"], lw["n"])),
        ("Ort. sepet", tl(avg_basket(day)), "geçen hafta %s" % chg_html(avg_basket(day), avg_basket(lw))),
    ]))
    p.append(notes("ins", "Günün özeti", insights_day(b, wd)))
    p.append(box("Gün dilimleri", dayparts_block(b, day["dp"], lw["dp"], "geçen %s" % wd)))
    ch_html, _ = channels_block(day["ch"], None, "sipariş", basket=avg_basket(b["w1"]))
    p.append(box("Kanallar", ch_html))
    p.append(box("Ürün aileleri", families_block(day["fam"], None, "")))
    top = [(h(t[0]), tl(t[2]), "%s adet" % num(t[1]), None) for t in day["top"]]
    p.append(box("En çok satan 8 ürün", rows(top)))
    rew = sum(v[0] for v in day["rew"].values())
    cust = [
        ("İçecekli sipariş", "%%%.0f" % share(day["drink"], day["n"]), "%s / %s sipariş" % (num(day["drink"]), num(day["n"])), None),
        ("Çaylı sipariş (mağaza içi)", "%%%.0f" % share(day["tea"], day["inN"]), "%s / %s" % (num(day["tea"]), num(day["inN"])), None),
        ("Sipariş başına ürün", ("%.1f" % (day["items"] / float(day["n"] or 1))).replace(".", ","), "", None),
        ("WhatsApp müşterisi", num(day["waCust"]), "ilk kez sipariş veren %s" % num(day["waNew"]), None),
        ("İndirim", tl(day["disc"]), "", None),
        ("Sadakat ödülü", num(rew), "", None),
    ]
    p.append(box("Sepet ve müşteri", rows(cust)))
    return "".join(p)


def page_week(data, b):
    w1, w0 = b["w1"], b["w0"]
    p = ['<div class="bt">%s</div>' % h(b["name"])]
    p.append(kpis([
        ("Net satış (7 gün)", tl(w1["net"]), "önceki 7 gün %s" % chg_html(w1["net"], w0["net"])),
        ("Sipariş", num(w1["n"]), "önceki %s" % chg_html(w1["n"], w0["n"])),
        ("Ort. sepet", tl(avg_basket(w1)), "önceki %s" % chg_html(avg_basket(w1), avg_basket(w0))),
    ]))
    p.append(notes("ins", "Haftanın özeti", insights_week(b)))
    shorts = [s[0] for s in b["series"] if s[3]]
    p.append(box("Günlük net satış", chart28(b["series"]), "son 28 gün · koyu: son 7 gün",
                 ("Açık gri: kısa açık kalan gün (%s), ortalamalara dahil değil." % ", ".join(dm(d) for d in shorts)) if shorts else ""))
    wd = b["wdavg"]
    mx = max(x[0] for x in wd) or 1
    items = [(WD[i], tl(wd[(i + 1) % 7][0]), "", wd[(i + 1) % 7][0] / float(mx) * 100) for i in range(7)]
    p.append(box("Haftanın günleri", rows(items), "son 4 hafta ortalaması"))
    p.append(box("Saat × gün yoğunluğu", heat_block(b["heat"]), "mağaza içi · son 4 hafta · ort. net, bin TL"))
    p.append(box("Yükselen ve düşen ürünler", movers_block(b["up"], b["down"]), "son 7 gün / önceki 7 gün"))
    ch_html, foot = channels_block(w1["ch"], w0["ch"], "önceki 7 gün", w1["days"], w0["days"])
    p.append(box("Kanallar", ch_html, "", foot))
    return "".join(p)


def page_month(data, b):
    m1, m0 = b["m1"], b["m0"]
    d1, d0 = m1["days"] or 1, m0["days"] or 1
    per1, per0 = m1["net"] / float(d1), m0["net"] / float(d0)
    p = ['<div class="bt">%s</div>' % h(b["name"])]
    p.append(kpis([
        ("Ay başından net satış", tl(m1["net"]), "%s gün" % m1["days"]),
        ("Günlük ortalama", tl(per1), "geçen ay %s" % chg_html(per1, per0)),
        ("Ort. sepet", tl(avg_basket(m1)), "geçen ay %s" % chg_html(avg_basket(m1), avg_basket(m0))),
    ]))
    p.append(notes("ins", "Ayın özeti", insights_month(b)))
    top = [(h(t[0]), tl(t[2]), "%s adet · %s" % (num(t[1]), chg_html(t[2] / float(d1), t[3] / float(d0))), None) for t in m1["top"]]
    p.append(box("En çok satan 10 ürün", rows(top, ("Ürün", "adet · geçen ay", "net")), "ay başından"))
    p.append(box("Ürün aileleri", families_block(m1["fam"], m0["fam"], "geçen ay", d1, d0)))
    ch_html, foot = channels_block(m1["ch"], m0["ch"], "geçen ay", d1, d0)
    p.append(box("Kanallar", ch_html, "", foot))
    prev_dp = dict((k, [v[0] * d1 / float(d0), v[1]]) for k, v in m0["dp"].items())
    p.append(box("Gün dilimleri", dayparts_block(b, m1["dp"], prev_dp, "geçen ay")))
    return "".join(p)


def page_customers(data, b):
    d30, m1, m0 = b["d30"], b["m1"], b["m0"]
    p = ['<div class="bt">%s</div>' % h(b["name"])]
    rew_n = sum(v[0] for v in d30["rew"].values())
    rew_v = sum(v[1] for v in d30["rew"].values())
    cust = [
        ("WhatsApp siparişi", num(d30["wa"]), "%%%.0f · tüm siparişler içinde" % share(d30["wa"], d30["n"]), None),
        ("WhatsApp müşterisi (tekil)", num(d30["waCust"]), "ilk kez %s · tekrar %s" % (num(d30["waNew"]), num(d30["waRep"])), None),
        ("Salon/Teras/Tezgah'ta kayıtlı müşteri", num(d30["roomReg"]), "%s sipariş içinde" % num(d30["room"]), None),
        ("Sadakat ödülü", num(rew_n), ("%s TL" % num(rew_v)) if rew_n else "kullanım yok", None),
        ("İndirim", tl(d30["disc"]), "", None),
        ("Pazarlama masası (liste fiyatı)", tl(d30["mk"][1]), "%s sipariş" % num(d30["mk"][0]), None),
    ]
    p.append(box("Müşteri, sadakat, indirim", rows(cust), "son 30 gün"))
    drinks = [
        ("İçecekli sipariş", "%%%.0f" % share(d30["drink"], d30["n"]), "%s / %s" % (num(d30["drink"]), num(d30["n"])), None),
        ("Çaylı sipariş (mağaza içi)", "%%%.0f" % share(d30["tea"], d30["inN"]), "%s / %s" % (num(d30["tea"]), num(d30["inN"])), None),
        ("Sipariş başına ürün", ("%.1f" % (d30["items"] / float(d30["n"] or 1))).replace(".", ","), "", None),
    ]
    p.append(box("Sepet derinliği", rows(drinks), "son 30 gün"))
    pairs = [(h(x[0]), "%s sip." % num(x[1]), "", None) for x in b["pairs"]]
    p.append(box("Birlikte alınanlar", rows(pairs), "son 30 gün · çay ve su hariç"))
    slow = [(h(x[0]), tl(x[2]), "%s adet" % num(x[1]), None) for x in b["slow"]]
    p.append(box("En az satan menü ürünleri", rows(slow), "son 30 gün · satılan %s menü ürünü içinde" % b["menuN"]))
    return "".join(p)


def render_html(data, font_base="/cz_whatsapp_reports/static/src/fonts/", zoom=0.75):
    """zoom: Odoo's wkhtmltopdf lays the A4 page out at 794 css px wide; the layout is designed for ~1030 px."""
    dt = iso_date(data["D"])
    brs = [data["br"][k] for k in sorted(data["br"])]
    left, right = brs[0], brs[1] if len(brs) > 1 else None
    w_from = dt - timedelta(days=6)
    foot = (
        '<div class="foot">Kaynak: Odoo POS, kapanan oturumlar. Tutarlar KDV hariç, iadeler düşülmüş net TL. Gün, saat 06:00\'da başlar. '
        "Personel, pazarlama ve hatalı sipariş masaları satışa dahil değildir. Gün dilimleri ve saat yoğunluğu yalnızca mağaza içi "
        "kanalları (Salon, Teras, Tezgah, WhatsApp) kapsar; platform siparişlerinin kasaya giriş saati gerçek sipariş saati değildir. "
        "Platform sipariş adetleri toplu girişlerde gerçeği yansıtmaz; tutarlar doğrudur.</div>"
    )
    p = ["<style>%s%s</style>" % (FONTS % {"base": font_base}, CSS), '<div class="mk" style="zoom:%s;">' % zoom]

    def two(fn):
        s = '<div class="wrap"><div class="colL">%s</div>' % fn(data, left)
        if right:
            s += '<div class="colR">%s</div>' % fn(data, right)
        return s + '<div class="clr"></div></div>'

    p.append('<div class="page">')
    p.append(header("Choco Zuma", "Pazarlama Raporu · Günlük", WD[dt.weekday()], d_fmt(data["D"])))
    p.append(two(page_day))
    p.append(foot + "</div>")

    p.append('<div class="page pb">')
    p.append(header("Choco Zuma", "Pazarlama Raporu · Haftalık", "son 7 gün", "%s – %s" % (w_from.strftime("%d.%m"), dt.strftime("%d.%m.%Y"))))
    p.append(two(page_week))
    p.append("</div>")

    p.append('<div class="page pb">')
    p.append(header("Choco Zuma", "Pazarlama Raporu · Aylık", "ay başından, geçen ayın aynı günleriyle", "1 – %d %s %d" % (dt.day, MONTHS[dt.month - 1], dt.year)))
    p.append(two(page_month))
    p.append("</div>")

    p.append('<div class="page pb">')
    p.append(header("Choco Zuma", "Pazarlama Raporu · Müşteri ve Fırsatlar", "son 30 gün", "%s itibarıyla" % d_fmt(data["D"])))
    p.append(two(page_customers))
    tn = team_notes(data)
    if tn:
        p.append('<div class="wrap">%s</div>' % notes("act", "Pazarlama ekibi için", tn))
    p.append(foot + "</div>")
    p.append("</div>")
    return "".join(p)
