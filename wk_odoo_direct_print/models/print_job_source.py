# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2025-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#    See LICENSE file for full copyright and licensing details.
#################################################################################

from odoo import api, fields, models, tools, _

class PrintJobSource(models.Model):
    _name = 'print.job.source'
    _description = 'Print Job Source Records'
    
    name = fields.Char(string="Name", compute="_compute_name", recursive=True, store=True)
    print_job_id = fields.Many2one( 'print.jobs', required=True, ondelete='cascade' )
    print_id = fields.Integer( 'Print Job', related="print_job_id.id")

    content_ref = fields.Char(string="Document Ref")
    print_job_for = fields.Char( string="Print Job For", help="Indicates what the print job is used for (e.g., attachment, report).")    

    source_ref = fields.Reference(selection='_get_source_models',string="Source Document", help="Select the source document for this print job (e.g., invoice, sale order, report).")
    source_ref_char = fields.Char(string="Source Document Name", help="The display name of the selected source document.")

    def _get_source_models(self):
        models = self.env['ir.model'].search([])
        return [(m.model, m.name) for m in models]
    
    @api.depends('content_ref','source_ref_char')
    def _compute_name(self):
        for rec in self:
            rec.name = f'{rec.source_ref_char},{rec.content_ref}'
