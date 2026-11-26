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

Kitchen + depot (18.0.1.2.0): kitchen products kept in the Main Warehouse building are a
sub-location of the Central Kitchen stock (CKWH/Stock/2 Depo/Dondurucu | Soğuk Oda), so orders
still reserve them and the car can load at the depot. Transfer types Mutfak → Depo and
Depo → Mutfak; a "Stok" tab for the chefs (kitchen | depot side by side, days of cover, age,
alerts, one-click draft transfers); the same snapshot feeds the daily WhatsApp stock report.

Labels (18.0.1.4.0): "Etiket Yazdır" on the manufacturing order (and "Mutfak Etiketi" in the
product Print menu) prints 55×40 Zebra labels through RawBT. Odoo computes production date, SKT
(fresh) or freezer SKT + days after thawing (frozen) from the product's label shelf-life fields;
the MO number is the batch reference (no lot tracking — kitchen products are shared with branches).

Lot help (18.0.1.5.0): one lot per product per day (a second MO the same day reuses the
morning lot); on validation a lot line asking more than the lot holds is completed from the other
non-expired lots of the product (oldest first, noted in the chatter) — no more negative lots.

Only reads/acts through standard stock.picking rights: a user sees exactly
the transfers Odoo already lets them see.
    """,
    'author': 'Choco Zuma Yönetim',
    'website': 'https://chocozuma.com',
    'category': 'Inventory/Inventory',
    'version': '18.0.1.5.0',
    'license': 'LGPL-3',
    'depends': ['stock', 'mrp', 'web'],
    'data': [
        'views/dashboard_views.xml',
        'views/product_views.xml',
        'views/label_views.xml',
        'data/kitchen_depot_setup.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'cz_inventory_dashboard/static/src/dashboard/**/*',
            'cz_inventory_dashboard/static/src/stock_board/**/*',
        ],
    },
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': False,
}
