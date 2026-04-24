# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WasteLog(models.Model):
    _name = 'waste.log'
    _description = 'Waste Log'
    _order = 'timestamp desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default='New',
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        tracking=True,
    )
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        related='product_id.uom_id',
        store=True,
        readonly=True,
    )
    quantity = fields.Float(
        string='Quantity Wasted',
        required=True,
        digits='Product Unit of Measure',
        tracking=True,
    )
    total_qty_ordered = fields.Float(
        string='Total Ordered Quantity',
        help="The original quantity ordered in the POS order.",
    )
    reason_id = fields.Many2one(
        'waste.reason',
        string='Waste Reason',
        required=True,
        tracking=True,
    )
    other_reason = fields.Char(
        string='Other Reason',
        help="Specify the reason if 'Other' is selected.",
    )
    user_id = fields.Many2one(
        'res.users',
        string='Logged By',
        default=lambda self: self.env.user,
        readonly=True,
        tracking=True,
    )
    station = fields.Char(
        string='Station',
        help='Kitchen station or section where the waste occurred.',
    )
    timestamp = fields.Datetime(
        string='Timestamp',
        default=fields.Datetime.now,
        readonly=True,
        tracking=True,
    )
    location_id = fields.Many2one(
        'stock.location',
        string='Source Location',
        required=True,
        tracking=True,
        default=lambda self: self._get_default_location_id(),
    )
    location_dest_id = fields.Many2one(
        'stock.location',
        string='Waste Location',
        required=True,
        tracking=True,
        default=lambda self: self._get_default_location_dest_id(),
    )
    photo = fields.Binary(
        string='Photo',
        attachment=True,
        help='Optional photo for disputes or insurance.',
    )
    photo_filename = fields.Char(string='Photo Filename')
    notes = fields.Text(string='Notes')
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('confirmed', 'Confirmed'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
    )
    stock_move_id = fields.Many2one(
        'stock.move',
        string='Stock Move',
        readonly=True,
        copy=False,
    )
    pos_order_id = fields.Many2one(
        'pos.order',
        string='POS Order',
        readonly=True,
    )
    order_ref = fields.Char(
        string='Order Reference',
        tracking=True,
    )
    preparation_display_id = fields.Many2one(
        'pos_preparation_display.display',
        string='Preparation Display',
        readonly=True,
    )
    preparation_display_orderline_id = fields.Many2one(
        'pos_preparation_display.orderline',
        string='KDS Order Line',
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    cost = fields.Float(
        string='Estimated Cost',
        compute='_compute_cost',
        store=True,
        digits='Product Price',
    )

    def _get_default_location_id(self):
        # Default source: POS config stock location or warehouse lot_stock
        pos_session = self.env['pos.session'].search([('user_id', '=', self.env.user.id), ('state', '=', 'opened')], limit=1)
        if pos_session and pos_session.config_id.picking_type_id.default_location_src_id:
            return pos_session.config_id.picking_type_id.default_location_src_id.id

        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        return warehouse.lot_stock_id.id if warehouse else False

    def _get_default_location_dest_id(self):
        # Default destination: POS config waste_location or company waste_location
        pos_session = self.env['pos.session'].search([('user_id', '=', self.env.user.id), ('state', '=', 'opened')], limit=1)
        if pos_session and pos_session.config_id.waste_location_id:
            return pos_session.config_id.waste_location_id.id

        if self.env.company.waste_location_id:
            return self.env.company.waste_location_id.id

        waste_loc = self.env.ref('cz_waste_management.stock_location_waste', raise_if_not_found=False)
        return waste_loc.id if waste_loc else False

    @api.depends('product_id', 'quantity', 'product_id.standard_price')
    def _compute_cost(self):
        for record in self:
            record.cost = record.quantity * (record.product_id.standard_price or 0.0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('waste.log') or 'New'
        return super().create(vals_list)

    def action_confirm(self):
        """Confirm the waste log and create inventory move."""
        for record in self:
            if record.state != 'draft':
                continue
            if record.quantity <= 0:
                raise UserError(_("Quantity wasted must be greater than zero."))

            source_location = record.location_id
            if not source_location:
                raise UserError(_("Please specify a source location."))

            waste_location = record.location_dest_id
            if not waste_location:
                raise UserError(_("Please specify a waste destination location."))

            # Ensure company matches source location to avoid "Incompatible companies on records"
            if source_location.company_id and record.company_id != source_location.company_id:
                record.company_id = source_location.company_id.id

            # Create and validate stock move
            move_vals = {
                'name': _('Waste: %s - %s', record.name, record.product_id.display_name),
                'product_id': record.product_id.id,
                'product_uom_qty': record.quantity,
                'product_uom': record.product_uom_id.id,
                'location_id': source_location.id,
                'location_dest_id': waste_location.id,
                'origin': record.name,
                'company_id': record.company_id.id,
                'move_line_ids': [(0, 0, {
                    'product_id': record.product_id.id,
                    'product_uom_id': record.product_uom_id.id,
                    'quantity': record.quantity,
                    'location_id': source_location.id,
                    'location_dest_id': waste_location.id,
                    'company_id': record.company_id.id,
                })],
            }
            stock_move = self.env['stock.move'].create(move_vals)
            stock_move._action_confirm()
            stock_move._action_assign()
            stock_move._action_done()

            # Update KDS: Increase cancelled quantity so it disappears/decreases on screen
            if record.preparation_display_orderline_id:
                line = record.preparation_display_orderline_id
                line.product_cancelled += record.quantity

                # Check if entire order is now fully wasted/cancelled
                order = line.preparation_display_order_id
                all_wasted = True
                for l in order.preparation_display_order_line_ids:
                    if l.product_quantity > l.product_cancelled:
                        all_wasted = False
                        break

                if all_wasted:
                    order.displayed = False

                # Notify KDS to reload
                if record.preparation_display_id:
                    record.preparation_display_id._send_load_orders_message()
                else:
                    # Fallback: notify all displays that might have this order
                    displays = self.env['pos_preparation_display.display'].search([])
                    for d in displays:
                        if order.pos_config_id in d.pos_config_ids or not d.pos_config_ids:
                            d._send_load_orders_message()

            record.write({
                'stock_move_id': stock_move.id,
                'state': 'confirmed',
            })

            _logger.info(
                "Waste log %s confirmed: %s × %s %s → %s",
                record.name, record.quantity,
                record.product_uom_id.name, record.product_id.display_name,
                waste_location.display_name
            )

    def action_cancel(self):
        """Cancel the waste log. Does NOT reverse the stock move."""
        for record in self:
            if record.state == 'confirmed' and record.stock_move_id:
                raise UserError(
                    _("Cannot cancel a confirmed waste log with a completed stock move. "
                      "Please create a manual inventory adjustment if needed.")
                )
            record.state = 'cancelled'

    def action_draft(self):
        """Reset to draft."""
        for record in self:
            if record.state == 'cancelled':
                record.state = 'draft'

    @api.model
    def get_kds_waste_data(self, pos_order_id=False):
        """Return waste reasons and POS products for the KDS waste log popup."""
        reasons = self.env['waste.reason'].sudo().search_read(
            [('active', '=', True)],
            ['id', 'name', 'sequence'],
            order='sequence, id',
        )
        products = self.env['product.product'].sudo().search_read(
            [('available_in_pos', '=', True), ('active', '=', True)],
            ['id', 'display_name', 'uom_id'],
            order='id',
        )

        # Determine locations based on POS order if provided
        pos_config = False
        if pos_order_id:
            order = self.env['pos.order'].sudo().browse(pos_order_id)
            if order:
                pos_config = order.config_id

        if not pos_config:
            # Fallback to current session
            pos_session = self.env['pos.session'].search([('user_id', '=', self.env.user.id), ('state', '=', 'opened')], limit=1)
            if pos_session:
                pos_config = pos_session.config_id

        # Source Location
        source_loc = False
        if pos_config and pos_config.picking_type_id.default_location_src_id:
            source_loc = pos_config.picking_type_id.default_location_src_id
        else:
            warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
            if warehouse:
                source_loc = warehouse.lot_stock_id

        # Destination Location (Waste)
        dest_loc = False
        if pos_config and pos_config.waste_location_id:
            dest_loc = pos_config.waste_location_id
        elif self.env.company.waste_location_id:
            dest_loc = self.env.company.waste_location_id
        else:
            dest_loc = self.env.ref('cz_waste_management.stock_location_waste', raise_if_not_found=False)

        return {
            'reasons': reasons,
            'products': products,
            'default_location': source_loc.read(['id', 'display_name'])[0] if source_loc else False,
            'default_dest_location': dest_loc.read(['id', 'display_name'])[0] if dest_loc else False,
        }

    @api.model
    def create_from_kds(self, **kwargs):
        """Create and auto-confirm multiple waste logs from the KDS popup.

        This is called via orm.call from the KDS frontend.
        """
        items = kwargs.get('items', [])
        if not items and kwargs.get('product_id'):
            # Fallback for single item if still used
            items = [{
                'product_id': kwargs['product_id'],
                'quantity': kwargs['quantity'],
                'total_qty_ordered': kwargs.get('total_qty_ordered'),
            }]

        if not items:
            return {'success': False, 'error': 'No items provided for waste logging.'}

        reason_id = kwargs.get('reason_id')
        if not reason_id:
            return {'success': False, 'error': 'Missing required field: reason_id'}

        try:
            created_logs = self.env['waste.log']
            for item in items:
                vals = {
                    'product_id': int(item['product_id']),
                    'quantity': float(item['quantity']),
                    'total_qty_ordered': float(item['total_qty_ordered'] or 0.0),
                    'reason_id': int(reason_id),
                    'other_reason': kwargs.get('other_reason', ''),
                    'station': kwargs.get('station', ''),
                    'notes': kwargs.get('notes', ''),
                    'order_ref': kwargs.get('order_ref', ''),
                }

                if item.get('preparation_display_orderline_id'):
                    vals['preparation_display_orderline_id'] = int(item['preparation_display_orderline_id'])

                # Optional photo
                if kwargs.get('photo'):
                    vals['photo'] = kwargs['photo']
                    vals['photo_filename'] = kwargs.get('photo_filename', 'waste_photo.jpg')

                # Optional POS order link
                if kwargs.get('pos_order_id'):
                    vals['pos_order_id'] = int(kwargs['pos_order_id'])

                # Optional preparation display link
                if kwargs.get('preparation_display_id'):
                    vals['preparation_display_id'] = int(kwargs['preparation_display_id'])

                # Source Location
                if kwargs.get('location_id'):
                    vals['location_id'] = int(kwargs['location_id'])
                
                # Destination Location
                if kwargs.get('location_dest_id'):
                    vals['location_dest_id'] = int(kwargs['location_dest_id'])

                waste_log = self.create(vals)
                waste_log.action_confirm()
                created_logs += waste_log

            _logger.info(
                "%d Waste logs created from KDS by user %s",
                len(created_logs), self.env.user.name,
            )

            return {
                'success': True,
                'count': len(created_logs),
                'first_log_name': created_logs[0].name if created_logs else 'New',
            }

        except Exception as e:
            _logger.exception("Error creating waste logs from KDS")
            return {
                'success': False,
                'error': str(e),
            }
