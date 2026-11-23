# -*- coding: utf-8 -*-
"""The button under a WhatsApp card opens /cz/r/<token>: the PDF of that one send.

The token is a random 128-bit value stored on the send log; nothing else is reachable through it.
Links stay valid for LINK_DAYS days.
"""
from datetime import timedelta

from werkzeug.exceptions import NotFound

from odoo import fields, http
from odoo.http import request


LINK_DAYS = 60


class CzReportLink(http.Controller):

    @http.route("/cz/r/<string:token>", type="http", auth="public", methods=["GET"], csrf=False, sitemap=False)
    def cz_report_pdf(self, token, **kw):
        token = (token or "").strip().lower()
        if len(token) != 32 or not token.isalnum():
            raise NotFound()
        log = request.env["cz.wa.report.log"].sudo().search([("access_token", "=", token)], limit=1)
        if not log or not log.brief_html:
            raise NotFound()
        if log.create_date < fields.Datetime.now() - timedelta(days=LINK_DAYS):
            return request.make_response("Bu raporun bağlantısının süresi doldu. / انتهت صلاحية هذا الرابط.",
                                         headers=[("Content-Type", "text/plain; charset=utf-8")], status=410)
        pdf = log._cached_pdf()
        name = "ChocoZuma-%s-%s.pdf" % (log.report_id.code, (log.business_day or "").replace("/", ".").replace(" ", ""))
        return request.make_response(pdf, headers=[
            ("Content-Type", "application/pdf"),
            ("Content-Disposition", 'inline; filename="%s"' % name),
            ("Cache-Control", "private, max-age=86400"),
            ("X-Robots-Tag", "noindex, nofollow"),
        ])
