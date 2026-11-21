# -*- coding: utf-8 -*-
"""Yemeksepeti: order intake from the partner-portal export (orderDetails.xlsx).

Until the Delivery Hero API is available, Yemeksepeti orders reach Odoo by
uploading the portal's "Order details" export. The same posting engine as
Trendyol is used (POS sale, stock, payment method per platform), with three
differences:

* Products come from the "Order items" text ("1 Special Waffle [1 Oreo]"),
  mapped by name; prices from the mapping (last_price) or the product price.
* The restaurant-funded discount/voucher is spread over the lines, so the
  sale equals what the restaurant really earns.
* Before posting, each order is matched against what the cashier already
  typed (one receipt per order, or one receipt per day). Matched orders are
  never posted again; unclear days go to "Needs review".

Back-dated orders are never sent to the kitchen display or the cashier toast.
"""
import base64
import io
import json
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

from odoo import api, fields, models
from odoo.exceptions import UserError

_M = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
TR_OFFSET = timedelta(hours=3)        # Istanbul, no DST
BUSINESS_DAY_SHIFT = timedelta(hours=5)  # orders/entries until 05:00 belong to the previous day
STATUS_MAP = {'picked up': 'Delivered', 'delivered': 'Delivered', 'cancelled': 'Cancelled',
              'canceled': 'Cancelled', 'rejected': 'Cancelled'}


