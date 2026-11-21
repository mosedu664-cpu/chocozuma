# -*- coding: utf-8 -*-
"""Turn stored platform orders into POS sales (and refunds).

Rules (decided with Mo, 19/11/2026):
* Only orders created after the account's go-live time are posted; older
  ones were typed by the cashier and are marked 'skipped'.
* A POS order is created as soon as the package exists (Created/Picking/...):
  no table, partner *TRENDYOL, the account's payment method (Online Payment),
  reference "TRENDYOL <order number>". It is sent to the branch kitchen
  display if one is linked to the POS. Kitchen printers are NOT used (Sepet
  Takip keeps printing exactly as today).
* Cancelled/UnSupplied after posting -> automatic full refund.
* Unknown product -> 'needs_mapping', no open session -> 'waiting_session';
  both are retried by the cron, nothing is ever dropped.
* Idempotent: the POS order uuid is derived from the package id, so the same
  package can never create two sales.
"""
import json
import logging
import uuid

import psycopg2

from odoo import fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)

POSTABLE = ('Created', 'Picking', 'Invoiced', 'Shipped', 'Delivered')
CANCELLED = ('Cancelled', 'UnSupplied')


# Trendyol paymentType values that mean the platform collected the money.
ONLINE_PAYMENT_TYPES = ('PAY_WITH_CARD', 'PAY_WITH_MEAL_CARD_ONLINE', 'ONLINE')

