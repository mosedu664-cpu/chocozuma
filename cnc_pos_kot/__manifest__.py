{
    "name": "POS Kitchen Order Ticket",
    "author": "Codes 'n colors",
    "category": "Point of Sale",
    "summary": """This module is responsible for printing the Kitchen Order Ticket (KOT) 
                    once the order is transferred to the kitchen.""",
    "description": """CNC POS Kitchen Order Ticket Printing""",
    "version": "18.1.0",
    "depends": ["point_of_sale", "pos_restaurant"],
    "application": True,
    "data": [
        'views/pos_config.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'cnc_pos_kot/static/src/js/pos_order.js',
            'cnc_pos_kot/static/src/xml/kot_receipt.xml',
            'cnc_pos_kot/static/src/js/kot_receipt.js',
            'cnc_pos_kot/static/src/js/actionpad_widget.js'

        ],
    },
    "auto_install": False,
    "installable": True,
    "images": ["static/description/icon.png", ],
    "license": "OPL-1",
}
