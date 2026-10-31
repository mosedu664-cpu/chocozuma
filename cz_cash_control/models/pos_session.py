# -*- coding: utf-8 -*-
from datetime import timedelta

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
            vals.update({
                'payment_ref': ' — '.join(parts),
                'cz_category_id': category.id,
                'cz_employee_id': employee.id if employee.exists() else False,
                'cz_receipt_ref': receipt or False,
                'partner_id': employee.work_contact_id.id if employee.exists() else False,
            })
        vals.update({
            'cz_pos_cashier': extras.get('cz_cashier_name') or False,
            'cz_manager_pin_ok': bool(extras.get('cz_pin_ok')),
            'cz_end_of_day': bool(extras.get('cz_end_of_day')),
        })
        return vals

    def _cz_validate_cash_move(self, session, category, sign, amount, extras):
        """Server-side guard: the POS enforces the same rules, this is the safety net."""
        if sign < 0 and category.direction == 'in' or sign > 0 and category.direction == 'out':
            raise UserError(_("Category %s cannot be used for this type of cash movement.", category.name))
        if category.max_amount and amount > category.max_amount:
            raise UserError(_("Category %(cat)s is capped at %(max)s per movement.",
                              cat=category.name, max=category.max_amount))
        if category.requires_employee and not extras.get('cz_employee_id'):
            raise UserError(_("Category %s requires the staff member.", category.name))
        if category.requires_receipt_above and amount > category.requires_receipt_above \
                and not (extras.get('cz_receipt_ref') or '').strip():
            raise UserError(_("A receipt number is required above %s.", category.requires_receipt_above))
        pin_needed = category.requires_pin or (category.pin_above and amount > category.pin_above) \
            or (session.config_id.cz_cash_out_pin_above and sign < 0 and amount > session.config_id.cz_cash_out_pin_above)
        if pin_needed and not extras.get('cz_pin_ok'):
            raise UserError(_("A manager PIN is required for this movement."))

    def try_cash_in_out(self, _type, amount, reason, extras):
        res = super().try_cash_in_out(_type, amount, reason, extras)
        # keep the open day sheet in sync so the accountant sees movements live
        for session in self.filtered(lambda s: s.config_id.cz_cash_control):
            session.sudo()._cz_get_or_create_day()._compute_all()
        return res

    # ----------------------------------------------------------------- closing
    def _cz_business_date(self):
        """Business day of the session: sessions opened before 04:00 local belong to the previous day."""
        self.ensure_one()
        start = fields.Datetime.context_timestamp(self, self.start_at or fields.Datetime.now())
        day = start.date()
        if start.hour < 4:
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
