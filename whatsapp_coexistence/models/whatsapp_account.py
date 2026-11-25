import logging
import re
import secrets
import time
from datetime import datetime, timezone

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import config, consteq, plaintext2html

_logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

DEFAULT_GRAPH_VERSION = "v25.0"
DEFAULT_BROKER_URL = "https://coexistence.rcstudio.dev"

# History import: Meta sends the history in chunks, each one a single webhook
# request. Media has to be downloaded from the Graph API one file at a time, so
# a chunk full of photos could keep the HTTP worker busy past the proxy timeout
# and Meta would never get its 200. Past this budget the remaining media of the
# chunk is recorded as a placeholder instead of being downloaded.
HISTORY_MEDIA_BUDGET_SECONDS = 25
HISTORY_MEDIA_TYPES = ("image", "video", "audio", "document", "sticker")


class WhatsAppAccount(models.Model):
    _inherit = "whatsapp.account"

    connection_type = fields.Selection(
        selection=[("api", "Cloud API (dedicated)"), ("coexistence", "Coexistence")],
        string="Connection Type", default="api", required=True, tracking=True,
        help="Cloud API: the number is dedicated to the API and stops working on the phone.\n"
             "Coexistence: the number stays on the phone app while the API observes and "
             "sends alongside it (QR onboarding).")

    # In coexistence mode the QR onboarding fills these in, not the user, so
    # they stop being required at model level (the constraint below still
    # enforces them for 'api'). Without this an empty coexistence account could
    # not be saved before clicking "Connect via Coexistence".
    app_uid = fields.Char(required=False)
    app_secret = fields.Char(required=False)
    phone_uid = fields.Char(required=False)
    account_uid = fields.Char(required=False)
    token = fields.Char(required=False)

    wacoex_business_id = fields.Char("Business ID (Coexistence)", copy=False)
    wacoex_config_id = fields.Char(
        "Login Configuration ID",
        default=lambda self: self._wacoex_param("config_id"),
        help="The 'Facebook Login for Business' configuration used for this number's QR. "
             "Defaults to the global one from Settings.")
    wacoex_state_synced_at = fields.Datetime("Contacts Synced On", copy=False)
    wacoex_history_synced_at = fields.Datetime("History Synced On", copy=False)
    wacoex_connected = fields.Boolean(
        "Coexistence Connected", compute="_compute_wacoex_connected")

    # --- Meta app provider --------------------------------------------------
    # Two modes, picked automatically from whether an App Secret is set:
    #   * with an App Secret    -> the customer's own app (they answer for it)
    #   * without an App Secret -> RC Studio's app through the broker
    # RC Studio's secret is NEVER copied into the customer's database: the
    # broker keeps it and only returns the business token, which is theirs.
    wacoex_broker_url = fields.Char(
        "RC Studio Broker",
        default=lambda self: self._wacoex_param("broker_url") or DEFAULT_BROKER_URL,
        help="Service that keeps the App Secret when you use RC Studio's Meta app. "
             "Only used when the App Secret is left empty.")
    wacoex_license_key = fields.Char(
        "RC Studio License", copy=False, groups="whatsapp.group_whatsapp_admin",
        help="Key issued by RC Studio. With it, nothing else is needed: the App ID "
             "and the Login Configuration are fetched from RC Studio automatically. "
             "It grants access only to the numbers of this account; it neither "
             "replaces nor reveals the App Secret.")
    wacoex_signup_token = fields.Char(
        "Signup Session Token", copy=False, groups="whatsapp.group_whatsapp_admin",
        help="Token of the Embedded Signup session opened on the RC Studio broker. "
             "Short-lived; only needed until the connection completes.")
    wacoex_broker_mode = fields.Boolean(
        "Broker Mode", compute="_compute_wacoex_broker_mode", compute_sudo=True,
        help="True when this number connects through RC Studio's Meta app "
             "(license set, no App Secret of your own).")
    wacoex_provider_label = fields.Char(
        "App Provider", compute="_compute_wacoex_provider_label",
        help="Which Meta app will be used to connect this number.")
    wacoex_webhook_mode = fields.Selection([
        ("direct", "Straight from Meta to this Odoo"),
        ("relay", "Through the RC Studio service (older connections)"),
    ], string="Webhook Delivery", default="direct", readonly=True, copy=False,
        help="How Meta's deliveries reach this Odoo. The module always asks for direct delivery, "
             "so no message passes through RC Studio, which only takes part in the connection. "
             "Accounts connected with an older version stay on the relay until they are connected "
             "again; that is the only case where this reads otherwise.")
    wacoex_webhook_token = fields.Char(
        "Direct Webhook Token", copy=False, groups="whatsapp.group_whatsapp_admin",
        default=lambda self: secrets.token_urlsafe(32),
        help="Secret part of the direct webhook URL. It is what authenticates the deliveries "
             "Meta sends straight to this Odoo.")
    wacoex_direct_callback_url = fields.Char(
        "Direct Webhook URL", compute="_compute_wacoex_direct_callback_url",
        help="The URL registered with Meta when the delivery is direct. Its token is secret.")

    wacoex_subscribe_pending = fields.Boolean(
        "Webhook Registration Pending", copy=False,
        help="Set while the webhook registration is waiting for the scheduled action that "
             "performs it outside the web request.")
    wacoex_webhook_secret = fields.Char(
        "Webhook Secret (Broker)", copy=False,
        groups="whatsapp.group_whatsapp_admin",
        help="Meta signs webhooks with the App Secret, which is not here in broker mode. "
             "The broker validates that signature and forwards the delivery re-signed "
             "with this secret, which is yours. Issued by the broker on subscription.")

    @api.depends("connection_type", "token", "phone_uid", "account_uid")
    def _compute_wacoex_connected(self):
        for acc in self:
            acc.wacoex_connected = bool(
                acc.connection_type == "coexistence" and acc.token
                and acc.phone_uid and acc.account_uid)

    @api.depends("app_secret", "wacoex_license_key")
    def _compute_wacoex_broker_mode(self):
        for acc in self:
            acc.wacoex_broker_mode = bool(acc.wacoex_license_key and not acc.app_secret)

    @api.depends("app_secret", "wacoex_license_key")
    def _compute_wacoex_provider_label(self):
        """Make an otherwise invisible rule visible: empty secret = broker."""
        for acc in self:
            if acc.sudo().app_secret:
                acc.wacoex_provider_label = _("Your own Meta app")
            elif acc.sudo().wacoex_license_key:
                acc.wacoex_provider_label = _("RC Studio's app (broker)")
            else:
                acc.wacoex_provider_label = _("Not configured")

    @api.constrains("connection_type", "phone_uid", "account_uid", "token")
    def _check_api_credentials(self):
        for acc in self:
            if acc.connection_type == "api" and not (
                    acc.phone_uid and acc.account_uid and acc.token):
                raise ValidationError(_(
                    "A Cloud API connection requires the Phone Number ID, "
                    "the Account ID and the Access Token."))

    @api.constrains("connection_type", "app_secret", "wacoex_license_key")
    def _check_wacoex_provider(self):
        """Fail here, in plain words, instead of blowing up later on Graph."""
        for acc in self:
            if acc.connection_type != "coexistence":
                continue
            acc_sudo = acc.sudo()
            if not acc_sudo.app_secret and not acc_sudo.wacoex_license_key:
                raise ValidationError(_(
                    "Coexistence needs one of two things: the App ID and App Secret of "
                    "your own Meta app, or an RC Studio license to use ours as "
                    "the provider (the App ID is then configured automatically)."))

    # ------------------------------------------------------------------
    # CRUD: with a license, the App ID comes from RC Studio invisibly
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        accounts = super().create(vals_list)
        accounts._wacoex_autofill_from_broker()
        accounts._wacoex_adopt_orphan_threads()
        return accounts

    def _wacoex_adopt_orphan_threads(self):
        """A new account picks up the conversations an old one left behind.

        A WhatsApp thread points at its account through a foreign key declared ON
        DELETE SET NULL, so deleting an account - which is what re-onboarding a
        coexistence number usually means - leaves all of its conversations with no
        account at all. Odoo then neither finds them when the customer writes again
        (the search is by account) nor renders them, because the composer reads the
        account to build its placeholder. The history is still there, unreachable.

        Only unambiguous cases are repaired: it is done when this is the one and only
        account in the database, and a thread is never adopted when the account
        already has a live thread for that same number.
        """
        for account in self:
            if self.env["whatsapp.account"].sudo().search_count([]) != 1:
                continue
            self.env.cr.execute("""
                UPDATE discuss_channel c SET wa_account_id = %s
                 WHERE c.channel_type = 'whatsapp' AND c.active
                   AND c.wa_account_id IS NULL AND c.whatsapp_number IS NOT NULL
                   AND NOT EXISTS (SELECT 1 FROM discuss_channel k
                                    WHERE k.channel_type = 'whatsapp' AND k.active
                                      AND k.wa_account_id = %s
                                      AND k.whatsapp_number = c.whatsapp_number)
            """, (account.id, account.id))
            if self.env.cr.rowcount:
                _logger.warning("Coexistence: account %s adopted %s conversations that had "
                                "been left without an account.", account.id, self.env.cr.rowcount)
                self.env["discuss.channel"].invalidate_model(["wa_account_id"])

    def write(self, vals):
        res = super().write(vals)
        if any(k in vals for k in ("wacoex_license_key", "app_secret", "connection_type", "wacoex_broker_url")):
            self._wacoex_autofill_from_broker()
        return res

    def _wacoex_autofill_from_broker(self):
        """Fetch the App ID / Login Configuration from the broker for accounts in
        broker mode. Best effort: an unreachable broker or a wrong license only
        logs a warning, the record still saves, and the onboarding page retries."""
        for acc in self.sudo().filtered(
                lambda a: a.connection_type == "coexistence" and a.wacoex_broker_mode):
            try:
                acc._wacoex_app_config()
            except Exception as e:  # noqa: BLE001 - never block saving on the broker
                _logger.warning("Could not fetch the app configuration from the broker "
                                "for account %s: %s", acc.id, e)

    # ------------------------------------------------------------------
    # Config helpers (app-level Tech Provider)
    # ------------------------------------------------------------------
    @api.model
    def _wacoex_param(self, key, default=False):
        return self.env["ir.config_parameter"].sudo().get_param(
            "whatsapp_coex.%s" % key, default)

    @api.model
    def _wacoex_graph_version(self):
        return self._wacoex_param("graph_version") or DEFAULT_GRAPH_VERSION

    @api.model
    def _wacoex_graph_base(self):
        return "https://graph.facebook.com/%s" % self._wacoex_graph_version()

    def _wacoex_graph_request(self, method, path, token=None, params=None,
                              json=None, retries=2):
        if not requests:
            raise UserError(_("The Python package 'requests' is not installed."))
        url = "%s/%s" % (self._wacoex_graph_base(), path.lstrip("/"))
        headers = {"Authorization": "Bearer %s" % token} if token else {}
        last_err = None
        for attempt in range(retries + 1):
            try:
                resp = requests.request(method, url, headers=headers,
                                        params=params, json=json, timeout=30)
                try:
                    data = resp.json()
                except ValueError:
                    data = {"raw": resp.text}
                usage = resp.headers.get("x-app-usage")
                if usage:
                    _logger.info("Meta app usage: %s", usage)
                if resp.status_code >= 400:
                    err = (data.get("error") or {}) if isinstance(data, dict) else {}
                    msg = "Graph %s %s -> %s: %s" % (
                        method, path, resp.status_code, err.get("message") or data)
                    _logger.warning("%s [x-app-usage: %s]", msg, usage or "n/a")
                    if err.get("code") == 4:
                        # App-level limit: 200 calls/hour x active users, on a
                        # sliding window. Retrying now only extends it.
                        raise UserError(_(
                            "The Meta app quota is exhausted. Wait at least one hour "
                            "without making calls before retrying: the window is "
                            "sliding and every attempt extends it. "
                            "(current usage: %s)") % (usage or "unknown"))
                    if resp.status_code != 429 or attempt == retries:
                        raise UserError(msg)
                    last_err = msg
                    continue
                return data
            except requests.RequestException as e:
                last_err = str(e)
                if attempt == retries:
                    raise UserError(_("Network error calling Graph: %s") % last_err)
        raise UserError(_("Graph failed after retries: %s") % last_err)

    # ------------------------------------------------------------------
    # Provider: the customer's own app vs RC Studio's broker
    # ------------------------------------------------------------------
    def _wacoex_use_broker(self):
        """Without an own App Secret, RC Studio provides the app through the broker."""
        self.ensure_one()
        return not bool(self.sudo().app_secret)

    def _wacoex_broker_request(self, method, path, payload=None, params=None):
        """Call the broker. The App Secret lives there; only the license travels."""
        self.ensure_one()
        if not requests:
            raise UserError(_("The Python package 'requests' is not installed."))
        acc = self.sudo()
        base = (acc.wacoex_broker_url or DEFAULT_BROKER_URL).rstrip("/")
        if not acc.wacoex_license_key:
            raise UserError(_(
                "The RC Studio license is missing. Set it on the account, or "
                "configure the App Secret of your own Meta app."))
        url = "%s/v1/%s" % (base, path.lstrip("/"))
        headers = {"Authorization": "Bearer %s" % acc.wacoex_license_key}
        try:
            resp = requests.request(method, url, headers=headers, params=params,
                                    json=payload, timeout=60)
        except requests.RequestException as e:
            raise UserError(_("Could not reach the RC Studio broker: %s") % e)
        try:
            data = resp.json()
        except ValueError:
            data = {"error": resp.text}
        if resp.status_code >= 400:
            msg = data.get("error") or data
            _logger.warning("Broker %s %s -> %s: %s", method, path,
                            resp.status_code, msg)
            raise UserError(_("RC Studio broker: %s") % msg)
        return data

    def _wacoex_app_config(self):
        """App ID / Config ID to use in this account's Embedded Signup.

        In broker mode they are fetched from the service instead of being
        hard-coded, so the Login Configuration can rotate without a new release.
        """
        self.ensure_one()
        acc = self.sudo()
        if not self._wacoex_use_broker():
            return {"app_id": acc.app_uid or "",
                    "config_id": acc.wacoex_config_id or "",
                    "graph_version": self._wacoex_graph_version()}
        try:
            data = self._wacoex_broker_request("GET", "app-config")
        except UserError as e:
            _logger.warning("Could not read app-config from the broker: %s", e)
            return {"app_id": acc.app_uid or self._wacoex_param("app_id") or "",
                    "config_id": acc.wacoex_config_id or self._wacoex_param("config_id") or "",
                    "graph_version": self._wacoex_graph_version()}
        vals = {}
        if data.get("app_id") and data["app_id"] != acc.app_uid:
            vals["app_uid"] = data["app_id"]
        if data.get("config_id") and data["config_id"] != acc.wacoex_config_id:
            vals["wacoex_config_id"] = data["config_id"]
        if vals:
            acc.write(vals)
        return data

    # ------------------------------------------------------------------
    # Onboarding (Embedded Signup -> fills the native account)
    # ------------------------------------------------------------------
    def action_wacoex_onboard(self):
        """Button: open the Embedded Signup page for this number."""
        self.ensure_one()
        if not self.id:
            raise UserError(_("Save the record before connecting."))
        return {
            "type": "ir.actions.act_url",
            "url": "/whatsapp/coexistence/onboard?account_id=%s" % self.id,
            "target": "new",
        }

    def _wacoex_exchange_code(self, code, waba_id=None, phone_number_id=None,
                              business_id=None):
        """Exchange the code for the business token.

        The only step that needs the App Secret: with an own app the account's
        secret is used; with RC Studio's app the exchange happens on the broker
        and only the issued token arrives here.
        """
        self.ensure_one()
        if self._wacoex_use_broker():
            data = self._wacoex_broker_request("POST", "exchange", payload={
                "code": code,
                "waba_id": waba_id or self.account_uid or "",
                "phone_number_id": phone_number_id or self.phone_uid or "",
                "business_id": business_id or self.wacoex_business_id or "",
            })
            token = data.get("access_token")
            if not token:
                raise UserError(_("The broker did not return an access token: %s") % data)
            return token

        app_id = self.app_uid
        app_secret = self.sudo().app_secret
        if not app_id:
            raise UserError(_("Enter the App ID of the Meta app on this account."))
        data = self._wacoex_graph_request("GET", "oauth/access_token", params={
            "client_id": app_id, "client_secret": app_secret, "code": code})
        token = data.get("access_token")
        if not token:
            raise UserError(_("Meta did not return an access token: %s") % data)
        return token

    def wacoex_onboard(self, code, waba_id, phone_number_id, business_id=None,
                       event=None):
        """Full orchestration: exchange the code, fill the account, subscribe the
        webhook with override, read the number and trigger the syncs. Non-critical
        steps are best-effort.
        """
        self.ensure_one()
        if not (code and waba_id and phone_number_id):
            raise UserError(_("Missing code, waba_id or phone_number_id."))

        token = self._wacoex_exchange_code(
            code, waba_id=waba_id, phone_number_id=phone_number_id,
            business_id=business_id)
        return self._wacoex_finish_onboarding(waba_id, phone_number_id, token, business_id)

    # ------------------------------------------------------------------
    # Hosted Embedded Signup (broker mode): the Facebook dialog runs on a page
    # of the broker, so the customer's domain never has to be registered in
    # Meta's App Dashboard. The business token never goes through the browser:
    # the popup only reports that it finished and Odoo collects the result
    # server-to-server under the license.
    # ------------------------------------------------------------------
    def wacoex_signup_session(self, origin):
        """Open a signup session on the broker for the Odoo that will show the popup.

        :param origin: ``scheme://host[:port]`` of the current request, no path.
        :return: dict with ``url`` (page to open in a popup), ``token`` and ``expires_in``.
        """
        self.ensure_one()
        if not self._wacoex_use_broker():
            raise UserError(_("The hosted connection is only available with an RC Studio license."))
        data = self._wacoex_broker_request("POST", "signup/session", payload={"origin": origin})
        if not (data.get("url") and data.get("token")):
            raise UserError(_("The broker did not return a signup session: %s") % data)
        self.sudo().wacoex_signup_token = data["token"]
        # Ask the broker for the page in the language of whoever is connecting.
        url = data["url"]
        lang = (self.env.context.get("lang") or self.env.user.lang or "en")[:2]
        url += ("&" if "?" in url else "?") + "lang=" + lang
        return {"url": url, "token": data["token"], "expires_in": data.get("expires_in")}

    def wacoex_signup_collect(self):
        """Collect the result of the signup session and finish the onboarding.

        :return: dict with ``status`` (``pending`` | ``done``) and, while pending,
                 the broker's ``last_error`` written for the end user, if any.
        """
        self.ensure_one()
        token = self.sudo().wacoex_signup_token
        if not token:
            raise UserError(_("There is no connection session in progress. Click Connect again."))
        data = self._wacoex_broker_request("GET", "signup/session/%s" % token)
        status = data.get("status")
        if status == "expired":
            self.sudo().wacoex_signup_token = False
            raise UserError(_("The connection session expired. Click Connect again."))
        if status != "done":
            return {"status": "pending", "last_error": data.get("last_error") or ""}
        if not (data.get("access_token") and data.get("waba_id") and data.get("phone_number_id")):
            raise UserError(_("The broker returned an incomplete result: %s") % data)
        self._wacoex_finish_onboarding(
            data["waba_id"], data["phone_number_id"], data["access_token"], data.get("business_id"))
        self.sudo().wacoex_signup_token = False
        return {
            "status": "done",
            "name": self.name,
            "phone_number": self.phone_number if "phone_number" in self._fields else "",
        }

    def _wacoex_finish_onboarding(self, waba_id, phone_number_id, token, business_id=None):
        """Common tail of both onboarding flows: fill the account, subscribe the
        webhook with override, read the number and trigger the one-time syncs."""
        self.ensure_one()
        self.write({
            "connection_type": "coexistence",
            "account_uid": waba_id,
            "phone_uid": phone_number_id,
            "token": token,
            "wacoex_business_id": business_id or False,
        })

        # Registering makes Meta verify the callback URL within seconds while this request
        # still holds an HTTP worker; on a small instance that verification can queue behind
        # it and time out. The cron thread does it instead, right away.
        if not self._wacoex_queue_subscription():
            self._wacoex_subscribe_override()
            self.sudo().wacoex_subscribe_pending = False
        # register: SKIPPED in coexistence.
        try:
            self._wacoex_fetch_number_info()
        except UserError as e:
            _logger.warning("Could not read info of number %s: %s", phone_number_id, e)

        # Initial sync (24-hour window, once). NOT fatal (rate-limit #4 is common).
        sync_errors = []
        for label, method in (("state", self._wacoex_sync_state),
                              ("history", self._wacoex_sync_history)):
            try:
                method()
            except UserError as e:
                sync_errors.append("%s: %s" % (label, e))
                _logger.warning("Sync %s failed for %s: %s", label, phone_number_id, e)

        if sync_errors:
            self.message_post(body=_(
                "Coexistence is connected, but the initial sync failed. There is only "
                "a 24-hour window and one attempt per onboarding: if it cannot be "
                "fixed, unlink the number and connect it again.<br/>%s")
                % Markup("<br/>").join(sync_errors))
        else:
            self.message_post(body=_("Coexistence connected and synchronized."))
        return self

    # ------------------------------------------------------------------
    # Graph actions
    # ------------------------------------------------------------------
    @api.depends("wacoex_webhook_token")
    def _compute_wacoex_direct_callback_url(self):
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        for account in self:
            token = account.sudo().wacoex_webhook_token
            account.wacoex_direct_callback_url = (
                "%s/whatsapp/coexistence/webhook/%s/%s" % (base, account.id, token)
                if account.id and token else False)

    @api.model
    def _wacoex_find_by_webhook_token(self, account_id, token):
        """The account whose direct webhook URL carries this token, or an empty set."""
        account = self.sudo().browse(int(account_id)).exists()
        if account and account.wacoex_webhook_token and consteq(account.wacoex_webhook_token, token):
            return account
        return self.sudo().browse()

    def action_wacoex_rotate_webhook_token(self):
        """A new token, hence a new URL, registered with Meta. The old URL stops working.

        The registration goes through the scheduler: the service verifies the new URL from
        a separate request, and that request cannot see the new token while this
        transaction is still open, so registering it inline makes the handshake answer 403.
        """
        self.ensure_one()
        self.sudo().wacoex_webhook_token = secrets.token_urlsafe(32)
        self.invalidate_recordset(["wacoex_direct_callback_url"])
        self.message_post(body=_("The direct webhook token was rotated."))
        if not self.wacoex_connected:
            return True
        if self._wacoex_queue_subscription():
            self.message_post(body=_("Registering the new URL. It takes a few seconds."))
            return True
        # No scheduler here, so nothing runs after this transaction and the new token cannot
        # be announced before it is saved: the registration waits for the Re-subscribe
        # Webhook button, which runs in a request of its own.
        self.message_post(body=_(
            "Press Re-subscribe Webhook to register the new URL: this instance has no "
            "scheduler to do it on its own."))
        return True

    def _wacoex_subscribe_override(self):
        self.ensure_one()
        if self._wacoex_use_broker():
            # Always direct: none of the customer's traffic should pass through RC Studio.
            # Meta must then reach this Odoo on our own tokenized route, because the native
            # one checks a signature made with an App Secret that is not in this database.
            data = self._wacoex_broker_request("POST", "subscribe", payload={
                "waba_id": self.account_uid,
                "callback_url": self.wacoex_direct_callback_url,
                "verify_token": self.webhook_verify_token,
                "mode": "direct"})
            granted = data.get("mode") or "relay"
            self.sudo().wacoex_webhook_mode = granted
            if granted != "direct":
                # An older service, or an administrator holding this account on the relay:
                # the legacy path keeps working, deliveries arrive signed by the service.
                _logger.warning("Coexistence: asked for direct delivery on account %s, the "
                                "service registered %s; staying on the relay.", self.id, granted)
                self._wacoex_graph_request(
                    "POST", "%s/subscribed_apps" % self.account_uid, token=self.token,
                    json={"override_callback_uri": self.callback_url,
                          "verify_token": self.webhook_verify_token})
            # Deliveries relayed by the broker are validated with this secret;
            # without it the controller would reject them all with 403.
            if data.get("webhook_secret"):
                self.sudo().wacoex_webhook_secret = data["webhook_secret"]
            return True
        self._wacoex_graph_request(
            "POST", "%s/subscribed_apps" % self.account_uid, token=self.token,
            json={"override_callback_uri": self.callback_url,
                  "verify_token": self.webhook_verify_token})
        return True

    @api.model
    def _cron_wacoex_subscribe(self):
        """Register the webhook of the accounts whose onboarding left it pending."""
        # wacoex_connected is computed and not stored, so it cannot go in the domain:
        # the stored fields it is made of are searched instead and it is checked here.
        pending = self.search([
            ("wacoex_subscribe_pending", "=", True),
            ("connection_type", "=", "coexistence"),
            ("phone_uid", "!=", False),
            ("account_uid", "!=", False),
        ]).filtered("wacoex_connected")
        for account in pending:
            try:
                with self.env.cr.savepoint():
                    account._wacoex_subscribe_override()
                    account.sudo().wacoex_subscribe_pending = False
            except Exception as exc:  # noqa: BLE001 - one account must not stop the others
                _logger.warning("Could not register the webhook of account %s: %s", account.id, exc)
                account.message_post(body=_("The webhook could not be registered: %s", exc))

    def _wacoex_queue_subscription(self):
        """Ask the scheduler to register the webhook, out of the web request.

        Registering makes Meta verify the callback URL straight away and Meta gives up
        after six seconds. Doing it inside the request would hold the worker serving it
        while Meta knocks on the door, and an Odoo with a single worker would have nobody
        left to answer. Returns False when there is no scheduler (max_cron_threads = 0),
        in which case the caller registers it inline.
        """
        self.ensure_one()
        self.sudo().wacoex_subscribe_pending = True
        if not config["max_cron_threads"]:
            return False
        try:
            self.env.ref("whatsapp_coexistence.cron_wacoex_subscribe").sudo()._trigger()
        except Exception as exc:  # noqa: BLE001 - the module may be mid-upgrade
            _logger.warning("Could not queue the webhook registration: %s", exc)
            return False
        return True

    def action_wacoex_resubscribe(self):
        """Register the webhook again without redoing the Embedded Signup.

        Needed after changing the `callback_url`, when switching from an own
        app to the broker (or back) and to renew the webhook secret.
        """
        for acc in self:
            if acc._wacoex_queue_subscription():
                acc.message_post(body=_("Registering the webhook. It takes a few seconds."))
                continue
            acc._wacoex_subscribe_override()
            acc.sudo().wacoex_subscribe_pending = False
            acc.message_post(body=_("Webhook re-subscribed."))
        return True

    def action_wacoex_unsubscribe(self):
        self.ensure_one()
        self._wacoex_graph_request(
            "POST", "%s/subscribed_apps" % self.account_uid, token=self.token, json={})
        self.message_post(body=_("Webhook override removed (back to the app default)."))
        return True

    def _wacoex_fetch_number_info_raw(self):
        """Read the number on Graph (directly or via the broker) and return the raw data."""
        self.ensure_one()
        if self._wacoex_use_broker():
            data = self._wacoex_broker_request("GET", "number/%s" % self.phone_uid)
        else:
            data = self._wacoex_graph_request(
                "GET", self.phone_uid, token=self.token,
                params={"fields": "display_phone_number,verified_name,"
                                  "platform_type,is_on_biz_app,status"})
        # Early signal of error 133010: if the number was not linked to the
        # phone app, the sync will fail, so say it clearly.
        if data.get("is_on_biz_app") is False:
            _logger.warning(
                "Number %s was not linked as coexistence (platform_type=%s, "
                "status=%s): check the Embedded Signup's Login Configuration.",
                self.phone_uid, data.get("platform_type"), data.get("status"))
        return data

    def _wacoex_fetch_number_info(self):
        self.ensure_one()
        data = self._wacoex_fetch_number_info_raw()
        vals = {}
        # The display number field only exists on the account model in Odoo 19+.
        if data.get("display_phone_number") and "phone_number" in self._fields:
            vals["phone_number"] = data["display_phone_number"]
        if data.get("verified_name") and not self.name:
            vals["name"] = data["verified_name"]
        if vals:
            self.write(vals)
        return True

    def _wacoex_sync(self, sync_type):
        self.ensure_one()
        if self._wacoex_use_broker():
            # The broker enforces Meta's rule (one sync per onboarding) and the
            # cooldown, so a retry does not burn the shared quota.
            return self._wacoex_broker_request("POST", "sync", payload={
                "phone_number_id": self.phone_uid, "sync_type": sync_type})
        return self._wacoex_graph_request(
            "POST", "%s/smb_app_data" % self.phone_uid, token=self.token,
            json={"messaging_product": "whatsapp", "sync_type": sync_type})

    def action_wacoex_diagnose(self):
        """One call that tells whether the number really ended up in coexistence.

        The antidote to error 133010: when ``is_on_biz_app`` is false the
        Embedded Signup did not link the phone and no sync will work.
        """
        self.ensure_one()
        data = self._wacoex_fetch_number_info_raw()
        on_app = data.get("is_on_biz_app")
        if on_app:
            body = _("Number linked as coexistence. Status: %(status)s, "
                     "platform: %(platform)s.",
                     status=data.get("status") or "?",
                     platform=data.get("platform_type") or "?")
        else:
            body = _("This number was NOT linked to the WhatsApp Business app "
                     "(is_on_biz_app=%(on)s, platform_type=%(platform)s, "
                     "status=%(status)s). Check that the Embedded Signup uses the "
                     "coexistence Login Configuration and connect again; the syncs "
                     "will fail with \"Account not registered\".",
                     on=on_app, platform=data.get("platform_type") or "?",
                     status=data.get("status") or "?")
        body += "\n" + self._wacoex_webhook_diagnosis()
        self.message_post(body=plaintext2html(body))
        return True

    def _wacoex_webhook_diagnosis(self):
        """What Meta actually has registered for this business account, in plain words.

        Meta keeps one callback override per app and business account, so a second Odoo
        connected to the same account - a staging copy, most often - takes the deliveries
        over silently just by registering after this one. Reading the override back is the
        only way to see it: everything looks healthy from here otherwise.
        """
        self.ensure_one()
        try:
            answer = self._wacoex_graph_request(
                "GET", "%s/subscribed_apps" % self.account_uid, token=self.token) or {}
        except Exception as exc:  # noqa: BLE001 - a diagnosis never raises
            return _("Could not read the webhook subscriptions: %s", exc)
        apps = answer.get("data") or []
        if not apps:
            return _("Webhook: no app is subscribed to this WhatsApp Business Account. "
                     "Press Re-subscribe Webhook.")
        expected = (self.wacoex_direct_callback_url if self.wacoex_webhook_mode == "direct"
                    else self.callback_url)
        lines = []
        for app in apps:
            data = app.get("whatsapp_business_api_data") or {}
            line = _("Webhook: app %(name)s (%(app_id)s) subscribed",
                     name=data.get("name") or "?", app_id=data.get("id") or "?")
            override = app.get("override_callback_uri")
            if not override:
                line += _(", no callback override (Meta delivers to the app default)")
            else:
                line += _(", callback %(url)s", url=override)
                if expected and override != expected:
                    line += _(" - which is NOT this Odoo. Meta keeps one callback per business "
                              "account, so another instance registered it last and is receiving "
                              "the messages. Press Re-subscribe Webhook here to take it back")
            lines.append(line + ".")
        return "\n".join(lines)

    def _wacoex_check_sync_allowed(self, label, done_at):
        """Meta allows each sync ONCE per onboarding.

        Running it again requires offboarding the number and redoing the
        Embedded Signup, so a retry fixes nothing: it only burns app quota (error #4).
        """
        if done_at:
            raise UserError(_(
                "The %(label)s sync already ran on %(date)s. Meta allows only one "
                "per onboarding: to run it again, unlink the number and redo the "
                "Coexistence connection.",
                label=label, date=done_at))

    def action_wacoex_sync_state(self):
        for acc in self:
            acc._wacoex_check_sync_allowed(_("contacts"), acc.wacoex_state_synced_at)
            acc._wacoex_sync_state()
        return True

    def _wacoex_sync_state(self):
        self._wacoex_sync("smb_app_state_sync")
        self.wacoex_state_synced_at = fields.Datetime.now()

    def action_wacoex_sync_history(self):
        for acc in self:
            acc._wacoex_check_sync_allowed(_("history"), acc.wacoex_history_synced_at)
            acc._wacoex_sync_history()
        return True

    def _wacoex_sync_history(self):
        self._wacoex_sync("history")
        self.wacoex_history_synced_at = fields.Datetime.now()

    # ------------------------------------------------------------------
    # Phone echoes -> Discuss (smb_message_echoes / message_echoes)
    # ------------------------------------------------------------------
    def _process_message_echoes(self, value):
        """Graft the echoes (messages typed on the phone) as OUTBOUND messages
        into the customer's Discuss channel.

        Coexistence gotcha: echoes arrive in 'message_echoes' (not 'messages')
        and the counterpart is 'to' (not 'from').
        """
        self.ensure_one()
        echoes = value.get("message_echoes") or []
        if not echoes:
            return
        WaMessage = self.env["whatsapp.message"].sudo()
        # Author = business side (renders as outbound, i.e. not the customer).
        author = (self.notify_user_ids[:1].partner_id
                  or self.env.ref("base.partner_root"))
        try:
            from odoo.addons.whatsapp.tools.whatsapp_api import WhatsAppApi
            wa_api = WhatsAppApi(self)
        except Exception:  # noqa: BLE001
            wa_api = None

        contacts = {c.get("wa_id"): (c.get("profile") or {}).get("name")
                    for c in (value.get("contacts") or [])}

        for echo in echoes:
            uid = echo.get("id")
            if not uid:
                continue
            # Dedupe: skip a wamid we already know (e.g. Odoo sent it).
            if WaMessage.search_count([("msg_uid", "=", uid)]):
                continue
            customer = echo.get("to")
            if not customer:
                continue
            channel = self._find_active_channel(
                customer, sender_name=contacts.get(customer), create_if_not_found=True)
            kwargs = {
                "message_type": "whatsapp_message",
                "author_id": author.id,
                "subtype_xmlid": "mail.mt_comment",
                "whatsapp_inbound_msg_uid": uid,  # creates whatsapp.message and does NOT resend
            }
            mtype = echo.get("type") or "text"
            if mtype == "text":
                kwargs["body"] = plaintext2html((echo.get("text") or {}).get("body") or "")
            elif mtype in ("image", "video", "audio", "document", "sticker") and wa_api:
                media = echo.get(mtype) or {}
                caption = media.get("caption")
                try:
                    datas = wa_api._get_whatsapp_document(media["id"])
                    filename = media.get("filename") or mtype
                    kwargs["attachments"] = [(filename, datas, {"voice": media.get("voice")})]
                    if caption:
                        kwargs["body"] = plaintext2html(caption)
                except Exception:  # noqa: BLE001
                    kwargs["body"] = _("[%s sent from the phone]") % mtype
            else:
                kwargs["body"] = _("[%s sent from the phone]") % mtype
            channel.message_post(**kwargs)

    # ------------------------------------------------------------------
    # History -> Discuss (field "history", coexistence onboarding)
    # ------------------------------------------------------------------
    def _process_history(self, value):
        """Import the chat history Meta sends after a coexistence onboarding.

        Meta delivers it once per onboarding, in chunks, on the ``history``
        field, with two payload shapes:

        * ``value.history[].threads[]``: one thread per customer (``id`` is the
          customer's wa_id) with its messages. A message whose ``from`` is the
          customer is inbound; anything else was sent by the business. Media
          comes here as ``media_placeholder``, without the file.
        * ``value.messages[]``: a later webhook, same field, that carries the
          media of a ``media_placeholder`` sent within the last ~2 weeks, with
          the SAME wamid. It completes the message already imported (or, if it
          arrives first, imports it), so deduplicating by wamid alone would
          throw the file away.

        Each message is written straight into the customer's Discuss channel
        with its original date, and NOT through ``message_post``. Posting would
        treat months-old messages as new: a notification to the team for each
        one, and an inbound one would reopen the 24-hour window that Meta
        actually measures from the real date, so Odoo would offer free-form
        replies that Meta then rejects. For the same reason the imported
        messages are marked as read for members who were up to date.

        Known limitation: Discuss orders a channel by message id, not by date.
        History imported into a channel that already has messages shows after
        them, and Meta does not deliver the chunks in order, so a chunk with
        recent messages may land before an older one. Each message keeps its
        real date.
        """
        self.ensure_one()
        for error in value.get("errors") or []:
            _logger.warning("Coexistence history on account %s: Meta reported %s",
                            self.id, error)
        try:
            from odoo.addons.whatsapp.tools.whatsapp_api import WhatsAppApi
            wa_api = WhatsAppApi(self)
        except Exception:  # noqa: BLE001
            wa_api = None
        deadline = time.monotonic() + HISTORY_MEDIA_BUDGET_SECONDS
        imported = 0
        for packet in value.get("history") or []:
            meta = packet.get("metadata") or {}
            _logger.info("Coexistence history on account %s: phase %s, chunk %s, progress %s%%",
                         self.id, meta.get("phase"), meta.get("chunk_order"), meta.get("progress"))
            for error in packet.get("errors") or []:
                _logger.warning("Coexistence history on account %s: Meta reported %s",
                                self.id, error)
            for thread in packet.get("threads") or []:
                customer = re.sub(r"\D", "", str(thread.get("id") or ""))
                messages = [m for m in (thread.get("messages") or []) if m.get("id")]
                if not customer or not messages:
                    continue
                channel = self._find_active_channel(customer, create_if_not_found=True)
                if not channel:
                    continue
                last_before = self._wacoex_channel_last_message_id(channel)
                for raw in sorted(messages, key=self._wacoex_history_order):
                    try:
                        with self.env.cr.savepoint():
                            if self._wacoex_import_history_message(
                                    channel, customer, raw, wa_api, deadline):
                                imported += 1
                    except Exception:  # noqa: BLE001 - one bad message must not lose the rest
                        _logger.exception("Coexistence history: message %s could not be imported",
                                          raw.get("id"))
                self._wacoex_history_mark_read(channel, last_before)
        # The media of the history comes back on this same field as
        # ``messages`` (inbound, per Meta's docs) or, for what the business sent,
        # as ``message_echoes`` with ``to`` = the customer (seen in production).
        media = [m for m in (value.get("messages") or []) + (value.get("message_echoes") or [])
                 if m.get("id")]
        if not value.get("history") and not media:
            # Nothing to import: say what Meta sent, the payload is not kept anywhere
            _logger.info("Coexistence history on account %s: webhook without history "
                         "nor messages, keys %s", self.id, sorted(value))
        if media:
            _logger.info("Coexistence history on account %s: media webhook with %s messages",
                         self.id, len(media))
            business = re.sub(r"\D", "", str(
                (value.get("metadata") or {}).get("display_phone_number") or ""))
            for raw in sorted(media, key=self._wacoex_history_order):
                try:
                    with self.env.cr.savepoint():
                        if self._wacoex_history_media(raw, business, wa_api, deadline):
                            imported += 1
                except Exception:  # noqa: BLE001
                    _logger.exception("Coexistence history: media of message %s could not be imported",
                                      raw.get("id"))
        _logger.info("Coexistence history: %s messages imported on account %s", imported, self.id)
        return imported

    def _wacoex_history_media(self, raw, business, wa_api, deadline):
        """Media webhook of the history (``messages`` or ``message_echoes``):
        complete the placeholder with the file.

        True if a message was completed or imported.
        """
        WaMessage = self.env["whatsapp.message"].sudo()
        existing = WaMessage.search([("msg_uid", "=", raw["id"])], limit=1)
        if existing:
            message = existing.mail_message_id
            if (not message or message.attachment_ids
                    or message.model != "discuss.channel"):
                return False  # already complete (or not a channel message)
            channel = self.env["discuss.channel"].sudo().browse(message.res_id)
            body, attachments = self._wacoex_history_content(channel, raw, wa_api, deadline)
            if not attachments:
                return False  # the download failed: keep the placeholder
            message.write({
                "body": body,
                "attachment_ids": [(4, att.id) for att in attachments],
            })
            return True
        # The media arrived before its placeholder chunk. Only an inbound one can
        # be placed: for an outbound one ``from`` is the business and the payload
        # does not say which customer it went to.
        sender = re.sub(r"\D", "", str(raw.get("from") or ""))
        customer = re.sub(r"\D", "", str(raw.get("to") or "")) or sender
        if not customer or not business or customer == business:
            _logger.info("Coexistence history: media of message %s skipped, unknown chat",
                         raw.get("id"))
            return False
        channel = self._find_active_channel(customer, create_if_not_found=True)
        if not channel:
            return False
        last_before = self._wacoex_channel_last_message_id(channel)
        done = self._wacoex_import_history_message(channel, customer, raw, wa_api, deadline)
        self._wacoex_history_mark_read(channel, last_before)
        return done

    def _wacoex_import_history_message(self, channel, customer, raw, wa_api, deadline):
        """Write one history message into ``channel``. False if already there."""
        WaMessage = self.env["whatsapp.message"].sudo()
        uid = raw["id"]
        if WaMessage.search_count([("msg_uid", "=", uid)]):
            return False  # already imported, or it arrived live as a message/echo
        inbound = re.sub(r"\D", "", str(raw.get("from") or "")) == customer
        if inbound:
            author = channel.whatsapp_partner_id
        else:
            author = (self.notify_user_ids[:1].partner_id
                      or self.env.ref("base.partner_root"))
        body, attachments = self._wacoex_history_content(channel, raw, wa_api, deadline)
        message = self.env["mail.message"].sudo().create({
            "model": "discuss.channel",
            "res_id": channel.id,
            "message_type": "whatsapp_message",
            "subtype_id": self.env.ref("mail.mt_comment").id,
            "author_id": author.id,
            "body": body,
            "date": self._wacoex_history_date(raw.get("timestamp")),
            "attachment_ids": [(6, 0, attachments.ids)],
        })
        # create_date is the ORM's "now"; backdate it to when the message was
        # sent. Odoo 17 measures the 24-hour window from the create_date of the
        # customer's last message, so a months-old one must not look fresh.
        self.env.cr.execute("UPDATE mail_message SET create_date = %s WHERE id = %s",
                            (message.date, message.id))
        message.invalidate_recordset(["create_date"])
        WaMessage.create({
            "mail_message_id": message.id,
            "message_type": "inbound" if inbound else "outbound",
            "mobile_number": "+%s" % (channel.whatsapp_number or customer),
            "msg_uid": uid,
            "state": "received" if inbound else "sent",
            "wa_account_id": self.id,
        })
        return True

    def _wacoex_channel_last_message_id(self, channel):
        last = self.env["mail.message"].sudo().search(
            [("model", "=", "discuss.channel"), ("res_id", "=", channel.id)],
            order="id desc", limit=1)
        return last.id

    def _wacoex_history_mark_read(self, channel, last_before):
        """Imported history must not show as hundreds of unread messages.

        A member who had read everything before the import (or a channel that
        was empty) is moved past the imported messages. A member who still had
        unread messages keeps them: the read marker is a single message id, so
        it cannot skip the history without also hiding what they had not read.
        Odoo 17 counts unread from ``seen_message_id``; 18+ from
        ``new_message_separator``.
        """
        last = self._wacoex_channel_last_message_id(channel)
        if not last or last == last_before:
            return
        Member = self.env["discuss.channel.member"].sudo()
        has_separator = "new_message_separator" in Member._fields
        members = Member.search([("channel_id", "=", channel.id)])
        for member in members:
            if not last_before:
                up_to_date = True
            elif has_separator:
                up_to_date = member.new_message_separator > last_before
            else:
                up_to_date = (member.seen_message_id.id or 0) >= last_before
            if not up_to_date:
                continue
            vals = {"seen_message_id": last}
            if has_separator:
                vals["new_message_separator"] = last + 1
            if "fetched_message_id" in Member._fields:
                vals["fetched_message_id"] = last
            member.write(vals)

    def _wacoex_history_content(self, channel, raw, wa_api, deadline):
        """Body (html) and attachments of a history message."""
        Attachment = self.env["ir.attachment"].sudo()
        mtype = raw.get("type") or "text"
        if mtype == "text":
            return plaintext2html((raw.get("text") or {}).get("body") or ""), Attachment
        if mtype in HISTORY_MEDIA_TYPES:
            media = raw.get(mtype) or {}
            caption = media.get("caption")
            body = plaintext2html(caption) if caption else ""
            if wa_api and media.get("id") and time.monotonic() < deadline:
                try:
                    datas = wa_api._get_whatsapp_document(media["id"])
                    attachment = Attachment.create({
                        "name": media.get("filename") or mtype,
                        "raw": datas,
                        "mimetype": (media.get("mime_type") or "").split(";")[0] or False,
                        "res_model": "discuss.channel",
                        "res_id": channel.id,
                    })
                    return body, attachment
                except Exception:  # noqa: BLE001 - expired or unavailable media
                    _logger.info("Coexistence history: media %s not available", media.get("id"))
            placeholder = plaintext2html(_("[%s from the chat history]") % mtype)
            return (body + placeholder) if body else placeholder, Attachment
        if mtype == "media_placeholder":
            # Recent media is completed later by the media webhook; older media
            # is never sent by Meta.
            return plaintext2html(_("[Attachment: WhatsApp did not include the file "
                                    "in the chat history]")), Attachment
        if mtype == "location":
            loc = raw.get("location") or {}
            text = " ".join(str(p) for p in (loc.get("name"), loc.get("address")) if p)
            text = text or "%s, %s" % (loc.get("latitude"), loc.get("longitude"))
            return plaintext2html("📍 %s" % text), Attachment
        if mtype == "contacts":
            names = [((c.get("name") or {}).get("formatted_name") or "")
                     for c in raw.get("contacts") or []]
            return plaintext2html(", ".join(n for n in names if n) or _("[contact card]")), Attachment
        if mtype == "interactive":
            interactive = raw.get("interactive") or {}
            text = self._wacoex_history_interactive_text(interactive)
            if text:
                return plaintext2html(text), Attachment
            _logger.info("Coexistence history: interactive message %s of unknown shape, keys %s",
                         raw.get("id"), sorted(interactive))
        if mtype == "button":
            text = (raw.get("button") or {}).get("text")
            if text:
                return plaintext2html(text), Attachment
        if mtype == "reaction":
            emoji = (raw.get("reaction") or {}).get("emoji")
            if emoji:
                return plaintext2html(_("Reacted %s") % emoji), Attachment
        if mtype in ("errors", "unsupported"):
            titles = [e.get("title") or e.get("message") for e in raw.get("errors") or []]
            titles = [t for t in titles if t]
            if titles:
                return plaintext2html(_("[Message not supported by WhatsApp: %s]")
                                      % "; ".join(titles)), Attachment
            return plaintext2html(_("[Message not supported by WhatsApp]")), Attachment
        return plaintext2html(_("[%s from the chat history]") % mtype), Attachment

    @staticmethod
    def _wacoex_history_interactive_text(interactive):
        """Readable text of an interactive message: the option the customer
        tapped, or the body of the buttons/list the business sent."""
        for key in ("button_reply", "list_reply"):
            reply = interactive.get(key)
            if reply and reply.get("title"):
                return " - ".join(p for p in (reply["title"], reply.get("description")) if p)
        nfm = interactive.get("nfm_reply") or {}
        if nfm.get("body"):
            return nfm["body"]
        body = interactive.get("body")
        if isinstance(body, dict):
            return body.get("text")
        return body if isinstance(body, str) else None

    @staticmethod
    def _wacoex_history_order(raw):
        """Sort key: oldest first, a malformed timestamp last instead of crashing."""
        try:
            return int(raw.get("timestamp"))
        except (TypeError, ValueError):
            return float("inf")

    @staticmethod
    def _wacoex_history_date(value):
        try:
            return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None)
        except (TypeError, ValueError, OverflowError):
            return fields.Datetime.now()
