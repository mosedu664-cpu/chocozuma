import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { parseFloat } from "@web/views/fields/parsers";
import { CashMovePopup } from "@point_of_sale/app/navbar/cash_move_popup/cash_move_popup";
import { askManagerPin } from "@cz_cash_control/app/manager_pin/manager_pin";

/**
 * Categorised cash in/out.
 *
 * When the POS has Cash Control enabled the cashier must pick a category
 * (and, depending on the category, the staff member / receipt number) and
 * sensitive movements require a manager PIN. The accounting side of the
 * category is never shown in the POS.
 */
patch(CashMovePopup.prototype, {
    setup() {
        super.setup(...arguments);
        this.state.czCategoryId = false;
        this.state.czEmployeeId = false;
        this.state.czReceiptRef = "";
        this.czPinOk = false;
        this.czManagerName = "";
    },

    get czEnabled() {
        return Boolean(this.pos.config.cz_cash_control);
    },

    get czCategories() {
        const model = this.pos.models["cz.cash.category"];
        if (!model) {
            return [];
        }
        const dir = this.state.type;
        return [...model.getAll()]
            .filter((c) => c.direction === "both" || c.direction === dir)
            .sort((a, b) => a.sequence - b.sequence || a.name.localeCompare(b.name));
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

    get czNeedsReceipt() {
        const c = this.czCategory;
        return Boolean(c && c.requires_receipt_above && this.czAmount > c.requires_receipt_above);
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

    czSelectCategory(id) {
        this.state.czCategoryId = id;
        this.czPinOk = false;
        this.czManagerName = "";
    },

    onClickButton(type) {
        super.onClickButton(...arguments);
        // category list depends on direction
        if (this.czCategory && !["both", type].includes(this.czCategory.direction)) {
            this.state.czCategoryId = false;
        }
    },

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
        if (this.czNeedsReceipt && !this.state.czReceiptRef.trim()) {
            return false;
        }
        if (this.czOverMax) {
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
