"""
Credential Protocol — Email Sender
Sends the credential email to a new member.

Uses the Brevo (formerly Sendinblue) transactional email HTTP API.
Switched from SendGrid because SendGrid gates new accounts behind a
Twilio phone-verification step that can be unreliable (VOIP/forwarded
numbers often get rejected outright). Brevo verifies its sender by an
email link instead — no phone step. Like SendGrid, this goes out over
plain HTTPS, so it isn't affected by Railway's outbound SMTP block
(confirmed earlier: raw SMTP to Gmail failed both with an instant
"Network is unreachable" and, once forced onto IPv4, a hard timeout).

Branding (creator name, card title, accent color, members page) and the
wording of the welcome email (subject, intro, sign-off — all editable in
the dashboard's "Welcome email" section) come from the live settings, read
fresh on every send. See SETUP.md.
"""

import base64
import json
import os
import re
import requests
from html import escape as _esc
from pathlib import Path

import card_kinds
import config_store
import email_templates
import public_url

BASE_DIR = Path(__file__).resolve().parent


def _load_config() -> dict:
    # The live settings (DATA_DIR/config.json once the dashboard has saved
    # any, otherwise the repo default) — see config_store.py.
    return config_store.read_config()


_cfg = _load_config()

# ── CONFIG — fill these in (config.json for branding, env vars for secrets) ──
BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
FROM_EMAIL    = os.environ.get("GMAIL_ADDRESS", "your@gmail.com")   # must match your Brevo verified sender
CREATOR_NAME  = _cfg.get("creator_name", "Your Creator Name")
CARD_TITLE    = _cfg.get("card_title", "YOUR BRAND HERE")
ACCENT_COLOR  = _cfg.get("accent_color", "#00e87a")
FROM_NAME     = CARD_TITLE
MEMBERS_PAGE  = os.environ.get("MEMBERS_PAGE", _cfg.get("members_page", ""))   # refreshed (and defaulted) per send

BREVO_URL = "https://api.brevo.com/v3/smtp/email"

# The wording a creator can change in the dashboard. {name}, {tier},
# {creator}, {brand} and {expires} are filled in per member.
DEFAULT_SUBJECT = "Your Access Card — {name}"
DEFAULT_INTRO   = ("{name} — your credential has been issued and signed.\n"
                   "Your card and bundle are attached to this email.")
PLACEHOLDERS    = ("name", "tier", "creator", "brand", "expires")
MAX_SUBJECT, MAX_INTRO, MAX_SIGNOFF = 150, 1000, 600

# Expiry reminder wording (also editable in the dashboard). Same five
# placeholders plus {days}, which becomes "3 days" / "1 day".
DEFAULT_REMINDER_SUBJECT = "Your access ends on {expires}"
DEFAULT_REMINDER_TEXT    = ("{name} — your {tier} access ends on {expires}, {days} from now.\n"
                            "To keep it going, renew with {creator} before then.")
MAX_REMINDER_SUBJECT, MAX_REMINDER_TEXT, MAX_RENEW_URL = 150, 1000, 500

# "Access extended" wording (editable too). Same five placeholders plus {days},
# which here is how many days were added ("5 days").
DEFAULT_EXTENDED_SUBJECT = "Your access has been extended until {expires}"
DEFAULT_EXTENDED_TEXT    = ("{name} — your {tier} access has been extended by {days}.\n"
                            "It now runs until {expires}. Your access link has not changed.")
MAX_EXTENDED_SUBJECT, MAX_EXTENDED_TEXT = 150, 1000


def _fill(text: str, values: dict) -> str:
    """Replace {name}-style placeholders. Only the names present in `values`
    are touched (no str.format), so stray braces in a creator's text are
    safe — and {days} stays as typed in the welcome email, where it means
    nothing."""
    names = [re.escape(k) for k in values]
    if not names:
        return text or ""
    return re.sub(r"\{(%s)\}" % "|".join(names),
                  lambda m: str(values.get(m.group(1), "")), text or "")


def is_configured() -> bool:
    """True when this server can actually send email."""
    return bool(BREVO_API_KEY)


def _refresh_branding():
    """Re-read the branding values from the current settings. They used to
    be read once at import time, which meant a change saved in the dashboard
    didn't reach emails until the app restarted. Called at the start of
    every send so emails always use what's currently saved."""
    global CREATOR_NAME, CARD_TITLE, ACCENT_COLOR, FROM_NAME, MEMBERS_PAGE
    cfg = _load_config()
    CREATOR_NAME = cfg.get("creator_name", "Your Creator Name")
    CARD_TITLE   = cfg.get("card_title", "YOUR BRAND HERE")
    ACCENT_COLOR = cfg.get("accent_color", "#00e87a")
    FROM_NAME    = CARD_TITLE
    MEMBERS_PAGE = public_url.effective_members_page(os.environ.get("MEMBERS_PAGE", cfg.get("members_page", "")))


