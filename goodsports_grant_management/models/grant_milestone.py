# -*- coding: utf-8 -*-
from odoo import models, fields, api


class GrantMilestone(models.Model):
    _name = 'grant.milestone'
    _description = 'Grant Milestone / Deliverable'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'due_date asc, sequence asc'

    grant_id = fields.Many2one('grant.grant', string='Grant', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Milestone / Deliverable', required=True)
    description = fields.Text(string='Description & Success Criteria')

    milestone_type = fields.Selection([
        ('deliverable', 'Program Deliverable'),
        ('report', 'Report Due'),
        ('payment_trigger', 'Payment Trigger'),
        ('evaluation', 'Evaluation / Assessment'),
        ('administrative', 'Administrative'),
    ], string='Type', default='deliverable')

    state = fields.Selection([
        ('pending', 'Not Started'),
        ('in_progress', 'In Progress'),
        ('done', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='pending', tracking=True)

    due_date = fields.Date(string='Due Date', required=True)
    completion_date = fields.Date(string='Actual Completion Date')
    is_overdue = fields.Boolean(compute='_compute_overdue', store=True)

    assigned_to_id = fields.Many2one('res.users', string='Assigned To')
    verified_by_id = fields.Many2one('res.users', string='Verified By')

    target_quantity = fields.Float(string='Target Quantity')
    actual_quantity = fields.Float(string='Actual Quantity Achieved')
    unit_of_measure = fields.Char(string='Unit of Measure')
    achievement_pct = fields.Float(string='Achievement %', compute='_compute_achievement')

    currency_id = fields.Many2one(related='grant_id.currency_id', store=True)
    budget_allocated = fields.Monetary(string='Budget Allocated', currency_field='currency_id')

    linked_payment_id = fields.Many2one('grant.payment', string='Triggers Payment')
    linked_report_id = fields.Many2one('grant.report', string='Linked Report')

    evidence = fields.Html(string='Evidence / Documentation')
    notes = fields.Text(string='Notes')

    @api.depends('due_date', 'state')
    def _compute_overdue(self):
        today = fields.Date.today()
        for m in self:
            m.is_overdue = (
                m.due_date and m.due_date < today and
                m.state not in ('done', 'cancelled')
            )

    @api.depends('target_quantity', 'actual_quantity')
    def _compute_achievement(self):
        for m in self:
            if m.target_quantity:
                m.achievement_pct = min((m.actual_quantity / m.target_quantity) * 100, 100)
            else:
                m.achievement_pct = 0.0

    def action_start(self):
        self.write({'state': 'in_progress'})

    def action_complete(self):
        self.write({'state': 'done', 'completion_date': fields.Date.today()})

    def action_cancel(self):
        self.write({'state': 'cancelled'})
