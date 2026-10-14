/** @odoo-module */

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { _t } from "@web/core/l10n/translation";
import { CancelReasonPopup, DISCOUNT_REASONS } from "@cz_customizations/app/utils/cancel_reason_popup/cancel_reason_popup";

patch(ProductScreen.prototype, {
    getProductName(product) {
        if (product.short_name) {
            return product.short_name;
        }
        return super.getProductName(...arguments);
    },

    /**
     * Ask the discount reason the moment the cashier presses the "%" numpad
     * button, BEFORE any digit is typed, so typing is never interrupted.
     * Loyalty reward lines are skipped. If the popup is dismissed, we do not
     * switch to discount mode at all.
     */
    async onNumpadClick(buttonValue) {
        if (buttonValue === "discount") {
            const order = this.pos.get_order();
            const line = order && order.get_selected_orderline();
            if (
                line &&
                !line.discount_reason_code &&
                !(line.is_reward_line || line.reward_id)
            ) {
                const payload = await makeAwaitable(this.dialog, CancelReasonPopup, {
                    title: _t("Discount Reason"),
                    reasons: DISCOUNT_REASONS,
                });
                if (!payload) {
                    return; // No reason, no discount mode
                }
                line.discount_reason_code = payload.code;
                line.discount_reason = payload.text;
            }
        }
        return super.onNumpadClick(...arguments);
    },
});
