# -*- coding: utf-8 -*-
"""Pure-Python renderers of the CEO brief (no Odoo import, testable alone).

Direction rules (Arabic report with Turkish/English names and figures):
* every text line starts with RLM so the line is laid out right-to-left;
* every Latin name and every figure is wrapped in an LTR isolate, so it keeps
  its own internal order and never drags the Arabic words around it.
"""
from html import escape

RLM = "‏"
LRI = "⁦"
PDI = "⁩"
MINUS = "−"


def money(v):
    return "{:,.0f}".format(round(v or 0.0))


def pct_change(cur, prev):
    """-> (text, direction) ; direction in (-1, 0, 1)."""
    if not prev:
        return "-", 0
    v = (cur - prev) / prev * 100.0
    if abs(v) < 0.5:
        return "0%", 0
    return "%s%.0f%%" % ("+" if v > 0 else MINUS, abs(v)), (1 if v > 0 else -1)


# ---------------------------------------------------------------- plain text
def _l(s):
    return "%s%s%s" % (LRI, s, PDI)


def _tl(v):
    return _l("%s TL" % money(v))


def render_text(vm):
    """WhatsApp / on-screen text: one fact per line, direction-safe."""
    out = []

    def add(s=""):
        out.append((RLM + s) if s else "")

    add("تشوكو زوما · موجز يوم %s" % _l(vm["date"]))
    add()
    add("— المجموعة —")
    add("الصافي: %s" % _tl(vm["net"]))
    add("عدد الطلبات: %s" % _l(vm["orders"]))
    add("عن اليوم السابق: %s" % _l(vm["pct"]))
    if vm["alerts"]:
        add()
        add("— تنبيهات —")
        for i, a in enumerate(vm["alerts"], 1):
            text = a["text"]
            for key, val in (a.get("vals") or {}).items():
                text = text.replace("{%s}" % key, _l(val))
            add("%s) %s: %s" % (_l(i), _l(a["branch"]), text))
    for b in vm["branches"]:
        add()
        add("— %s —" % _l(b["name"]))
        add("الجلسة: %s" % _l(b["session"]))
        add("الصافي: %s" % _tl(b["net"]))
        add("عدد الطلبات: %s" % _l(b["orders"]))
        add("متوسط الطلب: %s" % _tl(b["avg"]))
        add("عن اليوم السابق: %s" % _l(b["pct"]))
        if b["margin"] is None:
            add("الهامش الحقيقي للمواد: غير متاح")
        else:
            add("الهامش الحقيقي للمواد: %s" % _l("%.1f%%" % b["margin"]))
            add("تكلفة المواد: %s من مبيعات %s" % (_tl(b["real_cost"]), _tl(b["covered"])))
        add("المنصات: %s وتمثل %s" % (_tl(b["platform"]), _l("%.1f%%" % b["platform_share"])))
        add("الإلغاءات: %s بقيمة %s" % (_l(b["cancel_n"]), _tl(b["cancel_value"])))
        add("إلغاءات بلا سبب: %s" % _l(b["cancel_no_reason"]))
        add("المرتجعات: %s بقيمة %s" % (_l(b["refund_n"]), _tl(b["refund_value"])))
        add("الخصومات: %s" % _tl(b["discount"]))
        add("الولاء: %s" % _tl(b["reward"]))
        add("وجبات الموظفين: %s بقيمة %s بسعر القائمة" % (_l(b["staff_orders"]), _tl(b["staff_value"])))
        add("فرق الكاش: %s" % _tl(b["cash_diff"]))
        if b["channels"]:
            add("القنوات:")
            for name, n, net in b["channels"]:
                add("• %s: %s · عدد %s" % (_l(name), _tl(net), _l(n)))
        if b["cashiers"]:
            add("الكاشير:")
            for name, n, net, canc in b["cashiers"]:
                add("• %s: %s · عدد %s · إلغاء %s" % (_l(name), _tl(net), _l(n), _l(canc)))
        if b["top"]:
            add("الأعلى مبيعاً:")
            for name, qty, net, margin in b["top"]:
                m = ("هامش %s" % _l("%.0f%%" % margin)) if margin is not None else "هامش غير متاح"
                add("• %s: %s · كمية %s · %s" % (_l(name), _tl(net), _l("%g" % qty), m))
    return "\n".join(out)


