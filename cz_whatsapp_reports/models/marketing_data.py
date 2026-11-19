# -*- coding: utf-8 -*-
"""Marketing report - pure-Python aggregation (no Odoo import, testable outside Odoo).

Input per branch: a list of order dicts already reduced by the Odoo adapter (wa_report._marketing_orders):
    {"day": "YYYY-MM-DD" (business day, starts 06:00 local), "hour": local hour (+24 before 06:00),
     "ch": channel ("Salon", "Teras", "Tezgah", "WhatsApp", "Trendyol Go", "Yemeksepeti", "Getir",
           "Migros Yemek", or "STAFF" / "MKT" / "ERR"),
     "net": amount_total - amount_tax, "tot": amount_total, "partner": partner id or 0 (0 = none or generic),
     "lines": [{"name", "fam", "extra", "qty", "sub", "reward", "program", "list"}]}

Rules (audited 19.11.2026):
- Sales = orders with amount_total > 0 outside the STAFF / MKT / ERR floors (refunds are negative orders and
  reduce net through "net" only).  MKT orders are reported apart at list value (qty x price, VAT excluded).
- Day parts and the hour heatmap use in-store channels only (platform punch-in time is not the order time).
- A short day (net < 35% of the 28-day median) is left out of averages, the heatmap and best/worst.
"""
import re
from datetime import date, timedelta

IN_STORE = ("Salon", "Teras", "Tezgah", "WhatsApp")
ROOM = ("Salon", "Teras", "Tezgah")
NOT_SALES = ("STAFF", "MKT", "ERR")
DAYPARTS = (("Sabah", 6, 11), ("Öğle", 11, 15), ("İkindi", 15, 18), ("Akşam", 18, 22), ("Gece", 22, 31))
HEAT_HOURS = list(range(9, 25))
SHORT_RATIO = 0.35

DRINK_CATS = {"beverages", "soft drinks", "drinks", "black coffee", "cold coffee", "hot chocolate", "hot coffee", "milk-based coffee",
              "frappe", "herbal teas", "milkshake", "smoothie"}
DRINK_RE = re.compile(
    r"\b(çay|cay|su|soda|coffee|kahve|latte|americano|espresso|mocha|cortado|cappuccino|macchiato|frappe|"
    r"milkshake|smoothie|lemonade|limonata|juice|tea|flat white|milk|ayran)\b", re.I)
BAKERY_RE = re.compile(r"croissant|kruvasan|omelet|brioche|parfait|simit|poğaça|pogaca", re.I)
WATER_TEA_RE = re.compile(r"^(çay|cay|su|water|turkish tea)\b", re.I)
TEA_RE = re.compile(r"^(çay|cay|turkish tea)$", re.I)


# ------------------------------------------------------------------ products
def clean_name(name):
    n = re.sub(r"^\s*\[[^\]]*\]\s*", "", name or "")
    prev = None
    while prev != n:
        prev = n
        n = re.sub(r"\s*\((?:P|P O|W|Custom Combo)\)\s*$", "", n, flags=re.I)
    n = re.sub(r"\s+Base$", "", n, flags=re.I)
    if re.search(r"kampan", n, re.I):  # campaign copies: "24\\10 Kampanya Zuma Roll" -> "Zuma Roll"
        n = re.sub(r"\(P\)|\bkampan\w*\b|\d+(?:\s*[.\\/]\s*\d+)+", " ", n, flags=re.I)
    n = re.sub(r"\s+New$", "", re.sub(r"\s+", " ", n).strip(), flags=re.I)
    n = n.replace("Profitreole", "Profiterole")
    if n.lower() == "çay" or n.lower() == "cay":
        n = "Çay"
    return n.strip()


def is_extra(name, cats):
    n = (name or "").strip().lower()
    return any("extras" in c for c in cats) or bool(re.match(r"(extra|ekstra|yan[ıi]nda)\b", n))


