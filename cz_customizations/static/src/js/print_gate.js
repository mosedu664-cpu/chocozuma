/** @odoo-module **/

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { onWillStart } from "@odoo/owl";

/**
 * PRINT GATE — no receipt/bill may be printed before the order has been
 * sent to the kitchen.
 *
 * Same "unsent" signal as the pay gate (Store/pos_store.js). Paid
 * (finalized) orders and pure refunds are never blocked, so reprints after
 * payment keep working. Kitchen tickets (KOT / preparation printers) are not
 * affected: they do not go through the wrapped methods.
 *
 * The wrappers are installed on the INSTANCE after every module's patches
 * are applied, so they work whatever the load order of Print Direct
 * (pos_direct_print) or pos_restaurant, which override the same methods
 * without calling super.
 */

patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
        const originalPrintReceipt = this.printReceipt;
        this.printReceipt = async (...args) => {
            const order = (args[0] && args[0].order) || this.get_order();
            if (this.czBlockPrintIfUnsent(order)) {
                return false;
            }
            return originalPrintReceipt.apply(this, args);
        };
    },

    czHasUnsentKitchenChanges(order) {
        if (!this.config.module_pos_restaurant || !order || order.finalized) {
            return false;
        }
        const lines = order.lines || [];
        if (lines.length === 0) {
            return false;
        }
        if (lines.every((line) => line.refunded_orderline_id)) {
            return false; // pure refund
        }
        const changes = this.getOrderChanges(false, order);
        if (changes.nbrOfChanges > 0 || changes.generalNote !== undefined || changes.modeUpdate) {
            return true;
        }
        const lastChange = order.last_order_preparation_change || {};
        return (
            Object.keys(lastChange.lines || {}).length === 0 && !lastChange.metadata?.serverDate
        );
    },

    /** Returns true (and warns the cashier) when printing must be refused. */
    czBlockPrintIfUnsent(order) {
        if (!this.czHasUnsentKitchenChanges(order)) {
            return false;
        }
        this.dialog.add(AlertDialog, {
            title: _t("Order Not Sent to Kitchen"),
            body: _t(
                "Sipariş mutfağa gönderilmeden yazdırılamaz. Önce 'Order' butonuna basın.\n" +
                    "The order must be sent to the kitchen before printing. Please click the 'Order' button first."
            ),
        });
        return true;
    },
});

patch(ControlButtons.prototype, {
    setup() {
        super.setup(...arguments);
        // onWillStart runs after the whole setup chain, so the print methods
        // set by other patches (pos_restaurant "Bill", our "Print Receipt")
        // are final here and get wrapped exactly once.
        onWillStart(() => {
            for (const method of ["clickPrintBill", "onClickPrintReceiptDirectly"]) {
                const original = this[method];
                if (typeof original !== "function") {
                    continue;
                }
                this[method] = async (...args) => {
                    if (this.pos.czBlockPrintIfUnsent(this.pos.get_order())) {
                        return;
                    }
                    return original.apply(this, args);
                };
            }
        });
    },
});
