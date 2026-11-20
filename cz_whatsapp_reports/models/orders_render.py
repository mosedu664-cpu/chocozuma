# -*- coding: utf-8 -*-
"""Yesterday's sale orders (Turkish) — pure-Python HTML renderer, no Odoo import.

Two audiences from the same data:
* kitchen (show_prices=False): what came in, the total to prepare per product against the
  kitchen stock right now, then every order with its lines — no money;
* accounting (show_prices=True): the same orders with amounts, invoice status and the list
  of orders still to invoice.
"""
from datetime import datetime

from .kitchen_render import EXTRA_CSS, q
from .marketing_render import CSS, FONTS, WD, h, header, notes

ORDER_CSS = """
.mk .oc{background:#fdfaf4;border:1px solid #e3d6bd;border-left:4px solid #c9a24a;padding:6px 10px 5px 10px;margin-top:7px;}
.mk .oc .t{font-weight:bold;font-size:12px;}
.mk .oc .m{color:#7a6652;font-size:10px;}
.mk .oc table td{padding:2px 4px;font-size:10.5px;border-bottom:1px dotted #e3d6bd !important;}
.mk .oc td.n{text-align:right;white-space:nowrap;}
.mk .pill{display:inline-block;font-size:9.5px;padding:0 6px;border-radius:8px;border:1px solid #c9a24a;color:#7a6652;margin-left:4px;}
.mk .pill.bad{border-color:#b5532e;color:#b5532e;} .mk .pill.ok{border-color:#1e8449;color:#1e8449;}
"""

INVOICE = {"to invoice": ("Faturalanacak", "bad"), "invoiced": ("Faturalandı", "ok"), "no": ("Fatura yok", ""),
           "upselling": ("Ek satış", "")}
DELIVERY = {"done": ("Teslim edildi", "ok"), "assigned": ("Sevke hazır", ""), "confirmed": ("Stok bekliyor", "bad"),
            "waiting": ("Bekliyor", "bad"), "partially_available": ("Kısmen hazır", "bad"), "cancel": ("İptal", "bad"),
            "draft": ("Taslak", "")}


def tl(v):
    return "%s TL" % q(round(v or 0))


def summary(data):
    """One line for the WhatsApp template ({{2}})."""
    n = len(data["orders"])
    if not n:
        return "dün sipariş gelmedi"
    s = "%d sipariş, %d müşteri" % (n, len({o["partner"] for o in data["orders"]}))
    if data.get("unusual"):
        s += ", %d olağandışı miktar" % len(data["unusual"])
    if data["show_prices"]:
        s += ", toplam %s (KDV hariç)" % tl(data["untaxed"])
        if data["to_invoice"]:
            s += ", %d faturalanacak" % data["to_invoice"]
    return s


def render_text(data):
    lines = ["Choco Zuma · Dünkü siparişler · %s · %s" % (data["title"], data["day_txt"]), summary(data)]
    for o in data["orders"][:15]:
        lines.append("%s %s — %d kalem%s" % (o["name"], o["partner"], len(o["lines"]),
                                             (", " + tl(o["untaxed"])) if data["show_prices"] else ""))
    return "\n".join(lines)


def _order_card(o, show_prices):
    pills = []
    if o["delivery"]:
        label, cls = DELIVERY.get(o["delivery"], (o["delivery"], ""))
        pills.append('<span class="pill %s">%s</span>' % (cls, label))
    if show_prices:
        label, cls = INVOICE.get(o["invoice_status"], (o["invoice_status"], ""))
        pills.append('<span class="pill %s">%s</span>' % (cls, label))
    meta = ["sipariş %s" % h(o["time"])]
    if o["deliver_on"]:
        meta.append("teslim %s" % h(o["deliver_on"]))
    if o["ref"]:
        meta.append("ref %s" % h(o["ref"]))
    if o["by"]:
        meta.append(h(o["by"]))
    rows = []
    for l in o["lines"]:
        price = ('<td class="n">%s</td>' % tl(l["subtotal"])) if show_prices else ""
        rows.append('<tr><td><span style="color:#7a6652;font-size:9.5px;">%s</span> %s</td><td class="n"><b>%s</b> %s</td>%s</tr>'
                    % (h(l["code"]), h(l["name"]), q(l["qty"]), h(l["uom"]), price))
    total = ""
    if show_prices:
        total = ('<tr><td style="text-align:right;color:#7a6652;">KDV hariç / dahil</td><td></td>'
                 '<td class="n"><b>%s</b> / %s</td></tr>' % (tl(o["untaxed"]), tl(o["total"])))
    return ('<div class="oc"><div class="t">%s · %s %s</div><div class="m">%s</div><table>%s%s</table></div>'
            % (h(o["name"]), h(o["partner"]), "".join(pills), " · ".join(meta), "".join(rows), total))


