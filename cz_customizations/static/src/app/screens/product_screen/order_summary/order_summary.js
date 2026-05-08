/** @odoo-module **/

import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { patch } from "@web/core/utils/patch";
import { TextInputPopup } from "@point_of_sale/app/utils/input_popups/text_input_popup";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { _t } from "@web/core/l10n/translation";

patch(OrderSummary.prototype, {
    /**
     * Override _setValue to intercept order line removal.
     * If the line was already sent to the kitchen, ask for a reason and validation.
     */
    async _setValue(val) {
        if (this.pos.numpadMode === "quantity" && val === "remove") {
            const selectedLine = this.currentOrder.get_selected_orderline();
            
            // Check if the line has been sent to the kitchen.
            // In Odoo Restaurant, sent lines are tracked in last_order_preparation_change.
            const sentLines = this.currentOrder.last_order_preparation_change?.lines || {};
            const isSent = selectedLine && sentLines[selectedLine.preparationKey];

            if (isSent) {
                // 1. Ask for reason
                const reason = await makeAwaitable(this.dialog, TextInputPopup, {
                    title: _t("Line Cancellation Reason"),
                    placeholder: _t("Why is this line being removed?"),
                    startingValue: "",
                });

                if (!reason) {
                    return; // Abort removal
                }

                const trimmedReason = reason.trim();
                if (!trimmedReason) {
                    // We could show an alert here, but for now we just abort.
                    return;
                }

                // 2. Capture name of the person removing the line.
                // We use selectCashier to ensure a valid employee/manager is identified.
                let cashier = null;
                if (this.pos.selectCashier) {
                    cashier = await this.pos.selectCashier();
                }
                
                if (!cashier) {
                    // Fallback to currently logged in cashier if selectCashier was cancelled or unavailable
                    cashier = this.pos.get_cashier();
                }

                const personName = cashier ? cashier.name : this.pos.user.name;

                // 3. Log to backend chatter immediately if the order is synced.
                if (typeof this.currentOrder.id === "number") {
                    try {
                        await this.pos.data.callRelated("pos.order", "log_line_cancellation", [
                            [this.currentOrder.id],
                            {
                                product_name: selectedLine.get_full_product_name(),
                                reason: trimmedReason,
                                user_name: personName,
                            }
                        ]);
                    } catch (error) {
                        console.error("Failed to log line cancellation:", error);
                    }
                }
            }
        }
        return super._setValue(...arguments);
    }
});
