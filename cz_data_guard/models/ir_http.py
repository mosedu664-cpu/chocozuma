# -*- coding: utf-8 -*-
from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        info = super().session_info()
        info['cz_can_transfer_data'] = self.env.user.has_group('base.group_allow_export')
        return info
