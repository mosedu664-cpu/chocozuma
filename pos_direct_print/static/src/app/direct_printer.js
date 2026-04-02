/* @odoo-module */
/* Copyright (c) 2016-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>) */
/* See LICENSE file for full copyright and licensing details. */
/* License URL : <https://store.webkul.com/license.html/> */
import { BasePrinter } from "@point_of_sale/app/printer/base_printer";
import { loadAllImages } from "@point_of_sale/utils";

export class DirectPrinter extends BasePrinter {
    setup({ direct_printer_id, pos }) {
        super.setup(...arguments);
        this.direct_printer_id = direct_printer_id
        this.pos = pos
        this.renderer = pos.env.services.renderer
        this.is_hostmachine_online = false
        this.pos_cashdrawer = false
        this.pending_print_jobs = 0
    }
    async refresh_printer_info() {
        try {
            const printer_info = await this.pos.data.call(
                'pos.config',
                'get_direct_printer_info',
                [this.pos.config.id],
            );
            if (printer_info && printer_info['is_hostmachine_online']) {
                this.is_hostmachine_online = printer_info['is_hostmachine_online']
            }
            if (printer_info && printer_info['pos_cashdrawer']) {
                this.pos_cashdrawer = printer_info['pos_cashdrawer']
            }
            if (printer_info) {
                this.pending_print_jobs = printer_info['pending_print_jobs']
            }
            return true
        } catch (e) {
            console.error("printer info could not refresh correctly", e);
            return false
        }

    }
    /**
     * @override
     */
    async print(component, props) {
        const el = await this.renderer.toHtml(component, props);
        try {
            await loadAllImages(el);
        } catch (e) {
            console.error("Images could not be loaded correctly", e);
        }
        try {
            return await this.printReceipt(el);
        } finally {
            // this.state.isPrinting = false;
        }
    }

    async escposPrintReceipt(receiptParts, method, kitchen_receipt, is_byte_stream) {
        if (receiptParts) {
            this.receiptQueue.push(receiptParts);
        }
        let printResult;
        while (this.receiptQueue.length > 0) {
            receiptParts = this.receiptQueue.shift();
            try {
                printResult = await this.sendPrintingJob(receiptParts, method, kitchen_receipt, is_byte_stream);

            } catch {
                // Error in communicating to the IoT box.
                this.receiptQueue.length = 0;
                return this.getActionError();
            }
            // rpc call is okay but printing failed because
            // IoT box can't find a printer.
            if (!printResult || printResult.result === false) {
                this.receiptQueue.length = 0;
                return this.getResultsError(printResult);
            }
        }
        return { successful: true };
    }

    async sendPrintingJob(receiptParts, method = 'print-image', kitchen_receipt=false, is_byte_stream=false) {
        console.log("receiptParts---------->", receiptParts)
        const printerId = this.direct_printer_id;
        const source_info = {
            model: "pos.order",
            ids: [this.pos.get_order()?.id],
            report_name: kitchen_receipt ? "POS Kitchen Receipt" : "POS Order Receipt",
            job_for: "POS"
        };
        if (this && this.pos_cashdrawer && !kitchen_receipt){
            await this.pos.data.call("print.jobs", "create_print_and_cashdrawer_job", [[], printerId, method, receiptParts, undefined, is_byte_stream, source_info]);
            return true;
        }
        await this.pos.data.call("print.jobs", "create_print_job", [[], printerId, method, receiptParts, undefined, is_byte_stream, source_info]);
        return true;
    }
    
    processCanvas(canvas) {
        return canvas.toDataURL("image/jpeg").replace("data:image/jpeg;base64,", "");
    }

}
