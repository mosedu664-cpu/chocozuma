# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import AccessError


class BaseImport(models.TransientModel):
    _inherit = 'base_import.import'

    def execute_import(self, fields, columns, options, dryrun=False):
        """Server-side import lock: same people as export."""
        # Programmatic imports run in sudo/superuser (module data loading,
        # e.g. app_common.app_quick_import) are never blocked.
        if not self.env.su and not self.env.user.has_group('base.group_allow_export'):
            raise AccessError(_("You are not allowed to import data."))
        return super().execute_import(fields, columns, options, dryrun=dryrun)
