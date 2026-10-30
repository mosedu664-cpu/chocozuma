# -*- coding: utf-8 -*-
from collections import defaultdict
from datetime import timedelta

from markupsafe import Markup, escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero


class CzCashDay(models.Model):
    """One sheet per POS per business day — the accountant's single screen.

    Built automatically from POS sessions (cash sales, cash in/out, counted cash).
    Approval posts the category counterparts and mirrors safe transfers.
    """
    _name = 'cz.cash.day'
    _description = 'Daily Cash Sheet'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, config_id'
    _check_company_auto = True

    name = fields.Char(compute='_compute_name', store=True)
    config_id = fields.Many2one('pos.config', string='Point of Sale', required=True, index=True, ondelete='restrict')
    company_id = fields.Many2one(related='config_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    safe_id = fields.Many2one(related='config_id.cz_safe_id', string='Branch Safe')
    cash_journal_id = fields.Many2one('account.journal', compute='_compute_cash_journal', store=True)
    date = fields.Date(required=True, index=True)
    seq = fields.Integer(string='Sheet no.', default=1, required=True,
                         help="2, 3... when a new session is opened after the day's sheet was already approved.")
    session_ids = fields.One2many('pos.session', 'cz_day_id', string='POS Sessions')
    session_count = fields.Integer(compute='_compute_sessions')
    all_sessions_closed = fields.Boolean(compute='_compute_sessions')
    cashier_names = fields.Char(compute='_compute_sessions', string='Cashiers')
    statement_line_ids = fields.One2many('account.bank.statement.line', 'cz_day_id', string='Cash Movements')
    summary_line_ids = fields.One2many('cz.cash.day.line', 'day_id', string='Summary by Category')

    # --- figures (stored snapshot, refreshed by _compute_all)
    opening_cash = fields.Monetary(currency_field='currency_id', readonly=True)
    cash_sales = fields.Monetary(string='POS Cash Sales', currency_field='currency_id', readonly=True)
    cash_in_total = fields.Monetary(string='Cash In', currency_field='currency_id', readonly=True)
    expense_total = fields.Monetary(string='Expenses from Drawer', currency_field='currency_id', readonly=True)
    safe_transfer_total = fields.Monetary(string='Transferred to Safe', currency_field='currency_id', readonly=True)
    refund_total = fields.Monetary(string='Refunds', currency_field='currency_id', readonly=True)
    uncategorised_total = fields.Monetary(string='Uncategorised', currency_field='currency_id', readonly=True)
    uncategorised_count = fields.Integer(readonly=True)
    expected_cash = fields.Monetary(string='Expected in Drawer', currency_field='currency_id', readonly=True)
    counted_cash = fields.Monetary(string='Counted at Closing', currency_field='currency_id', readonly=True)
    difference = fields.Monetary(string='Difference', currency_field='currency_id', readonly=True)
    closing_notes = fields.Text(readonly=True)
    non_cash_total = fields.Monetary(string='Card / Online', currency_field='currency_id', readonly=True)
    total_sales = fields.Monetary(string='Total Sales', currency_field='currency_id', readonly=True)

    # --- parallel-run check against the legacy Excel sheet
    excel_cash_sales = fields.Monetary(string='Excel: Cash Sales', currency_field='currency_id',
                                       help="During the parallel run: the CASH SALES figure typed in the old Excel sheet.")
    excel_expenses = fields.Monetary(string='Excel: Expenses', currency_field='currency_id')
    excel_diff = fields.Monetary(compute='_compute_excel_diff', currency_field='currency_id', string='Excel vs POS')

    # --- accountant decisions
    difference_action = fields.Selection([
        ('keep', 'Keep as cash difference (profit/loss)'),
        ('to_safe', 'Cash was moved to the safe without a cash-out'),
        ('reclass', 'Post to another account'),
    ], default='keep', required=True)
    difference_account_id = fields.Many2one('account.account',
                                            domain="[('company_ids', 'parent_of', company_id), ('deprecated', '=', False)]")
    difference_note = fields.Char()
    accountant_note = fields.Text()

    state = fields.Selection([
        ('open', 'Open'),
        ('to_approve', 'To Approve'),
        ('approved', 'Approved'),
    ], default='open', required=True, tracking=True, index=True)
    approved_by = fields.Many2one('res.users', readonly=True)
    approved_at = fields.Datetime(readonly=True)
    alert_level = fields.Selection([('ok', 'OK'), ('warning', 'Warning'), ('danger', 'Critical')],
                                   default='ok', readonly=True)
    alert_html = fields.Html(readonly=True, sanitize=False)
    alert_count = fields.Integer(readonly=True)
    safe_move_ids = fields.One2many('cz.cash.safe.move', 'origin_day_id', string='Safe movements created')

    _sql_constraints = [
        ('config_date_seq_uniq', 'unique(config_id, date, seq)', 'There is already a cash sheet for this POS, day and sheet number.'),
    ]

    # ------------------------------------------------------------------ computes
    @api.depends('config_id', 'date', 'seq')
    def _compute_name(self):
        for day in self:
            if not (day.config_id and day.date):
                day.name = _('New')
                continue
            day.name = f"{day.config_id.name} — {day.date}" + (f" ({day.seq})" if day.seq > 1 else "")

    @api.depends('config_id.payment_method_ids')
    def _compute_cash_journal(self):
        for day in self:
            cash_pm = day.config_id.payment_method_ids.filtered(lambda pm: pm.type == 'cash')[:1]
            day.cash_journal_id = cash_pm.journal_id

    @api.depends('session_ids.state', 'session_ids.user_id')
    def _compute_sessions(self):
        for day in self:
            day.session_count = len(day.session_ids)
            day.all_sessions_closed = bool(day.session_ids) and all(s.state == 'closed' for s in day.session_ids)
            names = set()
            for s in day.session_ids:
                names.update(s.statement_line_ids.mapped('cz_pos_cashier'))
                names.update(s.order_ids.mapped('employee_id.name'))
            day.cashier_names = ', '.join(sorted(n for n in names if n))

    @api.depends('excel_cash_sales', 'cash_sales')
    def _compute_excel_diff(self):
        for day in self:
            day.excel_diff = (day.excel_cash_sales - day.cash_sales) if day.excel_cash_sales else 0.0

    # ------------------------------------------------------------------ refresh
    def _diff_accounts(self):
        self.ensure_one()
        j = self.cash_journal_id
        return (j.profit_account_id | j.loss_account_id)

    def _counterparts(self, line):
        return line.move_id.line_ids.filtered(lambda l: l.account_id != line.journal_id.default_account_id)

    def _is_diff_line(self, line):
        """Statement line auto-created by Odoo at closing for the count difference."""
        if line.cz_category_id:
            return False
        counterparts = self._counterparts(line)
        return bool(counterparts) and counterparts.account_id <= self._diff_accounts()

    def _is_system_line(self, line):
        """Statement line Odoo itself created and already booked at closing
        (the session's cash payments line, counterpart POS receivable). Not a drawer movement."""
        if line.cz_category_id:
            return False
        counterparts = self._counterparts(line)
        return bool(counterparts) and line.journal_id.suspense_account_id not in counterparts.account_id \
            and not self._is_diff_line(line)

    def _compute_all(self):
        """Rebuild the snapshot from the sessions. Safe to call any time before approval."""
        Payment = self.env['pos.payment'].sudo()
        for day in self:
            if day.state == 'approved':
                continue
            sessions = day.session_ids.sudo()
            lines = sessions.statement_line_ids
            lines.filtered(lambda l: l.cz_day_id != day).write({'cz_day_id': day.id})

            cash_pms = day.config_id.payment_method_ids.filtered(lambda pm: pm.type == 'cash')
            payments = Payment.search([('session_id', 'in', sessions.ids)])
            cash_sales = sum(payments.filtered(lambda p: p.payment_method_id in cash_pms).mapped('amount'))
            non_cash = sum(payments.filtered(lambda p: p.payment_method_id not in cash_pms
                                             and p.payment_method_id.type != 'pay_later').mapped('amount'))

            totals = defaultdict(float)
            per_cat = defaultdict(lambda: {'count': 0, 'amount': 0.0})
            uncategorised = 0.0
            uncategorised_count = 0
            diff_lines_total = 0.0
            system_total = 0.0
            for line in lines:
                if day._is_diff_line(line):
                    diff_lines_total += line.amount
                    continue
                if day._is_system_line(line):
                    system_total += line.amount
                    continue
                cat = line.cz_category_id
                if cat:
                    totals[cat.kind] += line.amount
                    per_cat[cat.id]['count'] += 1
                    per_cat[cat.id]['amount'] += line.amount
                else:
                    uncategorised += line.amount
                    uncategorised_count += 1

            first = sessions.sorted('start_at')[:1]
            opening = first.cash_register_balance_start if first else 0.0
            # Expected = what Odoo expected at the last closing (before its own diff line)
            expected = opening + cash_sales + sum(lines.mapped('amount')) - diff_lines_total - system_total
            closed = sessions.filtered(lambda s: s.state == 'closed').sorted('stop_at')
            # several sessions in one day: each closing counted its own drawer; the last count is the drawer
            counted = closed[-1].cash_register_balance_end_real if closed else 0.0
            difference = sum(sessions.mapped('cash_register_difference'))

            day.write({
                'opening_cash': opening,
                'cash_sales': cash_sales,
                'non_cash_total': non_cash,
                'total_sales': cash_sales + non_cash,
                'cash_in_total': totals.get('cash_in', 0.0),
                'expense_total': -(totals.get('expense', 0.0) + totals.get('advance', 0.0) + totals.get('salary', 0.0)
                                   + totals.get('bank_deposit', 0.0) + totals.get('other', 0.0)),
                'safe_transfer_total': -totals.get('safe_transfer', 0.0),
                'refund_total': -totals.get('refund', 0.0),
                'uncategorised_total': uncategorised,
                'uncategorised_count': uncategorised_count,
                'expected_cash': expected,
                'counted_cash': counted,
                'difference': difference,
                'closing_notes': '\n'.join(filter(None, sessions.mapped('closing_notes'))),
            })
            # summary lines
            day.summary_line_ids.unlink()
            self.env['cz.cash.day.line'].create([{
                'day_id': day.id, 'category_id': cat_id,
                'count': v['count'], 'amount': v['amount'],
            } for cat_id, v in per_cat.items()])
            day._compute_alerts()
            if day.state == 'open' and day.all_sessions_closed:
                day.state = 'to_approve'

    def _compute_alerts(self):
        for day in self:
            alerts = []  # (level, text)
            cur = day.currency_id
            cfg = day.config_id
            closed = day.session_ids.filtered(lambda s: s.state == 'closed')
            if closed and float_is_zero(day.counted_cash, precision_rounding=cur.rounding) and day.cash_sales > 0:
                alerts.append(('danger', _("Counted cash is 0 although cash sales were %s — cashier skipped the count.",
                                           cur.format(day.cash_sales))))
            if abs(day.difference) > (cfg.cz_diff_pin_above or 50.0):
                alerts.append(('danger' if abs(day.difference) > 1000 else 'warning',
                               _("Cash difference of %s at closing.", cur.format(day.difference))))
            if day.uncategorised_count:
                alerts.append(('warning', _("%(n)s cash movement(s) without category (%(amt)s).",
                                            n=day.uncategorised_count, amt=cur.format(day.uncategorised_total))))
            if day.state != 'open' and closed and not any(day.statement_line_ids.filtered(
                    lambda l: l.cz_category_id.kind == 'safe_transfer')) and day.cash_sales > 5000:
                alerts.append(('warning', _("No transfer to the safe was recorded although cash sales were %s.",
                                            cur.format(day.cash_sales))))
            for line in day.statement_line_ids:
                cat = line.cz_category_id
                if cat and cat.typical_amount and abs(line.amount) > 2 * cat.typical_amount:
                    alerts.append(('warning', _("Unusual %(cat)s: %(amt)s (typical %(typ)s) — %(ref)s",
                                                cat=cat.name, amt=cur.format(abs(line.amount)),
                                                typ=cur.format(cat.typical_amount), ref=line.payment_ref)))
                if cat and cat.requires_receipt_above and abs(line.amount) > cat.requires_receipt_above and not line.cz_receipt_ref:
                    alerts.append(('warning', _("Missing receipt number: %s", line.payment_ref)))
            if day.excel_cash_sales and abs(day.excel_diff) > 1:
                alerts.append(('warning', _("Excel cash sales differ from POS by %s.", cur.format(day.excel_diff))))
            if day.state == 'to_approve' and (fields.Date.today() - day.date).days > 2:
                alerts.append(('warning', _("Waiting for approval for %s days.", (fields.Date.today() - day.date).days)))

            level = 'ok'
            if any(a[0] == 'danger' for a in alerts):
                level = 'danger'
            elif alerts:
                level = 'warning'
            html = ''
            if alerts:
                html = Markup('<ul class="mb-0">') + Markup('').join(
                    Markup('<li class="text-%s">%s</li>') % (a[0], a[1]) for a in alerts) + Markup('</ul>')
            day.write({'alert_level': level, 'alert_html': html, 'alert_count': len(alerts)})

    # ------------------------------------------------------------------ events
    def _on_session_closed(self, session):
        """Notify accountants/managers and open an approval activity."""
        self.ensure_one()
        cfg = self.config_id
        cur = self.currency_id
        body = Markup(_(
            "<b>%(pos)s — %(date)s</b> closed by %(user)s.<br/>"
            "Cash sales: %(sales)s · Expenses: %(exp)s · To safe: %(safe)s · "
            "Expected: %(expected)s · Counted: %(counted)s · <b>Difference: %(diff)s</b>")) % {
            'pos': cfg.name, 'date': self.date, 'user': session.user_id.name,
            'sales': cur.format(self.cash_sales), 'exp': cur.format(self.expense_total),
            'safe': cur.format(self.safe_transfer_total), 'expected': cur.format(self.expected_cash),
            'counted': cur.format(self.counted_cash), 'diff': cur.format(self.difference)}
        if self.alert_html:
            body += Markup('<br/>') + Markup(self.alert_html)
        partners = (cfg.cz_accountant_ids | cfg.cz_manager_ids).partner_id
        self.message_post(body=body, partner_ids=partners.ids, subtype_xmlid='mail.mt_comment')
        for user in cfg.cz_accountant_ids:
            if not self.activity_ids.filtered(lambda a: a.user_id == user):
                self.activity_schedule('mail.mail_activity_data_todo', user_id=user.id,
                                       summary=_('Approve daily cash sheet'),
                                       date_deadline=fields.Date.today() + timedelta(days=1))

    # ------------------------------------------------------------------ actions
    def action_refresh(self):
        self._compute_all()
        return True

    def action_approve(self):
        for day in self:
            day._compute_all()
            if day.state == 'approved':
                continue
            if not day.all_sessions_closed:
                raise UserError(_("All POS sessions of %s must be closed first.", day.name))
            if day.uncategorised_count:
                raise UserError(_("%(n)s cash movement(s) have no category. Set a category on each line before approving.",
                                  n=day.uncategorised_count))
            if day.difference_action == 'reclass' and not day.difference_account_id:
                raise UserError(_("Choose the account for the difference."))
            if day.difference_action == 'to_safe' and not day.safe_id:
                raise UserError(_("No branch safe is configured on %s.", day.config_id.name))
            day._post_counterparts()
            day._post_difference()
            day.sudo().statement_line_ids.with_context(cz_approval=True).write({'cz_approved': True})
            day.write({'state': 'approved', 'approved_by': self.env.uid, 'approved_at': fields.Datetime.now()})
            day.activity_ids.action_feedback(feedback=_('Approved'))
            day.message_post(body=_("Daily cash sheet approved by %s. Counterparts posted.", self.env.user.name))
        return True

    def _post_counterparts(self):
        self.ensure_one()
        safe = self.safe_id
        safe_transfer_total = 0.0
        for line in self.statement_line_ids.sudo():
            if self._is_diff_line(line) or self._is_system_line(line):
                continue
            cat = line.cz_category_id
            if cat.kind == 'safe_transfer':
                if not safe:
                    raise UserError(_("No branch safe is configured on %s.", self.config_id.name))
                account = safe.transfer_account_id
                safe_transfer_total += -line.amount
            else:
                account = cat.account_id
            line._cz_set_counterpart(account, label=line.payment_ref)
        if safe and not float_is_zero(safe_transfer_total, precision_rounding=self.currency_id.rounding):
            self._create_safe_in(safe_transfer_total, _("Drawer → safe transfer (%s)", self.name))

    def _create_safe_in(self, amount, note):
        self.ensure_one()
        move = self.env['cz.cash.safe.move'].sudo().create({
            'safe_id': self.safe_id.id,
            'date': self.date,
            'move_type': 'in',
            'amount': amount,
            'note': note,
            'origin_day_id': self.id,
        })
        move.action_approve()
        return move

    def _post_difference(self):
        self.ensure_one()
        if float_is_zero(self.difference, precision_rounding=self.currency_id.rounding):
            return
        diff_lines = self.statement_line_ids.sudo().filtered(lambda l: self._is_diff_line(l))
        if self.difference_action == 'keep' or not diff_lines:
            return
        if self.difference_action == 'to_safe':
            account = self.safe_id.transfer_account_id
            label = _("Cash moved to safe without cash-out — %s", self.difference_note or self.name)
            for line in diff_lines:
                line._cz_set_counterpart(account, label=label)
            # the shortage in the drawer is cash sitting in the safe
            self._create_safe_in(-self.difference, label)
        elif self.difference_action == 'reclass':
            label = self.difference_note or _("Cash difference reclassified")
            for line in diff_lines:
                line._cz_set_counterpart(self.difference_account_id, label=label)

    def action_set_to_approve(self):
        for day in self:
            if day.state == 'open' and day.all_sessions_closed:
                day.state = 'to_approve'

    def action_open_statement_lines(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cash Movements — %s', self.name),
            'res_model': 'account.bank.statement.line',
            'view_mode': 'list,form',
            'domain': [('cz_day_id', '=', self.id)],
            'context': {'create': 0},
        }

    def unlink(self):
        if any(d.state == 'approved' for d in self):
            raise UserError(_("Approved daily cash sheets cannot be deleted."))
        return super().unlink()

    # ------------------------------------------------------------------ cron
    @api.model
    def _cron_daily(self):
        """Refresh open sheets, chase unapproved ones, check safes."""
        for day in self.search([('state', 'in', ('open', 'to_approve'))]):
            day._compute_all()
            if day.state == 'to_approve' and (fields.Date.today() - day.date).days >= 2:
                partners = (day.config_id.cz_accountant_ids | day.config_id.cz_manager_ids).partner_id
                day.message_post(body=_("Reminder: this daily cash sheet is still waiting for approval."),
                                 partner_ids=partners.ids, subtype_xmlid='mail.mt_comment')
        self.env['cz.cash.safe'].search([])._check_alerts()
        return True


class CzCashDayLine(models.Model):
    _name = 'cz.cash.day.line'
    _description = 'Daily Cash Sheet — Category Summary'
    _order = 'amount'

    day_id = fields.Many2one('cz.cash.day', required=True, ondelete='cascade', index=True)
    date = fields.Date(related='day_id.date', store=True)
    config_id = fields.Many2one(related='day_id.config_id', store=True)
    company_id = fields.Many2one(related='day_id.company_id', store=True)
    currency_id = fields.Many2one(related='day_id.currency_id')
    category_id = fields.Many2one('cz.cash.category', required=True)
    kind = fields.Selection(related='category_id.kind', store=True)
    count = fields.Integer()
    amount = fields.Monetary(currency_field='currency_id', help="Signed: negative = cash out.")