def build_email(
    to_name:       str,
    tier:          str,
    credential_id: str,
    bundle_hash:   str,
    expires_at:    str,
    overrides:     dict = None,
    link_base:     str = None,
) -> dict:
    """
    Build the welcome email: {"subject", "html", "text", "link"}.

    Everything about the member (name, tier) comes from the public signup
    form, so it's HTML-escaped before it goes into the page — a name with
    markup in it shows up as text, not as part of the email.

    `overrides` (email_subject / email_intro / email_signoff) lets the
    dashboard preview or test-send wording that hasn't been saved yet; with
    none, the saved settings are used.
    """
    _refresh_branding()
    cfg = _load_config()
    ov  = overrides or {}

    def pick(key):
        return ov[key] if key in ov else cfg.get(key, "")

    subject_t = (str(pick("email_subject") or "").strip() or DEFAULT_SUBJECT)[:MAX_SUBJECT]
    intro_t   = (str(pick("email_intro")   or "").strip() or DEFAULT_INTRO)[:MAX_INTRO]
    signoff_t = (str(pick("email_signoff") or "").strip())[:MAX_SIGNOFF]

    # A collectible never expires: say so instead of printing the far-future date.
    never   = card_kinds.is_never(expires_at)
    expires = "forever" if never else (expires_at or "")[:10]
    exp_label = "VALID" if never else "VALID UNTIL"
    values  = {"name": to_name, "tier": tier, "creator": CREATOR_NAME,
               "brand": CARD_TITLE, "expires": expires}

    subject = re.sub(r"[\r\n]+", " ", _fill(subject_t, values)).strip()
    intro   = _fill(intro_t, values)
    signoff = _fill(signoff_t, values)

    base = MEMBERS_PAGE if link_base is None else link_base
    sep = "&" if "?" in base else "?"
    personal_link = f"{base}{sep}id={credential_id}&h={bundle_hash[:32]}"

    e_name, e_tier  = _esc(to_name), _esc(tier)
    e_creator       = _esc(CREATOR_NAME.upper())
    e_brand         = _esc(CARD_TITLE)
    e_link_attr     = _esc(personal_link, quote=True)
    e_link_text     = _esc(personal_link)
    e_intro         = _esc(intro).replace("\n", "<br>")
    signoff_html    = (f'\n  <div class="value" style="margin-top:28px;line-height:1.8;">'
                       f'{_esc(signoff).replace(chr(10), "<br>")}</div>\n') if signoff else ""

    # ── HTML email body ──
    html_body = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body {{
    background: #0a0908;
    color: #e6dfd2;
    font-family: 'Courier New', monospace;
    margin: 0;
    padding: 0;
  }}
  .wrap {{
    max-width: 560px;
    margin: 0 auto;
    padding: 48px 32px;
  }}
  .header {{
    font-size: 28px;
    letter-spacing: 6px;
    color: {_esc(ACCENT_COLOR, quote=True)};
    text-transform: uppercase;
    margin-bottom: 4px;
  }}
  .sub {{
    font-size: 9px;
    letter-spacing: 3px;
    color: #6b6058;
    text-transform: uppercase;
    margin-bottom: 40px;
  }}
  .line {{
    border: none;
    border-top: 1px solid #3a1210;
    margin: 28px 0;
  }}
  .label {{
    font-size: 8px;
    letter-spacing: 3px;
    color: {_esc(ACCENT_COLOR, quote=True)};
    text-transform: uppercase;
    margin-bottom: 6px;
  }}
  .value {{
    font-size: 12px;
    color: #e6dfd2;
    margin-bottom: 20px;
  }}
  .access-btn {{
    display: inline-block;
    background: {_esc(ACCENT_COLOR, quote=True)};
    color: #0a0908;
    font-family: 'Courier New', monospace;
    font-size: 11px;
    letter-spacing: 3px;
    text-transform: uppercase;
    padding: 14px 28px;
    text-decoration: none;
    margin: 24px 0;
  }}
  .warning {{
    font-size: 10px;
    color: {_esc(ACCENT_COLOR, quote=True)};
    letter-spacing: 1px;
    text-transform: uppercase;
    border-left: 2px solid #3a1210;
    padding: 10px 14px;
    margin-top: 28px;
    line-height: 1.8;
  }}
  .footer {{
    font-size: 8px;
    color: #3a1210;
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-top: 40px;
    line-height: 2;
  }}
  .row {{
    display: flex;
    justify-content: space-between;
    padding: 8px 0;
    border-bottom: 1px solid #1a100e;
    font-size: 10px;
  }}
  .row-label {{ color: #6b6058; }}
  .row-val   {{ color: #e6dfd2; }}
</style>
</head>
<body>
<div class="wrap">

  <div class="header">{e_creator}</div>
  <div class="sub">{e_brand} — Member Access</div>

  <hr class="line">

  <div class="label">Welcome</div>
  <div class="value">
    {e_intro}
  </div>

  <div class="row">
    <span class="row-label">MEMBER</span>
    <span class="row-val">{_esc(to_name.upper())}</span>
  </div>
  <div class="row">
    <span class="row-label">ACCESS CLASS</span>
    <span class="row-val">{e_tier}</span>
  </div>
  <div class="row">
    <span class="row-label">CREDENTIAL ID</span>
    <span class="row-val">{_esc(credential_id[:16].upper())}</span>
  </div>
  <div class="row">
    <span class="row-label">{exp_label}</span>
    <span class="row-val">{_esc(expires)}</span>
  </div>
  <div class="row">
    <span class="row-label">ISSUED BY</span>
    <span class="row-val">{e_creator}</span>
  </div>

  <hr class="line">

  <div class="label">Your personal access link</div>
  <a href="{e_link_attr}" class="access-btn">◈ Get Access</a>

  <div style="font-size:9px;color:#6b6058;letter-spacing:1px;word-break:break-all;margin-top:-12px;">
    {e_link_text}
  </div>

  <hr class="line">

  <div class="label">What's attached</div>
  <div class="value" style="font-size:10px;line-height:2;color:#6b6058;">
    ◈ Your member card (HTML) — a signed keepsake with your QR code<br>
    ◈ Your credential bundle (ZIP) — a signed backup copy, for your records<br>
    ◈ Use the link above (or the QR on your card) to get into the member area
  </div>

  <div class="warning">
    KEEP YOUR ACCESS LINK SOMEWHERE SAFE.<br>
    YOUR CARD AND BUNDLE ARE YOUR SIGNED PROOF OF MEMBERSHIP —<br>
    BUT THE LINK ABOVE IS WHAT ACTUALLY GETS YOU IN.
  </div>
{signoff_html}
  <hr class="line">

  <div class="footer">
    {e_brand}<br>
    Your credential is cryptographically signed with ECDSA.<br>
    Keep your card and bundle safe — they are your access key.
  </div>

</div>
</body>
</html>"""

    # ── Plain text fallback ──
    signoff_text = f"\n{signoff}\n" if signoff else ""
    plain_body = f"""
{CREATOR_NAME.upper()} — {CARD_TITLE.upper()} MEMBER ACCESS
======================================

{intro}

MEMBER:      {to_name.upper()}
TIER:        {tier}
ID:          {credential_id[:16].upper()}
{exp_label+":":<12} {expires}
ISSUED BY:   {CREATOR_NAME.upper()}

YOUR PERSONAL ACCESS LINK (this is what gets you in):
{personal_link}

Your member card (HTML) and credential bundle (ZIP) are also attached —
a signed keepsake and a signed backup copy, for your records.

Keep your access link somewhere safe.
{signoff_text}
{CARD_TITLE}
"""
    return {"subject": subject, "html": html_body, "text": plain_body, "link": personal_link}


def _post_to_brevo(payload: dict) -> tuple:
    """Send one prepared message. Returns (ok, human-readable detail)."""
    try:
        if not BREVO_API_KEY:
            raise RuntimeError("BREVO_API_KEY is not set")
        resp = requests.post(
            BREVO_URL,
            headers={
                "accept": "application/json",
                "api-key": BREVO_API_KEY,
                "content-type": "application/json",
            },
            json=payload,
            timeout=15,
        )
        if resp.status_code in (200, 201, 202):
            return True, "sent"
        return False, f"Brevo {resp.status_code} — {resp.text}"
    except Exception as e:
        return False, str(e)


def send_credential_email(
    to_name:       str,
    to_email:      str,
    tier:          str,
    credential_id: str,
    bundle_hash:   str,
    bundle_path:   str,
    card_path:     str,
    expires_at:    str,
    kind:          str = "pass",
    event:         dict = None,
    drop:          dict = None,
) -> bool:
    """
    Send the credential email via Brevo's HTTP API: the Welcome email for a
    membership, the ticket confirmation for a ticket, the collectible one for
    a collectible. Attaches the card HTML and bundle ZIP and includes the
    personal access link. Returns True on success.
    """
    if kind == "ticket" and event:
        msg = build_ticket_email(to_name, tier, credential_id, bundle_hash, event)
    elif kind == "collectible" and drop:
        msg = build_collectible_email(to_name, tier, credential_id, bundle_hash, drop)
    else:
        msg = build_email(to_name, tier, credential_id, bundle_hash, expires_at)

    try:
        if not BREVO_API_KEY:
            raise RuntimeError("BREVO_API_KEY is not set")

        attachments = []

        if card_path and Path(card_path).exists():
            with open(card_path, "rb") as f:
                attachments.append({
                    "content": base64.b64encode(f.read()).decode("ascii"),
                    "name": f"member_card_{credential_id[:8]}.html",
                })

        if bundle_path and Path(bundle_path).exists():
            with open(bundle_path, "rb") as f:
                attachments.append({
                    "content": base64.b64encode(f.read()).decode("ascii"),
                    "name": f"credential_{credential_id[:8]}.zip",
                })

        payload = {
            "sender": {"name": FROM_NAME, "email": FROM_EMAIL},
            "to": [{"email": to_email, "name": to_name}],
            "subject": msg["subject"],
            "htmlContent": msg["html"],
            "textContent": msg["text"],
        }
        if attachments:
            payload["attachment"] = attachments
    except Exception as e:
        print(f"❌ Email failed: {e}")
        return False

    ok, detail = _post_to_brevo(payload)
    if ok:
        print(f"✔ Email sent to {to_email}")
    else:
        print(f"❌ Email failed: {detail}")
    return ok


# A made-up member used for the dashboard's preview and test email.
_SAMPLE = dict(to_name="Sample Member", credential_id="0123456789abcdef0123",
               bundle_hash="a1b2c3d4e5f60718293a4b5c6d7e8f90", expires_at="2099-12-31T00:00:00+00:00")


def preview_email(tier: str, overrides: dict = None) -> dict:
    """The welcome email for a made-up member, from wording that may not be
    saved yet — what the dashboard's Preview shows. Nothing is sent."""
    _refresh_branding()   # MEMBERS_PAGE below must be the current setting, not the import-time one
    return build_email(tier=tier or "MEMBER", overrides=overrides,
                       link_base=MEMBERS_PAGE or "https://your-site.example/members", **_SAMPLE)


def send_test_email(to_email: str, tier: str, overrides: dict = None, kind: str = "welcome") -> tuple:
    """Send the sample email ("welcome", "reminder" or "extended") to one address (no
    attachments). Returns (ok, message for the creator)."""
    if not BREVO_API_KEY:
        return False, ("Email isn't set up on this server yet, so nothing can be sent. "
                       "Set BREVO_API_KEY and GMAIL_ADDRESS (see SETUP.md), then try again.")
    msg = preview_kind(kind, tier, overrides)
    ok, detail = _post_to_brevo({
        "sender": {"name": FROM_NAME, "email": FROM_EMAIL},
        "to": [{"email": to_email}],
        "subject": "[TEST] " + msg["subject"],
        "htmlContent": msg["html"],
        "textContent": msg["text"],
    })
    if ok:
        return True, f"Test email sent to {to_email}. Check the inbox (and spam)."
    print(f"❌ Test email failed: {detail}")
    return False, f"The email service refused it: {detail}"


# ── Renewal emails: "access extended" and "expiry reminder" ──
def _shell(heading: str, intro: str, rows, link: str, link_label: str, extra_html: str = "", footer_note: str = "",
           blocks=None) -> str:
    """The shared look of the short emails below. `rows` is a list of
    (label, value) pairs; `blocks` is a list of (label, text) paragraphs shown
    before the rows; with no `link` there is no button. Everything is escaped here."""
    acc = _esc(ACCENT_COLOR, quote=True)
    rows_html = "".join(
        f'<div class="row"><span class="row-label">{_esc(a)}</span><span class="row-val">{_esc(b)}</span></div>'
        for a, b in rows)
    blocks_html = "".join(
        f'<div class="label" style="margin-top:6px;">{_esc(a)}</div>'
        f'<div class="value">{_esc(b).replace(chr(10), "<br>")}</div>' for a, b in (blocks or []) if b)
    button_html = (f'<a href="{_esc(link, quote=True)}" class="btn">{_esc(link_label)}</a>\n  {extra_html}\n'
                   f'  <div style="font-size:9px;color:#6b6058;letter-spacing:1px;word-break:break-all;margin-top:8px;">{_esc(link)}</div>'
                   if link else extra_html)
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
  body {{ background:#0a0908; color:#e6dfd2; font-family:'Courier New',monospace; margin:0; padding:0; }}
  .wrap {{ max-width:560px; margin:0 auto; padding:48px 32px; }}
  .header {{ font-size:28px; letter-spacing:6px; color:{acc}; text-transform:uppercase; margin-bottom:4px; }}
  .sub {{ font-size:9px; letter-spacing:3px; color:#6b6058; text-transform:uppercase; margin-bottom:40px; }}
  .line {{ border:none; border-top:1px solid #3a1210; margin:28px 0; }}
  .label {{ font-size:8px; letter-spacing:3px; color:{acc}; text-transform:uppercase; margin-bottom:6px; }}
  .value {{ font-size:12px; color:#e6dfd2; margin-bottom:20px; line-height:1.7; }}
  .btn {{ display:inline-block; background:{acc}; color:#0a0908; font-size:11px; letter-spacing:3px;
          text-transform:uppercase; padding:14px 28px; text-decoration:none; margin:8px 10px 8px 0; }}
  .row {{ display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid #1a100e; font-size:10px; }}
  .row-label {{ color:#6b6058; }} .row-val {{ color:#e6dfd2; }}
  .footer {{ font-size:8px; color:#3a1210; letter-spacing:1px; text-transform:uppercase; margin-top:40px; line-height:2; }}
</style></head>
<body><div class="wrap">
  <div class="header">{_esc(CREATOR_NAME.upper())}</div>
  <div class="sub">{_esc(CARD_TITLE)} — Member Access</div>
  <hr class="line">
  <div class="label">{_esc(heading)}</div>
  <div class="value">{_esc(intro).replace(chr(10), "<br>")}</div>
  {blocks_html}
  {rows_html}
  <hr class="line">
  {button_html}
  <hr class="line">
  {('<div style="font-size:11px;line-height:1.6;color:#8a8176;margin-top:4px;">' + _esc(footer_note) + '</div>') if footer_note else ""}
  <div class="footer">{_esc(CARD_TITLE)}</div>
</div></body></html>"""


def _personal_link(credential_id: str, bundle_hash: str, link_base: str = None) -> str:
    base = MEMBERS_PAGE if link_base is None else link_base
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}id={credential_id}&h={bundle_hash[:32]}"


def _plural_days(n) -> str:
    try:
        n = int(n)
    except (ValueError, TypeError):
        n = 0
    return f"{n} day" if n == 1 else f"{n} days"


def safe_renew_url(url) -> str:
    """The renewal address from the settings, only if it is a plain web link."""
    u = str(url or "").strip()[:MAX_RENEW_URL]
    return u if re.match(r"^https?://[^\s<>\"']+$", u, re.I) else ""


def build_extended_email(to_name, tier, credential_id, bundle_hash, expires_at,
                         days_added=None, link_base=None, overrides: dict = None) -> dict:
    """The note a member gets when the creator extends their card. Subject and
    text are editable in the dashboard (`overrides` lets the preview use wording
    that is not saved yet). The access link is the same one they already have,
    so the email repeats it."""
    _refresh_branding()
    cfg = _load_config()
    ov = overrides or {}

    def pick(key):
        return ov[key] if key in ov else cfg.get(key, "")

    subject_t = (str(pick("extended_subject") or "").strip() or DEFAULT_EXTENDED_SUBJECT)[:MAX_EXTENDED_SUBJECT]
    text_t    = (str(pick("extended_text") or "").strip() or DEFAULT_EXTENDED_TEXT)[:MAX_EXTENDED_TEXT]
    expires = (expires_at or "")[:10]
    values = {"name": to_name, "tier": tier, "creator": CREATOR_NAME, "brand": CARD_TITLE,
              "expires": expires, "days": _plural_days(days_added) if days_added else "some days"}
    link = _personal_link(credential_id, bundle_hash, link_base)
    intro = _fill(text_t, values)
    subject = re.sub(r"[\r\n]+", " ", _fill(subject_t, values)).strip()
    html_body = _shell("Access extended", intro,
                       [("MEMBER", to_name.upper()), ("ACCESS CLASS", tier), ("VALID UNTIL", expires)],
                       link, "◈ Open member area")
    text = (f"{CREATOR_NAME.upper()} — {CARD_TITLE.upper()}\n\n{intro}\n\n"
            f"Your access link:\n{link}\n\n{CARD_TITLE}\n")
    return {"subject": subject, "html": html_body, "text": text, "link": link}


def build_reminder_email(to_name, tier, credential_id, bundle_hash, expires_at, days_left,
                         overrides: dict = None, link_base=None) -> dict:
    """The "your access ends soon" email. Subject and text are editable in
    the dashboard (overrides lets the preview use wording that isn't saved
    yet); an optional renewal address adds a second button."""
    _refresh_branding()
    cfg = _load_config()
    ov = overrides or {}

    def pick(key):
        return ov[key] if key in ov else cfg.get(key, "")

    subject_t = (str(pick("reminder_subject") or "").strip() or DEFAULT_REMINDER_SUBJECT)[:MAX_REMINDER_SUBJECT]
    text_t    = (str(pick("reminder_text") or "").strip() or DEFAULT_REMINDER_TEXT)[:MAX_REMINDER_TEXT]
    renew     = safe_renew_url(pick("reminder_renew_url"))

    expires = (expires_at or "")[:10]
    values = {"name": to_name, "tier": tier, "creator": CREATOR_NAME, "brand": CARD_TITLE,
              "expires": expires, "days": _plural_days(days_left)}
    subject = re.sub(r"[\r\n]+", " ", _fill(subject_t, values)).strip()
    body    = _fill(text_t, values)
    link    = _personal_link(credential_id, bundle_hash, link_base)

    extra = (f'<a href="{_esc(renew, quote=True)}" class="btn" style="background:transparent;'
             f'border:1px solid {_esc(ACCENT_COLOR, quote=True)};color:{_esc(ACCENT_COLOR, quote=True)};">'
             f'Renew</a>') if renew else ""
    html_body = _shell("Access ending soon", body,
                       [("MEMBER", to_name.upper()), ("ACCESS CLASS", tier), ("VALID UNTIL", expires)],
                       link, "◈ Open member area", extra_html=extra)
    renew_text = f"\nRenew: {renew}\n" if renew else ""
    text = (f"{CREATOR_NAME.upper()} — {CARD_TITLE.upper()}\n\n{body}\n{renew_text}\n"
            f"Your access link:\n{link}\n\n{CARD_TITLE}\n")
    return {"subject": subject, "html": html_body, "text": text, "link": link}


# ── The newer emails: ticket, collectible, how to pay, declined, event reminder, alert ──
# Each has an editable subject and message (settings keys in email_templates.py);
# blank means the standard words. They share the look of the short emails above.
def _tpl(prefix: str, overrides, default_subject: str, default_text: str):
    """The subject and message wording for one of the newer emails: what was
    typed (preview) or saved, or the standard words."""
    cfg = _load_config()
    ov = overrides or {}

    def pick(key):
        return ov[key] if key in ov else cfg.get(key, "")

    subj = (str(pick(prefix + "_subject") or "").strip() or default_subject)[:email_templates.MAX_SUBJECT]
    text = (str(pick(prefix + "_text") or "").strip() or default_text)[:email_templates.MAX_TEXT]
    return subj, text


def _one_line(text: str) -> str:
    return re.sub(r"[\r\n]+", " ", text or "").strip()


def _plain(heading_line: str, body: str, extra_lines: str, link: str) -> str:
    return (f"{CREATOR_NAME.upper()} — {CARD_TITLE.upper()}\n\n{body}\n{extra_lines}\n"
            + (f"Your access link:\n{link}\n\n" if link else "") + f"{CARD_TITLE}\n")


def _event_values(to_name, tier, event):
    ev = event or {}
    return {"name": to_name, "tier": tier, "creator": CREATOR_NAME, "brand": CARD_TITLE,
            "event": ev.get("name") or "the event", "when": ev.get("when") or "soon",
            "place": ev.get("place") or "the venue"}


def _event_rows(to_name, tier, event):
    ev = event or {}
    rows = [("MEMBER", to_name.upper()), ("EVENT", ev.get("name") or "")]
    if ev.get("when"):
        rows.append(("WHEN", ev["when"]))
    if ev.get("place"):
        rows.append(("WHERE", ev["place"]))
    rows.append(("TICKET", tier))
    return [r for r in rows if r[1]]


def build_ticket_email(to_name, tier, credential_id, bundle_hash, event, overrides: dict = None, link_base=None) -> dict:
    """The confirmation a ticket holder gets with their ticket."""
    _refresh_branding()
    subj_t, text_t = _tpl("ticket", overrides, email_templates.DEFAULT_TICKET_SUBJECT, email_templates.DEFAULT_TICKET_TEXT)
    values = _event_values(to_name, tier, event)
    link = _personal_link(credential_id, bundle_hash, link_base)
    intro = _fill(text_t, values)
    html_body = _shell("Your ticket", intro, _event_rows(to_name, tier, event), link, "◈ Open my ticket",
                       footer_note="Keep this email. Your ticket is attached; show its QR code at the door, or open the button above.")
    ev = event or {}
    extra = "".join(f"{a}: {b}\n" for a, b in _event_rows(to_name, tier, ev))
    return {"subject": _one_line(_fill(subj_t, values)), "html": html_body,
            "text": _plain("Your ticket", intro, "\n" + extra, link), "link": link}


def _edition_text(drop) -> str:
    d = drop or {}
    try:
        n, of = int(d.get("edition") or 0), int(d.get("of") or 0)
    except (TypeError, ValueError):
        n, of = 0, 0
    if not n:
        return ""
    return f"#{n} of {of}" if of else f"#{n}"


def build_collectible_email(to_name, tier, credential_id, bundle_hash, drop, overrides: dict = None, link_base=None) -> dict:
    """What a collector gets with their numbered collectible."""
    _refresh_branding()
    subj_t, text_t = _tpl("collectible", overrides, email_templates.DEFAULT_COLLECTIBLE_SUBJECT,
                          email_templates.DEFAULT_COLLECTIBLE_TEXT)
    d = drop or {}
    values = {"name": to_name, "tier": tier, "creator": CREATOR_NAME, "brand": CARD_TITLE,
              "drop": d.get("name") or tier, "edition": _edition_text(d)}
    link = _personal_link(credential_id, bundle_hash, link_base)
    intro = _fill(text_t, values)
    rows = [("COLLECTOR", to_name.upper()), ("DROP", d.get("name") or tier)]
    if values["edition"]:
        rows.append(("EDITION", values["edition"]))
    if d.get("note"):
        rows.append(("NOTE", d["note"]))
    rows.append(("VALID", "forever"))
    html_body = _shell("Collectible claimed", intro, rows, link, "◈ Open my collectible",
                       footer_note="Keep this email. Your collectible is attached; the button above opens what it unlocks.")
    extra = "".join(f"{a}: {b}\n" for a, b in rows)
    return {"subject": _one_line(_fill(subj_t, values)), "html": html_body,
            "text": _plain("Collectible", intro, "\n" + extra, link), "link": link}


def _pay_values(to_name, tier, price_text, reference):
    return {"name": to_name, "tier": tier, "creator": CREATOR_NAME, "brand": CARD_TITLE,
            "price": price_text or "the price", "reference": reference or ""}


def build_howtopay_email(to_name, tier, price_text="", reference="", instructions="", pay_url="", pay_label="",
                         overrides: dict = None) -> dict:
    """Sent when someone asks for a paid card and pays by hand or with the
    creator's own link: the creator's instructions, the pay button and the
    reference, so nothing is lost when the browser tab closes."""
    _refresh_branding()
    subj_t, text_t = _tpl("howtopay", overrides, email_templates.DEFAULT_HOWTOPAY_SUBJECT,
                          email_templates.DEFAULT_HOWTOPAY_TEXT)
    values = _pay_values(to_name, tier, price_text, reference)
    intro = _fill(text_t, values)
    instructions = str(instructions or "").strip()[:2000]
    pay_url = safe_renew_url(pay_url)
    rows = [("CARD", tier)]
    if price_text:
        rows.append(("AMOUNT", price_text))
    if reference:
        rows.append(("REFERENCE", reference))
    label = ("◈ " + (str(pay_label or "").strip()[:40] or "Pay now")) if pay_url else ""
    html_body = _shell("How to pay", intro, rows, pay_url, label,
                       footer_note="Keep this email: quote your reference if you write to us about this payment.",
                       blocks=[("What to do", instructions)])
    extra = "".join(f"{a}: {b}\n" for a, b in rows)
    plain = (f"{CREATOR_NAME.upper()} — {CARD_TITLE.upper()}\n\n{intro}\n\n"
             + (f"{instructions}\n\n" if instructions else "") + extra
             + (f"\nPay here: {pay_url}\n" if pay_url else "") + f"\n{CARD_TITLE}\n")
    return {"subject": _one_line(_fill(subj_t, values)), "html": html_body, "text": plain, "link": pay_url}


def build_declined_email(to_name, tier, price_text="", reference="", overrides: dict = None) -> dict:
    """Sent when the creator rejects a payment request."""
    _refresh_branding()
    subj_t, text_t = _tpl("declined", overrides, email_templates.DEFAULT_DECLINED_SUBJECT,
                          email_templates.DEFAULT_DECLINED_TEXT)
    values = _pay_values(to_name, tier, price_text, reference)
    intro = _fill(text_t, values)
    rows = [("CARD", tier)] + ([("REFERENCE", reference)] if reference else [])
    html_body = _shell("Payment not confirmed", intro, rows, "", "")
    extra = "".join(f"{a}: {b}\n" for a, b in rows)
    return {"subject": _one_line(_fill(subj_t, values)), "html": html_body,
            "text": _plain("Declined", intro, "\n" + extra, ""), "link": ""}


def build_event_reminder_email(to_name, tier, credential_id, bundle_hash, event, overrides: dict = None,
                               link_base=None) -> dict:
    """The "see you soon" note a ticket holder gets before the event."""
    _refresh_branding()
    subj_t, text_t = _tpl("evremind", overrides, email_templates.DEFAULT_EVREMIND_SUBJECT,
                          email_templates.DEFAULT_EVREMIND_TEXT)
    values = _event_values(to_name, tier, event)
    link = _personal_link(credential_id, bundle_hash, link_base)
    intro = _fill(text_t, values)
    html_body = _shell("Event reminder", intro, _event_rows(to_name, tier, event), link, "◈ Open my ticket")
    extra = "".join(f"{a}: {b}\n" for a, b in _event_rows(to_name, tier, event))
    return {"subject": _one_line(_fill(subj_t, values)), "html": html_body,
            "text": _plain("Reminder", intro, "\n" + extra, link), "link": link}


def build_alert_email(who_name, who_email, tier, price_text="", reference="") -> dict:
    """The note the creator gets when a payment request comes in. Fixed wording."""
    _refresh_branding()
    base = public_url.base_url() or ""
    link = (base.rstrip("/") + "/admin/dashboard") if base else ""
    who = who_name or who_email or "Someone"
    subject = _one_line(f"New payment waiting: {who} wants {tier}")[:150]
    intro = (f"{who} asked for {tier}" + (f" ({price_text})" if price_text else "") + ".\n"
             "Check that the money arrived, then approve or reject the request on your dashboard.")
    rows = [("FROM", who_name or "—"), ("EMAIL", who_email or "—"), ("CARD", tier)]
    if price_text:
        rows.append(("AMOUNT", price_text))
    if reference:
        rows.append(("REFERENCE", reference))
    html_body = _shell("Payment waiting for your OK", intro, rows, link, "◈ Open dashboard")
    extra = "".join(f"{a}: {b}\n" for a, b in rows)
    return {"subject": subject, "html": html_body,
            "text": _plain("Payment", intro, "\n" + extra, "") + (f"Dashboard: {link}\n" if link else ""), "link": link}


def send_howtopay_email(to_name, to_email, tier, price_text, reference, instructions, pay_url="", pay_label="") -> tuple:
    if not BREVO_API_KEY:
        return False, "Email isn't set up on this server."
    msg = build_howtopay_email(to_name, tier, price_text, reference, instructions, pay_url, pay_label)
    ok, detail = _send_simple(to_name, to_email, msg)
    print(f"{'✔ How-to-pay email sent to' if ok else '❌ How-to-pay email failed for'} {to_email}" + ("" if ok else f": {detail}"))
    return ok, detail


def send_declined_email(to_name, to_email, tier, price_text="", reference="") -> tuple:
    if not BREVO_API_KEY:
        return False, "Email isn't set up on this server."
    msg = build_declined_email(to_name, tier, price_text, reference)
    ok, detail = _send_simple(to_name, to_email, msg)
    print(f"{'✔ Declined email sent to' if ok else '❌ Declined email failed for'} {to_email}" + ("" if ok else f": {detail}"))
    return ok, detail


def send_event_reminder_email(to_name, to_email, tier, credential_id, bundle_hash, event) -> bool:
    if not BREVO_API_KEY:
        return False
    msg = build_event_reminder_email(to_name, tier, credential_id, bundle_hash, event)
    ok, detail = _send_simple(to_name, to_email, msg)
    print(f"{'✔ Event reminder sent to' if ok else '❌ Event reminder failed for'} {to_email}" + ("" if ok else f": {detail}"))
    return ok


def send_payment_alert(to_email, who_name, who_email, tier, price_text="", reference="") -> tuple:
    if not BREVO_API_KEY:
        return False, "Email isn't set up on this server."
    msg = build_alert_email(who_name, who_email, tier, price_text, reference)
    ok, detail = _post_to_brevo({
        "sender": {"name": FROM_NAME, "email": FROM_EMAIL},
        "to": [{"email": to_email}],
        "subject": msg["subject"], "htmlContent": msg["html"], "textContent": msg["text"],
    })
    print(f"{'✔ Payment alert sent to' if ok else '❌ Payment alert failed for'} {to_email}" + ("" if ok else f": {detail}"))
    return ok, detail


def build_lostlink_email(to_name, cards, overrides: dict = None, link_base=None) -> dict:
    """The "here's your link again" email. `cards` is a list of
    (tier, credential_id, bundle_hash); with several, each gets its own line."""
    _refresh_branding()
    subj_t, text_t = _tpl("lostlink", overrides, email_templates.DEFAULT_LOSTLINK_SUBJECT,
                          email_templates.DEFAULT_LOSTLINK_TEXT)
    values = {"name": to_name, "creator": CREATOR_NAME, "brand": CARD_TITLE}
    intro = _fill(text_t, values)
    cards = list(cards or [])[:5]
    links = [(t, _personal_link(cid, h, link_base)) for t, cid, h in cards]
    first = links[0][1] if links else ""
    blocks = [(t, l) for t, l in links] if len(links) > 1 else None
    rows = [("MEMBER", to_name.upper())] + ([("CARD", links[0][0])] if len(links) == 1 else [])
    html_body = _shell("Your access link", intro, rows, first, "◈ Open member area", blocks=blocks,
                       footer_note="You get this because someone asked for the link to be sent to this address.")
    plain = (f"{CREATOR_NAME.upper()} — {CARD_TITLE.upper()}\n\n{intro}\n\n"
             + "".join(f"{t}: {l}\n" for t, l in links) + f"\n{CARD_TITLE}\n")
    return {"subject": _one_line(_fill(subj_t, values)), "html": html_body, "text": plain, "link": first}


def unsubscribe_link(credential_id: str, bundle_hash: str, base=None) -> str:
    """The "stop these emails" page for one member (it asks them to confirm)."""
    base = (public_url.base_url() if base is None else base) or ""
    return f"{base.rstrip('/')}/unsubscribe?id={credential_id}&h={bundle_hash[:32]}"


def build_followup_email(step, to_name, tier, credential_id, bundle_hash, overrides: dict = None,
                         link_base=None, unsub_base=None) -> dict:
    """Follow-up email number `step` (1 to 5): the creator's own wording, a button
    to the member area, and a "stop these emails" link."""
    _refresh_branding()
    step = max(1, min(email_templates.FOLLOW_STEPS, int(step)))
    dsub, dtext = email_templates.FOLLOW_DEFAULTS[step - 1]
    subj_t, text_t = _tpl("follow%d" % step, overrides, dsub, dtext)
    values = {"name": to_name, "tier": tier, "creator": CREATOR_NAME, "brand": CARD_TITLE}
    intro = _fill(text_t, values)
    link = _personal_link(credential_id, bundle_hash, link_base)
    stop = unsubscribe_link(credential_id, bundle_hash, unsub_base)
    stop_html = (f'<div style="font-size:11px;line-height:1.6;color:#8a8176;margin-top:12px;">'
                 f'You get this because you joined {_esc(CARD_TITLE)}. '
                 f'<a href="{_esc(stop, quote=True)}" style="color:#8a8176;">Stop these emails</a></div>')
    html_body = _shell("A note from " + CREATOR_NAME, intro, [], link, "◈ Open member area", extra_html=stop_html)
    plain = (f"{CREATOR_NAME.upper()} — {CARD_TITLE.upper()}\n\n{intro}\n\n{link}\n\n"
             f"Stop these emails: {stop}\n")
    return {"subject": _one_line(_fill(subj_t, values)), "html": html_body, "text": plain,
            "link": link, "unsubscribe": stop}


def send_followup_email(step, to_name, to_email, tier, credential_id, bundle_hash) -> bool:
    if not BREVO_API_KEY:
        return False
    msg = build_followup_email(step, to_name, tier, credential_id, bundle_hash)
    payload = {
        "sender": {"name": FROM_NAME, "email": FROM_EMAIL},
        "to": [{"email": to_email, "name": to_name}],
        "subject": msg["subject"], "htmlContent": msg["html"], "textContent": msg["text"],
    }
    if msg["unsubscribe"].startswith("http"):
        payload["headers"] = {"List-Unsubscribe": f"<{msg['unsubscribe']}>",
                              "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    ok, detail = _post_to_brevo(payload)
    print(f"{'✔ Follow-up ' + str(step) + ' sent to' if ok else '❌ Follow-up ' + str(step) + ' failed for'} {to_email}"
          + ("" if ok else f": {detail}"))
    return ok


def build_ended_email(to_name, tier, overrides: dict = None) -> dict:
    """The note a member gets when the creator revokes their card."""
    _refresh_branding()
    subj_t, text_t = _tpl("ended", overrides, email_templates.DEFAULT_ENDED_SUBJECT,
                          email_templates.DEFAULT_ENDED_TEXT)
    values = {"name": to_name, "tier": tier, "creator": CREATOR_NAME, "brand": CARD_TITLE}
    intro = _fill(text_t, values)
    html_body = _shell("Access ended", intro, [("MEMBER", to_name.upper()), ("CARD", tier)], "", "")
    return {"subject": _one_line(_fill(subj_t, values)), "html": html_body,
            "text": _plain("Ended", intro, f"\nCARD: {tier}\n", ""), "link": ""}


def send_lostlink_email(to_name, to_email, cards) -> tuple:
    if not BREVO_API_KEY:
        return False, "Email isn't set up on this server."
    msg = build_lostlink_email(to_name, cards)
    ok, detail = _send_simple(to_name, to_email, msg)
    print(f"{'✔ Link email sent to' if ok else '❌ Link email failed for'} {to_email}" + ("" if ok else f": {detail}"))
    return ok, detail


def send_ended_email(to_name, to_email, tier) -> tuple:
    if not BREVO_API_KEY:
        return False, "Email isn't set up on this server."
    msg = build_ended_email(to_name, tier)
    ok, detail = _send_simple(to_name, to_email, msg)
    print(f"{'✔ Access-ended email sent to' if ok else '❌ Access-ended email failed for'} {to_email}" + ("" if ok else f": {detail}"))
    return ok, detail


def preview_kind(kind: str, tier: str, overrides: dict = None) -> dict:
    """Any editable email for a made-up member, from wording that may not be
    saved yet (what Preview shows and Send test sends). Nothing else happens."""
    _refresh_branding()
    base = MEMBERS_PAGE or "https://your-site.example/members"
    tier = tier or "MEMBER"
    sample_event = card_kinds.sample_event()
    d = dict(_SAMPLE)
    if kind == "reminder":
        return preview_reminder(tier, overrides)
    if kind == "extended":
        return preview_extended(tier, overrides)
    if kind == "ticket":
        return build_ticket_email(d["to_name"], tier, d["credential_id"], d["bundle_hash"], sample_event, overrides, base)
    if kind == "collectible":
        return build_collectible_email(d["to_name"], tier, d["credential_id"], d["bundle_hash"],
                                       card_kinds.sample_drop(), overrides, base)
    if kind == "evremind":
        return build_event_reminder_email(d["to_name"], tier, d["credential_id"], d["bundle_hash"], sample_event, overrides, base)
    cfg = _load_config()
    if kind == "howtopay":
        return build_howtopay_email(d["to_name"], tier, "9.99 USD", "A1B2C3",
                                    (cfg.get("manual_payment_instructions") or "Send 9.99 USD to you@example.com.").strip(),
                                    "https://pay.example/checkout", "Pay now", overrides)
    if kind == "declined":
        return build_declined_email(d["to_name"], tier, "9.99 USD", "A1B2C3", overrides)
    if kind == "alert":
        return build_alert_email(d["to_name"], "member@example.com", tier, "9.99 USD", "A1B2C3")
    if kind == "lostlink":
        return build_lostlink_email(d["to_name"], [(tier, d["credential_id"], d["bundle_hash"])], overrides, base)
    if kind == "ended":
        return build_ended_email(d["to_name"], tier, overrides)
    if kind.startswith("follow") and kind[6:].isdigit():
        return build_followup_email(int(kind[6:]), d["to_name"], tier, d["credential_id"], d["bundle_hash"], overrides, base,
                                    (public_url.base_url() or "https://your-site.example"))
    return preview_email(tier, overrides)


# ── Announcements ──
MAX_ANNOUNCE_SUBJECT = 150


def build_announcement_email(to_name, tier, credential_id, bundle_hash, title, text, link="",
                             link_base=None) -> dict:
    """An announcement from the creator (see announcements.py). Plain wording
    they typed, the member's own access link, an optional extra button for the
    link they added, and a line saying why they are getting it."""
    _refresh_branding()
    title = str(title or "").strip()[:150]
    text = str(text or "").strip()
    personal = _personal_link(credential_id, bundle_hash, link_base)
    subject = re.sub(r"[\r\n]+", " ", title or f"News from {CREATOR_NAME}").strip()[:MAX_ANNOUNCE_SUBJECT]
    extra_link = safe_renew_url(link)
    extra = (f'<a href="{_esc(extra_link, quote=True)}" class="btn" style="background:transparent;'
             f'border:1px solid {_esc(ACCENT_COLOR, quote=True)};color:{_esc(ACCENT_COLOR, quote=True)};">'
             f'Open the link</a>') if extra_link else ""
    why = f"You get this because you hold a {tier} card from {CREATOR_NAME}."
    html_body = _shell(title or "News", text, [], personal, "◈ Open member area",
                       extra_html=extra, footer_note=why)
    extra_text = f"\nLink: {extra_link}\n" if extra_link else ""
    plain = (f"{CREATOR_NAME.upper()} — {CARD_TITLE.upper()}\n\n"
             f"{title + chr(10) + chr(10) if title else ''}{text}\n{extra_text}\n"
             f"Your access link:\n{personal}\n\n{why}\n{CARD_TITLE}\n")
    return {"subject": subject, "html": html_body, "text": plain, "link": personal}


def send_announcement_email(to_name, to_email, tier, credential_id, bundle_hash, title, text, link="") -> tuple:
    """Returns (ok, detail)."""
    if not BREVO_API_KEY:
        return False, "Email isn't set up on this server."
    msg = build_announcement_email(to_name, tier, credential_id, bundle_hash, title, text, link)
    return _send_simple(to_name, to_email, msg)


def preview_announcement(title, text, link="", tier="MEMBER") -> dict:
    """The announcement for a made-up member (nothing is sent)."""
    _refresh_branding()
    return build_announcement_email(_SAMPLE["to_name"], tier or "MEMBER", _SAMPLE["credential_id"],
                                    _SAMPLE["bundle_hash"], title, text, link,
                                    link_base=MEMBERS_PAGE or "https://your-site.example/members")


def send_test_announcement(to_email, title, text, link="", tier="MEMBER") -> tuple:
    """Send the sample announcement to one address. Returns (ok, message)."""
    if not BREVO_API_KEY:
        return False, ("Email isn't set up on this server yet, so nothing can be sent. "
                       "Set BREVO_API_KEY and GMAIL_ADDRESS (see SETUP.md), then try again.")
    msg = preview_announcement(title, text, link, tier)
    ok, detail = _post_to_brevo({
        "sender": {"name": FROM_NAME, "email": FROM_EMAIL},
        "to": [{"email": to_email}],
        "subject": "[TEST] " + msg["subject"],
        "htmlContent": msg["html"],
        "textContent": msg["text"],
    })
    if ok:
        return True, f"Test email sent to {to_email}. Check the inbox (and spam)."
    return False, f"The email service refused it: {detail}"


def _send_simple(to_name, to_email, msg) -> tuple:
    return _post_to_brevo({
        "sender": {"name": FROM_NAME, "email": FROM_EMAIL},
        "to": [{"email": to_email, "name": to_name}],
        "subject": msg["subject"],
        "htmlContent": msg["html"],
        "textContent": msg["text"],
    })


def send_extended_email(to_name, to_email, tier, credential_id, bundle_hash, expires_at, days_added=None) -> tuple:
    """Returns (ok, detail)."""
    if not BREVO_API_KEY:
        return False, "Email isn't set up on this server."
    msg = build_extended_email(to_name, tier, credential_id, bundle_hash, expires_at, days_added)
    ok, detail = _send_simple(to_name, to_email, msg)
    print(f"{'✔ Extension email sent to' if ok else '❌ Extension email failed for'} {to_email}" + ("" if ok else f": {detail}"))
    return ok, detail


def send_reminder_email(to_name, to_email, tier, credential_id, bundle_hash, expires_at, days_left) -> bool:
    if not BREVO_API_KEY:
        return False
    msg = build_reminder_email(to_name, tier, credential_id, bundle_hash, expires_at, days_left)
    ok, detail = _send_simple(to_name, to_email, msg)
    print(f"{'✔ Reminder sent to' if ok else '❌ Reminder failed for'} {to_email}" + ("" if ok else f": {detail}"))
    return ok


def preview_extended(tier: str, overrides: dict = None) -> dict:
    """The "access extended" email for a made-up member (nothing is sent)."""
    _refresh_branding()
    d = dict(_SAMPLE)
    d["expires_at"] = "2099-12-31T00:00:00+00:00"
    return build_extended_email(tier=tier or "MEMBER", days_added=30, overrides=overrides,
                                link_base=MEMBERS_PAGE or "https://your-site.example/members", **d)


def preview_reminder(tier: str, overrides: dict = None) -> dict:
    """The reminder for a made-up member (nothing is sent)."""
    _refresh_branding()
    d = dict(_SAMPLE)
    d["expires_at"] = "2099-12-31T00:00:00+00:00"
    return build_reminder_email(tier=tier or "MEMBER", days_left=3, overrides=overrides,
                                link_base=MEMBERS_PAGE or "https://your-site.example/members", **d)


# ── Quick test (prints without sending if no key set) ──
if __name__ == "__main__":
    if not BREVO_API_KEY:
        print("Set BREVO_API_KEY (and GMAIL_ADDRESS as your verified sender) to test email sending.")
        print("Personal link would be:")
        print(f"{MEMBERS_PAGE}?id=test1234abcd5678&h=abc123def456")
    else:
        result = send_credential_email(
            to_name       = "Test Member",
            to_email      = FROM_EMAIL,
            tier          = "DEMO",
            credential_id = "test1234abcd5678",
            bundle_hash   = "abc123def456",
            bundle_path   = "",
            card_path     = "",
            expires_at    = "2026-12-31T00:00:00+00:00",
        )
        print("Result:", result)
