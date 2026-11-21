# -*- coding: utf-8 -*-
from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    cz_shared_login = fields.Boolean(
        string='Shared POS login (not a person)', groups='hr.group_hr_user',
        help="Tick for generic logins such as 'Kasa', 'Joker' or 'X': they can still log in to the POS, but they are "
             "not offered as the staff member on a taxi, meal, advance… An expense is always for a real person.")
