import { _t } from "@web/core/l10n/translation";
import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { TextInputPopup } from "@point_of_sale/app/utils/input_popups/text_input_popup";
import { CashMoveReceipt } from "@point_of_sale/app/navbar/cash_move_popup/cash_move_receipt/cash_move_receipt";
import { formatDateTime } from "@web/core/l10n/dates";
import { askManagerPinWithCode } from "@cz_cash_control/app/manager_pin/manager_pin";
import { czPrint } from "@cz_cash_control/app/printing/cz_print";

const { DateTime } = luxon;

/** Full-size receipt photo of one movement. */
export class CzReceiptPhotoDialog extends Component {
    static template = "cz_cash_control.CzReceiptPhotoDialog";
    static components = { Dialog };
    static props = { title: String, src: String, close: Function };
}

/**
 * "Hareketler": every drawer movement of the open session, inside the POS.
 *
 * Read-only by design — nothing can be deleted. A wrong movement is cancelled
 * with an opposite "correction" movement (manager PIN + reason), so both the
 * mistake and its correction stay on record and net to zero for the day.
 */
export class CzCashMovesDialog extends Component {
    static template = "cz_cash_control.CzCashMovesDialog";
    static components = { Dialog };
    static props = { close: Function, onChange: { type: Function, optional: true } };

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.printer = useService("printer");
        this.state = useState({
            loading: true,
            error: "",
            data: null,
            filter: "all", // all | out | in | pin | photo
            search: "",
            busyId: false,
            flashId: false,
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = "";
        try {
            this.state.data = await this.pos.data.call(
                "pos.session",
                "cz_session_moves",
                [[this.pos.session.id]],
                {},
                true
            );
        } catch (e) {
            console.error(e);
            this.state.error = _t("Hareketler yüklenemedi. İnternet bağlantısını kontrol edin.");
        } finally {
            this.state.loading = false;
        }
    }

    // ------------------------------------------------------------------ display helpers
    fmt(value) {
        return this.env.utils.formatCurrency(value);
    }

    get lines() {
        return this.state.data?.lines || [];
    }

    get filteredLines() {
        const q = this.state.search.trim().toLocaleLowerCase("tr");
        return this.lines.filter((l) => {
            switch (this.state.filter) {
                case "out":
                    if (l.type !== "out") return false;
                    break;
                case "in":
                    if (l.type !== "in") return false;
                    break;
                case "pin":
                    if (!l.manager) return false;
                    break;
                case "photo":
                    if (!l.has_photo) return false;
                    break;
            }
            if (!q) {
                return true;
            }
            return [l.category, l.reason, l.employee, l.cashier, l.manager, l.receipt_ref, l.code]
                .join(" ")
                .toLocaleLowerCase("tr")
                .includes(q);
        });
    }

    get filters() {
        const lines = this.lines;
        return [
            { key: "all", label: _t("Tümü"), icon: "fa-list", count: lines.length },
            { key: "out", label: _t("Çıkış"), icon: "fa-arrow-up", count: lines.filter((l) => l.type === "out").length },
            { key: "in", label: _t("Giriş"), icon: "fa-arrow-down", count: lines.filter((l) => l.type === "in").length },
            { key: "pin", label: _t("Yönetici onaylı"), icon: "fa-lock", count: lines.filter((l) => l.manager).length },
            { key: "photo", label: _t("Fişli"), icon: "fa-camera", count: lines.filter((l) => l.has_photo).length },
        ];
    }

    /** Biggest spending categories of the session (safe transfers left out, corrections netted). */
    get topCategories() {
        const per = {};
        for (const l of this.lines) {
            if (l.end_of_day || l.kind === "safe_transfer") {
                continue;
            }
            const signed = l.type === "out" ? l.amount : -l.amount;
            const isExpenseSide = l.type === "out" || l.is_correction;
            if (!isExpenseSide) {
                continue;
            }
            const key = l.category;
            per[key] = per[key] || { name: key, icon: l.icon, color: l.color, amount: 0, count: 0 };
            per[key].amount += signed;
            per[key].count += l.is_correction ? -1 : 1;
        }
        return Object.values(per)
            .filter((c) => c.amount > 0.004)
            .sort((a, b) => b.amount - a.amount)
            .slice(0, 4);
    }

    get maxTop() {
        return Math.max(1, ...this.topCategories.map((c) => c.amount));
    }

    iconClass(line) {
        const icon = (line.icon || "fa-tag").trim();
        return `fa fa-fw ${icon.startsWith("fa-") ? icon : "fa-" + icon}`;
    }

    rowClass(line) {
        const classes = ["cz-move-row"];
        if (line.corrected) classes.push("cz-move-corrected");
        if (line.is_correction) classes.push("cz-move-correction");
        if (this.state.flashId === line.id) classes.push("cz-move-flash");
        return classes.join(" ");
    }

    originalOf(line) {
        return this.lines.find((l) => l.id === line.corrects_id);
    }

    // ------------------------------------------------------------------ actions
    setFilter(key) {
        this.state.filter = key;
    }

    async openPhoto(line) {
        try {
            const data = await this.pos.data.call(
                "pos.session",
                "cz_move_photo",
                [[this.pos.session.id], line.id],
                {},
                true
            );
            if (!data) {
                this.notification.add(_t("Bu harekette fotoğraf yok."), { type: "warning" });
                return;
            }
            this.dialog.add(CzReceiptPhotoDialog, {
                title: `${line.time} · ${line.category} · ${this.fmt(line.amount)}`,
                src: `data:image/jpeg;base64,${data}`,
            });
        } catch (e) {
            console.error(e);
            this.notification.add(_t("Fotoğraf açılamadı."), { type: "danger" });
        }
    }

    async correct(line) {
        if (!line.reversible || this.state.busyId) {
            return;
        }
        const direction = line.type === "out" ? _t("çekmeceye geri girer") : _t("çekmeceden çıkar");
        const reason = await makeAwaitable(this.dialog, TextInputPopup, {
            title: _t("İptal sebebi — %(cat)s %(amount)s", { cat: line.category, amount: this.fmt(line.amount) }),
            placeholder: _t("Örn: yanlış tutar girildi, iki kez girildi…"),
            rows: 3,
        });
        if (!reason || reason.trim().length < 3) {
            if (reason !== undefined && reason !== null) {
                this.notification.add(_t("Lütfen iptal sebebini yazın."), { type: "warning" });
            }
            return;
        }
        const auth = await askManagerPinWithCode(
            this.pos,
            this.dialog,
            this.notification,
            _t("Yönetici PIN — hareketi iptal et")
        );
        if (!auth) {
            return;
        }
        this.state.busyId = line.id;
        try {
            const cashier = this.pos.get_cashier?.();
            const res = await this.pos.data.call("pos.session", "cz_reverse_move", [
                [this.pos.session.id],
                line.id,
                auth.manager.id,
                auth.pin,
                reason.trim(),
                cashier ? cashier.name : this.pos.user?.name || "",
            ]);
            this.notification.add(
                _t("Hareket iptal edildi: %(amount)s %(dir)s.", { amount: this.fmt(line.amount), dir: direction }),
                { type: "success" }
            );
            this._printCorrection(line, reason.trim(), auth.manager.name);
            await this.load();
            this.state.flashId = res?.id || false;
            this.props.onChange?.();
        } catch (e) {
            console.error(e);
            const msg = e?.data?.message || e?.message || _t("İşlem yapılamadı.");
            this.notification.add(msg, { type: "danger" });
        } finally {
            this.state.busyId = false;
        }
    }

    _printCorrection(line, reason, managerName) {
        // the cancel slip goes with the original receipt in the drawer; never blocks
        czPrint(this.pos, this.printer, CashMoveReceipt, {
            reason: _t("İPTAL: %(cat)s — %(reason)s — Onay: %(manager)s", {
                cat: line.category,
                reason,
                manager: managerName,
            }),
            translatedType: line.type === "out" ? _t("in") : _t("out"),
            formattedAmount: this.fmt(line.amount),
            headerData: this.pos.getReceiptHeaderData(),
            date: formatDateTime(DateTime.now()),
        });
    }
}
