# -*- coding: utf-8 -*-
"""WhatsApp header cards — one image per report send (pure Python, no Odoo import).

The card is a billboard: on a phone it is shown about 330 px wide (a fifth of its size), so it
carries only what reads at that size — the report's name, emblem and colour, the day, a one-line
headline and at most three big numbers. Everything else lives in the message text and the PDF.
Each report has its own colour, its own emblem and a large faint copy of that emblem behind the
numbers, so the five reports are told apart before a word is read.
Size 1600 x 836 (1.91:1, the ratio WhatsApp shows without cropping).
"""
import base64
import os
import re
from html import escape

W, H = 1600, 836
FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "src", "fonts")
BG = "#1c110a"

THEMES = {
    # accent, shade
    "ceo_daily": ("#d9b45f", "#6b5426"),
    "branch_daily": ("#3fb7a6", "#1f5a52"),
    "marketing": ("#ef8b68", "#6e3a2a"),
    "kitchen_stock": ("#a6c886", "#475a37"),
    "orders_daily": ("#7ea9f2", "#33476b"),
}
TONE = {"up": "#7bd389", "down": "#ff8a7a", "warn": "#f3c969", "": "#cdbfa8"}

# Emblems: original geometric glyphs on a 100x100 grid, filled with the accent colour.
EMBLEMS = {
    # stepped pyramid crowned by a sun — the group view
    "ceo_daily": (
        '<circle cx="50" cy="22" r="11"/>'
        '<g stroke-width="5" stroke-linecap="square">'
        '<line x1="50" y1="2" x2="50" y2="6"/><line x1="30" y1="22" x2="34" y2="22"/><line x1="66" y1="22" x2="70" y2="22"/>'
        '<line x1="36" y1="8" x2="39" y2="11"/><line x1="64" y1="8" x2="61" y2="11"/></g>'
        '<polygon points="6,96 94,96 94,86 84,86 84,76 74,76 74,66 64,66 64,56 36,56 36,66 26,66 26,76 16,76 16,86 6,86"/>'
        '<rect x="44" y="80" width="12" height="16" fill="%(bg)s"/>'),
    # shop front with a scalloped awning — the branch
    "branch_daily": (
        '<polygon points="8,20 92,20 98,44 2,44"/>'
        '<circle cx="14" cy="44" r="8"/><circle cx="31" cy="44" r="8"/><circle cx="48" cy="44" r="8"/>'
        '<circle cx="65" cy="44" r="8"/><circle cx="82" cy="44" r="8"/><circle cx="96" cy="44" r="4"/>'
        '<rect x="12" y="54" width="76" height="42"/>'
        '<rect x="20" y="62" width="28" height="20" fill="%(bg)s"/><rect x="56" y="62" width="22" height="34" fill="%(bg)s"/>'
        '<rect x="8" y="6" width="84" height="8"/>'),
    # megaphone with sound steps — marketing
    "marketing": (
        '<polygon points="10,40 34,40 70,16 70,84 34,60 10,60"/>'
        '<polygon points="20,60 34,60 40,88 26,88"/>'
        '<rect x="78" y="44" width="16" height="12"/><rect x="78" y="22" width="8" height="12"/><rect x="78" y="66" width="8" height="12"/>'),
    # chef's toque — the kitchen
    "kitchen_stock": (
        '<circle cx="30" cy="40" r="18"/><circle cx="50" cy="28" r="22"/><circle cx="70" cy="40" r="18"/>'
        '<rect x="24" y="40" width="52" height="34"/>'
        '<rect x="24" y="78" width="52" height="16"/>'
        '<rect x="36" y="56" width="5" height="16" fill="%(bg)s"/><rect x="48" y="52" width="5" height="20" fill="%(bg)s"/>'
        '<rect x="60" y="56" width="5" height="16" fill="%(bg)s"/>'),
    # parcel with ribbon — orders
    "orders_daily": (
        '<polygon points="50,6 94,26 50,46 6,26"/>'
        '<polygon points="6,32 47,52 47,96 6,76"/>'
        '<polygon points="94,32 53,52 53,96 94,76"/>'
        '<polygon points="28,16 72,36 72,50 64,46 64,40 20,20" fill="%(bg)s"/>'),
}


def h(s):
    return escape(str(s))


_NUM = re.compile(r"([+\-−]?[%]?\d[\d.,:/]*%?(?:\s?(?:TL|₺))?)")


