# -*- coding: utf-8 -*-
"""
Form 990 — Return of Organization Exempt from Income Tax
IRS Annual Filing for 501(c)(3) Nonprofits

Data Sources mapped to Odoo modules:
  Part I   - Summary             → account (P&L), res.company
  Part II  - Signature           → res.users
  Part IV  - Checklist           → manual fields on this model
  Part VI  - Governance          → manual fields
  Part VII - Compensation        → hr.payslip / hr.employee (if HR installed)
  Part VIII- Statement of Revenue→ account.move.line (analytic, income accounts)
  Part IX  - Statement of Expenses→account.move.line (expense accounts by function)
  Part X   - Balance Sheet       → account.move.line (assets/liabilities)
  Schedule I - Grants & Assistance → grant.grant (this module)
"""
from odoo import models, fields, api
from odoo.exceptions import ValidationError
import datetime


class Form990(models.Model):
    _name = 'form.990'
    _description = 'IRS Form 990 — Annual Nonprofit Tax Return'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'display_name_computed'
    _order = 'tax_year desc'

    # ── Identity ──────────────────────────────────────────────────────
    tax_year = fields.Integer(
        string='Tax Year', required=True,
        default=lambda self: datetime.date.today().year - 1,
        tracking=True,
        help='The fiscal/calendar year this return covers.')
    fiscal_year_start = fields.Date(string='Fiscal Year Start', required=True)
    fiscal_year_end   = fields.Date(string='Fiscal Year End',   required=True)
    state = fields.Selection([
        ('draft',     'Draft'),
        ('in_review', 'In Review'),
        ('approved',  'Board Approved'),
        ('filed',     'Filed with IRS'),
        ('accepted',  'IRS Accepted'),
    ], string='Status', default='draft', tracking=True, copy=False)

    display_name_computed = fields.Char(
        string='Name', compute='_compute_display_name_computed', store=True)
    reference = fields.Char(
        string='Reference', readonly=True, copy=False, default='New')

    # ── Organisation (Part I header) ─────────────────────────────────
    company_id = fields.Many2one(
        'res.company', string='Organization', required=True,
        default=lambda self: self.env.company)
    ein = fields.Char(
        string='EIN (Employer Identification Number)',
        help='9-digit EIN in format XX-XXXXXXX')
    org_legal_name  = fields.Char(string='Legal Name')
    org_dba         = fields.Char(string='DBA / Trade Name')
    org_address     = fields.Char(string='Street Address')
    org_city        = fields.Char(string='City')
    org_state       = fields.Char(string='State')
    org_zip         = fields.Char(string='ZIP Code')
    org_phone       = fields.Char(string='Phone')
    org_website     = fields.Char(string='Website')
    org_type = fields.Selection([
        ('501c3', '501(c)(3) Public Charity'),
        ('501c3_pf', '501(c)(3) Private Foundation'),
        ('501c4', '501(c)(4) Social Welfare'),
        ('501c6', '501(c)(6) Business League'),
        ('other', 'Other Exempt Organization'),
    ], string='Organization Type', default='501c3')
    form_type = fields.Selection([
        ('990',    'Form 990 (Full)'),
        ('990ez',  'Form 990-EZ (Short Form)'),
        ('990n',   'Form 990-N (e-Postcard)'),
        ('990pf',  'Form 990-PF (Private Foundation)'),
    ], string='Form Type', default='990', required=True)

    principal_officer_id = fields.Many2one('res.users', string='Principal Officer / CEO')
    preparer_id          = fields.Many2one('res.users', string='Return Preparer')
    preparer_firm        = fields.Char(string='Preparer Firm Name')

    # ── Part I — Summary ──────────────────────────────────────────────
    mission_statement = fields.Text(
        string='Mission Statement (Part I, Line 1)')
    num_voting_board_members = fields.Integer(
        string='# Voting Board Members', default=0)
    num_independent_board_members = fields.Integer(
        string='# Independent Board Members', default=0)
    num_employees_total   = fields.Integer(string='Total Employees')
    num_volunteers_total  = fields.Integer(string='Total Volunteers')

    # Revenue (Part I lines 8-12) — auto-computed from accounting
    revenue_contributions      = fields.Monetary(
        string='Contributions & Grants', currency_field='currency_id',
        compute='_compute_revenue', store=True)
    revenue_program_services   = fields.Monetary(
        string='Program Service Revenue', currency_field='currency_id',
        compute='_compute_revenue', store=True)
    revenue_investment         = fields.Monetary(
        string='Investment Income', currency_field='currency_id',
        compute='_compute_revenue', store=True)
    revenue_other              = fields.Monetary(
        string='Other Revenue', currency_field='currency_id',
        compute='_compute_revenue', store=True)
    revenue_total              = fields.Monetary(
        string='Total Revenue', currency_field='currency_id',
        compute='_compute_revenue', store=True)

    # Expense (Part I lines 13-17)
    expense_program_services   = fields.Monetary(
        string='Program Service Expenses', currency_field='currency_id',
        compute='_compute_expenses', store=True)
    expense_management         = fields.Monetary(
        string='Management & General Expenses', currency_field='currency_id',
        compute='_compute_expenses', store=True)
    expense_fundraising        = fields.Monetary(
        string='Fundraising Expenses', currency_field='currency_id',
        compute='_compute_expenses', store=True)
    expense_total              = fields.Monetary(
        string='Total Expenses', currency_field='currency_id',
        compute='_compute_expenses', store=True)

    # Net / Balance Sheet (Part I lines 18-22)
    net_assets_beginning       = fields.Monetary(
        string='Net Assets — Beginning of Year', currency_field='currency_id')
    net_assets_end             = fields.Monetary(
        string='Net Assets — End of Year', currency_field='currency_id',
        compute='_compute_net_assets', store=True)
    revenue_less_expenses      = fields.Monetary(
        string='Revenue Less Expenses', currency_field='currency_id',
        compute='_compute_net_assets', store=True)
    total_assets               = fields.Monetary(
        string='Total Assets (End of Year)', currency_field='currency_id')
    total_liabilities          = fields.Monetary(
        string='Total Liabilities (End of Year)', currency_field='currency_id')

    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)

    # ── Part IV — Checklist of Required Schedules ─────────────────────
    has_conservation_easements    = fields.Boolean('Conservation Easements (Sch D)?')
    has_art_collections           = fields.Boolean('Art/Museum Collections (Sch D)?')
    has_escrow_accounts           = fields.Boolean('Escrow/Custodial Accounts (Sch D)?')
    has_endowment_funds           = fields.Boolean('Endowment Funds (Sch D)?')
    has_land_buildings            = fields.Boolean('Land/Buildings/Equipment (Sch D)?')
    has_investments               = fields.Boolean('Investments (Sch D)?')
    has_unrelated_business_income = fields.Boolean('Unrelated Business Income (Form 990-T)?')
    has_related_organizations     = fields.Boolean('Related Organizations (Sch R)?')
    has_grants_to_orgs            = fields.Boolean('Grants to Organizations (Sch I)?')
    has_grants_to_individuals     = fields.Boolean('Grants to Individuals (Sch I)?')
    has_foreign_activities        = fields.Boolean('Foreign Activities (Sch F)?')
    conducts_lobbying             = fields.Boolean('Lobbying Activities (Sch C)?')
    is_school                     = fields.Boolean('School (Sch E)?')
    has_hospital                  = fields.Boolean('Hospital (Sch H)?')

    # ── Part VI — Governance ─────────────────────────────────────────
    has_written_conflict_policy   = fields.Boolean('Written Conflict of Interest Policy?')
    has_whistleblower_policy      = fields.Boolean('Whistleblower Policy?')
    has_document_retention_policy = fields.Boolean('Document Retention/Destruction Policy?')
    board_reviews_form990         = fields.Boolean('Board Reviews Form 990 Before Filing?')
    uses_management_company       = fields.Boolean('Uses Management Company?')
    copiable_to_public            = fields.Boolean('Form 990 Available to Public?', default=True)
    form990_how_available = fields.Selection([
        ('website', 'Posted on Website'),
        ('upon_request', 'Available Upon Request'),
        ('state', 'Through State Filing'),
    ], string='How Available to Public', default='website')

    # ── Part VIII — Statement of Revenue (detailed) ───────────────────
    rev_federated_campaigns        = fields.Monetary(string='Federated Campaign Contributions',    currency_field='currency_id')
    rev_membership_dues            = fields.Monetary(string='Membership Dues',                     currency_field='currency_id')
    rev_fundraising_events         = fields.Monetary(string='Fundraising Events (gross)',           currency_field='currency_id')
    rev_related_orgs               = fields.Monetary(string='Related Organizations',                currency_field='currency_id')
    rev_government_grants          = fields.Monetary(string='Government Grants (contributions)',    currency_field='currency_id')
    rev_other_contributions        = fields.Monetary(string='All Other Contributions & Grants',     currency_field='currency_id')
    rev_program_service_a          = fields.Monetary(string='Program Revenue — Equipment Loans',    currency_field='currency_id')
    rev_program_service_b          = fields.Monetary(string='Program Revenue — Sports Events',      currency_field='currency_id')
    rev_program_service_other      = fields.Monetary(string='Program Revenue — Other',              currency_field='currency_id')
    rev_interest                   = fields.Monetary(string='Interest Income',                      currency_field='currency_id')
    rev_dividends                  = fields.Monetary(string='Dividend & Interest from Securities',  currency_field='currency_id')
    rev_rental_income              = fields.Monetary(string='Rental Income',                        currency_field='currency_id')
    rev_other_revenue              = fields.Monetary(string='Other Revenue (misc)',                  currency_field='currency_id')

    # ── Part IX — Statement of Functional Expenses ────────────────────
    exp_salaries_officers          = fields.Monetary(string='Officer/Director Compensation',        currency_field='currency_id')
    exp_salaries_other             = fields.Monetary(string='Other Salaries & Wages',               currency_field='currency_id')
    exp_pension_benefits           = fields.Monetary(string='Pension Plan Contributions',            currency_field='currency_id')
    exp_other_employee_benefits    = fields.Monetary(string='Other Employee Benefits',               currency_field='currency_id')
    exp_payroll_taxes              = fields.Monetary(string='Payroll Taxes',                         currency_field='currency_id')
    exp_fees_contractors           = fields.Monetary(string='Fees for Services — Contractors',      currency_field='currency_id')
    exp_fees_legal                 = fields.Monetary(string='Fees for Services — Legal',             currency_field='currency_id')
    exp_fees_accounting            = fields.Monetary(string='Fees for Services — Accounting',       currency_field='currency_id')
    exp_advertising                = fields.Monetary(string='Advertising & Promotion',               currency_field='currency_id')
    exp_office                     = fields.Monetary(string='Office Expenses',                       currency_field='currency_id')
    exp_it_technology              = fields.Monetary(string='Information Technology',                currency_field='currency_id')
    exp_royalties                  = fields.Monetary(string='Royalties',                             currency_field='currency_id')
    exp_occupancy                  = fields.Monetary(string='Occupancy (rent/utilities)',            currency_field='currency_id')
    exp_travel                     = fields.Monetary(string='Travel',                                currency_field='currency_id')
    exp_conferences                = fields.Monetary(string='Conferences, Conventions, Meetings',   currency_field='currency_id')
    exp_interest_expense           = fields.Monetary(string='Interest Expense',                      currency_field='currency_id')
    exp_depreciation               = fields.Monetary(string='Depreciation & Amortization',          currency_field='currency_id')
    exp_insurance                  = fields.Monetary(string='Insurance',                             currency_field='currency_id')
    exp_grants_to_orgs             = fields.Monetary(string='Grants to Organizations (domestic)',   currency_field='currency_id')
    exp_grants_to_individuals      = fields.Monetary(string='Grants to Individuals',                currency_field='currency_id')
    exp_other_expenses             = fields.Monetary(string='All Other Expenses',                    currency_field='currency_id')

    # Functional allocation columns
    exp_pct_program   = fields.Float(string='% Program Services',  default=85.0)
    exp_pct_mgmt      = fields.Float(string='% Management',        default=10.0)
    exp_pct_fundraise = fields.Float(string='% Fundraising',       default=5.0)

    # ── Schedule I — Grants & Assistance ─────────────────────────────
    schedule_i_ids = fields.One2many(
        'form.990.schedule.i', 'form990_id', string='Schedule I — Grants')
    schedule_i_total = fields.Monetary(
        string='Schedule I Total', currency_field='currency_id',
        compute='_compute_schedule_i', store=True)

    # ── Program Accomplishments (Part III) ────────────────────────────
    program_accomplishment_ids = fields.One2many(
        'form.990.program', 'form990_id', string='Program Service Accomplishments')

    # ── Filing Info ───────────────────────────────────────────────────
    due_date              = fields.Date(string='Filing Due Date',
                                        compute='_compute_due_date', store=True)
    extension_filed       = fields.Boolean(string='Extension Filed (Form 8868)?')
    extension_due_date    = fields.Date(string='Extended Due Date')
    date_filed            = fields.Date(string='Date Filed with IRS')
    irs_confirmation_num  = fields.Char(string='IRS Confirmation / EIN')
    prior_year_filed      = fields.Boolean(string='Prior Year Return on File?')

    notes = fields.Html(string='Internal Notes & Preparer Instructions')
    active = fields.Boolean(default=True)

    # ── Computed ──────────────────────────────────────────────────────
    @api.depends('tax_year', 'company_id')
    def _compute_display_name_computed(self):
        for r in self:
            r.display_name_computed = (
                f'Form 990 — {r.company_id.name or "Organization"} — FY {r.tax_year}'
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('reference', 'New') == 'New':
                vals['reference'] = (
                    self.env['ir.sequence'].next_by_code('form.990') or 'New'
                )
        return super().create(vals_list)

    def action_view_schedule_i(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Schedule I Grants',
            'res_model': 'form.990.schedule.i',
            'view_mode': 'list,form',
            'domain': [('form990_id', '=', self.id)],
            'context': {'default_form990_id': self.id},
        }

    @api.depends('fiscal_year_end')
    def _compute_due_date(self):
        for r in self:
            if r.fiscal_year_end:
                fy_end = r.fiscal_year_end
                # Due 15th day of the 5th month after fiscal year end
                month = fy_end.month + 5
                year  = fy_end.year + (month - 1) // 12
                month = ((month - 1) % 12) + 1
                r.due_date = datetime.date(year, month, 15)
            else:
                r.due_date = False

    @api.depends('revenue_contributions', 'revenue_program_services',
                 'revenue_investment', 'revenue_other')
    def _compute_revenue(self):
        """
        Pull actual revenue from Odoo Accounting (account.move.line).
        Looks at posted journal entries in the fiscal year date range.
        Account tags / types used:
          - income: account.account.type in ['income', 'other_income']
        For a production system, map specific GL account codes here.
        """
        for r in self:
            if not (r.fiscal_year_start and r.fiscal_year_end and r.company_id):
                r.revenue_total = 0
                r.revenue_contributions = 0
                r.revenue_program_services = 0
                r.revenue_investment = 0
                r.revenue_other = 0
                continue

            domain_base = [
                ('move_id.state', '=', 'posted'),
                ('move_id.company_id', '=', r.company_id.id),
                ('date', '>=', r.fiscal_year_start),
                ('date', '<=', r.fiscal_year_end),
                ('account_id.account_type', 'in', ['income', 'income_other']),
            ]
            lines = self.env['account.move.line'].search(domain_base)

            # Sum credits minus debits (income accounts credit = revenue)
            total = sum(-l.balance for l in lines)

            # Attempt to categorise by account tag name (customize per org)
            contributions = sum(
                -l.balance for l in lines
                if any(t.name in ('Contributions', 'Grants', 'Donations')
                       for t in l.account_id.tag_ids)
            )
            program_svc = sum(
                -l.balance for l in lines
                if any(t.name in ('Program Services', 'Program Revenue')
                       for t in l.account_id.tag_ids)
            )
            investment = sum(
                -l.balance for l in lines
                if any(t.name in ('Investment', 'Interest', 'Dividends')
                       for t in l.account_id.tag_ids)
            )
            other = total - contributions - program_svc - investment

            r.revenue_contributions    = max(contributions, 0)
            r.revenue_program_services = max(program_svc, 0)
            r.revenue_investment       = max(investment, 0)
            r.revenue_other            = max(other, 0)
            r.revenue_total            = max(total, 0)

    @api.depends('expense_program_services', 'expense_management', 'expense_fundraising')
    def _compute_expenses(self):
        """Pull actual expenses from posted journal entries."""
        for r in self:
            if not (r.fiscal_year_start and r.fiscal_year_end and r.company_id):
                r.expense_program_services = 0
                r.expense_management = 0
                r.expense_fundraising = 0
                r.expense_total = 0
                continue

            domain_base = [
                ('move_id.state', '=', 'posted'),
                ('move_id.company_id', '=', r.company_id.id),
                ('date', '>=', r.fiscal_year_start),
                ('date', '<=', r.fiscal_year_end),
                ('account_id.account_type', 'in', ['expense', 'expense_depreciation', 'expense_direct_cost']),
            ]
            lines = self.env['account.move.line'].search(domain_base)
            total = sum(l.balance for l in lines)

            # Functional expense allocation using exp_pct fields
            r.expense_program_services = total * (r.exp_pct_program   / 100)
            r.expense_management       = total * (r.exp_pct_mgmt      / 100)
            r.expense_fundraising      = total * (r.exp_pct_fundraise  / 100)
            r.expense_total            = total

    @api.depends('net_assets_beginning', 'revenue_total', 'expense_total')
    def _compute_net_assets(self):
        for r in self:
            r.revenue_less_expenses = r.revenue_total - r.expense_total
            r.net_assets_end = r.net_assets_beginning + r.revenue_less_expenses

    @api.depends('schedule_i_ids.amount_cash', 'schedule_i_ids.amount_noncash')
    def _compute_schedule_i(self):
        for r in self:
            r.schedule_i_total = sum(
                l.amount_cash + l.amount_noncash for l in r.schedule_i_ids
            )

    # ── Actions ───────────────────────────────────────────────────────
    def action_populate_from_accounting(self):
        """Trigger recompute of all accounting-sourced fields."""
        self._compute_revenue()
        self._compute_expenses()
        self._compute_net_assets()
        return True

    def action_populate_schedule_i(self):
        """Auto-populate Schedule I from active grant.grant records."""
        self.ensure_one()
        if not (self.fiscal_year_start and self.fiscal_year_end):
            raise ValidationError(
                'Set Fiscal Year Start and End before auto-populating Schedule I.'
            )
        # Remove existing auto lines
        self.schedule_i_ids.filtered(lambda l: l.source == 'auto').unlink()

        grants = self.env['grant.grant'].search([
            ('company_id', '=', self.company_id.id),
            ('award_date', '>=', self.fiscal_year_start),
            ('award_date', '<=', self.fiscal_year_end),
            ('state', 'in', ['active', 'reporting', 'closed', 'awarded']),
        ])
        lines = []
        for g in grants:
            lines.append({
                'form990_id': self.id,
                'recipient_name': g.funder_id.name if g.funder_id else g.name,
                'recipient_ein': '',
                'recipient_address': '',
                'recipient_city': '',
                'recipient_state': '',
                'purpose': g.name,
                'amount_cash': g.awarded_amount,
                'amount_noncash': 0.0,
                'description': g.grant_type or '',
                'grant_id': g.id,
                'source': 'auto',
            })
        self.env['form.990.schedule.i'].create(lines)
        self.message_post(
            body=f'Schedule I auto-populated: {len(lines)} grant(s) pulled from Grant Management.',
            message_type='notification',
        )

    def action_submit_for_review(self):
        self.write({'state': 'in_review'})

    def action_board_approve(self):
        self.write({'state': 'approved'})

    def action_mark_filed(self):
        self.write({'state': 'filed', 'date_filed': fields.Date.today()})

    def action_mark_accepted(self):
        self.write({'state': 'accepted'})

    @api.constrains('tax_year', 'company_id')
    def _check_unique_year(self):
        for r in self:
            duplicate = self.search([
                ('tax_year', '=', r.tax_year),
                ('company_id', '=', r.company_id.id),
                ('id', '!=', r.id),
            ])
            if duplicate:
                raise ValidationError(
                    f'A Form 990 for tax year {r.tax_year} already exists for this organization.'
                )


class Form990ScheduleI(models.Model):
    """Schedule I — Grants and Other Assistance to Organizations, Governments, and Individuals."""
    _name = 'form.990.schedule.i'
    _description = 'Form 990 Schedule I — Grants'
    _order = 'amount_cash desc'

    form990_id      = fields.Many2one('form.990', string='Form 990', required=True, ondelete='cascade')
    grant_id        = fields.Many2one('grant.grant', string='Linked Grant', ondelete='set null')
    source          = fields.Selection([('auto', 'Auto-populated'), ('manual', 'Manual')],
                                       default='manual')

    # Schedule I fields per IRS form layout
    recipient_name    = fields.Char(string='Recipient Name', required=True)
    recipient_ein     = fields.Char(string='Recipient EIN')
    recipient_irc     = fields.Char(string='IRC Section (if applicable)')
    recipient_address = fields.Char(string='Recipient Address')
    recipient_city    = fields.Char(string='City')
    recipient_state   = fields.Char(string='State')
    recipient_zip     = fields.Char(string='ZIP')
    recipient_type = fields.Selection([
        ('public_charity', 'Public Charity'),
        ('private_foundation', 'Private Foundation'),
        ('government', 'Government Entity'),
        ('individual', 'Individual'),
        ('other', 'Other'),
    ], string='Recipient Type', default='public_charity')

    purpose           = fields.Char(string='Purpose of Grant', required=True)
    amount_cash       = fields.Monetary(string='Amount of Cash Grant',   currency_field='currency_id')
    amount_noncash    = fields.Monetary(string='Amount of Non-Cash',     currency_field='currency_id')
    noncash_desc      = fields.Char(string='Non-Cash Description')
    description       = fields.Char(string='Method of Valuation')
    currency_id       = fields.Many2one(related='form990_id.currency_id', store=True)
    total             = fields.Monetary(string='Total', currency_field='currency_id',
                                        compute='_compute_total', store=True)

    @api.depends('amount_cash', 'amount_noncash')
    def _compute_total(self):
        for r in self:
            r.total = r.amount_cash + r.amount_noncash


class Form990Program(models.Model):
    """Part III — Statement of Program Service Accomplishments."""
    _name = 'form.990.program'
    _description = 'Form 990 Program Service Accomplishment'
    _order = 'sequence'

    form990_id    = fields.Many2one('form.990', required=True, ondelete='cascade')
    sequence      = fields.Integer(default=10)
    program_name  = fields.Char(string='Program Name', required=True)
    description   = fields.Text(string='Program Description & Accomplishments', required=True)
    expense_amount= fields.Monetary(string='Program Expenses', currency_field='currency_id')
    grant_amount  = fields.Monetary(string='Grants Included', currency_field='currency_id')
    revenue_amount= fields.Monetary(string='Revenue from Program', currency_field='currency_id')
    currency_id   = fields.Many2one(related='form990_id.currency_id', store=True)
    is_new        = fields.Boolean(string='New Program This Year?')
