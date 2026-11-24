# -*- coding: utf-8 -*-
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class WhatsappMessage(models.Model):
    _inherit = "whatsapp.message"

    @api.model_create_multi
    def create(self, vals_list):
        messages = super().create(vals_list)
        # Only enqueue. Never raise: the Meta webhook must always get its 200.
        try:
            inbound = messages.filtered(lambda m: m.message_type == "inbound")
            if inbound:
                with self.env.cr.savepoint():
                    if self.env["cz.loyalty.inbound"].sudo()._enqueue(inbound):
                        cron = self.env.ref("cz_loyalty.ir_cron_cz_loyalty_inbound", raise_if_not_found=False)
                        if cron:
                            cron._trigger()
        except Exception:
            _logger.exception("cz_loyalty: could not enqueue inbound WhatsApp message")
        return messages
