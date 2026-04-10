/** @odoo-module */

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

patch(PosStore.prototype, {
    /**
     * Override pay() to block payment when the order has unsent kitchen changes.
     * In restaurant mode, the order must first be sent to the kitchen via
     * the "Order" button before the cashier can proceed to payment.
     */
    async pay() {
        if (this.config.module_pos_restaurant) {
            const currentOrder = this.get_order();
            var ifAllRefund = false;
            currentOrder.lines.forEach((line) => {
                ifAllRefund = false
                if(line.refunded_orderline_id){
                    ifAllRefund = true
                }
            });
            if(ifAllRefund){
                return super.pay();
            }
            if (currentOrder && !currentOrder.finalized) {
                const changes = this.getOrderChanges();
                const hasUnsent =
                    changes.nbrOfChanges > 0 ||
                    changes.generalNote !== undefined ||
                    changes.modeUpdate;

                if (hasUnsent) {
                    this.dialog.add(AlertDialog, {
                        title: _t("Order Not Sent to Kitchen"),
                        body: _t("You must send the order to the kitchen before proceeding to payment. Please click the 'Order' button first."),
                    });
                    return;
                }

                // Also block if the order has never been sent to kitchen at all
                // (brand new order with lines but last_order_preparation_change is empty)
                const lastChange = currentOrder.last_order_preparation_change;
                if (
                    currentOrder.lines.length > 0 &&
                    Object.keys(lastChange.lines).length === 0 &&
                    !lastChange.metadata?.serverDate
                ) {
                    this.dialog.add(AlertDialog, {
                        title: _t("Order Not Sent to Kitchen"),
                        body: _t(
                            "You must send the order to the kitchen before proceeding to payment. Please click the 'Order' button first."
                        ),
                    });
                    return;
                }
            }
        }
        return super.pay();
    },
});
