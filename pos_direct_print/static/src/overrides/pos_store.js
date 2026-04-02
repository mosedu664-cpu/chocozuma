/*@odoo-module*/
/* Copyright (c) 2016-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>) */
/* See LICENSE file for full copyright and licensing details. */
/* License URL : <https://store.webkul.com/license.html/> */

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { DirectPrinter } from "@pos_direct_print/app/direct_printer";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { renderToString } from "@web/core/utils/render";
import { renderToElement } from "@web/core/utils/render";
import { htmlToCanvas } from "@point_of_sale/app/printer/render_service";

patch(PosStore.prototype, {
    afterProcessServerData() {
        var self = this;
        return super.afterProcessServerData(...arguments).then(function () {
            if (self.config.use_direct_print && self.config.raw && self.config.raw.direct_printer_id) {
                self.direct_printer = new DirectPrinter({ direct_printer_id: self.config.raw.direct_printer_id, pos: self });
                self.refresh_printer_info()
            }
            let unwatched_printer = []
            for (const pt of self.unwatched.printers){
            if(pt.config.printer_type != "direct_printer")
                unwatched_printer.push(pt)
            }
            self.unwatched.printers = unwatched_printer;
            for (const relPrinter of self.models["pos.printer"].getAll()) {
                const printer = relPrinter.serialize();
                printer.direct_printer_id = relPrinter.raw.direct_printer_id;
                if (relPrinter.printer_type == "direct_printer" && relPrinter.raw.direct_printer_id){
                    var HWPrinter = new DirectPrinter({ direct_printer_id:relPrinter.raw.direct_printer_id, pos: self })
                    self.refresh_printer_info()
                    HWPrinter.config = printer;
                    self.unwatched.printers.push(HWPrinter);

                    for (const id of printer.product_categories_ids) {
                        self.printers_category_ids_set.add(id);
                    }
                }
            }
            self.config.iface_printers = !!self.unwatched.printers.length;
        });
    },

    async refresh_printer_info() {
        if (this.config.use_direct_print && this.direct_printer) {
            return await this.direct_printer.refresh_printer_info();
        } else {
            return false
        }
    },

    async printReceipt({
        basic = false,
        order = this.get_order(),
        printBillActionTriggered = false,
    } = {}) {
        if (this.config.use_direct_print && this.direct_printer) {
            if(this.config.order_receipt_format === 'xml'){
                await this.get_esc_receipt(order, 'print-complex');
            }
            else{
                const result = await this.direct_printer.print(
                    OrderReceipt,
                    {
                        data: this.orderExportForPrinting(order),
                        formatCurrency: this.env.utils.formatCurrency,
                        basic_receipt: basic,
                    },
                    { webPrintFallback: true }
                );
                if (!printBillActionTriggered) {
                    order.nb_print += 1;
                    if (typeof order.id === "number" && result) {
                        await this.data.write("pos.order", [order.id], { nb_print: order.nb_print });
                    }
                }
                return true;
            }
        }
        else {
            return super.printReceipt(...arguments)
        }
    },

    async is_invoice_printer_hostmachine_online() {
        if (this.config.raw.invoice_operation == 'print') {
            const { is_hostmachine_online } = await this.data.call(
                'pos.config',
                'get_invoice_printer_info',
                [this.config.id],
            );
            return is_hostmachine_online
        }
        return false
    },

    async canUseInvoicePrinter() {
        if (this.config.raw.invoice_operation == 'print' && this.config.raw.selected_invoice_printer) {
            return await this.is_invoice_printer_hostmachine_online()
        }
        return false

    },

    async printInvoiceByInvoicePrinter(order) {
        var canUseInvoicePrinter = await this.canUseInvoicePrinter()
        if (canUseInvoicePrinter) {
            var res = await this.data.call("pos.config", "print_invoice_documents_printer", [[this.config.id],[order.raw.account_move]]);
            return true
        } else {
            return false
            // await this.invoiceService.downloadPdf(order.raw.account_move);
        }
    },

    generate_wrapped_product_name(product_name, mx_length=24) {
        var MAX_LENGTH = mx_length; // 40 * line ratio of .6
        var wrapped = [];
        var name = product_name;
        var current_line = "";
        while (name.length > 0) {
            var space_index = name.indexOf(" ");
            if (space_index === -1) {
                space_index = name.length;
            }
            if (current_line.length + space_index > MAX_LENGTH) {
                if (current_line.length) {
                    wrapped.push(current_line);
                }
                current_line = "";
            }
            current_line += name.slice(0, space_index + 1);
            name = name.slice(space_index + 1);
        }

        if (current_line.length) {
            wrapped.push(current_line);
        }
        return wrapped;
    },

    truncateAtXIfTooLong(orderline, mx_length){
        const required_string = `${orderline.qty} x ${orderline.unitPrice} / ${orderline.unit}`;
        let result;
        if (required_string.length > mx_length) {
            const splitIndex = required_string.indexOf("x") + 1; // include the "x"
            const part1 = required_string.slice(0, splitIndex).trim();  // includes "x"
            const part2 = required_string.slice(splitIndex).trim();
            result = [part1, part2];
        } else {
            result = [required_string];
        }
        return result;
    },

    async getBase64(template, order){
        let imgReceipt = undefined;
        let canvas = undefined;
        let image = undefined;
        let receiptData = {
                    data: this.orderExportForPrinting(order),
                    formatCurrency: this.env.utils.formatCurrency,
                }
        if(template === 'pos_direct_print.posOrCode' && receiptData.data.pos_qr_code){
            imgReceipt = await renderToElement(template, {
                props: receiptData
            });
        }
        else{
            console.log("Unsupported template:", template)
        }
        /**
         * Add future template to convert into base64
         */
        if(imgReceipt){
            canvas = await htmlToCanvas(imgReceipt,{ addClass: "pos-receipt-print" });
            image = canvas.toDataURL("image/jpeg").replace("data:image/jpeg;base64,", "")
        }
        return image;
    },

    async getEscpos(template, order) {
        let xmlReceipt = '';
        const data = this.orderExportForPrinting(order);

        // Process order lines
        for(let line of data.orderlines){
            line.name_wrapped = this.generate_wrapped_product_name(line.productName, 24);
            line.unitPrice = (line.unitPrice || '').replace(/\u00A0/g, ' ');
            line.price = (line.price || '').replace(/\u00A0/g, ' ');
            line.line_unit_price_wrapped = this.truncateAtXIfTooLong(line, 30);
        }
        // Format payment lines

        for(let line of data.paymentlines){
            line.formatedAmount = this.env.utils.formatCurrency(line.amount, false)?.replace(/\u00A0/g, ' ');
        }

        // Format tax details
        for(let line of data.tax_details){
            line.formatedAmount = (line.amount || 0).toFixed(2);
        }

        // Format totals
        data.formatedChange = this.env.utils.formatCurrency(data.change)?.replace(/\u00A0/g, ' ');
        data.formatedTotalDiscount = this.env.utils.formatCurrency(data.total_discount)?.replace(/\u00A0/g, ' ');
        data.formatedAmountTotal = this.env.utils.formatCurrency(data.amount_total)?.replace(/\u00A0/g, ' ');
        data.formatedTotalTaxs = this.env.utils.roundCurrency(
            (data.total_paid || 0) - (data.total_without_tax || 0)
        );
        
        if (template === 'pos_direct_print.OrderReceipt') {
            xmlReceipt = renderToString(template, {
                props: {
                    data: data,
                    formatCurrency: this.env.utils.formatCurrency,
                }
            });
        }

        else if (template === 'pos_direct_print.OrderReceiptFooter') {
            xmlReceipt = renderToString(template, {
                props: {
                    data: data,
                    formatCurrency: this.env.utils.formatCurrency,
                }
            });
        }
        else {
            console.log("Unsupported template:", template)
        }

        // Clean up and normalize receipt content
        xmlReceipt = xmlReceipt
            .replaceAll('<br>', '<br></br>')    // Ensure self-closing
            .replaceAll('\x00', '[NULL]')      // Replace null bytes
            .replaceAll('\n', '\x0A')         // Normalize newlines for ESC/POS


        // Get final ESC/POS command set from the backend
        let escposReceipt = await this.env.services.orm.call(
            'wk.printer',
            'get_esc_command_set',
            [{ 'data': xmlReceipt }]
        );

        return escposReceipt;
    },

    compressBase64Image(base64, quality = 0.7, maxWidth = 1920, maxHeight = 1080) {
        return new Promise((resolve, reject) => {
            const base64Data = base64.split(',')[1] || base64;
            const mimeType = base64.match(/data:([^;]+);/)?.[1] || 'image/png';
            const byteCharacters = atob(base64Data);
            const byteNumbers = new Array(byteCharacters.length);
            for (let i = 0; i < byteCharacters.length; i++) {
                byteNumbers[i] = byteCharacters.charCodeAt(i);
            }
            const byteArray = new Uint8Array(byteNumbers);
            const blob = new Blob([byteArray], { type: mimeType });
            const url = URL.createObjectURL(blob);
            
            const img = new Image();
            img.crossOrigin = 'anonymous';
            
            img.onload = () => {
                URL.revokeObjectURL(url);
            
                const canvas = document.createElement('canvas');
                let { width, height } = img;
                if (width > maxWidth || height > maxHeight) {
                    const ratio = Math.min(maxWidth / width, maxHeight / height);
                    width = Math.floor(width * ratio);
                    height = Math.floor(height * ratio);
                }

                canvas.width = width;
                canvas.height = height;
                
                const ctx = canvas.getContext('2d');
                
                // For PNG or images with transparency, preserve the transparency
                if (mimeType === 'image/png') {
                    // Don't fill background - keep transparency
                    ctx.clearRect(0, 0, width, height);
                } else {
                    // For JPEG, fill with white background
                    ctx.fillStyle = 'white';
                    ctx.fillRect(0, 0, width, height);
                }
                
                ctx.drawImage(img, 0, 0, width, height);
                
                // Use the original format
                const outputFormat = mimeType;
                
                let compressedBase64 = outputFormat === 'image/jpeg' 
                    ? canvas.toDataURL(outputFormat, quality)
                    : canvas.toDataURL(outputFormat);
                    
                compressedBase64 = compressedBase64.split(',')[1];
                
                resolve(compressedBase64);
            };
            
            img.onerror = (error) => {
                URL.revokeObjectURL(url);
                reject(new Error('Failed to load image: ' + error));
            };
            img.src = url;
        });
    },

    async get_esc_receipt(order, method='print-complex') {

        const logo = this.orderExportForPrinting(order).headerData?.company?.logo || false;
        const qr_code = await this.getBase64("pos_direct_print.posOrCode", order) || false;

        let compressed_qr_code = false;
        let compressed_logo = false;

        if (logo) {
            try {
                const result = await this.compressBase64Image(logo, 1, 190, 190);
                compressed_logo = result;
            } catch (error) {
                console.error("Error compressing logo:", error);
                compressed_logo = false;
            }
        }
        if(qr_code){
            try {
                const result = await this.compressBase64Image(qr_code, 0.7);
                compressed_qr_code = result;
            } catch (error) {
                console.error("Error compressing QR code:", error);
                compressed_qr_code = false;
            }
        }

        const receiptParts = [
            {
                type: "image",
                content: compressed_logo,
            },
            {
                type: "escpos",
                content: await this.getEscpos("pos_direct_print.OrderReceipt", order) || false,
            },
            {
                type: "image",
                content: compressed_qr_code,
            },

            {
                type: "escpos",
                content: await this.getEscpos("pos_direct_print.OrderReceiptFooter", order) || false,
            },


            // Future items can be added here
            // e.g., { type: 'image/escpos', content: 'image/escpos' }
        ];

        await this.direct_printer.escposPrintReceipt(receiptParts, method, false, false);
        return receiptParts;
    },

})
