from odoo import api, fields, models, _


class PosConfig(models.Model):
    _inherit = 'pos.config'

    print_kot = fields.Boolean( string='Print KOT',
                                 help='Allow Printing Kitchen Order Receipt', copy=False)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_print_kot = fields.Boolean(related='pos_config_id.print_kot', readonly=False)