# -*- coding: utf-8 -*-
"""Kitchen + depot stock (Central Kitchen products also stored at the Main Warehouse building).

Design
------
The depot shelves are modelled as *sub-locations of the Central Kitchen stock* (CKWH/Stock):

    CKWH/Stock
    ├── 1 Mutfak              kitchen shelves (putaway target of everything entering CKWH/Stock)
    └── 2 Depo                kitchen products kept in the Main Warehouse building
        ├── Dondurucu         freezer
        └── Soğuk Oda         chiller

Because the depot is inside CKWH/Stock, every existing flow keeps working unchanged:
sale orders, branch auto-orders, B2B deliveries and MOs still use the Central Kitchen
warehouse and *can reserve depot stock* — a delivery picks straight from the depot when
the stock is there (the car loads at the depot), the picking line shows "2 Depo/...".

Removal: CKWH/Stock uses "closest" (kitchen first, then depot) so MOs consume kitchen
shelves before depot stock; the B2B finished-goods categories (Toptan) use FIFO so the
oldest box leaves first wherever it is.

One snapshot (``stock.warehouse._cz_kitchen_snapshot``) feeds the chef screen and the
WhatsApp report, so the two can never disagree.
"""
import logging
from collections import defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero, float_round

_logger = logging.getLogger(__name__)

MOD = "cz_inventory_dashboard"
WATCH_PREFIXES = ("CZ-", "KM-", "PM-")
USAGE_DAYS = 14
OPEN_STATES = ("assigned", "waiting", "confirmed", "partially_available")


class ProductTemplate(models.Model):
    _inherit = "product.template"

    cz_chef_watch = fields.Boolean(
        "Şef takibi", help="Shown on the kitchen/depot stock screen and in the daily WhatsApp stock report.")
    cz_shelf_days = fields.Integer(
        "Raf ömrü (gün)", help="Days a batch may stay in stock. The daily report warns at 75% and at 100%.")
    cz_depot_zone = fields.Selection(
        [("freezer", "Dondurucu"), ("chill", "Soğuk Oda")], string="Depo bölgesi",
        help="Where this product goes when it is sent to the depot (putaway rule kept in sync).")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "cz_chef_watch" not in vals and (vals.get("default_code") or "").startswith(WATCH_PREFIXES):
                vals["cz_chef_watch"] = True
        records = super().create(vals_list)
        records.filtered("cz_depot_zone")._cz_sync_depot_putaway()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "cz_depot_zone" in vals:
            self._cz_sync_depot_putaway()
        return res

    def _cz_sync_depot_putaway(self):
        """One putaway rule per product on '2 Depo' pointing at its zone."""
        locs = self.env["stock.warehouse"]._cz_locations(raise_if_missing=False)
        if not locs:
            return
        Rule = self.env["stock.putaway.rule"].sudo()
        zone_loc = {"freezer": locs["freezer"], "chill": locs["chill"]}
        for tmpl in self:
            products = tmpl.with_context(active_test=False).product_variant_ids
            rules = Rule.search([("location_in_id", "=", locs["depot"].id), ("product_id", "in", products.ids)])
            target = zone_loc.get(tmpl.cz_depot_zone)
            if not target:
                rules.unlink()
                continue
            for product in products:
                rule = rules.filtered(lambda r: r.product_id == product)
                if rule:
                    rule[:1].location_out_id = target.id
                    (rule - rule[:1]).unlink()
                else:
                    Rule.create({
                        "location_in_id": locs["depot"].id, "location_out_id": target.id,
                        "product_id": product.id, "company_id": locs["depot"].company_id.id,
                    })


