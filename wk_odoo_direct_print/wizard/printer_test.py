# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2025-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#    See LICENSE file for full copyright and licensing details.
#################################################################################

from odoo import models, fields, api, _
import logging 
from odoo.exceptions import ValidationError, UserError
import random

_logger = logging.getLogger(__name__)

TEXT_CONTENT = '''+----------------------------------------------+
               Hi! How are you?
+----------------------------------------------+'''
ESCPOS_CONTENT = '''\x1ba\x00\x1b!\x00\x1br\x00\x1b-\x00\x1bE\x00\x1bM\x00\x1ba\x01\x1b!\x00\x1br\x00\x1b-\x00\x1bE\x00\x1bM\x00\x1ba\x01\x1b!0\x1br\x00\x1b-\x00\x1bE\x01\x1bM\x00\x1bt\x00My Company\n\x1ba\x01\x1b!\x00\x1br\x00\x1b-\x00\x1bE\x00\x1bM\x00\n\x1ba\x01\x1b!\x00\x1br\x00\x1b-\x00\x1bE\x00\x1bM\x00\x1ba\x01\x1b!\x00\x1br\x00\x1b-\x00\x1bE\x00\x1bM\x01\x1ba\x01\x1b!\x00\x1br\x00\x1b-\x00\x1bE\x00\x1bM\x01My Company (San Francisco)\n\x1ba\x01\x1b!\x00\x1br\x00\x1b-\x00\x1bE\x00\x1bM\x01\x1ba\x01\x1b!\x00\x1br\x00\x1b-\x00\x1bE\x00\x1bM\x01Tel:+1 (777) 777-7777\n\x1ba\x01\x1b!\x00\x1br\x00\x1b-\x00\x1bE\x00\x1bM\x01\x1ba\x01\x1b!\x00\x1br\x00\x1b-\x00\x1bE\x00\x1bM\x01info@yourcompany.com\n\x1ba\x01\x1b!\x00\x1br\x00\x1b-\x00\x1bE\x00\x1bM\x01\x1ba\x01\x1b!\x00\x1br\x00\x1b-\x00\x1bE\x00\x1bM\x01http://www.example.com\n\x1ba\x01\x1b!\x00\x1br\x00\x1b-\x00\x1bE\x00\x1bM\x01\x1ba\x01\x1b!\x00\x1br\x00\x1b-\x00\x1bE\x00\x1bM\x01\x1ba\x01\x1b!\x00\x1br\x00\x1b-\x00\x1bE\x00\x1bM\x01--------------------------------\n\x1ba\x01\x1b!\x00\x1br\x00\x1b-\x00\x1bE\x00\x1bM\x01\x1ba\x01\x1b!\x00\x1br\x00\x1b-\x00\x1bE\x00\x1bM\x01Served by Mitchell Admin\n\x1ba\x01\x1b!\x00\x1br\x00\x1b-\x00\x1bE\x00\x1bM\x01\x1ba\x01\x1b!\x00\x1br\x00\x1b-\x00\x1bE\x00\x1bM\x00\n\n\n\x1dV\x00'''
ZPL_CONTENT = '''
^XA ^CFA,30 ^FO50,100^FD Printing ^FS ^FO50,140^FD Test 1 ^FS ^FO50,180^FD Testing Test 2 ^FS ^FO50,220^FD Testing Test 3 ^FS ^CFA,15 ^BY5,2,270 ^FO100,350^BC^FD 11223344 ^FS ^XZ
'''

class WizardTestPrinter(models.TransientModel):
    _name = "wizard.test.printer"
    _description ="Test Printer"

    name = fields.Char(string="Name")
    host_id = fields.Char(string="Host ID")
    idVendor = fields.Char(string="Vendor ID")
    idProduct = fields.Char(string="Product ID")
    paper_width = fields.Integer(string="Paper Width")
    paper_height = fields.Integer(string="Paper Height")
    printerType = fields.Char(string="Printer Type")
    content = fields.Text(string="Content", compute="_compute_content")
    editor = fields.Text(string="Editor")
    use_editer = fields.Boolean(string="Use Editor")
    noOfPrint = fields.Integer(string="No of Prints", default=1, readonly=True)
    
    def _compute_content(self):
        for rec in self:
            if rec.printerType and 'ESCPOS' in rec.printerType:
                rec.content = ESCPOS_CONTENT
            elif rec.printerType and 'ZPL' in rec.printerType:
                rec.content = ZPL_CONTENT
            else:
                rec.content = TEXT_CONTENT

    def _construct_notification(self, msg, type='success'):
        return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'type': type,
                        'message': _(msg),
                    }
                }
    
    def test_printer(self):
        printer_id = self.env['wk.printer'].search([('id', '=', self.env.context.get("active_id"))])
        if self.use_editer:
            if self.editor == '':
                raise ValidationError('Please write something on the editor.')
        content = self.content if not self.use_editer else self.editor
        print_data = printer_id._get_printer_config()
        vals = {
            'printer_id': printer_id.id,
            'method': 'print-raw',
            # 'file_extension': 'none',
            'content': content.replace("\x00", "[NULL]"),
        }
        new_print_job = self.env['print.jobs'].create(vals)
        print_data['contentCode'] = new_print_job.content

        msg_id = random.randint(999,1_999_999_999)
        if printer_id.use_printer_access:
            usr_ids = printer_id.user_ids
        else:
            usr_ids = printer_id.hostmachine_id.user_ids
        for each_partner in usr_ids:
            self.env['bus.bus']._sendone(
                each_partner.partner_id,
                "mail.record/insert",
                {'Persona': [{
                'id': msg_id, 
                'im_status': 'print direct', 
                'type': 'partner', 
                'data':{'method': 'print-job-cmd', 'host_id':printer_id.hostmachine_id.host_id, 'record_id':new_print_job.id}
                }]}
            )
