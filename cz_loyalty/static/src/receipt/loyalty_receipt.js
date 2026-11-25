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
const CZ_MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"];

/** Whole days from today (the POS's local date) to the launch day; 0 or less once launched. */
function czDaysToLaunch(iso) {
    if (!iso) {
        return 0;
    }
    const [y, m, d] = iso.split("-").map(Number);
    const now = new Date();
    const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
    return Math.round((Date.UTC(y, m - 1, d) - today) / 86400000);
}

function czLaunchLabel(iso) {
    if (!iso) {
        return "";
    }
    const [, m, d] = iso.split("-").map(Number);
    return `${d} ${CZ_MONTHS[m - 1]}`.toLocaleUpperCase("tr-TR");
}

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
        const days = czDaysToLaunch(config.cz_loyalty_launch);
        // live: the banknote · sealed (last 3 days): banknote with a real QR, "opens on launch day"
        // count (4+ days out): a countdown with no QR at all.
        const phase = days <= 0 ? "live" : days <= 3 ? "sealed" : "count";
        return {
            phase,
            days,
            qr: phase === "count" ? false : qrCodeSrc(`https://wa.me/${number}?text=${text}`, { size: 300 }),
            serial: `${code.slice(0, 4)} ${code.slice(4)}`,
            hours: config.cz_loyalty_valid_hours || 72,
            launch: czLaunchLabel(config.cz_loyalty_launch),
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
            hint = this.pos.config.cz_loyalty_hint && order && order.czKakaoData();
        } catch (e) {
            console.error("cz_loyalty: hint skipped", e);
        }
        const result = await super.afterOrderValidation(...arguments);
        if (hint) {
            try {
                const msg = {
                    live: ["\u2726 Bu fişte kakao banknotu var",
                        "Misafire söyleyin: «Fişinizde bir kakao taneniz var, kameranızla okutun.»"],
                    sealed: ["\u2726 Bu fişte mühürlü kakao tanesi var",
                        "Misafire söyleyin: «Bu fişi saklayın, 1 Aralık'ta açılıyor. İlk kakao taneniz içinde.»"],
                    count: ["\u2726 Kakao Hazinesi geliyor",
                        "Misafir sorarsa: «Çok yakında. Fişinizin altında ipucu var.»"],
                }[hint.phase] || [];
                if (msg.length) {
                    this.pos.notification.add(msg[1], { title: msg[0], type: "info" });
                }
            } catch (e) {
                console.error("cz_loyalty: hint skipped", e);
            }
        }
        return result;
    },
});
