# -*- coding: utf-8 -*-
{
    'name': 'Chocozuma Waste Management',
    'version': '18.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Kitchen waste logging from KDS with inventory tracking',
    'description': """
        Waste Management System for Chocozuma
        ======================================
        - Log Waste button on Kitchen Display Screen (KDS)
        - Popup form for waste logging with product, quantity, reason, photo
        - Automatic inventory deduction via configured Waste location
        - XLSX waste reporting with custom filters
    """,
    'author': 'Axiom World | Burhan Ud Din',
    'website': 'https://axiomworld.net/',
    'depends': [
        'pos_preparation_display',
        'stock',
        'point_of_sale',
    ],
    'data': [
        'security/waste_management_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'wizard/waste_report_wizard_view.xml',
        'views/waste_log_views.xml',
        'views/waste_reason_views.xml',
        'views/pos_config_views.xml',
        'views/res_company_views.xml',
        'views/waste_management_menus.xml',
    ],
    'assets': {
        'pos_preparation_display.assets': [
            'cz_waste_management/static/src/**/*',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
