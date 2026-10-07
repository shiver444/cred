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

# Layout is part of the style: how the pages are arranged, not just colored.
#   long  one long page, as it always was (Spaceship)
#   toc   the same long page, with a small contents list beside it (Studio)
#   app   screens: a sidebar on a computer, a tab bar and a Settings list on a
#         phone, one settings screen at a time, a save bar (Daylight, Midnight)
LAYOUTS = {"spaceship": "long", "studio": "toc", "daylight": "app", "midnight": "app"}

# The dashboard's settings screens, in the order they are listed: (id, title, one line).
# Each id matches a <section id="sec-<id>"> on the dashboard page.
SETTINGS_SCREENS = [
    ("branding", "Branding & cards", "Name, accent color, logo and card style"),
    ("widget",   "Widget look",      "Colors, lettering and wording of the member widget"),
    ("tiers",    "Tiers & pricing",  "Passes, prices, limits and card designs"),
    ("payment",  "Payment",          "How paid tiers are fulfilled"),
    ("emails",   "Emails",           "Welcome email and expiry reminder"),
    ("style",    "Dashboard style",  "How these admin pages look"),
    ("backup",   "Backup & restore", "Download or restore your data"),
]
SETTINGS_IDS = tuple(s[0] for s in SETTINGS_SCREENS)


def layout(style):
    return LAYOUTS[clean_style(style)]


def body_attrs(style, page, brand=""):
    """Attributes for the <body> tag: tells the shell script which layout and
    page this is. `brand` is shown in the sidebar."""
    from html import escape
    return 'data-layout="%s" data-page="%s" data-brand="%s"' % (layout(style), escape(page, quote=True), escape(str(brand or ""), quote=True))


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



_ICONS = {
    "home": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v9.5h13V10"/><path d="M10 19.5v-5h4v5"/></svg>',
    "members": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.6 3.2-5.5 6.5-5.5s5.9 1.9 6.5 5.5"/><path d="M16 4.7a3.5 3.5 0 0 1 0 6.6"/><path d="M18 14.8c2 .6 3.2 2.3 3.5 5.2"/></svg>',
    "content": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/></svg>',
    "settings": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>',
}

_TOC_CSS = """
.toc { display:none; }
@media (min-width:1300px) {
  .toc { display:block; position:fixed; top:96px; left:calc(50% + 478px); width:168px; font-family:var(--font); font-size:12.5px; }
  .toc a { display:block; padding:5px 0 5px 12px; color:var(--muted); text-decoration:none; border-left:2px solid var(--line); line-height:1.4; }
  .toc a:hover { color:var(--fg); }
  .toc a.on { color:var(--accent-text); border-left-color:var(--accent-text); font-weight:600; }
}
"""