class CzPlatformOrderPos(models.Model):
    _inherit = 'cz.platform.order'

    # ------------------------------------------------------------------
    def _cz_uuid(self):
        self.ensure_one()
        acc = self.account_id.sudo()
        return str(uuid.uuid5(uuid.NAMESPACE_URL, 'cz-platform-order:%s:%s:%s' % (
            acc.platform, (acc.supplier_ref or '').strip(), self.package_ref)))

    def _cz_label(self):
        return 'YEMEKSEPETI' if self.platform == 'yemeksepeti' else 'TRENDYOL'

    def _cz_ref(self):
        self.ensure_one()
        return '%s %s' % (self._cz_label(), self.order_number or self.package_ref[:12])

    # ------------------------------------------------------------------
    def _cz_lock_open_session(self, config):
        """Return the open session, row-locked so it cannot be closed while
        we add an order to it; None if closed/closing or being closed now."""
        session = config.current_session_id
        if not session or session.state != 'opened':
            return None
        try:
            with self.env.cr.savepoint(flush=False):
                self.env.cr.execute(
                    "SELECT id FROM pos_session WHERE id = %s AND state = 'opened' "
                    "FOR NO KEY UPDATE NOWAIT", (session.id,))
                if not self.env.cr.fetchone():
                    return None
        except (psycopg2.errors.LockNotAvailable, psycopg2.errors.SerializationFailure):
            return None
        return session

    def _cz_build_lines(self, config):
        """Return (lines, missing): lines = list of dicts ready for POS."""
        self.ensure_one()
        if self.platform == 'yemeksepeti':
            return self._cz_ys_build_lines(config)
        account = self.account_id
        Map = self.env['cz.platform.product.map'].sudo()
        maps = Map.search([('account_id', '=', account.id)])
        by_key = {(m.kind, m.platform_ref): m for m in maps}
        pkg = json.loads(self.sudo().raw_json or '{}')
        lines, missing = [], []

        for pl in pkg.get('lines') or []:
            items = pl.get('items')
            if isinstance(items, list):
                qty = len([i for i in items if not (i or {}).get('isCancelled')])
            else:
                qty = float(pl.get('quantity') or 1)
            if qty <= 0:
                continue
            ref = str(pl.get('productId') or '')
            m = by_key.get(('product', ref))
            if not m:
                missing.append('%s (%s)' % (pl.get('name'), ref))
                continue
            m.last_price = float(pl.get('price') or 0.0)
            base_price = float(pl.get('price') or pl.get('unitSellingPrice') or 0.0)
            removed = ', '.join('-' + str(r.get('name', '')).strip() for r in pl.get('removedIngredients') or [])
            if m.product_id.type == 'combo':
                if pl.get('modifierProducts'):
                    missing.append('%s: müşteri seçimi (modifier) eşleştirilmedi' % pl.get('name'))
                    continue
                combo_lines = self._cz_combo_lines(m, qty, base_price, removed)
                if combo_lines is None:
                    missing.append('%s: kombo seçimleri eksik' % pl.get('name'))
                    continue
                lines += combo_lines
            else:
                lines.append({'product': m.product_id, 'qty': qty, 'price': base_price,
                              'note': removed or False})
            # paid add-ons: extraIngredients (id) and, on simple products,
            # modifierProducts (productId, e.g. "Ekstra Sütlü Çikolata [50 gr]")
            addons = [(str(ex.get('id')), ex) for ex in pl.get('extraIngredients') or []]
            if m.product_id.type != 'combo':
                for mod in pl.get('modifierProducts') or []:
                    addons.append((str(mod.get('productId')), mod))
                    addons += [(str(ex.get('id')), ex) for ex in mod.get('extraIngredients') or []]
                    if mod.get('modifierProducts'):
                        missing.append('%s: iç içe seçim (modifier) desteklenmiyor' % mod.get('name'))
            for ref_x, ex in addons:
                em = by_key.get(('extra', ref_x))
                if not em:
                    missing.append('+%s (%s)' % (ex.get('name'), ref_x))
                    continue
                lines.append({'product': em.product_id, 'qty': qty,
                              'price': float(ex.get('price') or 0.0), 'note': False})
        return lines, missing

    def _cz_combo_lines(self, m, qty, price, note):
        """Parent combo line (0) + one child per combo step, like the cashier does."""
        parent = {'product': m.product_id, 'qty': qty, 'price': 0.0, 'note': note or False,
                  'children': []}
        choices = list(m.combo_choice_ids)
        children = []
        for combo in m.product_id.product_tmpl_id.combo_ids.sorted('id'):
            items = combo.combo_item_ids
            if len(items) == 1:
                item = items
            else:
                item = next((i for i in items if i.product_id in choices), None)
                if not item:
                    return None  # never guess a sauce: ask for mapping
                choices.remove(item.product_id)
            children.append({'product': item.product_id, 'qty': qty,
                             'price': item.extra_price, 'combo_item': item})
        # the platform price is the truth: put any difference on the priced step
        total = sum(c['price'] for c in children)
        if children and float_compare(total, price, 2) != 0:
            main = max(children, key=lambda c: c['price'])
            main['price'] += price - total
        parent['children'] = children
        return [parent]

    # ------------------------------------------------------------------
    def _cz_line_vals(self, line, config, fpos):
        product = line['product']
        # A branch (e.g. Metrokent under Mayapan) uses its parent company's taxes:
        # same rule as the POS itself (closest company in the branch chain).
        taxes = product.taxes_id._filter_taxes_by_company(config.company_id)
        if not taxes and line['price']:
            raise UserError("Ürünün %s şirketi için KDV'si yok: %s" % (
                config.company_id.name, product.display_name))
        taxes_fp = fpos.map_tax(taxes) if fpos else taxes
        res = taxes_fp.compute_all(line['price'], config.currency_id, line['qty'], product=product)
        vals = {
            'uuid': str(uuid.uuid4()),
            'product_id': product.id,
            'full_product_name': product.with_context(display_default_code=False).display_name,
            'qty': line['qty'],
            'price_unit': line['price'],
            'discount': 0.0,
            'tax_ids': [(6, 0, taxes.ids)],
            'price_subtotal': res['total_excluded'],
            'price_subtotal_incl': res['total_included'],
        }
        if line.get('note'):
            vals['note'] = line['note']           # kitchen / preparation note
            vals['customer_note'] = line['note']  # receipt note
        if line.get('combo_item'):
            vals['combo_item_id'] = line['combo_item'].id
        return vals, res['total_included'] - res['total_excluded']

    def _cz_post_to_pos(self):
        """Create the POS sale for this platform order. Returns True if posted."""
        self.ensure_one()
        account = self.account_id
        config = account.pos_config_id
        if not config:
            self.write({'state': 'error', 'error': 'Platform account has no Branch / POS.'})
            return False
        Order = self.env['pos.order'].sudo().with_company(config.company_id)
        existing = Order.search([('uuid', '=', self._cz_uuid())], limit=1)
        if existing:
            self.write({'state': 'posted', 'pos_order_id': existing.id, 'error': False})
            return True
        if (self.payment_type or '').upper() not in ONLINE_PAYMENT_TYPES:
            # Platform orders are online-paid only. A pay-at-door order may have
            # been collected in the shop: never post it as online payment.
            self.write({'state': 'review',
                        'error': 'Kapıda ödeme (%s): otomatik girilmedi, kasada elle girin.' % (self.payment_type or '?')})
            return False
        session = self._cz_lock_open_session(config)
        if not session:
            self.write({'state': 'waiting_session', 'error': 'POS oturumu açık değil (veya kapanıyor).'})
            return False
        lines, missing = self._cz_build_lines(config)
        if missing:
            self.write({'state': 'needs_mapping', 'error': 'Eşleşmeyen: ' + ', '.join(missing)})
            return False
        if not lines:
            self.write({'state': 'review', 'error': 'No line to post.'})
            return False

        fpos = config.default_fiscal_position_id
        line_cmds, children_by_parent, amount_tax, amount_total = [], {}, 0.0, 0.0
        for line in lines:
            vals, tax = self._cz_line_vals(line, config, fpos)
            line_cmds.append((0, 0, vals))
            amount_tax += tax
            amount_total += vals['price_subtotal_incl']
            for child in line.get('children') or []:
                cvals, ctax = self._cz_line_vals(child, config, fpos)
                line_cmds.append((0, 0, cvals))
                children_by_parent.setdefault(vals['uuid'], []).append(cvals['uuid'])
                amount_tax += ctax
                amount_total += cvals['price_subtotal_incl']

        currency = config.currency_id
        amount_tax = currency.round(amount_tax)
        amount_total = currency.round(amount_total)
        if float_compare(amount_total, self.amount_total, precision_rounding=currency.rounding) != 0:
            self.write({'state': 'review',
                        'error': 'Tutar farkı: Odoo %.2f / %s %.2f' % (amount_total, self._cz_label().title(), self.amount_total)})
            return False

        method = account.payment_method_id
        if method not in config.payment_method_ids:
            self.write({'state': 'error', 'error': 'Payment method %s is not on POS %s.' % (method.name, config.name)})
            return False

        label = 'TRENDYOL GO' if self.platform != 'yemeksepeti' else 'YEMEKSEPETI'
        note = '%s | %s | Sipariş %s' % (label, self.order_code or '-', self.order_number or self.package_ref[:12])
        if self.customer_note:
            note += '\n' + self.customer_note
        order_vals = {
            'uuid': self._cz_uuid(),
            'name': self._cz_ref(),
            'session_id': session.id,
            'company_id': config.company_id.id,
            'partner_id': account.partner_id.id or False,
            'user_id': session.user_id.id,
            'date_order': fields.Datetime.to_string(self.order_date or fields.Datetime.now()),
            'lines': line_cmds,
            'payment_ids': [(0, 0, {
                'payment_method_id': method.id,
                'amount': amount_total,
                'payment_date': fields.Datetime.to_string(fields.Datetime.now()),
                'name': self._cz_ref(),
            })],
            'amount_tax': amount_tax,
            'amount_total': amount_total,
            'amount_paid': amount_total,
            'amount_return': 0.0,
            'state': 'paid',
            'to_invoice': False,
            'general_note': note,
            # header of the kitchen-display card and name in the orders list
            'floating_order_name': '%s | %s' % (label, self.order_code or (self.order_number or '')[-5:]),
        }
        Order.with_context(cz_platform_post=True, preparation=False).sync_from_ui([order_vals])
        pos_order = Order.search([('uuid', '=', self._cz_uuid())], limit=1)
        if not pos_order or pos_order.state not in ('paid', 'done', 'invoiced'):
            # roll back (savepoint in _cz_process): never leave a draft order in the till
            raise UserError("POS siparişi ödenmiş duruma geçmedi (%s)." % (pos_order.state if pos_order else 'yok'))
        # link combo children to their parent line, exactly like a cashier combo
        for parent_uuid, child_uuids in children_by_parent.items():
            parent = pos_order.lines.filtered(lambda l: l.uuid == parent_uuid)
            kids = pos_order.lines.filtered(lambda l: l.uuid in child_uuids)
            if parent and kids:
                kids.write({'combo_parent_id': parent.id})
        self.write({'state': 'posted', 'pos_order_id': pos_order.id, 'error': False})
        if not (self.env.context.get('cz_backfill') or self.backfill):
            # back-dated imports never reach the kitchen or the cashier toast
            self._cz_send_to_kitchen(pos_order)
            self._cz_notify_pos(pos_order)
        return True

    def _cz_send_to_kitchen(self, pos_order):
        """Kitchen display (Enterprise pos_preparation_display), if one is
        linked to this POS. Never blocks the sale."""
        self._cz_kitchen(pos_order, cancelled=False)

    def _cz_kitchen(self, pos_order, cancelled=False):
        if 'pos_preparation_display.order' not in self.env:
            return
        try:
            with self.env.cr.savepoint():
                # A display with no POS selected serves every POS of its company
                # (Kayaşehir 'TONALLİ' works like that): let Odoo pick the displays.
                Display = self.env['pos_preparation_display.display'].sudo()
                if not Display.search_count(['|', ('pos_config_ids', 'in', pos_order.config_id.ids),
                                             ('pos_config_ids', '=', False)]):
                    return
                self.env['pos_preparation_display.order'].sudo().process_order(
                    pos_order.id, cancelled, pos_order.general_note or '', {})
        except Exception as e:  # noqa: BLE001 - kitchen display must never break a sale
            _logger.warning("cz_platform_orders: kitchen display failed for %s: %s", pos_order.name, e)

    def _cz_notify_pos(self, pos_order):
        config = pos_order.config_id
        items = ' · '.join('%s× %s' % (int(l.qty) if l.qty == int(l.qty) else l.qty, l.full_product_name)
                          for l in pos_order.lines if not l.combo_parent_id)
        try:
            config._notify('CZ_PLATFORM_ORDER', {
                'ref': self._cz_ref(),
                'code': self.order_code or '',
                'amount': pos_order.amount_total,
                'items': items[:200],
                'platform': 'Trendyol',
            })
        except Exception as e:  # noqa: BLE001
            _logger.warning("cz_platform_orders: POS notification failed: %s", e)

    # ------------------------------------------------------------------
    def _cz_refund(self):
        """Full refund of a posted order whose package was cancelled."""
        self.ensure_one()
        pos_order = self.pos_order_id.sudo()
        config = pos_order.config_id
        if not self._cz_lock_open_session(config):
            self.write({'error': 'İptal: iade için açık POS oturumu bekleniyor.'})
            return False
        refund = pos_order.with_company(pos_order.company_id)._refund()
        # core copies combo_parent_id from the original: re-link to the refund's own parent
        by_origin = {l.refunded_orderline_id.id: l for l in refund.lines}
        for line in refund.lines.filtered('combo_parent_id'):
            own_parent = by_origin.get(line.combo_parent_id.id)
            if own_parent:
                line.combo_parent_id = own_parent.id
        refund.add_payment({
            'pos_order_id': refund.id,
            'amount': refund.amount_total,
            'payment_method_id': self.account_id.payment_method_id.id,
            'payment_date': fields.Datetime.now(),
            'name': self._cz_ref() + ' İPTAL',
        })
        refund.action_pos_order_paid()
        refund._create_order_picking()
        self.write({'state': 'refunded', 'refund_order_id': refund.id, 'error': False})
        self._cz_kitchen(pos_order, cancelled=True)
        return True

    # ------------------------------------------------------------------
    def _cz_process(self):
        """Decide what to do with each stored order. Safe to call repeatedly."""
        for rec in self:
            account = rec.account_id
            try:
                with self.env.cr.savepoint():
                    if rec.state == 'posted' and rec.status in CANCELLED:
                        rec._cz_refund()
                        continue
                    if rec.state in ('posted', 'refunded', 'cancelled', 'skipped'):
                        continue
                    if rec.pos_order_id:  # safety: a sale exists, never treat as unposted
                        rec.write({'state': 'posted'})
                        continue
                    if rec.status in CANCELLED:
                        rec.write({'state': 'cancelled', 'error': False})
                        continue
                    if rec.status not in POSTABLE:
                        continue
                    if not account.auto_post or not account.post_from:
                        continue  # stays 'new' until posting is switched on
                    if not rec.order_date or rec.order_date < account.post_from:
                        rec.write({'state': 'skipped'})
                        continue
                    rec._cz_post_to_pos()
            except Exception as e:  # noqa: BLE001 - one bad order must not stop the others
                _logger.exception("cz_platform_orders: processing %s failed", rec.package_ref)
                vals = {'error': str(e)[:250], 'attempts': rec.attempts + 1}
                if not rec.pos_order_id:
                    vals['state'] = 'error'
                # a posted order keeps state 'posted' so the refund is retried
                rec.write(vals)
            if self.env.context.get('cz_commit'):
                # cron only: each order is its own unit of work
                self.env.cr.commit()

    def action_mark_manual(self):
        """The cashier entered this order by hand: close it without posting."""
        self.filtered(lambda r: r.state in ('review', 'needs_mapping', 'error') and not r.pos_order_id).write(
            {'state': 'skipped', 'error': 'Kasada elle girildi (%s).' % self.env.user.name})

    def action_retry(self):
        todo = self.filtered(lambda r: r.state in ('error', 'review', 'needs_mapping', 'waiting_session'))
        ys = todo.filtered(lambda r: r.platform == 'yemeksepeti' and not r.pos_order_id)
        for rec in todo:
            if rec in ys and rec.state == 'review':
                continue  # a review is cleared with "Kontrol edildi, gir"
            rec.write({'state': 'posted' if rec.pos_order_id else 'new', 'attempts': 0})
        for rec in ys.filtered(lambda r: r.state == 'new').sorted('order_date'):
            with self.env.cr.savepoint():
                rec.with_context(cz_backfill=True)._cz_post_to_pos()
        (todo - ys).account_id._process_orders_locked()
