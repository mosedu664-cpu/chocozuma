/** @odoo-module **/

import { Component, useState, onWillStart, useRef, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const LIMIT = 20;

export class WkPrintJobsMenu extends Component {
    static template = "wk_odoo_direct_print.WkPrintJobsMenu";
    static props = {};

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");
        this.root   = useRef("root");

        this.state = useState({
            open:  false,
            tab:   "Queue",
            jobs:  { Queue: [], Done: [], Failed: [] },
            offset: { Queue: 0, Done: 0, Failed: 0 },
            hasMore: { Queue: false, Done: false, Failed: false },
            loading: false,
        });

        onWillStart(() => this._load("Queue"));
        onWillStart(() => this._load("Done"));
        onWillStart(() => this._load("Failed"));

        useEffect(() => {
            const handler = (e) => {
                if (this.state.open && !this.root.el?.contains(e.target)) {
                    this.state.open = false;
                }
            };
            document.addEventListener("click", handler, true);
            return () => document.removeEventListener("click", handler, true);
        });
    }

    async _load(tab, offset = 0) {
        this.state.loading = true;
        const stateMap = { Queue: "Queue", Done: "Done", Failed: "Failed" };

        const records = await this.orm.searchRead(
            "print.jobs",
            [["state", "=", stateMap[tab]]],
            ["name", "state", "printer_id", "msg", "write_date",
                "print_job_for", "model_ref", "rec_ref"],
            { order: "write_date desc", limit: LIMIT + 1, offset }
        );

        const hasMore = records.length > LIMIT;
        const data    = hasMore ? records.slice(0, LIMIT) : records;

        if (offset === 0) {
            this.state.jobs[tab] = data;
        } else {
            this.state.jobs[tab] = [...this.state.jobs[tab], ...data];
        }

        this.state.offset[tab]  = offset;
        this.state.hasMore[tab] = hasMore;
        this.state.loading      = false;
    }

    async toggle() {
        if (!this.state.open) {
            await this._load("Queue");
            await this._load("Done");
            await this._load("Failed");
        }
        this.state.open = !this.state.open;
    }

    async setTab(tab) {
        this.state.tab = tab;
    }

    async loadMore() {
        const tab    = this.state.tab;
        const offset = this.state.offset[tab] + LIMIT;
        await this._load(tab, offset);
    }

    get activeJobs() {
        return this.state.jobs[this.state.tab] || [];
    }

    get counts() {
        return {
            Queue:  this.state.jobs.Queue.length,
            Done:   this.state.jobs.Done.length,
            Failed: this.state.jobs.Failed.length,
        };
    }

    get currentHasMore() {
        return this.state.hasMore[this.state.tab];
    }

    openAll() {
        this.state.open = false;
        this.action.doAction({
            type:      "ir.actions.act_window",
            name:      "Print Jobs",
            res_model: "print.jobs",
            view_mode: "list,form",
            views:     [[false, "list"], [false, "form"]],
            target:    "current",
        });
    }

    openJob(jobId) {
        this.state.open = false;
        this.action.doAction({
            type:      "ir.actions.act_window",
            name:      "Print Job",
            res_model: "print.jobs",
            res_id:    jobId,
            view_mode: "form",
            views:     [[false, "form"]],
            target:    "current",
        });
    }

    formatTime(dateStr) {
        if (!dateStr) return "";
        const date = new Date(dateStr);
        const now  = new Date();
        const diff = Math.floor((now - date) / 1000); // seconds

        if (diff < 60)                return "Just now";
        if (diff < 3600)              return `${Math.floor(diff / 60)} min ago`;
        if (diff < 86400)             return `${Math.floor(diff / 3600)} hr ago`;
        if (diff < 172800)            return "Yesterday";
        return date.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
    }

}

registry.category("systray").add("wk.PrintJobsMenu", {
    Component: WkPrintJobsMenu,
    sequence:  99,
});
