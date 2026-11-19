# -*- coding: utf-8 -*-
{
    "name": "Choco Zuma WhatsApp Reports",
    "version": "18.0.1.3.0",
    "summary": "Real-cost engine, CEO daily brief (AR) and daily marketing report (TR) by WhatsApp",
    "author": "Choco Zuma",
    "license": "LGPL-3",
    "category": "Point of Sale",
    "depends": ["point_of_sale", "pos_restaurant", "pos_hr", "mrp", "account", "mail", "whatsapp"],
    "data": [
        "security/ir.model.access.csv",
        "report/ceo_brief_report.xml",
        "views/wa_report_views.xml",
        "data/wa_report_data.xml",
        "data/wa_cron_data.xml",
    ],
    "installable": True,
    "application": False,
}
