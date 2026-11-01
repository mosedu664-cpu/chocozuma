import { Component } from "@odoo/owl";
import { ReceiptHeader } from "@point_of_sale/app/screens/receipt_screen/receipt/receipt_header/receipt_header";

/**
 * Printed "Gün Sonu" slip that goes into the envelope / bag with the cash.
 * Everything is pre-formatted by pos.session.cz_eod_summary (server side).
 */
export class CzEodReceipt extends Component {
    static template = "cz_cash_control.CzEodReceipt";
    static components = { ReceiptHeader };
    static props = {
        summary: Object,
        headerData: Object,
        cashier: String,
        manager: String,
        envelope: String,
        posName: String,
        date: String,
    };
}
