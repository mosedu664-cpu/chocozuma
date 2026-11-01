# -*- coding: utf-8 -*-
from datetime import timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class PosSession(models.Model):
    _inherit = 'pos.session'

    cz_day_id = fields.Many2one('cz.cash.day', string='Daily Cash Sheet', readonly=True, copy=False, index=True)

    @api.model
    def _load_pos_data_models(self, config_id):
        models_ = super()._load_pos_data_models(config_id)
        if 'cz.cash.category' not in models_:
            models_.append('cz.cash.category')
        return models_

    # ----------------------------------------------------------------- cash in/out
    def _prepare_account_bank_statement_line_vals(self, session, sign, amount, reason, extras):
        vals = super()._prepare_account_bank_statement_line_vals(session, sign, amount, reason, extras)
        if not session.config_id.cz_cash_control:
            return vals
        category = self.env['cz.cash.category'].browse(extras.get('cz_category_id') or False)
        employee = self.env['hr.employee'].browse(extras.get('cz_employee_id') or False)
        if category.exists():
            self._cz_validate_cash_move(session, category, sign, amount, extras)
            parts = [f"[{category.code}] {category.name}"]
            if employee.exists():
                parts.append(employee.name)
            if reason:
                parts.append(reason)
            receipt = (extras.get('cz_receipt_ref') or '').strip()
            if receipt:
                parts.append(_("fiş %s", receipt))
            envelope = (extras.get('cz_envelope_ref') or '').strip()
            if envelope:
                parts.append(_("zarf %s", envelope))
            vals.update({
                'payment_ref': ' — '.join(parts),
                'cz_category_id': category.id,
                'cz_employee_id': employee.id if employee.exists() else False,
                'cz_receipt_ref': receipt or False,
                'cz_envelope_ref': envelope or False,
                'partner_id': self._cz_partner_for(session, employee),
            })
        image = self._cz_clean_image(extras.get('cz_receipt_image'))
        vals.update({
            'cz_pos_cashier': extras.get('cz_cashier_name') or False,
            'cz_manager_pin_ok': bool(extras.get('cz_pin_ok')),
            'cz_manager_name': (extras.get('cz_manager_name') or False) if extras.get('cz_pin_ok') else False,
            'cz_end_of_day': bool(extras.get('cz_end_of_day')),
            'cz_receipt_image': image,
        })
        return vals

    @api.model
    def _cz_partner_for(self, session, employee):
        """Employee's contact as partner of the statement line — only when the contact is usable
        from the session's company (shared contact or contact of the company / a parent company).
        Employees created under another company (e.g. ADMIN under Tonalli) otherwise break the
        multi-company check; the employee is still kept in cz_employee_id."""
        if not employee.exists():
            return False
        partner = employee.work_contact_id
        if not partner:
            return False
        if partner.company_id and partner.company_id not in session.company_id.parent_ids:
            return False
        return partner.id

    @api.model
    def _cz_clean_image(self, data):
        """base64 (optionally a data: URL) coming from the POS camera → raw base64 or False."""
        if not data or not isinstance(data, str):
            return False
        if data.startswith('data:'):
            data = data.split(',', 1)[-1]
        data = data.strip()
        if len(data) > 6 * 1024 * 1024:  # ~4.5 MB binary: the POS already downsizes, this is a safety net
            raise UserError(_("The receipt photo is too large."))
        return data or False

    def _cz_validate_cash_move(self, session, category, sign, amount, extras):
        """Server-side guard: the POS enforces the same rules, this is the safety net."""
        if sign < 0 and category.direction == 'in' or sign > 0 and category.direction == 'out':
            raise UserError(_("Category %s cannot be used for this type of cash movement.", category.name))
        if category.max_amount and amount > category.max_amount:
            raise UserError(_("Category %(cat)s is capped at %(max)s per movement.",
                              cat=category.name, max=category.max_amount))
        if category.requires_employee and not extras.get('cz_employee_id'):
            raise UserError(_("Category %s requires the staff member.", category.name))
        has_receipt = (extras.get('cz_receipt_ref') or '').strip() or extras.get('cz_receipt_image')
        if category.requires_receipt_above and amount > category.requires_receipt_above and not has_receipt:
            raise UserError(_("A receipt number or receipt photo is required above %s.", category.requires_receipt_above))
        pin_needed = category.requires_pin or (category.pin_above and amount > category.pin_above) \
            or (session.config_id.cz_cash_out_pin_above and sign < 0 and amount > session.config_id.cz_cash_out_pin_above)
        if pin_needed and not extras.get('cz_pin_ok'):
            raise UserError(_("A manager PIN is required for this movement."))

    def try_cash_in_out(self, _type, amount, reason, extras):
        """Cashiers have no accounting rights (the standard POS hides Cash In/Out from them).
        With Cash Control the guard is the category rules + manager PIN (validated server-side
        in _prepare_account_bank_statement_line_vals), so the statement line itself is written
        with elevated rights on their behalf."""
        controlled = self.filtered(lambda s: s.config_id.cz_cash_control)
        if controlled and not self.env.su and not self.env.user.has_group('account.group_account_invoice'):
            if controlled != self:
                raise UserError(_("Mixed sessions are not supported."))
            cashier = extras.get('cz_cashier_name') or self.env.user.name
            extras = dict(extras, cz_cashier_name=cashier)
            res = super(PosSession, self.sudo()).try_cash_in_out(_type, amount, reason, extras)
        else:
            res = super().try_cash_in_out(_type, amount, reason, extras)
        # keep the open day sheet in sync so the accountant sees movements live
        for session in controlled:
            session.sudo()._cz_get_or_create_day()._compute_all()
        return res

    # ----------------------------------------------------------------- POS helpers
    @api.model
    def cz_recent_moves(self, config_id, limit=6):
        """Last distinct drawer movements of this POS (30 days) for the one-tap "repeat" chips.
        Only what the cashier typed himself is returned: category, staff, amount, reason."""
        config = self.env['pos.config'].browse(int(config_id)).exists()
        if not config or not config.cz_cash_control:
            return []
        since = fields.Datetime.now() - timedelta(days=30)
        lines = self.env['account.bank.statement.line'].sudo().search([
            ('pos_session_id.config_id', '=', config.id),
            ('cz_category_id', '!=', False),
            ('cz_end_of_day', '=', False),
            ('create_date', '>=', since),
        ], order='create_date desc', limit=200)
        result, seen = [], set()
        for line in lines:
            cat = line.cz_category_id
            if not cat.pos_available or cat.kind in ('safe_transfer', 'refund'):
                continue
            reason = self._cz_reason_from_ref(line, cat)
            key = (cat.id, line.cz_employee_id.id, round(abs(line.amount), 2), reason)
            if key in seen:
                continue
            seen.add(key)
            result.append({
                'category_id': cat.id,
                'category_name': cat.name,
                'employee_id': line.cz_employee_id.id or False,
                'employee_name': line.cz_employee_id.name or '',
                'amount': round(abs(line.amount), 2),
                'type': 'in' if line.amount > 0 else 'out',
                'reason': reason,
            })
            if len(result) >= limit:
                break
        return result

    @api.model
    def _cz_reason_from_ref(self, line, category):
        """payment_ref is "[CODE] Name — employee — reason — fiş X": pull the free-text reason back out."""
        parts = [p.strip() for p in (line.payment_ref or '').split(' — ')]
        skip = {f"[{category.code}] {category.name}", line.cz_employee_id.name or ''}
        for part in parts[1:]:
            if part in skip or part.startswith(('fiş ', 'zarf ')):
                continue
            return part
        return ''

    def cz_eod_summary(self, counted):
        """Figures printed on the end-of-day slip (before the drawer is emptied)."""
        self.ensure_one()
        session = self.sudo()
        cur = session.currency_id
        cash_pms = session.config_id.payment_method_ids.filtered(lambda pm: pm.type == 'cash')
        payments = self.env['pos.payment'].sudo().search([('session_id', '=', session.id)])
        cash_sales = sum(payments.filtered(lambda p: p.payment_method_id in cash_pms).mapped('amount'))
        non_cash = sum(payments.filtered(lambda p: p.payment_method_id not in cash_pms
                                         and p.payment_method_id.type != 'pay_later').mapped('amount'))
        by_cat = {}
        cash_in = 0.0
        safe_transfers = 0.0
        moves_total = 0.0
        for line in session.statement_line_ids.filtered(lambda l: not l.cz_end_of_day):
            cat = line.cz_category_id
            moves_total += line.amount
            if cat.kind == 'safe_transfer':
                safe_transfers += -line.amount
            elif line.amount > 0:
                cash_in += line.amount
            else:
                entry = by_cat.setdefault(cat.id or 0, {'name': cat.name or _('Uncategorised'), 'count': 0, 'amount': 0.0})
                entry['count'] += 1
                entry['amount'] += -line.amount
        opening = session.cash_register_balance_start
        expected = opening + cash_sales + moves_total
        counted = float(counted or 0.0)
        fmt = cur.format
        return {
            'opening': fmt(opening),
            'cash_sales': fmt(cash_sales),
            'non_cash': fmt(non_cash),
            'total_sales': fmt(cash_sales + non_cash),
            'cash_in': fmt(cash_in),
            'safe_transfers': fmt(safe_transfers),
            'expenses': [{'name': v['name'], 'count': v['count'], 'amount': fmt(v['amount'])}
                         for v in sorted(by_cat.values(), key=lambda v: -v['amount'])],
            'expenses_total': fmt(sum(v['amount'] for v in by_cat.values())),
            'expected': fmt(expected),
            'counted': fmt(counted),
            'difference': fmt(counted - expected),
            'difference_raw': counted - expected,
            'order_count': len(session.order_ids.filtered(lambda o: o.state in ('paid', 'done', 'invoiced'))),
            'session_name': session.name,
            'safe_name': session.config_id.cz_safe_id.name or '',
            'date': fields.Date.context_today(self).strftime('%d.%m.%Y'),
        }

    # ----------------------------------------------------------------- mid-day check
    def _cz_check_manager(self, manager_id, pin):
        """Server-side PIN check: the employee must be a POS manager of this config
        (same rule as pos_hr: POS Administrator user or in Advanced rights)."""
        self.ensure_one()
        employee = self.env['hr.employee'].sudo().browse(int(manager_id or 0)).exists()
        if not employee or not pin or not employee.pin or str(employee.pin) != str(pin):
            raise UserError(_("Wrong manager PIN."))
        config = self.config_id.sudo()
        is_manager = employee in config.advanced_employee_ids or (
            employee.user_id and config.group_pos_manager_id in employee.user_id.groups_id)
        if not is_manager:
            raise UserError(_("%s is not a manager on this point of sale.", employee.name))
        return employee

    def _cz_expected_cash(self):
        """Expected drawer cash right now — same formula as Odoo's closing popup
        (get_closing_control_data): opening + cash payments of closed orders + cash in/out."""
        self.ensure_one()
        session = self.sudo()
        cash_pm = session.payment_method_ids.filtered(lambda pm: pm.type == 'cash')[:1]
        if not cash_pm:
            raise UserError(_("There is no cash payment method for this PoS Session"))
        payments = session._get_closed_orders().payment_ids.filtered(lambda p: p.payment_method_id == cash_pm)
        cash_sales = sum(payments.mapped('amount'))
        moves = sum(session.statement_line_ids.mapped('amount'))
        opening = session.cash_register_balance_start
        return opening, cash_sales, moves, opening + cash_sales + moves

    def cz_drawer_check(self, counted, check_type, manager_id, pin, cashier_name=False):
        """Record a blind mid-day count without closing the session; returns the figures."""
        self.ensure_one()
        if not self.config_id.cz_cash_control:
            raise UserError(_("Cash Control is not enabled on this point of sale."))
        if self.state != 'opened':
            raise UserError(_("The register must be open to check the drawer."))
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise UserError(_("You don't have the access rights to perform a drawer check."))
        try:
            counted = float(counted)
        except (TypeError, ValueError):
            raise UserError(_("Invalid counted amount."))
        if counted < 0:
            raise UserError(_("Counted amount cannot be negative."))
        if check_type not in ('handover', 'spot'):
            check_type = 'spot'
        manager = self._cz_check_manager(manager_id, pin)
        opening, cash_sales, moves, expected = self._cz_expected_cash()
        currency = self.currency_id
        difference = currency.round(counted - expected)
        day = self.sudo()._cz_get_or_create_day()
        check = self.env['cz.cash.check'].sudo().create({
            'session_id': self.id,
            'day_id': day.id,
            'check_type': check_type,
            'cashier_name': cashier_name or False,
            'manager_id': manager.id,
            'opening': opening,
            'cash_sales': cash_sales,
            'cash_moves': moves,
            'expected': expected,
            'counted': counted,
            'difference': difference,
        })
        type_label = dict(check._fields['check_type']._description_selection(self.env))[check_type]
        day.message_post(body=_(
            "%(type)s %(ref)s — cashier %(cashier)s, authorised by %(manager)s: counted %(counted)s, "
            "expected %(expected)s, difference %(diff)s.",
            type=type_label, ref=check.name, cashier=cashier_name or '-', manager=manager.name,
            counted=currency.format(counted), expected=currency.format(expected),
            diff=currency.format(difference)))
        day.invalidate_recordset(['check_ids'])
        day._compute_alerts()
        return {
            'id': check.id,
            'name': check.name,
            'opening': opening,
            'cash_sales': cash_sales,
            'cash_moves': moves,
            'expected': expected,
            'counted': counted,
            'difference': difference,
            'manager': manager.name,
        }

    # ----------------------------------------------------------------- closing
    def _cz_business_date(self):
        """Business day of the session.

        Sessions running before 04:00 local belong to the previous day (late closing) —
        unless the previous day's register was already closed after midnight: then the
        day has ended and a session opened before 04:00 is the new day's.
        """
        self.ensure_one()
        start = fields.Datetime.context_timestamp(self, self.start_at or fields.Datetime.now())
        day = start.date()
        if start.hour < 4:
            local_midnight = start.replace(hour=0, minute=0, second=0, microsecond=0)
            utc_midnight = local_midnight.astimezone(pytz.utc).replace(tzinfo=None)
            closed_after_midnight = self.env['pos.session'].sudo().search_count([
                ('config_id', '=', self.config_id.id),
                ('id', '!=', self.id),
                ('state', '=', 'closed'),
                ('stop_at', '>=', utc_midnight),
                ('start_at', '<', self.start_at or fields.Datetime.now()),
            ])
            if not closed_after_midnight:
                day = day - timedelta(days=1)
        return day

    def _cz_get_or_create_day(self):
        self.ensure_one()
        if self.cz_day_id:
            return self.cz_day_id
        Day = self.env['cz.cash.day'].sudo()
        bdate = self._cz_business_date()
        days = Day.search([('config_id', '=', self.config_id.id), ('date', '=', bdate)], order='seq desc')
        day = days[:1]
        if not day or day.state == 'approved':
            # never touch an approved sheet: a late session gets its own sheet (2), (3)...
            day = Day.create({'config_id': self.config_id.id, 'date': bdate, 'seq': (day.seq + 1) if day else 1})
        self.cz_day_id = day
        return day

    def _validate_session(self, balancing_account=False, amount_to_balance=0, bank_payment_method_diffs=None):
        res = super()._validate_session(balancing_account, amount_to_balance, bank_payment_method_diffs)
        for session in self.filtered(lambda s: s.config_id.cz_cash_control and s.state == 'closed'):
            day = session.sudo()._cz_get_or_create_day()
            day._compute_all()
            day._on_session_closed(session)
        return res

    def post_closing_cash_details(self, counted_cash):
        res = super().post_closing_cash_details(counted_cash)
        if res.get('successful') and self.config_id.cz_cash_control:
            self.sudo()._cz_get_or_create_day()
        return res

    def _set_opening_control_data(self, cashbox_value, notes):
        # Odoo 18: inherit the internal method, not set_opening_control
        res = super()._set_opening_control_data(cashbox_value, notes)
        for session in self.filtered(lambda s: s.config_id.cz_cash_control and s.state == 'opened'):
            session.sudo()._cz_get_or_create_day()._compute_all()
        return res
