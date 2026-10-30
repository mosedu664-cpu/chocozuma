# -*- coding: utf-8 -*-
{
    'name': 'Choco Zuma — Cash Control (Kasa Köprüsü)',
    'summary': 'Daily cash bridge: POS drawer → categorised cash-outs → safe → accountant approval',
    'description': """
Choco Zuma Cash Control
=======================
Replaces the side Excel "kasa" sheets with a controlled flow inside Odoo:

* Cashier records every drawer expense from the POS with a fixed category
  (taxi, fuel, food, daily wage, market, cleaning, safe transfer...).
  No accounts are visible to the cashier and nothing can be edited afterwards.
* Safe transfers and sensitive categories require a manager PIN in the POS.
* Blind cash count at closing (expected amount hidden), zero/large differences
  need a manager PIN and a closing note.
* One "Daily Cash Sheet" per branch per day for the accountant: POS cash sales,
  cash-outs by category, safe transfers, counted, difference. Approval posts
  the counterparts to the right accounts and mirrors transfers into the safe
  journal. Nothing is posted before approval.
* Branch safe (küçük kasa) ledger with live balance, manager-only movements
  and periodic counts.
* Alerts (zero count, big difference, unusual expense, unapproved days).
    """,
    'author': 'Choco Zuma Yönetim',
    'website': 'https://chocozuma.com',
    'category': 'Accounting/Point of Sale',
    'version': '18.0.1.0.0',
    'license': 'LGPL-3',
    'depends': ['point_of_sale', 'pos_hr', 'account', 'hr'],
    'data': [
        'security/cz_cash_control_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',
        'data/mail_template_data.xml',
        'views/cz_cash_category_views.xml',
        'views/cz_cash_safe_views.xml',
        'views/cz_cash_safe_move_views.xml',
        'views/cz_cash_day_views.xml',
        'views/account_bank_statement_line_views.xml',
        'views/pos_config_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'cz_cash_control/static/src/**/*',
        ],
    },
    'installable': True,
    'application': True,
}