def family(name, cats):
    n = (name or "").lower()
    cats = {c.lower() for c in cats}
    if "ambalaj" in cats:  # packaging
        return "Diğer"
    if re.search(r"\bbox\b", n):
        return "Kutular (Box)"
    if re.search(r"\broll\b", n):
        return "Zuma Roll"
    if "waffle" in n:
        return "Waffle"
    if "crepe" in n or "krep" in n or "crepe" in cats:
        return "Krep"
    if cats & DRINK_CATS or DRINK_RE.search(n):
        return "İçecek"
    if BAKERY_RE.search(n) or any(k in c for c in cats for k in ("bakery", "brunch", "breakfast", "croissant")):
        return "Fırın & Brunch"
    if any(k in c for c in cats for k in ("dessert", "chocolate")):
        return "Tatlı & Çikolata"
    return "Diğer"


# ------------------------------------------------------------------- helpers
def d_iso(d):
    return d.isoformat()


def iso_d(s):
    y, m, dd = [int(x) for x in s.split("-")]
    return date(y, m, dd)


def js_wd(d):
    """JS getUTCDay: 0 = Sunday."""
    return (d.weekday() + 1) % 7


def daypart(hour):
    for name, a, b in DAYPARTS:
        if a <= hour < b:
            return name
    return "Gece"


def median(vals):
    v = sorted(vals)
    if not v:
        return 0.0
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2.0


def is_sale(o):
    """An order counted as a sale (orders and averages)."""
    return o["tot"] > 0 and o["ch"] not in NOT_SALES


def is_refund(o):
    """A refund on a sales floor: reduces net sales, is not counted as an order."""
    return o["tot"] < 0 and o["ch"] not in NOT_SALES


# --------------------------------------------------------------- aggregation
def base(orders, first_day, start, end):
    """Aggregate the orders whose business day is in [start, end] (ISO strings)."""
    sel = [o for o in orders if start <= o["day"] <= end]
    sales = [o for o in sel if is_sale(o)]
    r = {
        "net": 0.0, "n": 0, "items": 0.0, "disc": 0.0, "drink": 0, "tea": 0, "inN": 0, "room": 0, "roomReg": 0,
        "wa": 0, "waCust": 0, "waNew": 0, "waRep": 0, "mk": [0, 0.0], "staff": 0, "days": 0,
        "rew": {}, "ch": {}, "fam": {}, "dp": {},
    }
    days, ch_days, wa_cnt = set(), {}, {}
    prods = {}
    for o in sel:
        if o["ch"] == "STAFF":
            r["staff"] += 1
        elif o["ch"] == "MKT":
            r["mk"][0] += 1
            r["mk"][1] += sum(l["list"] for l in o["lines"] if not l["reward"])
    for o in sel:
        if not is_refund(o):
            continue
        r["net"] += o["net"]
        r["ch"].setdefault(o["ch"], [0.0, 0, 0])[0] += o["net"]
        for l in o["lines"]:
            # returned items only; the reversed discount line of a refund is not a product sale
            if l["reward"] or l["sub"] >= 0:
                continue
            r["fam"][l["fam"]] = r["fam"].get(l["fam"], 0.0) + l["sub"]
            if not l["extra"] and l["sub"] < 0:
                p = prods.setdefault(l["name"], [0.0, 0.0])
                p[0] += l["qty"]
                p[1] += l["sub"]
    for o in sales:
        r["net"] += o["net"]
        r["n"] += 1
        days.add(o["day"])
        c = r["ch"].setdefault(o["ch"], [0.0, 0, 0])
        c[0] += o["net"]
        c[1] += 1
        ch_days.setdefault(o["ch"], set()).add(o["day"])
        if o["ch"] in IN_STORE:
            r["inN"] += 1
            dp = r["dp"].setdefault(daypart(o["hour"]), [0.0, 0])
            dp[0] += o["net"]
            dp[1] += 1
        if o["ch"] in ROOM:
            r["room"] += 1
            if o["partner"]:
                r["roomReg"] += 1
        if o["ch"] == "WhatsApp":
            r["wa"] += 1
            if o["partner"]:
                wa_cnt[o["partner"]] = wa_cnt.get(o["partner"], 0) + 1
        drink = tea = False
        for l in o["lines"]:
            if l["reward"]:
                p = r["rew"].setdefault(l["program"] or "Ödül", [0, 0.0, {}])
                p[0] += 1
                p[1] += -l["sub"]
                p[2][o["ch"]] = p[2].get(o["ch"], 0) + 1
                continue
            if l["sub"] < 0:
                r["disc"] += -l["sub"]
                continue
            if l["sub"] > 0:
                r["items"] += l["qty"]
            r["fam"][l["fam"]] = r["fam"].get(l["fam"], 0.0) + l["sub"]
            if l["qty"] > 0 and not l["extra"] and l["fam"] == "İçecek":
                drink = True
            if TEA_RE.match(l["name"]) and l["qty"] > 0:
                tea = True
            if l["sub"] > 0 and not l["extra"]:
                p = prods.setdefault(l["name"], [0.0, 0.0])
                p[0] += l["qty"]
                p[1] += l["sub"]
        r["drink"] += drink
        if tea and o["ch"] in IN_STORE:
            r["tea"] += 1
    r["days"] = len(days)
    for name, c in r["ch"].items():
        c[2] = len(ch_days.get(name, ()))
    r["waCust"] = len(wa_cnt)
    r["waNew"] = len([p for p in wa_cnt if (first_day.get(p) or "0") >= start])
    r["waRep"] = len([p for p, n in wa_cnt.items() if n >= 2])
    r["disc"] = round(r["disc"], 2)
    r["_prods"] = prods
    return r


