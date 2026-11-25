import hashlib
import hmac
import json
import logging

from werkzeug.exceptions import Forbidden

from odoo import http, _
from odoo.exceptions import AccessError, UserError
from odoo.http import request
from odoo.tools import consteq
from odoo.addons.whatsapp.controller.main import Webhook

_logger = logging.getLogger(__name__)


class WhatsAppCoexWebhook(Webhook):
    """Extend the native webhook to process coexistence echoes.

    The native controller only handles ``field == 'messages'`` (inbound +
    statuses) and ignores ``smb_message_echoes``. We call the native code
    (which already resolves inbound for coexistence accounts, matched by
    account_uid + phone_uid) and then process the echoes it let through.
    """

    def _check_signature(self, business_account):
        """In broker mode the signature comes from the broker, not from Meta.

        The native code validates with ``app_secret``; when it is empty it
        returns False and the webhook is rejected with 403, which is exactly
        what would happen with RC Studio's app, whose secret does not live
        here. When a webhook secret is set, the same HMAC-SHA256 is checked
        against it instead.

        Gotcha with several numbers on one WABA: Meta sends the business
        account (not the number) in ``entry[].id``, and the native code
        searches by ``account_uid`` without ``limit``. With two numbers on the
        same WABA that returns a multi-record set and the native code crashes
        with ``Expected singleton`` while reading ``app_secret``, before even
        comparing the signature, and still answers 200, so Meta does not retry
        and the messages are silently lost. The signature belongs to the Meta
        app, not to the number, so validating against any account of the WABA
        is enough.
        """
        if len(business_account) > 1:
            return any(self._check_signature(acc) for acc in business_account)
        account = business_account
        if account and not account.sudo().app_secret:
            secret = account.sudo().wacoex_webhook_secret
            if secret:
                signature = request.httprequest.headers.get("X-Hub-Signature-256")
                if not signature or not signature.startswith("sha256="):
                    _logger.warning("Missing or malformed signature: %r", signature)
                    return False
                expected = hmac.new(
                    secret.encode(), msg=request.httprequest.data,
                    digestmod=hashlib.sha256).hexdigest()
                return consteq(signature[7:], expected)
        return super()._check_signature(business_account)

    @http.route("/whatsapp/webhook/", methods=["POST"], type="json", auth="public")
    def webhookpost(self):
        res = super().webhookpost()
        try:
            data = json.loads(request.httprequest.data)
        except ValueError:
            return res
        WaAccount = request.env["whatsapp.account"].sudo()
        for entry in data.get("entry", []):
            account_id = entry.get("id")
            accounts = WaAccount.search([("account_uid", "=", account_id)])
            if not accounts:
                continue
            if not self._check_signature(accounts):
                raise Forbidden()
            for changes in entry.get("changes", []):
                field = changes.get("field")
                if field not in ("smb_message_echoes", "history"):
                    continue
                value = changes.get("value") or {}
                # A WABA may hold several numbers: the echo belongs to the number
                # in the metadata, not to whichever the search returns first.
                phone_uid = (value.get("metadata") or {}).get("phone_number_id")
                account = accounts.filtered(
                    lambda a: a.phone_uid == phone_uid) if phone_uid else accounts
                if not account:
                    _logger.warning(
                        "Coexistence echo from a number that is not configured: %s", phone_uid)
                    continue
                try:
                    if field == "history":
                        account[:1]._process_history(value)
                    else:
                        account[:1]._process_message_echoes(value)
                except Exception:  # noqa: BLE001
                    _logger.exception("Error while processing coexistence %s", field)
        return res


