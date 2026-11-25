"""Message statuses Odoo does not know about.

Meta keeps adding values to the ``statuses`` webhook: ``played`` arrived in March
2026, for the first time a voice note is played. Odoo writes whatever Meta sends
straight into ``whatsapp.message.state``, so a value outside that field's
selection raises ``ValueError`` and the whole delivery fails. Meta then retries
it for 36 hours with the same result and the acknowledgement is lost.

Two things happen here, before Odoo reads the payload:

* ``played`` is stored as ``read`` -- a voice note cannot be played without the
  chat being opened, so the meaning is kept and no view, filter or report has to
  learn a new state.
* any other status this Odoo cannot store is logged and dropped, so the delivery
  is accepted. An acknowledgement we cannot read is no reason to reject the
  whole webhook, and the next value Meta invents will not break the number.
"""
import logging

from odoo import models

_logger = logging.getLogger(__name__)

# Meta status -> the state that means the same thing in Odoo
EQUIVALENT = {'played': 'read'}

# Statuses Odoo translates on its own: they are not values of the state field,
# and must not be dropped here.
TRANSLATED_BY_ODOO = ('failed',)


class WhatsAppMessage(models.Model):
    _inherit = 'whatsapp.message'

    def _process_statuses(self, value):
        statuses = value.get('statuses') or []
        if statuses:
            clean = [entry for entry in (self._coex_known_status(s) for s in statuses) if entry]
            if clean != statuses:
                # a copy: the caller keeps reading the original payload afterwards
                value = dict(value, statuses=clean)
        return super()._process_statuses(value)

    def _coex_known_status(self, status):
        """One entry of ``value['statuses']``: unchanged, rewritten, or None to skip."""
        name = (status or {}).get('status')
        if not name:
            return status
        known = set(self._fields['state'].get_values(self.env))
        equivalent = EQUIVALENT.get(name)
        if equivalent in known:
            return dict(status, status=equivalent)
        if name in known or name in TRANSLATED_BY_ODOO:
            return status
        _logger.info(
            "WhatsApp: this Odoo cannot store the message status %r, so it is ignored. "
            "The delivery is accepted, no message is lost.", name)
        return None
