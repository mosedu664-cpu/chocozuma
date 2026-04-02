# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2025-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#    See LICENSE file for full copyright and licensing details.
#################################################################################
from odoo import models

class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_reverse(self):
        res = super().action_reverse()
        self.env['autoprint.rule']._autoprint_on_action(records=self,action_name="Credit Note",model="account.move")
        return res

    def button_draft(self):
        res = super().button_draft()
        self.env['autoprint.rule']._autoprint_on_action(records=self,action_name="Reset to Draft",model="account.move")
        return res
    
    def action_register_payment(self):
        res = super().action_register_payment()
        self.env['autoprint.rule']._autoprint_on_action(records=self,action_name="Pay",model="account.move")
        return res
    
    def button_cancel(self):
        res = super().button_cancel()
        self.env['autoprint.rule']._autoprint_on_action(records=self,action_name="Cancel",model="account.move")
        return res
    
    def action_post(self):
        res = super().action_post()
        self.env['autoprint.rule']._autoprint_on_action(records=self,action_name="Confirm",model="account.move")
        return res
    