class WhatsAppCoexDirectWebhook(http.Controller):
    """Meta straight to this Odoo, without the RC Studio relay in the middle.

    Meta signs every delivery with the App Secret of the Tech Provider app, which in
    licence mode belongs to RC Studio and never reaches this database: the signature
    cannot be checked here, and the native controller would reject the delivery. What
    authenticates a request on this route is the secret token in its URL, and the
    payload is then matched against the account that owns that URL: anything naming
    another business account or another number is dropped.

    Answers are always 200 once the token is right, even for a payload we drop: a 4xx
    would only make Meta retry for hours something that can never match.
    """

    _route = "/whatsapp/coexistence/webhook/<int:account_id>/<string:token>"

    @http.route(_route, type="http", auth="public", methods=["GET"], csrf=False)
    def verify(self, account_id, token, **kw):
        """Meta's (and the service's) handshake: echo hub.challenge in plain text."""
        account = request.env["whatsapp.account"]._wacoex_find_by_webhook_token(account_id, token)
        if not account or kw.get("hub.mode") != "subscribe":
            return request.make_response("Forbidden", status=403)
        expected = account.sudo().webhook_verify_token or ""
        if not expected or not consteq(kw.get("hub.verify_token") or "", expected):
            return request.make_response("Forbidden", status=403)
        return request.make_response(kw.get("hub.challenge") or "",
                                     headers=[("Content-Type", "text/plain")])

    @http.route(_route, type="http", auth="public", methods=["POST"], csrf=False)
    def deliver(self, account_id, token, **kw):
        account = request.env["whatsapp.account"]._wacoex_find_by_webhook_token(account_id, token)
        if not account:
            return request.make_response("Forbidden", status=403)
        try:
            payload = json.loads(request.httprequest.get_data() or b"{}")
        except ValueError:
            return request.make_response("Bad Request", status=400)
        if payload.get("object") not in ("whatsapp_business_account", None):
            return request.make_response("OK")
        # Several numbers can share one business account, and Meta delivers them all here
        siblings = request.env["whatsapp.account"].sudo().search(
            [("account_uid", "=", account.sudo().account_uid)])
        for entry in payload.get("entry") or []:
            if str(entry.get("id") or "") != (account.sudo().account_uid or ""):
                _logger.warning("Coexistence direct webhook: entry for business account %s is not "
                                "this account's; dropped.", entry.get("id"))
                continue
            for change in entry.get("changes") or []:
                self._process_change(siblings, change)
        return request.make_response("OK")

    def _process_change(self, siblings, change):
        """One change, handed to the account of the number it belongs to."""
        value = change.get("value")
        if not isinstance(value, dict):
            return
        phone_uid = (value.get("metadata") or {}).get("phone_number_id")
        target = siblings.filtered(lambda a: a.phone_uid == phone_uid) if phone_uid else siblings
        if not target:
            _logger.warning("Coexistence direct webhook: event for number %s, which is not "
                            "configured here; dropped.", phone_uid)
            return
        field = change.get("field")
        try:
            if field == "messages":
                target[:1]._process_messages(value)
            elif field == "smb_message_echoes":
                target[:1]._process_message_echoes(value)
            elif field == "history":
                target[:1]._process_history(value)
            else:
                _logger.info("Coexistence direct webhook: ignoring field %r", field)
        except Exception:  # noqa: BLE001 - one bad event must not lose the others
            _logger.exception("Coexistence direct webhook: %s failed on account %s",
                              field, target[:1].id)