_APP_CSS = """
:root { --side-w:248px; }
body[data-layout=app].app-ready { max-width:none !important; margin:0 !important; padding:0 !important; border:0 !important; border-radius:0 !important;
  box-shadow:none !important; background:var(--page) !important; min-height:100vh; }
.app-ready .nav { display:none !important; }
.app-ready .dsec { display:none; }
.app-ready .dsec.on { display:block; background:var(--bg); border:1px solid var(--line); border-radius:var(--radius-lg); padding:6px 30px 30px; box-shadow:var(--shadow); }
.app-ready .dsec > h2:first-child, .app-ready .dsec > .backup-box > h2:first-child { display:none; }
.app-ready .dsec.on > :first-child { margin-top:22px; }
.app-ready .backup-box { border:0 !important; background:none !important; padding:0 !important; margin:0 !important; }
.app-ready .save-btn, .app-ready h2:empty { display:none; }
.app-ready h1.orig-title { display:none; }
.app-main { box-sizing:border-box; margin-left:var(--side-w); padding:36px 44px 90px; max-width:calc(var(--side-w) + 960px); }
.app-main.plain { max-width:none; }
.app-main.plain > .app-card { overflow-x:auto; background:var(--bg); border:1px solid var(--line); border-radius:var(--radius-lg); padding:26px 30px 34px; box-shadow:var(--shadow); }
.app-main.plain > .app-card > h1 { margin-top:0; }
.app-title { font-family:var(--head); font-size:30px !important; font-weight:700; margin:0 0 20px !important; letter-spacing:-.01em; color:var(--fg); }
.app-back { display:none; align-items:center; gap:2px; margin:0 0 6px -6px; padding:6px 8px; color:var(--accent-text); text-decoration:none; font-size:16px; font-weight:500; }
.app-back svg { width:20px; height:20px; }
.app-side { position:fixed; top:0; bottom:0; left:0; width:var(--side-w); box-sizing:border-box; padding:22px 14px 18px; background:var(--bg);
  border-right:1px solid var(--line); overflow:auto; display:flex; flex-direction:column; gap:2px; z-index:20; font-family:var(--font); }
.app-brand { font-family:var(--head); font-weight:700; font-size:17px; padding:4px 12px 20px; color:var(--fg); line-height:1.25; word-break:break-word; }
.app-side a { display:flex; align-items:center; gap:11px; padding:9px 12px; border-radius:var(--radius); color:var(--soft); text-decoration:none; font-size:14px; }
.app-side a svg { width:19px; height:19px; flex:0 0 19px; }
.app-side a:hover { background:var(--hover); color:var(--fg); }
.app-side a.on { background:color-mix(in srgb, var(--accent-text) 13%, transparent); color:var(--accent-text); font-weight:600; }
.app-side .app-grp { font-size:11px; font-weight:600; color:var(--muted); padding:18px 12px 6px; text-transform:uppercase; letter-spacing:.07em; }
.app-side a.sub { padding-left:42px; font-size:13.5px; }
.app-side .sp { flex:1; }
.app-tabs { display:none; position:fixed; left:0; right:0; bottom:0; z-index:40; background:color-mix(in srgb, var(--bg) 94%, transparent);
  -webkit-backdrop-filter:blur(14px); backdrop-filter:blur(14px); border-top:1px solid var(--line); padding:6px 6px calc(6px + env(safe-area-inset-bottom)); font-family:var(--font); }
.app-tabs a { flex:1; display:flex; flex-direction:column; align-items:center; gap:3px; font-size:11px; color:var(--muted); text-decoration:none; padding:6px 0; border-radius:12px; }
.app-tabs a svg { width:25px; height:25px; }
.app-tabs a.on { color:var(--accent-text); font-weight:600; }
.app-list { display:none; }
.app-list .grp { background:var(--bg); border:1px solid var(--line); border-radius:var(--radius-lg); overflow:hidden; margin:0 0 18px; box-shadow:var(--shadow); }
.app-list a { display:flex; align-items:center; gap:12px; padding:14px 16px; border-bottom:1px solid var(--line); color:var(--fg); text-decoration:none; }
.app-list a:last-child { border-bottom:0; }
.app-list a:active { background:var(--hover); }
.app-list .t { display:block; font-size:15px; font-weight:600; }
.app-list .s { display:block; font-size:12.5px; color:var(--muted); margin-top:2px; line-height:1.4; }
.app-list a::after { content:"\\203A"; margin-left:auto; color:var(--muted); font-size:24px; line-height:1; }
.app-savebar { display:none; position:fixed; left:var(--side-w); right:0; bottom:0; z-index:50; align-items:center; justify-content:space-between; gap:14px;
  padding:12px 28px; background:var(--bg); border-top:1px solid var(--line); box-shadow:0 -10px 30px rgba(0,0,0,.10); font-family:var(--font); font-size:14px; color:var(--soft); }
.app-savebar.show { display:flex; }
.app-savebar button { background:var(--accent); color:var(--on-accent); border:0; border-radius:var(--radius); padding:10px 22px; font-size:14px; font-weight:600; cursor:pointer; font-family:var(--font); }
@media (max-width:899px) {
  :root { --side-w:0px; }
  .app-side { display:none; }
  .app-tabs { display:flex; }
  .app-main { padding:18px 14px calc(110px + env(safe-area-inset-bottom)); max-width:none; }
  .app-title { font-size:30px !important; margin-bottom:14px !important; }
  .view-s .app-back { display:inline-flex; }
  .view-list .app-list { display:block; }
  .app-ready .dsec.on { padding:2px 16px 22px; box-shadow:none; }
  .app-main.plain > .app-card { padding:18px 16px 26px; box-shadow:none; }
  .app-savebar { left:0; right:0; bottom:calc(66px + env(safe-area-inset-bottom)); padding:10px 14px; }
}
"""

