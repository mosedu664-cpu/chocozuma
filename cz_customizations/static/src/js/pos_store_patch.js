/** @odoo-module **/

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { _t } from "@web/core/l10n/translation";
import { CancelReasonPopup, DISCOUNT_REASONS } from "@cz_customizations/app/utils/cancel_reason_popup/cancel_reason_popup";

patch(PosStore.prototype, {
    /**
     * Skip the morning Opening Control popup: the previous closing balance
     * is carried over automatically as the opening cash. Real cash
     * counting stays where it matters — at session closing.
     */
    async openOpeningControl() {
        if (this.session && this.session.state === "opening_control") {
            try {
                await this.data.call("pos.session", "set_opening_control", [
                    this.session.id,
                    0,
                    "Otomatik açılış (0)",
                ]);
                this.session.state = "opened";
                return;
            } catch (e) {
                // Offline or any failure: fall back to the standard popup.
                return super.openOpeningControl(...arguments);
            }
        }
        return super.openOpeningControl(...arguments);
    },

    /**
     * Intercept ALL manual line discounts (numpad % mode and the restricted
     * NumberPopup flow both funnel through this method) and require a reason
     * from a fixed list, once per line. Loyalty reward lines are never touched:
     * they do not pass through this method, and are skipped explicitly anyway.
     */
    async setDiscountFromUI(line, val) {
        const numeric =
            typeof val === "number" ? val : parseFloat(String(val).replace(",", ".")) || 0;

        // Never interfere with loyalty program reward lines
        if (line && (line.is_reward_line || line.reward_id)) {
            return super.setDiscountFromUI(...arguments);
        }

        if (line && numeric !== 0 && !line.discount_reason_code) {
            if (line._czReasonAsking) {
                return; // A reason popup is already open for this line
            }
            line._czReasonAsking = true;
            let payload;
            try {
                payload = await makeAwaitable(this.dialog, CancelReasonPopup, {
                    title: _t("Discount Reason"),
                    reasons: DISCOUNT_REASONS,
                });
            } finally {
                line._czReasonAsking = false;
            }
            if (!payload) {
                return; // No reason, no discount
            }
            line.discount_reason_code = payload.code;
            line.discount_reason = payload.text;
        }

        // Discount cleared back to 0 — clear the stored reason too
        if (line && numeric === 0) {
            line.discount_reason_code = false;
            line.discount_reason = false;
        }

        return super.setDiscountFromUI(...arguments);
    },

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

                // GAP FIX: paths that call deleteOrders directly (session
                // closing bulk-cancel, etc.) bypass onDeleteOrder and its
                // popup. Ask here, per order, for any synced order with
                // lines that has no reason yet. Dismiss = abort everything.
                if (
                    typeof order.id === "number" &&
                    !order._cancelReason &&
                    order.lines &&
                    order.lines.length > 0
                ) {
                    const payload = await makeAwaitable(this.dialog, CancelReasonPopup, {
                        title: _t("İptal sebebi: %s", order.pos_reference || order.name || ""),
                    });
                    if (!payload) {
                        return false;
                    }
                    order._cancelReason = payload.text;
                    order._cancelReasonCode = payload.code;
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
            // Write each order's OWN reason before cancelling (was: first
            // reason applied to the whole batch).
            for (const [orderId, reason] of Object.entries(reasonMap)) {
                await this.data.ormWrite("pos.order", [parseInt(orderId)], {
                    cancel_reason: reason.text,
                    cancel_reason_code: reason.code,
                });
            }
            await this.data.callRelated("pos.order", "action_pos_order_cancel", [orderIds], {
                context: { from_pos: true },
            });
            return true;
        }

        return true;
    },
});
