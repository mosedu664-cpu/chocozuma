# -*- coding: utf-8 -*-
import json
from datetime import datetime, timezone

from odoo import fields, models

# Customer personal data is never stored: these keys are dropped from raw JSON.
PERSONAL_KEYS = {'customer', 'address', 'invoiceAddress', 'shipmentAddress',
                 'customerFirstName', 'customerLastName', 'customerEmail',
                 'customerPhone', 'callCenterPhone', 'pinCode', 'phone', 'email'}

STATUSES = [
    ('Created', 'Yeni (Created)'),
    ('Picking', 'Hazırlanıyor (Picking)'),
    ('Invoiced', 'Faturalandı (Invoiced)'),
    ('Shipped', 'Yolda (Shipped)'),
    ('Delivered', 'Teslim edildi (Delivered)'),
    ('Cancelled', 'İptal (Cancelled)'),
    ('UnSupplied', 'Tedarik edilemedi (UnSupplied)'),
    ('other', 'Diğer'),
]
KNOWN = {s for s, _l in STATUSES}


def _ms_to_dt(value):
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return False
    if ms <= 0:
        return False
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).replace(tzinfo=None)


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _strip_personal(obj):
    if isinstance(obj, dict):
        return {k: _strip_personal(v) for k, v in obj.items() if k not in PERSONAL_KEYS}
    if isinstance(obj, list):
        return [_strip_personal(v) for v in obj]
    return obj


class CzPlatformOrder(models.Model):
    _name = 'cz.platform.order'
    _description = 'Delivery Platform Order (raw intake)'
    _order = 'order_date desc, id desc'
    _rec_name = 'order_number'

    account_id = fields.Many2one('cz.platform.account', required=True, ondelete='cascade', index=True)
    platform = fields.Selection(related='account_id.platform', store=True)
    company_id = fields.Many2one(related='account_id.company_id', store=True)
    sales_line = fields.Selection(related='account_id.sales_line', store=True)
    package_ref = fields.Char('Package ID', required=True, index=True)
    order_number = fields.Char(index=True)
    store_ref = fields.Char('Store ID')
    status = fields.Selection(STATUSES, index=True)
    status_raw = fields.Char()
    order_date = fields.Datetime(index=True)
    modified_date = fields.Datetime()
    amount_total = fields.Float(digits=(16, 2))
    lines_total = fields.Float('Lines total', digits=(16, 2))
    payment_type = fields.Char()
    store_pickup = fields.Boolean()
    line_ids = fields.One2many('cz.platform.order.line', 'order_id')
    raw_json = fields.Text(groups='base.group_system')
    # step 2
    pos_order_id = fields.Many2one('pos.order', readonly=True, copy=False)
    state = fields.Selection([('new', 'Stored'), ('posted', 'POS order created'), ('error', 'Error')],
                             default='new', index=True)
    error = fields.Char()

    _sql_constraints = [
        ('package_account_uniq', 'unique(account_id, package_ref)',
         'This platform package is already stored.'),
    ]

    def _upsert_from_trendyol(self, account, pkg):
        """Create or refresh one package. Returns True if newly created."""
        package_ref = str(pkg.get('id') or pkg.get('packageId') or '')
        if not package_ref:
            return False
        status_raw = str(pkg.get('packageStatus') or pkg.get('status') or '')
        payment = pkg.get('payment') or {}
        line_vals = []
        lines_total = 0.0
        for line in pkg.get('lines') or []:
            items = line.get('items')
            if isinstance(items, list):
                qty = len([i for i in items if not (i or {}).get('isCancelled')])
            else:
                qty = _num(line.get('quantity') or 1)
            unit = _num(line.get('unitSellingPrice') or line.get('price'))
            names = []
            for key, prefix in (('modifierProducts', ''), ('extraIngredients', '+'),
                                ('removedIngredients', '-')):
                for m in line.get(key) or []:
                    if isinstance(m, dict) and m.get('name'):
                        names.append(prefix + str(m['name']))
            lines_total += qty * unit
            line_vals.append((0, 0, {
                'platform_product_ref': str(line.get('productId') or ''),
                'name': str(line.get('name') or line.get('productName') or '?'),
                'qty': qty,
                'price_unit': unit,
                'options': ', '.join(names) or False,
            }))
        vals = {
            'account_id': account.id,
            'package_ref': package_ref,
            'order_number': str(pkg.get('orderNumber') or pkg.get('orderCode') or pkg.get('code') or package_ref[:12]),
            'store_ref': str(pkg.get('storeId') or '') or False,
            'status': status_raw if status_raw in KNOWN else 'other',
            'status_raw': status_raw,
            'order_date': _ms_to_dt(pkg.get('packageCreationDate') or pkg.get('createdDate')),
            'modified_date': _ms_to_dt(pkg.get('packageModificationDate') or pkg.get('lastModifiedDate')),
            'amount_total': _num(pkg.get('totalPrice') or pkg.get('amount') or payment.get('amount')),
            'lines_total': lines_total,
            'payment_type': payment.get('paymentType') or False,
            'store_pickup': bool(pkg.get('storePickupSelected') or pkg.get('isStorePickup')),
            'raw_json': json.dumps(_strip_personal(pkg), ensure_ascii=False, indent=1)[:200000],
        }
        existing = self.search([('account_id', '=', account.id), ('package_ref', '=', package_ref)], limit=1)
        if existing:
            if existing.state == 'posted':
                # never touch lines of an order already turned into a POS sale
                vals.pop('raw_json', None)
                existing.write({k: v for k, v in vals.items()
                                if k in ('status', 'status_raw', 'modified_date')})
            else:
                existing.line_ids.unlink()
                vals['line_ids'] = line_vals
                existing.write(vals)
            return False
        vals['line_ids'] = line_vals
        self.create(vals)
        return True


class CzPlatformOrderLine(models.Model):
    _name = 'cz.platform.order.line'
    _description = 'Delivery Platform Order Line'

    order_id = fields.Many2one('cz.platform.order', required=True, ondelete='cascade', index=True)
    platform_product_ref = fields.Char('Platform product ID', index=True)
    name = fields.Char(required=True)
    qty = fields.Float(digits=(16, 2))
    price_unit = fields.Float(digits=(16, 2))
    subtotal = fields.Float(compute='_compute_subtotal', digits=(16, 2))
    options = fields.Char()

    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.qty * line.price_unit
