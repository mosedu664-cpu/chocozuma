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
            self._cz_validate_cash_move(session, category, sign, amount, extras, reason=reason)
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

    def _cz_validate_cash_move(self, session, category, sign, amount, extras, reason=''):
        """Server-side guard: the POS enforces the same rules, this is the safety net."""
        if self.env.context.get('cz_reversal'):
            return  # a correction mirrors an existing movement; checked in cz_reverse_move
        if sign < 0 and category.direction == 'in' or sign > 0 and category.direction == 'out':
            raise UserError(_("Category %s cannot be used for this type of cash movement.", category.name))
        if category.max_amount and amount > category.max_amount:
            raise UserError(_("Category %(cat)s is capped at %(max)s per movement.",
                              cat=category.name, max=category.max_amount))
        if category.requires_reason and len((reason or '').strip()) < 3:
            raise UserError(_("Category %s requires a description.", category.name))
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
            ('cz_reversal_of_id', '=', False),
            ('cz_reversal_ids', '=', False),
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

    # ----------------------------------------------------------------- movements list in the POS
    def _cz_check_pos_access(self):
        self.ensure_one()
        if not self.config_id.cz_cash_control:
            raise UserError(_("Cash Control is not enabled on this point of sale."))
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise UserError(_("You don't have the access rights to see the cash movements."))

    def _cz_line_reversible(self, line):
        """A movement can be corrected from the POS while its session is open, if it is a
        categorised cashier movement that is neither a correction itself nor already corrected."""
        return bool(
            self.state == 'opened'
            and line.pos_session_id == self
            and line.cz_category_id
            and not line.cz_end_of_day
            and not line.cz_approved
            and not line.cz_reversal_of_id
            and not line.cz_reversal_ids
        )

    def cz_session_moves(self):
        """Every drawer movement of this session for the POS "Hareketler" list (read-only).
        Nothing accounting-related (accounts, counterparts) is returned."""
        self._cz_check_pos_access()
        session = self.sudo()
        lines = session.statement_line_ids.sorted(lambda l: (l.create_date, l.id), reverse=True)
        cur = session.currency_id
        rows = []
        total_in = total_out = cancelled_amount = 0.0
        cancelled_count = 0
        for line in lines:
            cat = line.cz_category_id
            amount = cur.round(line.amount)
            in_pair = bool(line.cz_reversal_of_id or line.cz_reversal_ids)
            if in_pair:
                # a cancelled movement and its correction net to zero: kept out of the in/out totals
                if line.cz_reversal_ids:
                    cancelled_count += 1
                    cancelled_amount += abs(amount)
            elif amount >= 0:
                total_in += amount
            else:
                total_out += -amount
            created = fields.Datetime.context_timestamp(self, line.create_date) if line.create_date else False
            reason = self._cz_reason_from_ref(line, cat) if cat else (line.payment_ref or '')
            rows.append({
                'id': line.id,
                'time': created.strftime('%H:%M') if created else '',
                'type': 'in' if amount >= 0 else 'out',
                'amount': abs(amount),
                'category': cat.name or _('Uncategorised'),
                'code': cat.code or '',
                'kind': cat.kind or '',
                'icon': cat.icon or 'fa-exchange',
                'color': cat.color or 0,
                'reason': reason,
                'employee': line.cz_employee_id.name or '',
                'cashier': line.cz_pos_cashier or '',
                'manager': line.cz_manager_name or '',
                'receipt_ref': line.cz_receipt_ref or '',
                'has_photo': bool(line.cz_has_receipt_image),
                'end_of_day': line.cz_end_of_day,
                'is_correction': bool(line.cz_reversal_of_id),
                'corrects_id': line.cz_reversal_of_id.id or False,
                'correction_reason': line.cz_reversal_reason or '',
                'corrected': bool(line.cz_reversal_ids),
                'reversible': session._cz_line_reversible(line),
            })
        return {
            'session_name': session.name,
            'is_open': session.state == 'opened',
            'lines': rows,
            'total_in': cur.round(total_in),
            'total_out': cur.round(total_out),
            'net': cur.round(sum(lines.mapped('amount'))),
            'count': len(rows),
            'cancelled_count': cancelled_count,
            'cancelled_amount': cur.round(cancelled_amount),
        }

    def cz_move_photo(self, line_id):
        """Receipt photo of one movement of this session (base64 jpeg) or False."""
        self._cz_check_pos_access()
        line = self.sudo().statement_line_ids.filtered(lambda l: l.id == int(line_id or 0))
        image = line.cz_receipt_image if line else False
        if isinstance(image, bytes):
            image = image.decode()
        return image or False

    def cz_reverse_move(self, line_id, manager_id, pin, reason, cashier_name=False):
        """Cancel a movement of the open session with an opposite movement (manager PIN).
        The original is never deleted or edited: both lines stay and net to zero, the
        daily sheet, the drawer expectation and the accountant see the pair."""
        self._cz_check_pos_access()
        reason = (reason or '').strip()
        if len(reason) < 3:
            raise UserError(_("Please write why the movement is being corrected."))
        session = self.sudo()
        line = session.statement_line_ids.filtered(lambda l: l.id == int(line_id or 0))
        if not line:
            raise UserError(_("This movement does not belong to the current session."))
        if not session._cz_line_reversible(line):
            raise UserError(_("This movement can no longer be corrected from the POS."))
        manager = self._cz_check_manager(manager_id, pin)
        amount = abs(line.amount)
        _type = 'out' if line.amount > 0 else 'in'
        cat = line.cz_category_id
        extras = {
            'translatedType': _('in') if _type == 'in' else _('out'),
            # pos_hr: same employee as the original, so the closing popup's per-employee totals net out
            'employee_id': line.employee_id.id if 'employee_id' in line._fields and line.employee_id else False,
            'cz_category_id': cat.id,
            'cz_employee_id': line.cz_employee_id.id or False,
            'cz_pin_ok': True,
            'cz_manager_name': manager.name,
            'cz_cashier_name': cashier_name or self.env.user.name,
        }
        before = set(session.statement_line_ids.ids)
        session.with_context(cz_reversal=True).try_cash_in_out(
            _type, amount, _("DÜZELTME: %s", reason), extras)
        new_line = session.statement_line_ids.filtered(lambda l: l.id not in before)
        new_line.write({
            'cz_reversal_of_id': line.id,
            'cz_reversal_reason': reason,
            'payment_ref': _("↩ İPTAL — %(orig)s — %(reason)s (onay: %(manager)s)",
                             orig=line.payment_ref, reason=reason, manager=manager.name),
        })
        if session.cz_day_id:
            session.cz_day_id.message_post(body=_(
                "Movement corrected in the POS by %(manager)s: %(orig)s (%(amount)s). Reason: %(reason)s",
                manager=manager.name, orig=line.payment_ref,
                amount=session.currency_id.format(line.amount), reason=reason))
        return {'id': new_line.id, 'amount': amount, 'type': _type}

    # ----------------------------------------------------------------- branch safe in the POS
    def _cz_pos_safe(self):
        self._cz_check_pos_access()
        safe = self.config_id.sudo().cz_safe_id
        if not safe:
            raise UserError(_("No branch safe is set on this point of sale."))
        return safe

    def cz_safe_info(self, manager_id, pin):
        """Safe screen for a manager (PIN re-checked): balance, payment categories,
        staff and the last movements. Accounts are never sent to the POS."""
        safe = self._cz_pos_safe()
        self._cz_check_manager(manager_id, pin)
        cats = self.env['cz.cash.category'].sudo().search([
            ('company_id', '=', safe.company_id.id),
            ('safe_pos_available', '=', True),
            ('direction', 'in', ('out', 'both')),
            ('kind', 'in', ('expense', 'advance', 'bank_deposit', 'salary', 'other')),
        ])
        usage = dict(self.env['cz.cash.safe.move'].sudo()._read_group(
            [('safe_id', '=', safe.id), ('state', '=', 'approved'), ('category_id', 'in', cats.ids),
             ('date', '>=', fields.Date.subtract(fields.Date.context_today(self), days=60))],
            ['category_id'], ['__count']))
        cats = cats.sorted(lambda c: (-usage.get(c, 0), c.sequence, c.name))
        moves = self.env['cz.cash.safe.move'].sudo().search(
            [('safe_id', '=', safe.id), ('state', '!=', 'cancelled'), ('move_type', '!=', 'count')], limit=15)
        employees = self.env['hr.employee'].sudo().search([('company_id', 'in', [safe.company_id.id, False])])
        return {
            'safe_name': safe.name,
            'balance': safe.currency_id.round(safe.balance),
            'pending': safe.currency_id.round(safe.pending_day_amount),
            'expected': safe.currency_id.round(safe.expected_balance),
            'categories': [{
                'id': c.id, 'name': c.name, 'code': c.code, 'icon': c.icon or 'fa-tag', 'color': c.color or 0,
                'usage': usage.get(c, 0),
                'requires_employee': c.requires_employee, 'requires_receipt_above': c.requires_receipt_above,
                'max_amount': c.max_amount,
            } for c in cats],
            'employees': [{'id': e.id, 'name': e.name} for e in employees.sorted('name')],
            'moves': [{
                'id': m.id,
                'name': m.name,
                'date': fields.Date.to_string(m.date),
                'type': m.move_type,
                'amount': m.amount,
                'category': m.category_id.name or (_('Çekmeceden') if m.move_type == 'in' else ''),
                'icon': m.category_id.icon or ('fa-arrow-down' if m.move_type == 'in' else 'fa-tag'),
                'color': m.category_id.color or 0,
                'note': m.note or '',
                'employee': m.employee_id.name or '',
                'manager': m.cz_manager_id.name or '',
                'from_pos': m.cz_from_pos,
                'state': m.state,
                'has_photo': bool(m.attachment_ids),
            } for m in moves],
        }

    def cz_safe_payment(self, manager_id, pin, category_id, amount, note, employee_id=False,
                        receipt_ref=False, receipt_image=False):
        """A manager pays directly from the branch safe (never from the drawer).
        Booked at once so the safe balance stays true; the accountant reviews
        'Entered in the POS' movements and can cancel one."""
        safe = self._cz_pos_safe()
        manager = self._cz_check_manager(manager_id, pin)
        cat = self.env['cz.cash.category'].sudo().browse(int(category_id or 0)).exists()
        if not cat or cat.company_id != safe.company_id or not cat.safe_pos_available \
                or cat.direction not in ('out', 'both') \
                or cat.kind not in ('expense', 'advance', 'bank_deposit', 'salary', 'other'):
            raise UserError(_("This category cannot be used for a payment from the safe."))
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            raise UserError(_("Invalid amount."))
        amount = safe.currency_id.round(amount)
        if amount <= 0:
            raise UserError(_("Amount must be positive."))
        note = (note or '').strip()
        if len(note) < 3:
            raise UserError(_("Please write what was paid and to whom."))
        if cat.max_amount and amount > cat.max_amount:
            raise UserError(_("Maximum for %(cat)s is %(max)s.", cat=cat.name,
                              max=safe.currency_id.format(cat.max_amount)))
        if safe.currency_id.compare_amounts(amount, safe.expected_balance) > 0:
            raise UserError(_("Expected cash in the safe is %s: this payment is larger. "
                              "Count the safe or ask the accountant.", safe.currency_id.format(safe.expected_balance)))
        employee = self.env['hr.employee'].sudo().browse(int(employee_id or 0)).exists()
        if cat.requires_employee and not employee:
            raise UserError(_("Category %s requires the staff member.", cat.name))
        receipt_ref = (receipt_ref or '').strip()
        if cat.requires_receipt_above and amount > cat.requires_receipt_above and not (receipt_ref or receipt_image):
            raise UserError(_("A receipt number or photo is required above %s.",
                              safe.currency_id.format(cat.requires_receipt_above)))
        move = self.env['cz.cash.safe.move'].sudo().create({
            'safe_id': safe.id,
            'date': fields.Date.context_today(self),
            'move_type': 'out',
            'amount': amount,
            'category_id': cat.id,
            'employee_id': employee.id or False,
            'note': note,
            'receipt_ref': receipt_ref or False,
            'cz_from_pos': True,
            'cz_manager_id': manager.id,
            'cz_pos_session_id': self.id,
        })
        if receipt_image:
            image = self._cz_clean_image(receipt_image)
            if image:
                att = self.env['ir.attachment'].sudo().create({
                    'name': f"{move.name.replace('/', '-')}.jpg",
                    'datas': image,
                    'mimetype': 'image/jpeg',
                    'res_model': 'cz.cash.safe.move',
                    'res_id': move.id,
                })
                move.attachment_ids = [(4, att.id)]
        move.action_approve()
        move.message_post(body=_("Paid from the safe in the POS (%(session)s) — manager %(manager)s.",
                                 session=self.name, manager=manager.name))
        safe.invalidate_recordset(['balance', 'expected_balance', 'pending_day_amount'])
        return {'name': move.name, 'amount': amount, 'expected': safe.currency_id.round(safe.expected_balance)}

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
            # a POS correction is classified like the movement it cancels, so the pair nets out
            base = line.cz_reversal_of_id or line
            if cat.kind == 'safe_transfer':
                safe_transfers += -line.amount
            elif base.amount > 0:
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