# ----------------------------------------------------------------------
def read_order_export(data):
    """Rows of the portal export as dicts (header = 2nd row). The portal's
    xlsx has a stylesheet openpyxl rejects, so the sheet XML is read directly."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        shared = []
        if 'xl/sharedStrings.xml' in z.namelist():
            for si in ET.fromstring(z.read('xl/sharedStrings.xml')).iter(_M + 'si'):
                shared.append(''.join(t.text or '' for t in si.iter(_M + 't')))
        sheet = next(n for n in z.namelist() if n.startswith('xl/worksheets/sheet'))
        rows = []
        for row in ET.fromstring(z.read(sheet)).iter(_M + 'row'):
            vals = {}
            for c in row.findall(_M + 'c'):
                col = re.sub(r'\d', '', c.get('r') or '')
                v, is_ = c.find(_M + 'v'), c.find(_M + 'is')
                if c.get('t') == 's' and v is not None:
                    val = shared[int(v.text)]
                elif is_ is not None:
                    val = ''.join(t.text or '' for t in is_.iter(_M + 't'))
                else:
                    val = v.text if v is not None else ''
                vals[col] = val
            rows.append(vals)
    except Exception as e:  # noqa: BLE001
        raise UserError("Dosya okunamadı (Yemeksepeti 'Order details' xlsx olmalı): %s" % e)
    header_idx = next((i for i, r in enumerate(rows[:5]) if 'Order ID' in r.values()), None)
    if header_idx is None:
        raise UserError("Dosyada 'Order ID' sütunu bulunamadı.")
    header = rows[header_idx]
    return [{header[k]: v for k, v in r.items() if k in header} for r in rows[header_idx + 1:]
            if any(r.values())]


def _split_top(text):
    out, depth, cur = [], 0, ''
    for ch in text or '':
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
        if ch == ',' and depth == 0:
            out.append(cur.strip())
            cur = ''
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def parse_items(text):
    """'1 Special Waffle [1 Oreo, 1 Bisküvi], 2 Su (33 cl.)' ->
    [(1, 'Special Waffle', [(1, 'Oreo'), (1, 'Bisküvi')]), (2, 'Su (33 cl.)', [])]"""
    res = []
    for it in _split_top(text):
        m = re.match(r'^(\d+)\s+(.+?)(?:\s*\[(.*)\])?$', it)
        if not m:
            res.append((1, it.strip(), []))
            continue
        extras = []
        for e in _split_top(m.group(3) or ''):
            em = re.match(r'^(\d+)\s+(.+)$', e)
            extras.append((int(em.group(1)), em.group(2).strip()) if em else (1, e.strip()))
        res.append((int(m.group(1)), m.group(2).strip(), extras))
    return res


def norm(name):
    return re.sub(r'\s+', ' ', (name or '').strip()).lower()


def _f(row, key):
    try:
        return float(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def _local_to_utc(text):
    try:
        return datetime.strptime(text.strip()[:16], '%Y-%m-%d %H:%M') - TR_OFFSET
    except (AttributeError, ValueError):
        return False


def business_day(dt_utc):
    return (dt_utc + TR_OFFSET - BUSINESS_DAY_SHIFT).date()


# ----------------------------------------------------------------------
class CzPlatformAccountYs(models.Model):
    _inherit = 'cz.platform.account'

    manual_method_ids = fields.Many2many(
        'pos.payment.method', 'cz_platform_account_manual_method_rel', 'account_id', 'method_id',
        string='Cashier payment methods',
        help="Methods the cashier uses when typing these orders by hand (e.g. Online Payment, "
             "Yemeksepeti Çikolata). Used to find orders already entered, so they are never posted twice.")
    manual_match_partner = fields.Boolean(
        'Manual entries carry the POS customer',
        help="Only count cashier entries whose customer is this account's POS customer "
             "(Kayaşehir: *YEMEKSEPETI).")


class CzPlatformOrderYs(models.Model):
    _inherit = 'cz.platform.order'

    manual_pos_order_id = fields.Many2one(
        'pos.order', string='Typed by cashier', readonly=True, copy=False,
        help="Cashier receipt that already contains this order (never posted again).")
    backfill = fields.Boolean(readonly=True, help="Imported after the fact: no kitchen display, no toast.")

    # --- intake -----------------------------------------------------------
    def _upsert_from_ys_row(self, account, row):
        ref = (row.get('Order ID') or '').strip()
        if not ref:
            return None
        subtotal = _f(row, 'Subtotal')
        vendor_disc = _f(row, 'Discount Funded by you') + _f(row, 'Voucher Funded by you')
        status_raw = (row.get('Order status') or '').strip()
        pay = (row.get('Payment type') or '').strip()
        keep = ('Order ID', 'Store ID', 'Restaurant name', 'Delivery type', 'Payment type',
                'Payment method', 'Order status', 'Order received at', 'Subtotal',
                'Discount Funded by you', 'Voucher Funded by you', 'Total discount',
                'Total voucher', 'Order items')
        vals = {
            'account_id': account.id,
            'package_ref': ref,
            'order_number': ref,
            'order_code': ref.split('-')[-1],
            'store_ref': row.get('Store ID') or False,
            'status': STATUS_MAP.get(status_raw.lower(), 'other'),
            'status_raw': status_raw,
            'order_date': _local_to_utc(row.get('Order received at')),
            'amount_total': round(subtotal - vendor_disc, 2),
            'lines_total': subtotal,
            'payment_type': 'ONLINE' if pay.lower() == 'online' else (pay or 'UNKNOWN'),
            'raw_json': json.dumps({k: row.get(k) for k in keep}, ensure_ascii=False),
            'backfill': True,
        }
        existing = self.search([('account_id', '=', account.id), ('package_ref', '=', ref)], limit=1)
        if existing:
            if existing.state in ('new', 'review', 'needs_mapping', 'error'):
                existing.write(vals)
            return existing
        return self.create(vals)

    # --- lines ------------------------------------------------------------
    def _cz_ys_build_lines(self, config):
        self.ensure_one()
        maps = self.env['cz.platform.product.map'].sudo().search([('account_id', '=', self.account_id.id)])
        by_key = {(m.kind, norm(m.platform_ref)): m for m in maps}
        row = json.loads(self.sudo().raw_json or '{}')
        lines, missing, priced = [], [], []

        def price_of(m):
            return m.last_price if m.last_price else m.product_id.lst_price

        for qty, name, extras in parse_items(row.get('Order items')):
            m = by_key.get(('product', norm(name)))
            if not m:
                missing.append(name)
                continue
            price = price_of(m)
            if m.product_id.type == 'combo':
                combo = self._cz_combo_lines(m, qty, price, False)
                if combo is None:
                    missing.append('%s: kombo seçimleri eksik' % name)
                    continue
                lines += combo
                priced += [c for c in combo[0]['children'] if c['price']]
            else:
                line = {'product': m.product_id, 'qty': qty, 'price': price, 'note': False}
                lines.append(line)
                priced.append(line)
            for eqty, ename in extras:
                em = by_key.get(('extra', norm(ename)))
                if not em:
                    missing.append('+' + ename)
                    continue
                eprice = price_of(em)
                if not em.product_id or not eprice:
                    continue  # free option ("Bol çilekli olsun") -> nothing to post
                line = {'product': em.product_id, 'qty': eqty, 'price': eprice, 'note': False}
                lines.append(line)
                priced.append(line)
        if missing:
            return [], missing

        currency = config.currency_id
        gross = sum(l['price'] * l['qty'] for l in priced)
        subtotal = self.lines_total
        if currency.compare_amounts(gross, subtotal) != 0:
            return [], ['Fiyat farkı: eşleştirme %.2f / Yemeksepeti %.2f (eşleştirmedeki fiyatı düzeltin)'
                        % (gross, subtotal)]
        # spread the restaurant-funded discount over the lines
        target = self.amount_total
        if priced and currency.compare_amounts(target, gross) != 0:
            factor = target / gross if gross else 0
            for l in priced:
                l['price'] = currency.round(l['price'] * factor)
            diff = currency.round(target - sum(l['price'] * l['qty'] for l in priced))
            if diff:
                one = next((l for l in sorted(priced, key=lambda x: -x['price']) if l['qty'] == 1), None)
                if one:
                    one['price'] = currency.round(one['price'] + diff)
        return lines, []

    # --- matching with cashier entries -------------------------------------
    @api.model
    def _cz_ys_match_manual(self, orders):
        """Mark orders already typed by the cashier. orders: YS orders of ONE POS."""
        todo = orders.filtered(lambda o: o.state in ('new', 'review') and not o.pos_order_id
                               and o.order_date)
        if not todo:
            return
        config = todo[0].account_id.pos_config_id
        accounts = todo.account_id
        methods = accounts.manual_method_ids
        if not methods:
            return
        partner = accounts.filtered('manual_match_partner').partner_id[:1]
        posted_ids = self.search([('pos_order_id', '!=', False)]).pos_order_id.ids
        linked_ids = self.search([('manual_pos_order_id', '!=', False)]).manual_pos_order_id.ids
        start = min(todo.mapped('order_date')) - timedelta(days=1)
        end = max(todo.mapped('order_date')) + timedelta(days=6)
        domain = [('config_id', '=', config.id), ('state', 'in', ('paid', 'done', 'invoiced')),
                  ('date_order', '>=', start), ('date_order', '<=', end),
                  ('payment_ids.payment_method_id', 'in', methods.ids),
                  ('id', 'not in', posted_ids + linked_ids), ('amount_total', '>', 0)]
        if partner:
            domain.append(('partner_id', '=', partner.id))
        pool = self.env['pos.order'].sudo().with_company(config.company_id).search(domain, order='date_order')
        pool = pool.filtered(lambda p: not p.refund_orders_count)
        used = set()

        def candidates(o):
            row = json.loads(o.sudo().raw_json or '{}')
            sub = _f(row, 'Subtotal')
            return {round(o.amount_total, 2), round(sub, 2),
                    round(sub - _f(row, 'Total discount') - _f(row, 'Total voucher'), 2)}

        # 1. one receipt per order
        for o in todo.sorted('order_date'):
            amounts = candidates(o)
            best, gap = None, None
            for p in pool:
                if p.id in used:
                    continue
                dt = (p.date_order - o.order_date).total_seconds()
                if dt < -2 * 3600 or dt > 5 * 86400:
                    continue
                if not any(abs(a - p.amount_total) < 0.02 for a in amounts):
                    continue
                if gap is None or abs(dt) < gap:
                    best, gap = p, abs(dt)
            if best:
                used.add(best.id)
                o.write({'state': 'skipped', 'manual_pos_order_id': best.id,
                         'error': 'Kasada elle girilmiş: %s' % best.name})
        # 2. one receipt per day (Metrokent style)
        left = todo.filtered(lambda o: o.state != 'skipped')
        by_day = defaultdict(lambda: self.browse())
        for o in left:
            by_day[business_day(o.order_date)] |= o
        manual_by_day = defaultdict(list)
        for p in pool:
            if p.id not in used:
                manual_by_day[business_day(p.date_order)].append(p)
        for day, day_orders in by_day.items():
            manual = manual_by_day.get(day) or []
            if not manual:
                continue
            ys_sum = sum(day_orders.mapped('amount_total'))
            man_sum = sum(p.amount_total for p in manual)
            if abs(ys_sum - man_sum) < 1:
                for o in day_orders:
                    o.write({'state': 'skipped', 'manual_pos_order_id': manual[0].id,
                             'error': 'Günlük toplu girişte var: %s' % ', '.join(p.name for p in manual)})
                used.update(p.id for p in manual)
            else:
                day_orders.write({'state': 'review', 'error': (
                    'Aynı gün eşleşmeyen kasa girişi var (%s = %.2f ₺, Yemeksepeti %.2f ₺): '
                    'çift kayıt olmasın diye otomatik girilmedi.' % (
                        ', '.join(p.name for p in manual), man_sum, ys_sum))[:250]})

    def action_ys_mark_reviewed(self):
        """Reviewed by a manager: not in the till yet -> post it."""
        todo = self.filtered(lambda o: o.state == 'review' and o.platform == 'yemeksepeti'
                             and not o.pos_order_id)
        todo.write({'state': 'new', 'error': False})
        for o in todo.sorted('order_date'):
            with self.env.cr.savepoint():
                o.with_context(cz_backfill=True)._cz_post_to_pos()


class CzPlatformReportImport(models.TransientModel):
    _name = 'cz.platform.report.import'
    _description = 'Yemeksepeti order export import'

    file = fields.Binary('Yemeksepeti Order details (xlsx)', required=True)
    filename = fields.Char()
    post_now = fields.Boolean('Post missing orders now', default=True,
                              help="Off: only store and match (nothing posted).")
    result = fields.Text(readonly=True)
    order_ids = fields.Many2many('cz.platform.order', readonly=True)

    def action_import(self):
        self.ensure_one()
        rows = read_order_export(base64.b64decode(self.file))
        Account = self.env['cz.platform.account'].sudo()
        Order = self.env['cz.platform.order'].sudo()
        accounts = Account.search([('platform', '=', 'yemeksepeti')])
        by_store = {(a.store_ref or '').strip(): a for a in accounts if a.store_ref}
        stats = defaultdict(int)
        unknown = set()
        orders = Order.browse()
        for row in rows:
            acc = by_store.get((row.get('Store ID') or '').strip())
            if not acc:
                unknown.add(row.get('Store ID') or '?')
                continue
            o = Order._upsert_from_ys_row(acc, row)
            if o:
                orders |= o
        # cancelled orders are never posted
        orders.filtered(lambda o: o.status == 'Cancelled' and not o.pos_order_id
                        and o.state in ('new', 'review')).write({'state': 'cancelled'})
        for config in orders.account_id.pos_config_id:
            Order._cz_ys_match_manual(orders.filtered(lambda o: o.account_id.pos_config_id == config))
        if self.post_now:
            for o in orders.filtered(lambda o: o.state in ('new', 'needs_mapping', 'waiting_session')
                                     and not o.pos_order_id).sorted('order_date'):
                try:
                    with self.env.cr.savepoint():
                        o.with_context(cz_backfill=True)._cz_post_to_pos()
                except Exception as e:  # noqa: BLE001
                    o.write({'state': 'error', 'error': str(e)[:250]})
        for o in orders:
            stats[o.state] += 1
        labels = dict(Order._fields['state'].selection)
        lines = ['Dosyadaki sipariş: %d' % len(rows)]
        lines += ['%s: %d' % (labels.get(k, k), v) for k, v in sorted(stats.items())]
        posted = orders.filtered(lambda o: o.state == 'posted' and o.backfill)
        lines.append('Kasaya girilen tutar: %.2f ₺' % sum(posted.mapped('amount_total')))
        if unknown:
            lines.append('Hesabı olmayan mağaza kodları: %s' % ', '.join(sorted(unknown)))
        self.write({'result': '\n'.join(lines), 'order_ids': [(6, 0, orders.ids)]})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new', 'name': 'Yemeksepeti import'}

    def action_open_orders(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'cz.platform.order',
                'name': 'Yemeksepeti import', 'view_mode': 'list,form',
                'domain': [('id', 'in', self.order_ids.ids)]}
