# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2025-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#    See LICENSE file for full copyright and licensing details.
#################################################################################

from odoo import http
from odoo.http import request
import logging
import base64
import tempfile

class Attachment(http.Controller):

    @http.route('/direct-print/attachment-info', type='json', auth="user", csrf=False, methods=['POST'])
    def attachment_info(self, id, activeCompanyIds=[]):
        result = request.env['print.jobs'].sudo().print_attachment(id=id,activeCompanyIds=activeCompanyIds)
        return result