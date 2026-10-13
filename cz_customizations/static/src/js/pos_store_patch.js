/** @odoo-module **/

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { _t } from "@web/core/l10n/translation";
import { CancelReasonPopup } from "@cz_customizations/app/utils/cancel_reason_popup/cancel_reason_popup";

patch(PosStore.prototype, {
    /**
     * Override onDeleteOrder to prompt for a cancellation reason before proceeding.
     * The reason is chosen from a fixed list (plus optional note) and stored on the
     * order, both as text and as a reporting code (Selection field).
     */
    async onDeleteOrder(order) {
        // Ask for cancellation reason first
        const payload = await makeAwaitable(this.dialog, CancelReasonPopup, {
            title: _t("Cancellation Reason"),
        });

        // User dismissed the dialog — abort cancellation
        if (!payload) {
            return false;
        }

        // Store reason on the order object so deleteOrders can pass it to the server
        order._cancelReason = payload.text;
        order._cancelReasonCode = payload.code;

        return await super.onDeleteOrder(order);
    },

    /**
     * Override deleteOrders to pass the cancel reason to the backend RPC call.
     */
    async deleteOrders(orders, serverIds = []) {
        const ids = new Set();
        // Collect cancel reasons keyed by order id
        const reasonMap = {};

        for (const order of orders) {
            if (order && (await this._onBeforeDeleteOrder(order))) {
                if (
                    typeof order.id === "number" &&
                    Object.keys(order.last_order_preparation_change.lines).length > 0
                ) {
                    await this.checkPreparationStateAndSentOrderInPreparation(order, true);
                }

                const cancelled = this.removeOrder(order, false);
                this.removePendingOrder(order);
                if (!cancelled) {
                    return false;
                } else if (typeof order.id === "number") {
                    ids.add(order.id);
                    if (order._cancelReason) {
                        reasonMap[order.id] = {
                            text: order._cancelReason,
                            code: order._cancelReasonCode || false,
                        };
                    }
                }
            } else {
                return false;
            }
        }

        if (serverIds.length > 0) {
            for (const id of serverIds) {
                if (typeof id !== "number") {
                    continue;
                }
                ids.add(id);
            }
        }

        if (ids.size > 0) {
            const orderIds = Array.from(ids);
            const cancelReason = Object.values(reasonMap)[0] || null;
            // Write the reason onto the order record first, then cancel normally (no extra kwargs)
            if (cancelReason) {
                await this.data.ormWrite("pos.order", orderIds, {
                    cancel_reason: cancelReason.text,
                    cancel_reason_code: cancelReason.code,
                });
            }
            await this.data.callRelated("pos.order", "action_pos_order_cancel", [orderIds]);
            return true;
        }

        return true;
    },
});
