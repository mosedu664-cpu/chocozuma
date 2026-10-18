# -*- coding: utf-8 -*-
{
    'name': 'CZ Data Guard',
    'summary': 'Server-side export lock, export audit log, API key lock',
    'description': """
- Export (list export, CSV/XLSX, pivot XLSX) only for users with
  "Access to export feature"; enforced on the SERVER, not just by hiding
  the button. On install, the right is removed from everyone except
  Settings administrators and from the default new-user template.
- Every export is logged (who, model, fields, rows, format, time).
- Only Settings administrators can create API keys.
""",
    'author': 'Choco Zuma',
    'version': '18.0.1.0.0',
    'category': 'Hidden/Tools',
    'depends': ['web', 'base'],
    'data': [
        'security/ir.model.access.csv',
        'views/export_log_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
