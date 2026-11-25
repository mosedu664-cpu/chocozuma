{
    'name': 'WhatsApp Coexistence',
    'version': '18.0.3.6.2',
    'category': 'Marketing/WhatsApp',
    'summary': 'Connect WhatsApp to Odoo without losing your phone connection: '
               'official Embedded Signup, no bans, no second app.',
    'description': """
WhatsApp Coexistence — extension of the ``whatsapp`` module
===========================================================

Adds a **connection type** to ``whatsapp.account``: the dedicated Cloud API,
or **Coexistence**. In Coexistence mode the number keeps working on the phone
while the Cloud API observes and sends alongside it.

* A **"Connect via Coexistence"** button on the account opens Meta's Embedded
  Signup (QR code), reusing the same Meta app (Tech Provider model) — no
  second application needed.
* Exchanges the ``code`` for a System User token and fills the native account
  (app id, WABA id, phone number id, number).
* Subscribes the WABA to webhooks with ``override_callback_uri`` so Meta
  delivers this number's events to this Odoo: with an RC Studio licence to a
  route of its own, guarded by a token in the URL, and otherwise to Odoo's
  native endpoint with the callback URL and verify token the account already
  generates — nothing to type.
* Initial coexistence sync (contacts + history, 24-hour window) with retry
  buttons.
* **Phone echoes** (``smb_message_echoes``) are grafted into the customer's
  Discuss channel as outbound messages; inbound messages go through the native
  webhook.

Two ways to use it
------------------

**1. With your own Meta app.** Enter your App ID, App Secret and Login
Configuration on the account and the module talks to Graph directly. You are
responsible for business verification, App Review and your app's quota.

**2. With RC Studio's app.** Leave the App Secret **empty** and paste the
license we issue. The module detects the mode and routes the onboarding
through our service, which keeps the secret: it is never copied into your
database. The resulting business token does live in your Odoo, so sending
messages goes straight to Meta and does not depend on our service.

Sending is direct in both modes.

Data handling with RC Studio's app (mode 2)
--------------------------------------------

**Messages do not transit RC Studio.** The service takes part only while the
number is being connected: it runs the QR onboarding with its app secret (never
copied into your database), exchanges the ``code`` for your business token,
registers the webhook and triggers the initial sync. It then asks Meta to
deliver the events of your number **straight to this Odoo**, at a callback URL
unique to the account. Meta signs with RC Studio's app secret, which is not in
your database and so cannot be verified here; what authenticates the call is a
random token inside that URL, deliveries addressed to another business account
or another number are dropped, and the token can be rotated from the account
form at any time. Sending is direct as well, with your business token stored in
your own database. RC Studio keeps, encrypted, the business token issued for
your number in order to register the webhook again when your Odoo URL changes
and to trigger the initial sync; it is deleted when the number is offboarded.
Accounts connected with earlier versions of this module keep being relayed
through the service until **Re-subscribe Webhook** is pressed. With your own
Meta app (mode 1) nothing transits RC Studio at all. Privacy policy:
https://rcstudio.dev/privacy

Mode 1 requires a Meta app of type **Tech Provider** (Cloud API with
coexistence permissions). If you do not have one, **RC Studio provides it for
an additional fee**. Pricing and contact on WhatsApp: **+57 317 365 5128**.
""",
    'author': 'RC Studio',
    'website': 'https://rcstudio.dev',
    'support': 'https://wa.me/573173655128',
    'depends': [
        'whatsapp',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
    'data': [
        'data/cron.xml',
        'views/whatsapp_account_views.xml',
    ],
    'images': [
        # the store uses the FIRST image as the cover of the listing card, and serves it
        # untouched: the animated GIF has to come before the still.
        'static/description/banner.gif',
        'static/description/banner.png',
        'static/description/cover.png',
        'static/description/discuss.png',
        'static/description/own-provider.png',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 49.00,
    'currency': 'USD',
    'license': 'OPL-1',
}