class StockWarehouse(models.Model):
    _inherit = "stock.warehouse"

    # ------------------------------------------------------------- structure
    @api.model
    def _cz_kitchen_env(self):
        """Self bound to the kitchen's company whatever the company switcher shows
        (the user must belong to that company)."""
        stock = _ref(self.env(su=True), "loc_ck_stock")
        if not stock:
            raise UserError(_("The kitchen/depot locations are not set up yet (module %s).", MOD))
        company = stock.company_id
        if not self.env.su and company not in self.env.user.company_ids:
            raise UserError(_("You do not have access to %s.", company.name))
        return self.with_context(allowed_company_ids=[company.id])

    @api.model
    def _cz_locations(self, raise_if_missing=True):
        refs = {
            "stock": "loc_ck_stock", "kitchen": "loc_ck_kitchen", "depot": "loc_ck_depot",
            "freezer": "loc_ck_depot_freezer", "chill": "loc_ck_depot_chill",
            "type_out": "type_kitchen_to_depot", "type_in": "type_depot_to_kitchen",
        }
        res = {}
        for key, xml in refs.items():
            rec = _ref(self.env, xml)
            if not rec:
                if raise_if_missing:
                    raise UserError(_("The kitchen/depot locations are not set up yet (module %s).", MOD))
                return {}
            res[key] = rec
        res["warehouse"] = res["stock"].warehouse_id
        return res

    @api.model
    def _cz_setup_kitchen_depot(self):
        """Idempotent: runs at every install/upgrade of the module. Creates nothing twice."""
        wh = self.sudo().with_context(active_test=False).search([("code", "=", "CKWH")], limit=1)
        if not wh:
            _logger.info("cz_inventory_dashboard: no CKWH warehouse, kitchen/depot setup skipped")
            return
        env = self.env(su=True, context=dict(self.env.context, allowed_company_ids=[wh.company_id.id]))
        Loc = env["stock.location"].with_context(active_test=False)

        def ref(xml):
            return _ref(env, xml)

        def bind(xml, rec):
            # system parameters, not module xmlids: uninstalling the module must never delete a location
            env["ir.config_parameter"].set_param("%s.%s" % (MOD, xml), "%s,%s" % (rec._name, rec.id))
            return rec

        def loc(xml, name, parent):
            rec = ref(xml) or Loc.search([("name", "=", name), ("location_id", "=", parent.id)], limit=1)
            if not rec:
                rec = Loc.create({"name": name, "location_id": parent.id, "usage": "internal",
                                  "company_id": wh.company_id.id})
            if not rec.active:
                rec.active = True
            return bind(xml, rec)

        stock = bind("loc_ck_stock", wh.lot_stock_id)
        kitchen = loc("loc_ck_kitchen", "1 Mutfak", stock)
        depot = loc("loc_ck_depot", "2 Depo", stock)
        loc("loc_ck_depot_freezer", "Dondurucu", depot)
        chill = loc("loc_ck_depot_chill", "Soğuk Oda", depot)

        # everything that enters CKWH/Stock (MOs, receipts, returns) lands on the kitchen shelves
        Rule = env["stock.putaway.rule"]
        if not Rule.search([("location_in_id", "=", stock.id), ("product_id", "=", False), ("category_id", "=", False)]):
            Rule.create({"location_in_id": stock.id, "location_out_id": kitchen.id, "company_id": wh.company_id.id})

        # kitchen shelves first, depot last (location names sort "1 Mutfak" < "2 Depo")
        closest = env.ref("stock.removal_closest")
        if stock.removal_strategy_id != closest:
            stock.removal_strategy_id = closest.id
        # B2B finished goods: oldest box first, wherever it is
        fifo = env.ref("stock.removal_fifo")
        for categ in env["product.category"].search([("complete_name", "=like", "All / Toptan%")]):
            if not categ.removal_strategy_id:
                categ.removal_strategy_id = fifo.id

        PT = env["stock.picking.type"].with_context(active_test=False)
        for xml, name, code, src, dest, seq in (
            ("type_kitchen_to_depot", "Mutfak → Depo", "MD", kitchen, depot, 30),
            ("type_depot_to_kitchen", "Depo → Mutfak", "DM", depot, kitchen, 31),
        ):
            rec = ref(xml) or PT.search([("warehouse_id", "=", wh.id), ("sequence_code", "=", code)], limit=1)
            vals = {"default_location_src_id": src.id, "default_location_dest_id": dest.id}
            if not rec:
                rec = PT.create(dict(vals, name=name, code="internal", sequence_code=code, sequence=seq,
                                     warehouse_id=wh.id, company_id=wh.company_id.id))
            else:
                rec.write(dict(vals, active=True))
            bind(xml, rec)

        # first run: chef watch on the kitchen product families
        Tmpl = env["product.template"].with_context(active_test=False)
        if not Tmpl.search_count([("cz_chef_watch", "=", True)]):
            domain = ["|"] * (len(WATCH_PREFIXES) - 1) + [("default_code", "=like", p + "%") for p in WATCH_PREFIXES]
            Tmpl.search(domain).write({"cz_chef_watch": True})
        _logger.info("cz_inventory_dashboard: kitchen/depot structure ready (%s, %s)", kitchen.complete_name, chill.complete_name)

    @api.model
    def cz_move_legacy_to_kitchen(self):
        """One-off: put the free quantity still sitting directly on CKWH/Stock onto '1 Mutfak'.
        Reserved quantity and negative quants are left where they are (they are listed as data errors)."""
        if not self.env.user.has_group("stock.group_stock_manager"):
            raise UserError(_("Only inventory administrators."))
        self = self._cz_kitchen_env()
        locs = self._cz_locations()
        quants = self.env["stock.quant"].sudo().search([("location_id", "=", locs["stock"].id), ("quantity", ">", 0)])
        moved = 0
        for quant in quants:
            free = quant.quantity - quant.reserved_quantity
            if float_compare(free, 0, precision_rounding=quant.product_uom_id.rounding) <= 0:
                continue
            vals = quant.with_context(inventory_name=_("Kurulum: Mutfak rafına taşındı"))._get_inventory_move_values(
                free, quant.location_id, locs["kitchen"], quant.package_id, quant.package_id)
            self.env["stock.move"].sudo().create(vals)._action_done()
            moved += 1
        return moved

    # -------------------------------------------------------------- snapshot
    @api.model
    def _cz_kitchen_snapshot(self, usage_days=USAGE_DAYS):
        """Everything the chef screen and the daily report show, computed once.

        Quantities are in the product's own unit. 'Kitchen' = CKWH/Stock and every child that is
        not under '2 Depo' (legacy quants on CKWH/Stock itself count as kitchen).
        """
        self = self._cz_kitchen_env()
        locs = self._cz_locations()
        company = locs["stock"].company_id
        env = self.env
        now = fields.Datetime.now()
        since = now - timedelta(days=usage_days)
        depot_ids = set(env["stock.location"].search([("id", "child_of", locs["depot"].id)]).ids)
        freezer_ids = set(env["stock.location"].search([("id", "child_of", locs["freezer"].id)]).ids)
        chill_ids = set(env["stock.location"].search([("id", "child_of", locs["chill"].id)]).ids)
        all_ids = set(env["stock.location"].search([("id", "child_of", locs["stock"].id)]).ids)

        def bucket(loc_id):
            if loc_id in freezer_ids:
                return "freezer"
            if loc_id in chill_ids:
                return "chill"
            if loc_id in depot_ids:
                return "depot_other"
            return "kitchen"

        quants = env["stock.quant"].search([("location_id", "in", list(all_ids))])
        watched = env["product.product"].search([("product_tmpl_id.cz_chef_watch", "=", True)])
        products = watched | quants.filtered(lambda q: q.location_id.id in depot_ids).product_id

        rows = {}

        def row(p):
            r = rows.get(p.id)
            if r is None:
                r = rows[p.id] = {
                    "id": p.id, "tmpl_id": p.product_tmpl_id.id, "code": p.default_code or "", "name": p.name,
                    "uom": p.uom_id.name, "rounding": p.uom_id.rounding, "family": _family(p.default_code),
                    "kitchen": 0.0, "freezer": 0.0, "chill": 0.0, "depot_other": 0.0, "reserved": 0.0,
                    "age_kitchen": None, "age_depot": None, "shelf": p.product_tmpl_id.cz_shelf_days or 0,
                    "zone": p.product_tmpl_id.cz_depot_zone or "", "use_day": 0.0, "kitchen_use_day": 0.0,
                    "made": 0.0, "demand": 0.0, "min": 0.0, "max": 0.0, "flags": [],
                }
            return r

        for p in products:
            row(p)
        for q in quants:
            if q.product_id.id not in rows:
                continue
            r = rows[q.product_id.id]
            b = bucket(q.location_id.id)
            r[b] += q.quantity
            r["reserved"] += q.reserved_quantity
            if q.quantity > 0 and q.in_date:
                age = (now - q.in_date).total_seconds() / 86400.0
                key = "age_kitchen" if b == "kitchen" else "age_depot"
                r[key] = age if r[key] is None else max(r[key], age)

        pids = list(rows)
        loc_list = list(all_ids)
        Move = env["stock.move"]
        # outflow: done moves leaving CKWH/Stock (deliveries, MO consumption, scrap, transfers out), not count corrections
        for g in Move._read_group(
            [("state", "=", "done"), ("date", ">=", since), ("product_id", "in", pids),
             ("location_id", "in", loc_list), ("location_dest_id", "not in", loc_list), ("is_inventory", "=", False)],
            ["product_id", "location_dest_id"], ["product_qty:sum"],
        ):
            product, dest, qty = g
            r = rows[product.id]
            r["use_day"] += qty / usage_days
            if dest.usage == "production":
                r["kitchen_use_day"] += qty / usage_days
        for product, qty in Move._read_group(
            [("state", "=", "done"), ("date", ">=", since), ("product_id", "in", pids), ("production_id", "!=", False),
             ("location_dest_id", "in", loc_list)], ["product_id"], ["product_qty:sum"],
        ):
            rows[product.id]["made"] = qty
        # open demand from the kitchen for the next two days (deliveries + MOs) not yet covered
        horizon = now + timedelta(days=2)
        for product, need, done in Move._read_group(
            [("state", "in", OPEN_STATES), ("product_id", "in", pids), ("location_id", "in", loc_list),
             ("location_dest_id", "not in", loc_list), ("date", "<=", horizon)],
            ["product_id"], ["product_qty:sum", "quantity:sum"],
        ):
            rows[product.id]["demand"] = need
        for op in env["stock.warehouse.orderpoint"].search(
            [("product_id", "in", pids), ("location_id", "in", loc_list), ("company_id", "=", company.id)]
        ):
            r = rows[op.product_id.id]
            r["min"] += op.product_min_qty
            r["max"] += op.product_max_qty

        alerts = {"produce": [], "fetch": [], "shortage": [], "expired": [], "expiring": [], "negative": [],
                  "no_zone": [], "transit": [], "depot_consumed": []}
        for r in rows.values():
            rnd = r["rounding"]
            r["depot"] = r["freezer"] + r["chill"] + r["depot_other"]
            r["total"] = r["kitchen"] + r["depot"]
            r["free"] = r["total"] - r["reserved"]
            r["days"] = (r["total"] / r["use_day"]) if r["use_day"] > 0 and r["total"] > 0 else (0.0 if r["use_day"] > 0 else None)
            for k in ("kitchen", "freezer", "chill", "depot_other", "depot", "total", "free", "reserved",
                      "use_day", "kitchen_use_day", "made", "demand", "min", "max"):
                r[k] = float_round(r[k], precision_rounding=rnd) if rnd else r[k]
            neg = [k for k in ("kitchen", "freezer", "chill", "depot_other") if float_compare(r[k], 0, precision_rounding=rnd) < 0]
            if neg:
                r["flags"].append("negative")
                alerts["negative"].append(r["id"])
            if r["min"] and float_compare(r["total"], r["min"], precision_rounding=rnd) < 0:
                r["to_make"] = float_round(max(r["max"], r["min"]) - r["total"], precision_rounding=rnd)
                r["flags"].append("produce")
                alerts["produce"].append(r["id"])
            short = r["demand"] - max(r["total"], 0)
            if r["demand"] and float_compare(short, 0, precision_rounding=rnd) > 0:
                r["short"] = float_round(short, precision_rounding=rnd)
                r["flags"].append("shortage")
                alerts["shortage"].append(r["id"])
            # used in kitchen recipes, less than one day on the kitchen shelf, the depot has it
            if r["kitchen_use_day"] > 0 and r["depot"] > 0 and r["kitchen"] < r["kitchen_use_day"]:
                r["fetch"] = float_round(min(r["depot"], 2 * r["kitchen_use_day"] - max(r["kitchen"], 0)), precision_rounding=rnd)
                r["flags"].append("fetch")
                alerts["fetch"].append(r["id"])
            if r["shelf"]:
                oldest = max([a for a in (r["age_kitchen"], r["age_depot"]) if a is not None] or [0])
                if oldest >= r["shelf"]:
                    r["flags"].append("expired")
                    alerts["expired"].append(r["id"])
                elif oldest >= 0.75 * r["shelf"]:
                    r["flags"].append("expiring")
                    alerts["expiring"].append(r["id"])
            if r["depot"] > 0 and not r["zone"]:
                alerts["no_zone"].append(r["id"])

        # transfers kitchen <-> depot started but not validated for more than 6 hours (in the car? forgotten?)
        late = now - timedelta(hours=6)
        transit = []
        for p in env["stock.picking"].search([
            ("picking_type_id", "in", [locs["type_out"].id, locs["type_in"].id]),
            ("state", "in", OPEN_STATES), ("create_date", "<=", late)], order="create_date"):
            transit.append({"id": p.id, "name": p.name, "type": p.picking_type_id.name,
                            "hours": round((now - p.create_date).total_seconds() / 3600.0),
                            "lines": len(p.move_ids)})
        alerts["transit"] = transit
        # MO components taken straight from the depot in the last 24 h: stock moved without a Depo → Mutfak transfer
        for ml in env["stock.move.line"].search([
            ("state", "=", "done"), ("date", ">=", now - timedelta(hours=24)),
            ("location_id", "in", list(depot_ids)), ("location_dest_id.usage", "=", "production")]):
            alerts["depot_consumed"].append({"product": ml.product_id.display_name, "qty": ml.quantity,
                                             "uom": ml.product_uom_id.name, "mo": ml.move_id.raw_material_production_id.name or ""})

        return {
            "company": company.name,
            "company_id": company.id,
            "as_of": fields.Datetime.context_timestamp(self.with_context(tz="Europe/Istanbul"), now).strftime("%d.%m.%Y %H:%M"),
            "usage_days": usage_days,
            "locations": {k: locs[k].complete_name for k in ("kitchen", "depot", "freezer", "chill")},
            "rows": sorted(rows.values(), key=lambda r: (r["family"], r["code"] or r["name"])),
            "alerts": alerts,
            "transfer_types": {"out": locs["type_out"].id, "in": locs["type_in"].id},
        }


