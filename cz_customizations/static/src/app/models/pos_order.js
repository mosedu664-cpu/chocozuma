/** @odoo-module **/

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";

patch(PosOrder.prototype, {
    setup(vals) {
        super.setup(...arguments);
        // Handle the waiter field when loading from server or creating from JSON
        if (vals.opened_by_employee_id) {
            const employeeId = Array.isArray(vals.opened_by_employee_id) 
                ? vals.opened_by_employee_id[0] 
                : vals.opened_by_employee_id;
            this.opened_by_employee_id = this.models["hr.employee"].get(employeeId);
        }
    },
    serialize() {
        const res = super.serialize(...arguments);
        // Ensure the waiter field is sent to the server
        if (this.opened_by_employee_id) {
            res.opened_by_employee_id = typeof this.opened_by_employee_id === 'object' 
                ? this.opened_by_employee_id.id 
                : this.opened_by_employee_id;
        }
        return res;
    }
});
