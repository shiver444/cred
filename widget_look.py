"""
The member widget's look (dashboard -> "Widget look").

Everything here is plain checking of what the creator typed, so a bad value
can never reach the public /config answer (and from there the visitor's page):

  widget_theme    match (default: copy the colors of the page it sits on),
                  dark, light, or custom (the two colors below)
  widget_font     page (default: the page's own font) or keycard (the card's
                  Bebas Neue / JetBrains Mono look)
  widget_corners  square (default) or rounded
  widget_bg       background color for "custom"  (#rrggbb)
  widget_text     text color for "custom"        (#rrggbb)
  widget_*_text   the wording of six texts; blank = the built-in wording
  widget_terms_url / widget_privacy_url
                  optional links (http/https only). When either is set the sign-up
                  box shows "By getting a card you agree to the Terms and Privacy
                  Policy." under the form, with those words as links.

cp.js checks the same values again on its side, because the dashboard's live
preview hands it unsaved ones.
"""

THEMES  = ("match", "dark", "light", "custom")
FONTS   = ("page", "keycard")
CORNERS = ("square", "rounded")

DEFAULT_THEME, DEFAULT_FONT, DEFAULT_CORNERS = "match", "page", "square"
DEFAULT_BG, DEFAULT_TEXT = "#121214", "#ecebe8"

# key -> (longest allowed, built-in wording shown as the dashboard hint)
TEXTS = {
    "widget_banner_text":   (80,  "Get your card — click here"),
    "widget_drop_title":    (60,  "Insert card here"),
    "widget_drop_sub":      (100, "drop your card file · or click to browse"),
    "widget_signup_title":  (60,  "Get your card"),
    "widget_signup_sub":    (200, "Pick a tier, enter your name and email.\nYour card arrives instantly."),
    "widget_button_text":   (40,  "Send my card"),
}

URLS = ("widget_terms_url", "widget_privacy_url")
MAX_URL = 300

KEYS = ("widget_theme", "widget_font", "widget_corners", "widget_bg", "widget_text") + tuple(TEXTS) + URLS


def clean_url(value):
    """An http(s) address, or "" (no javascript:, data:, spaces or markup)."""
    import re
    v = str(value or "").strip()[:MAX_URL]
    return v if re.match(r"^https?://[^\s<>\"']+$", v, re.I) else ""


def clean_choice(value, allowed, default):
    v = str(value or "").strip().lower()
    return v if v in allowed else default


def clean_hex(value, default):
    """#rrggbb (a #rgb shorthand is expanded); anything else -> `default`."""
    v = str(value or "").strip().lower()
    if len(v) == 4 and v[0] == "#" and all(c in "0123456789abcdef" for c in v[1:]):
        v = "#" + "".join(c * 2 for c in v[1:])
    if len(v) == 7 and v[0] == "#" and all(c in "0123456789abcdef" for c in v[1:]):
        return v
    return default


def clean_text(value, max_len):
    """Plain text, trimmed and cut to length; line breaks kept (as \\n) only
    where they are wanted. No HTML is ever interpreted — cp.js escapes it."""
    v = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    v = "".join(ch for ch in v if ch == "\n" or ch >= " ")   # drop control characters
    return v.strip()[:max_len]


def from_values(get) -> dict:
    """Clean settings from any `get(key)` lookup (a form, or saved config)."""
    out = {
        "widget_theme":   clean_choice(get("widget_theme"),   THEMES,  DEFAULT_THEME),
        "widget_font":    clean_choice(get("widget_font"),    FONTS,   DEFAULT_FONT),
        "widget_corners": clean_choice(get("widget_corners"), CORNERS, DEFAULT_CORNERS),
        "widget_bg":      clean_hex(get("widget_bg"),   DEFAULT_BG),
        "widget_text":    clean_hex(get("widget_text"), DEFAULT_TEXT),
    }
    for key, (max_len, _default) in TEXTS.items():
        out[key] = clean_text(get(key), max_len)
    for key in URLS:
        out[key] = clean_url(get(key))
    return out


def from_config(cfg: dict) -> dict:
    return from_values(lambda k: (cfg or {}).get(k))


def from_form(form) -> dict:
    return from_values(lambda k: form.get(k))
