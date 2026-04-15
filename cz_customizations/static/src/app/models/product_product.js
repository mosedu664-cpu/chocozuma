/** @odoo-module */

import { ProductProduct } from "@point_of_sale/app/models/product_product";
import { patch } from "@web/core/utils/patch";

patch(ProductProduct.prototype, {
    get searchString() {
        const fields = ["display_name", "barcode", "default_code", "short_name"];
        return fields
            .map((field) => this[field] || "")
            .filter(Boolean)
            .join(" ");
    },
    get productDisplayName() {
        if (this.short_name) {
            return this.default_code ? `[${this.default_code}] ${this.short_name}` : this.short_name;
        }
        return super.productDisplayName;
    },
});
