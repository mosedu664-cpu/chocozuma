/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

export const CANCEL_REASONS = [
    { code: "KEY_ERR", label: "Hatalı tuşlama (yanlış ürün/adet)", danger: false },
    { code: "DUP", label: "Mükerrer sipariş (iki kere girildi)", danger: false },
    { code: "CUST_NP", label: "Müşteri iptali – ürün HAZIRLANMADI", danger: false },
    { code: "CUST_P", label: "Müşteri iptali – ürün HAZIRLANDI", danger: true },
    { code: "STOCK", label: "Stokta yok / ürün bitti", danger: false },
    { code: "PLATFORM", label: "Platform iptali (Getir/Yemeksepeti/Trendyol)", danger: false },
    { code: "COURIER", label: "Kurye sorunu (gecikme/rahatsızlık)", danger: false },
    { code: "KITCHEN", label: "Mutfak hatası – yeniden hazırlandı", danger: true },
    { code: "SWAP", label: "Ürün değişikliği (başka ürünle değişti)", danger: false },
    { code: "OTHER", label: "Diğer (açıklama zorunlu)", danger: false },
];

export const DISCOUNT_REASONS = [
    { code: "SADAKAT", label: "Sadakat / Zuma's Family", danger: false },
    { code: "SIKAYET", label: "Müşteri şikayeti / telafi", danger: true },
    { code: "IKRAM", label: "Yönetim ikramı / misafir", danger: false },
    { code: "PERSONEL", label: "Personel indirimi", danger: false },
    { code: "KAMPANYA", label: "Kampanya / promosyon", danger: false },
    { code: "PLATFORM", label: "Platform fiyat farkı", danger: false },
    { code: "DAIMI", label: "Daimi müşteri", danger: false },
    { code: "FIYAT", label: "Fiyat düzeltme / menü hatası", danger: false },
    { code: "OTHER", label: "Diğer (açıklama zorunlu)", danger: false },
];

export class CancelReasonPopup extends Component {
    static template = "cz_customizations.CancelReasonPopup";
    static components = { Dialog };
    static props = {
        title: { type: String, optional: true },
        reasons: { type: Array, optional: true },
        getPayload: Function,
        close: Function,
    };
    static defaultProps = {
        title: _t("Cancellation Reason"),
    };

    setup() {
        this.reasons = this.props.reasons || CANCEL_REASONS;
        this.state = useState({ code: "", note: "" });
    }

    select(code) {
        this.state.code = this.state.code === code ? "" : code;
    }

    get canApply() {
        if (!this.state.code) {
            return false;
        }
        if (this.state.code === "OTHER" && !this.state.note.trim()) {
            return false;
        }
        return true;
    }

    confirm() {
        if (!this.canApply) {
            return;
        }
        const reason = this.reasons.find((r) => r.code === this.state.code);
        const note = this.state.note.trim();
        this.props.getPayload({
            code: reason.code,
            label: reason.label,
            note: note,
            text: note ? `${reason.label} — ${note}` : reason.label,
        });
        this.props.close();
    }

    close() {
        this.props.close();
    }
}
