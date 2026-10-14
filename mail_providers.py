"""
Credential Protocol: email services.

Every email the app sends is first built in one plain shape (the one Brevo uses):

    {"sender": {"name", "email"}, "to": [{"email", "name"}], "subject", "htmlContent", "textContent",
     "attachment": [{"name", "content" (base64)}], "headers": {...}}

and handed to `send(provider, payload)`, which turns it into what the chosen email service wants and sends it.
Nothing else in the app knows which service is used.

Services:
  brevo    BREVO_API_KEY
  mailjet  MAILJET_API_KEY + MAILJET_SECRET_KEY      (a free plan, and one sender address is checked by a link, no domain)
  resend   RESEND_API_KEY                            (needs a domain you own, checked with a few DNS records)
  smtp     SMTP_HOST (+ SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_SECURITY)   any service; Railway blocks it on its free and
                                                      hobby plans, so use one of the services above there

`EMAIL_PROVIDER` picks one by name; without it the first service whose keys are set is used (brevo, mailjet, resend, smtp).
The sender address is `FROM_EMAIL` (or the older `GMAIL_ADDRESS`).
"""

import base64
import mimetypes
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

import requests

PROVIDERS = ("brevo", "mailjet", "resend", "smtp")
NAMES = {"brevo": "Brevo", "mailjet": "Mailjet", "resend": "Resend", "smtp": "your email server (SMTP)"}
TIMEOUT = 15

BREVO_URL = "https://api.brevo.com/v3/smtp/email"
MAILJET_URL = "https://api.mailjet.com/v3.1/send"
RESEND_URL = "https://api.resend.com/emails"


