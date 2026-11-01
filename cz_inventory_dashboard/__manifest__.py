# -*- coding: utf-8 -*-
{
    'name': 'Choco Zuma — Sevkiyat Paneli',
    'summary': 'Inventory home dashboard: deliveries ready / waiting / late, receipts, per warehouse and customer',
    'description': """
Choco Zuma Inventory Dashboard (Sevkiyat Paneli)
================================================
One screen for every inventory user, opened as the Inventory home page:

* Today's picture per warehouse (Main Warehouse, Central Kitchen, Dropship):
  Ready to ship, Waiting (not reserved), Late, Receipts to accept, Internal.
* Late and Ready deliveries listed by customer (branch), with scheduled time,
  source order, line count, reservation state — one click opens the transfer,
  one click validates a fully-reserved delivery.
* "Check availability" on waiting deliveries straight from the board.
* Priority customers (branches) pinned at the top; the rest grouped.
* Auto-refresh every 60 s; last 7 days throughput per warehouse.

Only reads/acts through standard stock.picking rights: a user sees exactly
the transfers Odoo already lets them see.
    """,
    'author': 'Choco Zuma Yönetim',
    'website': 'https://chocozuma.com',
    'category': 'Inventory/Inventory',
    'version': '18.0.1.0.5',
    'license': 'LGPL-3',
    'depends': ['stock', 'web'],
    'data': [
        'views/dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'cz_inventory_dashboard/static/src/dashboard/**/*',
        ],
    },
    'installable': True,
    'application': False,
}
