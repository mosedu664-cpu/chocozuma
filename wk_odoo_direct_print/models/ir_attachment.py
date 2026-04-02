# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2025-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#    See LICENSE file for full copyright and licensing details.
#################################################################################

from odoo import models, api


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    def write(self, vals):
        res = super(IrAttachment, self).write(vals)
        for rec in self:
            self.env['print.jobs'].print_attachment(id = rec,activeCompanyIds = [rec.env.company.id],auto=True)
        return res 
