# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2025-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#    See LICENSE file for full copyright and licensing details.
#################################################################################

from odoo import models, fields

class ShippingLabelAutomation(models.Model):
    _name = "shipping.label.automation"
    _description = "Shipping Label Automation"

    name = fields.Char(
        string="Name",
        required=True
    )

    carrier_ids = fields.Many2many(
        'delivery.carrier',
        string="Delivery Carrier",
        required=True,
        help="Select the delivery carrier for which labels or documents will be printed automatically."
    )

    picking_type_ids = fields.Many2many(
        'stock.picking.type',
        string="Operations",
        help="Select operations where this automation should apply."
    )

    printer_ids = fields.Many2many(
        'wk.printer',
        string="Printers",
        domain="[('state', '=', 'Active')]",
        help="Printers used for automatic printing."
    )

    print_label = fields.Boolean(
        string="Print Shipping Label",
        default=False
    )

    print_documents = fields.Boolean(
        string="Print Shipping Documents",
        default=False
    )

    is_active = fields.Boolean(
        string="Active",
        default=True
    )
    
    def toggle_is_active(self):
        for rec in self:
            rec.is_active = not rec.is_active
