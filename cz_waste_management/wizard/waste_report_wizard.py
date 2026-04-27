# -*- coding: utf-8 -*-
import base64
import io
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class WasteReportWizard(models.TransientModel):
    _name = 'waste.report.wizard'
    _description = 'Waste Report Wizard'

    from_date = fields.Datetime(string='From Date', required=True, default=fields.Datetime.now)
    to_date = fields.Datetime(string='To Date', required=True, default=fields.Datetime.now)

    user_id = fields.Many2one('res.users', string='Employee / User')
    product_id = fields.Many2one('product.product', string='Product')
    reason_id = fields.Many2one('waste.reason', string='Waste Reason')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    def action_generate_xlsx(self):
        if not xlsxwriter:
            raise UserError(_("The xlsxwriter library is not installed."))

        domain = [('state', '=', 'confirmed')]
        if self.from_date:
            domain.append(('timestamp', '>=', self.from_date))
        if self.to_date:
            domain.append(('timestamp', '<=', self.to_date))
        if self.user_id:
            domain.append(('user_id', '=', self.user_id.id))
        if self.product_id:
            domain.append(('product_id', '=', self.product_id.id))
        if self.reason_id:
            domain.append(('reason_id', '=', self.reason_id.id))
        if self.company_id:
            domain.append(('company_id', '=', self.company_id.id))

        logs = self.env['waste.log'].search(domain, order='timestamp desc')

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Waste Report')

        # Formats
        header_format = workbook.add_format({
            'bold': True, 'bg_color': '#D3D3D3', 'border': 1, 'align': 'center'
        })
        date_format = workbook.add_format({'num_format': 'yyyy-mm-dd hh:mm:ss', 'border': 1})
        num_format = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        text_format = workbook.add_format({'border': 1})
        total_format = workbook.add_format({'bold': True, 'border': 1, 'bg_color': '#E9E9E9', 'num_format': '#,##0.00'})

        # Headers
        headers = [
            'Date & Time', 'Employee / User', 'Order Reference', 'Product',
            'Quantity Wasted', 'Unit of Measure', 'Unit Cost', 'Total Cost (Value)',
            'Waste Reason', 'Source Location'
        ]
        for col, header in enumerate(headers):
            sheet.write(0, col, header, header_format)
            sheet.set_column(col, col, 18)

        # Data
        row = 1
        total_qty = 0
        total_value = 0
        for log in logs:
            unit_cost = log.cost / log.quantity if log.quantity > 0 else 0
            
            sheet.write_datetime(row, 0, log.timestamp.replace(tzinfo=None), date_format)
            sheet.write(row, 1, log.user_id.name, text_format)
            sheet.write(row, 2, log.order_ref or '', text_format)
            sheet.write(row, 3, log.product_id.display_name, text_format)
            sheet.write(row, 4, log.quantity, num_format)
            sheet.write(row, 5, log.product_uom_id.name, text_format)
            sheet.write(row, 6, unit_cost, num_format)
            sheet.write(row, 7, log.cost, num_format)
            sheet.write(row, 8, log.reason_id.name, text_format)
            sheet.write(row, 9, log.location_id.display_name, text_format)
            
            total_qty += log.quantity
            total_value += log.cost
            row += 1

        # Totals Row
        sheet.write(row, 3, 'TOTALS', header_format)
        sheet.write(row, 4, total_qty, total_format)
        sheet.write(row, 7, total_value, total_format)

        workbook.close()
        output.seek(0)
        
        file_name = f"Waste_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        attachment = self.env['ir.attachment'].create({
            'name': file_name,
            'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'res_model': 'waste.report.wizard',
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
