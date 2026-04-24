/** @odoo-module **/

import { Component, useState, useRef } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

export class WasteLogPopup extends Component {
    static template = "cz_waste_management.WasteLogPopup";
    static components = { Dialog };
    static props = {
        close: Function,
        orderlines: { type: Array, optional: true },
        preparationDisplayId: { type: Number, optional: true },
        posOrderId: { type: Number, optional: true },
        orderRef: { type: String, optional: true },
        products: { type: Array, optional: true },
        reasons: { type: Array, optional: true },
        defaultLocation: { type: Object, optional: true },
        defaultDestLocation: { type: Object, optional: true },
    };
    static defaultProps = {
        orderlines: [],
        products: [],
        reasons: [],
    };

    setup() {
        this.photoInput = useRef("photo-input");
        
        // Initialize with orderlines UNSELECTED by default
        const initialItems = this.props.orderlines.map(line => ({
            preparation_display_orderline_id: line.id,
            productId: line.productId,
            name: line.productName,
            code: line.productCode || '',
            orderedQty: line.productQuantity,
            quantity: line.productQuantity,
            selected: false,
            fromOrder: true,
        }));

        this.state = useState({
            items: initialItems,
            productId: "",
            productSearch: "",
            quantity: 1,
            reasonId: "",
            otherReason: "",
            station: "",
            notes: "",
            photo: null,
            photoFilename: "",
            photoPreview: null,
            submitting: false,
            error: "",
            success: "",
            showProductDropdown: false,
            locationId: this.props.defaultLocation ? this.props.defaultLocation.id : "",
            locationDestId: this.props.defaultDestLocation ? this.props.defaultDestLocation.id : "",
        });
    }

    get filteredProducts() {
        const search = this.state.productSearch.toLowerCase();
        let items = [];

        // Build list of products not already in the order
        const orderProductIds = new Set(this.props.orderlines.map(l => l.productId));
        
        for (const product of this.props.products) {
            if (!orderProductIds.has(product.id)) {
                items.push({
                    id: product.id,
                    name: product.display_name,
                });
            }
        }

        if (search) {
            items = items.filter((p) => p.name.toLowerCase().includes(search));
        }

        return items.slice(0, 50);
    }

    selectProduct(product) {
        // Add product to items list if not already there
        const existing = this.state.items.find(i => i.productId === product.id);
        if (existing) {
            existing.selected = true;
        } else {
            this.state.items.push({
                productId: product.id,
                name: product.name,
                code: '',
                orderedQty: 0,
                quantity: 1,
                selected: true,
                fromOrder: false,
            });
        }
        this.state.productSearch = "";
        this.state.showProductDropdown = false;
    }

    onItemQtyInput(item, ev) {
        let val = parseFloat(ev.target.value) || 0;
        if (item.fromOrder && val > item.orderedQty) {
            val = item.orderedQty;
        }
        item.quantity = val;
    }

    get selectedReason() {
        return this.props.reasons.find(r => r.id == this.state.reasonId);
    }

    async submit() {
        const selectedItems = this.state.items.filter(i => i.selected && i.quantity > 0);
        
        // Validation
        if (selectedItems.length === 0) {
            this.state.error = _t("Please select at least one item and enter a quantity.");
            return;
        }
        if (!this.state.reasonId) {
            this.state.error = _t("Please select a waste reason.");
            return;
        }
        if (this.selectedReason && this.selectedReason.name === 'Other' && !this.state.otherReason) {
            this.state.error = _t("Please specify the reason for 'Other'.");
            return;
        }

        this.state.error = "";
        this.state.submitting = true;

        try {
            const result = await this.env.services.orm.call(
                "waste.log",
                "create_from_kds",
                [],
                {
                    items: selectedItems.map(i => ({
                        product_id: i.productId,
                        quantity: i.quantity,
                        total_qty_ordered: i.orderedQty,
                        preparation_display_orderline_id: i.preparation_display_orderline_id,
                    })),
                    reason_id: parseInt(this.state.reasonId),
                    other_reason: this.state.otherReason || "",
                    station: this.state.station || "",
                    notes: this.state.notes || "",
                    photo: this.state.photo || false,
                    photo_filename: this.state.photoFilename || "",
                    pos_order_id: this.props.posOrderId || false,
                    preparation_display_id: this.props.preparationDisplayId || false,
                    order_ref: this.props.orderRef || "",
                    location_id: this.state.locationId || false,
                    location_dest_id: this.state.locationDestId || false,
                }
            );

            if (result.success) {
                this.state.success = _t("Waste logged successfully.");
                setTimeout(() => {
                    this.props.close();
                }, 1200);
            } else {
                this.state.error = result.error || _t("Failed to log waste.");
            }
        } catch (error) {
            console.error("Waste log error:", error);
            this.state.error = error.message || _t("An error occurred while logging waste.");
        } finally {
            this.state.submitting = false;
        }
    }

    onProductSearchInput(ev) {
        this.state.productSearch = ev.target.value;
        this.state.showProductDropdown = true;
    }

    onProductSearchFocus() {
        this.state.showProductDropdown = true;
    }

    onProductSearchBlur() {
        // Small delay to allow click on dropdown items
        setTimeout(() => {
            this.state.showProductDropdown = false;
        }, 200);
    }

    onPhotoChange(ev) {
        const file = ev.target.files[0];
        if (file) {
            this.state.photoFilename = file.name;
            const reader = new FileReader();
            reader.onload = (e) => {
                const base64Data = e.target.result.split(",")[1];
                this.state.photo = base64Data;
                this.state.photoPreview = e.target.result;
            };
            reader.readAsDataURL(file);
        }
    }

    removePhoto() {
        this.state.photo = null;
        this.state.photoFilename = "";
        this.state.photoPreview = null;
        if (this.photoInput.el) {
            this.photoInput.el.value = "";
        }
    }

    cancel() {
        this.props.close();
    }
}
