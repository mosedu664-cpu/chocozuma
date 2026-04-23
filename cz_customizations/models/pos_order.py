# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import api, fields, models, _


class PosOrder(models.Model):
    _inherit = 'pos.order'

    cancel_reason = fields.Char(string='Cancellation Reason', readonly=True, copy=False)
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
            reason_text = order.cancel_reason or _('No reason provided')
            order.message_post(
                body=Markup(
                    "<b>Order Cancelled</b><br/>"
                    "<b>Reason:</b> {reason}<br/>"
                    "<b>Cancelled by:</b> {user}"
                ).format(reason=reason_text, user=user_name),
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )

        cancellable_orders.write({'state': 'cancel'})

        return {
            'pos.order': cancellable_orders.read(
                self._load_pos_data_fields(self.config_id.ids[0]), load=False
            )
        }
