# -*- coding: utf-8 -*-
from odoo import fields, models, tools


class WasteReport(models.Model):
    _name = 'waste.report'
    _description = 'Waste Report'
    _auto = False
    _order = 'timestamp desc'

    timestamp = fields.Datetime(string='Date & Time', readonly=True)
    user_id = fields.Many2one('res.users', string='Employee / User', readonly=True)
    order_ref = fields.Char(string='Order Reference', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    quantity = fields.Float(string='Quantity Wasted', readonly=True, aggregator='sum')
    product_uom_id = fields.Many2one('uom.uom', string='Unit of Measure', readonly=True)
    unit_cost = fields.Float(string='Unit Cost', readonly=True, aggregator='avg')
    total_cost = fields.Float(string='Total Cost (Value)', readonly=True, aggregator='sum')
    reason_id = fields.Many2one('waste.reason', string='Waste Reason', readonly=True)
    location_id = fields.Many2one('stock.location', string='Source Location', readonly=True)
    station = fields.Char(string='Station', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    wl.id AS id,
                    wl.timestamp AS timestamp,
                    wl.user_id AS user_id,
                    wl.order_ref AS order_ref,
                    wl.product_id AS product_id,
                    wl.quantity AS quantity,
                    wl.product_uom_id AS product_uom_id,
                    CASE WHEN wl.quantity > 0 THEN wl.cost / wl.quantity ELSE 0 END AS unit_cost,
                    wl.cost AS total_cost,
                    wl.reason_id AS reason_id,
                    wl.location_id AS location_id,
                    wl.station AS station,
                    wl.company_id AS company_id
                FROM waste_log wl
                WHERE wl.state = 'confirmed'
            )
        """ % self._table)
