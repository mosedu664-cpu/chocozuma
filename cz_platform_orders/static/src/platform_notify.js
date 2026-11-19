/** @odoo-module **/

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

/**
 * Platform orders (Trendyol) in the cashier screen:
 *  - a short toast when a new platform order has been recorded as a sale
 *    (no action needed, nothing printed, no table used);
 *  - a gentle reminder when the cashier picks *TRENDYOL by hand, because
 *    chocolate Trendyol orders now arrive automatically.
 */
patch(PosStore.prototype, {
    async initServerData() {
        const res = await super.initServerData(...arguments);
        const notification = this.notification;
        const fmt = (value) => {
            try {
                return this.env.utils.formatCurrency(value || 0);
            } catch {
                return `${Number(value || 0).toFixed(2)} ₺`;
            }
        };
        this.data.connectWebSocket("CZ_PLATFORM_ORDER", (payload) => {
            try {
                notification.add(
                    `${payload.code ? "Kod " + payload.code + " | " : ""}${fmt(payload.amount)} | ${payload.items || ""}`,
                    { title: _t("TRENDYOL GO | Sipariş kasaya işlendi"), type: "info" }
                );
            } catch (e) {
                console.warn("cz_platform_orders notification", e);
            }
        });
        return res;
    },

    async selectPartner() {
        const res = await super.selectPartner(...arguments);
        const partner = this.get_order()?.get_partner?.();
        if (partner && (partner.name || "").toUpperCase().startsWith("*TRENDYOL")) {
            this.notification.add(
                _t(
                    "Trendyol çikolata siparişleri otomatik giriliyor. Kahvaltı siparişini elle girebilirsiniz."
                ),
                { title: _t("Hatırlatma"), type: "info", sticky: false }
            );
        }
        return res;
    },
});
