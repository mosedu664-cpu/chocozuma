/*@odoo-module*/
/* Copyright (c) 2016-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>) */
/* See LICENSE file for full copyright and licensing details. */
/* License URL : <https://store.webkul.com/license.html/> */

import { Component } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { Navbar } from "@point_of_sale/app/navbar/navbar";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { InvoiceButton } from "@point_of_sale/app/screens/ticket_screen/invoice_button/invoice_button";

export class DirectPrintPrinterstatus extends Component {
    static template = "DirectPrintPrinterstatus";
    static props = {};
    setup() {
        this.pos = usePos();
    }
    async refresh_printer_info() {
        var res = await this.pos.refresh_printer_info()
        return true
    }
    get isHostmachineOnline() {
        return this.printer?.is_hostmachine_online
    }
    get printer() {
        return this.pos.direct_printer
    }
    get totalWaitQueue() {
        return this.printer ? this.printer.pending_print_jobs + (this.printer.receiptQueue ? this.printer.receiptQueue.length : 0) : 0
    }
}
patch(Navbar, {
    components: { ...Navbar.components, DirectPrintPrinterstatus },
});

patch(PaymentScreen.prototype, {
    shouldDownloadInvoice() {
        return this.pos.config.raw.invoice_operation == 'print' && this.pos.config.raw.selected_invoice_printer
            ? false
            : super.shouldDownloadInvoice();
    },
    async afterOrderValidation(suggestToSync = true) {
        this.ui.block();
        if (this.currentOrder.is_to_invoice() && this.pos.config.raw.invoice_operation == 'print' && this.pos.config.raw.selected_invoice_printer) {
            if (this.currentOrder.raw.account_move) {
                var res = await this.pos.printInvoiceByInvoicePrinter(this.currentOrder)
                if (!res) {
                    await this.invoiceService.downloadPdf(this.currentOrder.raw.account_move);
                }
            } else {
                throw {
                    code: 401,
                    message: "Backend Invoice",
                    data: { order: this.currentOrder },
                };
            }
        }

        if (
            this.pos.config.receipt_print_auto &&
            this.pos.config.use_direct_print &&
            this.pos.direct_printer &&
            !this.pos.config.iface_print_auto
        ) {
            if(this.pos.config.order_receipt_format === 'xml'){
                let order = this.pos.get_order();
                await this.pos.get_esc_receipt(order, 'print-complex');
            }
            else{
                await this.pos.printReceipt(this.currentOrder);
                await this.pos.refresh_printer_info()
            }
        }
        await super.afterOrderValidation(suggestToSync)
        this.ui.unblock();
    },
});


patch(InvoiceButton.prototype, {
    async _downloadInvoice(orderId) {
        let orderWithInvoice;
        try {
            orderWithInvoice = await this.pos.data.read("pos.order", [orderId], [], {
                load: false,
            });
        } catch (error) {
            if (error instanceof Error) {
                throw error;
            } else {
                // NOTE: error here is most probably undefined
                this.dialog.add(AlertDialog, {
                    title: _t("Network Error"),
                    body: _t("Unable to download invoice."),
                });
            }
            return false
        }
        const order = orderWithInvoice[0];
        const accountMoveId = order.raw.account_move;
        if (accountMoveId) {
            var res = await this.pos.printInvoiceByInvoicePrinter(order)
            if (!res) {
                await this.invoiceService.downloadPdf(order.raw.account_move);
            }
        } else {
            return super._downloadInvoice();
        }
    }
});
