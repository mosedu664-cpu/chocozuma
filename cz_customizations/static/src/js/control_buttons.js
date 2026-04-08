/** @odoo-module **/

import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { patch } from "@web/core/utils/patch";
import { useAsyncLockedMethod } from "@point_of_sale/app/utils/hooks";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";

patch(ControlButtons.prototype, {
    setup() {
        super.setup(...arguments);
        this.onClickPrintReceiptDirectly = useAsyncLockedMethod(this.onClickPrintReceiptDirectly);
    },
    async onClickPrintReceiptDirectly() {
        try {
            const order = this.pos.get_order();
            if (!order || order.is_empty()) {
                if (this.notification) {
                    this.notification.add("Order is empty. Cannot print receipt.", { type: "danger" });
                }
                return;
            }
            if (this.notification) {
                this.notification.add("Printing...", { type: "info" });
            }

            // Temporary fix: Prevent string IDs (unvalidated order) from freezing ORM calls via Webkul.
            const originalId = order.id;
            const originalRawId = order.raw ? order.raw.id : null;
            if (typeof order.id !== "number") {
                order.id = 0;
            }
            if (order.raw && typeof order.raw.id !== "number") {
                order.raw.id = 0;
            }

            if (this.pos.config.use_direct_print && this.pos.direct_printer) {
                if (this.pos.config.order_receipt_format === 'xml' && typeof this.pos.get_esc_receipt === 'function') {
                    await this.pos.get_esc_receipt(order, 'print-complex');
                } else {
                    await this.pos.direct_printer.print(
                        OrderReceipt,
                        {
                            data: this.pos.orderExportForPrinting(order),
                            formatCurrency: this.env.utils.formatCurrency,
                            basic_receipt: false,
                        },
                        { webPrintFallback: true }
                    );
                }
            } else {
                await this.env.services.printer.print(
                    OrderReceipt,
                    {
                        data: this.pos.orderExportForPrinting(order),
                        formatCurrency: this.env.utils.formatCurrency,
                    }
                );
            }

            order.id = originalId;
            if (order.raw) {
                order.raw.id = originalRawId;
            }

            if (this.notification) {
                this.notification.add("Print command sent.", { type: "success" });
            }
        } catch (error) {
            console.error("Print Error:", error);
            if (this.notification) {
                this.notification.add("Error printing receipt: " + (error.message || error), { type: "danger" });
            }
        }
    }
});