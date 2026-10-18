# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import AccessError


class APIKeyDescription(models.TransientModel):
    _inherit = 'res.users.apikeys.description'

    def check_access_make_key(self):
        super().check_access_make_key()
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_("Only administrators can create API keys."))
