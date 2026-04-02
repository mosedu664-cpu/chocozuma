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
from io import BytesIO
import PyPDF2

ERR_MSG = {
    'success' : False,
    'msg': 'This report is not supported.'
}

def rotate_base64_pdf(base64_pdf, rotate_type="portrait"):
    version = PyPDF2.__version__
    major = int(version.split(".")[0])

    pdf_bytes = base64.b64decode(base64_pdf)
    pdf_stream = BytesIO(pdf_bytes)
    if major == 1:  # PyPDF2 1.x
        Reader = PyPDF2.PdfFileReader
        Writer = PyPDF2.PdfFileWriter
    else:  # PyPDF2 >= 2.x
        Reader = PyPDF2.PdfReader
        Writer = PyPDF2.PdfWriter

    reader = Reader(pdf_stream)
    writer = Writer()

    if major == 1:
        num_pages = reader.getNumPages()
        page_getter = lambda i: reader.getPage(i)
    else:
        num_pages = len(reader.pages)
        page_getter = lambda i: reader.pages[i]
    for i in range(num_pages):
        page = page_getter(i)
        if rotate_type == "portrait":
            rotate_angle = 270  # rotate CCW 90
        elif rotate_type == "landscape":
            rotate_angle = 90   # rotate CW 90
        else:
            raise ValueError("rotate_type must be 'portrait' or 'landscape'")
        if major == 1:
            if rotate_angle == 90:
                page.rotateClockwise(90)
            else:
                page.rotateCounterClockwise(90)
        else:
            page.rotate(rotate_angle)
        if major == 1:
            writer.addPage(page)
        else:
            writer.add_page(page)
    output_buffer = BytesIO()
    if major == 1:
        writer.write(output_buffer)
    else:
        writer.write(output_buffer)
    rotated_pdf_bytes = output_buffer.getvalue()
    return base64.b64encode(rotated_pdf_bytes).decode("utf-8")

class Report(http.Controller):
    
    def print_report(self,action,report,report_name,wkprinter,printer_ids):
        def create_print_job(printer_id, method, content, file_extension=None, is_byte_stream=False,ids=False,model=False,report_name=False):
            vals = {
                'printer_id': printer_id,
                'method': method,
                'content': content,
                'file_extension': file_extension,
                'is_byte_stream': is_byte_stream,
                'source_ref': {'model':model,'ids':ids},
                'report_name': report_name,
                'job_for':'Reports'
            }
            request.env['print.jobs'].create_notify_print_job(**vals)
        printed = False
        active_ids = action['context'].get('active_ids')
        if not active_ids:
            return ERR_MSG

        if report.report_type == 'qweb-text':
            renderd_text = request.env['ir.actions.report']._render_qweb_text(report_name, active_ids, data=action.get('data'))[0]
            if report.printerType == 'ESCPOS':
                renderd_text = str(renderd_text)
                if len(active_ids) > 1: # for multi records
                    temp_text = []
                    def extract_receipts(text):
                        receipt_blocks = text.split('</receipt>')
                        receipts = [block + '</receipt>' for block in receipt_blocks if block.strip()]
                        return receipts
                    receipts = extract_receipts(renderd_text[4:-1])
                    for i, receipt in enumerate(receipts, 1):
                        xml_text = receipt.split('\\n')
                        xml_text = "".join(xml_text)
                        temp_text.append(wkprinter.get_esc_command_set({'data':xml_text}))
                    renderd_text = ''.join(temp_text)
                else:
                    xml_text = renderd_text[4:-1].split('\\n')
                    xml_text = "".join(xml_text)
                    try:
                        renderd_text = wkprinter.get_esc_command_set({'data':xml_text})
                    except:
                        print(f'Could not render the report for ESCPOS priner.')
                renderd_text = renderd_text.replace("\x00", "[NULL]")
            for printer in printer_ids:
                if printer.use_printer_access:
                    usr_ids = printer.user_ids
                else:
                    usr_ids = printer.hostmachine_id.user_ids
                if request.env.uid not in usr_ids.ids:
                    continue
                printed = True
                create_print_job(printer, 'print-raw', renderd_text,ids=action['context'].get('active_ids'),model=action['context'].get('active_model'),report_name=action['name'])
        elif report.report_type == 'qweb-pdf':
            pdf = request.env['ir.actions.report']._render_qweb_pdf(report_name, active_ids, data=action.get('data'))[0]
            renderd_text = base64.b64encode(pdf)
            if report.paperformat_id and report.paperformat_id.orientation == 'Landscape':
                renderd_text = rotate_base64_pdf(renderd_text, "portrait") 
            for printer in printer_ids:
                if printer.use_printer_access:
                    usr_ids = printer.user_ids
                else:
                    usr_ids = printer.hostmachine_id.user_ids
                if request.env.uid not in usr_ids.ids:
                    continue
                printed = True
                create_print_job(printer, 'print-file', renderd_text, file_extension='pdf',ids=action['context'].get('active_ids'),model=action['context'].get('active_model'),report_name=action['name'])
        if printed:
            return {
                'success' : True,
            }
        else:
            return ERR_MSG

    @http.route('/direct-print/print-report', type='json', auth="user", csrf=False, methods=['POST'])
    def report_info(self, action, options):
        allowed_company = action["context"].get("allowed_company_ids")
        ReportSudo = request.env['ir.actions.report'].sudo()
        report_name = action.get('report_name')
        if not report_name:
            return ERR_MSG
        report = ReportSudo.search([('report_name', '=', report_name)], limit=1)

        wkprinter = request.env['wk.printer']
        printers = wkprinter.search([('company_ids', 'in', allowed_company), ('state', '=', 'Active'), ('report_ids', 'in', [report.id])])

        printer_ids = []
        download = False

        for p in printers:
            if p.hostmachine_id.is_online:
                printer_ids.append(p)
            else:
                action_on_report = p.hostmachine_id.offline_hostmachine_action

                if action_on_report in ['both', 'queue']:
                    printer_ids.append(p)

                if action_on_report in ['both', 'download']:
                    download = True
        if printer_ids:
            printed = self.print_report(action,report,report_name,wkprinter,printer_ids)
            if download:
                return ERR_MSG
            else:
                return printed
        else:
            return {
                'success' : False,
                'msg': 'No Printer found for this action.'
            }



