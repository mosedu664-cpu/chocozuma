# -*- coding: utf-8 -*-
# cz_customizations/models/nilvera_fetch.py              CHOCO ZUMA — 30/10/2026
# NEDEN: Odoo'nun l10n_tr_nilvera_einvoice modülü gelen faturaları "GET /einvoice/Purchase?StatusCode=succeed" ile ister —
#        sayfa / sayfa boyutu / tarih parametresi YOK → Nilvera yalnız 1. sayfayı (en yeni ~10-20 belge) döndürür.
#        Günde 30-40 belge gelince (CZ tedarikçi faturaları + şubelere giden INV kopyaları) ilk sayfaya sığmayanlar
#        liste kayana kadar (ertesi gün 00:11) ya da daha geç düşer → 3-5 gün gecikme, gece yarısı yığınları.
# NE YAPAR: Aynı Odoo akışını (XML indir → fatura oluştur → PDF ekle) korur; yalnız listeyi TÜM SAYFALARIYLA,
#        son 20 günün belgeleri için (DateFilterType=CreatedDate), 100'erlik sayfalarla çeker. Zaten var olan UUID'ler atlanır.
# KURULUM: dosyayı cz_customizations/models/ altına koy, models/__init__.py'ye "from . import nilvera_fetch" ekle,
#        __manifest__.py depends listesine 'l10n_tr_nilvera_einvoice' ekle, sürümü artır (0.5) → staging'de test → main.
#        Cron "Nilvera: retrieve new documents": 1 saat → 30 dakika.
from datetime import datetime, timedelta
from urllib.parse import quote

import logging

from odoo import models
from odoo.addons.l10n_tr_nilvera.lib.nilvera_client import _get_nilvera_client

_logger = logging.getLogger(__name__)

FETCH_DAYS = 20      # bu kadar gün geriye bak (tedarikçi e-faturayı irsaliyeden 7 güne kadar sonra kesebilir)
PAGE_SIZE = 100


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _l10n_tr_nilvera_get_documents(self, invoice_channel="einvoice", document_category="Purchase", journal_type="purchase"):
        # GÜVENLİK AĞI: sayfalı istek herhangi bir nedenle hata verirse (parametre reddi, ağ) Odoo'nun kendi yöntemine geri dönülür —
        # fatura çekme asla durmaz, en kötü ihtimalle eski davranış sürer.
        try:
            self._cz_nilvera_get_documents_paged(invoice_channel, document_category, journal_type)
        except Exception as e:  # noqa: BLE001
            _logger.warning("CZ Nilvera paged fetch failed (%s) — falling back to standard fetch", e)
            super()._l10n_tr_nilvera_get_documents(invoice_channel, document_category, journal_type)

    def _cz_nilvera_get_documents_paged(self, invoice_channel, document_category, journal_type):
        with _get_nilvera_client(self.env.company) as client:
            now = datetime.utcnow()
            base_params = {
                "StatusCode": ["succeed"],
                "PageSize": PAGE_SIZE,
                "SortColumn": "CreatedDate",
                "SortType": "DESC",
                "DateFilterType": "CreatedDate",
                "StartDate": (now - timedelta(days=FETCH_DAYS)).strftime("%Y-%m-%dT00:00:00"),
                "EndDate": (now + timedelta(days=1)).strftime("%Y-%m-%dT23:59:59"),
            }
            journal = self._l10n_tr_get_nilvera_invoice_journal(journal_type)
            page = 1
            while True:
                response = client.request("GET", f"/{invoice_channel}/{quote(document_category)}", params=dict(base_params, Page=page))
                if not response or not response.get('Content'):
                    break
                document_uuids, document_uuids_records, document_uuids_references = self._l10n_tr_build_document_uuids_list(response)
                for document_uuid in document_uuids:
                    move = document_uuids_records.get(document_uuid)
                    if not move:
                        move = self._l10n_tr_nilvera_get_invoice_from_uuid(client, journal, document_uuid, document_category, invoice_channel)
                        self._l10n_tr_nilvera_add_pdf_to_invoice(client, move, document_uuid, document_category, invoice_channel)
                    elif not move.ref and (nilvera_reference := document_uuids_references.get(document_uuid)):
                        move.ref = nilvera_reference
                        self._l10n_tr_nilvera_add_pdf_to_invoice(client, move, document_uuid, document_category, invoice_channel)
                    self._cr.commit()
                total_pages = response.get('TotalPages')
                if len(response.get('Content', [])) < PAGE_SIZE or (total_pages and page >= total_pages):
                    break
                page += 1
