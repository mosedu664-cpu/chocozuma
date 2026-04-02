import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";
import { markup } from "@odoo/owl";

patch(PosOrder.prototype, {
    export_for_printing(baseUrl, headerData) {
        const result = super.export_for_printing(...arguments);
        if (this.partner_id){
            result.partner = this.partner_id;
        }

        result.invoice_number = this.invoice_number || '';
        let company_address = '';
        if (this.company_id) {
            const street = this.company_id.street || '';
            const city = this.company_id.city || '';
            const country = (this.company_id.country_id && this.company_id.country_id.name) || '';
            const addressParts = [street, city, country].filter(part => part.trim() !== '');
            company_address = addressParts.join(', ');
        }
        result.headerData.company_address = company_address;
        return result;
    },
});