def strip(r):
    r = dict(r)
    r.pop("_prods", None)
    return r


def top_products(prods, k):
    return [[n, round(v[0], 2), round(v[1], 2)] for n, v in sorted(prods.items(), key=lambda kv: -kv[1][1])[:k]]


def daily(orders):
    out = {}
    for o in orders:
        if is_sale(o) or is_refund(o):
            v = out.setdefault(o["day"], [0.0, 0])
            v[0] += o["net"]
            v[1] += 1 if is_sale(o) else 0
    return out


def build_branch(name, orders, first_day, D):
    d = iso_d(D)
    day_tot = daily(orders)
    d28 = [d_iso(d - timedelta(days=i)) for i in range(27, -1, -1)]
    med = median([day_tot[x][0] for x in d28 if x in day_tot])
    short = set(x for x in day_tot if day_tot[x][0] < SHORT_RATIO * med)

    res = {"name": name}
    day = base(orders, first_day, D, D)
    res["day"] = strip(day)
    res["day"]["top"] = top_products(day["_prods"], 8)
    res["day"]["short"] = D in short
    lw_d = d_iso(d - timedelta(days=7))
    res["lw"] = strip(base(orders, first_day, lw_d, lw_d))
    res["lw"]["short"] = lw_d in short
    same = [d_iso(d - timedelta(days=7 * k)) for k in range(1, 5)]
    same = [x for x in same if x in day_tot and x not in short]
    res["avg4"] = [
        sum(day_tot[x][0] for x in same) / len(same) if same else 0.0,
        sum(day_tot[x][1] for x in same) / float(len(same)) if same else 0.0,
        len(same),
    ]

    w1 = base(orders, first_day, d_iso(d - timedelta(days=6)), D)
    w0 = base(orders, first_day, d_iso(d - timedelta(days=13)), d_iso(d - timedelta(days=7)))
    res["w1"], res["w0"] = strip(w1), strip(w0)
    diffs = []
    for pname in set(w1["_prods"]) | set(w0["_prods"]):
        a = w1["_prods"].get(pname, [0.0, 0.0])
        b = w0["_prods"].get(pname, [0.0, 0.0])
        diffs.append([pname, round(a[1] - b[1], 2), round(a[0], 2), round(b[0], 2)])
    res["up"] = [x for x in sorted(diffs, key=lambda x: -x[1]) if x[1] > 0][:5]
    res["down"] = [x for x in sorted(diffs, key=lambda x: x[1]) if x[1] < 0][:5]

    res["series"] = [[x, round(day_tot.get(x, [0, 0])[0], 2), day_tot.get(x, [0, 0])[1], x in short] for x in d28]
    wd_vals = {}
    for x in d28:
        if x in day_tot and x not in short:
            wd_vals.setdefault(js_wd(iso_d(x)), []).append(day_tot[x][0])
    res["wdavg"] = [[(sum(wd_vals[i]) / len(wd_vals[i])) if wd_vals.get(i) else 0.0, len(wd_vals.get(i, []))] for i in range(7)]

    heat = [[0.0] * len(HEAT_HOURS) for _ in range(7)]
    wd_days = {}
    valid = set(x for x in d28 if x in day_tot and x not in short)
    for x in valid:
        wd_days[js_wd(iso_d(x))] = wd_days.get(js_wd(iso_d(x)), 0) + 1
    dp28 = {}
    for o in orders:
        # day parts and hours: sales only (a refund is punched at another hour than the sale)
        if not is_sale(o) or o["ch"] not in IN_STORE or o["day"] < d28[0] or o["day"] > D:
            continue
        p = dp28.setdefault(daypart(o["hour"]), [0.0, 0])
        p[0] += o["net"]
        p[1] += 1
        if o["day"] in valid:
            hh = min(max(o["hour"], HEAT_HOURS[0]), HEAT_HOURS[-1])
            heat[js_wd(iso_d(o["day"]))][hh - HEAT_HOURS[0]] += o["net"]
    for wd in range(7):
        n = wd_days.get(wd, 0)
        heat[wd] = [round(v / n / 100.0, 1) if n else 0.0 for v in heat[wd]]
    res["heat"], res["dp28"] = heat, dp28

    m_from = d.replace(day=1)
    prev_end_month = m_from - timedelta(days=1)
    pm_from = prev_end_month.replace(day=1)
    pm_to = prev_end_month.replace(day=min(d.day, prev_end_month.day))
    m1 = base(orders, first_day, d_iso(m_from), D)
    m0 = base(orders, first_day, d_iso(pm_from), d_iso(pm_to))
    res["m1"] = strip(m1)
    res["m1"]["top"] = [[n, q, s, round(m0["_prods"].get(n, [0, 0])[1], 2)] for n, q, s in top_products(m1["_prods"], 10)]
    mdays = [x for x in sorted(day_tot) if d_iso(m_from) <= x <= D]
    full = [x for x in mdays if x not in short]
    res["m1"]["best"] = [max(full, key=lambda x: day_tot[x][0]), round(day_tot[max(full, key=lambda x: day_tot[x][0])][0], 2)] if full else None
    res["m1"]["worst"] = [min(full, key=lambda x: day_tot[x][0]), round(day_tot[min(full, key=lambda x: day_tot[x][0])][0], 2)] if full else None
    res["m1"]["shortDays"] = [x for x in mdays if x in short]
    res["m0"] = strip(m0)
    res["m0"]["from"], res["m0"]["to"] = d_iso(pm_from), d_iso(pm_to)

    d30_from = d_iso(d - timedelta(days=29))
    d30 = base(orders, first_day, d30_from, D)
    res["d30"] = strip(d30)
    pairs = {}
    for o in orders:
        if not is_sale(o) or o["day"] < d30_from or o["day"] > D:
            continue
        names = sorted(set(l["name"] for l in o["lines"]
                           if l["sub"] > 0 and not l["extra"] and not l["reward"] and not WATER_TEA_RE.match(l["name"])))
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                key = names[i] + " + " + names[j]
                pairs[key] = pairs.get(key, 0) + 1
    res["pairs"] = [[k, v] for k, v in sorted(pairs.items(), key=lambda kv: (-kv[1], kv[0]))[:6]]
    menu = {}
    for o in orders:
        if not is_sale(o) or o["day"] < d30_from or o["day"] > D:
            continue
        for l in o["lines"]:
            if l["sub"] > 0 and not l["extra"] and not l["reward"] and l["fam"] != "Diğer":
                m = menu.setdefault(l["name"], [0.0, 0.0])
                m[0] += l["qty"]
                m[1] += l["sub"]
    res["slow"] = [[n, round(v[0], 2), round(v[1], 2)] for n, v in sorted(menu.items(), key=lambda kv: (kv[1][1], kv[0]))[:6]]
    res["menuN"] = len(menu)
    return res


def window_start(D):
    """First business day the report needs (previous month start or 35 days back, whichever is earlier)."""
    d = iso_d(D)
    prev_month = (d.replace(day=1) - timedelta(days=1)).replace(day=1)
    return min(prev_month, d - timedelta(days=34))


def build(D, branches):
    """branches: {"K": {"name": ..., "orders": [...]} ...}, plus first_day: {partner_id: ISO}."""
    out = {"D": D, "br": {}}
    for key, b in branches.items():
        out["br"][key] = build_branch(b["name"], b["orders"], b.get("first_day") or {}, D)
    return out
