import { Component } from "@odoo/owl";
import { Orderline } from "@point_of_sale/app/generic_components/orderline/orderline";
import { OrderWidget } from "@point_of_sale/app/generic_components/order_widget/order_widget";
import { ReceiptHeader } from "@point_of_sale/app/screens/receipt_screen/receipt/receipt_header/receipt_header";
import { omit } from "@point_of_sale/utils";

export class KotReceipt extends Component {
    static template = "cnc_pos_kot.KotReceipt";
    static components = {
        Orderline,
        OrderWidget,
        ReceiptHeader,
    };
    static props = {
        data: Object,
        formatCurrency: Function,
        basic_receipt: { type: Boolean, optional: true },
    };
    static defaultProps = {
        basic_receipt: false,
    };

    omit(...args) {
        return omit(...args);
    }

    doesAnyOrderlineHaveTaxLabel() {
        return this.props.data.orderlines.some((line) => line.taxGroupLabels);
    }

    hasKitchenNotes() {
        return this.props.data.orderlines.some((line) => line.customer_note || line.internal_note);
    }
}