class WhatsAppCoexOnboarding(http.Controller):

    @http.route("/whatsapp/coexistence/onboard", type="http", auth="user",
                methods=["GET"])
    def onboard_page(self, account_id=None, **kw):
        if not request.env.user.has_group("whatsapp.group_whatsapp_admin"):
            return request.make_response("forbidden", status=403)
        account = None
        if account_id:
            account = request.env["whatsapp.account"].browse(int(account_id))
        if not (account and account.exists()):
            return request.make_response("account not found", status=404)
        if account.sudo()._wacoex_use_broker():
            return self._hosted_signup_page(account)
        # Own Meta app: classic flow, the SDK runs on this domain (which must be
        # registered in the customer's own App Dashboard).
        app_config = account.sudo()._wacoex_app_config()
        if not (app_config.get("app_id") and app_config.get("config_id")):
            return request.make_response(
                "The App ID and the Login Configuration are missing. Check the "
                "account's own App Secret or its RC Studio license.",
                status=400)
        html = ONBOARD_HTML.format(
            app_id=json.dumps(app_config.get("app_id") or ""),
            config_id=json.dumps(app_config.get("config_id") or ""),
            graph_version=json.dumps(
                app_config.get("graph_version")
                or request.env["whatsapp.account"]._wacoex_graph_version()),
            account_id=json.dumps(account_id or ""),
            lang=request.env.lang.split("_")[0] if request.env.lang else "en",
            t_title=_("Connect WhatsApp via Coexistence"),
            t_step_button=_("Click %(button)s.", button="<b>Connect via Coexistence</b>"),
            t_step_dialog=_("In Meta's dialog choose %(option)s and scan the %(qr)s with your app (NOT \"new number\").",
                            option="<b>\"add an existing WhatsApp Business account\"</b>", qr="<b>QR code</b>"),
            t_step_age=_("The number must have been active on WhatsApp Business for %(days)s.", days="<b>7 days or more</b>"),
            t_loading=_("Loading SDK…"),
            t_connect=json.dumps(_("Connect via Coexistence")),
            t_cancelled=json.dumps(_("Cancelled.")),
            t_processing=json.dumps(_("Completing the onboarding in Odoo…")),
            t_connected=json.dumps(_("Connected:")),
            t_close=json.dumps(_("You can close this window.")),
            t_error=json.dumps(_("Error:")),
            t_unknown=json.dumps(_("unknown")),
            t_network=json.dumps(_("Network error:")),
            t_opening=json.dumps(_("Opening Meta's dialog…")),
        )
        return request.make_response(html, [("Content-Type", "text/html; charset=utf-8")])

    def _hosted_signup_page(self, account):
        """Broker mode: the Facebook dialog runs on the broker's page, in a popup."""
        broker = (account.sudo().wacoex_broker_url or "").rstrip("/")
        html = HOSTED_HTML.format(
            account_id=json.dumps(str(account.id)),
            broker_origin=json.dumps(broker),
            lang=request.env.lang.split("_")[0] if request.env.lang else "en",
            t_title=_("Connect WhatsApp via Coexistence"),
            t_step_button=_("Click %(button)s: a secure window from RC Studio opens.",
                            button="<b>Connect via Coexistence</b>"),
            t_step_dialog=_("In Meta's dialog choose %(option)s and scan the %(qr)s with your app (NOT \"new number\").",
                            option="<b>\"add an existing WhatsApp Business account\"</b>", qr="<b>QR code</b>"),
            t_step_age=_("The number must have been active on WhatsApp Business for %(days)s.", days="<b>7 days or more</b>"),
            t_connect=_("Connect via Coexistence"),
            t_opening=json.dumps(_("Opening the secure connection window…")),
            t_blocked=json.dumps(_("Your browser blocked the window. Open it with this link:")),
            t_waiting=json.dumps(_("Complete the connection in the window that just opened…")),
            t_processing=json.dumps(_("Finishing the onboarding in Odoo…")),
            t_pending=json.dumps(_("The connection is not finished yet. Complete it in the window and try again.")),
            t_connected=json.dumps(_("Connected:")),
            t_close=json.dumps(_("You can close this window.")),
            t_error=json.dumps(_("Error:")),
            t_unknown=json.dumps(_("unknown")),
            t_retry=json.dumps(_("Check the result again")),
        )
        return request.make_response(html, [("Content-Type", "text/html; charset=utf-8")])

    def _signup_account(self, account_id):
        if not request.env.user.has_group("whatsapp.group_whatsapp_admin"):
            raise AccessError(_("Only WhatsApp administrators can connect a number."))
        account = request.env["whatsapp.account"].browse(int(account_id or 0)).exists()
        if not account:
            raise UserError(_("Account not found."))
        return account.sudo()

    @http.route("/whatsapp/coexistence/signup/session", type="json", auth="user", methods=["POST"])
    def coexistence_signup_session(self, account_id=None, **kw):
        """Step 1: open the signup session on the broker for this Odoo's origin."""
        account = self._signup_account(account_id)
        # The popup only talks to the origin declared here: use the real one of
        # this request, not a stored value.
        origin = request.httprequest.host_url.rstrip("/")
        return account.wacoex_signup_session(origin)

    @http.route("/whatsapp/coexistence/signup/collect", type="json", auth="user", methods=["POST"])
    def coexistence_signup_collect(self, account_id=None, **kw):
        """Step 4: collect the result server-to-server and finish the onboarding."""
        account = self._signup_account(account_id)
        return account.wacoex_signup_collect()

    @http.route("/whatsapp/coexistence/exchange", type="http", auth="user",
                methods=["POST"], csrf=False)
    def coexistence_exchange(self, **kw):
        raw = request.httprequest.get_data() or b"{}"
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            return self._json({"ok": False, "error": "bad json"}, status=400)
        if not request.env.user.has_group("whatsapp.group_whatsapp_admin"):
            return self._json({"ok": False, "error": "forbidden"}, status=403)
        account_id = data.get("account_id")
        if not account_id:
            return self._json({"ok": False, "error": "missing account_id"}, status=400)
        account = request.env["whatsapp.account"].sudo().browse(int(account_id))
        if not account.exists():
            return self._json({"ok": False, "error": "account not found"}, status=404)
        try:
            account.wacoex_onboard(
                code=data.get("code"),
                waba_id=data.get("waba_id"),
                phone_number_id=data.get("phone_number_id"),
                business_id=data.get("business_id"),
                event=data.get("event"),
            )
        except Exception as e:  # noqa: BLE001
            _logger.exception("Coexistence onboarding failed")
            return self._json({"ok": False, "error": str(e)}, status=500)
        return self._json({
            "ok": True,
            "account_id": account.id,
            "phone_number": account.phone_number if "phone_number" in account._fields else "",
            "name": account.name,
        })

    def _json(self, payload, status=200):
        return request.make_response(
            json.dumps(payload), status=status,
            headers=[("Content-Type", "application/json")])


