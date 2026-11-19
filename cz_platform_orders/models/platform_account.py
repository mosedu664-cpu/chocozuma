# -*- coding: utf-8 -*-
import logging
import time

from odoo import api, fields, models
from odoo.exceptions import UserError

from .trendyol_client import TrendyolYemekClient, TrendyolYemekError

_logger = logging.getLogger(__name__)

HOUR_MS = 3600 * 1000
WINDOW_MS = 6 * HOUR_MS          # one API call covers at most 6 hours
OVERLAP_MS = 15 * 60 * 1000      # re-read the last 15 min on every sync


class CzPlatformAccount(models.Model):
    _name = 'cz.platform.account'
    _description = 'Delivery Platform Account'
    _order = 'sequence, id'

    name = fields.Char(required=True, help="Örn: Trendyol Yemek — Choco Zuma — Kayaşehir (Çikolata)")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    platform = fields.Selection(
        [('trendyol_yemek', 'Trendyol Yemek (Uber Eats Trendyol Go)'),
         ('yemeksepeti', 'Yemeksepeti')],
        required=True, default='trendyol_yemek')
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        help="Platform faturasının kesildiği şirket (Choco Zuma, Tonalli, Mayapan).")
    pos_config_id = fields.Many2one(
        'pos.config', string='Branch / POS',
        help="Step 2: orders of this account become sales of this POS.")
    sales_line = fields.Selection(
        [('chocolate', 'Çikolata'), ('breakfast', 'Kahvaltı')],
        string='Sales line', default='chocolate', required=True)
    environment = fields.Selection(
        [('prod', 'Canlı (Production)'), ('stage', 'Test (Stage)')],
        default='prod', required=True)

    # --- credentials: administrators only -------------------------------
    supplier_ref = fields.Char('Satıcı ID (Cari ID)', groups='base.group_system')
    store_ref = fields.Char(
        'Store / Restaurant ID', groups='base.group_system',
        help="Optional. Empty = all restaurants of this Satıcı ID.")
    api_key = fields.Char('API Key', groups='base.group_system')
    api_secret = fields.Char('API Secret', groups='base.group_system')
    executor_user = fields.Char(
        'Executor e-mail', groups='base.group_system',
        default='muhasebeonline@chocozuma.com',
        help="Sent in the x-executor-user header (who performs the call).")

    # --- POS posting (step 2) --------------------------------------------
    auto_post = fields.Boolean(
        'Create POS sales', default=False,
        help="ON: every new platform order becomes a POS sale of the branch "
             "(and goes to the kitchen display). OFF: orders are only stored.")
    post_from = fields.Datetime(
        'Go-live from',
        help="Only orders created after this moment become POS sales. Earlier "
             "orders were typed by the cashier and are never posted again.")
    payment_method_id = fields.Many2one(
        'pos.payment.method', string='POS payment method',
        help="Payment method used for platform sales (Kayaşehir: Online Payment).")
    partner_id = fields.Many2one('res.partner', string='POS customer', help="E.g. *TRENDYOL")
    map_ids = fields.One2many('cz.platform.product.map', 'account_id', string='Product mapping')
    map_count = fields.Integer(compute='_compute_map_count')
    attention_count = fields.Integer(compute='_compute_order_count')

    # --- status ---------------------------------------------------------
    last_sync_ms = fields.Float('Last sync (epoch ms)', readonly=True, digits=(16, 0))
    last_sync = fields.Datetime(readonly=True)
    last_result = fields.Text(readonly=True)
    order_ids = fields.One2many('cz.platform.order', 'account_id')
    order_count = fields.Integer(compute='_compute_order_count')

    def _compute_order_count(self):
        data = self.env['cz.platform.order']._read_group(
            [('account_id', 'in', self.ids)], ['account_id'], ['__count'])
        counts = {acc.id: n for acc, n in data}
        att = self.env['cz.platform.order']._read_group(
            [('account_id', 'in', self.ids),
             ('state', 'in', ('needs_mapping', 'review', 'error', 'waiting_session'))],
            ['account_id'], ['__count'])
        att = {acc.id: n for acc, n in att}
        for rec in self:
            rec.order_count = counts.get(rec.id, 0)
            rec.attention_count = att.get(rec.id, 0)

    @api.constrains('auto_post', 'store_ref', 'pos_config_id', 'payment_method_id', 'post_from')
    def _check_auto_post(self):
        for rec in self.sudo():
            if rec.auto_post and not (rec.store_ref and rec.pos_config_id
                                      and rec.payment_method_id and rec.post_from):
                raise UserError("POS satışını açmak için Store ID, Branch/POS, ödeme yöntemi ve "
                                "başlangıç zamanı zorunludur (Store ID boşsa kahvaltı hesabının "
                                "siparişleri de karışabilir).")

    def _compute_map_count(self):
        for rec in self:
            rec.map_count = len(rec.map_ids)

    # ------------------------------------------------------------------
    def _client(self):
        self.ensure_one()
        acc = self.sudo()
        if acc.platform != 'trendyol_yemek':
            raise UserError("Bu platform henüz desteklenmiyor (önce Trendyol Yemek).")
        return TrendyolYemekClient(acc.supplier_ref, acc.api_key, acc.api_secret,
                                   acc.executor_user, acc.environment)

    def _fetch_range(self, start_ms, end_ms):
        """Read every package modified in the range and store it. Read-only.

        Windows are read newest -> oldest. Trendyol only serves a limited
        history: when an older window is refused after at least one window
        succeeded, we stop there and report how far back we got.
        """
        self.ensure_one()
        client = self._client()
        Order = self.env['cz.platform.order'].sudo()
        created = updated = 0
        reached = int(end_ms)
        cursor = int(end_ms)
        limited = False
        while cursor > start_ms:
            begin = max(cursor - WINDOW_MS, int(start_ms))
            try:
                for pkg in client.iter_packages(begin, cursor, store_id=self.sudo().store_ref or None):
                    if Order._upsert_from_trendyol(self, pkg):
                        created += 1
                    else:
                        updated += 1
            except TrendyolYemekError as e:
                if e.history_limit and reached < int(end_ms):
                    limited = True
                    break
                raise  # 429 / timeout / auth: last_sync is NOT advanced
            reached = begin
            cursor = begin
        return created, updated, reached, limited

    def _run_sync(self, start_ms, end_ms):
        """Fetch + process. One run per account at a time: a session-level
        advisory lock (survives the per-order commits of the cron) makes the
        cron and the manual buttons never overlap."""
        cr = self.env.cr
        for acc in self:
            cr.execute("SELECT pg_try_advisory_lock(%s, %s)", (874201, acc.id))
            if not cr.fetchone()[0]:
                continue
            try:
                try:
                    with cr.savepoint():
                        created, updated, reached, limited = acc._fetch_range(start_ms, end_ms)
                    msg = "OK — %s yeni, %s güncellenen sipariş." % (created, updated)
                    if limited:
                        days = (end_ms - reached) / (24.0 * HOUR_MS)
                        msg += " Trendyol geçmişi sınırlı: en fazla %.1f gün geriye okunabildi." % days
                    acc.write({'last_sync_ms': end_ms, 'last_sync': fields.Datetime.now(),
                               'last_result': msg})
                except (TrendyolYemekError, UserError) as e:
                    acc.write({'last_result': "HATA: %s" % e})
                    _logger.warning("cz_platform_orders %s: %s", acc.name, e)
                if self.env.context.get('cz_commit'):
                    cr.commit()
                # posting runs even if the fetch failed (retries of waiting orders)
                acc._process_orders()
            finally:
                cr.execute("SELECT pg_advisory_unlock(%s, %s)", (874201, acc.id))

    PROCESS_BATCH = 20

    def _process_orders(self):
        """Post at most PROCESS_BATCH orders per run (oldest first); the 2-min
        cron drains any backlog. In the cron every order is committed on its
        own, so a long backlog never hits the worker time limit."""
        self.ensure_one()
        Order = self.env['cz.platform.order'].sudo()
        # refunds of posted+cancelled orders always run (even if posting is off)
        domain = ['&', ('state', '=', 'posted'), ('status', 'in', ('Cancelled', 'UnSupplied'))]
        if self.auto_post:
            domain = ['|', '|',
                      ('state', 'in', ('new', 'waiting_session', 'needs_mapping')),
                      '&', ('state', '=', 'error'), ('attempts', '<', 5)] + domain
        todo = Order.search([('account_id', '=', self.id)] + domain,
                            order='order_date asc, id asc', limit=self.PROCESS_BATCH)
        todo._cz_process()

    def _process_orders_locked(self):
        """Same lock as _run_sync, for the manual retry button."""
        cr = self.env.cr
        for acc in self:
            cr.execute("SELECT pg_try_advisory_lock(%s, %s)", (874201, acc.id))
            if not cr.fetchone()[0]:
                raise UserError("Senkronizasyon şu an çalışıyor, birkaç saniye sonra tekrar deneyin.")
            try:
                acc._process_orders()
            finally:
                cr.execute("SELECT pg_advisory_unlock(%s, %s)", (874201, acc.id))

    # --- buttons ----------------------------------------------------------
    def action_load_default_mapping(self):
        self.ensure_one()
        created, missing = self.env['cz.platform.product.map'].sudo()._load_default_trendyol_map(self)
        msg = "%s eşleştirme eklendi." % created
        if missing:
            msg += " Bulunamayan ürün kodları: %s" % ', '.join(missing)
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': self.name, 'message': msg,
                           'type': 'warning' if missing else 'success', 'sticky': bool(missing)}}

    def action_open_mapping(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'cz_platform_orders.action_cz_platform_product_map')
        action['domain'] = [('account_id', '=', self.id)]
        action['context'] = {'default_account_id': self.id}
        return action

    def action_open_attention(self):
        action = self.action_open_orders()
        action['domain'] = [('account_id', '=', self.id),
                            ('state', 'in', ('needs_mapping', 'review', 'error', 'waiting_session'))]
        return action

    def action_fetch_last_24h(self):
        now = int(time.time() * 1000)
        self._run_sync(now - 24 * HOUR_MS, now)
        return self._notify()

    def action_fetch_last_7d(self):
        now = int(time.time() * 1000)
        self._run_sync(now - 7 * 24 * HOUR_MS, now)
        return self._notify()

    def action_fetch_last_35d(self):
        now = int(time.time() * 1000)
        self._run_sync(now - 35 * 24 * HOUR_MS, now)
        return self._notify()

    def action_open_orders(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'cz_platform_orders.action_cz_platform_order')
        action['domain'] = [('account_id', '=', self.id)]
        return action

    def _notify(self):
        self.ensure_one()
        ok = (self.last_result or '').startswith('OK')
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': self.name, 'message': self.last_result or '',
                       'type': 'success' if ok else 'danger', 'sticky': not ok},
        }

    # --- one payment method per platform (Kayaşehir) ----------------------
    PLATFORM_METHODS = [
        ('TYC', 'Trendyol Çikolata', 'chocolate'),
        ('TYK', 'Trendyol Kahvaltı', 'breakfast'),
        ('YSC', 'Yemeksepeti Çikolata', None),
        ('YSK', 'Yemeksepeti Kahvaltı', None),
    ]
    PM_SPLIT_PARAM = 'cz_platform_orders.pm_split_done'

    @api.model
    def _cz_ensure_platform_methods(self):
        """Once: create journal + POS payment method per platform on the POS
        that receives both chocolate and breakfast Trendyol orders, and point
        the Trendyol accounts to their own method. Runs from the cron (full
        registry loaded: a module-upgrade migration cannot create accounts
        because account_asset is not loaded yet). Idempotent by journal code.
        'Online Payment' is left untouched."""
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param(self.PM_SPLIT_PARAM):
            return
        accounts = self.sudo().with_context(active_test=False).search([
            ('platform', '=', 'trendyol_yemek'), ('pos_config_id', '!=', False)])
        configs = accounts.filtered(lambda a: a.sales_line == 'breakfast').pos_config_id
        for config in configs:
            company = config.company_id
            Journal = self.env['account.journal'].sudo().with_company(company)
            Method = self.env['pos.payment.method'].sudo().with_company(company)
            by_line = {}
            for code, name, line in self.PLATFORM_METHODS:
                journal = Journal.search([('code', '=', code), ('company_id', '=', company.id)], limit=1)
                if not journal:
                    journal = Journal.create({'name': name + ' Tahsilat', 'code': code,
                                              'type': 'bank', 'company_id': company.id})
                method = Method.with_context(active_test=False).search(
                    [('journal_id', '=', journal.id), ('company_id', '=', company.id)], limit=1)
                if not method:
                    method = Method.create({'name': name, 'journal_id': journal.id,
                                            'company_id': company.id})
                if config not in method.config_ids:
                    # written from the method side: allowed while a session exists
                    method.write({'config_ids': [(4, config.id)]})
                if line:
                    by_line[line] = method
                _logger.info("cz_platform_orders: %s -> journal %s, method %s on %s",
                             name, journal.code, method.id, config.name)
            for acc in accounts.filtered(lambda a: a.pos_config_id == config):
                method = by_line.get(acc.sales_line)
                if method and acc.payment_method_id != method:
                    acc.payment_method_id = method
        ICP.set_param(self.PM_SPLIT_PARAM, fields.Datetime.now())

    # --- cron -------------------------------------------------------------
    @api.model
    def _cron_sync(self):
        try:
            with self.env.cr.savepoint():
                self._cz_ensure_platform_methods()
        except Exception:  # noqa: BLE001 - never block order reading
            _logger.exception("cz_platform_orders: payment method split failed")
        now = int(time.time() * 1000)
        self = self.with_context(cz_commit=True)
        for acc in self.search([('platform', '=', 'trendyol_yemek')]):
            start = int(acc.last_sync_ms or 0) - OVERLAP_MS
            if start <= 0 or now - start > 7 * 24 * HOUR_MS:
                start = now - 24 * HOUR_MS
            acc._run_sync(start, now)
