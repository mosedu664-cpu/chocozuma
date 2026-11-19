# -*- coding: utf-8 -*-
{
    "name": "Choco Zuma WhatsApp Reports",
    "version": "18.0.1.1.0",
    "summary": "Real-cost engine and CEO daily brief (slice 2: direction-safe preview + PDF, no sending)",
    "author": "Choco Zuma",
    "license": "LGPL-3",
    "category": "Point of Sale",
    "depends": ["point_of_sale", "pos_restaurant", "pos_hr", "mrp", "account"],
    "data": [
        "security/ir.model.access.csv",
        "report/ceo_brief_report.xml",
        "views/wa_report_views.xml",
        "data/wa_report_data.xml",
    ],
    "installable": True,
    "application": False,
}