# The script that builds the shell (sidebar, tab bar, Settings list, save bar,
# contents list). It only rearranges the page that is already there: every
# form field stays in the one form, so saving works exactly as before.
_SHELL_JS = r"""
(function () {
  var body = document.body;
  var layout = body.getAttribute('data-layout') || 'long', page = body.getAttribute('data-page') || '';
  if (layout !== 'app' && layout !== 'toc') return;
  var SETTINGS = __SETTINGS__, ICONS = __ICONS__;
  function el(tag, props, kids) {
    var n = document.createElement(tag);
    Object.keys(props || {}).forEach(function (k) {
      if (k === 'text') n.textContent = props[k]; else if (k === 'html') n.innerHTML = props[k];
      else if (k === 'class') n.className = props[k]; else n.setAttribute(k, props[k]);
    });
    (kids || []).forEach(function (c) { if (c) n.appendChild(c); });
    return n;
  }
  var secs = [].slice.call(document.querySelectorAll('.dsec'));
  function secOf(id) { return document.getElementById('sec-' + id); }

  if (layout === 'toc') {
    if (!secs.length) return;
    var toc = el('nav', { class: 'toc', 'aria-label': 'Sections' });
    secs.forEach(function (s) { toc.appendChild(el('a', { href: '#' + s.id, text: s.getAttribute('data-title') || s.id })); });
    body.appendChild(toc);
    var links = [].slice.call(toc.querySelectorAll('a'));
    function spy() {
      var cur = 0;
      secs.forEach(function (s, i) { if (s.getBoundingClientRect().top < 140) cur = i; });
      links.forEach(function (a, i) { a.classList.toggle('on', i === cur); });
    }
    window.addEventListener('scroll', spy, { passive: true }); spy();
    return;
  }

  // ── app layout ──
  var brand = body.getAttribute('data-brand') || '';
  var kids = [].slice.call(body.childNodes).filter(function (n) {
    return !(n.nodeType === 1 && /^(SCRIPT|TEMPLATE|STYLE|NOSCRIPT)$/.test(n.tagName)) && !(n.nodeType === 3 && !n.textContent.trim());
  });
  var main = el('main', { class: 'app-main' + (secs.length ? '' : ' plain') });
  var holder = secs.length ? main : el('div', { class: 'app-card' });
  if (!secs.length) main.appendChild(holder);
  body.insertBefore(main, body.firstChild);
  kids.forEach(function (n) { holder.appendChild(n); });
  var origH1 = holder.querySelector('h1');
  if (secs.length && origH1) origH1.className += ' orig-title';

  function a(href, icon, label, cls) { return el('a', { href: href, class: cls || '', html: (icon ? ICONS[icon] : '') + '<span></span>' }, []); }
  function link(href, icon, label, cls) { var n = a(href, icon, label, cls); n.querySelector('span').textContent = label; return n; }
  var side = el('aside', { class: 'app-side' });
  side.appendChild(el('div', { class: 'app-brand', text: brand }));
  var sideItems = {};
  sideItems.home = link('/admin/dashboard#/home', 'home', 'Home'); side.appendChild(sideItems.home);
  sideItems.members = link('/admin/members', 'members', 'Members'); side.appendChild(sideItems.members);
  sideItems.content = link('/admin/content', 'content', 'Content'); side.appendChild(sideItems.content);
  side.appendChild(el('div', { class: 'app-grp', text: 'Settings' }));
  SETTINGS.forEach(function (s) { sideItems[s[0]] = link('/admin/dashboard#/s/' + s[0], null, s[1], 'sub'); side.appendChild(sideItems[s[0]]); });
  side.appendChild(el('div', { class: 'sp' }));
  side.appendChild(link('/admin/logout', null, 'Log out'));
  body.appendChild(side);

  var tabs = el('nav', { class: 'app-tabs', 'aria-label': 'Main' });
  var tabItems = {};
  [['home', 'home', 'Home', '/admin/dashboard#/home'], ['members', 'members', 'Members', '/admin/members'],
   ['content', 'content', 'Content', '/admin/content'], ['settings', 'settings', 'Settings', '/admin/dashboard#/settings']].forEach(function (t) {
    tabItems[t[0]] = link(t[3], t[1], t[2]); tabs.appendChild(tabItems[t[0]]);
  });
  body.appendChild(tabs);

  if (page === 'members') { sideItems.members.className += ' on'; tabItems.members.className += ' on'; }
  if (page === 'content') { sideItems.content.className += ' on'; tabItems.content.className += ' on'; }
  body.className += ' app-ready';
  if (page !== 'dashboard' || !secs.length) return;

  // dashboard: one screen at a time
  var title = el('h1', { class: 'app-title' });
  var back = el('a', { class: 'app-back', href: '/admin/dashboard#/settings', html: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 5l-7 7 7 7"/></svg><span>Settings</span>' });
  var list = el('div', { class: 'app-list' });
  var grp = el('div', { class: 'grp' });
  SETTINGS.forEach(function (s) { grp.appendChild(el('a', { href: '#/s/' + s[0] }, [el('span', {}, [el('span', { class: 't', text: s[1] }), el('span', { class: 's', text: s[2] })])])); });
  list.appendChild(grp);
  var first = main.firstChild;
  // the "Saved." banners stay on top, then back link, title, list
  var banners = [].slice.call(main.querySelectorAll(':scope > .banner'));
  var anchor = banners.length ? banners[banners.length - 1].nextSibling : main.firstChild;
  main.insertBefore(back, anchor); main.insertBefore(title, anchor); main.insertBefore(list, anchor);

  var form = document.querySelector('form[action="/admin/dashboard"]');
  var secField = null;
  if (form) { secField = el('input', { type: 'hidden', name: 'sec', value: '' }); form.appendChild(secField); }
  var bar = el('div', { class: 'app-savebar' }, [el('span', { text: 'You have unsaved changes.' }), el('button', { type: 'button', text: 'Save changes' })]);
  body.appendChild(bar);
  var dirty = false, view = 'home', firstRoute = true;
  bar.querySelector('button').addEventListener('click', function () { if (form.requestSubmit) form.requestSubmit(); else form.submit(); });
  if (form) {
    var mark = function () { dirty = true; paint(); };
    form.addEventListener('input', mark); form.addEventListener('change', mark);
    // a field the browser refuses to submit (e.g. a number out of range) may sit on a screen that is hidden: go there
    form.addEventListener('invalid', function (e) { var s = e.target.closest && e.target.closest('.dsec'); if (s && !s.classList.contains('on')) location.hash = '#/s/' + s.id.replace(/^sec-/, ''); }, true);
    form.addEventListener('submit', function () { dirty = false; });
  }
  var isWide = function () { return window.matchMedia('(min-width: 900px)').matches; };
  function paint() { bar.classList.toggle('show', dirty && view === 's'); }
  function titleOf(id) { var s = SETTINGS.filter(function (x) { return x[0] === id; })[0]; return s ? s[1] : id; }
  function route() {
    var h = location.hash || '';
    if (h === '#backup') h = '#/s/backup';
    var m = h.match(/^#\/s\/([a-z0-9-]+)$/), id = m && secOf(m[1]) ? m[1] : null, v = 'home';
    if (id) v = 's';
    else if (h === '#/settings') { if (isWide()) { v = 's'; id = SETTINGS[0][0]; } else v = 'list'; }
    view = v;
    secs.forEach(function (s) { s.classList.toggle('on', (v === 'home' && s.id === 'sec-home') || (v === 's' && s.id === 'sec-' + id)); });
    body.classList.toggle('view-home', v === 'home'); body.classList.toggle('view-list', v === 'list'); body.classList.toggle('view-s', v === 's');
    title.textContent = v === 'home' ? 'Home' : v === 'list' ? 'Settings' : titleOf(id);
    Object.keys(sideItems).forEach(function (k) { sideItems[k].classList.toggle('on', v === 'home' ? k === 'home' : v === 's' ? k === id : (k === 'branding' && false)); });
    sideItems.members.classList.remove('on'); sideItems.content.classList.remove('on');
    tabItems.home.classList.toggle('on', v === 'home'); tabItems.settings.classList.toggle('on', v !== 'home');
    if (secField) secField.value = v === 's' ? id : '';
    if (!firstRoute) { banners.forEach(function (b) { b.style.display = 'none'; }); window.scrollTo(0, 0); }
    firstRoute = false; paint();
  }
  window.addEventListener('hashchange', route);
  window.addEventListener('resize', function () { if (location.hash === '#/settings') route(); });
  route();
})();
"""


