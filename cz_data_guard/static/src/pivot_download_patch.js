/** @odoo-module **/

import { PivotRenderer } from "@web/views/pivot/pivot_renderer";
import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";

// The pivot buttons template (web.PivotView.Buttons) is t-called from the
// PivotRenderer, so the flag must live on the renderer instance.
patch(PivotRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        this.czCanExport = Boolean(session.cz_can_transfer_data);
    },
});