def _ltr_numbers(text):
    """Escape text and wrap each number run in an LTR span, so Arabic lines keep numbers intact."""
    out, last = [], 0
    for m in _NUM.finditer(text):
        out.append(h(text[last:m.start()]))
        out.append('<span class="n">%s</span>' % h(m.group(1)))
        last = m.end()
    out.append(h(text[last:]))
    return "".join(out)


def _svg_uri(svg):
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def _emblem(code, color, size):
    body = EMBLEMS.get(code, EMBLEMS["ceo_daily"]) % {"bg": BG}
    return _svg_uri(
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 100 100">'
        '<g fill="%s" stroke="%s">%s</g></svg>' % (size, size, color, color, body))


def _frieze(accent, shade, flip=False):
    """Stepped band in the brand's Mesoamerican spirit (original geometry), as an inline SVG."""
    unit = 64
    parts = []
    for i in range(W // unit + 2):
        x = i * unit
        pts = "%d,32 %d,32 %d,22 %d,22 %d,12 %d,12 %d,2 %d,2 %d,12 %d,12 %d,22 %d,22 %d,32" % (
            x, x + 8, x + 8, x + 16, x + 16, x + 24, x + 24, x + 40, x + 40, x + 48, x + 48, x + 56, x + 56)
        parts.append('<polygon points="%s" fill="%s"/>' % (pts, accent if i % 2 == 0 else shade))
        parts.append('<rect x="%d" y="14" width="4" height="4" fill="%s"/>' % (x + 30, BG))
    y0, y1 = (0, 2) if flip else (32, 32)
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="34" viewBox="0 0 %d 34">'
           '<rect width="%d" height="34" fill="%s"/><g%s>%s</g><rect y="%d" width="%d" height="2" fill="%s"/></svg>') % (
        W, W, W, BG, ' transform="translate(0,34) scale(1,-1)"' if flip else "", "".join(parts),
        y0 if flip else y1, W, accent)
    return _svg_uri(svg)


def _font(name, font_base):
    """Font URL: a base path for local tests, or the font embedded (server render needs no network or file access)."""
    if font_base:
        return font_base + name
    with open(os.path.join(FONT_DIR, name), "rb") as f:
        return "data:font/ttf;base64," + base64.b64encode(f.read()).decode()


