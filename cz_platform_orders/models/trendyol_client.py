# -*- coding: utf-8 -*-
"""Minimal READ-ONLY client for the Uber Eats Trendyol Go — Yemek API.

Endpoints and headers follow developers.tgoapps.com:
  GET {base}/integrator/order/meal/suppliers/{supplierId}/packages
      ?packageStatuses=...&packageModificationStartDate=<ms>
      &packageModificationEndDate=<ms>&page=<n>&size=<<=50>
  Authorization: Basic base64(apiKey:apiSecret)
  User-Agent: "<supplierId> - <integrator name>"
  x-agentname / x-executor-user

There is deliberately NO method that sends PUT/POST/DELETE: this client can
never accept, reject, cancel or modify an order on the platform.
"""
import base64
import logging

import requests

_logger = logging.getLogger(__name__)

BASE_URLS = {
    'prod': 'https://api.tgoapis.com',
    'stage': 'https://stageapi.tgoapis.com',
}
ALL_STATUSES = 'Created,Picking,Invoiced,Shipped,Delivered,Cancelled,UnSupplied'
PAGE_SIZE = 50
TIMEOUT = 20
AGENT_NAME = 'ChocoZumaOdoo'


class TrendyolYemekError(Exception):
    def __init__(self, message, status=None, history_limit=False):
        super().__init__(message)
        self.status = status
        self.history_limit = history_limit


class TrendyolYemekClient:
    def __init__(self, supplier_id, api_key, api_secret, executor_user, environment='prod'):
        if not (supplier_id and api_key and api_secret):
            raise TrendyolYemekError("Satıcı ID, API Key ve API Secret zorunludur.")
        self.supplier_id = str(supplier_id).strip()
        self.base = BASE_URLS.get(environment or 'prod', BASE_URLS['prod'])
        token = base64.b64encode(
            ('%s:%s' % (api_key.strip(), api_secret.strip())).encode()).decode()
        self.headers = {
            'Authorization': 'Basic %s' % token,
            'User-Agent': '%s - %s' % (self.supplier_id, AGENT_NAME),
            'x-agentname': AGENT_NAME,
            'x-executor-user': (executor_user or 'integration@chocozuma.com').strip(),
            'Accept': 'application/json',
        }

    def _get(self, path, params):
        url = '%s%s' % (self.base, path)
        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise TrendyolYemekError("Bağlantı hatası: %s" % e)
        if resp.status_code == 401 or resp.status_code == 403:
            raise TrendyolYemekError(
                "Yetki hatası (HTTP %s): Satıcı ID / API Key / API Secret kontrol edin." % resp.status_code)
        if resp.status_code == 429:
            raise TrendyolYemekError("Trendyol hız sınırı (HTTP 429). Birkaç dakika sonra tekrar deneyin.", status=429)
        if not resp.ok:
            body = resp.text or ''
            # Trendyol answers 400 'external.domain.rejects.request' for dates
            # older than its history window (31 days) - only that is a limit.
            limit = resp.status_code == 400 and 'external.domain.rejects.request' in body
            raise TrendyolYemekError("HTTP %s: %s" % (resp.status_code, body[:800]),
                                     status=resp.status_code, history_limit=limit)
        try:
            return resp.json()
        except ValueError:
            raise TrendyolYemekError("Geçersiz JSON cevabı: %s" % (resp.text or '')[:300])

    def iter_packages(self, start_ms, end_ms, statuses=ALL_STATUSES, store_id=None, max_pages=40):
        """Yield every package modified in [start_ms, end_ms], all pages."""
        path = '/integrator/order/meal/suppliers/%s/packages' % self.supplier_id
        page = 0
        while page < max_pages:
            params = {
                'packageStatuses': statuses,
                'packageModificationStartDate': int(start_ms),
                'packageModificationEndDate': int(end_ms),
                'page': page,
                'size': PAGE_SIZE,
            }
            if store_id:
                params['storeId'] = store_id
            data = self._get(path, params) or {}
            content = data.get('content') or []
            for pkg in content:
                yield pkg
            total_pages = data.get('totalPages')
            page += 1
            if not content or (total_pages is not None and page >= int(total_pages)):
                break
