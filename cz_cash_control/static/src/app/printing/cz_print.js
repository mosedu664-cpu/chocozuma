/**
 * Print a receipt component on whatever the POS actually uses:
 *  - Webkul "POS Print Direct" (pos_direct_print) when enabled on the config,
 *  - otherwise the standard printer service (IoT / ePOS printer, no browser dialog).
 * Never throws: printing problems must not block a cash movement or the closing.
 * Returns true when a job was sent.
 */
export async function czPrint(pos, printerService, component, props) {
    try {
        const direct = pos.direct_printer;
        if (pos.config.use_direct_print && direct && typeof direct.print === "function") {
            const res = await direct.print(component, props);
            return res !== false;
        }
        if (printerService?.is?.()) {
            await printerService.print(component, props);
            return true;
        }
        return false;
    } catch (e) {
        console.error("cz_cash_control: receipt could not be printed", e);
        return false;
    }
}