def render_html(data, font_base="/cz_whatsapp_reports/static/src/fonts/", zoom=0.75):
    show = data["show_prices"]
    day = datetime.strptime(data["day"], "%Y-%m-%d")
    p = ["<style>%s%s%s%s</style>" % (FONTS % {"base": font_base}, CSS, EXTRA_CSS, ORDER_CSS),
         '<div class="mk" style="zoom:%s;">' % zoom, '<div class="page">']
    p.append(header("Choco Zuma", h(data["title"]), WD[day.weekday()], h(data["day_txt"])))
    orders = data["orders"]
    kpis = [("Sipariş", str(len(orders)), "dün 06:00 – bugün 06:00"),
            ("Müşteri", str(len({o["partner"] for o in orders})), ""),
            ("Kalem", str(sum(len(o["lines"]) for o in orders)), "%d farklı ürün" % len(data["products"]))]
    if show:
        kpis.append(("Tutar (KDV hariç)", tl(data["untaxed"]), "KDV dahil %s" % tl(data["total"])))
    else:
        short = sum(1 for x in data["products"] if x["short"] > 0)
        kpis.append(("Üretilecek", str(short), "mutfak ürünü — stok siparişe yetmiyor"))
    cells = "".join('<td><div class="kpi"><div class="kl">%s</div><div class="kv">%s</div><div class="ks">%s</div></div></td>'
                    % (h(a), b, h(c)) for a, b, c in kpis)
    p.append('<div class="wrap"><table class="kpis"><tr>%s</tr></table>' % cells)
    if data.get("unusual"):
        p.append(notes("ins", "Olağandışı miktar — siparişi kontrol edin (yazım hatası olabilir)", [
            "<b>%s</b> %s · %s %s — <b>%s %s</b> (bu ürünün normal sipariş miktarı ~%s, %d kat)%s"
            % (h(u["order"]), h(u["partner"]), h(u["code"]), h(u["name"]), q(u["qty"]), h(u["uom"]), q(u["median"]),
               round(u["ratio"]), (" · %s" % tl(u["subtotal"])) if show else "")
            for u in data["unusual"]]))
    if not orders:
        p.append('<div class="ok"><div class="t">Dün bu depoya sipariş gelmedi.</div></div>')
    else:
        if show:
            inv = [o for o in orders if o["invoice_status"] == "to invoice"]
            p.append(notes("ins", "Faturalanacak siparişler (%d)" % len(inv),
                           ["<b>%s</b> %s — %s" % (h(o["name"]), h(o["partner"]), tl(o["total"])) for o in inv]))
        else:
            rows = ['<table class="tb"><tr><th class="l">Ürün</th><th>Siparişlerde toplam</th><th>Mutfak + depo stok</th>'
                    '<th>Üretilecek</th><th>Sipariş</th></tr>']
            made = [x for x in data["products"] if x["made"]]
            other = [x for x in data["products"] if not x["made"]]
            for x in made:
                rows.append('<tr class="%s"><td class="nm"><span class="c">%s</span> %s <span class="u">· %s</span></td>'
                            '<td class="tot">%s</td><td class="%s">%s</td><td class="%s">%s</td><td class="n">%d</td></tr>'
                            % ("fl" if x["short"] > 0 else "", h(x["code"]), h(x["name"]), h(x["uom"]), q(x["qty"]),
                               "neg" if x["stock"] < 0 else "n", q(x["stock"]),
                               "bad" if x["short"] > 0 else "z", q(x["short"]) if x["short"] > 0 else "–", x["orders"]))
            rows.append("</table>")
            if made:
                p.append('<div class="st2">Mutfakta üretilen ürünler <small style="font-weight:normal;font-size:10px;color:#7a6652;">'
                         'tüm siparişler birlikte; stok şu an Merkez Mutfak (mutfak + depo)</small></div>' + "".join(rows))
            if other:
                p.append('<div class="st2">Diğer kalemler <small style="font-weight:normal;font-size:10px;color:#7a6652;">'
                         'satın alma, sebze-meyve, ambalaj — hazırlanıp sevk edilecek miktar</small></div>'
                         '<div class="box" style="margin-top:4px;">%s</div>'
                         % " · ".join("<b>%s</b> %s <b>%s</b> %s" % (h(x["code"]), h(x["name"]), q(x["qty"]), h(x["uom"])) for x in other))
        p.append('<div class="st2">Siparişler</div>')
        half = (len(orders) + 1) // 2
        p.append('<div class="colL">%s</div><div class="colR">%s</div><div class="clr"></div>'
                 % ("".join(_order_card(o, show) for o in orders[:half]), "".join(_order_card(o, show) for o in orders[half:])))
    p.append("</div>")
    p.append('<div class="foot">Kaynak: Odoo satış siparişleri (onaylı), %s deposu, %s 06:00 – ertesi gün 06:00. %s</div>'
             % (h(data["warehouses"]), h(data["day_txt"]),
                "Tutarlar TL; fatura durumu Odoo'daki sipariş durumudur." if show else
                "Eksik = siparişlerdeki toplam − Merkez Mutfak'taki stok (rapor anında)."))
    p.append("</div></div>")
    return "".join(p)
