/** @odoo-module **/

import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { patch } from "@web/core/utils/patch";
import { TextInputPopup } from "@point_of_sale/app/utils/input_popups/text_input_popup";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

patch(TicketScreen.prototype, {
    async onDoRefund() {
        const order = this.getSelectedOrder();
        if (!order) {
            return;
        }

        // --- Receipt verification before refund ---
        const enteredReceipt = await makeAwaitable(this.dialog, TextInputPopup, {
            title: _t("Receipt Verification"),
            placeholder: _t("Enter receipt number..."),
            startingValue: "",
        });

        // User cancelled the popup
        if (enteredReceipt === undefined || enteredReceipt === null) {
            return;
        }

        const trimmedInput = enteredReceipt.trim();

        if (!trimmedInput) {
            this.dialog.add(AlertDialog, {
                title: _t("Receipt Number Required"),
                body: _t("Please enter a receipt number to proceed with the refund."),
            });
            return;
        }

        // Validate the entered receipt number against order's pos_reference
        if (trimmedInput !== order.pos_reference) {
            this.dialog.add(AlertDialog, {
                title: _t("Invalid Receipt Number"),
                body: _t(
                    "The entered receipt number does not match. Refund cannot be processed."
                ),
            });
            return;
        }

        // Receipt matched — re-select the orderline to ensure state is intact,
        // then proceed with the original refund logic.
        const firstLine = order.get_orderlines()[0];
        if (firstLine && !this.getSelectedOrderlineId()) {
            this.state.selectedOrderlineIds[order.id] = firstLine.id;
        }
        this.numberBuffer.reset();

        await super.onDoRefund(...arguments);
    },
});
