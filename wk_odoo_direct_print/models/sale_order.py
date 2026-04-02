# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2025-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#    See LICENSE file for full copyright and licensing details.
#################################################################################

from odoo import api, fields, models, _
import logging
from odoo.exceptions import ValidationError, UserError

_logger=logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_confirm(self):
        res = super().action_confirm()
        self.env['autoprint.rule']._autoprint_on_action(records=self,action_name="Confirm",model="sale.order")
        return res

    def _action_cancel(self):
        res = super(SaleOrder, self)._action_cancel()
        self.env['autoprint.rule']._autoprint_on_action(records=self,action_name="Cancel",model="sale.order")
        return res