_VARS = {"brevo": ("BREVO_API_KEY",), "mailjet": ("MAILJET_API_KEY", "MAILJET_SECRET_KEY"), "resend": ("RESEND_API_KEY",), "smtp": ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD")}


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def has_keys(provider: str, brevo_key=None) -> bool:
    """True when the settings a service needs are all there."""
    if provider == "brevo":
        return bool(_env("BREVO_API_KEY") if brevo_key is None else brevo_key)
    if provider == "mailjet":
        return bool(_env("MAILJET_API_KEY") and _env("MAILJET_SECRET_KEY"))
    if provider == "resend":
        return bool(_env("RESEND_API_KEY"))
    if provider == "smtp":
        return bool(_env("SMTP_HOST"))
    return False


def active(brevo_key=None) -> str:
    """The service in use: EMAIL_PROVIDER when it names one, else the first one that has its keys, else brevo."""
    chosen = _env("EMAIL_PROVIDER").lower()
    if chosen in PROVIDERS:
        return chosen
    for p in PROVIDERS:
        if has_keys(p, brevo_key):
            return p
    # nothing complete: the service the person has started on, so the message can say what is still missing
    for p in PROVIDERS:
        if any(_env(v) for v in _VARS[p]):
            return p
    return "brevo"


def configured(brevo_key=None) -> bool:
    return has_keys(active(brevo_key), brevo_key)


def missing(brevo_key=None) -> str:
    """A plain sentence on what to set when email is not ready ('' when it is ready)."""
    p = active(brevo_key)
    if has_keys(p, brevo_key):
        return ""
    need = {"brevo": "BREVO_API_KEY", "mailjet": "MAILJET_API_KEY and MAILJET_SECRET_KEY", "resend": "RESEND_API_KEY",
            "smtp": "SMTP_HOST (and usually SMTP_USER and SMTP_PASSWORD)"}[p]
    return f"Set {need} and FROM_EMAIL (your sender address). See SETUP.md."


def _addr(person: dict) -> str:
    person = person or {}
    return formataddr((str(person.get("name") or ""), str(person.get("email") or "")))


def _content_type(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _headers(payload: dict) -> dict:
    h = payload.get("headers")
    return {str(k): str(v) for k, v in h.items()} if isinstance(h, dict) else {}


# ── translators (pure) ──
def to_mailjet(payload: dict) -> dict:
    msg = {
        "From": {"Email": payload["sender"]["email"], "Name": payload["sender"].get("name") or ""},
        "To": [{"Email": t["email"], "Name": t.get("name") or ""} for t in payload["to"]],
        "Subject": payload.get("subject") or "",
        "TextPart": payload.get("textContent") or "",
        "HTMLPart": payload.get("htmlContent") or "",
    }
    if payload.get("attachment"):
        msg["Attachments"] = [{"ContentType": _content_type(a["name"]), "Filename": a["name"], "Base64Content": a["content"]}
                              for a in payload["attachment"]]
    hdrs = _headers(payload)
    if hdrs:
        msg["Headers"] = hdrs
    return {"Messages": [msg]}


def to_resend(payload: dict) -> dict:
    body = {
        "from": _addr(payload["sender"]),
        "to": [_addr(t) for t in payload["to"]],
        "subject": payload.get("subject") or "",
        "html": payload.get("htmlContent") or "",
        "text": payload.get("textContent") or "",
    }
    if payload.get("attachment"):
        body["attachments"] = [{"filename": a["name"], "content": a["content"]} for a in payload["attachment"]]
    hdrs = _headers(payload)
    if hdrs:
        body["headers"] = hdrs
    return body


def to_smtp_message(payload: dict) -> EmailMessage:
    m = EmailMessage()
    m["From"] = _addr(payload["sender"])
    m["To"] = ", ".join(_addr(t) for t in payload["to"])
    m["Subject"] = payload.get("subject") or ""
    for k, v in _headers(payload).items():
        m[k] = v
    m.set_content(payload.get("textContent") or "")
    m.add_alternative(payload.get("htmlContent") or "", subtype="html")
    for a in payload.get("attachment") or []:
        main, _, sub = _content_type(a["name"]).partition("/")
        m.add_attachment(base64.b64decode(a["content"]), maintype=main, subtype=sub or "octet-stream", filename=a["name"])
    return m


# ── senders ──
def _short(text: str, n: int = 300) -> str:
    return " ".join(str(text).split())[:n]


def _send_brevo(payload: dict, brevo_key=None, url="") -> tuple:
    key = _env("BREVO_API_KEY") if brevo_key is None else brevo_key
    resp = requests.post(url or BREVO_URL,
                         headers={"accept": "application/json", "api-key": key, "content-type": "application/json"},
                         json=payload, timeout=TIMEOUT)
    if resp.status_code in (200, 201, 202):
        return True, "sent"
    return False, f"Brevo {resp.status_code} — {resp.text}"


def _send_mailjet(payload: dict) -> tuple:
    resp = requests.post(MAILJET_URL, auth=(_env("MAILJET_API_KEY"), _env("MAILJET_SECRET_KEY")),
                         headers={"Content-Type": "application/json"}, json=to_mailjet(payload), timeout=TIMEOUT)
    if resp.status_code == 200:
        try:
            first = (resp.json().get("Messages") or [{}])[0]
        except ValueError:
            first = {}
        if str(first.get("Status") or "success").lower() == "success":
            return True, "sent"
        return False, f"Mailjet — {_short(first.get('Errors') or first)}"
    hint = " (Is the sender address validated in Mailjet?)" if resp.status_code in (400, 401, 403) else ""
    return False, f"Mailjet {resp.status_code} — {_short(resp.text)}{hint}"


def _send_resend(payload: dict) -> tuple:
    resp = requests.post(RESEND_URL, headers={"Authorization": f"Bearer {_env('RESEND_API_KEY')}", "Content-Type": "application/json"},
                         json=to_resend(payload), timeout=TIMEOUT)
    if resp.status_code in (200, 201, 202):
        return True, "sent"
    hint = " (Is your domain verified in Resend, and does the sender address use it?)" if resp.status_code in (400, 403, 422) else ""
    return False, f"Resend {resp.status_code} — {_short(resp.text)}{hint}"


def _send_smtp(payload: dict) -> tuple:
    host = _env("SMTP_HOST")
    try:
        port = int(_env("SMTP_PORT") or 587)
    except ValueError:
        return False, "SMTP_PORT must be a number such as 587 or 465."
    mode = _env("SMTP_SECURITY").lower() or ("ssl" if port == 465 else "starttls")
    msg = to_smtp_message(payload)
    if mode == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(host, port, timeout=20)
    try:
        server.ehlo()
        if mode == "starttls":
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        if _env("SMTP_USER"):
            server.login(_env("SMTP_USER"), os.environ.get("SMTP_PASSWORD", ""))
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:
            pass
    return True, "sent"


def send(provider: str, payload: dict, brevo_key=None, brevo_url="") -> tuple:
    """Sends one prepared message. Returns (ok, human-readable detail). Never raises."""
    try:
        if provider == "brevo":
            return _send_brevo(payload, brevo_key, brevo_url)
        if provider == "mailjet":
            return _send_mailjet(payload)
        if provider == "resend":
            return _send_resend(payload)
        if provider == "smtp":
            return _send_smtp(payload)
        return False, "Unknown email service."
    except smtplib.SMTPAuthenticationError:
        return False, "The email server refused the user name or password (SMTP_USER / SMTP_PASSWORD)."
    except (OSError, smtplib.SMTPException) as e:
        extra = " Railway's free and hobby plans block SMTP: use Brevo, Mailjet or Resend there." if provider == "smtp" else ""
        return False, f"{NAMES.get(provider, provider)}: {_short(e)}.{extra}"
    except Exception as e:
        return False, f"{NAMES.get(provider, provider)}: {_short(e)}"
