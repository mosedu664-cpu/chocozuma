# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import api, fields, models, _


class PosOrder(models.Model):
    _inherit = 'pos.order'

    cancel_reason = fields.Char(string='Cancellation Reason', readonly=True, copy=False)
    cancel_reason_code = fields.Selection([
        ('KEY_ERR', 'Hatalı tuşlama (yanlış ürün/adet)'),
        ('DUP', 'Mükerrer sipariş (iki kere girildi)'),
        ('CUST_NP', 'Müşteri iptali – ürün hazırlanmadı'),
        ('CUST_P', 'Müşteri iptali – ürün hazırlandı'),
        ('STOCK', 'Stokta yok / ürün bitti'),
        ('PLATFORM', 'Platform iptali (Getir/Yemeksepeti/Trendyol)'),
        ('COURIER', 'Kurye sorunu (gecikme/rahatsızlık)'),
        ('KITCHEN', 'Mutfak hatası – yeniden hazırlandı'),
        ('SWAP', 'Ürün değişikliği (başka ürünle değişti)'),
        ('OTHER', 'Diğer'),
    ], string='Cancel Reason Code', readonly=True, copy=False, index=True)
    discount_log_posted = fields.Boolean(
        default=False, copy=False,
        help='Technical: discount summary already posted to chatter.')

    def _process_saved_order(self, draft):
        """Post one chatter note summarizing all discounts (with reasons)
        when the order is finalized. Posted once per order."""
        res = super()._process_saved_order(draft)
        if not draft and not self.discount_log_posted:
            discount_lines = self.lines.filtered(lambda l: l.discount_reason_code)
            if discount_lines:
                rows = []
                for line in discount_lines:
                    if line.discount:
                        amount = "%g%%" % line.discount
                    else:
                        amount = "%.2f" % line.price_subtotal_incl
                    rows.append("%s: %s — [%s] %s" % (
                        line.full_product_name or line.product_id.display_name,
                        amount,
                        line.discount_reason_code,
                        line.discount_reason or '',
                    ))
                self.message_post(
                    body=Markup("<b>Discounts</b><br/>%s") % Markup("<br/>").join(rows),
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                )
                self.discount_log_posted = True
        return res
    opened_by_employee_id = fields.Many2one('hr.employee', string='Waiter / Order Taker', readonly=True, copy=False,
                                            help='The employee who opened/created this order in the POS.', )

    @api.model
    def _load_pos_data_fields(self, config_id):
        # pos.order base returns [] which means "all fields" in search_read.
        # We must NOT restrict the list — just ensure our field is included.
        result = super()._load_pos_data_fields(config_id)
        if result:  # only append when the parent already returns a specific list
            result.append('opened_by_employee_id')
        return result

    def action_pos_order_cancel(self):
        """Override to post a cancellation log note (reason already written via ormWrite)."""
        cancellable_orders = self.filtered(lambda o: o.state == 'draft')

        for order in cancellable_orders:
            user_name = self.env.user.name
            waiter_name = order.opened_by_employee_id.name or _('Unknown')
            reason_text = order.cancel_reason or _('No reason provided')
            order.message_post(
                body=Markup(
                    "<b>Order Cancelled</b><br/>"
                    "<b>Reason:</b> {reason}<br/>"
                    "<b>Waiter:</b> {waiter}"
                ).format(reason=reason_text, user=user_name, waiter=waiter_name),
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )

        cancellable_orders.write({'state': 'cancel'})

        return {
            'pos.order': cancellable_orders.read(
                self._load_pos_data_fields(self.config_id.ids[0]), load=False
            )
        }

    def log_line_cancellation(self, line_data):
        """Log a note in the chatter when an order line is removed after being sent to the kitchen."""
        for order in self:
            order.message_post(
                body=Markup(
                    "<b>Order Line Removed (Post-Kitchen)</b><br/>"
                    "<b>Product:</b> {product}<br/>"
                    "<b>Reason:</b> {reason}<br/>"
                    "<b>Removed by:</b> {user}"
                ).format(
                    product=line_data.get('product_name', _('Unknown')),
                    reason=line_data.get('reason', _('No reason provided')),
                    user=line_data.get('user_name', self.env.user.name)
                ),
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    discount_reason_code = fields.Selection([
        ('SADAKAT', "Sadakat / Zuma's Family"),
        ('SIKAYET', 'Müşteri şikayeti / telafi'),
        ('IKRAM', 'Yönetim ikramı / misafir'),
        ('PERSONEL', 'Personel indirimi'),
        ('KAMPANYA', 'Kampanya / promosyon'),
        ('PLATFORM', 'Platform fiyat farkı'),
        ('DAIMI', 'Daimi müşteri'),
        ('FIYAT', 'Fiyat düzeltme / menü hatası'),
        ('OTHER', 'Diğer'),
    ], string='Discount Reason Code', readonly=True, copy=False, index=True)
    discount_reason = fields.Char(string='Discount Reason', readonly=True, copy=False)

    @api.model
    def _load_pos_data_fields(self, config_id):
        result = super()._load_pos_data_fields(config_id)
        result += ['discount_reason_code', 'discount_reason']
        return result
