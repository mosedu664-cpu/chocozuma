# -*- coding: utf-8 -*-
from odoo import api, models

from .res_users import PARAM


class IrConfigParameter(models.Model):
    _inherit = 'ir.config_parameter'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if any(v.get('key') == PARAM for v in vals_list):
            self.env['res.users']._cz_enforce_export_policy()
        return records

    def write(self, vals):
        touched = any(r.key == PARAM for r in self) or vals.get('key') == PARAM
        res = super().write(vals)
        if touched:
            # Apply the new allow-list immediately.
            self.env['res.users']._cz_enforce_export_policy()
        return res
