# -*- coding: utf-8 -*-

import logging

import odoo.addons.base.models.ir_mail_server as ir_mail_server
from odoo import api, models

_logger = logging.getLogger(__name__)

# Increase SMTP timeout to 600s or from system parameters
class IrMailServer(models.Model):
    _inherit = 'ir.mail_server'

    @api.model
    def _get_smtp_timeout(self):
        # Get timeout from system parameters, default to 600s
        timeout = self.env['ir.config_parameter'].sudo().get_param('mail.smtp.timeout', default=600)
        try:
            return int(timeout)
        except:
            return 600

    def connect(self, host=None, port=None, user=None, password=None, encryption=None,
                smtp_from=None, ssl_certificate=None, ssl_private_key=None, smtp_debug=False, mail_server_id=None,
                allow_archived=False):
        # Dynamically set the timeout
        ir_mail_server.SMTP_TIMEOUT = self._get_smtp_timeout()
        return super(IrMailServer, self).connect(host, port, user, password, encryption, smtp_from, ssl_certificate, ssl_private_key, smtp_debug, mail_server_id, allow_archived)
