# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class Grant(models.Model):
    """
    Core grant record. Represents an awarded or active grant.
    Covers pre-award through post-award lifecycle.
    Integrates with:
      - Analytic Accounts (expense tracking per grant)
      - Project (milestones & deliverables)
      - Accounting (journal entries, invoices)
    """
    _name = 'grant.grant'
    _description = 'Grant'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'project_end_date asc, name asc'

    # ─── Identification ────────────────────────────────────────────────
    name = fields.Char(string='Grant Name', required=True, tracking=True)
    reference = fields.Char(string='Grant Reference', readonly=True, copy=False, default='New')
    funder_reference = fields.Char(string='Funder Award Reference', tracking=True)

    funder_id = fields.Many2one('grant.funder', string='Funder', required=True,
                                ondelete='restrict', tracking=True)
    opportunity_id = fields.Many2one('grant.opportunity', string='Source Opportunity',
                                     readonly=True)
    focus_area_ids = fields.Many2many('grant.focus.area', string='Focus / Program Areas')

    # ─── State & Stage ─────────────────────────────────────────────────
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Application Submitted'),
        ('under_review', 'Under Review'),
        ('awarded', 'Awarded'),
        ('active', 'Active / In Progress'),
        ('reporting', 'In Reporting Period'),
        ('closed', 'Closed'),
        ('declined', 'Declined'),
    ], string='Status', default='draft', tracking=True, copy=False)

    kanban_state = fields.Selection([
        ('normal', 'On Track'),
        ('done', 'Ready for Next Stage'),
        ('blocked', 'Blocked'),
    ], string='Kanban State', default='normal', tracking=True)

    # ─── Financials ────────────────────────────────────────────────────
    currency_id = fields.Many2one('res.currency', required=True,
                                  default=lambda self: self.env.company.currency_id)
    requested_amount = fields.Monetary(string='Requested Amount', currency_field='currency_id',
                                       tracking=True)
    awarded_amount = fields.Monetary(string='Awarded Amount', currency_field='currency_id',
                                     tracking=True)
    budget_total = fields.Monetary(string='Approved Budget', currency_field='currency_id',
                                   tracking=True)
    match_required = fields.Boolean(string='Match/Cost-Share Required')
    match_amount = fields.Monetary(string='Required Match Amount', currency_field='currency_id')
    match_type = fields.Selection([
        ('cash', 'Cash Match'),
        ('in_kind', 'In-Kind Match'),
        ('both', 'Cash + In-Kind'),
    ], string='Match Type')

    # Computed financials
    total_expenses = fields.Monetary(string='Total Expenses Charged',
                                     compute='_compute_financials', store=True,
                                     currency_field='currency_id')
    remaining_budget = fields.Monetary(string='Remaining Budget',
                                       compute='_compute_financials', store=True,
                                       currency_field='currency_id')
    budget_utilization = fields.Float(string='Budget Utilization %',
                                      compute='_compute_financials', store=True)
    total_received = fields.Monetary(string='Total Funds Received',
                                     compute='_compute_financials', store=True,
                                     currency_field='currency_id')

    # ─── Dates ─────────────────────────────────────────────────────────
    application_date = fields.Date(string='Application Date', tracking=True)
    award_date = fields.Date(string='Award Date', tracking=True)
    project_start_date = fields.Date(string='Project Start Date', required=True, tracking=True)
    project_end_date = fields.Date(string='Project End Date', required=True, tracking=True)
    close_date = fields.Date(string='Actual Close Date')
    next_report_due = fields.Date(string='Next Report Due', compute='_compute_next_report_due',
                                  store=True)

    days_remaining = fields.Integer(string='Days Remaining', compute='_compute_days_remaining')
    is_overdue = fields.Boolean(compute='_compute_days_remaining')

    # ─── Team & Responsibility ─────────────────────────────────────────
    grant_writer_id = fields.Many2one('res.users', string='Grant Writer',
                                      default=lambda self: self.env.user)
    program_manager_id = fields.Many2one('res.users', string='Program Manager', tracking=True)
    finance_contact_id = fields.Many2one('res.users', string='Finance Contact')
    executive_approver_id = fields.Many2one('res.users', string='Executive Approver')

    # ─── Grant Type & Requirements ─────────────────────────────────────
    grant_type = fields.Selection([
        ('restricted', 'Restricted (Program-Specific)'),
        ('unrestricted', 'Unrestricted (General Operating)'),
        ('matching', 'Matching Grant'),
        ('capacity_building', 'Capacity Building'),
        ('equipment', 'Equipment / In-Kind'),
        ('research', 'Research'),
        ('other', 'Other'),
    ], string='Grant Type', default='restricted', tracking=True)

    reporting_frequency = fields.Selection([
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('semi_annual', 'Semi-Annual'),
        ('annual', 'Annual'),
        ('final_only', 'Final Report Only'),
        ('milestone', 'Milestone-Based'),
    ], string='Reporting Frequency', default='quarterly')

    reporting_requirements = fields.Text(string='Reporting Requirements & Conditions')
    allowable_expenses = fields.Text(string='Allowable Expense Categories')
    restrictions = fields.Text(string='Restrictions & Compliance Notes')

    # ─── Integrations ──────────────────────────────────────────────────
    analytic_account_id = fields.Many2one('account.analytic.account',
                                          string='Analytic Account',
                                          help='Auto-created on award. All expenses coded '
                                               'to this account are tracked against this grant.')
    project_id = fields.Many2one('project.project', string='Linked Project',
                                 help='Project for milestone and deliverable tracking.')

    # ─── Related Records ───────────────────────────────────────────────
    milestone_ids = fields.One2many('grant.milestone', 'grant_id', string='Milestones')
    budget_line_ids = fields.One2many('grant.budget.line', 'grant_id', string='Budget Lines')
    report_ids = fields.One2many('grant.report', 'grant_id', string='Reports')
    payment_ids = fields.One2many('grant.payment', 'grant_id', string='Payment Schedule')

    milestone_count = fields.Integer(compute='_compute_counts')
    report_count = fields.Integer(compute='_compute_counts')
    payment_count = fields.Integer(compute='_compute_counts')
    overdue_milestone_count = fields.Integer(compute='_compute_counts')

    notes = fields.Html(string='Internal Notes')
    active = fields.Boolean(default=True)

    # ─── Computed ──────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('reference', 'New') == 'New':
                vals['reference'] = self.env['ir.sequence'].next_by_code('grant.grant') or 'New'
        return super().create(vals_list)

    @api.depends('budget_line_ids.actual_amount', 'payment_ids.amount',
                 'payment_ids.state', 'budget_total')
    def _compute_financials(self):
        for grant in self:
            expenses = sum(grant.budget_line_ids.mapped('actual_amount'))
            received = sum(
                p.amount for p in grant.payment_ids if p.state == 'received'
            )
            grant.total_expenses = expenses
            grant.total_received = received
            grant.remaining_budget = (grant.budget_total or 0) - expenses
            if grant.budget_total:
                grant.budget_utilization = (expenses / grant.budget_total) * 100
            else:
                grant.budget_utilization = 0.0

    @api.depends('project_end_date')
    def _compute_days_remaining(self):
        today = fields.Date.today()
        for grant in self:
            if grant.project_end_date:
                delta = (grant.project_end_date - today).days
                grant.days_remaining = delta
                grant.is_overdue = delta < 0 and grant.state not in ('closed', 'declined')
            else:
                grant.days_remaining = 0
                grant.is_overdue = False

    @api.depends('report_ids', 'report_ids.due_date', 'report_ids.state')
    def _compute_next_report_due(self):
        today = fields.Date.today()
        for grant in self:
            pending = grant.report_ids.filtered(
                lambda r: r.state in ('pending', 'in_progress') and r.due_date >= today
            ).sorted('due_date')
            grant.next_report_due = pending[0].due_date if pending else False

    @api.depends('milestone_ids', 'report_ids', 'payment_ids')
    def _compute_counts(self):
        today = fields.Date.today()
        for grant in self:
            grant.milestone_count = len(grant.milestone_ids)
            grant.report_count = len(grant.report_ids)
            grant.payment_count = len(grant.payment_ids)
            grant.overdue_milestone_count = len(
                grant.milestone_ids.filtered(
                    lambda m: m.due_date < today and m.state not in ('done', 'cancelled')
                )
            )

    # ─── Workflow Actions ───────────────────────────────────────────────
    def action_submit(self):
        self.write({'state': 'submitted', 'application_date': fields.Date.today()})

    def action_under_review(self):
        self.write({'state': 'under_review'})

    def action_award(self):
        self.ensure_one()
        if not self.awarded_amount:
            raise ValidationError('Please enter the awarded amount before marking as awarded.')
        # Auto-create analytic account if not present
        if not self.analytic_account_id:
            analytic = self.env['account.analytic.account'].create({
                'name': f'{self.reference} - {self.name}',
                'plan_id': self.env.ref('analytic.analytic_plan_projects', raise_if_not_found=False) and
                           self.env.ref('analytic.analytic_plan_projects').id,
                'partner_id': self.funder_id.partner_id.id if self.funder_id.partner_id else False,
            })
            self.analytic_account_id = analytic
        self.write({
            'state': 'active',
            'award_date': fields.Date.today(),
            'budget_total': self.awarded_amount,
        })
        self.message_post(
            body=f'<b>Grant Awarded!</b> Amount: {self.currency_id.symbol}{self.awarded_amount:,.2f}. '
                 f'Analytic account <b>{self.analytic_account_id.name}</b> created for expense tracking.',
            message_type='notification',
        )

    def action_set_reporting(self):
        self.write({'state': 'reporting'})

    def action_close(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Close Grant',
            'res_model': 'grant.close.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_grant_id': self.id},
        }

    def action_decline(self):
        self.write({'state': 'declined'})

    def action_view_milestones(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Milestones',
            'res_model': 'grant.milestone',
            'view_mode': 'list,form',
            'domain': [('grant_id', '=', self.id)],
            'context': {'default_grant_id': self.id},
        }

    def action_view_reports(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Grant Reports',
            'res_model': 'grant.report',
            'view_mode': 'list,form',
            'domain': [('grant_id', '=', self.id)],
            'context': {'default_grant_id': self.id},
        }


