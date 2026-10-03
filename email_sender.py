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

Branding (creator name, card title, accent color, members page) is read
from config.json at import time — see _load_config() below. Fill in
config.json before deploying; see SETUP.md.
"""

import base64
import json
import os
import requests
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_config() -> dict:
    try:
        with open(BASE_DIR / "config.json") as f:
            return json.load(f)
    except Exception:
        return {}


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

    personal_link = (
        f"{MEMBERS_PAGE}"
        f"?id={credential_id}"
        f"&h={bundle_hash[:32]}"
    )

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
    color: {ACCENT_COLOR};
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
    color: {ACCENT_COLOR};
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
    background: {ACCENT_COLOR};
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
    color: {ACCENT_COLOR};
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

  <div class="header">{CREATOR_NAME.upper()}</div>
  <div class="sub">{CARD_TITLE} — Member Access</div>

  <hr class="line">

  <div class="label">Welcome</div>
  <div class="value">
    {to_name} — your credential has been issued and signed.<br>
    Your card and bundle are attached to this email.
  </div>

  <div class="row">
    <span class="row-label">MEMBER</span>
    <span class="row-val">{to_name.upper()}</span>
  </div>
  <div class="row">
    <span class="row-label">ACCESS CLASS</span>
    <span class="row-val">{tier}</span>
  </div>
  <div class="row">
    <span class="row-label">CREDENTIAL ID</span>
    <span class="row-val">{credential_id[:16].upper()}</span>
  </div>
  <div class="row">
    <span class="row-label">VALID UNTIL</span>
    <span class="row-val">{expires_at[:10]}</span>
  </div>
  <div class="row">
    <span class="row-label">ISSUED BY</span>
    <span class="row-val">{CREATOR_NAME.upper()} / CRITHLABS</span>
  </div>

  <hr class="line">

  <div class="label">Your personal access link</div>
  <a href="{personal_link}" class="access-btn">◈ Get Access</a>

  <div style="font-size:9px;color:#6b6058;letter-spacing:1px;word-break:break-all;margin-top:-12px;">
    {personal_link}
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

  <hr class="line">

  <div class="footer">
    CrithLabs Credential Protocol<br>
    Your credential is cryptographically signed with ECDSA.<br>
    Keep your card and bundle safe — they are your access key.<br>
    crithlabs.com
  </div>

</div>
</body>
</html>"""

    # ── Plain text fallback ──
    plain_body = f"""
{CREATOR_NAME.upper()} — {CARD_TITLE.upper()} MEMBER ACCESS
======================================

Welcome, {to_name}.

Your credential has been issued.

MEMBER:      {to_name.upper()}
TIER:        {tier}
ID:          {credential_id[:16].upper()}
VALID UNTIL: {expires_at[:10]}
ISSUED BY:   {CREATOR_NAME.upper()} / CRITHLABS

YOUR PERSONAL ACCESS LINK (this is what gets you in):
{personal_link}

Your member card (HTML) and credential bundle (ZIP) are also attached —
a signed keepsake and a signed backup copy, for your records.

Keep your access link somewhere safe.

CrithLabs Credential Protocol
crithlabs.com
"""

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
            "subject": f"Your Access Card — {to_name}",
            "htmlContent": html_body,
            "textContent": plain_body,
        }
        if attachments:
            payload["attachment"] = attachments

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
            print(f"✔ Email sent to {to_email}")
            return True
        else:
            print(f"❌ Email failed: Brevo {resp.status_code} — {resp.text}")
            return False

    except Exception as e:
        print(f"❌ Email failed: {e}")
        return False


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
