# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2025-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#    See LICENSE file for full copyright and licensing details.
#################################################################################

from odoo import api, fields, models, _
import logging
from odoo.exceptions import ValidationError, UserError
from ..wklib import printer_info
import base64

PRINTER_TYPE = [
    ('ZPL', 'ZPL'),
    ('ESCPOS', 'ESCPOS'),
    ('PDF', 'PDF'),
]

class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    printerType = fields.Selection(string="For Printer Type", selection=PRINTER_TYPE, compute='_compute_printer_type', store=True, readonly=False, help=printer_info.PRINTER_TYPE_HELP)
    report_type_alert = fields.Html(string="", store=False, readonly=True, default='')

    def _compute_printer_type(self):
        for rec in self:
            if rec.report_type=="qweb-pdf":
                rec.printerType = "PDF"
            elif rec.report_type=="qweb-text":
                if 'ZPL' in rec.name:
                    rec.printerType = "ZPL"

    @api.onchange('report_type', 'printerType')
    def _onchange_set_printerType(self):
        for rec in self:
            rec.report_type_alert = '<span class="text-warning h5">Please select the proper QWEB views and Printer Type according to the Report.</span>'
            if rec.report_type == 'qweb-pdf':
                rec.printerType = 'PDF'
            if rec.report_type == 'qweb-html':
                rec.printerType = None
            if rec.report_type == 'qweb-text' and rec.printerType == 'PDF':
                rec.printerType = None

    def set_printerType_pdf(self):
        for rec in self:
                rec.printerType = 'PDF'

    def set_printerType_zpl(self):
        for rec in self:
                rec.printerType = 'ZPL'

    def set_printerType_escpos(self):
        for rec in self:
                rec.printerType = 'ESCPOS'
