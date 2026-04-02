# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2025-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#    See LICENSE file for full copyright and licensing details.
#################################################################################

from odoo import api, fields, models, _
import logging
from odoo.exceptions import ValidationError, UserError

import base64
import tempfile

_logger=logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = "stock.picking"

    @api.returns('mail.message', lambda value: value.id)
    def message_post(self, **kwargs):
        message = super(StockPicking, self).message_post(**kwargs)
        allowed_company = self.company_id
        for attachment in message.attachment_ids:
            print_flag = False
            attachments_name = attachment.name
            auto_printdirect_carrier_labels = self.env['shipping.label.automation'].search([('carrier_ids', 'in', [self.carrier_id.id]), ('picking_type_ids', 'in', [self.picking_type_id.id]), ('print_label', '=', True), ('is_active', '=', True), ])
            auto_printdirect_export_documents = self.env['shipping.label.automation'].search([('carrier_ids', 'in', [self.carrier_id.id]), ('picking_type_ids', 'in', [self.picking_type_id.id]), ('print_documents', '=', True), ('is_active', '=', True), ])
            if auto_printdirect_carrier_labels and 'label' in attachments_name.lower():
                print_flag = True
                default_printer = auto_printdirect_carrier_labels.printer_ids
            elif auto_printdirect_export_documents and 'shippingdoc' in attachments_name.lower():
                print_flag = True
                default_printer = auto_printdirect_export_documents.printer_ids
            if print_flag:
                default_printers = None
                if attachment.name[-4:] in ['.pdf', '.PDF']:
                    default_printers = default_printer.filtered(lambda p: p.printerType in ('PDF','PDF Image'))
                    contentCode = attachment.datas
                    file_extension = 'pdf'
                    method = 'print-file'
                elif attachment.name[-4:] in ['.png', '.PNG', '.jpg', '.JPG']:
                    default_printers = default_printer.filtered(lambda p: p.printerType in ('Image','PDF Image'))
                    contentCode = attachment.datas
                    file_extension = attachment.name[-3:].lower()
                    method = 'print-image'
                elif attachment.name[-4:] in ['.zpl', '.ZPL']:
                    default_printers = default_printer.filtered(lambda p: p.printerType == 'ZPL')
                    temp = tempfile.NamedTemporaryFile(suffix='.txt')
                    with open(temp.name, 'wb') as file:
                        file.write(base64.b64decode(attachment.datas))
                    with open(temp.name, 'r') as file:
                        contentCode = file.read()
                        file_extension = None
                        method = 'print-raw'
                printer_ids = default_printers
                filtered_printers = []
                for printer in printer_ids:
                    if list(set([each.id for each in printer.company_ids]) & set([allowed_company.id])):
                        filtered_printers.append(printer)
                for printer in filtered_printers:
                    if printer.use_printer_access:
                        usr_ids = printer.user_ids
                    else:
                        usr_ids = printer.hostmachine_id.user_ids
                    if self.env.uid not in usr_ids.ids:
                        continue
                    vals = {
                        'printer_id': printer,
                        'method': method,
                        'content': contentCode,
                        'file_extension': file_extension,
                        'source_ref': {'model':'stock.picking','ids':self.ids},
                        'report_name': attachment.name,
                        'job_for':'Shipping Label(Attachment)'
                    }
                    self.env['print.jobs'].create_notify_print_job(**vals)
        return message

                
    def action_cancel(self):
        res = super().action_cancel()
        self.env['autoprint.rule']._autoprint_on_action(records=self,action_name="Cancel",model="stock.picking")
        return res

    def button_validate(self):
        res = super().button_validate()
        if res == True:
            self.env['autoprint.rule']._autoprint_on_action(records=self,action_name="Validate",model="stock.picking")
        return res

    def send_to_shipper(self):
        res = super().send_to_shipper()
        self.env['autoprint.rule']._autoprint_on_action(records=self,action_name="Send to Shipper",model="stock.picking")
        return res

    def action_put_in_pack(self):
        res = super().action_put_in_pack()
        self.env['autoprint.rule']._autoprint_on_action(records=self,action_name="Put in Pack",model="stock.picking")
        return res
