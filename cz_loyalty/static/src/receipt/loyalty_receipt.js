/** @odoo-module **/

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";
import { qrCodeSrc } from "@point_of_sale/utils";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";

/**
 * Kakao Hazinesi: the cacao banknote under the receipt.
 *
 * The code itself is created by the server when the order is first saved, so it
 * is only known once the order has been synced. No code → no banknote: the
 * receipt prints exactly as before. Nothing here may ever break a print.
 */
patch(PosOrder.prototype, {
    export_for_printing(baseUrl, headerData) {
        const result = super.export_for_printing(...arguments);
        try {
            result.cz_kakao = this.czKakaoData();
        } catch (e) {
            console.error("cz_loyalty: banknote skipped", e);
            result.cz_kakao = false;
        }
        return result;
    },

    czKakaoData() {
        const config = this.config;
        const code = this.cz_loyalty_code;
        const number = config.cz_loyalty_wa_number;
        if (!config.cz_loyalty_receipt || !code || !number) {
            return false;
        }
        if (this.get_total_with_tax() < (config.cz_loyalty_min_amount || 0)) {
            return false;
        }
        const excluded = (config.cz_loyalty_excluded_partners || "")
            .split(",")
            .filter(Boolean)
            .map(Number);
        if (this.partner_id && excluded.includes(this.partner_id.id)) {
            return false;
        }
        const text = encodeURIComponent(`Kakao Hazinesi \u2726 ZUMA-${code}`);
        return {
            qr: qrCodeSrc(`https://wa.me/${number}?text=${text}`, { size: 300 }),
            serial: `${code.slice(0, 4)} ${code.slice(4)}`,
            hours: config.cz_loyalty_valid_hours || 72,
        };
    },
});

/**
 * First weeks: right after the payment of a receipt that carries the banknote, remind the cashier
 * what to say. One short toast, no click needed; switched off in the settings once it is a habit.
 */
patch(PaymentScreen.prototype, {
    async afterOrderValidation() {
        let hint = false;
        try {
            const order = this.currentOrder;
            hint = Boolean(this.pos.config.cz_loyalty_hint && order && order.czKakaoData());
        } catch (e) {
            console.error("cz_loyalty: hint skipped", e);
        }
        const result = await super.afterOrderValidation(...arguments);
        if (hint) {
            try {
                this.pos.notification.add(
                    "Misafire söyleyin: «Fişinizde bir kakao taneniz var, kameranızla okutun.»",
                    { title: "\u2726 Bu fişte kakao banknotu var", type: "info" }
                );
            } catch (e) {
                console.error("cz_loyalty: hint skipped", e);
            }
        }
        return result;
    },
});
