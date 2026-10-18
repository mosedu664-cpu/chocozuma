/** @odoo-module **/

import { registry } from "@web/core/registry";
import { session } from "@web/session";

// Hide "Import records" for users without the data-transfer right.
// (Server-side execute_import is locked too; this only cleans the UI.)
const cogMenuRegistry = registry.category("cogMenu");
if (cogMenuRegistry.contains("import-menu")) {
    const item = cogMenuRegistry.get("import-menu");
    const original = item.isDisplayed;
    cogMenuRegistry.add(
        "import-menu",
        {
            ...item,
            isDisplayed: (env) => Boolean(session.cz_can_transfer_data) && original(env),
        },
        { force: true, sequence: 1 }
    );
}
