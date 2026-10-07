"""
Dashboard styles: how the admin pages (dashboard, Members, Content, login)
look. One setting, `admin_style` in config.json, chosen on the dashboard:

  spaceship  the original look: near-black, typewriter lettering, small caps
  daylight   clean and light, friendly sans-serif, rounded cards (new default)
  studio     warm ivory paper, serif headings, thin lines: quiet and editorial
  midnight   modern dark blue-grey, readable sans-serif, soft depth

The pages are written once, using color variables (--bg, --fg, --line ...).
`css()` returns the <style> text that gives those variables their values for
the chosen style, plus the few rules that change shape (fonts, corners,
spacing). Spaceship only sets the variables, with exactly the colors the
pages always used, so it looks as it always did.

The creator's accent color is theirs and is kept in every style; for text and
outlines it is nudged just enough to stay readable on the style's background.
"""

STYLES = ("spaceship", "daylight", "studio", "midnight")
DEFAULT_STYLE = "spaceship"      # a deployment that never chose one keeps today's look
NEW_DEPLOYMENT_STYLE = "daylight"  # what the template's own config.json starts with

LABELS = {
    "spaceship": ("Spaceship", "Near-black, typewriter lettering, small capitals. The original look."),
    "daylight":  ("Daylight",  "Clean and light with friendly lettering and rounded cards. Easiest to read."),
    "studio":    ("Studio",    "Warm ivory paper with elegant serif headings and thin lines."),
    "midnight":  ("Midnight",  "Modern dark blue-grey with readable lettering and soft depth."),
}

_SANS  = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
_SERIF = "'Iowan Old Style', 'Palatino Linotype', Palatino, Georgia, 'Times New Roman', serif"
_MONO  = "'Courier New', monospace"

# Every variable the pages use. `page` is the colour behind the page "card".
_PALETTES = {
    "spaceship": dict(
        page="#0a0908", bg="#0a0908", fg="#e6dfd2", soft="#a8a094", muted="#6b6058",
        line="#3a1210", line2="#5a4a42", dash="#2a1a18", panel="#13100f", field="#1a100e", hover="#1a100e",
        ok="#5fd98a", ok_bg="#13371f", warn="#f0c674", warn_bg="#3a2a10", bad="#e8232b", frame="#050403",
        font=_MONO, head=_MONO, radius="0px", radius_lg="0px", shadow="none", min_contrast=3.0),
    "daylight": dict(
        page="#eef1f6", bg="#ffffff", fg="#1d2330", soft="#4a5468", muted="#5f697b",
        line="#dde2ea", line2="#b9c1cf", dash="#e6eaf0", panel="#f6f8fb", field="#ffffff", hover="#f2f5f9",
        ok="#16703c", ok_bg="#e1f4e8", warn="#7d5200", warn_bg="#fff1cf", bad="#c0262d", frame="#ffffff",
        font=_SANS, head=_SANS, radius="8px", radius_lg="16px",
        shadow="0 1px 2px rgba(20,30,50,.06), 0 8px 30px rgba(20,30,50,.08)", min_contrast=4.5),
    "studio": dict(
        page="#e8e1d3", bg="#faf7f0", fg="#2b2620", soft="#554c40", muted="#6c6354",
        line="#d9d1bf", line2="#b7ac95", dash="#e5ddcb", panel="#f2ede1", field="#fffdf8", hover="#f2ede1",
        ok="#2c6a3c", ok_bg="#e3eedb", warn="#765000", warn_bg="#f5e6bd", bad="#a3271e", frame="#ffffff",
        font=_SANS, head=_SERIF, radius="2px", radius_lg="3px",
        shadow="0 1px 0 rgba(60,45,20,.06), 0 10px 34px rgba(60,45,20,.10)", min_contrast=4.5),
    "midnight": dict(
        page="#0d1016", bg="#151a23", fg="#e6e9ef", soft="#aab2c1", muted="#8c95a6",
        line="#283041", line2="#3b465c", dash="#222a39", panel="#1b2230", field="#0f131b", hover="#1b2230",
        ok="#5fd98a", ok_bg="#12301f", warn="#f0c674", warn_bg="#33290f", bad="#ff7676", frame="#0b0e14",
        font=_SANS, head=_SANS, radius="9px", radius_lg="16px",
        shadow="0 1px 2px rgba(0,0,0,.4), 0 14px 40px rgba(0,0,0,.45)", min_contrast=4.5),
}


