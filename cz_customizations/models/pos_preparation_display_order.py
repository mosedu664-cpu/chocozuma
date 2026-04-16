# -*- coding: utf-8 -*-
from odoo import api, models

class PosPreparationDisplayOrder(models.Model):
    _inherit = 'pos_preparation_display.order'

    def _export_for_ui(self, preparation_display):
        res = super()._export_for_ui(preparation_display)
        if res:
            for line in res.get('orderlines', []):
                product = self.env['product.product'].browse(line['product_id'])
                if product.short_name:
                    line['product_name'] = product.short_name
        return res
