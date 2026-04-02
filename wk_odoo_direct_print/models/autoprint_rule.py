# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2025-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#    See LICENSE file for full copyright and licensing details.
#################################################################################


from odoo import api, fields, models, _
import base64
from odoo.exceptions import ValidationError, UserError

class AutoPrintRule(models.Model):
    _name = "autoprint.rule"
    _description = "Auto Print Rule"


    model = fields.Selection([
        ('sale.order', 'Sale Order'),
        ('stock.picking', 'Delivery/Receipts'),
        ('purchase.order', 'Purchase Order'),
        ('account.move', 'Accounting (Invoice)'),
    ], string="Model", required=True)
    
    name_rule_id = fields.Many2one(
        "report.trigger.rule",
        string="Action",required=True,
        domain="[('model', '=', model)]"
    )
    
    report_id = fields.Many2one(
    'ir.actions.report',
    string='Report',
    domain="[('model', '=', model), ('report_type', 'in', ('qweb-pdf', 'qweb-text'))]",
    required=True
    )

    no_of_copies = fields.Integer(
        string='Number of Copies',
        default=1,required=True
    )

    printer_id = fields.Many2one(
        'wk.printer',
        string='Printer',
        domain="[('state', '=', 'Active')]"
    )
    
    is_enabled = fields.Boolean(string="Enabled", default=False,help='Enable or disable this printing rule.')

    @api.constrains('no_of_copies')
    def _check_no_of_copies(self):
        for record in self:
            if record.no_of_copies < 1:
                raise ValidationError("Number of copies must be at least 1.")
    
    def process_and_create_job(self, model, id, report_id, printer_id, copies=1,job_for=False):
        def create_print_job(printer_id, method, content, file_extension=None, is_byte_stream=False,ids=False,model=False,report_name=False):
            vals = {
                'printer_id': printer_id,
                'method': method,
                'content': content,
                'file_extension': file_extension,
                'is_byte_stream': is_byte_stream,
                'source_ref': {'model':model,'ids':ids},
                'report_name': report_name,
                'job_for': job_for if job_for else 'Printing Automation(Report)'
            }
            self.env['print.jobs'].create_notify_print_job(**vals)

        printer = self.env['wk.printer'].sudo()
        printer_id = printer.browse(int(printer_id.id) if printer_id!='' else None)
        report = self.env['ir.actions.report'].sudo()
        report_id = report.browse(int(report_id) if report_id!='' else None)
        if printer_id and report_id:
            if report_id.report_type == 'qweb-text':
                renderd_text = report._render_qweb_text(report_id.report_name, id, )[0]
                if report_id.printerType == 'ESCPOS':
                    renderd_text = str(renderd_text)
                    xml_text = renderd_text[4:-1].split('\\n')
                    xml_text = "".join(xml_text)
                    renderd_text = printer.get_esc_command_set({'data':xml_text})
                    renderd_text = renderd_text.replace("\x00", "[NULL]")
                for _ in range(copies):
                    create_print_job(printer_id, 'print-raw', renderd_text,ids=[id],model=model,report_name=report_id.display_name)
            elif report_id.report_type == 'qweb-pdf':
                pdf =  report._render_qweb_pdf(report_id.report_name,id)[0]
                base = base64.b64encode(pdf)
                for _ in range(copies):
                    create_print_job(printer_id, 'print-file', base, file_extension='pdf',ids=[id],model=model,report_name=report_id.display_name)
                
    def _autoprint_on_action(self,records,action_name,model):
        allowed_user = self.env.user
        active_company = self.env.company.id
        rules = self.search([
            ('model', '=', model),
            ('name_rule_id.name', '=', action_name),
            ('is_enabled', '=', True),
            ('printer_id', '!=', False),
            ('report_id', '!=', False),
            ('printer_id.hostmachine_id.user_ids', 'in', allowed_user.ids),
            ('printer_id.company_ids', 'in', [active_company]),
        ])
        for rule in rules:
            for rec in records:
                rule.process_and_create_job(
                    model=rec._name,
                    id=rec.id,
                    report_id=rule.report_id,
                    printer_id=rule.printer_id,
                    copies=rule.no_of_copies
                )
                    
    @api.onchange('model')
    def _onchange_model_clear_fields(self):
        self.name_rule_id = False
        self.report_id = False
        self.printer_id = False
        
    @api.onchange('printer_id')
    def _onchange_is_enabled(self):
        if not self.printer_id:
            self.is_enabled = False
            
