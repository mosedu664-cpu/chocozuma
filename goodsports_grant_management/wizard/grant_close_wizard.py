# -*- coding: utf-8 -*-
from odoo import models, fields


class GrantCloseWizard(models.TransientModel):
    _name = 'grant.close.wizard'
    _description = 'Grant Closure Wizard'

    grant_id = fields.Many2one('grant.grant', string='Grant', required=True)
    close_date = fields.Date(string='Closure Date', default=fields.Date.today)
    final_report_submitted = fields.Boolean(string='Final Report Submitted')
    final_payment_received = fields.Boolean(string='Final Payment Received')
    all_milestones_complete = fields.Boolean(string='All Milestones Complete')
    closure_notes = fields.Html(string='Closure Summary / Lessons Learned')
    total_spent = fields.Monetary(string='Total Amount Spent',
                                  currency_field='currency_id',
                                  related='grant_id.total_expenses')
    currency_id = fields.Many2one(related='grant_id.currency_id')

    def action_close_grant(self):
        self.ensure_one()
        self.grant_id.write({
            'state': 'closed',
            'close_date': self.close_date,
        })
        self.grant_id.message_post(
            body='<b>Grant Closed.</b>',
            message_type='notification',
        )
        return {'type': 'ir.actions.act_window_close'}
