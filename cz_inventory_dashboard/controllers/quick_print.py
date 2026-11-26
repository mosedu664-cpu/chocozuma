# -*- coding: utf-8 -*-
"""One-tap printing: any Odoo document opened as a web page that calls the device's own print
dialog at once (Android/iOS/desktop) — no PDF download, no second app to open the file.

URL: /cz/print/<report_name>/<ids>   e.g. /cz/print/stock.report_deliveryslip/45677
Only report names in ALLOWED are served; records are read with the user's own access rights.
"""
from odoo import http
from odoo.http import request

ALLOWED = {
    "stock.report_deliveryslip",
}

BAR = """
<style>
#czbar{position:sticky;top:0;z-index:99;display:flex;gap:10px;justify-content:center;padding:10px;
background:#FFF7EF;border-bottom:1px solid #E8C9A0;font-family:Arial,Helvetica,sans-serif}
#czbar button{padding:14px 28px;font-size:20px;font-weight:bold;border:0;border-radius:999px;color:#fff;
background:linear-gradient(120deg,#E8A33D,#C77E1E)}
#czbar .b2{background:#8A7460}
@media print{#czbar{display:none!important}}
</style>
<div id="czbar"><button type="button" onclick="window.print()">🖨 YAZDIR</button>
<button type="button" class="b2" onclick="history.length>1?history.back():window.close()">Kapat</button></div>
"""
AUTO = """<script>window.addEventListener('load',function(){setTimeout(function(){window.print();},600);});</script>"""


class CzQuickPrint(http.Controller):

    @http.route("/cz/print/<string:report_name>/<string:ids>", type="http", auth="user")
    def cz_print(self, report_name, ids, **kw):
        if report_name not in ALLOWED:
            return request.not_found()
        try:
            res_ids = [int(i) for i in ids.split(",") if i]
        except ValueError:
            return request.not_found()
        html, _fmt = request.env["ir.actions.report"]._render_qweb_html(report_name, res_ids)
        html = html.decode() if isinstance(html, bytes) else html
        if "<body" in html:
            start = html.index(">", html.index("<body")) + 1
            html = html[:start] + BAR + html[start:]
        html = html.replace("</body>", AUTO + "</body>", 1) if "</body>" in html else html + AUTO
        return request.make_response(html, headers=[("Content-Type", "text/html; charset=utf-8")])
