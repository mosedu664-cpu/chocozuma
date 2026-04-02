# -*- coding: utf-8 -*-
#################################################################################
# Author      : Webkul Software Pvt. Ltd. (<https://webkul.com/>)
# Copyright(c): 2015-Present Webkul Software Pvt. Ltd.
# All Rights Reserved.
#
#
#
# This program is copyright property of the author mentioned above.
# You can`t redistribute it and/or modify it.
#
#
# You should have received a copy of the License along with this program.
# If not, see <https://store.webkul.com/license.html/>
#################################################################################
{
    "name":  "POS Print Direct : Single Click Print",
    "summary":  """The POS Print Direct: Single Click Print module simplifies the process of printing POS receipts and invoice with any printer—thermal, PDF, or image printers—directly from Odoo. It eliminates the need for downloads or extra steps, ensuring a seamless printing experience. Receipt printing is fully compatible with multiple languages, including Arabic, French, German, Spanish, Italian, Dutch, and others, enabling global businesses to print POS receipts in their preferred language. The module also supports remote printing and printing from mobile devices, tablets, Android, and iOS, providing flexibility for businesses on the go.
Keywords: Odoo Direct Print | POS Direct Print | Network Print | Thermal Print | Zebra Print | All-in-One Print | POS Receipt Printer | Pos Order Invoice Print| Invoice Print | POS Receipt and Invoice Printing  | Print Directly | Auto Print | IoTBox Free Print | Printer Connection | Print Without Downloading | POS Print Integration | Direct Print Module for POS | Receipt Printer POS | Quick Print POS | Wireless Printer for POS | Zebra Printer for POS | POS Automated Printing | Backend Invoice Print | Local Printer Integration | Direct Print Solution | Thermal Label Printing for POS | Print Custom Labels | POS Print without Pop-ups | Print from Odoo Backend | POS Print Automation | Odoo POS Print Solution | PDF Print for POS | Image Print for POS | Label Print | Report Print | طباعة إيصال POS | Impression de reçu POS | POS-Beleg-Druck | Impresión de recibo POS | Stampa ricevuta POS | Afdrukken van POS-ontvangst | Remote Printing for POS | Mobile Printing for POS | Tablet Printing for POS | Android Printing for POS | iOS Printing for POS | Print from Mobile Device | Print from Tablet | POS Print from Android | POS Print from iOS | Cloud Printing for POS | POS Mobile Receipt Print | Remote Mobile Print for POS""",
    "category":  "Point of Sale",
    "version":  "1.0.14",
    "sequence":  2,
    "author":  "Webkul Software Pvt. Ltd.",
    "license":  "Other proprietary",
    "website":  "https://store.webkul.com/odoo-pos-direct-print.html",
    "description":  """The Odoo POS Direct Print  Module is designed to enhance the printing capabilities of your POS system by offering a direct and independent solution that doesn't rely on network printers or specific print commands. Perfect for businesses that require a flexible, non-subscription-based printing option, this module ensures that all printing operations are handled efficiently, even in cases where the printer is temporarily unavailable.rect Print""",
    "live_test_url":  "https://odoodemo.webkul.in/demo_feedback?module=pos_direct_print",
    "depends":  ['point_of_sale', 'wk_odoo_direct_print'],
    "data":  [
        'views/pos_config_view.xml',
    ],
    "assets":  {
        'point_of_sale._assets_pos': [
            'pos_direct_print/static/src/app/direct_printer.js',
            'pos_direct_print/static/src/overrides/main.js',
            'pos_direct_print/static/src/overrides/navbar.xml',
            'pos_direct_print/static/src/overrides/order_receipt.xml',
            'pos_direct_print/static/src/overrides/pos_store.js',
        ],
    },
    "images":  ['static/description/Banner.gif'],
    "application":  True,
    "installable":  True,
    "auto_install":  False,
    "price":  59,
    "currency":  "USD",
    "pre_init_hook":  "pre_init_check",
    "external_dependencies": {'python': ['python-escpos']}
}
