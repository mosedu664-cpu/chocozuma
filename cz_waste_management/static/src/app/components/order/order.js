/** @odoo-module **/

import { Order } from "@pos_preparation_display/app/components/order/order";
import { WasteLogPopup } from "@cz_waste_management/app/components/waste_log_popup/waste_log_popup";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";

patch(Order.prototype, {
    setup() {
        super.setup(...arguments);
        this.dialog = useService("dialog");
    },

    async logWaste() {
        if (this._loadingWaste) return;
        this._loadingWaste = true;
        
        try {
            const order = this.props.order;
            // Fetch fresh data for the specific order context
            const wasteData = await this.env.services.orm.call(
                "waste.log",
                "get_kds_waste_data",
                [],
                { pos_order_id: order.posOrderId || false }
            );

            // Filter and map orderlines
            const orderlines = [];
            for (const line of order.orderlines) {
                const qty = line.productQuantity || line.product_quantity || 0;
                const cancelled = line.product_cancelled || line.productCancelled || 0;
                const remainingQty = qty - cancelled;
                
                if (remainingQty > 0) {
                    orderlines.push({
                        id: line.id,
                        productId: line.productId || line.product_id,
                        productName: line.productName || line.product_name,
                        productQuantity: remainingQty,
                        productCode: line.productCode || line.product_code || '',
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
        } finally {
            this._loadingWaste = false;
        }
    },
});
