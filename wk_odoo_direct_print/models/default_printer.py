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

ATTACHMENT_FILE = [
    ('ZPL', 'ZPL File'),
    ('PDF', 'PDF File'),
    ('Image', 'Image File'),
]

class DefaultPrinter(models.Model):
    _name = "default.printer"
    _description = "Default Printer"
    _rec_name = "file_type"

    file_type = fields.Selection(selection=ATTACHMENT_FILE, string="Attachment Type", required=True)
    printer_ids = fields.Many2many('wk.printer', string="Printers", ondelete="cascade")
