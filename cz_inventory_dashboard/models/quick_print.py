# -*- coding: utf-8 -*-
from odoo import models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def action_cz_print_slip(self):
        """Opens the delivery slip as a page that shows the device's print dialog at once."""
        return {
            "type": "ir.actions.act_url",
            "url": "/cz/print/stock.report_deliveryslip/%s" % ",".join(str(i) for i in self.ids),
            "target": "new",
        }
