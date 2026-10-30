import { patch } from "@web/core/utils/patch";
import { Navbar } from "@point_of_sale/app/navbar/navbar";
import { Chrome } from "@point_of_sale/app/pos_app";

/**
 * With Cash Control the cashier (not only managers / invoicing users) must be
 * able to record drawer movements: control comes from categories and PINs,
 * not from hiding the button.
 */
patch(Navbar.prototype, {
    get showCashMoveButton() {
        if (this.pos.config.cz_cash_control && this.pos.config.cash_control) {
            return true;
        }
        return super.showCashMoveButton;
    },
});

patch(Chrome.prototype, {
    get showCashMoveButton() {
        if (this.pos.config.cz_cash_control && this.pos.config.cash_control) {
            return true;
        }
        return super.showCashMoveButton;
    },
});
