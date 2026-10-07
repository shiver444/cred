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

import config_store

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
MEMBERS_PAGE  = os.environ.get("MEMBERS_PAGE", _cfg.get("members_page", ""))

BREVO_URL = "https://api.brevo.com/v3/smtp/email"

# The wording a creator can change in the dashboard. {name}, {tier},
# {creator}, {brand} and {expires} are filled in per member.
DEFAULT_SUBJECT = "Your Access Card — {name}"
DEFAULT_INTRO   = ("{name} — your credential has been issued and signed.\n"
                   "Your card and bundle are attached to this email.")
PLACEHOLDERS    = ("name", "tier", "creator", "brand", "expires")
MAX_SUBJECT, MAX_INTRO, MAX_SIGNOFF = 150, 1000, 600


def _fill(text: str, values: dict) -> str:
    """Replace {name}-style placeholders. Only the five known ones are
    touched (no str.format), so stray braces in a creator's text are safe."""
    return re.sub(r"\{(%s)\}" % "|".join(PLACEHOLDERS),
                  lambda m: str(values.get(m.group(1), "")), text or "")


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
    MEMBERS_PAGE = os.environ.get("MEMBERS_PAGE", cfg.get("members_page", ""))


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

    expires = (expires_at or "")[:10]
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
    <span class="row-label">VALID UNTIL</span>
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
VALID UNTIL: {expires}
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
) -> bool:
    """
    Send the credential welcome email via Brevo's HTTP API.
    Attaches the card HTML and bundle ZIP.
    Includes personal access link.
    Returns True on success.
    """
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


def send_test_email(to_email: str, tier: str, overrides: dict = None) -> tuple:
    """Send the sample email to one address (no attachments). Returns
    (ok, message for the creator)."""
    if not BREVO_API_KEY:
        return False, ("Email isn't set up on this server yet, so nothing can be sent. "
                       "Set BREVO_API_KEY and GMAIL_ADDRESS (see SETUP.md), then try again.")
    msg = preview_email(tier, overrides)
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