ONBOARD_HTML = """<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{t_title}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 640px; margin: 40px auto; padding: 0 16px; color: #222; }}
    h1 {{ font-size: 1.4rem; }}
    button {{ background:#25D366; color:#fff; border:0; padding:12px 20px; font-size:1rem; border-radius:8px; cursor:pointer; }}
    button:disabled {{ opacity:.5; cursor:not-allowed; }}
    #status {{ margin-top:20px; padding:12px; border-radius:8px; background:#f5f5f5; white-space:pre-wrap; }}
    ol {{ line-height:1.6; }}
  </style>
</head>
<body>
  <div id="fb-root"></div>
  <h1>{t_title}</h1>
  <ol>
    <li>{t_step_button}</li>
    <li>{t_step_dialog}</li>
    <li>{t_step_age}</li>
  </ol>
  <button id="btn" disabled>{t_loading}</button>
  <div id="status"></div>

  <script>
    var APP_ID = {app_id};
    var CONFIG_ID = {config_id};
    var GRAPH_VERSION = {graph_version};
    var ACCOUNT_ID = {account_id};
    var T = {{
      connect: {t_connect}, cancelled: {t_cancelled}, processing: {t_processing},
      connected: {t_connected}, close: {t_close}, error: {t_error},
      unknown: {t_unknown}, network: {t_network}, opening: {t_opening}
    }};
    var sessionData = {{}};

    function setStatus(msg) {{ document.getElementById("status").textContent = msg; }}

    window.addEventListener("message", function (event) {{
      if (!event.origin.endsWith("facebook.com")) return;
      try {{
        var data = JSON.parse(event.data);
        if (data.type !== "WA_EMBEDDED_SIGNUP") return;
        sessionData = data;
      }} catch (e) {{ /* not JSON, ignore */ }}
    }});

    window.fbAsyncInit = function () {{
      FB.init({{ appId: APP_ID, autoLogAppEvents: true, xfbml: false, version: GRAPH_VERSION }});
      var btn = document.getElementById("btn");
      btn.disabled = false;
      btn.textContent = T.connect;
    }};

    (function (d, s, id) {{
      var js, fjs = d.getElementsByTagName(s)[0];
      if (d.getElementById(id)) return;
      js = d.createElement(s); js.id = id;
      js.src = "https://connect.facebook.net/en_US/sdk.js";
      js.async = true; js.defer = true; js.crossOrigin = "anonymous";
      fjs.parentNode.insertBefore(js, fjs);
    }})(document, "script", "facebook-jssdk");

    function onFbResponse(response) {{
      if (!response.authResponse) {{ setStatus(T.cancelled); return; }}
      var code = response.authResponse.code;
      var d = (sessionData && sessionData.data) || {{}};
      setStatus(T.processing);
      fetch("/whatsapp/coexistence/exchange", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{
          account_id: ACCOUNT_ID,
          code: code,
          waba_id: d.waba_id,
          phone_number_id: d.phone_number_id,
          business_id: d.business_id,
          event: sessionData && sessionData.event
        }})
      }})
      .then(function (r) {{ return r.json(); }})
      .then(function (j) {{
        if (j.ok) setStatus("✅ " + T.connected + " " + (j.name || "") + " " + (j.phone_number || "") + ". " + T.close);
        else setStatus("❌ " + T.error + " " + (j.error || T.unknown));
      }})
      .catch(function (e) {{ setStatus("❌ " + T.network + " " + e); }});
    }}

    document.getElementById("btn").addEventListener("click", function () {{
      setStatus(T.opening);
      FB.login(function (response) {{ onFbResponse(response); }}, {{
        config_id: CONFIG_ID,
        response_type: "code",
        override_default_response_type: true,
        extras: {{ setup: {{}}, featureType: "whatsapp_business_app_onboarding", sessionInfoVersion: "3" }}
      }});
    }});
  </script>
</body>
</html>"""


