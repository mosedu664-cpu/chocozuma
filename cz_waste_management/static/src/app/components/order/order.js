/** @odoo-module **/

import { Order } from "@pos_preparation_display/app/components/order/order";
import { WasteLogPopup } from "@cz_waste_management/app/components/waste_log_popup/waste_log_popup";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";

patch(Order.prototype, {
    setup() {
        super.setup(...arguments);
        this.dialog = useService("dialog");
        this._wasteData = null;
    },

    async _loadWasteData(posOrderId) {
        if (!this._wasteData) {
            this._wasteData = await this.env.services.orm.call(
                "waste.log",
                "get_kds_waste_data",
                [],
                { pos_order_id: posOrderId || false }
            );
        }
        return this._wasteData;
    },

    async logWaste() {
        const order = this.props.order;
        const wasteData = await this._loadWasteData(order.posOrderId);

        // Filter and map orderlines: only show items with remaining quantity
        const orderlines = [];
        for (const line of order.orderlines) {
            const remainingQty = line.productQuantity - (line.product_cancelled || 0);
            if (remainingQty > 0) {
                orderlines.push({
                    id: line.id,
                    productId: line.productId,
                    productName: line.productName,
                    productQuantity: remainingQty, // Pass remaining as max quantity
                    productCode: line.productCode || '',
                });
            }
        }

        this.dialog.add(WasteLogPopup, {
            orderlines: orderlines,
            products: wasteData.products || [],
            reasons: wasteData.reasons || [],
            defaultLocation: wasteData.default_location || false,
            defaultDestLocation: wasteData.default_dest_location || false,
            preparationDisplayId: this.preparationDisplay.id,
            posOrderId: order.posOrderId || false,
            orderRef: order.trackingNumber ? `#${order.trackingNumber}` : order.name,
        });
    },
});
