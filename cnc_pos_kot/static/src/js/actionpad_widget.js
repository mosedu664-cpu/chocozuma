import { patch } from "@web/core/utils/patch";
import { ActionpadWidget } from "@point_of_sale/app/screens/product_screen/action_pad/action_pad";
import { useService } from "@web/core/utils/hooks";
import {KotReceipt} from "@cnc_pos_kot/js/kot_receipt";


patch(ActionpadWidget.prototype, {
    setup() {
        super.setup();
        this.printer = useService("printer");
             this.dialog = useService('dialog');
    },

    async submitOrder() {
        await super.submitOrder();
        if (this.pos.config.print_kot){
              const result = await this.printer.print(
                    KotReceipt,
                    {
                        data: this.pos.kotExportForPrinting(this.pos.get_order()),
                        formatCurrency: this.env.utils.formatCurrency,
                        basic_receipt: false,
                    },
                    {webPrintFallback: true}
                );
        }

    },

    }
 );
