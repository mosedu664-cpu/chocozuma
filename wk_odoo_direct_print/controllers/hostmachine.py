# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2025-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#    See LICENSE file for full copyright and licensing details.
#################################################################################

from odoo import http
from odoo.http import request
import logging
from ast import literal_eval


_logger=logging.getLogger(__name__)

class HostMachine(http.Controller):

    @http.route('/direct-print/hostmachine-connection', type='json', auth="user", csrf=False, methods=['POST'])
    def new_hostmachine_connection(self, **kwargs):
        host_info = request.get_json_data().get('host_info')
        _logger.info(f'\nhostmachine-connection ------------- {host_info}')
        is_online = request.get_json_data().get('is_online')
        host_obj = request.env['wk.hostmachine'].search([('host_id', '=', host_info.get('host_id')), ('platform', '=', host_info.get('platform'))])
        if not host_obj:
            new_host  = request.env['wk.hostmachine'].create({
                'name': host_info.get('host'),
                'host_id': host_info.get('host_id'),
                'hostname': host_info.get('host'),
                'platform': host_info.get('platform'),
                'is_online': True,
                'logged_with' : request.env.user.name,
                'app_version': host_info.get('app_version')
            })
            if host_info.get('platform') in ['Android', 'iOS']:
                request.env['wk.printer'].create({
                'name':'Default Printer',
                'hostmachine_id':new_host.id
                })
        else: 
            if host_info:
                vals = dict(
                    is_online = is_online if 'is_online' in request.get_json_data() else True,
                    logged_with = request.env.user.name or '',
                    app_version = host_info.get('app_version'),
                    user_ids = host_obj.user_ids+request.env.user
                )
                host_obj.write(vals)
        return {
                'success' : True,
                'msg': 'Received request.'
            }

    @http.route('/direct-print/add-printers', type='json', auth="user", csrf=False, methods=['POST'])
    def add_printers(self, **kwargs):
        host_info = request.get_json_data().get('host_info')
        printers = request.get_json_data().get('printers')

        def add_printer(host):
            for each in printers.get('data'):
                printer_exist = request.env['wk.printer'].search([('hostmachine_id', '=', host.id), ('name', '=', each.get('name'))])
                if printer_exist:
                    continue
                new_printer = request.env['wk.printer'].create({
                    'name': each.get('name'),
                    'interface': each.get('interface'),
                    'idVendor': each.get('idVendor'),
                    'idProduct': each.get('idProduct'),
                    'paper_width': each.get('paper_width') or 590,
                    'paper_height': each.get('paper_height') or 1703,
                    'hostmachine_id': host.id
                })

        host_obj = request.env['wk.hostmachine'].search([('host_id', '=', host_info.get('host_id')), ('platform', '=', host_info.get('platform'))])
        if host_obj:
            host_obj.is_online = True
            add_printer(host_obj)
        return {
                'success' : True,
                'msg': 'Received request.'
            }
    
    @http.route('/direct-print/get-print-job', type='json', auth="user", csrf=False, methods=['POST'])
    def send_print_job(self, **kwargs):
        host_info = request.get_json_data().get('host_info')
        record_id = request.get_json_data().get('record_id')
        job_id = request.env['print.jobs'].search([('id', '=', record_id)])
        if job_id and job_id.host_id == host_info.get('host_id'):
            job_id.printer_id.hostmachine_id.is_online = True # Change The host machine status 
            printer_id = job_id.printer_id
            print_data = printer_id._get_printer_config()
            if job_id.is_byte_stream:
                list_bytes = job_id.content.replace("[NULL]", "\x00")
                print_data['contentCode'] = literal_eval(list_bytes)
            else:
                print_data['contentCode'] = job_id.content
            print_data['file_extension'] = job_id.file_extension
            print_data['is_byte_stream'] = job_id.is_byte_stream
            print_data['use_raw_image'] = job_id.use_raw_image
            print_data['is_dummy'] = job_id.is_dummy
            return {
                'method': job_id.method,
                'print_data': print_data
            }

    @http.route('/direct-print/process-print-job', type='json', auth="user", csrf=False, methods=['POST'])
    def process_print_job(self, **kwargs):
        host_info = request.get_json_data().get('host_info')
        record_id = request.get_json_data().get('record_id')
        job_state = request.get_json_data().get('job_state')
        msg = request.get_json_data().get('msg')
        job_id = request.env['print.jobs'].search([('id', '=', record_id)])
        if job_id and job_id.host_id == host_info.get('host_id'):
            job_id.state = job_state
            job_id.msg = msg
            return {
                'success': True
            }
        
