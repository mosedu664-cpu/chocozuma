# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2025-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#    See LICENSE file for full copyright and licensing details.
#################################################################################

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class AttachmentAutomation(models.Model):
    _name = "attachment.automation"
    _description = "Attachment Automation"
    
    
    printer_ids = fields.Many2many('wk.printer', string="Printers", ondelete="cascade", domain="[('state', '=', 'Active')]")
    model_ids = fields.Many2many('ir.model', string="On Models", ondelete="cascade", domain="[('field_id.name', '=', 'message_ids')]" )
    print_type = fields.Selection(
        [
            ('pdf', 'Print PDF'),
            ('zpl', 'Print ZPL'),
            ('img', 'Print IMG'),
        ], string="Print Type", help="Select the attachment type to print", required=True, default='pdf')
    is_active = fields.Boolean(
        string="Active",
        default=False
    )

    def toggle_is_active(self):
        for rec in self:
            rec.is_active = not rec.is_active