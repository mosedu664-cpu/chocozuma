# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2025-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#    See LICENSE file for full copyright and licensing details.
#################################################################################

from odoo import api, fields, models, _

class IrActionsServer(models.Model):
    _inherit = 'ir.actions.server'

    state = fields.Selection(
        selection_add=[('auto_print', 'Automatic Printing')],
        ondelete={'auto_print': 'set default'}
    )
    
    printer_id = fields.Many2one(
        'wk.printer',
        string='Printer',
        required=True,
        domain="[('state', '=', 'Active')]"
    )
    
    model_technical_name = fields.Char(
    string='Model Technical Name',
    related='model_id.model',
    store=True,
    readonly=True
)

    report_id = fields.Many2one(
        'ir.actions.report',
        string='Report',
        required=True,
        domain="[('model', '=', model_technical_name), ('report_type', 'in', ('qweb-pdf', 'qweb-text'))]",
        help="Select a report for the chosen model. Only QWeb PDF or Text reports are allowed."
    )
    

    
    
    def _run_action_auto_print_multi(self, eval_context=None):
        records = eval_context.get('records') or eval_context.get('record')
        for rec in records:
            self.env['autoprint.rule'].process_and_create_job(
                        model=rec._name,
                        id=rec.id,
                        report_id=self.report_id,
                        printer_id=self.printer_id,
                        copies=1,
                        job_for = 'Advance Printing Automation(Report)' 
                    )