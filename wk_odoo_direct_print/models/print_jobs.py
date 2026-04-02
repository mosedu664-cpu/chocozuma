# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2025-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#    See LICENSE file for full copyright and licensing details.
#################################################################################

from odoo import api, fields, models, _
import logging
from odoo.exceptions import ValidationError, UserError
from datetime import datetime, timedelta
import random
import base64
import tempfile

_logger=logging.getLogger(__name__)

METHOD = [
    ('print-raw', 'Raw Commandset'),
    ('print-image', 'Image'),
    ('print-file', 'File'),
    ('print-complex', 'Raw+Image'),
]

class PrintJobs(models.Model):
    _name = "print.jobs"
    _description = "Print Jobs"
    _rec_name = 'name'

    name = fields.Char(string="Name", compute="_compute_name", recursive=True, store=True)
    msg_id_for_ws = fields.Char(string="Message ID on Websocket", default=str(random.randint(999, 1_999_999_999)), help="Use this message ID to resend the Websocket message unless the Desktop App receives.")
    host_id = fields.Char(string="Host ID", compute="_compute_host_id")
    printer_id = fields.Many2one('wk.printer', string="Printer")
    state = fields.Selection(selection=[('Queue', 'Queue'), ('Done', 'Sent'), ('Failed', 'Failed'),('In Progress', 'In Progress'), ('Print Done', 'Print Done')], string='State', default='Queue')
    method = fields.Selection(selection=METHOD, string="Print What?", required=True)
    is_byte_stream = fields.Boolean(string="Is byte Stream", help="If True, the content stores the list() of bytes.")
    msg = fields.Text(string="Response")
    file_extension = fields.Char(string="File Extension")
    content = fields.Text(string="Content", required=True)
    use_raw_image = fields.Boolean()
    is_dummy = fields.Boolean()


    print_job_source_ids = fields.One2many(
        'print.job.source',
        'print_job_id',
        string="Source Records"
    )
    
    model_ref = fields.Char(string="Model Ref")
    rec_ref = fields.Char(string="Record Ref")
    content_ref = fields.Char(string="Document Ref")
    print_job_for = fields.Char( string="Print Job For", help="Indicates what the print job is used for (e.g., attachment, report).")    


    @api.depends('create_date')
    def _compute_name(self):
        for rec in self:
            now = datetime.now()
            today = now.date()
            yesterday = today - timedelta(days=1)
            dt = rec.create_date
            if dt.date() == today:
                rec.name = f"Today"
            elif dt.date() == yesterday:
                rec.name = f"Yesterday"
            else:
                rec.name = f"On {dt.strftime('%b %d')}"

    @api.depends('printer_id')
    def _compute_host_id(self):
        for rec in self:
            rec.host_id = rec.printer_id.hostmachine_id.host_id

    def retry_print(self):
        if not self.printer_id:
            raise ValidationError('The Printer info is missing.\nThis may occur if the user have deleted the printer info from odoo.\nCreate a new print job.')
        msg_id = random.randint(999,1_999_999_999)
        if self.printer_id.use_printer_access:
            usr_ids = self.printer_id.user_ids
        else:
            usr_ids = self.printer_id.hostmachine_id.user_ids
        for each_partner in usr_ids:
            message = {'Persona': [{
                'id': msg_id,
                'im_status': 'print direct', 
                'type': 'partner', 
                'data':{'method': 'print-job-cmd', 'host_id':self.printer_id.hostmachine_id.host_id, 'record_id':self.id}
                }]}
            self.env['bus.bus']._sendone(
                each_partner.partner_id,
                "mail.record/insert",
                message
            )

    def create_notify_print_job(self, **kwargs):
        msg_id = random.randint(999,1_999_999_999)
        record = self.env[kwargs['source_ref']['model']].browse(kwargs["source_ref"]["ids"][0])
        vals = {
                'printer_id': kwargs.get('printer_id').id,
                'method': kwargs.get('method'),
                'content': kwargs.get('content'),
                'file_extension': kwargs.get('file_extension'),
                'msg_id_for_ws': str(msg_id),
                'is_byte_stream': kwargs.get('is_byte_stream'),
                "content_ref": kwargs.get("report_name"),
                "print_job_for": kwargs.get("job_for"),
                "model_ref": kwargs['source_ref']['model'],
                "rec_ref":record.name if 'name' in record._fields else f'{record._name}:{record.id}'
            }
        new_print_job = self.create(vals)
        try:
            if kwargs.get("source_ref", {}).get("ids"):
                ref_vals_list = []

                for rec_id in kwargs["source_ref"]["ids"]:
                    source_rec = self.env[kwargs['source_ref']['model']].browse(rec_id)

                    ref_vals = {
                        "content_ref": kwargs.get("report_name"),
                        "print_job_for": kwargs.get("job_for"),
                        "print_job_id": new_print_job.id,
                        "source_ref": f"{kwargs['source_ref']['model']},{rec_id}",
                        "source_ref_char": source_rec.name if 'name' in source_rec._fields 
                            else f'{source_rec._name}:{source_rec.id}'
                    }

                    ref_vals_list.append(ref_vals)

                self.env['print.job.source'].create(ref_vals_list)

        except Exception as e:
            _logger.exception("Error while creating print.job.source records: %s", e)
        if new_print_job.printer_id.use_printer_access:
            usr_ids = new_print_job.printer_id.user_ids
        else:
            usr_ids = new_print_job.printer_id.hostmachine_id.user_ids
        for each_partner in usr_ids:
            message = {'Persona': [{
                'id': msg_id, 
                'im_status': 'print direct', 
                'type': 'partner', 
                'data':{'method': 'print-job-cmd', 'host_id':new_print_job.printer_id.hostmachine_id.host_id, 'record_id':new_print_job.id}
                }]}
            self.env['bus.bus']._sendone(
                each_partner.partner_id,
                "mail.record/insert",
                message
            )

    def _cron_clean_print_jobs(self, days=3, queue=False, sent=True, failed=False):
        state = []
        if queue:
            state.append('Queue')
        if sent:
            state.append('Done')
        if failed:
            state.append('Failed')
        for rec in self.search([('state', 'in', state)]):
            if (datetime.now() - rec.create_date).days > days:
                rec.unlink()

    def _cron_renotify_queued_jobs(self, jobs=10, created_within=120):
        '''
        :param jobs: number of jobs to notify.
        :param created_within: takes minutes, compares from datetime.now() 
        '''
        created_before = (datetime.now() - timedelta(minutes=created_within)).strftime('%Y-%m-%d %H:%M:%S')
        for rec in self.search([('state', '=', 'Queue'), ('create_date', '>=', created_before)], limit=jobs):
            if rec.printer_id.use_printer_access:
                usr_ids = rec.printer_id.user_ids
            else:
                usr_ids = rec.printer_id.hostmachine_id.user_ids
            for each_partner in usr_ids:
                message = {'Persona': [{
                    'id': int(rec.msg_id_for_ws), 
                    'im_status': 'print direct', 
                    'type': 'partner', 
                    'data':{'method': 'print-job-cmd', 'host_id':rec.printer_id.hostmachine_id.host_id, 'record_id':rec.id}
                    }]}
                self.env['bus.bus']._sendone(
                    each_partner.partner_id,
                    "mail.record/insert",
                    message
                )
    
    def print_attachment(self, id, activeCompanyIds=[], auto=False):
        attachment = id if auto else self.env['ir.attachment'].sudo().search([('id', '=', id)])
        default_printer = self.env['default.printer']
        return_data = {
            'success' : True,
        }
        activeCompanyIds = activeCompanyIds if activeCompanyIds else self.env.company.ids
        if attachment:
            res_model = attachment.res_model
            attachment_type = attachment.name[-4:]
            default_printers = None
            if attachment_type in ['.pdf', '.PDF']:
                if auto:
                    default_printers = self.env['attachment.automation'].search([('model_ids.model', '=', res_model), ('print_type', '=', 'pdf'), ('is_active', '=', True), ])
                else:
                    default_printers = default_printer.search([('file_type', '=', 'PDF')])
                contentCode = attachment.datas
                file_extension = 'pdf'
                method = 'print-file'
            elif attachment_type in ['.png', '.PNG', '.jpg', '.JPG']:
                # default_printers = default_printer.search([('file_type', '=', 'Image')])
                if auto:
                    default_printers = self.env['attachment.automation'].search([('model_ids.model', '=', res_model), ('print_type', '=', 'img'), ('is_active', '=', True), ])
                else:
                    default_printers = default_printer.search([('file_type', '=', 'Image')])
                contentCode = attachment.datas
                file_extension = attachment.name[-3:].lower()
                method = 'print-image'
            elif attachment_type in ['.zpl', '.ZPL']:
                # default_printers = default_printer.search([('file_type', '=', 'ZPL')])
                if auto:
                    default_printers = self.env['attachment.automation'].search([('model_ids.model', '=', res_model), ('print_type', '=', 'zpl'), ('is_active', '=', True), ])
                else:
                    default_printers = default_printer.search([('file_type', '=', 'ZPL')])
                temp = tempfile.NamedTemporaryFile(suffix='.txt')
                with open(temp.name, 'wb') as file:
                    file.write(base64.b64decode(attachment.datas))
                with open(temp.name, 'r') as file:
                    contentCode = file.read()
                    file_extension = None
                    method = 'print-raw'
            if default_printers:
                printer_ids = default_printers.printer_ids
                filtered_printers = []
                for printer in printer_ids:
                    if list(set([each.id for each in printer.company_ids]) & set(activeCompanyIds)):
                        filtered_printers.append(printer)
                if not filtered_printers:
                    return {
                        'success' : False,
                        'msg' : 'Default Printer Not Configured for this attachment type or company.\nGo to: Print Direct > Printer > Default Printer For Attachments',
                    }
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
                        'source_ref': {'model':attachment.res_model,'ids':[attachment.res_id]},
                        'report_name': attachment.name,
                        'job_for':'Printing Automation(Attachment)' if auto else 'Attachment'
                    }
                    self.create_notify_print_job(**vals)
            if not auto:
                return return_data