class GrantBudgetLine(models.Model):
    _name = 'grant.budget.line'
    _description = 'Grant Budget Line Item'
    _order = 'sequence, name'

    grant_id = fields.Many2one('grant.grant', string='Grant', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Budget Category', required=True)
    description = fields.Text(string='Description')

    expense_category = fields.Selection([
        ('personnel', 'Personnel / Salaries'),
        ('fringe', 'Fringe Benefits'),
        ('travel', 'Travel'),
        ('equipment', 'Equipment'),
        ('supplies', 'Supplies & Materials'),
        ('contractual', 'Contractual / Consultants'),
        ('indirect', 'Indirect / Overhead'),
        ('other_direct', 'Other Direct Costs'),
    ], string='Expense Category', required=True)

    currency_id = fields.Many2one(related='grant_id.currency_id', store=True)
    budgeted_amount = fields.Monetary(string='Budgeted Amount', currency_field='currency_id')
    actual_amount = fields.Monetary(string='Actual Spent', currency_field='currency_id')
    variance = fields.Monetary(string='Variance', compute='_compute_variance',
                               currency_field='currency_id', store=True)
    utilization_pct = fields.Float(string='Utilization %', compute='_compute_variance', store=True)

    analytic_account_id = fields.Many2one(related='grant_id.analytic_account_id', store=True)
    notes = fields.Text(string='Notes')

    @api.depends('budgeted_amount', 'actual_amount')
    def _compute_variance(self):
        for line in self:
            line.variance = line.budgeted_amount - line.actual_amount
            if line.budgeted_amount:
                line.utilization_pct = (line.actual_amount / line.budgeted_amount) * 100
            else:
                line.utilization_pct = 0.0


class GrantPayment(models.Model):
    _name = 'grant.payment'
    _description = 'Grant Payment Schedule'

    grant_id = fields.Many2one('grant.grant', string='Grant', required=True, ondelete='cascade')
    name = fields.Char(string='Payment Description', required=True)
    payment_type = fields.Selection([
        ('advance', 'Advance / Upfront'),
        ('reimbursement', 'Reimbursement'),
        ('milestone_based', 'Milestone-Based'),
        ('installment', 'Installment'),
        ('final', 'Final Payment'),
    ], string='Payment Type', default='installment')

    currency_id = fields.Many2one(related='grant_id.currency_id', store=True)
    amount = fields.Monetary(string='Amount', currency_field='currency_id')
    expected_date = fields.Date(string='Expected Date')
    received_date = fields.Date(string='Date Received')
    state = fields.Selection([
        ('scheduled', 'Scheduled'),
        ('invoiced', 'Invoiced / Requested'),
        ('received', 'Received'),
        ('overdue', 'Overdue'),
    ], string='Status', default='scheduled')

    linked_milestone_id = fields.Many2one('grant.milestone', string='Linked Milestone')
    journal_entry_id = fields.Many2one('account.move', string='Journal Entry')
    notes = fields.Text(string='Notes')


class GrantReport(models.Model):
    _name = 'grant.report'
    _description = 'Grant Progress / Compliance Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    grant_id = fields.Many2one('grant.grant', string='Grant', required=True, ondelete='cascade')
    name = fields.Char(string='Report Name', required=True)
    report_type = fields.Selection([
        ('progress', 'Progress Report'),
        ('financial', 'Financial Report'),
        ('combined', 'Combined Progress & Financial'),
        ('final', 'Final Report'),
        ('interim', 'Interim Report'),
    ], string='Report Type', default='progress')

    due_date = fields.Date(string='Due Date', required=True, tracking=True)
    submitted_date = fields.Date(string='Date Submitted', tracking=True)
    period_start = fields.Date(string='Reporting Period Start')
    period_end = fields.Date(string='Reporting Period End')

    state = fields.Selection([
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('submitted', 'Submitted'),
        ('accepted', 'Accepted by Funder'),
        ('revision_required', 'Revision Required'),
    ], string='Status', default='pending', tracking=True)

    is_overdue = fields.Boolean(compute='_compute_overdue')
    prepared_by_id = fields.Many2one('res.users', string='Prepared By',
                                     default=lambda self: self.env.user)
    approved_by_id = fields.Many2one('res.users', string='Approved By')

    narrative = fields.Html(string='Program Narrative / Outcomes')
    financial_summary = fields.Html(string='Financial Summary')
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments')
    notes = fields.Text(string='Internal Notes')

    @api.depends('due_date', 'state')
    def _compute_overdue(self):
        today = fields.Date.today()
        for r in self:
            r.is_overdue = (
                r.due_date and r.due_date < today and
                r.state not in ('submitted', 'accepted')
            )

    def action_submit(self):
        self.write({'state': 'submitted', 'submitted_date': fields.Date.today()})
