/* global Sha1 */
import { _t } from "@web/core/l10n/translation";
import { NumberPopup } from "@point_of_sale/app/utils/input_popups/number_popup";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";

/**
 * Ask for a manager PIN (pos_hr employee with role "manager").
 * Returns the manager employee record on success, false otherwise.
 *
 * The current cashier can never authorise himself unless he is a manager.
 */
export async function askManagerPin(pos, dialog, notification, title) {
    const managers = (pos.models["hr.employee"]?.getAll() || []).filter(
        (e) => e._role === "manager" && e._pin
    );
    if (!managers.length) {
        notification.add(_t("Bu kasada PIN tanımlı yönetici yok. Lütfen muhasebeye bildirin."), {
            type: "danger",
        });
        return false;
    }
    const pin = await makeAwaitable(dialog, NumberPopup, {
        title: title || _t("Yönetici PIN"),
        subtitle: _t("Bu işlem için yönetici onayı gerekli"),
        formatDisplayedValue: (x) => x.replace(/./g, "•"),
    });
    if (!pin) {
        return false;
    }
    const hash = Sha1.hash(pin);
    const manager = managers.find((e) => e._pin === hash);
    if (!manager) {
        notification.add(_t("Yanlış PIN"), { type: "warning", title: _t("Yönetici onayı başarısız") });
        return false;
    }
    return manager;
}
