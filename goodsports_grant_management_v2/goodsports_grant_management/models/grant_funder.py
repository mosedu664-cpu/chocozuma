# -*- coding: utf-8 -*-
from odoo import models, fields, api


class GrantFunder(models.Model):
    _name = 'grant.funder'
    _description = 'Grant Funder / Grantor Organization'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'

    name = fields.Char(string='Funder Name', required=True, tracking=True)
    funder_type = fields.Selection([
        ('foundation', 'Private Foundation'),
        ('corporate', 'Corporate Funder'),
        ('government_federal', 'Federal Government'),
        ('government_state', 'State Government'),
        ('government_local', 'Local Government'),
        ('community', 'Community Foundation'),
        ('individual', 'Individual Donor'),
        ('other', 'Other'),
    ], string='Funder Type', required=True, default='foundation', tracking=True)

    partner_id = fields.Many2one('res.partner', string='Contact Record', ondelete='set null')
    website = fields.Char(string='Website')
    email = fields.Char(string='Primary Email')
    phone = fields.Char(string='Phone')
    street = fields.Char(string='Street')
    city = fields.Char(string='City')
    state_id = fields.Many2one('res.country.state', string='State')
    country_id = fields.Many2one('res.country', string='Country')

    # Program officer / relationship contact
    program_officer_id = fields.Many2one('res.partner', string='Program Officer')
    relationship_manager_id = fields.Many2one('res.users', string='Our Relationship Manager',
                                               default=lambda self: self.env.user)

    # Focus areas & eligibility
    focus_areas = fields.Many2many('grant.focus.area', string='Focus Areas')
    geographic_focus = fields.Char(string='Geographic Focus')
    eligible_org_types = fields.Char(string='Eligible Organization Types')
    min_grant_amount = fields.Monetary(string='Min Grant Amount', currency_field='currency_id')
    max_grant_amount = fields.Monetary(string='Max Grant Amount', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)

    # Relationship tracking
    first_grant_date = fields.Date(string='First Grant Date')
    last_grant_date = fields.Date(string='Last Grant Date')
    relationship_status = fields.Selection([
        ('prospect', 'Prospect'),
        ('active', 'Active Funder'),
        ('lapsed', 'Lapsed'),
        ('declined', 'Declined Us'),
        ('blacklisted', 'Do Not Approach'),
    ], string='Relationship Status', default='prospect', tracking=True)

    # Grants
    grant_ids = fields.One2many('grant.grant', 'funder_id', string='Grants')
    grant_count = fields.Integer(string='Grant Count', compute='_compute_grant_stats')
    total_awarded = fields.Monetary(string='Total Awarded', compute='_compute_grant_stats',
                                    currency_field='currency_id')
    active_grant_count = fields.Integer(string='Active Grants', compute='_compute_grant_stats')

    notes = fields.Html(string='Notes & Strategy')
    active = fields.Boolean(default=True)

    @api.depends('grant_ids', 'grant_ids.state', 'grant_ids.awarded_amount')
    def _compute_grant_stats(self):
        for rec in self:
            grants = rec.grant_ids
            rec.grant_count = len(grants)
            rec.total_awarded = sum(
                g.awarded_amount for g in grants if g.state in ('awarded', 'active', 'closed')
            )
            rec.active_grant_count = len(grants.filtered(lambda g: g.state == 'active'))


class GrantFocusArea(models.Model):
    _name = 'grant.focus.area'
    _description = 'Grant Focus Area / Program Category'

    name = fields.Char(string='Focus Area', required=True)
    description = fields.Text(string='Description')
    color = fields.Integer(string='Color Index')
