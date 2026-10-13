/** @odoo-module **/

import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { patch } from "@web/core/utils/patch";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { _t } from "@web/core/l10n/translation";
import { CancelReasonPopup, DISCOUNT_REASONS } from "@cz_customizations/app/utils/cancel_reason_popup/cancel_reason_popup";

/**
 * Global discount ([DISC] product, pos_discount module): require a reason
 * BEFORE the percentage popup, then tag the generated discount line(s).
 * cz_customizations depends on pos_discount so this patch is applied on top
 * of the pos_discount implementation of clickDiscount / apply_discount.
 */
patch(ControlButtons.prototype, {
    async clickDiscount() {
        this._czDiscountReasonPayload = null;
        const payload = await makeAwaitable(this.dialog, CancelReasonPopup, {
            title: _t("Discount Reason"),
            reasons: DISCOUNT_REASONS,
        });
        if (!payload) {
            return; // No reason, no discount
        }
        this._czDiscountReasonPayload = payload;
        return super.clickDiscount(...arguments);
    },

    async apply_discount(pc) {
        await super.apply_discount(...arguments);
        const payload = this._czDiscountReasonPayload;
        if (!payload) {
            return;
        }
        const product = this.pos.config.discount_product_id;
        if (product) {
            const order = this.pos.get_order();
            for (const line of order.get_orderlines()) {
                if (line.get_product() === product) {
                    line.discount_reason_code = payload.code;
                    line.discount_reason = payload.text;
                }
            }
        }
        this._czDiscountReasonPayload = null;
    },
});
