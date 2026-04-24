# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    waste_location_id = fields.Many2one(
        'stock.location',
        string='Waste Location',
        help='Virtual location where wasted inventory is moved to.',
    )
