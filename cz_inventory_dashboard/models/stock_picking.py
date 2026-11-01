# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models
from odoo.osv import expression

OPEN_STATES = ('assigned', 'waiting', 'confirmed')


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.model
    def cz_dashboard_data(self, company_id=None):
        """Everything the board shows, in one call, under the caller's own access rights."""
        company = self.env['res.company'].browse(company_id) if company_id else self.env.company
        now = fields.Datetime.now()
        today = fields.Date.context_today(self)
        start_today = fields.Datetime.to_datetime(today)
        end_today = start_today + timedelta(days=1)
        week_ago = start_today - timedelta(days=7)

        types = self.env['stock.picking.type'].search(
            [('company_id', '=', company.id), ('active', '=', True),
             ('code', 'in', ('incoming', 'outgoing', 'internal', 'dropship'))],
            order='warehouse_id, sequence, id')

        base = [('company_id', '=', company.id)]
        late_dom = [('state', 'in', OPEN_STATES), '|',
                    ('scheduled_date', '<', start_today), ('has_deadline_issue', '=', True)]

        def count(dom):
            return self.search_count(expression.AND([base, dom]))

        warehouses = []
        for pt in types:
            wh = pt.warehouse_id
            key = wh.id or 0
            block = next((w for w in warehouses if w['id'] == key), None)
            if block is None:
                block = {'id': key, 'name': wh.name if wh else 'Dropship', 'code': wh.code if wh else 'DS', 'types': []}
                warehouses.append(block)
            d = [('picking_type_id', '=', pt.id)]
            block['types'].append({
                'id': pt.id, 'name': pt.name, 'code': pt.code,
                'ready': count(d + [('state', '=', 'assigned')]),
                'waiting': count(d + [('state', 'in', ('confirmed', 'waiting'))]),
                'late': count(d + late_dom),
                'today': count(d + [('state', 'in', OPEN_STATES), ('scheduled_date', '>=', start_today), ('scheduled_date', '<', end_today)]),
                'done_today': count(d + [('state', '=', 'done'), ('date_done', '>=', start_today)]),
                'done_7d': count(d + [('state', '=', 'done'), ('date_done', '>=', week_ago)]),
            })

        # Open outgoing (deliveries + dropship), grouped by customer
        out = self.search(expression.AND([base, [
            ('picking_type_code', 'in', ('outgoing', 'dropship')),
            ('state', 'in', OPEN_STATES)]]), order='scheduled_date')
        rows = []
        has_sale = 'sale_id' in self._fields
        for p in out:
            is_late = p.scheduled_date < start_today or p.has_deadline_issue
            # dropship pickings carry the vendor as partner; the board groups by customer
            customer = p.partner_id
            if p.picking_type_code == 'dropship' and has_sale and p.sale_id.partner_id:
                customer = p.sale_id.partner_id
            rows.append({
                'id': p.id, 'name': p.name,
                'partner': customer.display_name or '—',
                'partner_id': customer.id,
                'scheduled': fields.Datetime.context_timestamp(self, p.scheduled_date).strftime('%d.%m %H:%M'),
                'is_late': is_late,
                'is_today': start_today <= p.scheduled_date < end_today,
                'state': p.state,
                'origin': p.origin or '',
                'lines': len(p.move_ids),
                'wh': p.picking_type_id.warehouse_id.code or 'DS',
                'type': p.picking_type_id.name,
                'priority': p.priority == '1',
                'user': p.user_id.name or '',
            })
        by_partner = {}
        for r in rows:
            g = by_partner.setdefault(r['partner_id'], {'partner': r['partner'], 'partner_id': r['partner_id'], 'ready': 0, 'waiting': 0, 'late': 0, 'pickings': []})
            g['pickings'].append(r)
            g['ready' if r['state'] == 'assigned' else 'waiting'] += 1
            if r['is_late']:
                g['late'] += 1
        groups = sorted(by_partner.values(), key=lambda g: (-g['late'], -g['ready'], g['partner']))

        # Receipts open
        inc = self.search(expression.AND([base, [('picking_type_code', '=', 'incoming'), ('state', 'in', OPEN_STATES)]]), order='scheduled_date')
        receipts = [{
            'id': p.id, 'name': p.name, 'partner': p.partner_id.display_name or '—',
            'scheduled': fields.Datetime.context_timestamp(self, p.scheduled_date).strftime('%d.%m %H:%M'),
            'is_late': p.scheduled_date < start_today, 'state': p.state, 'origin': p.origin or '',
            'lines': len(p.move_ids), 'wh': p.picking_type_id.warehouse_id.code or '',
        } for p in inc]

        totals = {
            'ready': sum(1 for r in rows if r['state'] == 'assigned'),
            'waiting': sum(1 for r in rows if r['state'] != 'assigned'),
            'late': sum(1 for r in rows if r['is_late']),
            'today': sum(1 for r in rows if r['is_today']),
            'receipts': len(receipts),
            'receipts_late': sum(1 for r in receipts if r['is_late']),
            'done_today': count([('picking_type_code', 'in', ('outgoing', 'dropship')), ('state', '=', 'done'), ('date_done', '>=', start_today)]),
        }
        return {
            'company': company.name, 'company_id': company.id, 'has_sale': has_sale,
            'as_of': fields.Datetime.context_timestamp(self, now).strftime('%d.%m.%Y %H:%M'),
            'totals': totals, 'warehouses': warehouses, 'groups': groups, 'receipts': receipts,
            'can_validate': self.env.user.has_group('stock.group_stock_user'),
        }

    @api.model
    def cz_dashboard_action(self, picking_id, action):
        """Board buttons. Reuses the standard methods so every rule, lot and
        backorder wizard of Odoo still applies."""
        picking = self.browse(picking_id)
        picking.check_access('write')
        if action == 'check':
            picking.action_assign()
            return {'ok': True}
        if action == 'validate':
            if picking.state != 'assigned':
                return {'ok': False, 'msg': 'Not fully reserved'}
            res = picking.with_context(skip_sms=True).button_validate()
            # a wizard (backorder / immediate transfer) must be shown to the user
            if isinstance(res, dict) and res.get('res_model'):
                return {'ok': False, 'action': res}
            return {'ok': True}
        return {'ok': False, 'msg': 'unknown action'}
