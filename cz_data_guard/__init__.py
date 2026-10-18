# -*- coding: utf-8 -*-
from . import models
from . import controllers


# The ONLY users allowed to export and import (Mo's decision, 19/10/2026).
# Everyone else loses the right on install. Grant/revoke later by ticking
# "Access to export feature" on the user (developer mode).
ALLOWED_LOGINS = [
    'admin',                    # ADMIN (Mo)
    'muhamed@gmail.com',        # Muhamed - accountant
    'esmaa@gmail.com',          # Esmaa - accountant assistant
    'pazarlama@chocozuma.com',  # Iclal - marketing
]


def post_init_hook(env):
    export_group = env.ref('base.group_allow_export')
    Users = env['res.users'].with_context(active_test=False)
    allowed = Users.search([('login', 'in', ALLOWED_LOGINS)])
    others = export_group.users.filtered(lambda u: not u._is_superuser()) - allowed
    commands = [(4, u.id) for u in allowed] + [(3, u.id) for u in others]
    if commands:
        export_group.write({'users': commands})
    default_user = env.ref('base.default_user', raise_if_not_found=False)
    if default_user:
        default_user.sudo().write({'groups_id': [(3, export_group.id)]})
