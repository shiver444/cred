"""
Credential Protocol: how the emails look.

Every email shares one page style (a colored background, a header with the
creator's name, small labels, one button). This module holds the choices:

  dark   the original look: near-black page, monospaced type (the default)
  light  white page, plain sans-serif type
  paper  warm off-white page, serif type
  bold   white page, a big header band in the accent color
  match  "Match my website": colors and type kept from the creator's own site
         (read once with site_reader.py, editable, saved as plain values)

Settings (all optional; nothing saved = the dark look, exactly as before):

  email_look    dark | light | paper | bold | match
  email_bg      page color for "match"            (#rrggbb)
  email_text    text color for "match"            (#rrggbb)
  email_accent  button / heading color for "match" (#rrggbb; blank = the accent color from Branding)
  email_font    mono | sans | serif for "match"
  email_logo    1 = show the logo from Branding at the top (needs a public address)
  email_site    the creator's website address (only used to read its colors)

Everything is checked here, so a bad value can never reach an email's CSS.
The emails read the look through resolve(); a preview or test hands in values
that are not saved yet through override().
"""

import re
import threading
from contextlib import contextmanager

LOOKS = ("dark", "light", "paper", "bold", "match")
DEFAULT_LOOK = "dark"
FONTS = ("mono", "sans", "serif")
FONT_STACKS = {
    "mono":  "'Courier New',monospace",
    "sans":  "Helvetica,Arial,sans-serif",
    "serif": "Georgia,'Times New Roman',serif",
}
LOOK_NAMES = {
    "dark": "Dark", "light": "Light and clean", "paper": "Paper", "bold": "Bold", "match": "Match my website",
}
KEYS = ("email_look", "email_bg", "email_text", "email_accent", "email_font", "email_logo", "email_site")

DEFAULT_ACCENT = "#00e87a"
MAX_URL = 300

_HEX = re.compile(r"^#?([0-9a-f]{3}|[0-9a-f]{6})$", re.I)


# ── colors ──
def clean_hex(value, default=""):
    """#rrggbb (a #rgb shorthand is expanded), or `default`."""
    m = _HEX.match(str(value or "").strip())
    if not m:
        return default
    h = m.group(1).lower()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h


def _rgb(hexcolor):
    h = clean_hex(hexcolor, "#000000")[1:]
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(r, g, b):
    return "#%02x%02x%02x" % (max(0, min(255, round(r))), max(0, min(255, round(g))), max(0, min(255, round(b))))


