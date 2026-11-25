# -*- coding: utf-8 -*-
{
    "name": "Choco Zuma — Kakao Hazinesi (Loyalty)",
    "version": "18.0.0.5.2",
    "summary": "One loyalty wallet for all Choco Zuma branches: receipt code → WhatsApp → bean; gifts at 4 and 8 visits",
    "description": """
Kakao Hazinesi
==============
Increment 1 (server side only, no POS changes):

* One company-neutral wallet per phone number (cz.loyalty.member + ledger),
  shared by Kayaşehir (TONALLI) and Metrokent (Mayapan).
* Every paid POS order gets a one-time code. The guest sends it on WhatsApp,
  the system adds one bean. At 4 beans a small gift code (Şefin İkramı), at 8 the big one (Hazine Tabağı).
* Inbound WhatsApp messages are queued (never raise inside the webhook) and
  processed by a cron with retries; every decision is logged.
* Mode: off / test (only whitelisted phones get credits and replies) / live.
* "Simulate message" wizard: test the whole flow on staging without Meta.

Increment 2 adds the receipt QR and the cashier scan in the POS.
    """,
    "author": "Choco Zuma Yönetim",
    "license": "LGPL-3",
    "category": "Sales/Point of Sale",
    "depends": ["point_of_sale", "pos_restaurant", "whatsapp", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "data/config_data.xml",
        "data/cron_data.xml",
        "wizard/simulate_views.xml",
        "views/loyalty_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "cz_loyalty/static/src/receipt/*",
            "cz_loyalty/static/src/redeem/*",
        ],
    },
    "installable": True,
    "application": False,
}
