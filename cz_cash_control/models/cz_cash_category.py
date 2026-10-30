# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class CzCashCategory(models.Model):
    """Fixed list of drawer movement reasons shown to the cashier in the POS.

    The cashier only ever sees the *name*; the accounting side (account, kind,
    controls) is configured here by the accountant.
    """
    _name = 'cz.cash.category'
    _description = 'Cash Drawer Category'
    _inherit = ['pos.load.mixin']
    _order = 'sequence, name'
    _check_company_auto = True

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, size=12, help="Short code printed on receipts and used in journal labels, e.g. TAKSI.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)

    kind = fields.Selection([
        ('expense', 'Expense paid from drawer'),
        ('safe_transfer', 'Transfer to branch safe'),
        ('refund', 'Customer refund'),
        ('advance', 'Staff advance / loan'),
        ('bank_deposit', 'Bank deposit (from safe)'),
        ('salary', 'Salary / wage payment (from safe)'),
        ('cash_in', 'Cash in (float / change)'),
        ('other', 'Other'),
    ], required=True, default='expense')
    direction = fields.Selection([
        ('out', 'Cash out'),
        ('in', 'Cash in'),
        ('both', 'Both'),
    ], required=True, default='out', help="Which POS cash movement types this category may be used with.")

    account_id = fields.Many2one(
        'account.account', string='Counterpart Account',
        domain="[('company_ids', 'parent_of', company_id), ('deprecated', '=', False)]",
        help="Account debited (cash out) / credited (cash in) when the accountant approves the day. "
             "For 'Transfer to branch safe' use the internal transfer clearing account.")
    requires_employee = fields.Boolean(string='Employee required', default=False,
                                       help="Cashier must pick the staff member (taxi, food, advance...).")
    requires_receipt_above = fields.Monetary(
        string='Receipt no. required above', currency_field='currency_id', default=0.0,
        help="Above this amount the cashier must type the receipt / fiş number. 0 = never.")
    requires_pin = fields.Boolean(string='Manager PIN required', default=False,
                                  help="A manager PIN (pos_hr) is requested in the POS before this movement is accepted.")
    pin_above = fields.Monetary(string='Manager PIN above', currency_field='currency_id', default=0.0,
                                help="If 'Manager PIN required' is off, still ask for a PIN above this amount. 0 = never.")
    max_amount = fields.Monetary(string='Max per movement', currency_field='currency_id', default=0.0,
                                 help="Hard cap for a single movement. 0 = no cap.")
    typical_amount = fields.Monetary(string='Typical amount', currency_field='currency_id', default=0.0,
                                     help="Used for the 'unusual expense' alert (2x typical). 0 = no alert.")
    pos_available = fields.Boolean(string='Show in POS', default=True)
    color = fields.Integer()
    currency_id = fields.Many2one(related='company_id.currency_id')
    note = fields.Text()

    _sql_constraints = [
        ('code_company_uniq', 'unique(code, company_id)', 'Category code must be unique per company.'),
    ]

    @api.constrains('kind', 'account_id')
    def _check_account(self):
        for cat in self:
            if cat.kind != 'other' and not cat.account_id:
                raise ValidationError(_("Category %s needs a counterpart account.", cat.name))

    @api.model
    def _load_pos_data_domain(self, data):
        company_id = data['pos.config']['data'][0]['company_id']
        return [('company_id', '=', company_id), ('pos_available', '=', True)]

    @api.model
    def _load_pos_data_fields(self, config_id):
        return ['name', 'code', 'sequence', 'kind', 'direction', 'requires_employee',
                'requires_receipt_above', 'requires_pin', 'pin_above', 'max_amount', 'color']
