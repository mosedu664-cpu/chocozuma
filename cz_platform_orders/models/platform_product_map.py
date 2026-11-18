# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError

# Choco Zuma Kayaşehir — Trendyol Yemek menu -> Odoo product (default_code),
# built from 31 days of real orders and checked against what the cashiers
# typed for the same orders (same products, same prices).
# kind 'product': Trendyol productId ; kind 'extra': Trendyol extraIngredient id
DEFAULT_TRENDYOL_MAP = {
    'product': {
        '492192': ('Su (33 cl.)', 'S-227', []),
        '492200': ('Soda (20 cl.)', 'S-185', []),
        '492209': ('Sütlü Çikolata (50 gr.)', 'SO-046', []),
        '492210': ('Bitter Çikolata (50 gr.)', 'SO-040', []),
        '492212': ('Kinder Çikolata (50 gr.)', 'SO-047', []),
        '492221': ('Brownie (125 gr.)', 'SO-038', []),
        '492232': ('Çilek (100 gr.)', 'SO-053', []),
        '492235': ('Strawberry Brownies Box', 'SO-035', []),
        '492242': ('Chocolate Volcano', 'SO-023', []),
        '492252': ('Share Box', 'SO-034-C', ['S-261', 'S-264', 'S-256']),
        '492290': ('Zuma Cup', 'SO-027', []),
        '492318': ('Double Chocolate Krep', 'SO-016', []),
        '492319': ('Brownie Zuma Krep', 'SO-014', []),
        '492322': ('Waffle Spesiyal', 'SO-009', []),
        '492327': ('Zuma Roll', 'SO-020', []),
        '492329': ('Brownies Waffle', 'SO-001', []),
        '6191714': ('Strawberry Profiteroles Bites', 'SO-030', []),
        '6330355': ('Tropical Fettuccini', 'SO-019', []),
        '6330356': ('Strawberry Cream Waffle', 'SO-011', []),
        '6330358': ('Crunchy Biscoff Crepe', 'SO-015', []),
        '6330359': ('Lotus Volcano', 'SO-026', []),
        '6330360': ('Lotus Waffle', 'SO-005', []),
        '8588126': ('Aztec Box', 'SO-033-C', ['S-261', 'S-264', 'S-256', 'S-258']),
        '11140438': ('Çıtır Krispi Parçacıkları', 'SO-039', []),
        '11140463': ('Bisküvi Parçacıkları', 'SO-037', []),
        '11140488': ('Lotus Parçacıkları', 'SO-041', []),
        '11140510': ('Oreo Parçacıkları', 'SO-043', []),
        '11267300': ('Oreo Waffle', 'SO-007', []),
        '18458181': ('Mini Zuma Roll', 'SO-018', []),
        '18458415': ('Lotus Profiterole Stick', 'SO-025', []),
        '18458614': ('Choco Profiterole Stick', 'SO-022', []),
    },
    'extra': {
        '67698': ('+ Lotus', 'SO-041', []),
        '67695': ('+ Çilek', 'SO-048', []),
        '67696': ('+ Muz', 'SO-049', []),
        '637279': ('+ Sütlü çikolata (50g)', 'SO-056', []),
        '67699': ('+ Oreo', 'SO-043', []),
        '67697': ('+ Bisküvi', 'SO-037', []),
        '659348': ('+ Çilek (100gr.)', 'SO-045', []),
        '659350': ('+ Çıtır Krispi Parçacıkları', 'SO-039', []),
        '637280': ('+ Beyaz çikolata (50g)', 'SO-051', []),
        '659349': ('+ Muz (100gr.)', 'SO-036', []),
    },
}


class CzPlatformProductMap(models.Model):
    _name = 'cz.platform.product.map'
    _description = 'Platform product -> Odoo product'
    _order = 'account_id, kind, platform_name'

    account_id = fields.Many2one('cz.platform.account', required=True, ondelete='cascade', index=True)
    kind = fields.Selection([('product', 'Ürün'), ('extra', 'Ekstra')], required=True, default='product')
    platform_ref = fields.Char('Platform ID', required=True, index=True)
    platform_name = fields.Char('Platform name')
    product_id = fields.Many2one(
        'product.product', string='Odoo product', required=True,
        help="For boxes choose the combo product (Custom Combo).")
    is_combo = fields.Boolean(compute='_compute_is_combo')
    combo_choice_ids = fields.Many2many(
        'product.product', 'cz_platform_map_combo_choice_rel', 'map_id', 'product_id',
        string='Combo choices (in order)',
        help="For a combo product: the product picked in each multi-choice combo "
             "step, in order (e.g. the 3 or 4 chocolate sauces).")
    last_price = fields.Float('Last platform price', digits=(16, 2), readonly=True)
    note = fields.Char()

    _sql_constraints = [
        ('map_uniq', 'unique(account_id, kind, platform_ref)', 'This platform item is already mapped.'),
    ]

    @api.depends('product_id')
    def _compute_is_combo(self):
        for rec in self:
            rec.is_combo = rec.product_id.type == 'combo'

    @api.model
    def _load_default_trendyol_map(self, account):
        """Create the missing default rows for one Trendyol account."""
        Product = self.env['product.product'].with_context(active_test=False)
        created, missing = 0, []

        def by_code(code):
            prod = Product.search([('default_code', '=', code)], limit=1)
            if not prod:
                missing.append(code)
            return prod

        for kind, rows in DEFAULT_TRENDYOL_MAP.items():
            for ref, (name, code, choices) in rows.items():
                if self.search_count([('account_id', '=', account.id), ('kind', '=', kind),
                                      ('platform_ref', '=', ref)]):
                    continue
                prod = by_code(code)
                choice_prods = [by_code(c) for c in choices]
                if not prod or not all(choice_prods):
                    continue
                self.create({
                    'account_id': account.id, 'kind': kind, 'platform_ref': ref,
                    'platform_name': name, 'product_id': prod.id,
                    'combo_choice_ids': [(6, 0, [p.id for p in choice_prods])],
                })
                created += 1
        return created, sorted(set(missing))