HOSTED_HTML = """<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{t_title}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 640px; margin: 40px auto; padding: 0 16px; color: #222; }}
    h1 {{ font-size: 1.4rem; }}
    button {{ background:#25D366; color:#fff; border:0; padding:12px 20px; font-size:1rem; border-radius:8px; cursor:pointer; }}
    button:disabled {{ opacity:.5; cursor:not-allowed; }}
    #status {{ margin-top:20px; padding:12px; border-radius:8px; background:#f5f5f5; white-space:pre-wrap; word-break:break-word; }}
    #status a {{ color:#0b5; }}
    ol {{ line-height:1.6; }}
  </style>
</head>
<body>
  <h1>{t_title}</h1>
  <ol>
    <li>{t_step_button}</li>
    <li>{t_step_dialog}</li>
    <li>{t_step_age}</li>
  </ol>
  <button id="btn">{t_connect}</button>
  <button id="retry" style="display:none;background:#555;margin-left:8px"></button>
  <div id="status"></div>

  <script>
    var ACCOUNT_ID = {account_id};
    var BROKER_ORIGIN = {broker_origin};
    var T = {{
      opening: {t_opening}, blocked: {t_blocked}, waiting: {t_waiting}, processing: {t_processing},
      pending: {t_pending}, connected: {t_connected}, close: {t_close}, error: {t_error},
      unknown: {t_unknown}, retry: {t_retry}
    }};
    var btn = document.getElementById("btn");
    var retry = document.getElementById("retry");
    var statusEl = document.getElementById("status");
    var popup = null;
    retry.textContent = T.retry;

    function setStatus(msg, html) {{ if (html) statusEl.innerHTML = msg; else statusEl.textContent = msg; }}
    function escapeHtml(s) {{ return String(s).replace(/[&<>"]/g, function (c) {{ return {{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}}[c]; }}); }}

    /* Odoo JSON routes speak JSON-RPC: errors come back as JSON, never as HTML. */
    function rpc(path, params) {{
      return fetch(path, {{
        method: "POST", credentials: "same-origin",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ jsonrpc: "2.0", method: "call", id: Date.now(), params: params }})
      }}).then(function (r) {{ return r.json(); }}).then(function (j) {{
        if (j.error) {{ throw new Error((j.error.data && j.error.data.message) || j.error.message || T.unknown); }}
        return j.result;
      }});
    }}

    function collect() {{
      setStatus(T.processing);
      retry.style.display = "none";
      rpc("/whatsapp/coexistence/signup/collect", {{ account_id: ACCOUNT_ID }}).then(function (res) {{
        if (res.status === "done") {{
          setStatus("✅ " + T.connected + " " + (res.name || "") + " " + (res.phone_number || "") + ". " + T.close);
          btn.style.display = "none";
        }} else {{
          setStatus((res.last_error ? "❌ " + T.error + " " + res.last_error + "\\n" : "") + T.pending);
          retry.style.display = "inline-block";
        }}
      }}).catch(function (e) {{
        setStatus("❌ " + T.error + " " + (e.message || T.unknown));
        btn.disabled = false;
        retry.style.display = "inline-block";
      }});
    }}

    window.addEventListener("message", function (event) {{
      if (event.origin !== BROKER_ORIGIN) return;                 /* essential */
      var data = event.data;
      if (!data || data.type !== "wacoex_signup") return;
      if (data.ok) {{
        collect();
      }} else {{
        /* the popup stays open with a "try again" button; the session is still valid */
        setStatus("❌ " + T.error + " " + (data.error || T.unknown));
      }}
    }});

    btn.addEventListener("click", function () {{
      btn.disabled = true;
      setStatus(T.opening);
      rpc("/whatsapp/coexistence/signup/session", {{ account_id: ACCOUNT_ID }}).then(function (res) {{
        /* no "noopener": the popup needs window.opener to report back */
        popup = window.open(res.url, "wacoex_signup", "width=720,height=780");
        if (!popup) {{
          setStatus(T.blocked + ' <a href="' + escapeHtml(res.url) + '" target="_blank" rel="opener">' + escapeHtml(res.url) + "</a>", true);
        }} else {{
          setStatus(T.waiting);
        }}
        retry.style.display = "inline-block";
      }}).catch(function (e) {{
        setStatus("❌ " + T.error + " " + (e.message || T.unknown));
        btn.disabled = false;
      }});
    }});
    retry.addEventListener("click", collect);
  </script>
</body>
</html>"""
