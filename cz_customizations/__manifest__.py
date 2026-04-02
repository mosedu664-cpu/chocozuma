# -*- coding: utf-8 -*-
{
    'name': 'COCOZoma Customizations',
    'summary': 'Custom required for cocozoma',
    'description': """Custom required for cocozoma""",
    'author': "Axiomworld",
    'website': "https://axiomworld.net/",
    'depends': ['point_of_sale'],
    'category': 'Uncategorized',
    'version': '0.1',
    "assets": {
        "point_of_sale._assets_pos": [
            "cz_customizations/static/src/**/*",
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
