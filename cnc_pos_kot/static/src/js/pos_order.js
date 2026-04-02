import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { floatIsZero, roundPrecision } from "@web/core/utils/numbers";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import {  formatDateTime} from "@web/core/l10n/dates";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { parseUTCString } from "@point_of_sale/utils";
patch(PosOrder.prototype, {
        kot_export_for_printing(baseUrl) {
        return {
            orderlines: this.getSortedOrderlines().map((l) =>
                l.getDisplayData()
            ),
            name: this.pos_reference,
            generalNote: this.general_note || "",
            cashier: this.getCashierName(),
            date: formatDateTime(parseUTCString(this.date_order)),
            base_url: baseUrl,

        };
    }
})

patch(PosStore.prototype, {
        kotExportForPrinting(order) {
        const headerData = this.getReceiptHeaderData(order);
        const baseUrl = this.session._base_url;
        return order.kot_export_for_printing(baseUrl, headerData);
    }
});
