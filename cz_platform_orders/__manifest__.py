# -*- coding: utf-8 -*-
{
    'name': 'Choco Zuma — Platform Orders (Trendyol Yemek / Yemeksepeti)',
    'summary': 'Read-only intake of delivery-platform orders into Odoo',
    'description': """
Platform Orders
===============
Step 1: READ-ONLY intake.  Step 2 (18.0.2): POS sales, kitchen display,
automatic refunds, cashier toast. See models/platform_order_pos.py.

* One "Platform Account" record per platform account (platform, company,
  branch/POS, sales line, credentials). Today: Trendyol Yemek / Choco Zuma /
  Kayaşehir. Later: Tonalli breakfast accounts, Yemeksepeti, Mayapan.
* "Fetch orders" pulls packages from the Uber Eats Trendyol Go Yemek API
  (GET /integrator/order/meal/suppliers/{supplierId}/packages) and stores
  them with their lines in Odoo.
* The connector can only send GET requests: it never accepts, rejects,
  cancels or changes an order on the platform. Sepet Takip and the staff keep
  running the orders exactly as today.
* Nothing is posted: no POS order, no stock move, no accounting entry yet.
  (Step 2 turns stored orders into POS sales.)

Credentials are visible to administrators only.
    """,
    'author': 'Choco Zuma Yönetim',
    'website': 'https://chocozuma.com',
    'category': 'Sales/Point of Sale',
    'version': '18.0.2.0.1',
    'license': 'LGPL-3',
    'depends': ['point_of_sale'],
    'data': [
        'security/ir.model.access.csv',
        'data/cron.xml',
        'views/platform_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'cz_platform_orders/static/src/platform_notify.js',
        ],
    },
    'installable': True,
    'application': False,
}