def luminance(hexcolor):
    def ch(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(hexcolor)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def blend(a, b, t):
    """`t` of the way from color a to color b."""
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return _hex(ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t)


def readable_on(color, bg, minimum=3.0):
    """`color`, darkened or lightened (toward the opposite of the page) until it
    can be read on `bg`. A neon green is fine on black but would vanish on white."""
    if contrast(color, bg) >= minimum:
        return color
    target = "#000000" if luminance(bg) > 0.4 else "#ffffff"
    for step in range(1, 21):
        c = blend(color, target, step / 20.0)
        if contrast(c, bg) >= minimum:
            return c
    return target


def text_on(bg):
    """Black or white, whichever reads better on `bg` (a button's lettering)."""
    return "#0a0908" if contrast("#0a0908", bg) >= contrast("#ffffff", bg) else "#ffffff"


# ── the choices ──
def clean_look(value):
    v = str(value or "").strip().lower()
    return v if v in LOOKS else DEFAULT_LOOK


def clean_font(value, default="sans"):
    v = str(value or "").strip().lower()
    return v if v in FONTS else default


def clean_url(value):
    """An http(s) address with no spaces or markup, or ""."""
    v = str(value or "").strip()[:MAX_URL]
    return v if re.match(r"^https?://[^\s<>\"']+$", v, re.I) else ""


def clean_flag(value):
    return "1" if str(value).strip().lower() in ("1", "true", "yes", "on") else "0"


def clean_settings(data, saved=None):
    """The email-look settings from a dashboard form (or a JSON request),
    cleaned. A field that was not sent keeps its saved value, so a save from a
    page without this box cannot wipe anything."""
    saved = saved or {}
    get = data.get if hasattr(data, "get") else (lambda k, d=None: d)
    out = {}
    for key in KEYS:
        sent = get(key, None)
        raw = saved.get(key, "") if sent is None else sent
        if key == "email_look":
            out[key] = clean_look(raw)
        elif key in ("email_bg", "email_text", "email_accent"):
            out[key] = clean_hex(raw, "")
        elif key == "email_font":
            out[key] = clean_font(raw, "sans")
        elif key == "email_logo":
            out[key] = clean_flag(raw)
        elif key == "email_site":
            out[key] = clean_url(raw)
    # A checkbox that is not ticked is not sent at all: if the look box was
    # sent (email_look present) then a missing email_logo means "off".
    if get("email_look", None) is not None and get("email_logo", None) is None:
        out["email_logo"] = "0"
    return out


def values_for(cfg):
    """The settings with their defaults, as plain strings (for the screen)."""
    c = clean_settings({}, cfg or {})
    c.setdefault("email_look", DEFAULT_LOOK)
    return c


# ── the look itself ──
class Look(dict):
    """The tokens one email is drawn with (a dict with attribute access)."""
    __getattr__ = dict.get


def _preset(name, accent):
    if name == "dark":
        return dict(bg="#0a0908", text="#e6dfd2", muted="#6b6058", line="#3a1210", row="#1a100e", foot="#3a1210",
                    accent=accent, on_accent="#0a0908", font="mono", tech=True, band=False)
    if name == "light":
        bg, text = "#ffffff", "#1f2328"
        a = readable_on(accent, bg)
        return dict(bg=bg, text=text, muted="#6b7280", line="#e5e7eb", row="#eef0f2", foot="#9ca3af",
                    accent=a, on_accent=text_on(a), font="sans", tech=False, band=False)
    if name == "paper":
        bg, text = "#f6f1e7", "#2b2620"
        a = readable_on(accent, bg)
        return dict(bg=bg, text=text, muted="#7a6f60", line="#d9cfbd", row="#e8dfce", foot="#9a8f7e",
                    accent=a, on_accent=text_on(a), font="serif", tech=False, band=False)
    # bold
    bg, text = "#ffffff", "#111827"
    return dict(bg=bg, text=text, muted="#6b7280", line="#e5e7eb", row="#eef0f2", foot="#9ca3af",
                accent=accent, on_accent=text_on(accent), font="sans", tech=True, band=True)


def resolve(cfg, accent_color=None):
    """The Look for the saved settings in `cfg`. `accent_color` is the accent
    from Branding (the default heading and button color)."""
    cfg = cfg or {}
    s = values_for(cfg)
    brand = clean_hex(accent_color or cfg.get("accent_color"), DEFAULT_ACCENT)
    name = s["email_look"]
    if name != "match":
        t = _preset(name, brand)
    else:
        bg = s["email_bg"] or "#ffffff"
        text = s["email_text"] or text_on(bg)
        if contrast(text, bg) < 4.5:
            text = text_on(bg)
        accent = s["email_accent"] or brand
        accent = readable_on(accent, bg)
        t = dict(bg=bg, text=text, muted=blend(text, bg, 0.45), line=blend(text, bg, 0.82), row=blend(text, bg, 0.9),
                 foot=blend(text, bg, 0.55), accent=accent, on_accent=text_on(accent), font=s["email_font"],
                 tech=False, band=False)
    t["ink"] = readable_on(t["accent"], t["bg"])     # the accent as lettering on the page color
    t["name"] = name
    t["logo"] = s["email_logo"] == "1"
    return Look(t)


_local = threading.local()


@contextmanager
def override(look):
    """Draw the emails inside this block with `look` (a preview or a test that
    uses settings that are not saved yet)."""
    old = getattr(_local, "look", None)
    _local.look = look
    try:
        yield
    finally:
        _local.look = old


def overridden():
    return getattr(_local, "look", None)


def css(look, welcome=False):
    """The <style> rules shared by every email, for one Look. `welcome` adds the
    few rules only the welcome email uses."""
    L = look
    stack = FONT_STACKS.get(L.font, FONT_STACKS["sans"])
    tech = "text-transform:uppercase;" if L.tech else ""
    sp_head = "letter-spacing:6px;" if L.tech else "letter-spacing:.5px;"
    sp_small = "letter-spacing:3px;" if L.tech else "letter-spacing:.6px;"
    head_size = 28 if L.tech else 24
    band = (f"background:{L.accent}; color:{L.on_accent}; padding:18px 22px; margin-bottom:6px;"
            if L.band else f"color:{L.ink};")
    btn_sp = "letter-spacing:3px;" if L.tech else "letter-spacing:1px;"
    radius = "" if L.tech else "border-radius:6px;"
    rules = f"""
  body {{ background:{L.bg}; color:{L.text}; font-family:{stack}; margin:0; padding:0; }}
  .wrap {{ max-width:560px; margin:0 auto; padding:48px 32px; }}
  .header {{ font-size:{head_size}px; {sp_head} {band} {tech} margin-bottom:4px; }}
  .sub {{ font-size:9px; {sp_small} color:{L.muted}; text-transform:uppercase; margin-bottom:40px; }}
  .line {{ border:none; border-top:1px solid {L.line}; margin:28px 0; }}
  .label {{ font-size:8px; {sp_small} color:{L.ink}; text-transform:uppercase; margin-bottom:6px; }}
  .value {{ font-size:12px; color:{L.text}; margin-bottom:20px;{"" if welcome else " line-height:1.7;"} }}
  .btn {{ display:inline-block; background:{L.accent}; color:{L.on_accent}; font-size:11px; {btn_sp}
          text-transform:uppercase; padding:14px 28px; text-decoration:none; margin:8px 10px 8px 0; {radius} }}
  .row {{ display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid {L.row}; font-size:10px; }}
  .row-label {{ color:{L.muted}; }} .row-val {{ color:{L.text}; }}
  .footer {{ font-size:8px; color:{L.foot}; letter-spacing:1px; text-transform:uppercase; margin-top:40px; line-height:2; }}"""
    if welcome:
        rules += f"""
  .access-btn {{ display:inline-block; background:{L.accent}; color:{L.on_accent}; font-family:{stack}; font-size:11px; {btn_sp}
          text-transform:uppercase; padding:14px 28px; text-decoration:none; margin:24px 0; {radius} }}
  .warning {{ font-size:10px; color:{L.ink}; letter-spacing:1px; text-transform:uppercase; border-left:2px solid {L.line};
          padding:10px 14px; margin-top:28px; line-height:1.8; }}"""
    return rules


def logo_html(look, base_url, version, creator):
    """The logo image at the top, or "" (off, or no public address to host it)."""
    if not (look and look.logo and base_url and version):
        return ""
    import html as _h
    src = _h.escape(f"{base_url.rstrip('/')}/email-logo?v={version}", quote=True)
    return (f'<img src="{src}" alt="{_h.escape(creator or "", quote=True)}" '
            f'style="display:block;max-height:56px;max-width:220px;margin:0 0 18px;border:0;">')
