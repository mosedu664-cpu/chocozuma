# -*- coding: utf-8 -*-
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class WhatsappMessage(models.Model):
    _inherit = "whatsapp.message"

    @api.model_create_multi
    def create(self, vals_list):
        messages = super().create(vals_list)
        # Never raise: the Meta webhook must always get its 200.
        try:
            inbound = messages.filtered(lambda m: m.message_type == "inbound")
            queued = self.env["cz.loyalty.inbound"]
            if inbound:
                with self.env.cr.savepoint():
                    queued = self.env["cz.loyalty.inbound"].sudo()._enqueue(inbound)
            # Answer at once, inside the webhook request: the guest is waiting at the table and the
            # scheduled job can be minutes late. Whatever fails here stays queued for that job.
            for rec in queued:
                try:
                    with self.env.cr.savepoint():
                        rec._process()
                except Exception as e:  # noqa: BLE001
                    _logger.exception("cz_loyalty: inline processing of inbound %s failed", rec.id)
                    rec._schedule_retry(str(e))
            if queued.filtered(lambda r: r.state in ("queued", "pending", "failed")):
                cron = self.env.ref("cz_loyalty.ir_cron_cz_loyalty_inbound", raise_if_not_found=False)
                if cron:
                    cron._trigger()
        except Exception:
            _logger.exception("cz_loyalty: could not handle inbound WhatsApp message")
        return messages