# ---------------------------------------------------------------------- html
CSS = """
html,body{margin:0;padding:0;background:#f7f1e6;}
.container,.container-fluid{padding:0 !important;margin:0 !important;max-width:none !important;width:100% !important;}
.czb{font-family:'CZPlex','CZLatin','DejaVu Sans',sans-serif;font-size:13px;line-height:1.55;color:#2a1b12;direction:rtl;text-align:right;background:#f7f1e6;}
.czb table{border-collapse:collapse;width:100%;}
.czb td,.czb th{padding:0;vertical-align:top;text-align:right;font-weight:normal;}
.czb .l{direction:ltr;unicode-bidi:embed;white-space:nowrap;}
.czb .lat{font-family:'CZLatin','DejaVu Sans',sans-serif;}
.czb .head{background:#1c110a;color:#f7f1e6;padding:26px 40px 20px 40px;border-bottom:4px solid #c9a24a;}
.czb .brand{font-family:'CZMessiri','CZPlex',sans-serif;font-size:34px;line-height:1.2;color:#c9a24a;font-weight:bold;}
.czb .sub{font-size:14px;color:#e7dcc6;margin-top:2px;}
.czb .date{font-family:'CZMessiri','CZPlex',sans-serif;font-size:22px;color:#f7f1e6;text-align:left;font-weight:bold;}
.czb .datel{font-size:12px;color:#c9a24a;text-align:left;}
.czb .wrap{padding:18px 40px 8px 40px;}
.czb .kpi{background:#ffffff;border:1px solid #e3d6bd;border-top:3px solid #c9a24a;padding:12px 14px 10px 14px;}
.czb .kl{font-size:12px;color:#7a6652;}
.czb .kv{font-family:'CZMessiri','CZPlex',sans-serif;font-size:25px;line-height:1.3;font-weight:bold;color:#1c110a;}
.czb .kv small{font-size:13px;color:#7a6652;font-weight:normal;}
.czb .up{color:#1f8a84;} .czb .down{color:#b5532e;}
.czb .gap{width:12px;}
.czb .alerts{margin-top:14px;background:#fbeee7;border:1px solid #e2b9a6;border-right:5px solid #b5532e;padding:10px 14px;}
.czb .at{font-family:'CZMessiri','CZPlex',sans-serif;font-weight:bold;color:#b5532e;font-size:15px;margin-bottom:2px;}
.czb td.ai{padding:3px 0;vertical-align:middle;}
.czb .an{display:block;width:20px;height:20px;line-height:20px;text-align:center;background:#b5532e;color:#fff;font-size:11px;}
.czb .branch{margin-top:18px;page-break-inside:avoid;}
.czb .bt{background:#1c110a;color:#f7f1e6;padding:8px 14px;border-right:5px solid #c9a24a;}
.czb .bn{font-family:'CZLatin','DejaVu Sans',sans-serif;font-size:17px;font-weight:bold;color:#c9a24a;}
.czb .bs{font-size:11px;color:#e7dcc6;text-align:left;}
.czb .box{background:#ffffff;border:1px solid #e3d6bd;padding:10px 14px;margin-top:10px;}
.czb .st{font-family:'CZMessiri','CZPlex',sans-serif;font-weight:bold;font-size:14px;color:#1f8a84;border-bottom:1px solid #e3d6bd;padding-bottom:3px;margin-bottom:4px;}
.czb .row td{padding:4px 0;border-bottom:1px dotted #e3d6bd;font-size:12.5px;}
.czb .row td.v{text-align:left;white-space:nowrap;font-weight:bold;}
.czb .row td.m{text-align:left;white-space:nowrap;color:#7a6652;padding-left:10px;}
.czb .bar{height:5px;background:#efe6d3;margin-top:2px;}
.czb .bar div{height:5px;background:#c9a24a;}
.czb .foot{margin:16px 40px 0 40px;padding:8px 0 14px 0;border-top:1px solid #d9c9a8;font-size:10.5px;color:#7a6652;}
"""

