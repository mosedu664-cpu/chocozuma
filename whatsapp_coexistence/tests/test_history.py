from unittest.mock import patch

from odoo.addons.whatsapp.tests.common import WhatsAppCommon
from odoo import fields
from odoo.tests import tagged

CUSTOMER = '5492615335773'
BUSINESS = '5492613400122'


@tagged('post_install', '-at_install', 'whatsapp_coexistence')
class TestCoexistenceHistory(WhatsAppCommon):
    """The chat history Meta sends once per onboarding must land in Discuss.

    Before this release the ``history`` field was ignored, so customers saw their
    channels start on the day they connected (Almacenar, November 2026).
    """

    def _payload(self, *messages):
        return {
            'messaging_product': 'whatsapp',
            'metadata': {'display_phone_number': BUSINESS, 'phone_number_id': '1'},
            'history': [{
                'metadata': {'phase': 0, 'chunk_order': 1, 'progress': 100},
                'threads': [{'id': CUSTOMER, 'messages': list(messages)}],
            }],
        }

    @staticmethod
    def _text(uid, sender, ts, body):
        return {'from': sender, 'id': uid, 'timestamp': str(ts), 'type': 'text',
                'text': {'body': body}, 'history_context': {'status': 'READ'}}

    def _messages(self, channel):
        return self.env['mail.message'].sudo().search(
            [('model', '=', 'discuss.channel'), ('res_id', '=', channel.id),
             ('message_type', '=', 'whatsapp_message')], order='date asc')

    def test_history_lands_in_discuss_with_original_dates(self):
        payload = self._payload(
            # out of order on purpose: they must be written oldest first
            self._text('wamid.h2', BUSINESS, 1760000100, 'Hola, ya te lo envío'),
            self._text('wamid.h1', CUSTOMER, 1760000000, '¿Tienen stock?'),
        )
        self.assertEqual(self.whatsapp_account._process_history(payload), 2)

        channel = self.whatsapp_account._find_active_channel(CUSTOMER)
        messages = self._messages(channel)
        self.assertEqual(len(messages), 2)
        first, second = messages
        self.assertEqual(first.author_id, channel.whatsapp_partner_id)
        self.assertNotEqual(second.author_id, channel.whatsapp_partner_id)
        self.assertEqual(str(first.date), '2025-10-09 08:53:20')
        self.assertEqual(first.wa_message_ids.message_type, 'inbound')
        self.assertEqual(second.wa_message_ids.message_type, 'outbound')
        self.assertEqual(second.wa_message_ids.state, 'sent')
        # A months-old customer message must not reopen the 24-hour window
        # (18+ leave it empty; 17 dates it from the message, already expired)
        valid_until = channel.whatsapp_channel_valid_until
        self.assertFalse(valid_until and valid_until > fields.Datetime.now())

    def test_history_is_deduplicated(self):
        payload = self._payload(self._text('wamid.dup', CUSTOMER, 1760000000, 'Hola'))
        self.assertEqual(self.whatsapp_account._process_history(payload), 1)
        self.assertEqual(self.whatsapp_account._process_history(payload), 0)

    def test_history_media_and_placeholder(self):
        image = {'from': CUSTOMER, 'id': 'wamid.img', 'timestamp': '1760000000', 'type': 'image',
                 'image': {'id': 'media-1', 'mime_type': 'image/jpeg', 'caption': 'la pieza'}}
        audio = {'from': CUSTOMER, 'id': 'wamid.aud', 'timestamp': '1760000001', 'type': 'audio',
                 'audio': {'id': 'media-2', 'mime_type': 'audio/ogg', 'voice': True}}

        def fake_download(api, media_id):
            if media_id == 'media-1':
                return b'jpeg-bytes'
            raise Exception('expired')

        with patch('odoo.addons.whatsapp.tools.whatsapp_api.WhatsAppApi._get_whatsapp_document',
                   fake_download):
            self.whatsapp_account._process_history(self._payload(image, audio))

        channel = self.whatsapp_account._find_active_channel(CUSTOMER)
        img, aud = self._messages(channel)
        # bytes(): in Odoo 20 `raw` is a BinaryValue, not bytes
        self.assertEqual(bytes(img.attachment_ids.raw), b'jpeg-bytes')
        self.assertIn('la pieza', img.body)
        self.assertFalse(aud.attachment_ids)
        self.assertIn('audio', aud.body)

    def test_one_bad_message_does_not_lose_the_rest(self):
        first = self._text('wamid.bad', CUSTOMER, 1760000000, 'se rompe')
        second = self._text('wamid.ok', CUSTOMER, 1760000001, 'bien')
        with patch.object(type(self.whatsapp_account), '_wacoex_history_content',
                          side_effect=[Exception('boom'), ('<p>bien</p>', self.env['ir.attachment'])]):
            imported = self.whatsapp_account._process_history(self._payload(first, second))
        self.assertEqual(imported, 1)

    def test_malformed_timestamp_does_not_break_the_thread(self):
        broken = dict(self._text('wamid.ts', CUSTOMER, 0, 'sin fecha'), timestamp='nope')
        ok = self._text('wamid.ts2', CUSTOMER, 1760000000, 'con fecha')
        self.assertEqual(self.whatsapp_account._process_history(self._payload(broken, ok)), 2)

    # -- media webhook: same field "history", top-level "messages", same wamid --
    @staticmethod
    def _placeholder(uid, sender, ts):
        return {'from': sender, 'id': uid, 'timestamp': str(ts), 'type': 'media_placeholder',
                'history_context': {'status': 'READ'}}

    @staticmethod
    def _media_payload(*messages):
        return {
            'messaging_product': 'whatsapp',
            'metadata': {'display_phone_number': BUSINESS, 'phone_number_id': '1'},
            'messages': list(messages),
        }

    @staticmethod
    def _image(uid, sender, ts, media_id='media-9'):
        return {'from': sender, 'id': uid, 'timestamp': str(ts), 'type': 'image',
                'image': {'id': media_id, 'mime_type': 'image/jpeg', 'caption': 'la foto'}}

    def _patched_download(self):
        return patch('odoo.addons.whatsapp.tools.whatsapp_api.WhatsAppApi._get_whatsapp_document',
                     lambda api, media_id: b'jpeg-bytes')

    def test_media_webhook_completes_the_placeholder(self):
        account = self.whatsapp_account
        account._process_history(self._payload(self._placeholder('wamid.ph', CUSTOMER, 1760000000)))
        channel = account._find_active_channel(CUSTOMER)
        message = self._messages(channel)
        self.assertFalse(message.attachment_ids)
        self.assertIn('did not include the file', message.body)

        with self._patched_download():
            self.assertEqual(account._process_history(
                self._media_payload(self._image('wamid.ph', CUSTOMER, 1760000000))), 1)
            # Meta may repeat the webhook: no second attachment
            self.assertEqual(account._process_history(
                self._media_payload(self._image('wamid.ph', CUSTOMER, 1760000000))), 0)

        message = self._messages(channel)
        self.assertEqual(len(message), 1)
        self.assertEqual(len(message.attachment_ids), 1)
        self.assertEqual(bytes(message.attachment_ids.raw), b'jpeg-bytes')
        self.assertIn('la foto', message.body)
        self.assertNotIn('did not include the file', message.body)

    def test_media_webhook_before_its_placeholder(self):
        account = self.whatsapp_account
        with self._patched_download():
            self.assertEqual(account._process_history(
                self._media_payload(self._image('wamid.early', CUSTOMER, 1760000000))), 1)
        # the placeholder chunk arrives later and must not replace the file
        self.assertEqual(account._process_history(
            self._payload(self._placeholder('wamid.early', CUSTOMER, 1760000000))), 0)
        message = self._messages(account._find_active_channel(CUSTOMER))
        self.assertEqual(len(message), 1)
        self.assertTrue(message.attachment_ids)
        self.assertEqual(message.wa_message_ids.message_type, 'inbound')

    def test_media_as_message_echoes_completes_outbound_placeholder(self):
        """What production sent: the business's media comes back as
        ``message_echoes`` (from = business, to = customer) on field history."""
        account = self.whatsapp_account
        account._process_history(self._payload(self._placeholder('wamid.out', BUSINESS, 1760000000)))
        echo = dict(self._image('wamid.out', BUSINESS, 1760000000), to=CUSTOMER)
        payload = {'messaging_product': 'whatsapp',
                   'metadata': {'display_phone_number': BUSINESS, 'phone_number_id': '1'},
                   'message_echoes': [echo]}
        with self._patched_download():
            self.assertEqual(account._process_history(payload), 1)
        message = self._messages(account._find_active_channel(CUSTOMER))
        self.assertEqual(len(message), 1)
        self.assertTrue(message.attachment_ids)
        self.assertEqual(message.wa_message_ids.message_type, 'outbound')

    def test_unknown_echo_media_goes_to_the_customer_in_to(self):
        account = self.whatsapp_account
        echo = dict(self._image('wamid.first', BUSINESS, 1760000000), to=CUSTOMER)
        with self._patched_download():
            self.assertEqual(account._process_history(
                {'metadata': {'display_phone_number': BUSINESS}, 'message_echoes': [echo]}), 1)
        message = self._messages(account._find_active_channel(CUSTOMER))
        self.assertEqual(len(message), 1)
        self.assertNotEqual(message.author_id, account._find_active_channel(CUSTOMER).whatsapp_partner_id)

    def test_media_webhook_of_unknown_outbound_message_is_skipped(self):
        # ``from`` is the business and nothing says which chat it belongs to
        with self._patched_download():
            self.assertEqual(self.whatsapp_account._process_history(
                self._media_payload(self._image('wamid.lost', BUSINESS, 1760000000))), 0)
        self.assertFalse(self.env['whatsapp.message'].sudo().search_count(
            [('msg_uid', '=', 'wamid.lost')]))

    # -- unread counters --
    def _internal_member(self, channel):
        partner = self.env.ref('base.user_admin').partner_id
        Member = self.env['discuss.channel.member'].sudo()
        return (Member.search([('channel_id', '=', channel.id), ('partner_id', '=', partner.id)])
                or Member.create({'channel_id': channel.id, 'partner_id': partner.id}))

    def test_history_is_not_unread(self):
        account = self.whatsapp_account
        channel = account._find_active_channel(CUSTOMER, create_if_not_found=True)
        member = self._internal_member(channel)
        account._process_history(self._payload(
            self._text('wamid.r1', CUSTOMER, 1760000000, 'uno'),
            self._text('wamid.r2', BUSINESS, 1760000001, 'dos'),
            self._text('wamid.r3', CUSTOMER, 1760000002, 'tres'),
        ))
        member.invalidate_recordset()
        self.assertEqual(member.message_unread_counter, 0)

    def test_history_keeps_unread_messages_unread(self):
        account = self.whatsapp_account
        channel = account._find_active_channel(CUSTOMER, create_if_not_found=True)
        member = self._internal_member(channel)
        # a live message the member has not read yet
        self.env['mail.message'].sudo().create({
            'model': 'discuss.channel', 'res_id': channel.id, 'message_type': 'whatsapp_message',
            'author_id': channel.whatsapp_partner_id.id, 'body': 'sin leer'})
        member.invalidate_recordset()
        unread_before = member.message_unread_counter
        self.assertTrue(unread_before)
        account._process_history(self._payload(self._text('wamid.u1', CUSTOMER, 1760000000, 'viejo')))
        member.invalidate_recordset()
        self.assertGreaterEqual(member.message_unread_counter, unread_before)

    # -- readable bodies instead of "[x from the chat history]" --
    def test_interactive_and_unsupported_are_readable(self):
        reply = {'from': CUSTOMER, 'id': 'wamid.btn', 'timestamp': '1760000000', 'type': 'interactive',
                 'interactive': {'type': 'button_reply',
                                 'button_reply': {'id': 'b1', 'title': 'Sí, confirmo'}}}
        unsupported = {'from': BUSINESS, 'id': 'wamid.err', 'timestamp': '1760000001', 'type': 'errors',
                       'errors': [{'code': 131051, 'title': 'Message type unknown'}]}
        reaction = {'from': CUSTOMER, 'id': 'wamid.rx', 'timestamp': '1760000002', 'type': 'reaction',
                    'reaction': {'message_id': 'wamid.btn', 'emoji': '👍'}}
        self.whatsapp_account._process_history(self._payload(reply, unsupported, reaction))
        btn, err, rx = self._messages(self.whatsapp_account._find_active_channel(CUSTOMER))
        self.assertIn('Sí, confirmo', btn.body)
        self.assertIn('Message type unknown', err.body)
        self.assertNotIn('from the chat history', err.body)
        self.assertIn('👍', rx.body)
