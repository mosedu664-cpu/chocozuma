/** @odoo-module **/

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { NumberPopup } from "@point_of_sale/app/utils/input_popups/number_popup";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";

/**
 * Kakao Hazinesi: giving a gift (Şefin İkramı / Hazine Tabağı) at the till.
 *
 * The guest shows the 12-digit code from WhatsApp. The cashier scans it (the
 * code starts with 99) or types it with the "İkram Kodu" button. The server
 * checks and books the code in one step, then the gift is added at 0 ₺.
 * Removing the line before payment frees the code again.
 */
const GIFT_CODE = /^99\d{10}$/;

patch(PosStore.prototype, {
    async czAskGiftCode() {
        const value = await makeAwaitable(this.dialog, NumberPopup, {
            title: "İkram kodu (12 rakam)",
            startingValue: "",
        });
        if (value) {
            await this.czRedeemGift(value);
        }
    },

    czGiftAlert(body) {
        this.dialog.add(AlertDialog, { title: "İkram verilemedi", body });
    },

    async czRedeemGift(input) {
        const token = String(input || "").replace(/\D/g, "");
        const order = this.get_order();
        if (!order) {
            return false;
        }
        if (!GIFT_CODE.test(token)) {
            this.czGiftAlert("İkram kodu 99 ile başlar ve 12 rakamdır. Misafirin WhatsApp mesajındaki kodu girin.");
            return false;
        }
        let result;
        try {
            result = await this.data.call("cz.loyalty.reward", "pos_redeem", [
                token,
                this.config.id,
                order.uuid,
                order.pos_reference || "",
            ]);
        } catch (e) {
            console.error("cz_loyalty: redeem failed", e);
            this.czGiftAlert("Sunucuya ulaşılamadı. İnterneti kontrol edip tekrar deneyin; kod kullanılmadı.");
            return false;
        }
        if (!result || !result.ok) {
            this.czGiftAlert((result && result.message) || "Kod kabul edilmedi.");
            return false;
        }
        const product = this.models["product.product"].get(result.product_id);
        let line = false;
        if (product) {
            try {
                line = await this.addLineToOrder(
                    { product_id: product, price_unit: 0, qty: 1, cz_reward_token: token },
                    order,
                    { merge: false },
                    false
                );
            } catch (e) {
                console.error("cz_loyalty: could not add the gift line", e);
            }
        }
        if (!line) {
            // Nothing was added: free the code again so the guest does not lose the gift.
            try {
                await this.data.call("cz.loyalty.reward", "pos_release", [token, order.uuid]);
            } catch (e) {
                console.error("cz_loyalty: release failed", e);
            }
            this.czGiftAlert(`${result.gift_name} bu kasanın ürünlerinde yok. Yöneticiye haber verin; kod kullanılmadı.`);
            return false;
        }
        this.notification.add(`${result.gift_name} siparişe eklendi (0 ₺).`, { type: "success" });
        return true;
    },
});

patch(PosOrder.prototype, {
    removeOrderline(line) {
        const tokens = (line?.getAllLinesInCombo?.() || [line])
            .map((l) => l && l.cz_reward_token)
            .filter(Boolean);
        const uuid = this.uuid;
        const result = super.removeOrderline(...arguments);
        if (tokens.length) {
            // A split bill or a table transfer removes the line here and re-creates it on another
            // bill: wait for that to settle, then free only the codes that are on no open bill.
            const models = this.models;
            setTimeout(() => {
                for (const token of tokens) {
                    let stillThere = true;
                    try {
                        stillThere = models["pos.order.line"]
                            .getAll()
                            .some((l) => l.cz_reward_token === token);
                    } catch (e) {
                        console.error("cz_loyalty: could not check the gift line", e);
                    }
                    if (!stillThere) {
                        rpc("/web/dataset/call_kw/cz.loyalty.reward/pos_release", {
                            model: "cz.loyalty.reward",
                            method: "pos_release",
                            args: [token, uuid],
                            kwargs: {},
                        }).catch((e) => console.error("cz_loyalty: release failed", e));
                    }
                }
            }, 1500);
        }
        return result;
    },
});

patch(ProductScreen.prototype, {
    setup() {
        // Wrap the whole barcode chain on the instance, before the screen registers it with the
        // scanner: other modules (barcode lookup) look the code up as a product first, whatever
        // the load order. A gift code must never reach them.
        const productAction = this._barcodeProductAction;
        this._barcodeProductAction = async (code) => {
            const raw = String(code?.base_code || code?.code || "").replace(/\s/g, "");
            if (this.pos?.config?.cz_loyalty_redeem && GIFT_CODE.test(raw)) {
                await this.pos.czRedeemGift(raw);
                return;
            }
            return productAction.call(this, code);
        };
        super.setup(...arguments);
    },
});

patch(ControlButtons.prototype, {
    async czClickGiftCode() {
        if (this.props.close) {
            this.props.close();
        }
        await this.pos.czAskGiftCode();
    },
});
