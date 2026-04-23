/** @odoo-module **/

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";

patch(PosStore.prototype, {
    /**
     * Capture the currently logged-in employee as the "waiter" (order opener)
     * at the moment the order is created. This is separate from employee_id
     * which pos_hr may later update when the cashier takes over.
     */
    createNewOrder() {
        const order = super.createNewOrder(...arguments);

        // Only set if pos_hr is active and an employee is logged in
        const cashier = this.get_cashier?.();
        if (cashier?.id && !order.opened_by_employee_id) {
            order.update({ opened_by_employee_id: cashier });
        }

        return order;
    },
});
