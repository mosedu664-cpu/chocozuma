/** @odoo-module */
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component } from "@odoo/owl";

class ButtonDirectPrint extends Component {
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
    }

    async onClick() {
        var self = this
        console.log('On click Add Printer................', {self})
        if(self.props.method=='add_printers'){
            console.log('Add Printer................')
        }
    }
}
ButtonDirectPrint.template = "wk_odoo_direct_print.ButtonDirectPrint";

export const buttonDiretPrint = {
    component: ButtonDirectPrint,
    extractProps: ({ attrs }) => {
        return {
            method: attrs.button_name,
            title: attrs.title,
        };
    },
};

registry.category("view_widgets").add("printer_button", buttonDiretPrint);


