import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { askManagerPinWithCode } from "@cz_cash_control/app/manager_pin/manager_pin";
import { CzSafeDialog } from "@cz_cash_control/app/safe/safe_dialog";

patch(PosStore.prototype, {
    /** cz.cash.safe is not a POS model: the many2one is read from the raw config data. */
    get czSafeId() {
        const raw = this.config.raw?.cz_safe_id;
        const val = raw !== undefined ? raw : this.config.cz_safe_id;
        return Array.isArray(val) ? val[0] : val?.id || val || false;
    },

    get czShowSafe() {
        return Boolean(this.config.cz_cash_control && this.czSafeId);
    },

    /** "Küçük Kasa": manager PIN → safe screen (balance, payments from the safe, history). */
    async czOpenSafe() {
        if (this._czSafeOpening) {
            return;
        }
        this._czSafeOpening = true;
        try {
            const auth = await askManagerPinWithCode(this, this.dialog, this.notification, _t("Yönetici PIN — küçük kasa"));
            if (!auth) {
                return;
            }
            let info;
            try {
                info = await this.data.call(
                    "pos.session",
                    "cz_safe_info",
                    [[this.session.id], auth.manager.id, auth.pin],
                    {},
                    true
                );
            } catch (e) {
                this.notification.add(e?.data?.message || _t("Küçük kasa açılamadı. İnternet bağlantısını kontrol edin."), {
                    type: "danger",
                });
                return;
            }
            this.dialog.add(CzSafeDialog, { info, auth });
        } finally {
            this._czSafeOpening = false;
        }
    },
});
