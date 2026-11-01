/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const REFRESH_MS = 60000;

export class CzInventoryDashboard extends Component {
    static template = "cz_inventory_dashboard.Dashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.company = useService("company");
        this.state = useState({
            loading: true,
            data: null,
            tab: "out", // out | in | wh
            filter: "all", // all | late | ready | waiting | today
            busy: {},
            error: null,
        });
        onWillStart(() => this.load());
        this.timer = setInterval(() => this.load(true), REFRESH_MS);
        onWillUnmount(() => clearInterval(this.timer));
    }

    get companyId() {
        return this.company.currentCompany.id;
    }

    async load(silent = false) {
        if (!silent) this.state.loading = true;
        try {
            this.state.data = await this.orm.call("stock.picking", "cz_dashboard_data", [this.companyId]);
            this.state.error = null;
        } catch (e) {
            this.state.error = e.message || String(e);
        }
        this.state.loading = false;
    }

    // ---- derived ------------------------------------------------------
    get groups() {
        const d = this.state.data;
        if (!d) return [];
        const f = this.state.filter;
        const keep = (p) =>
            f === "all" ||
            (f === "late" && p.is_late) ||
            (f === "ready" && p.state === "assigned") ||
            (f === "waiting" && p.state !== "assigned") ||
            (f === "today" && p.is_today);
        return d.groups
            .map((g) => ({ ...g, pickings: g.pickings.filter(keep) }))
            .filter((g) => g.pickings.length);
    }

    get receipts() {
        const d = this.state.data;
        if (!d) return [];
        const f = this.state.filter;
        return d.receipts.filter(
            (p) =>
                f === "all" ||
                (f === "late" && p.is_late) ||
                (f === "ready" && p.state === "assigned") ||
                (f === "waiting" && p.state !== "assigned") ||
                (f === "today" && !p.is_late)
        );
    }

    stateLabel(s) {
        return { assigned: "Hazır", confirmed: "Bekliyor", waiting: "Bekliyor", draft: "Taslak" }[s] || s;
    }

    // ---- actions ------------------------------------------------------
    setTab(t) {
        this.state.tab = t;
    }
    setFilter(f) {
        this.state.filter = this.state.filter === f ? "all" : f;
    }

    openPicking(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "stock.picking",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openList(domain, name) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "stock.picking",
            domain,
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            context: { contact_display: "partner_address" },
            target: "current",
        });
    }

    openType(t, which) {
        const dom = [["picking_type_id", "=", t.id]];
        if (which === "ready") dom.push(["state", "=", "assigned"]);
        if (which === "waiting") dom.push(["state", "in", ["confirmed", "waiting"]]);
        if (which === "late") dom.push(["state", "in", ["assigned", "waiting", "confirmed"]], "|", ["scheduled_date", "<", new Date().toISOString().slice(0, 10)], ["has_deadline_issue", "=", true]);
        if (which === "done_7d") dom.push(["state", "=", "done"]);
        this.openList(dom, `${t.name} · ${which}`);
    }

    openPartner(g) {
        const who = this.state.data.has_sale
            ? ["|", ["partner_id", "=", g.partner_id], ["sale_id.partner_id", "=", g.partner_id]]
            : [["partner_id", "=", g.partner_id]];
        this.openList(
            [...who, ["picking_type_code", "in", ["outgoing", "dropship"]], ["state", "in", ["assigned", "waiting", "confirmed"]]],
            g.partner
        );
    }

    async act(p, what) {
        this.state.busy[p.id] = true;
        try {
            const res = await this.orm.call("stock.picking", "cz_dashboard_action", [p.id, what]);
            if (res.action) {
                await this.action.doAction(res.action, { onClose: () => this.load(true) });
            } else if (!res.ok) {
                this.notification.add(res.msg || "İşlem yapılamadı", { type: "warning" });
            } else {
                this.notification.add(what === "validate" ? "Teslimat onaylandı" : "Stok kontrolü yapıldı", { type: "success" });
            }
        } catch (e) {
            this.notification.add(e.message || String(e), { type: "danger" });
        }
        delete this.state.busy[p.id];
        await this.load(true);
    }
}

registry.category("actions").add("cz_inventory_dashboard", CzInventoryDashboard);
