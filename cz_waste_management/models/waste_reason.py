# -*- coding: utf-8 -*-
from odoo import fields, models


class WasteReason(models.Model):
    _name = 'waste.reason'
    _description = 'Waste Reason'
    _order = 'sequence, id'

    name = fields.Char(
        string='Reason',
        required=True,
        translate=True,
    )
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)
    description = fields.Text(string='Description')
    color = fields.Integer(string='Color')
