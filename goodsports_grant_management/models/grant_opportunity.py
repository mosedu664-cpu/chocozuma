# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class GrantOpportunity(models.Model):
    """
    Tracks potential grants in the research/prospecting stage before
    a formal application is submitted. Functions like a CRM pipeline
    for grant opportunities.
    """
    _name = 'grant.opportunity'
    _description = 'Grant Opportunity (Pre-Application)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'deadline asc, name asc'

    name = fields.Char(string='Opportunity Name', required=True, tracking=True)
    reference = fields.Char(string='Reference', readonly=True, copy=False,
                            default='New')

    funder_id = fields.Many2one('grant.funder', string='Funder', required=True, tracking=True)
    focus_area_ids = fields.Many2many('grant.focus.area', string='Focus Areas')

    stage_id = fields.Many2one('grant.opportunity.stage', string='Stage',
                               default=lambda self: self.env['grant.opportunity.stage'].search([], limit=1),
                               group_expand='_read_group_stage_ids', tracking=True)
    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'Normal'),
        ('2', 'High'),
        ('3', 'Critical'),
    ], string='Priority', default='1')

    # Amounts
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    estimated_amount = fields.Monetary(string='Estimated Grant Amount', currency_field='currency_id')
    min_amount = fields.Monetary(string='Min Requested', currency_field='currency_id')
    max_amount = fields.Monetary(string='Max Requestable', currency_field='currency_id')

    # Key dates
    deadline = fields.Date(string='Application Deadline', required=True, tracking=True)
    rfp_release_date = fields.Date(string='RFP Release Date')
    award_notification_date = fields.Date(string='Expected Award Notification')
    project_start_date = fields.Date(string='Projected Project Start')
    project_end_date = fields.Date(string='Projected Project End')

    days_to_deadline = fields.Integer(string='Days to Deadline', compute='_compute_days_to_deadline')
    is_past_deadline = fields.Boolean(compute='_compute_days_to_deadline')

    # Responsibility
    grant_writer_id = fields.Many2one('res.users', string='Grant Writer', tracking=True)
    program_manager_id = fields.Many2one('res.users', string='Program Manager')
    reviewed_by_id = fields.Many2one('res.users', string='Reviewed By')

    # Eligibility & fit
    eligibility_check = fields.Selection([
        ('pending', 'Not Checked'),
        ('eligible', 'Eligible'),
        ('ineligible', 'Ineligible'),
        ('conditional', 'Conditionally Eligible'),
    ], string='Eligibility', default='pending', tracking=True)
    fit_score = fields.Integer(string='Strategic Fit Score (1-10)', default=5)
    eligibility_notes = fields.Text(string='Eligibility Notes')

    # Grant type
    grant_type = fields.Selection([
        ('restricted', 'Restricted (Program-Specific)'),
        ('unrestricted', 'Unrestricted (General Operating)'),
        ('matching', 'Matching Grant'),
        ('capacity_building', 'Capacity Building'),
        ('equipment', 'Equipment / In-Kind'),
        ('research', 'Research'),
        ('other', 'Other'),
    ], string='Grant Type', default='restricted')

    reporting_requirements = fields.Text(string='Reporting Requirements')
    notes = fields.Html(string='Research Notes')

    # Outcome
    outcome = fields.Selection([
        ('pending', 'Pending'),
        ('applied', 'Application Submitted'),
        ('awarded', 'Awarded'),
        ('declined', 'Declined by Funder'),
        ('withdrawn', 'Withdrawn by Us'),
        ('not_applied', 'Decided Not to Apply'),
    ], string='Outcome', default='pending', tracking=True)

    grant_id = fields.Many2one('grant.grant', string='Resulting Grant', readonly=True)
    active = fields.Boolean(default=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('reference', 'New') == 'New':
                vals['reference'] = self.env['ir.sequence'].next_by_code('grant.opportunity') or 'New'
        return super().create(vals_list)

    @api.depends('deadline')
    def _compute_days_to_deadline(self):
        today = fields.Date.today()
        for rec in self:
            if rec.deadline:
                delta = (rec.deadline - today).days
                rec.days_to_deadline = delta
                rec.is_past_deadline = delta < 0
            else:
                rec.days_to_deadline = 0
                rec.is_past_deadline = False

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        return stages.search([], order=stages._order)

    def action_convert_to_grant(self):
        """Convert approved opportunity into a live grant record."""
        self.ensure_one()
        if self.grant_id:
            raise UserError('A grant has already been created from this opportunity.')
        grant = self.env['grant.grant'].create({
            'name': self.name,
            'funder_id': self.funder_id.id,
            'opportunity_id': self.id,
            'grant_writer_id': self.grant_writer_id.id,
            'program_manager_id': self.program_manager_id.id,
            'requested_amount': self.estimated_amount,
            'currency_id': self.currency_id.id,
            'focus_area_ids': [(6, 0, self.focus_area_ids.ids)],
            'project_start_date': self.project_start_date,
            'project_end_date': self.project_end_date,
            'grant_type': self.grant_type,
            'reporting_requirements': self.reporting_requirements,
        })
        self.grant_id = grant.id
        self.outcome = 'applied'
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'grant.grant',
            'res_id': grant.id,
            'view_mode': 'form',
        }


class GrantOpportunityStage(models.Model):
    _name = 'grant.opportunity.stage'
    _description = 'Grant Opportunity Stage'
    _order = 'sequence, name'

    name = fields.Char(string='Stage Name', required=True)
    sequence = fields.Integer(default=10)
    description = fields.Text(string='Stage Description')
    fold = fields.Boolean(string='Folded in Kanban')
    is_won = fields.Boolean(string='Is Applied/Won Stage')
    is_lost = fields.Boolean(string='Is Lost/Declined Stage')
