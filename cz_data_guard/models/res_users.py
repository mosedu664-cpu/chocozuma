# -*- coding: utf-8 -*-
import logging

from odoo import api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PARAM = 'cz_data_guard.allowed_logins'
GROUP_FIELD_PREFIXES = ('in_group_', 'sel_groups_')


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def _cz_allowed_logins(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(PARAM) or ''
        return {x.strip().lower() for x in raw.split(',') if x.strip()}

    @api.model
    def _cz_enforce_export_policy(self, strict=False):
        """Make 'Access to export feature' == allow-list. Idempotent.
        strict=True (install): abort if a listed login does not exist, so a
        typo can never silently strip the wrong person."""
        if self.env.context.get('cz_policy_running'):
            return
        Users = self.sudo().with_context(cz_policy_running=True, active_test=False)
        allowed_logins = Users._cz_allowed_logins()
        if not allowed_logins:
            # Safety: an empty/missing list must never strip everyone.
            _logger.warning("cz_data_guard: %s is empty - policy NOT enforced", PARAM)
            return
        group = Users.env.ref('base.group_allow_export')
        all_users = Users.search([])
        allowed = all_users.filtered(lambda u: (u.login or '').strip().lower() in allowed_logins)
        missing = allowed_logins - {(u.login or '').strip().lower() for u in allowed}
        if missing:
            msg = "cz_data_guard: allowed logins not found: %s" % ', '.join(sorted(missing))
            if strict:
                raise UserError(msg)
            _logger.warning(msg)
        current = group.with_context(active_test=False).users
        to_add = allowed - current
        to_remove = current.filtered(lambda u: not u._is_superuser()) - allowed
        commands = [(4, u.id) for u in to_add] + [(3, u.id) for u in to_remove]
        if commands:
            group.with_context(cz_policy_running=True).write({'users': commands})
            _logger.info("cz_data_guard: export granted to %s, removed from %s",
                         to_add.mapped('login'), to_remove.mapped('login'))
        default_user = Users.env.ref('base.default_user', raise_if_not_found=False)
        if default_user and group in default_user.groups_id:
            default_user.write({'groups_id': [(3, group.id)]})

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('cz_policy_running') and any(
            k == 'groups_id' or k.startswith(GROUP_FIELD_PREFIXES) for k in vals
        ):
            # Covers manual edits AND Odoo propagating default-user groups
            # to every internal user.
            self._cz_enforce_export_policy()
        return res

    def _register_hook(self):
        """Re-apply on every server start: undoes a re-grant done while
        updating 'base' (our write override is not loaded at that time)."""
        res = super()._register_hook()
        try:
            with self.env.cr.savepoint():
                self._cz_enforce_export_policy()
        except Exception:
            _logger.exception("cz_data_guard: enforcement at startup failed (ignored)")
        return res
