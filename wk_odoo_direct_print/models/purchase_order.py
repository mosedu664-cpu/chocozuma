# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2025-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#    See LICENSE file for full copyright and licensing details.
#################################################################################

from odoo import models

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def button_confirm(self):
        res = super().button_confirm()
        self.env['autoprint.rule']._autoprint_on_action(records=self,action_name="Confirm",model="purchase.order")
        return res

    def button_cancel(self):
        res = super().button_cancel()
        self.env['autoprint.rule']._autoprint_on_action(records=self,action_name="Cancel",model="purchase.order")
        return res
    
    def button_done(self):
        res = super().button_done()
        self.env['autoprint.rule']._autoprint_on_action(records=self,action_name="Lock",model="purchase.order")
        return res

    def action_create_invoice(self):
        res = super().action_create_invoice()
        self.env['autoprint.rule']._autoprint_on_action(records=self,action_name="Create Bill",model="purchase.order")
        return res
    
