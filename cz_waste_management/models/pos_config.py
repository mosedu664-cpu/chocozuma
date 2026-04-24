# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    waste_location_id = fields.Many2one(
        'stock.location',
        string='Waste Location',
        help='Location where wasted inventory is moved to for this POS. If not set, company default is used.',
        domain="[('usage', '=', 'inventory'), ('scrap_location', '=', True)]",
    )
