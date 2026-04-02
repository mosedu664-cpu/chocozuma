# -*- coding: utf-8 -*-
#################################################################################
#
#   Copyright (c) 2025-Present Webkul Software Pvt. Ltd. (<https://webkul.com/>)
#    See LICENSE file for full copyright and licensing details.
#################################################################################

from odoo import api, fields, models, _
import logging
import json
import requests
import time
import random
from odoo.exceptions import ValidationError, UserError
# from odoo.addons.hw_escpos.escpos import escpos
from ..wklib import printer_info
from ..wklib import platform_info
from ..wklib.escpos import escpos

_logger=logging.getLogger(__name__)

class WkHostMachine(models.Model):
    _name = "wk.hostmachine"
    _description = "Host Machine"

    name = fields.Char(string="Name", required=True)
    description = fields.Char(string="Description", help="")
    host_id =  fields.Char(string="Host ID", required=True) # use hostname for unique id
    hostname =  fields.Char(string="Host Machine Name")
    platform =  fields.Selection(string="Operating System", selection=platform_info.PLATFORM)
    offline_hostmachine_action = fields.Selection(
        selection=[
            ('queue', 'Send to Queue'),
            ('download', 'Download Report'),
            ('both', 'Download & Queue')
        ],
        string="If Host Machine Offline",
        help="Choose what should happen if the host machine is offline during printing.",default='queue'
    )
    app_version =  fields.Char(string="App version", help="PrintDirect Application Version")
    printer_ids = fields.One2many('wk.printer', 'hostmachine_id', string='Printer')
    logged_with = fields.Char(string="Logged With", default=lambda self:self.env.user.name)
    user_ids = fields.Many2many('res.users', string='Grant Access to:', default=lambda self:self.env.user, help="Do not remove the User from which you have log in this Hostmachine.")
    is_online = fields.Boolean(string="Status")
    company_ids = fields.Many2many('res.company', 'res_company_hostmachine_rel', 'hm_id', 'cid',
        string='Companies', default=lambda self: self.env.company.ids)
    
    @api.constrains('user_ids','logged_with')
    def _check_logged_with_user(self):
        for record in self:
            if record.logged_with not in record.user_ids.mapped('name'):
                raise ValidationError(f"You cannot remove {record.logged_with} while this host machine is logged in with that user.")
    
    @api.model_create_multi
    def create(self, vals_list):
        unique_vals = {}
        for vals in vals_list:
            host_id = vals.get('host_id')
            if host_id:
                unique_vals[host_id] = vals
        vals_list = list(unique_vals.values())
        return super().create(vals_list)

    def check_company_operation(self):
        allowed_company = self.env.context.get("allowed_company_ids", []) # company(s) the user is working on
        assigned_company = [each.id for each in self.company_ids] # list of company added to the hostmachine
        common_company = list(set(allowed_company) & set(assigned_company))
        if not common_company:
            raise UserError('This operation is not valid as per your current company.\nYou can add Companies for this Host Machine.')

    def get_sys_info(self):
        self.check_company_operation()
        self.is_online = False
        if not self.host_id:
            raise UserError('The Host ID is missing.')
        if not self.user_ids:
            raise UserError('No users are granted access to this Host machine.')
        msg_id = random.randint(999,1_999_999_999)
        for each_partner in self.user_ids:
            message = {'Persona': [{
                'id': msg_id, 
                'im_status': 'print direct', 
                'type': 'partner', 
                'data':{'method': 'sys-info', 'host_id': self.host_id}
                }]}
            self.env['bus.bus']._sendone(
                each_partner.partner_id,
                "mail.record/insert",
                message
            )
        time.sleep(2)
        return {
                'type': 'ir.actions.client',
                'tag': 'reload',
            }
    
    def _cron_sys_info(self):
        for rec in self.search([]):
            rec.get_sys_info()
    
    def get_printers(self):
        self.check_company_operation()
        if not self.host_id:
            raise UserError('The Host ID is missing.')
        if not self.user_ids:
            raise UserError('No users are granted access to this Host machine.')
        msg_id = random.randint(999,1_999_999_999)
        message = {'Persona': [{
            'id': msg_id, 
            'im_status': 'print direct', 
            'type': 'partner', 
            'data':{'method': 'get-printers', 'host_id': self.host_id}
            }]}
        for each_partner in self.user_ids:
            self.env['bus.bus']._sendone(
                each_partner.partner_id,
                "mail.record/insert",
                message
            )
        time.sleep(4)
        return {
                'type': 'ir.actions.client',
                'tag': 'reload',
            }