FONTS = """
@font-face{font-family:'CZMessiri';font-weight:bold;src:url('%(base)sElMessiri-Bold.ttf') format('truetype');}
@font-face{font-family:'CZPlex';font-weight:normal;src:url('%(base)sPlex-Regular.ttf') format('truetype');}
@font-face{font-family:'CZPlex';font-weight:bold;src:url('%(base)sPlex-SemiBold.ttf') format('truetype');}
@font-face{font-family:'CZLatin';font-weight:normal;src:url('%(base)sLatin-Regular.ttf') format('truetype');}
@font-face{font-family:'CZLatin';font-weight:bold;src:url('%(base)sLatin-Bold.ttf') format('truetype');}
"""


def _h(s):
    return escape(str(s))


def _num(s):
    return '<span class="l">%s</span>' % _h(s)


def _lat(s):
    return '<span class="l lat">%s</span>' % _h(s)


def _m(v):
    return '<span class="l">%s <small>TL</small></span>' % money(v)


def _cls(direction):
    return "up" if direction > 0 else ("down" if direction < 0 else "")


def _kpis(cells):
    tds = []
    for i, (label, value, cls) in enumerate(cells):
        if i:
            tds.append('<td class="gap"></td>')
        tds.append('<td><div class="kpi"><div class="kl">%s</div><div class="kv %s">%s</div></div></td>' % (label, cls, value))
    return "<table><tr>%s</tr></table>" % "".join(tds)


def _rows(rows):
    """rows: (label_html, value_html, muted_html)"""
    trs = "".join(
        '<tr class="row"><td>%s</td><td class="m">%s</td><td class="v">%s</td></tr>' % (a, c or "", b) for a, b, c in rows
    )
    return "<table>%s</table>" % trs