def shell_js(style):
    """The <script> that builds the layout (empty for the plain long layout)."""
    if layout(style) == "long":
        return ""
    import json
    js = _SHELL_JS.replace("__SETTINGS__", json.dumps([list(s) for s in SETTINGS_SCREENS])).replace("__ICONS__", json.dumps(_ICONS))
    return "<script>" + js.replace("</", "<\\/") + "</script>"


def css(style, accent, kind="page"):
    """Text for a page's <style> element, to go AFTER the page's own rules.
    kind: "page" (dashboard/content), "wide" (members table) or "login"."""
    style = clean_style(style)
    p = _PALETTES[style]
    accent = _safe_accent(accent)
    text = accent_text(accent, [p["bg"], p["panel"], p["hover"], p["page"]], p["min_contrast"])
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
    lay = layout(style)
    if kind == "login":
        return out + _MODERN + _MODERN_LOGIN + (_STUDIO_EXTRA if style == "studio" else "")
    extra = ""
    if kind == "wide":
        extra = "body { max-width:1200px; } td, th { padding:11px 12px !important; } th { border-bottom:1px solid var(--line); }\n"
    shell = _APP_CSS if lay == "app" else (_TOC_CSS if lay == "toc" else "")
    return out + _MODERN + _MODERN_PAGE + extra + (_STUDIO_EXTRA if style == "studio" else "") + shell


def swatch(style):
    """Four colors that sum up a style, for the little preview on the picker."""
    p = _PALETTES[clean_style(style)]
    return (p["page"], p["bg"], p["panel"], p["fg"])
