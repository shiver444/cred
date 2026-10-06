"""
Credential Protocol — Card Generator
Generates the distressed-keycard-style HTML membership card with an
embedded QR code. The QR encodes the card's tap-to-verify access link
(same id+hash pair as the emailed personal link), so scanning it with a
plain phone camera opens and verifies it directly.

Branding (logo, card title, creator name) is NOT hardcoded here — it's
passed in by the caller (credential_api.py), which reads it from
config.json. This file is the template's reusable engine; config.json is
where each deployment's identity lives.
"""

import json
import os
import base64
import qrcode
import qrcode.image.svg
from io import BytesIO
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent

# See credential_issuer.py — DATA_DIR is the persistent Volume mount in
# production, BASE_DIR as a local-dev fallback.
DATA_DIR  = Path(os.environ.get("DATA_DIR", str(BASE_DIR)))
CARDS_DIR = DATA_DIR / "cards"
CARDS_DIR.mkdir(parents=True, exist_ok=True)

# Drop your own logo at assets/logo.png — it's optional. If it's missing,
# the card simply renders without one (see _load_logo_data_uri below).
LOGO_PATH = BASE_DIR / "assets" / "logo.png"


def _load_logo_data_uri() -> str:
    """Load the deployment's logo as a data: URI. Falls back to no image if missing."""
    try:
        with open(LOGO_PATH, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except FileNotFoundError:
        return ""


def generate_qr_svg(data: str) -> str:
    """Generate a QR code as a plain black-on-white inline SVG.
    Kept monochrome (not tinted) so it stays reliably scannable by
    real phone cameras and jsQR — colored/inverted QRs are more prone
    to failing to decode at small display sizes."""
    factory = qrcode.image.svg.SvgPathImage
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=1,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(image_factory=factory)
    buffer = BytesIO()
    img.save(buffer)
    svg_str = buffer.getvalue().decode("utf-8")
    return svg_str


def _format_id(credential_id: str) -> str:
    """72f60c40ed8bd6ec -> 72F6-0C40-ED8B-DC6E"""
    s = credential_id.upper()
    return "-".join(s[i:i + 4] for i in range(0, len(s), 4))


def generate_card(
    credential_id: str,
    holder_name: str,
    tier: str,
    issued_at: str,
    expires_at: str,
    bundle_hash: str,
    signature_hex: str,
    sections: list = None,
    issuer_name: str = "",
    issuer_url: str = "",
    card_title: str = "YOUR BRAND HERE",
    card_subtitle: str = "Member Keycard",
    access_url: str = "",
    creator_name: str = "",
    accent_color: str = "#00e87a",
    show_barcode: bool = True,
    logo_data_uri: str = None,
) -> str:
    """
    Generate the HTML membership keycard.
    Returns the path to the saved HTML file.

    All branding (`card_title`, `creator_name`, `access_url`, `accent_color`)
    is expected to be passed in by the caller from config.json — nothing
    about a specific creator is hardcoded in this file. `issuer_name` is an
    optional extra line shown before the creator's name on the card
    (blank by default — the card shows only the creator's own brand).

    Note: `card_subtitle` is accepted for backward compatibility but is
    NOT rendered on the card. The fed reference design has a fixed
    "(MEMBER KEYCARD)" label there, not a per-tier dynamic subtitle — so
    the tag is hardcoded in the template below instead of derived from
    `tier`. Passing a different tier (e.g. via credential_api.py) still
    updates the "ACCESS CLASS" row further down; it just no longer
    overwrites this label.

    `sections` is embedded directly into the card as a hidden manifest
    (see `card_manifest_json` below), so the card file itself — not just
    the .zip bundle — can be dropped onto the cp.js widget to unlock
    access. This mirrors cp.js's existing (unsigned) trust model for the
    .zip drop path: it's a convenience container, not a cryptographic
    proof: the real signature/audit trail still lives in the .zip bundle
    (manifest.sig, chain_of_evidence.txt, the PDF certificate).

    `show_barcode` and `logo_data_uri` exist so a specific tier/pass type
    can override the deployment's global look (see the per-tier "design"
    editor in /admin/dashboard) — `logo_data_uri`, when given, is used
    as-is instead of loading LOGO_PATH from disk.
    """

    creator_name = creator_name or card_title or "MEMBER"

    sections = sections or []
    card_manifest = {
        "bundle_type":    "credential",
        "credential_id":  credential_id,
        "holder_name":    holder_name,
        "tier":           tier,
        "sections":       sections,
        "issued_at":      issued_at,
        "expires_at":     expires_at,
    }
    card_manifest_json = json.dumps(card_manifest, separators=(",", ":"))

    # The card's tap-to-verify link — same shape as the personal link cp.js
    # already reads off the page URL on load, so both a phone's native
    # camera scan and the emailed link land on the exact same verified,
    # revocation-checked path.
    access_link = f"{access_url}?id={credential_id}&h={bundle_hash[:32]}"

    # QR data: the access link itself (not a raw-JSON payload) so a plain
    # phone camera recognizes it as a link and offers to open it, instead
    # of just showing decoded text with nothing to tap. `src=qr` marks
    # scans as coming from the physical/PDF card, separate from an emailed
    # link click, in case that's ever worth telling apart later. cp.js's
    # own in-page scanner (jsQR) still reads this fine — parseToken() knows
    # how to pull id/h out of a URL, alongside the older raw-JSON shape
    # still carried by cards issued before this.
    qr_payload = f"{access_link}&src=qr"

    qr_svg = generate_qr_svg(qr_payload)
    logo_uri = logo_data_uri if logo_data_uri else _load_logo_data_uri()
    formatted_id = _format_id(credential_id)
    barcode_html = '<div class="card-barcode"></div>' if show_barcode else ''

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{card_title} — {tier} Keycard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Nosifer&family=Bebas+Neue&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    background: #050403;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    font-family: 'JetBrains Mono', monospace;
    padding: 40px 20px;
  }}

  .card {{
    position: relative;
    width: 100%;
    max-width: 380px;
    aspect-ratio: 0.76 / 1;
    border-radius: 26px;
    background:
      radial-gradient(circle at 18% 10%, rgba(255,255,255,0.05), transparent 42%),
      linear-gradient(165deg, #100b0a, #050403 60%);
    box-shadow:
      0 0 0 1px rgba(230,223,210,0.08),
      0 30px 70px rgba(0,0,0,0.65);
    overflow: hidden;
  }}

  /* film-grain texture */
  .card::before {{
    content: "";
    position: absolute;
    inset: 0;
    z-index: 1;
    opacity: 0.15;
    mix-blend-mode: overlay;
    pointer-events: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  }}

  /* faint scratches / cracks — kept subtle and pushed toward the edges */
  .card::after {{
    content: "";
    position: absolute;
    inset: 0;
    z-index: 1;
    pointer-events: none;
    background:
      linear-gradient(97deg, transparent 10%, rgba(255,255,255,0.035) 10.3%, transparent 11%),
      linear-gradient(74deg, transparent 88%, rgba(255,255,255,0.03) 88.3%, transparent 89%),
      linear-gradient(15deg, transparent 94%, rgba(255,255,255,0.035) 94.4%, transparent 95%),
      linear-gradient(150deg, transparent 4%, rgba(0,0,0,0.3) 4.6%, transparent 5.2%);
  }}

  /* worn corner vignette */
  .card-vignette {{
    position: absolute;
    inset: 0;
    z-index: 1;
    pointer-events: none;
    background: radial-gradient(ellipse at center, transparent 55%, rgba(0,0,0,0.55) 100%);
  }}

  .card-content {{
    position: relative;
    z-index: 2;
    height: 100%;
    padding: 34px 28px 24px;
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
  }}

  .card-logo {{
    width: 62%;
    max-width: 220px;
    height: auto;
    filter: contrast(1.45) brightness(1.2) drop-shadow(0 0 5px {accent_color}88);
    margin-bottom: 6px;
  }}

  .card-brand-title {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 22px;
    letter-spacing: 0.04em;
    color: #e6dfd2;
    line-height: 1.15;
  }}

  .card-kind {{
    font-size: 10px;
    letter-spacing: 0.15em;
    color: {accent_color};
    text-transform: uppercase;
    margin-top: 6px;
  }}

  .card-hr {{
    width: 100%;
    height: 1px;
    background: rgba(230,223,210,0.18);
    margin: 18px 0 14px;
  }}

  .card-meta {{
    width: 100%;
    text-align: left;
    font-size: 10.5px;
    letter-spacing: 0.04em;
    color: #a8a094;
    line-height: 1.9;
  }}

  .card-meta b {{
    color: #6b6058;
    font-weight: 400;
  }}

  .card-meta span {{
    color: #e6dfd2;
  }}

  .card-bottom-row {{
    width: 100%;
    margin-top: auto;
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 12px;
    text-align: left;
  }}

  .card-brand-block {{
    font-size: 9.5px;
    letter-spacing: 0.05em;
    color: #a8a094;
    line-height: 1.7;
  }}

  .card-brand-block .dim {{ color: #6b6058; }}

  .card-qr-link {{ display: block; line-height: 0; }}

  .card-qr-box {{
    width: 132px;
    height: 132px;
    background: #ffffff;
    border-radius: 4px;
    padding: 6px;
    display: flex;
    align-items: center;
    justify-content: center;
  }}

  .card-qr-box svg {{
    width: 100% !important;
    height: 100% !important;
  }}

  .card-barcode {{
    width: 100%;
    height: 30px;
    margin-top: 16px;
    opacity: 0.5;
    background: repeating-linear-gradient(
      90deg,
      #d8d2c4 0px, #d8d2c4 2px,
      transparent 2px, transparent 5px,
      #d8d2c4 5px, #d8d2c4 7px,
      transparent 7px, transparent 9px,
      #d8d2c4 9px, #d8d2c4 13px,
      transparent 13px, transparent 17px
    );
  }}
</style>
</head>
<body>

<div class="card">
  <div class="card-vignette"></div>
  <div class="card-content">
    <img class="card-logo" src="{logo_uri}" alt="{creator_name}">
    <div class="card-brand-title">{card_title}</div>
    <div class="card-kind">(MEMBER KEYCARD)</div>

    <div class="card-hr"></div>

    <div class="card-meta">
      <div><b>ACCESS CLASS</b> // <span>{tier}</span></div>
      <div><b>ID</b> // <span>{formatted_id}</span></div>
    </div>

    <div class="card-bottom-row">
      <div class="card-brand-block">
        <div>{(issuer_name.upper() + " // ") if issuer_name else ""}{creator_name.upper()}</div>
        <div class="dim">AUTHORIZED ACCESS</div>
      </div>
      <a class="card-qr-link" href="{access_link}" target="_blank" rel="noopener">
        <div class="card-qr-box">{qr_svg}</div>
      </a>
    </div>

    {barcode_html}
  </div>
</div>

<!-- Embedded credential — lets this card file itself be dropped onto
     the membership widget, same as the .zip bundle. Not rendered. -->
<script type="application/json" id="cp-manifest">{card_manifest_json}</script>

</body>
</html>"""

    # Save card
    card_filename = f"card_{credential_id}.html"
    card_path     = CARDS_DIR / card_filename
    with open(card_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✔ Card generated: {card_filename}")
    return str(card_path)


if __name__ == "__main__":
    from credential_issuer import issue_credential
    from credential_bundle import bundle_credential

    result = issue_credential(
        name        = "Test Member",
        email       = "test@example.com",
        tier        = "MEMBER",
        expiry_days = 31,
        sections    = ["downloads", "chat"],
    )

    bundle = bundle_credential(result)

    card_path = generate_card(
        credential_id = result["credential_id"],
        holder_name   = result["entry"]["holder_name"],
        tier          = result["entry"]["tier"],
        issued_at     = result["entry"]["issued_at"],
        expires_at    = result["entry"]["expires_at"],
        bundle_hash   = bundle["bundle_hash"],
        signature_hex = result["entry"]["signature_hex"],
        sections      = result["entry"]["sections"],
        card_title    = "YOUR BRAND HERE",
        card_subtitle = "Member Keycard",
        access_url    = "https://example.com/members.html",
        creator_name  = "Your Creator Name",
        accent_color  = "#00e87a",
    )

    print(f"\nCard saved: {card_path}")
    print("Open it in a browser to preview.")