def clean_style(value, default=DEFAULT_STYLE):
    v = str(value or "").strip().lower()
    return v if v in STYLES else default


# ── colour maths: keep the accent readable as text on the chosen background ──
def _rgb(h):
    h = str(h or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (0, 232, 122)


def _hex(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in c)


def _lum(c):
    def f(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def contrast(a, b):
    x, y = _lum(a), _lum(b)
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


def _mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def accent_text(accent, bg, min_contrast):
    """The accent, pushed toward black (light page) or white (dark page) until
    it reads on `bg` (one color, or a list of surfaces it may sit on). Unchanged
    if it already does."""
    a = _rgb(accent)
    surfaces = [_rgb(x) for x in (bg if isinstance(bg, (list, tuple)) else [bg])]
    b = surfaces[0]
    target = (0, 0, 0) if _lum(b) > 0.4 else (255, 255, 255)
    for i in range(21):
        c = _mix(a, target, i * 0.05)
        if all(contrast(c, s) >= min_contrast for s in surfaces):
            return _hex(c)
    return _hex(target)


def on_accent(accent):
    """Text color that reads on a filled accent button."""
    a = _rgb(accent)
    return "#0a0908" if contrast(a, (10, 9, 8)) >= contrast(a, (255, 255, 255)) else "#ffffff"


def _safe_accent(accent):
    h = str(accent or "").strip()
    ok = len(h) in (4, 7) and h[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in h[1:])
    return h if ok else "#00e87a"


# ── the shape rules shared by the three modern styles ──
_MODERN = """
html { background:var(--page); }
body { font-family:var(--font); }
h1, h2 { font-family:var(--head); text-transform:none !important; letter-spacing:0 !important; }
h1 { font-size:26px !important; font-weight:600; margin:0 0 6px; }
h2 { font-size:18px !important; font-weight:600; margin:42px 0 14px !important; padding-bottom:10px !important; }
td, input, select, textarea { font-size:14px !important; }
input, select, textarea { border-radius:var(--radius); padding:9px 12px !important; }
input[type=color] { padding:2px !important; border-radius:var(--radius); }
input[type=file] { padding:7px 10px !important; }
input:focus, select:focus, textarea:focus { outline:2px solid color-mix(in srgb, var(--accent-text) 38%, transparent); outline-offset:0; border-color:var(--accent-text); }
label, .issue-grid label { font-size:12.5px !important; font-weight:600; text-transform:none !important; letter-spacing:0 !important; color:var(--soft); }
th { font-size:12px !important; font-weight:600; text-transform:none !important; letter-spacing:0 !important; }
.hint, .count, .small, .placeholder, .no-logo, .upmsg, .empty, .msg, .chk-row, .warn, .banner, .chip { font-size:13px !important; line-height:1.6; }
.hint, .count { color:var(--muted); }
.msg, .banner { text-transform:none !important; letter-spacing:0 !important; }
.nav { font-size:13px !important; letter-spacing:0 !important; margin-bottom:22px !important; display:flex; flex-wrap:wrap; gap:8px; }
.nav a { margin-right:0 !important; padding:6px 14px; border-radius:999px; background:var(--panel); border:1px solid var(--line); color:var(--fg) !important; text-decoration:none !important; }
.nav a:hover { border-color:var(--accent-text); color:var(--accent-text) !important; }
button, .btn, .save-btn, .add-tier, .copy-btn, .bk-btn, .revoke-btn, .copy-link-btn, .delete-btn, .extend-btn, .issue-submit,
.approve-req-btn, .reject-req-btn, .preview-btn, .design-toggle, .remove-logo, .remove-tier, .mini, .small {
  font-family:var(--font) !important; font-size:13px !important; letter-spacing:0 !important; text-transform:none !important;
  border-radius:var(--radius) !important; }
.save-btn, .add-tier, .copy-btn, .bk-btn, .btn, .preview-btn, .approve-req-btn, .reject-req-btn { padding:10px 18px !important; font-weight:600; }
.revoke-btn, .copy-link-btn, .delete-btn, .extend-btn, .issue-submit { padding:6px 12px !important; font-weight:600; }
.checklist, .sec, .issue-box, .design-panel, .tiers, .embed-code, .placeholder, .chip, .warn, .banner { border-radius:var(--radius); }
.placeholder { background:var(--panel); border-left:3px solid var(--line2) !important; }
.checklist summary, .issue-box summary, .bk-restore summary { text-transform:none !important; letter-spacing:0 !important; font-size:14px !important; font-weight:600; }
.badge { text-transform:none !important; letter-spacing:0 !important; border-radius:999px; }
.preview-frame, .wl-frame { border-radius:var(--radius); }
.logo-thumb { border-radius:6px; }
table { border-collapse:separate; border-spacing:0; }
@media (max-width:700px) { table { display:block; max-width:100%; overflow-x:auto; } }
"""

_MODERN_PAGE = """
body { box-sizing:border-box; background:var(--bg) !important; border:1px solid var(--line); border-radius:var(--radius-lg);
       box-shadow:var(--shadow); margin:28px auto !important; padding:40px 44px !important; }
@media (max-width:700px) { body { margin:0 !important; border-radius:0; padding:22px 18px !important; } }
"""

_MODERN_LOGIN = """
body { background:var(--page) !important; }
.box { background:var(--bg); border:1px solid var(--line); border-radius:var(--radius-lg); box-shadow:var(--shadow);
       max-width:360px !important; padding:36px !important; }
h1 { font-size:20px !important; margin-bottom:22px; }
input { margin-bottom:14px; box-sizing:border-box; width:100%; }
button { padding:12px !important; border-radius:var(--radius); font-size:14px !important; font-weight:600; letter-spacing:0 !important; text-transform:none !important; }
"""

# Studio: small capitals on labels and section titles, for the editorial feel.
_STUDIO_EXTRA = """
h2 { border-bottom-color:var(--line2) !important; }
label, .issue-grid label, th { text-transform:uppercase !important; letter-spacing:.09em !important; font-size:11px !important; font-weight:600; }
h1 { font-weight:500; font-size:30px !important; }
h2 { font-weight:500; font-size:21px !important; }
.nav a { border-radius:2px; }
"""


def css(style, accent, kind="page"):
    """Text for a page's <style> element, to go AFTER the page's own rules.
    kind: "page" (dashboard/content), "wide" (members table) or "login"."""
    style = clean_style(style)
    p = _PALETTES[style]
    accent = _safe_accent(accent)
    text = accent_text(accent, [p["bg"], p["panel"], p["hover"]], p["min_contrast"])
    v = {
        "page": p["page"], "bg": p["bg"], "fg": p["fg"], "soft": p["soft"], "muted": p["muted"],
        "line": p["line"], "line-strong": p["line2"], "dash": p["dash"], "panel": p["panel"], "field": p["field"],
        "hover": p["hover"], "ok": p["ok"], "ok-bg": p["ok_bg"], "warn": p["warn"], "warn-bg": p["warn_bg"],
        "bad": p["bad"], "frame-bg": p["frame"], "font": p["font"], "head": p["head"],
        "radius": p["radius"], "radius-lg": p["radius_lg"], "shadow": p["shadow"],
        "accent": accent, "accent-text": text, "on-accent": on_accent(accent),
    }
    out = ":root { " + " ".join("--%s:%s;" % (k, val) for k, val in v.items()) + " color-scheme:%s; }\n" % (
        "dark" if _lum(_rgb(p["bg"])) < 0.4 else "light")
    if style == "spaceship":
        return out
    if kind == "login":
        return out + _MODERN + _MODERN_LOGIN + (_STUDIO_EXTRA if style == "studio" else "")
    extra = ""
    if kind == "wide":
        extra = "body { max-width:1200px; } td, th { padding:11px 12px !important; } th { border-bottom:1px solid var(--line); }\n"
    return out + _MODERN + _MODERN_PAGE + extra + (_STUDIO_EXTRA if style == "studio" else "")


def swatch(style):
    """Four colors that sum up a style, for the little preview on the picker."""
    p = _PALETTES[clean_style(style)]
    return (p["page"], p["bg"], p["panel"], p["fg"])
