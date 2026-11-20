# -*- coding: utf-8 -*-
{
    "name": "Choco Zuma WhatsApp Reports",
    "version": "18.0.1.5.2",
    "summary": "Real-cost engine, CEO daily brief (AR) and daily marketing report (TR) and kitchen/depot stock report (TR), yesterday orders (TR) by WhatsApp",
    "author": "Choco Zuma",
    "license": "LGPL-3",
    "category": "Point of Sale",
    "depends": ["point_of_sale", "pos_restaurant", "pos_hr", "mrp", "account", "mail", "whatsapp", "cz_inventory_dashboard"],
    "data": [
        "security/ir.model.access.csv",
        "report/ceo_brief_report.xml",
        "views/wa_report_views.xml",
        "data/wa_report_data.xml",
        "data/wa_cron_data.xml",
        "data/wa_report_setup.xml",
    ],
    "installable": True,
    "application": False,
}
