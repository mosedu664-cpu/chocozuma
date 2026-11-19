# -*- coding: utf-8 -*-
"""One payment method (and journal) per platform in the POS that the
Trendyol accounts post to (Kayaşehir), like Metrokent already has:

    Trendyol Çikolata  (TYC)   -> Choco Zuma invoiced, automatic
    Trendyol Kahvaltı  (TYK)   -> Tonalli invoiced, automatic
    Yemeksepeti Çikolata (YSC) -> cashier
    Yemeksepeti Kahvaltı (YSK) -> cashier

Idempotent: existing journals/methods (by code) are reused. The old
"Online Payment" method is left untouched (history + open sessions).
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

DEFS = [
    ('TYC', 'Trendyol Çikolata', 'chocolate'),
    ('TYK', 'Trendyol Kahvaltı', 'breakfast'),
    ('YSC', 'Yemeksepeti Çikolata', None),
    ('YSK', 'Yemeksepeti Kahvaltı', None),
]


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    accounts = env['cz.platform.account'].with_context(active_test=False).search([
        ('platform', '=', 'trendyol_yemek'), ('pos_config_id', '!=', False)])
    # the POS that receives both chocolate and breakfast Trendyol orders
    configs = accounts.filtered(lambda a: a.sales_line == 'breakfast').pos_config_id
    for config in configs:
        company = config.company_id
        Journal = env['account.journal'].with_company(company)
        Method = env['pos.payment.method'].with_company(company)
        by_line = {}
        for code, name, line in DEFS:
            journal = Journal.search([('code', '=', code), ('company_id', '=', company.id)], limit=1)
            if not journal:
                journal = Journal.create({'name': name + ' Tahsilat', 'code': code,
                                          'type': 'bank', 'company_id': company.id})
            method = Method.with_context(active_test=False).search(
                [('journal_id', '=', journal.id), ('company_id', '=', company.id)], limit=1)
            if not method:
                method = Method.create({'name': name, 'journal_id': journal.id,
                                        'company_id': company.id})
            if config not in method.config_ids:
                # written from the method side: allowed while a session exists
                method.write({'config_ids': [(4, config.id)]})
            if line:
                by_line[line] = method
            _logger.info("cz_platform_orders: %s -> journal %s, method %s on %s",
                         name, journal.code, method.id, config.name)
        for acc in accounts.filtered(lambda a: a.pos_config_id == config):
            method = by_line.get(acc.sales_line)
            if method and acc.payment_method_id != method:
                acc.payment_method_id = method
