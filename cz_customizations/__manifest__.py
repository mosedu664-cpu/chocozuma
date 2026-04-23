# -*- coding: utf-8 -*-
{
    'name': 'COCOZoma Customizations',
    'summary': 'Custom required for cocozoma',
    'description': """Custom required for cocozoma""",
    'author': "Axiomworld",
    'website': "https://axiomworld.net/",
    'depends': ['point_of_sale', 'pos_preparation_display'],
    'category': 'Uncategorized',
    'version': '0.1',
    'data': [
        'views/product_template_views.xml',
        'views/pos_order_views.xml',
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "cz_customizations/static/src/**/*",
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
