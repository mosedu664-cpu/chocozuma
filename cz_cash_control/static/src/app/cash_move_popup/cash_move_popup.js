import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { parseFloat } from "@web/views/fields/parsers";
import { onWillStart, useRef } from "@odoo/owl";
import { CashMovePopup } from "@point_of_sale/app/navbar/cash_move_popup/cash_move_popup";
import { askManagerPin } from "@cz_cash_control/app/manager_pin/manager_pin";
import { czPrint } from "@cz_cash_control/app/printing/cz_print";
import { CzCashMovesDialog } from "@cz_cash_control/app/cash_moves_list/cash_moves_dialog";

const TILE_LIMIT = 8;
const PHOTO_MAX_SIDE = 1280;
const PHOTO_QUALITY = 0.8;

/**
 * Categorised cash in/out.
 *
 * When the POS has Cash Control enabled the cashier must pick a category tile
 * (icon + colour, locked ones have a red border) and, depending on the category,
 * the staff member / receipt number or a receipt photo taken with the camera.
 * Tiles are ordered by 30-day usage; the last movements can be repeated in one tap.
 * Sensitive movements require a manager PIN. The accounting side of the category
 * is never shown in the POS.
 */
patch(CashMovePopup.prototype, {
    setup() {
        super.setup(...arguments);
        this.state.czCategoryId = false;
        this.state.czEmployeeId = false;
        this.state.czReceiptRef = "";
        this.state.czReceiptImage = ""; // data URL (jpeg) of the receipt photo
        this.state.czShowAll = false;
        this.state.czRecent = [];
        this.state.czPhotoBusy = false;
        this.czPinOk = false;
        this.czManagerName = "";
        this.czPhotoInput = useRef("czPhotoInput");
        // route the cash-move receipt to the real printer (direct print / IoT), never a browser dialog
        if (this.czEnabled) {
            const printerService = this.printer;
            this.printer = { print: (component, props) => czPrint(this.pos, printerService, component, props) };
        }
        onWillStart(async () => {
            if (!this.czEnabled || !this.pos.config.cz_show_recent) {
                return;
            }
            try {
                this.state.czRecent = await this.pos.data.call(
                    "pos.session",
                    "cz_recent_moves",
                    [this.pos.config.id],
                    {},
                    true
                );
            } catch {
                this.state.czRecent = []; // offline / older server: chips simply don't show
            }
        });
    },

    get czEnabled() {
        return Boolean(this.pos.config.cz_cash_control);
    },

    /** All categories usable for the current direction, most used first. */
    get czCategories() {
        const model = this.pos.models["cz.cash.category"];
        if (!model) {
            return [];
        }
        const dir = this.state.type;
        return [...model.getAll()]
            .filter((c) => c.direction === "both" || c.direction === dir)
            .sort(
                (a, b) =>
                    (b.usage_count || 0) - (a.usage_count || 0) ||
                    a.sequence - b.sequence ||
                    a.name.localeCompare(b.name)
            );
    },

    /** Tiles actually shown: the TILE_LIMIT most used ones, plus the selected one. */
    get czVisibleCategories() {
        const all = this.czCategories;
        if (this.state.czShowAll || all.length <= TILE_LIMIT) {
            return all;
        }
        const shown = all.slice(0, TILE_LIMIT);
        const selected = this.czCategory;
        if (selected && !shown.includes(selected)) {
            shown.push(selected);
        }
        return shown;
    },

    get czHiddenCount() {
        return Math.max(0, this.czCategories.length - this.czVisibleCategories.length);
    },

    get czCategory() {
        if (!this.state.czCategoryId) {
            return null;
        }
        return this.pos.models["cz.cash.category"].get(this.state.czCategoryId);
    },

    get czEmployees() {
        const model = this.pos.models["hr.employee"];
        return model ? [...model.getAll()].sort((a, b) => a.name.localeCompare(b.name)) : [];
    },

    get czAmount() {
        return this.env.utils.isValidFloat(this.state.amount) ? parseFloat(this.state.amount) : 0;
    },

    get czNeedsEmployee() {
        return Boolean(this.czCategory?.requires_employee);
    },

    get czNeedsReason() {
        return Boolean(this.czCategory?.requires_reason);
    },

    get czHasReason() {
        return (this.state.reason || "").trim().length >= 3;
    },

    get czNeedsReceipt() {
        const c = this.czCategory;
        return Boolean(c && c.requires_receipt_above && this.czAmount > c.requires_receipt_above);
    },

    /** A typed receipt number or a photo both satisfy the receipt rule. */
    get czHasReceipt() {
        return Boolean(this.state.czReceiptRef.trim() || this.state.czReceiptImage);
    },

    get czNeedsPin() {
        const c = this.czCategory;
        if (!c) {
            return false;
        }
        const cfgLimit = this.pos.config.cz_cash_out_pin_above;
        return Boolean(
            c.requires_pin ||
                (c.pin_above && this.czAmount > c.pin_above) ||
                (this.state.type === "out" && cfgLimit && this.czAmount > cfgLimit)
        );
    },

    get czOverMax() {
        const c = this.czCategory;
        return Boolean(c && c.max_amount && this.czAmount > c.max_amount);
    },

    /** Recent movements usable for the current direction. */
    get czRecentForType() {
        if (!this.pos.config.cz_show_recent) {
            return [];
        }
        return (this.state.czRecent || []).filter((r) => r.type === this.state.type);
    },

    czTileClass(cat) {
        const classes = ["cz-tile", `cz-color-${(cat.color || 0) % 12}`];
        if (cat.requires_pin) {
            classes.push("cz-tile-locked");
        }
        if (this.state.czCategoryId === cat.id) {
            classes.push("cz-tile-selected");
        }
        return classes.join(" ");
    },

    czIcon(cat) {
        const icon = (cat.icon || "fa-tag").trim();
        return `fa fa-fw ${icon.startsWith("fa-") ? icon : "fa-" + icon}`;
    },

    czSelectCategory(id) {
        this.state.czCategoryId = id;
        this.czPinOk = false;
        this.czManagerName = "";
    },

    /** "Hareketler": every movement of this session, read-only (corrections need a manager PIN). */
    czOpenMoves() {
        this.dialog.add(CzCashMovesDialog, {});
    },

    czToggleShowAll() {
        this.state.czShowAll = !this.state.czShowAll;
    },

    /** One tap: repeat a recent movement (still goes through every rule on confirm). */
    czApplyRecent(r) {
        if (r.type !== this.state.type) {
            this.onClickButton(r.type);
        }
        this.czSelectCategory(r.category_id);
        const emp = r.employee_id ? this.pos.models["hr.employee"]?.get(r.employee_id) : null;
        this.state.czEmployeeId = emp ? r.employee_id : false;
        this.state.amount = String(r.amount);
        this.state.reason = r.reason || "";
        this.state.czReceiptRef = "";
        this.state.czReceiptImage = "";
    },

    onClickButton(type) {
        super.onClickButton(...arguments);
        // category list depends on direction
        if (this.czCategory && !["both", type].includes(this.czCategory.direction)) {
            this.state.czCategoryId = false;
        }
    },

    // ------------------------------------------------------------------ receipt photo
    czTakePhoto() {
        this.czPhotoInput.el?.click();
    },

    async czOnPhotoSelected(ev) {
        const file = ev.target.files?.[0];
        ev.target.value = ""; // allow re-taking the same file
        if (!file) {
            return;
        }
        if (!file.type.startsWith("image/")) {
            this.notification.add(_t("Lütfen bir fotoğraf seçin."), { type: "warning" });
            return;
        }
        this.state.czPhotoBusy = true;
        try {
            this.state.czReceiptImage = await this._czShrinkImage(file);
        } catch (e) {
            console.error(e);
            this.notification.add(_t("Fotoğraf okunamadı, tekrar deneyin."), { type: "danger" });
        } finally {
            this.state.czPhotoBusy = false;
        }
    },

    czRemovePhoto() {
        this.state.czReceiptImage = "";
    },

    /** Downscale the camera picture to a receipt-friendly JPEG (≈150–300 KB). */
    _czShrinkImage(file) {
        return new Promise((resolve, reject) => {
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
    },

    // ------------------------------------------------------------------ validation / confirm
    isValidCashMove() {
        if (!this.czEnabled) {
            return super.isValidCashMove(...arguments);
        }
        if (!this.env.utils.isValidFloat(this.state.amount) || this.czAmount <= 0) {
            return false;
        }
        if (!this.czCategory) {
            return false;
        }
        if (this.czNeedsEmployee && !this.state.czEmployeeId) {
            return false;
        }
        if (this.czNeedsReason && !this.czHasReason) {
            return false;
        }
        if (this.czNeedsReceipt && !this.czHasReceipt) {
            return false;
        }
        if (this.czOverMax || this.state.czPhotoBusy) {
            return false;
        }
        return true;
    },

    async confirm() {
        if (this.czEnabled && this.czNeedsPin && !this.czPinOk) {
            const manager = await askManagerPin(
                this.pos,
                this.dialog,
                this.notification,
                _t("Yönetici PIN — %s", this.czCategory.name)
            );
            if (!manager) {
                return;
            }
            this.czPinOk = true;
            this.czManagerName = manager.name;
        }
        return super.confirm(...arguments);
    },

    _prepare_try_cash_in_out_payload(type, amount, reason, extras) {
        if (this.czEnabled) {
            const cashier = this.pos.get_cashier?.();
            Object.assign(extras, {
                cz_category_id: this.state.czCategoryId || false,
                cz_employee_id: this.state.czEmployeeId || false,
                cz_receipt_ref: this.state.czReceiptRef.trim(),
                cz_receipt_image: this.state.czReceiptImage
                    ? this.state.czReceiptImage.split(",", 2)[1]
                    : false,
                cz_pin_ok: this.czPinOk,
                cz_manager_name: this.czManagerName,
                cz_cashier_name: cashier ? cashier.name : this.pos.user?.name || "",
            });
        }
        return super._prepare_try_cash_in_out_payload(type, amount, reason, extras);
    },

    getMoveReceiptProps(formattedAmount) {
        const props = super.getMoveReceiptProps(...arguments);
        if (this.czEnabled && this.czCategory) {
            const parts = [`[${this.czCategory.code}] ${this.czCategory.name}`];
            if (this.state.czEmployeeId) {
                const emp = this.pos.models["hr.employee"]?.get(this.state.czEmployeeId);
                if (emp) {
                    parts.push(emp.name);
                }
            }
            if (this.state.reason.trim()) {
                parts.push(this.state.reason.trim());
            }
            if (this.state.czReceiptRef.trim()) {
                parts.push(_t("fiş %s", this.state.czReceiptRef.trim()));
            }
            if (this.state.czReceiptImage) {
                parts.push(_t("fiş fotoğrafı var"));
            }
            if (this.czManagerName) {
                parts.push(_t("Onay: %s", this.czManagerName));
            }
            props.reason = parts.join(" — ");
        }
        return props;
    },

    getMessage(formattedAmount) {
        const msg = super.getMessage(...arguments);
        return this.czEnabled && this.czCategory ? `${msg} [${this.czCategory.code}]` : msg;
    },
});
