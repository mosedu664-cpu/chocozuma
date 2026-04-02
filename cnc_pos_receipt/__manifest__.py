# -*- coding: utf-8 -*-
{
    'name': 'CNC POS Receipt',
    'summary': 'Custom receipt layout and formatting for Point of Sale',

    'description': """
    Customizes the Point of Sale receipt layout.
    Includes a redesigned header and order receipt template,
        """,
    'author': "Codes 'n Colors",
    'website': "https://codesncolors.com/",
    'depends': ['point_of_sale'],
    'category': 'Uncategorized',
    'version': '0.1',
    "assets": {
        "point_of_sale._assets_pos": [
            "cnc_pos_receipt/static/src/js/pos_receipt.js",
            "cnc_pos_receipt/static/src/xml/Screens/ReceiptScreen/OrderReceipt.xml",
            "cnc_pos_receipt/static/src/xml/Screens/ReceiptScreen/ReceiptHeader.xml",
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
