import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

/**
 * Result of a mid-day drawer check, shown only after the blind count was
 * recorded on the server (the figures can no longer change).
 */
export class DrawerCheckResultPopup extends Component {
    static template = "cz_cash_control.DrawerCheckResultPopup";
    static components = { Dialog };
    static props = {
        result: Object,
        checkType: String,
        close: Function,
        getPayload: { type: Function, optional: true },
    };

    fmt(value) {
        return this.env.utils.formatCurrency(value);
    }

    get isZero() {
        return Math.abs(this.props.result.difference) < 0.005;
    }

    get statusClass() {
        if (this.isZero) {
            return "alert-success";
        }
        return this.props.result.difference < 0 ? "alert-danger" : "alert-warning";
    }

    confirm() {
        this.props.getPayload?.(true);
        this.props.close();
    }
}
