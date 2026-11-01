import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { NumberPopup } from "@point_of_sale/app/utils/input_popups/number_popup";
import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";
import { askManagerPinWithCode } from "@cz_cash_control/app/manager_pin/manager_pin";
import { DrawerCheckResultPopup } from "@cz_cash_control/app/drawer_check/drawer_check_popup";

patch(PosStore.prototype, {
    get czShowDrawerCheck() {
        return Boolean(this.config.cz_cash_control && this.config.cash_control);
    },

    /**
     * Mid-day drawer check (X-count): reason → manager PIN → blind count →
     * server records counted vs expected → result shown. The session stays open.
     */
    async czDrawerCheck() {
        if (this._czCheckRunning) {
            return;
        }
        this._czCheckRunning = true;
        try {
            const checkType = await makeAwaitable(this.dialog, SelectionPopup, {
                title: _t("Kasa sayımı — sebep"),
                list: [
                    { id: 1, label: _t("Vardiya devri"), item: "handover" },
                    { id: 2, label: _t("Ani sayım"), item: "spot" },
                ],
            });
            if (!checkType) {
                return;
            }
            const auth = await askManagerPinWithCode(
                this,
                this.dialog,
                this.notification,
                _t("Yönetici PIN — kasa sayımı")
            );
            if (!auth) {
                return;
            }
            const raw = await makeAwaitable(this.dialog, NumberPopup, {
                title: _t("Çekmecedeki tüm nakdi sayın ve tutarı yazın"),
                subtitle: _t("Beklenen tutar kayıttan önce gösterilmez"),
                isValid: (x) => this.env.utils.isValidFloat(x) && parseFloat(x) >= 0,
            });
            if (raw === undefined || raw === null || raw === "" || !this.env.utils.isValidFloat(raw)) {
                return;
            }
            const counted = parseFloat(raw);
            if (!(counted >= 0)) {
                return;
            }
            // every paid order must be on the server before the expected cash is computed
            try {
                await this.syncAllOrders({ throw: true });
            } catch {
                this.notification.add(
                    _t("Şu an sayım yapılamaz: bazı siparişler sisteme gönderilemedi (bağlantı yok). Bağlantı gelince tekrar deneyin."),
                    { type: "danger" }
                );
                return;
            }
            const cashier = this.get_cashier?.();
            const result = await this.data.call("pos.session", "cz_drawer_check", [
                [this.session.id],
                counted,
                checkType,
                auth.manager.id,
                auth.pin,
                cashier ? cashier.name : this.user?.name || "",
            ]);
            await makeAwaitable(this.dialog, DrawerCheckResultPopup, { result, checkType });
        } finally {
            this._czCheckRunning = false;
        }
    },
});
