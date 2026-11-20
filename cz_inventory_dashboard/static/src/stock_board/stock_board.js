/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const REFRESH_MS = 120000;
const FAMILY = { "1_b2b": "B2B Hazır Ürünler", "2_semi": "Yarı Mamul (Mutfak)", "3_other": "Diğer (depoda olan)" };
const FLAG = {
    shortage: ["Siparişe yetmiyor", "bad"],
    produce: ["Üretilmeli", "bad"],
    expired: ["Süresi doldu", "bad"],
    fetch: ["Depodan getir", "warn"],
    expiring: ["Süresi yaklaşıyor", "warn"],
    negative: ["Eksi stok (sayım)", "data"],
};

function fmt(v) {
    if (v === null || v === undefined) return "–";
    const a = Math.abs(v);
    const d = a >= 100 ? 0 : a >= 10 ? 1 : 2;
    return Number(v.toFixed(d)).toLocaleString("tr-TR");
}

export class CzKitchenStockBoard extends Component {
    static template = "cz_inventory_dashboard.StockBoard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            loading: true, data: null, error: null,
            view: "all", // all | b2b | semi | depot | alerts | <flag>
            q: "",
            sel: {}, // product id -> qty (string)
            dir: null, // 'out' | 'in' while the transfer panel is open
            busy: false,
        });
        this.fmt = fmt;
        this.FLAG = FLAG;
        onWillStart(() => this.load());
        this.timer = setInterval(() => !this.state.dir && this.load(true), REFRESH_MS);
        onWillUnmount(() => clearInterval(this.timer));
    }

    async load(silent = false) {
        if (!silent) this.state.loading = true;
        try {
            this.state.data = await this.orm.call("stock.picking", "cz_stock_board_data", []);
            this.state.error = null;
        } catch (e) {
            this.state.error = (e.data && e.data.message) || e.message || String(e);
        }
        this.state.loading = false;
    }

    // ---------------------------------------------------------------- derived
    get alerts() {
        const a = this.state.data ? this.state.data.alerts : {};
        return [
            { key: "shortage", n: (a.shortage || []).length, label: "Siparişe yetmiyor", sub: "2 gün içindeki sipariş/üretim", cls: "bad" },
            { key: "produce", n: (a.produce || []).length, label: "Üretilmeli", sub: "hedef stok altı", cls: "bad" },
            { key: "fetch", n: (a.fetch || []).length, label: "Depodan getir", sub: "mutfakta 1 günden az", cls: "warn" },
            { key: "expired", n: (a.expired || []).length + (a.expiring || []).length, label: "Raf ömrü", sub: "dolan + yaklaşan", cls: "warn" },
            { key: "negative", n: (a.negative || []).length, label: "Eksi stok", sub: "sayım gerekli", cls: "data" },
            { key: "transit", n: (a.transit || []).length, label: "Bekleyen transfer", sub: "6 saatten eski", cls: "warn" },
        ];
    }

    get rows() {
        const d = this.state.data;
        if (!d) return [];
        const v = this.state.view;
        const q = this.state.q.trim().toLocaleLowerCase("tr-TR");
        return d.rows.filter((r) => {
            if (q && !(`${r.code} ${r.name}`.toLocaleLowerCase("tr-TR").includes(q))) return false;
            if (v === "all") return true;
            if (v === "b2b") return r.family === "1_b2b";
            if (v === "semi") return r.family === "2_semi";
            if (v === "depot") return r.depot !== 0;
            if (v === "alerts") return r.flags.length > 0;
            if (v === "expired") return r.flags.includes("expired") || r.flags.includes("expiring");
            return r.flags.includes(v);
        });
    }

    get groups() {
        const out = [];
        for (const r of this.rows) {
            let g = out.find((x) => x.key === r.family);
            if (!g) out.push((g = { key: r.family, label: FAMILY[r.family] || r.family, rows: [] }));
            g.rows.push(r);
        }
        return out;
    }

    get selected() {
        const d = this.state.data;
        if (!d) return [];
        return d.rows.filter((r) => r.id in this.state.sel);
    }

    daysCls(r) {
        if (r.days === null) return "";
        if (r.days < 1) return "bad";
        if (r.days < 2) return "warn";
        return "";
    }

    ageCls(r) {
        const age = Math.max(r.age_kitchen || 0, r.age_depot || 0);
        if (!r.shelf) return "";
        if (age >= r.shelf) return "bad";
        if (age >= 0.75 * r.shelf) return "warn";
        return "";
    }

    oldest(r) {
        const a = [r.age_kitchen, r.age_depot].filter((x) => x !== null && x !== undefined);
        if (!a.length) return "–";
        const m = Math.max(...a);
        return m < 1 ? "bugün" : `${Math.floor(m)} g`;
    }

    // ---------------------------------------------------------------- actions
    setView(v) {
        this.state.view = this.state.view === v ? "all" : v;
    }

    toggle(r) {
        if (r.id in this.state.sel) delete this.state.sel[r.id];
        else this.state.sel[r.id] = "";
    }

    openTransit() {
        const ids = (this.state.data.alerts.transit || []).map((t) => t.id);
        this.action.doAction({
            type: "ir.actions.act_window", name: "Bekleyen Mutfak ↔ Depo transferleri", res_model: "stock.picking",
            domain: [["id", "in", ids]], views: [[false, "list"], [false, "form"]], target: "current",
        });
    }

    openProduct(r) {
        this.action.doAction({
            type: "ir.actions.act_window", res_model: "product.template", res_id: r.tmpl_id,
            views: [[false, "form"]], target: "current",
        });
    }

    openQuants(r) {
        this.action.doAction({
            type: "ir.actions.act_window", name: r.name, res_model: "stock.quant",
            domain: [["product_id", "=", r.id], ["location_id.usage", "=", "internal"]],
            context: { group_by: ["location_id"] },
            views: [[false, "list"]], target: "current",
        });
    }

    startTransfer(dir) {
        // defaults: send the free kitchen quantity; fetch the suggested quantity (or everything in the depot)
        for (const r of this.selected) {
            const def = dir === "out" ? Math.max(r.kitchen, 0) : (r.fetch || Math.max(r.depot, 0));
            this.state.sel[r.id] = def ? String(Number(def.toFixed(3))) : "";
        }
        this.state.dir = dir;
    }

    cancelTransfer() {
        this.state.dir = null;
    }

    async confirmTransfer() {
        const lines = this.selected
            .map((r) => ({ product_id: r.id, qty: parseFloat(String(this.state.sel[r.id]).replace(",", ".")) || 0 }))
            .filter((l) => l.qty > 0);
        if (!lines.length) {
            this.notification.add("Miktar girin.", { type: "warning" });
            return;
        }
        this.state.busy = true;
        try {
            const act = await this.orm.call("stock.picking", "cz_stock_board_transfer", [this.state.dir, lines]);
            this.state.sel = {};
            this.state.dir = null;
            await this.action.doAction(act);
        } catch (e) {
            this.notification.add((e.data && e.data.message) || e.message || String(e), { type: "danger" });
        }
        this.state.busy = false;
    }
}

registry.category("actions").add("cz_kitchen_stock_board", CzKitchenStockBoard);
