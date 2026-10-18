# -*- coding: utf-8 -*-
import json
import logging

from werkzeug.datastructures import FileStorage

from odoo import _, http
from odoo.exceptions import AccessError
from odoo.http import request
from odoo.addons.web.controllers.export import CSVExport, ExcelExport
from odoo.addons.web.controllers.pivot import TableExporter

_logger = logging.getLogger(__name__)


def _log_export(fmt, data, allowed):
    """Best-effort audit row; never blocks or breaks an export."""
    try:
        params = {}
        if isinstance(data, FileStorage):
            data.stream.seek(0)
            params = json.load(data)
            data.stream.seek(0)
        elif data:
            params = json.loads(data)
        model = params.get('model') or ''
        field_count = len(params.get('fields') or params.get('measures') or [])
        ids = params.get('ids') or []
        record_count = len(ids)
        if not record_count and model and model in request.env and fmt != 'pivot':
            record_count = request.env[model].search_count(params.get('domain') or [])
        label = request.env['ir.model']._get(model).name if model else (params.get('title') or '')
        request.env['cz.export.log'].sudo().create({
            'user_id': request.env.uid,
            'model': model or 'pivot',
            'model_label': label,
            'field_count': field_count,
            'record_count': record_count,
            'export_format': fmt,
            'allowed': allowed,
        })
    except Exception:  # pragma: no cover - audit must never break exports
        _logger.exception("cz_data_guard: could not write export log")


def _guard(fmt, data):
    allowed = request.env.user.has_group('base.group_allow_export')
    _log_export(fmt, data, allowed)
    if not allowed:
        raise AccessError(_("You are not allowed to export data."))


class CzExcelExport(ExcelExport):
    @http.route()
    def web_export_xlsx(self, data):
        _guard('xlsx', data)
        return super().web_export_xlsx(data)


class CzCSVExport(CSVExport):
    @http.route()
    def web_export_csv(self, data):
        _guard('csv', data)
        return super().web_export_csv(data)


class CzTableExporter(TableExporter):
    @http.route()
    def export_xlsx(self, data, **kw):
        _guard('pivot', data)
        return super().export_xlsx(data, **kw)
