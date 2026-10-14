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

The same settings can be typed into the dashboard (Settings > Emails > Email service). They are kept in one small private file
(`email_service.json` in DATA_DIR, owner-only, never part of a backup) and win over Railway variables of the same name. A
"Remove" button deletes the file, so the Railway variables apply again.
"""

import base64
import json
import mimetypes
import os
import re
import smtplib
import ssl
import tempfile
import threading
from pathlib import Path
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


# ── settings typed into the dashboard ──
# What each service needs: (setting name, is it secret, label)
FIELDS = {
    "brevo": (("BREVO_API_KEY", True),),
    "mailjet": (("MAILJET_API_KEY", False), ("MAILJET_SECRET_KEY", True)),
    "resend": (("RESEND_API_KEY", True),),
    "smtp": (("SMTP_HOST", False), ("SMTP_PORT", False), ("SMTP_USER", False), ("SMTP_PASSWORD", True), ("SMTP_SECURITY", False)),
}
REQUIRED = {"brevo": ("BREVO_API_KEY",), "mailjet": ("MAILJET_API_KEY", "MAILJET_SECRET_KEY"), "resend": ("RESEND_API_KEY",), "smtp": ("SMTP_HOST",)}
_ALLOWED = {"EMAIL_PROVIDER", "FROM_EMAIL"} | {n for fs in FIELDS.values() for n, _ in fs}
MAX_VALUE = 500
_EMAIL_RE = re.compile(r"^[^@\s<>,;\"']+@[^@\s<>,;\"']+\.[^@\s<>,;\"']+$")
_store = {"path": None, "mtime": None, "data": {}}
_store_lock = threading.Lock()


def use_store(path) -> None:
    """Where the dashboard's email settings are kept (None = nowhere: only Railway variables count)."""
    with _store_lock:
        _store.update(path=Path(path) if path else None, mtime=None, data={})


def saved() -> dict:
    """The settings typed into the dashboard, {NAME: value}. Never raises; a missing or damaged file means none."""
    path = _store["path"]
    if not path:
        return {}
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        with _store_lock:
            _store.update(mtime=None, data={})
        return {}
    with _store_lock:
        if _store["mtime"] == mtime:
            return dict(_store["data"])
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        data = {k: str(v).strip() for k, v in raw.items() if k in _ALLOWED and isinstance(v, (str, int))} if isinstance(raw, dict) else {}
        _store.update(mtime=mtime, data=data)
        return dict(data)


def _write(data: dict) -> None:
    path = _store["path"]
    if not path:
        raise OSError("no place to keep the settings")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".email-", suffix=".tmp", dir=str(path.parent))
    try:
        os.chmod(tmp, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    with _store_lock:
        _store.update(mtime=None)


def clear_saved() -> None:
    path = _store["path"]
    if path and path.exists():
        path.unlink()
    with _store_lock:
        _store.update(mtime=None, data={})


def _env(name: str) -> str:
    """A setting: what was typed into the dashboard, else the Railway variable."""
    return saved().get(name) or (os.environ.get(name) or "").strip()


def sender_address() -> str:
    """The sender address from the dashboard or Railway ('' when none is set)."""
    return saved().get("FROM_EMAIL") or _env("FROM_EMAIL") or _env("GMAIL_ADDRESS")


def save_from_dashboard(provider: str, values: dict, from_email: str) -> tuple:
    """Checks and keeps the dashboard form. Returns (True, "") or (False, what to fix).
    A secret left empty keeps the one saved before (when the same service was saved before)."""
    provider = str(provider or "").lower()
    if provider not in PROVIDERS:
        return False, "Choose an email service."
    values = values if isinstance(values, dict) else {}
    old = saved()
    keep_old = old.get("EMAIL_PROVIDER") == provider
    out = {"EMAIL_PROVIDER": provider}
    for name, secret in FIELDS[provider]:
        v = " ".join(str(values.get(name) if values.get(name) is not None else "").split())
        if not v and secret and keep_old:
            v = old.get(name, "")
        if len(v) > MAX_VALUE:
            return False, "One of the boxes has too much text in it."
        if v:
            out[name] = v
    for name in REQUIRED[provider]:
        if not out.get(name):
            label = {"BREVO_API_KEY": "API key", "MAILJET_API_KEY": "API key", "MAILJET_SECRET_KEY": "Secret key",
                     "RESEND_API_KEY": "API key", "SMTP_HOST": "Server (host)"}[name]
            return False, f"Fill in the {label}."
    if out.get("SMTP_HOST") and not re.match(r"^[A-Za-z0-9]([A-Za-z0-9.\-]*[A-Za-z0-9])?$", out["SMTP_HOST"]):
        return False, "The server (host) is a name like smtp.example.com, with no spaces, http:// or slashes."
    if out.get("SMTP_PORT"):
        try:
            if not 1 <= int(out["SMTP_PORT"]) <= 65535:
                raise ValueError
        except ValueError:
            return False, "The port is a number such as 587 or 465."
    if out.get("SMTP_SECURITY", "starttls") not in ("starttls", "ssl", "none"):
        return False, "Security must be starttls, ssl or none."
    sender = " ".join(str(from_email or "").split())
    if not _EMAIL_RE.match(sender) or len(sender) > 254:
        return False, "Fill in your sender address, the email address people will see the emails coming from."
    out["FROM_EMAIL"] = sender
    try:
        _write(out)
    except OSError as e:
        print(f"❌ Email settings could not be saved: {e}")
        return False, "The settings could not be saved on the server's storage."
    return True, ""


def status(brevo_key=None) -> dict:
    """What the dashboard shows. Never contains a secret: only whether it is set, where, and the last 4 characters of one typed in."""
    sv = saved()
    prov = active(brevo_key)
    fields = {}
    for p, fs in FIELDS.items():
        for name, secret in fs:
            dash, env = sv.get(name, ""), (os.environ.get(name) or "").strip()
            if secret:
                fields[name] = {"set": bool(dash or env), "where": "dashboard" if dash else ("railway" if env else ""),
                                "tail": ("…" + dash[-4:]) if len(dash) >= 8 else ""}
            else:
                fields[name] = {"set": bool(dash or env), "where": "dashboard" if dash else ("railway" if env else ""), "value": dash or env}
    sender = sv.get("FROM_EMAIL") or _env("FROM_EMAIL") or _env("GMAIL_ADDRESS")
    return {"provider": prov, "name": NAMES[prov], "configured": has_keys(prov, brevo_key) and bool(sender),
            "from_email": sender, "from_where": "dashboard" if sv.get("FROM_EMAIL") else ("railway" if sender else ""),
            "from_default": not sender, "saved": bool(sv), "fields": fields,
            "names": {p: NAMES[p] for p in PROVIDERS}}


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