def render_html(vm, font_base="/cz_whatsapp_reports/static/src/fonts/"):
    p = []
    p.append("<style>%s%s</style>" % (FONTS % {"base": font_base}, CSS))
    p.append('<div class="czb" dir="rtl">')
    p.append(
        '<div class="head"><table><tr>'
        '<td><div class="brand">تشوكو زوما</div><div class="sub">الموجز اليومي للمدير التنفيذي</div></td>'
        '<td style="width:210px;vertical-align:bottom;"><div class="datel">يوم العمل</div><div class="date">%s</div></td>'
        "</tr></table></div>" % _num(vm["date"])
    )
    p.append('<div class="wrap">')
    p.append(
        _kpis(
            [
                ("صافي مبيعات المجموعة", _m(vm["net"]), ""),
                ("عدد الطلبات", _num(vm["orders"]), ""),
                ("عن اليوم السابق", _num(vm["pct"]), _cls(vm["dir"])),
            ]
        )
    )
    if vm["alerts"]:
        p.append('<div class="alerts"><div class="at">تنبيهات تحتاج نظرك</div><table>')
        for i, a in enumerate(vm["alerts"], 1):
            text = _h(a["text"])
            for key, val in (a.get("vals") or {}).items():
                text = text.replace("{%s}" % key, _lat(val))
            p.append(
                '<tr><td class="ai" style="width:28px;"><span class="an">%s</span></td>'
                '<td class="ai" style="width:190px;font-weight:bold;">%s</td><td class="ai">%s</td></tr>' % (i, _lat(a["branch"]), text)
            )
        p.append("</table></div>")
    for b in vm["branches"]:
        p.append('<div class="branch">')
        p.append(
            '<div class="bt"><table><tr><td><span class="l bn">%s</span></td>'
            '<td class="bs" style="width:200px;vertical-align:middle;">الجلسة %s</td></tr></table></div>'
            % (_h(b["name"]), _lat(b["session"]))
        )
        margin = _num("%.1f%%" % b["margin"]) if b["margin"] is not None else "غير متاح"
        p.append('<div style="margin-top:10px;">')
        p.append(
            _kpis(
                [
                    ("الصافي", _m(b["net"]), ""),
                    ("الطلبات", _num(b["orders"]), ""),
                    ("متوسط الطلب", _m(b["avg"]), ""),
                    ("عن اليوم السابق", _num(b["pct"]), _cls(b["dir"])),
                    ("الهامش الحقيقي للمواد", margin, ""),
                ]
            )
        )
        p.append("</div>")
        control = [
            ("تكلفة المواد الحقيقية", _m(b["real_cost"]), "من مبيعات %s" % _m(b["covered"])),
            ("مبيعات المنصات", _m(b["platform"]), _num("%.1f%%" % b["platform_share"])),
            ("الإلغاءات", _m(b["cancel_value"]), "عدد %s" % _num(b["cancel_n"])),
            ("إلغاءات بلا سبب", _num(b["cancel_no_reason"]), ""),
            ("المرتجعات", _m(b["refund_value"]), "عدد %s" % _num(b["refund_n"])),
            ("الخصومات", _m(b["discount"]), ""),
            ("الولاء", _m(b["reward"]), ""),
            ("وجبات الموظفين بسعر القائمة", _m(b["staff_value"]), "عدد %s" % _num(b["staff_orders"])),
            ("فرق الكاش", _m(b["cash_diff"]), ""),
        ]
        top_net = max([c[2] for c in b["channels"]] or [1.0]) or 1.0
        ch = []
        for name, n, net in b["channels"]:
            w = max(2, int(round(net / top_net * 100)))
            ch.append(
                '<tr class="row"><td>%s<div class="bar"><div style="width:%s%%"></div></div></td>'
                '<td class="m">عدد %s</td><td class="v">%s</td></tr>' % (_lat(name), w, _num(n), _m(net))
            )
        p.append('<table><tr><td style="width:50%;padding-left:6px;">')
        p.append('<div class="box"><div class="st">الرقابة</div>%s</div>' % _rows(control))
        p.append('</td><td style="width:50%;padding-right:6px;">')
        p.append('<div class="box"><div class="st">القنوات (صافي)</div><table>%s</table></div>' % "".join(ch))
        cash = [(_lat(name), _m(net), "عدد %s · إلغاء %s" % (_num(n), _num(c))) for name, n, net, c in b["cashiers"]]
        if cash:
            p.append('<div class="box"><div class="st">الكاشير</div>%s</div>' % _rows(cash))
        p.append("</td></tr></table>")
        if b["top"]:
            top = []
            for name, qty, net, mg in b["top"]:
                mtxt = ("هامش %s" % _num("%.0f%%" % mg)) if mg is not None else "هامش غير متاح"
                top.append((_lat(name), _m(net), "كمية %s · %s" % (_num("%g" % qty), mtxt)))
            p.append('<div class="box"><div class="st">الأعلى مبيعاً</div>%s</div>' % _rows(top))
        p.append("</div>")
    p.append("</div>")
    p.append(
        '<div class="foot">المصدر: بيانات نقاط البيع في أودو لآخر جلسة مغلقة لكل فرع. '
        "الهامش الحقيقي محسوب من أسعار فواتير الموردين لآخر %s يوماً وليس من تكلفة أودو المعيارية. "
        "كل المبالغ صافية من الضريبة بالليرة التركية.</div>" % int(vm.get("cost_days", 90))
    )
    p.append("</div>")
    return "".join(p)
