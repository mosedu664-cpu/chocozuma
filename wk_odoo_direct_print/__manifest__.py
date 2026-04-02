# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2025-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#    See LICENSE file for full copyright and licensing details.
#################################################################################

{
    "name"          :  "Print Direct: Direct Printing from Desktop, Mobile, Android & iOS",
    "summary"       :  """Odoo Print Direct makes printing easy by connecting Odoo directly to different types of printers. Businesses can print invoices, reports, labels, and documents instantly without downloading files or using extra hardware.


The module supports ZPL printers, ESC/POS printers, PDF printing, and WiFi or Bluetooth printers. With Odoo Print Direct, businesses can print quickly and improve daily operations in offices, warehouses, and logistics environments.
""",
    "category"      :  "Extra Tools",
    "version"       :  "2.0.25",
    "sequence"      :   1,
    "author"        :  "Webkul Software Pvt. Ltd.",
    "license"       :  "Other proprietary",
    "website"       :  "https://store.webkul.com/odoo-direct-print.html",
    "description"   :  """Odoo Print Direct makes printing easy. It removes extra steps in the printing process. Users do not need to download files before printing. They can send print commands directly from Odoo to the printer.

The module works with many types of printers. It supports ZPL printers for barcode and shipping labels. It also supports ESC/POS printers and PDF printers for documents. Businesses can add many printers and link them to reports or workflows.

Odoo Print Direct also works with WiFi and Bluetooth printers. This allows printing in offices, warehouses, and retail stores. Users can also print from Android and iOS devices connected to supported printers.

With fewer steps, printing becomes faster and easier. Odoo Print Direct helps teams work better and manage document printing smoothly.
""",
    "live_test_url" :  "https://odoodemo.webkul.in/demo_feedback?module=wk_odoo_direct_print",
    "depends"       :  ['account', 'sale', 'sale_management', 'mail', 'stock','purchase','base_automation'],
    "data"          :  [
        'security/ir.model.access.csv',
        'views/res_config.xml',
        'report/receipt_template.xml',
        'data/host_sys_info_cron.xml',
        'data/clean_print_jobs_cron.xml',
        'data/renotify_queued_jobs.xml',
        'data/default_printer.xml',
        'data/report_triger_rule.xml',
        'data/autoprint_rule_data.xml',
        'views/printer.xml',
        'views/hostmachine.xml',
        'views/print_jobs.xml',
        'views/default_printer.xml',
        'report/qweb_report.xml',
        'views/ir_actions_report.xml',
        'views/autoprint_rule.xml',
        'views/print_job_source.xml',
        'views/attachment_automation.xml',
        'views/shipping_label_automation.xml',
        'views/ir_actions_server.xml',
        'wizard/printer_test.xml',
    ],
    "demo":[
    ],
    'assets'            :{
                            'web.assets_backend':[
                                'wk_odoo_direct_print/static/src/automation_rule/*',
                                'wk_odoo_direct_print/static/src/printer/*',
                                'wk_odoo_direct_print/static/src/js/*',
                                'wk_odoo_direct_print/static/src/attachment/*',
                                'wk_odoo_direct_print/static/src/printer_icon/*'
                            ],
                        },

    "images":  ['static/description/Banner.gif'],
    "application"   :  True,
    "installable"   :  True,
    "price"         :  149,
    "currency"      :  "USD",
    "pre_init_hook" :  "pre_init_check",
}
