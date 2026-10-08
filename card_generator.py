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
from html import escape as _esc

import re

from logo_utils import is_logo_data_uri

# The built-in card styles. They all share one layout; only the look changes.
STYLES = ("distressed", "clean", "holographic", "minimal", "ticket", "gradient", "neon")
# How much a background picture is darkened so the card's text stays readable.
DIM_ALPHA = {"none": 0.0, "soft": 0.25, "medium": 0.45, "strong": 0.65}
QR_STYLES = ("solid", "blend", "off")
DEFAULT_DIM = "medium"

BASE_DIR = Path(__file__).resolve().parent

# See credential_issuer.py — DATA_DIR is the persistent Volume mount in
# production, BASE_DIR as a local-dev fallback.
DATA_DIR  = Path(os.environ.get("DATA_DIR", str(BASE_DIR)))
CARDS_DIR = DATA_DIR / "cards"
CARDS_DIR.mkdir(parents=True, exist_ok=True)

# The logo normally comes from the dashboard (Branding → Card logo, or a
# tier's own logo). assets/logo.png is only a last-resort fallback for
# someone running the code by hand; with neither, the card renders without
# a logo (see _load_logo_data_uri below).
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
    card_label: str = "",
    card_style: str = "distressed",
    background_data_uri: str = None,
    background_dim: str = DEFAULT_DIM,
    qr_style: str = "solid",
    kind: str = "pass",
    event: dict = None,
    save: bool = True,
) -> str:
    """
    Generate the HTML membership keycard.
    Returns the path to the saved HTML file — or, with `save=False` (dashboard
    previews), the card's HTML itself, written nowhere.

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

    `card_label` is the small "(MEMBER KEYCARD)" line under the title
    (blank = "Member Keycard"). `card_style` is "distressed" (the default
    worn-keycard look: film grain, scratches, vignette) or "clean" (the
    same card, smooth and unworn).

    `background_data_uri` (optional) is the creator's own picture shown behind
    the card's text; `background_dim` ("none", "soft", "medium", "strong")
    darkens it so the text stays readable. See card_looks.py for the saved
    "looks" these values come from.

    `kind` is "pass" (the membership card) or "ticket". A ticket shows the
    event's details (`event`: name, when, place, note) in place of the plain
    "access class" row, reads "Event Ticket" under the title and "Admit one"
    at the bottom, and leaves out the barcode line to make room. The look
    (style, colors, picture) is chosen separately, exactly as for a pass.

    `show_barcode` and `logo_data_uri` exist so a specific tier/pass type
    can override the deployment's global look (see the per-tier "design"
    editor in /admin/dashboard) — `logo_data_uri`, when given, is used
    as-is instead of loading LOGO_PATH from disk.
    """

    creator_name = creator_name or card_title or "MEMBER"
    card_style   = card_style if card_style in STYLES else "distressed"
    # The accent goes straight into the card's CSS, so only a plain color
    # (#abc, #aabbcc, #aabbccdd or a color name) is accepted.
    if not re.fullmatch(r"#[0-9a-fA-F]{3,8}|[A-Za-z]{3,20}", (accent_color or "").strip()):
        accent_color = "#00e87a"
    accent_color = accent_color.strip()
    is_ticket    = kind == "ticket"
    event        = event if (is_ticket and isinstance(event, dict)) else {}
    label_text   = "Event Ticket" if is_ticket else ((card_label or "").strip()[:40] or "Member Keycard")

    sections = sections or []
    card_manifest = {
        "bundle_type":    "credential",
        "credential_id":  credential_id,
        "holder_name":    holder_name,
        "tier":           tier,
        "sections":       sections,
        "issued_at":      issued_at,
        "expires_at":     expires_at,
        **({"kind": "ticket"} if is_ticket else {}),
    }
    # Goes inside a <script> block: "<" is written as \u003c so a name like
    # "</script><script>…" can never close the block (JSON.parse reads it back
    # as the same text).
    card_manifest_json = json.dumps(card_manifest, separators=(",", ":")).replace("<", "\\u003c")

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
    logo_uri = logo_data_uri if is_logo_data_uri(logo_data_uri) else _load_logo_data_uri()
    formatted_id = _format_id(credential_id)

    # Everything typed by a person is escaped before it goes into the page.
    e_title   = _esc(card_title)
    e_tier    = _esc(tier)
    e_creator = _esc(creator_name)
    e_issuer  = _esc(issuer_name.upper()) if issuer_name else ""
    e_label   = _esc(label_text.upper())
    e_link    = _esc(access_link, quote=True)
    accent_color = _esc(accent_color, quote=True)
    logo_html = f'<img class="card-logo" src="{_esc(logo_uri, quote=True)}" alt="{_esc(creator_name, quote=True)}">' if logo_uri else ""
    barcode_html = '<div class="card-barcode"></div>' if (show_barcode and not is_ticket) else ''
    has_bg = is_logo_data_uri(background_data_uri)
    dim = DIM_ALPHA.get(background_dim, DIM_ALPHA[DEFAULT_DIM])
    bg_html = (f'<img class="card-bg" src="{_esc(background_data_uri, quote=True)}" alt="">'
               f'<div class="card-scrim" style="background:rgba(0,0,0,{dim})"></div>') if has_bg else ""
    qr_style = qr_style if qr_style in QR_STYLES else "solid"
    card_classes = ("card" + (f" card--{card_style}" if card_style != "distressed" else "") + (" card--has-bg" if has_bg else "")
                    + (" card--is-ticket" if is_ticket else "")
                    + ("" if qr_style == "solid" else f" card--qr-{qr_style}"))

    if is_ticket:
        def _row(label, value, cls=""):
            return f'      <div{(" class=" + chr(34) + cls + chr(34)) if cls else ""}><b>{label}</b> // <span>{_esc(value)}</span></div>'
        rows = []
        if event.get("name"):  rows.append(_row("EVENT", event["name"], "ev-name"))
        if event.get("when"):  rows.append(_row("WHEN", event["when"]))
        if event.get("place"): rows.append(_row("WHERE", event["place"]))
        if event.get("note"):  rows.append(_row("NOTE", event["note"]))
        rows.append(_row("ADMIT", tier))
        if holder_name:        rows.append(_row("NAME", holder_name))
        rows.append(f'      <div><b>ID</b> // <span>{formatted_id}</span></div>')
        meta_rows = "\n".join(rows)
    else:
        meta_rows = (f'      <div><b>ACCESS CLASS</b> // <span>{e_tier}</span></div>\n'
                     f'      <div><b>ID</b> // <span>{formatted_id}</span></div>')

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{e_title} — {e_tier} Keycard</title>
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

  /* QR code: "solid" is the white box above. "blend" drops the white box and draws the
     code as see-through light squares on a very faint dark patch (the patch is
     what keeps it readable over busy pictures; tested with a decoder). "off" hides it; the link stays in the
     page so a dropped card file still works. */
  .card--qr-off .card-qr-link {{ display: none; }}
  .card--qr-blend .card-qr-box {{ background: rgba(0, 0, 0, 0.3) !important; box-shadow: none !important; }}
  .card--qr-blend .card-qr-box svg path {{ fill: #ffffff; fill-opacity: 0.6; }}
  .card--minimal:not(.card--has-bg).card--qr-blend .card-qr-box svg path {{ fill: #000000; fill-opacity: 0.45; }}

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

  /* "clean" style: same layout, smooth and unworn */
  .card--clean {{
    background: linear-gradient(165deg, #15100e, #070605 70%);
  }}
  .card--clean::before, .card--clean::after, .card--clean .card-vignette {{ display: none; }}
  .card--clean .card-logo {{ filter: none; }}

  /* The creator's own picture behind the card, darkened for readability. */
  .card-bg {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; z-index: 0; }}
  .card-scrim {{ position: absolute; inset: 0; z-index: 0; pointer-events: none; }}
  /* Over a picture the small grey text needs more contrast. */
  .card--has-bg .card-content {{ text-shadow: 0 1px 3px rgba(0,0,0,0.65); }}
  .card--has-bg .card-meta {{ color: #e6dfd2; }}
  .card--has-bg .card-meta b {{ color: #cfc7ba; }}
  .card--has-bg .card-brand-block {{ color: #e6dfd2; }}
  .card--has-bg .card-brand-block .dim {{ color: #cfc7ba; }}
  .card--has-bg .card-qr-box {{ text-shadow: none; }}

  /* ── More built-in styles. Same layout, different look. ── */

  /* holographic: dark glass with a rainbow sheen */
  .card--holographic {{
    background: linear-gradient(135deg, #14131f, #08080f 62%);
    box-shadow: 0 0 0 1px rgba(255,255,255,0.14), 0 30px 70px rgba(0,0,0,0.65), 0 0 46px {accent_color}33;
  }}
  .card--holographic::before {{ display: none; }}
  .card--holographic::after {{
    background:
      linear-gradient(115deg, transparent 18%, rgba(255,0,200,0.20) 34%, rgba(0,225,255,0.22) 50%, rgba(255,235,0,0.17) 66%, transparent 82%);
    mix-blend-mode: screen;
  }}
  .card--holographic .card-vignette {{ display: none; }}
  .card--holographic .card-logo {{ filter: drop-shadow(0 0 8px rgba(255,255,255,0.25)); }}
  .card--holographic .card-hr {{ background: linear-gradient(90deg, #ff00c8aa, #00e1ffaa, #ffeb00aa); height: 2px; }}

  /* minimal: light paper, thin lines */
  .card--minimal:not(.card--has-bg) {{ background: #f5f2eb; box-shadow: 0 0 0 1px rgba(0,0,0,0.10), 0 30px 70px rgba(0,0,0,0.5); }}
  .card--minimal::before, .card--minimal::after, .card--minimal .card-vignette {{ display: none; }}
  .card--minimal .card-logo {{ filter: none; }}
  .card--minimal:not(.card--has-bg) .card-brand-title {{ color: #1d1b18; }}
  .card--minimal:not(.card--has-bg) .card-kind {{ color: #5b564e; }}
  .card--minimal:not(.card--has-bg) .card-hr {{ background: rgba(0,0,0,0.16); }}
  .card--minimal:not(.card--has-bg) .card-meta {{ color: #6b655c; }}
  .card--minimal:not(.card--has-bg) .card-meta b {{ color: #9a9388; }}
  .card--minimal:not(.card--has-bg) .card-meta span {{ color: #1d1b18; }}
  .card--minimal:not(.card--has-bg) .card-brand-block {{ color: #6b655c; }}
  .card--minimal:not(.card--has-bg) .card-brand-block .dim {{ color: #9a9388; }}
  .card--minimal:not(.card--has-bg) .card-qr-box {{ box-shadow: 0 0 0 1px rgba(0,0,0,0.18); }}
  .card--minimal:not(.card--has-bg) .card-barcode {{ opacity: 0.8; background: repeating-linear-gradient(90deg, #1d1b18 0px, #1d1b18 2px, transparent 2px, transparent 5px, #1d1b18 5px, #1d1b18 7px, transparent 7px, transparent 9px, #1d1b18 9px, #1d1b18 13px, transparent 13px, transparent 17px); }}
  .card--minimal.card--has-bg .card-kind {{ color: #fff; }}

  /* ticket: notches at the sides, a dashed tear line, an accent stripe */
  .card--ticket {{
    background: linear-gradient(165deg, #17120f, #080605 70%);
    box-shadow: inset 7px 0 0 {accent_color};
    -webkit-mask-image: radial-gradient(circle at 0 60%, transparent 15px, #000 16px), radial-gradient(circle at 100% 60%, transparent 15px, #000 16px);
    -webkit-mask-composite: source-in;
    mask-image: radial-gradient(circle at 0 60%, transparent 15px, #000 16px), radial-gradient(circle at 100% 60%, transparent 15px, #000 16px);
    mask-composite: intersect;
  }}
  .card--ticket::before, .card--ticket::after, .card--ticket .card-vignette {{ display: none; }}
  .card--ticket .card-logo {{ filter: none; }}
  .card--ticket .card-hr {{ height: 0; background: none; border-top: 2px dashed rgba(230,223,210,0.35); }}
  .card--ticket .card-barcode {{ opacity: 0.85; }}

  /* gradient: a darkened wash of your accent color */
  .card--gradient {{
    background: linear-gradient(160deg, #1b1b1b, #0b0a0f 80%);
    background: linear-gradient(160deg, color-mix(in srgb, {accent_color} 58%, #000) 0%, color-mix(in srgb, {accent_color} 16%, #000) 52%, #0a090d 100%);
    box-shadow: 0 0 0 1px rgba(255,255,255,0.10), 0 30px 70px rgba(0,0,0,0.6);
  }}
  .card--gradient::before, .card--gradient::after, .card--gradient .card-vignette {{ display: none; }}
  .card--gradient .card-logo {{ filter: none; }}
  .card--gradient .card-brand-title {{ color: #fff; }}
  .card--gradient .card-kind {{ color: rgba(255,255,255,0.88); }}

  /* neon: near-black with a glowing accent outline */
  .card--neon {{
    background: #04050a;
    box-shadow: 0 0 0 2px {accent_color}, 0 0 26px {accent_color}99, inset 0 0 34px {accent_color}2b, 0 30px 70px rgba(0,0,0,0.7);
  }}
  .card--neon::before, .card--neon::after, .card--neon .card-vignette {{ display: none; }}
  .card--neon .card-logo {{ filter: drop-shadow(0 0 7px {accent_color}); }}
  .card--neon .card-brand-title {{ text-shadow: 0 0 10px {accent_color}cc; }}
  .card--neon .card-kind {{ text-shadow: 0 0 8px {accent_color}; }}
  .card--neon .card-hr {{ background: {accent_color}; box-shadow: 0 0 8px {accent_color}; }}
  .card--neon .card-qr-box {{ box-shadow: 0 0 0 2px {accent_color}, 0 0 14px {accent_color}aa; }}
  .card--neon .card-barcode {{ opacity: 0.9; background: repeating-linear-gradient(90deg, {accent_color} 0px, {accent_color} 2px, transparent 2px, transparent 5px, {accent_color} 5px, {accent_color} 7px, transparent 7px, transparent 9px, {accent_color} 9px, {accent_color} 13px, transparent 13px, transparent 17px); }}
  /* event tickets: more rows, so each value stays on one line (the event name may use two) */
  .card--is-ticket .card-meta {{ font-size: 11.5px; line-height: 1.6; }}
  .card--is-ticket .card-meta > div {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .card--is-ticket .card-meta > div.ev-name {{ white-space: normal; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }}
  .card--is-ticket .card-hr {{ margin: 14px 0 10px; }}

</style>
</head>
<body>

<div class="{card_classes}">
  {bg_html}
  <div class="card-vignette"></div>
  <div class="card-content">
    {logo_html}
    <div class="card-brand-title">{e_title}</div>
    <div class="card-kind">({e_label})</div>

    <div class="card-hr"></div>

    <div class="card-meta">
{meta_rows}
    </div>

    <div class="card-bottom-row">
      <div class="card-brand-block">
        <div>{(e_issuer + " // ") if e_issuer else ""}{_esc(creator_name.upper())}</div>
        <div class="dim">{"ADMIT ONE" if is_ticket else "AUTHORIZED ACCESS"}</div>
      </div>
      <a class="card-qr-link" href="{e_link}" target="_blank" rel="noopener">
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

    if not save:
        return html

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
