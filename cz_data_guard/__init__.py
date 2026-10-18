# -*- coding: utf-8 -*-
from . import models
from . import controllers


def post_init_hook(env):
    """Remove the export right from everyone except Settings admins and
    from the default template used for new users. Reversible: tick
    "Access to export feature" on a user to grant it back."""
    export_group = env.ref('base.group_allow_export')
    admin_group = env.ref('base.group_system')
    to_remove = export_group.users.filtered(
        lambda u: not u._is_superuser() and admin_group not in u.groups_id
    )
    if to_remove:
        export_group.write({'users': [(3, u.id) for u in to_remove]})
    default_user = env.ref('base.default_user', raise_if_not_found=False)
    if default_user:
        default_user.sudo().write({'groups_id': [(3, export_group.id)]})
