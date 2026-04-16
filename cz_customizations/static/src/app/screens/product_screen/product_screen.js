/** @odoo-module */

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";

patch(ProductScreen.prototype, {
    getProductName(product) {
        if (product.short_name) {
            return product.short_name;
        }
        return super.getProductName(...arguments);
    },
});
