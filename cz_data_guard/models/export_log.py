# -*- coding: utf-8 -*-
from odoo import fields, models


class CzExportLog(models.Model):
    _name = 'cz.export.log'
    _description = 'Export Audit Log'
    _order = 'create_date desc'

    user_id = fields.Many2one('res.users', string='User', readonly=True, index=True)
    model = fields.Char(string='Model', readonly=True, index=True)
    model_label = fields.Char(string='Data', readonly=True)
    field_count = fields.Integer(string='Columns', readonly=True)
    record_count = fields.Integer(string='Rows', readonly=True)
    export_format = fields.Selection(
        [('xlsx', 'Excel'), ('csv', 'CSV'), ('pivot', 'Pivot Excel')],
        string='Format', readonly=True)
    allowed = fields.Boolean(string='Allowed', readonly=True)
