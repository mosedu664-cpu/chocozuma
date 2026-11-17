# -*- coding: utf-8 -*-
"""Correction categories become 'cash difference' so they stop inflating the day's expenses:
FARK (shortage / surplus the cashier had typed as an expense) and HATA (entry-error corrections)."""


def migrate(cr, version):
    cr.execute("""
        UPDATE cz_cash_category
           SET kind = 'difference', pos_available = FALSE, safe_pos_available = FALSE
         WHERE code IN ('FARK', 'HATA') AND account_id IS NOT NULL
    """)
    cr.execute("UPDATE cz_cash_day_line l SET kind = c.kind FROM cz_cash_category c WHERE c.id = l.category_id AND l.kind != c.kind")
