# -*- coding: utf-8 -*-
{
    'name': 'CZ Data Guard',
    'summary': 'Export/import restricted to an allow-list of logins, audit log, API key lock',
    'description': """
Who may export and import is defined by ONE system parameter:
    cz_data_guard.allowed_logins   (comma-separated logins)
The module keeps "Access to export feature" in sync with that list:
on install, on every user-rights change, on every server start and
daily by cron. This also undoes Odoo silently re-granting export to all
users after an update of the base module.

- Export (list, Export All, pivot Download xlsx) and import are
  enforced on the SERVER, not only by hiding buttons.
- Every export attempt is logged (who, what, rows, allowed/blocked).
- Only Settings administrators can create new API keys.

To change who can export/import: Settings > Technical > System
Parameters > cz_data_guard.allowed_logins. Rollback: uninstall the
module, then add "Access to export feature" to the Default User
template (Odoo pushes it to all internal users).
""",
    'author': 'Choco Zuma',
    'version': '18.0.1.0.0',
    'category': 'Hidden/Tools',
    'depends': ['web', 'base', 'base_import', 'portal'],
    'data': [
        'security/ir.model.access.csv',
        'data/config_data.xml',
        'views/export_log_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'cz_data_guard/static/src/import_records_patch.js',
            'cz_data_guard/static/src/pivot_download_patch.js',
            'cz_data_guard/static/src/pivot_download_patch.xml',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
