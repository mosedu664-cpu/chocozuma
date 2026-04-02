# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2025-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#    See LICENSE file for full copyright and licensing details.
#################################################################################

from odoo import models, fields

class ReportTriggerRule(models.Model):
    _name = 'report.trigger.rule'
    _description = 'Report Trigger Rule'

    name = fields.Char(string='Action Name', required=True)
    model = fields.Char(string='Model Name', required=True)
