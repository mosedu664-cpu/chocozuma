# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    app_mail_smtp_timeout = fields.Integer('SMTP Timeout (Seconds)', default=600, config_parameter='mail.smtp.timeout',
                                           help="Setup SMTP Timeout, default 600s")
