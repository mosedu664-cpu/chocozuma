# -*- coding: utf-8 -*-
"""18.0.1.2.0 — give the existing categories an icon and a tile colour.

Only categories still on the default icon ('fa-tag' / empty) are touched, so
anything the accountant already customised is kept.
"""
from odoo import api, SUPERUSER_ID

# code -> (icon, colour index 0-11)
BY_CODE = {
    'TAKSI': ('fa-taxi', 3),
    'BENZIN': ('fa-car', 2),
    'YEMEK': ('fa-cutlery', 10),
    'GUNLUK': ('fa-user-circle-o', 7),
    'MARKET': ('fa-shopping-basket', 4),
    'TEMIZLIK': ('fa-tint', 4),
    'TAMIR': ('fa-wrench', 8),
    'DIGER': ('fa-question-circle', 0),
    'IADE': ('fa-undo', 6),
    'AVANS': ('fa-hand-paper-o', 9),
    'KASA': ('fa-archive', 1),
    'KASADAN': ('fa-plus-circle', 10),
    'MAAS': ('fa-money', 5),
    'KIRA': ('fa-home', 8),
    'SGK': ('fa-institution', 8),
    'ELEKTRIK': ('fa-bolt', 3),
    'TEDARIK': ('fa-truck', 7),
    'BANKA': ('fa-university', 8),
}
BY_KIND = {
    'expense': ('fa-shopping-basket', 4),
    'safe_transfer': ('fa-archive', 1),
    'refund': ('fa-undo', 6),
    'advance': ('fa-hand-paper-o', 9),
    'bank_deposit': ('fa-university', 8),
    'salary': ('fa-money', 5),
    'cash_in': ('fa-plus-circle', 10),
    'other': ('fa-tag', 0),
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cats = env['cz.cash.category'].with_context(active_test=False).search([])
    for cat in cats:
        if cat.icon and cat.icon != 'fa-tag':
            continue
        icon, color = BY_CODE.get((cat.code or '').upper()) or BY_KIND.get(cat.kind, ('fa-tag', 0))
        vals = {'icon': icon}
        if not cat.color:
            vals['color'] = color
        cat.write(vals)
