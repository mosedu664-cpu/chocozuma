# -*- coding: utf-8 -*-
"""Offer the usual safe payments in the new POS 'Küçük Kasa' screen."""


def migrate(cr, version):
    cr.execute("""
        UPDATE cz_cash_category
           SET safe_pos_available = TRUE
         WHERE active
           AND direction IN ('out', 'both')
           AND (kind IN ('expense', 'salary', 'advance') OR code = 'SEF')
    """)
