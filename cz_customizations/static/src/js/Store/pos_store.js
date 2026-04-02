import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";

patch(PosStore.prototype, {
    async pay() {
        let order = this.env.services.pos.get_order();
        var error = false;
        if(!error){
            super.pay();
        }
    }
});