class WkPrinter(models.Model):
    _name = "wk.printer"
    _description = "Printer"

    name = fields.Char(string="Name", required=True)
    state = fields.Selection(selection=[('Active', 'Active'), ('Inactive', 'Inactive')], string='State', default='Inactive', required=True)
    description = fields.Char(string="Description", help="Description of the printer. eg: Office printer")
    idVendor = fields.Char(string="Vendor ID")
    idProduct = fields.Char(string="Product ID")
    paper_width = fields.Integer(string="Paper Width", default=603)
    paper_height = fields.Integer(string="Paper Height", default=1703)
    interface = fields.Char(string="Interface") # System Defined | Raw(USB)
    printerType = fields.Selection(string="Printer Type", selection=printer_info.PRINTER_TYPE)
    printerType_domain = fields.Char(string="File Type", compute="_compute_printerType_domain")
    report_ids = fields.Many2many('ir.actions.report', 'wk_printer_report_rel', 'printer_id', 'report_id', string="Reports")
    hostmachine_id = fields.Many2one('wk.hostmachine', string='Host Machine', ondelete="cascade")
    platform =  fields.Selection(related="hostmachine_id.platform", string="Operating System")
    use_printer_access = fields.Boolean( string="Allow Specific Users", help="If enabled, only specific users will have access to the printer.\nIf disabled, access will be inherited from the host machine.", default=False)
    user_ids = fields.Many2many('res.users', string='Grant Access to:', default=lambda self:self.env.user, help="Do not remove the User from which you have log in this Hostmachine.")
    company_ids = fields.Many2many(related="hostmachine_id.company_ids", string='Companies')

        
    @api.constrains('user_ids','hostmachine_id')
    def _check_logged_with_user(self):
        for record in self:
            if record.hostmachine_id.logged_with not in record.user_ids.mapped('name'):
                raise ValidationError(f"You cannot remove {record.hostmachine_id.logged_with} while this host machine is logged in with that user.")
    
    @api.depends('printerType')
    def _compute_printerType_domain(self):
        for res in self:
            if res.printerType:
                arr = res.printerType.split(' ')
                res.printerType_domain = arr[0]
            else:
                res.printerType_domain = ''

    def toggle_is_active(self):
        for rec in self:
            if not rec.printerType:
                raise ValidationError('Please set the Printer Type first.')
            rec.state = 'Inactive' if rec.state == 'Active' else 'Active'
    
    def _get_printer_config(self):
        return {
            'host_id' : self.hostmachine_id.host_id,
            'name' : self.name,
            'idVendor' : self.idVendor,
            'idProduct' : self.idProduct,
            'printerType' : self.printerType,
            'paper_width' : self.paper_width,
            'paper_height' : self.paper_height,
        }

    def test_printer(self):
        if not self.printerType:
            raise ValidationError('Please set the Printer Type first.')
        self.hostmachine_id.check_company_operation()
        vals = self._get_printer_config()
        wiz = self.env['wizard.test.printer'].create(vals)
        view = self.env.ref('wk_odoo_direct_print.wizard_test_printer_form')

        return {
            'name': _(self.name),
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'wizard.test.printer',
            'views': [(view.id, 'form')],
            'target': 'new',
            'res_id': wiz.id,
        }
    
    @api.model
    def get_esc_command_set(self, data):
        printer = escpos.Escpos()
        printer.receipt(data.get("data"))
        return printer.esc_commands