def render(code, spec, font_base=None):
    """spec: lang ('tr'/'ar'), kicker, title, date, weekday, kpis [(label, value, sub, tone)] (max 3)."""
    accent, shade = THEMES.get(code, THEMES["ceo_daily"])
    rtl = spec.get("lang") == "ar"
    kpis = (spec.get("kpis") or [])[:3]
    n = max(1, len(kpis))
    gap = 30
    tile_w = (W - 120 - (n - 1) * gap) // n
    tiles = []
    for i, (label, value, sub, tone) in enumerate(kpis):
        side = ("margin-right:%dpx;" if rtl else "margin-left:%dpx;") % gap if i else ""
        vsize = {True: 124}.get(len(str(value)) <= 6) or (108 if len(str(value)) == 7 else 92)
        tiles.append(
            '<div class="tile" style="width:%dpx;%s"><div class="tl">%s</div>'
            '<div class="tv" style="font-size:%dpx"><span class="n">%s</span></div>'
            '<div class="ts" style="color:%s">%s</div></div>' % (
                tile_w - 4, side, _ltr_numbers(label), vsize, h(value),
                TONE.get(tone or "", TONE[""]), _ltr_numbers(sub or "")))
    rtl_fonts = (
        "@font-face{font-family:'CZA';font-weight:normal;src:url('%s') format('truetype');}"
        "@font-face{font-family:'CZA';font-weight:bold;src:url('%s') format('truetype');}" % (
            _font("Plex-Regular.ttf", font_base), _font("Plex-SemiBold.ttf", font_base))) if rtl else ""
    fonts = (
        "@font-face{font-family:'CZM';font-weight:bold;src:url('%s') format('truetype');}"
        "@font-face{font-family:'CZL';font-weight:normal;src:url('%s') format('truetype');}"
        "@font-face{font-family:'CZL';font-weight:bold;src:url('%s') format('truetype');}" % (
            _font("ElMessiri-Bold.ttf", font_base), _font("Latin-Regular.ttf", font_base), _font("Latin-Bold.ttf", font_base))
    ) + rtl_fonts
    body_font = "'CZA','CZL',sans-serif" if rtl else "'CZL','CZA',sans-serif"
    al, op = ("right", "left") if rtl else ("left", "right")
    css = """
    html,body{margin:0;padding:0;width:%(W)dpx;height:%(H)dpx;overflow:hidden;background:%(bg)s;}
    .c{position:relative;width:%(W)dpx;height:%(H)dpx;overflow:hidden;color:#f7f1e6;
       background:-webkit-linear-gradient(top,#26170e 0%%,#1c110a 60%%,#150d08 100%%);
       font-family:%(bf)s;direction:%(dir)s;text-align:%(al)s;}
    .fz{position:absolute;left:0;width:%(W)dpx;height:34px;}
    .wm{position:absolute;top:150px;%(op)s:-70px;width:620px;height:620px;opacity:0.07;}
    .n{direction:ltr;unicode-bidi:embed;}
    .hd{position:absolute;top:66px;%(al)s:60px;%(op)s:60px;height:130px;}
    .em{float:%(al)s;width:124px;height:124px;}
    .nm{float:%(al)s;margin-%(al)s:28px;margin-top:2px;}
    .brand{font-family:'CZL',sans-serif;font-weight:bold;letter-spacing:10px;font-size:26px;color:%(ac)s;}
    .kick{font-family:'CZM','CZA',sans-serif;font-weight:bold;font-size:%(ks)dpx;line-height:1.05;color:#f7f1e6;margin-top:6px;white-space:nowrap;}
    .date{float:%(op)s;text-align:%(op)s;margin-top:24px;%(dm)s}
    .date .d{font-family:'CZM','CZA',sans-serif;font-weight:bold;font-size:60px;line-height:1;color:%(ac)s;}
    .date .w{font-size:34px;color:#cdbfa8;margin-top:8px;}
    .title{position:absolute;top:228px;%(al)s:60px;%(op)s:60px;font-family:'CZM','CZA',sans-serif;font-weight:bold;
           font-size:58px;line-height:1.1;color:#f7f1e6;white-space:nowrap;overflow:hidden;}
    .bar{display:inline-block;width:14px;height:52px;background:%(ac)s;vertical-align:-6px;margin-%(op)s:22px;}
    .tiles{position:absolute;top:340px;%(al)s:60px;width:%(TW)dpx;height:410px;}
    .tile{float:%(al)s;height:400px;background:rgba(48,30,18,0.82);border-top:10px solid %(ac)s;
          border-bottom:2px solid %(sh)s;}
    .tl{font-size:40px;color:#e8dcc8;padding:30px 34px 0 34px;height:52px;overflow:hidden;white-space:nowrap;}
    .tv{font-family:'CZM','CZL',sans-serif;font-weight:bold;line-height:1;color:#ffffff;
        padding:42px 34px 0 34px;height:136px;white-space:nowrap;}
    .ts{font-size:38px;padding:34px 34px 0 34px;white-space:nowrap;overflow:hidden;}
    """ % {"W": W, "H": H, "bg": BG, "bf": body_font, "dir": "rtl" if rtl else "ltr", "al": al, "op": op,
           "ac": accent, "sh": shade, "TW": W - 120, "dm": "" if rtl else "margin-right:60px;", "ks": 64 if rtl else 58}
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"/><style>%(fonts)s%(css)s</style></head><body>'
        '<div class="c"><img class="fz" style="top:0" src="%(fz)s"/><img class="wm" src="%(wm)s"/>'
        '<div class="hd"><div class="date"><div class="d"><span class="n">%(date)s</span></div><div class="w">%(wd)s</div></div>'
        '<img class="em" src="%(em)s"/><div class="nm"><div class="brand">CHOCO ZUMA</div><div class="kick">%(kick)s</div></div></div>'
        '<div class="title"><span class="bar"></span>%(title)s</div>'
        '<div class="tiles">%(tiles)s</div>'
        '<img class="fz" style="bottom:0" src="%(fzb)s"/></div></body></html>'
    ) % {"fonts": fonts, "css": css, "fz": _frieze(accent, shade), "fzb": _frieze(accent, shade, flip=True),
         "wm": _emblem(code, accent, 620), "em": _emblem(code, accent, 124), "date": h(spec.get("date", "")),
         "wd": h(spec.get("weekday", "")), "kick": h(spec.get("kicker", "")),
         "title": _ltr_numbers(spec.get("title", "")), "tiles": "".join(tiles)}
