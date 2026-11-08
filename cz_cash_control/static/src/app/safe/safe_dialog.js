import { _t } from "@web/core/l10n/translation";
import { Component, useRef, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { parseFloat } from "@web/views/fields/parsers";
import { CashMoveReceipt } from "@point_of_sale/app/navbar/cash_move_popup/cash_move_receipt/cash_move_receipt";
import { formatDateTime } from "@web/core/l10n/dates";
import { czPrint } from "@cz_cash_control/app/printing/cz_print";

const { DateTime } = luxon;
const PHOTO_MAX_SIDE = 1280;
const PHOTO_QUALITY = 0.8;

/**
 * "Küçük Kasa" — the branch safe inside the POS, for managers only (PIN asked
 * before opening, re-checked by the server on every call).
 *
 * The manager pays directly from the safe (daily wages, courier, cleaning, ads…).
 * Nothing here touches the drawer. Each payment is booked at once so the safe
 * balance stays true, and is listed for the accountant as "Entered in the POS".
 */
export class CzSafeDialog extends Component {
    static template = "cz_cash_control.CzSafeDialog";
    static components = { Dialog };
    static props = {
        info: Object,
        auth: Object, // { manager, pin }
        close: Function,
    };

    setup() {
        this.pos = usePos();
        this.notification = useService("notification");
        this.printer = useService("printer");
        this.photoInput = useRef("czSafePhoto");
        this.state = useState({
            info: this.props.info,
            tab: "pay", // pay | history
            categoryId: false,
            amount: "",
            note: "",
            employeeId: "",
            receiptRef: "",
            photo: "",
            photoBusy: false,
            saving: false,
            lastResult: null,
        });
    }

    fmt(v) {
        return this.env.utils.formatCurrency(v);
    }

    iconClass(c) {
        const icon = (c.icon || "fa-tag").trim();
        return `fa fa-fw ${icon.startsWith("fa-") ? icon : "fa-" + icon}`;
    }

    get info() {
        return this.state.info;
    }

    get category() {
        return this.info.categories.find((c) => c.id === this.state.categoryId) || null;
    }

    get amount() {
        return this.env.utils.isValidFloat(this.state.amount) ? parseFloat(this.state.amount) : 0;
    }

    get needsEmployee() {
        return Boolean(this.category?.requires_employee);
    }

    get needsReceipt() {
        const c = this.category;
        return Boolean(c && c.requires_receipt_above && this.amount > c.requires_receipt_above);
    }

    get overMax() {
        const c = this.category;
        return Boolean(c && c.max_amount && this.amount > c.max_amount);
    }

    get overSafe() {
        return this.amount > (this.info.expected || 0) + 0.001;
    }

    get problems() {
        const p = [];
        if (!this.category) p.push(_t("Kategori seçin"));
        if (!(this.amount > 0)) p.push(_t("Tutarı yazın"));
        if (this.state.note.trim().length < 3) p.push(_t("Ne ödendiğini ve kime ödendiğini yazın"));
        if (this.needsEmployee && !this.state.employeeId) p.push(_t("Personeli seçin"));
        if (this.needsReceipt && !this.state.receiptRef.trim() && !this.state.photo)
            p.push(_t("Fiş numarası veya fotoğraf gerekli"));
        if (this.overMax) p.push(_t("Bu kategori için azami tutar aşıldı"));
        if (this.overSafe) p.push(_t("Kasadaki beklenen nakitten fazla"));
        return p;
    }

    get canConfirm() {
        return !this.problems.length && !this.state.saving && !this.state.photoBusy;
    }

    selectCategory(id) {
        this.state.categoryId = id;
        this.state.lastResult = null;
    }

    // ------------------------------------------------------------------ photo
    takePhoto() {
        this.photoInput.el?.click();
    }

    removePhoto() {
        this.state.photo = "";
    }

    async onPhoto(ev) {
        const file = ev.target.files?.[0];
        ev.target.value = "";
        if (!file) return;
        if (!file.type.startsWith("image/")) {
            this.notification.add(_t("Lütfen bir fotoğraf seçin."), { type: "warning" });
            return;
        }
        this.state.photoBusy = true;
        try {
            this.state.photo = await new Promise((resolve, reject) => {
                const url = URL.createObjectURL(file);
                const img = new Image();
                img.onload = () => {
                    try {
                        const scale = Math.min(1, PHOTO_MAX_SIDE / Math.max(img.width, img.height));
                        const canvas = document.createElement("canvas");
                        canvas.width = Math.round(img.width * scale);
                        canvas.height = Math.round(img.height * scale);
                        canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
                        resolve(canvas.toDataURL("image/jpeg", PHOTO_QUALITY));
                    } catch (e) {
                        reject(e);
                    } finally {
                        URL.revokeObjectURL(url);
                    }
                };
                img.onerror = (e) => {
                    URL.revokeObjectURL(url);
                    reject(e);
                };
                img.src = url;
            });
        } catch (e) {
            console.error(e);
            this.notification.add(_t("Fotoğraf okunamadı, tekrar deneyin."), { type: "danger" });
        } finally {
            this.state.photoBusy = false;
        }
    }

    // ------------------------------------------------------------------ actions
    async reload() {
        this.state.info = await this.pos.data.call(
            "pos.session",
            "cz_safe_info",
            [[this.pos.session.id], this.props.auth.manager.id, this.props.auth.pin],
            {},
            true
        );
    }

    async confirm() {
        if (!this.canConfirm) return;
        this.state.saving = true;
        const cat = this.category;
        const amount = this.amount;
        const note = this.state.note.trim();
        const employee = this.info.employees.find((e) => String(e.id) === String(this.state.employeeId));
        try {
            const res = await this.pos.data.call("pos.session", "cz_safe_payment", [
                [this.pos.session.id],
                this.props.auth.manager.id,
                this.props.auth.pin,
                cat.id,
                amount,
                note,
                employee ? employee.id : false,
                this.state.receiptRef.trim(),
                this.state.photo ? this.state.photo.split(",", 2)[1] : false,
            ]);
            this.state.lastResult = { ...res, category: cat.name };
            this.notification.add(_t("Küçük kasadan ödendi: %(ref)s — %(amount)s", { ref: res.name, amount: this.fmt(amount) }), {
                type: "success",
            });
            this._print(res, cat, note, employee);
            Object.assign(this.state, {
                categoryId: false,
                amount: "",
                note: "",
                employeeId: "",
                receiptRef: "",
                photo: "",
            });
            await this.reload();
        } catch (e) {
            console.error(e);
            this.notification.add(e?.data?.message || e?.message || _t("İşlem yapılamadı."), { type: "danger" });
        } finally {
            this.state.saving = false;
        }
    }

    _print(res, cat, note, employee) {
        const parts = [_t("KÜÇÜK KASADAN ÖDEME %s", res.name), cat.name];
        if (employee) parts.push(employee.name);
        parts.push(note);
        parts.push(_t("Onay: %s", this.props.auth.manager.name));
        czPrint(this.pos, this.printer, CashMoveReceipt, {
            reason: parts.join(" — "),
            translatedType: _t("out"),
            formattedAmount: this.fmt(res.amount),
            headerData: this.pos.getReceiptHeaderData(),
            date: formatDateTime(DateTime.now()),
        });
    }
}
