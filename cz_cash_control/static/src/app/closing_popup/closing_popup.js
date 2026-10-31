import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { parseFloat } from "@web/views/fields/parsers";
import { ClosePosPopup } from "@point_of_sale/app/navbar/closing_popup/closing_popup";
import { ask } from "@point_of_sale/app/store/make_awaitable_dialog";
import { askManagerPin } from "@cz_cash_control/app/manager_pin/manager_pin";

/**
 * Blind count + controlled closing.
 *
 * - expected cash and the difference are hidden from the cashier (config flag)
 * - a count of 0 while there were cash sales needs a manager PIN
 * - a difference above the configured threshold needs a closing note + manager PIN
 */
patch(ClosePosPopup.prototype, {
    setup() {
        super.setup(...arguments);
        this.notification = useService("notification");
        this.czPinOk = false;
    },

    get czEnabled() {
        return Boolean(this.pos.config.cz_cash_control);
    },

    get czBlind() {
        return this.czEnabled && Boolean(this.pos.config.cz_blind_count);
    },

    czCountedCash() {
        if (!this.pos.config.cash_control || !this.props.default_cash_details?.id) {
            return null;
        }
        const raw = this.state.payments[this.props.default_cash_details.id]?.counted;
        return this.env.utils.isValidFloat(raw) ? parseFloat(raw) : null;
    },

    hasUserAuthority() {
        return this.czPinOk || super.hasUserAuthority(...arguments);
    },

    async confirm() {
        if (!this.czEnabled || !this.pos.config.cash_control) {
            return super.confirm(...arguments);
        }
        const counted = this.czCountedCash();
        const details = this.props.default_cash_details;
        const cashSales = details?.payment_amount || 0;
        const diff = this.getDifference(details.id);
        const threshold = this.pos.config.cz_diff_pin_above || 0;

        // 1. "0" while cash was sold: almost always a skipped count
        if (
            this.pos.config.cz_zero_count_pin &&
            counted !== null &&
            this.env.utils.floatIsZero(counted) &&
            cashSales > 0
        ) {
            const ok = await ask(this.dialog, {
                title: _t("Kasa sayımı 0"),
                body: _t(
                    "Bugün nakit satış vardı ama sayılan tutar 0 girildi. Çekmecedeki parayı gerçekten saydınız mı? " +
                        "Para küçük kasaya aktarıldıysa önce 'Nakit Çıkışı → Küçük Kasaya' kaydı yapın."
                ),
                confirmLabel: _t("Evet, çekmece boş"),
                cancelLabel: _t("Geri dön ve say"),
            });
            if (!ok) {
                return;
            }
            if (!this.czPinOk) {
                const manager = await askManagerPin(this.pos, this.dialog, this.notification, _t("Yönetici PIN — sıfır sayım"));
                if (!manager) {
                    return;
                }
                this.czPinOk = true;
                this.state.notes = `${this.state.notes || ""}\n[Sıfır sayım onayı: ${manager.name}]`.trim();
            }
        }

        // 2. big difference: note + manager PIN
        if (threshold && Math.abs(diff) > threshold) {
            if (!(this.state.notes || "").trim()) {
                this.notification.add(
                    _t("Kasa farkı var. Lütfen kapanış notuna farkın sebebini yazın."),
                    { type: "warning" }
                );
                return;
            }
            if (!this.czPinOk) {
                const manager = await askManagerPin(this.pos, this.dialog, this.notification, _t("Yönetici PIN — kasa farkı"));
                if (!manager) {
                    return;
                }
                this.czPinOk = true;
                this.state.notes = `${this.state.notes}\n[Fark onayı: ${manager.name}]`;
            }
        }
        return super.confirm(...arguments);
    },

    /** Category of kind safe_transfer usable for the end-of-day transfer */
    get czEodCategory() {
        const model = this.pos.models["cz.cash.category"];
        if (!model) {
            return null;
        }
        return (
            model
                .getAll()
                .filter((c) => c.kind === "safe_transfer" && ["out", "both"].includes(c.direction))
                .sort((a, b) => a.sequence - b.sequence)[0] || null
        );
    },

    get czShowEndOfDay() {
        return (
            this.czEnabled &&
            this.pos.config.cash_control &&
            Boolean(this.pos.config.cz_safe_id) &&
            Boolean(this.czEodCategory)
        );
    },

    /**
     * End of day: the cashier counts the drawer (blind), the whole counted amount is
     * moved to the safe with one manager PIN, the drawer closes at 0 and Odoo's
     * difference is still exactly (counted - expected).
     */
    async czEndOfDay() {
        const counted = this.czCountedCash();
        if (counted === null || counted < 0) {
            this.notification.add(_t("Önce çekmecedeki nakdi sayıp tutarı yazın."), { type: "warning" });
            return;
        }
        const cat = this.czEodCategory;
        const ok = await ask(this.dialog, {
            title: _t("Gün sonu"),
            body: _t(
                "Sayılan %s küçük kasaya aktarılacak ve çekmece 0 ile kapatılacak. Devam edilsin mi?",
                this.env.utils.formatCurrency(counted)
            ),
            confirmLabel: _t("Evet, aktar ve kapat"),
            cancelLabel: _t("Vazgeç"),
        });
        if (!ok) {
            return;
        }
        const manager = await askManagerPin(this.pos, this.dialog, this.notification, _t("Yönetici PIN — gün sonu"));
        if (!manager) {
            return;
        }
        if (counted > 0) {
            const cashier = this.pos.get_cashier?.();
            const formattedAmount = this.env.utils.formatCurrency(counted);
            await this.pos.data.call(
                "pos.session",
                "try_cash_in_out",
                [
                    [this.pos.session.id],
                    "out",
                    counted,
                    _t("Gün sonu — çekmece boşaltıldı"),
                    {
                        formattedAmount,
                        translatedType: _t("out"),
                        cz_category_id: cat.id,
                        cz_employee_id: false,
                        cz_receipt_ref: "",
                        cz_pin_ok: true,
                        cz_manager_name: manager.name,
                        cz_cashier_name: cashier ? cashier.name : this.pos.user?.name || "",
                        cz_end_of_day: true,
                    },
                ],
                {},
                true
            );
        }
        this.czPinOk = true;
        this.state.payments[this.props.default_cash_details.id].counted = "0";
        this.state.notes = `${this.state.notes || ""}\n[Gün sonu: ${this.env.utils.formatCurrency(counted)} küçük kasaya — onay ${manager.name}]`.trim();
        await this.closeSession();
    },

    autoFillCashCount() {
        // never let the cashier copy the expected amount in blind mode
        if (this.czBlind) {
            this.notification.add(_t("Kör sayım: beklenen tutar kopyalanamaz. Lütfen parayı sayın."), {
                type: "warning",
            });
            return;
        }
        return super.autoFillCashCount(...arguments);
    },
});