def _ref(env, xml):
    value = env["ir.config_parameter"].sudo().get_param("%s.%s" % (MOD, xml))
    if not value:
        return None
    model, rid = value.split(",")
    rec = env[model].sudo().with_context(active_test=False).browse(int(rid)).exists()
    return rec.with_env(env) if rec else None


def _family(code):
    code = code or ""
    if code.startswith("CZ-"):
        return "1_b2b"
    if code.startswith(("KM-", "PM-")):
        return "2_semi"
    return "3_other"


class StockPicking(models.Model):
    _inherit = "stock.picking"

    @api.model
    def cz_stock_board_data(self):
        """Chef screen: the shared snapshot (read under the user's own access rights)."""
        return self.env["stock.warehouse"]._cz_kitchen_snapshot()

    @api.model
    def cz_stock_board_transfer(self, direction, lines):
        """Create a DRAFT transfer kitchen→depot ('out') or depot→kitchen ('in') and open it.
        lines: [{'product_id': int, 'qty': float}]. Nothing is validated here: the receiving side
        checks the quantities in the transfer form and validates."""
        wh = self.env["stock.warehouse"]._cz_kitchen_env()
        self = self.with_env(wh.env)
        locs = wh._cz_locations()
        ptype = locs["type_out"] if direction == "out" else locs["type_in"]
        moves = []
        for line in lines or []:
            product = self.env["product.product"].browse(int(line["product_id"]))
            qty = float(line.get("qty") or 0)
            if not product.exists() or qty <= 0:
                continue
            moves.append((0, 0, {
                "name": product.display_name, "product_id": product.id, "product_uom_qty": qty,
                "product_uom": product.uom_id.id,
                "location_id": ptype.default_location_src_id.id, "location_dest_id": ptype.default_location_dest_id.id,
            }))
        if not moves:
            raise UserError(_("Select at least one product with a quantity."))
        picking = self.create({
            "picking_type_id": ptype.id,
            "location_id": ptype.default_location_src_id.id,
            "location_dest_id": ptype.default_location_dest_id.id,
            "move_ids": moves,
        })
        picking.action_confirm()
        picking.action_assign()
        return {"type": "ir.actions.act_window", "res_model": "stock.picking", "res_id": picking.id,
                "views": [[False, "form"]], "target": "current"}
