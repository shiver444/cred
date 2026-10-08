"""
Credential Protocol — API Server
Flask HTTP server handling:
  POST /issue       — issue a FREE-tier credential directly
  POST /checkout    — start a paid-tier purchase. Free tiers issue
                       instantly; paid tiers route through whichever
                       `payment_provider` config.json names — "manual"
                       (default: an admin-approval queue, no payment
                       account needed, works in any country) or "stripe"
                       (automatic card checkout, needs STRIPE_SECRET_KEY), or
                       "custom" (the member is sent to any payment link you
                       enter; you approve once the money arrives).
  POST /webhook/stripe — Stripe calls this on payment completion. Only
                       relevant when payment_provider is "stripe".
  POST /admin/payment-requests/<id>/approve, /reject — admin decides a
                       pending manual payment request; approve issues the
                       credential the same way the Stripe webhook does.
  POST /verify      — verify a credential
  POST /revoke      — revoke a credential
  GET  /status      — health check and stats
  GET  /revocation-list — serve the revocation list
  GET  /admin/login, /admin/logout — session-based admin login
  GET  /admin/dashboard — edit branding/tiers/pricing/payment provider
                       (config.json) through a UI
  GET  /admin/members   — view/revoke issued credentials

Run locally: python credential_api.py

This is the generic template — all creator branding (name, card title,
accent color, members page URL) is read from config.json at request time
via load_config() below, never hardcoded. Payment is the same way: Stripe
is just one plugin behind a small provider interface, not a hardcoded
dependency — see "Adding a new payment provider" in SETUP.md to wire in
PayPal, a regional processor, or anything else. See SETUP.md before
deploying.
"""

from flask import Flask, request, jsonify, session, redirect, make_response
from flask_cors import CORS
from pathlib import Path
from datetime import datetime, timezone, timedelta
from html import escape as esc_html
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import threading
import time
from urllib.parse import quote as _q

# On Railway, a service with a Volume attached automatically gets
# RAILWAY_VOLUME_MOUNT_PATH (e.g. "/data"). If DATA_DIR wasn't set by hand,
# use that — so a deployment with a Volume stores everything on it without
# anyone having to remember a second setting. Must run before the imports
# below: every module reads DATA_DIR once, at import time.
if not os.environ.get("DATA_DIR") and os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"):
    os.environ["DATA_DIR"] = os.environ["RAILWAY_VOLUME_MOUNT_PATH"]

try:
    import stripe
except ImportError:
    stripe = None  # payments simply stay disabled — see check_payments_configured()

# Importing this at startup (not lazily, inside a route) guarantees the
# signing keypair exists — generated automatically on first boot if
# missing — before this app serves a single request, not just after the
# first /issue call. See credential_issuer.py's _ensure_keypair().
import credential_issuer  # noqa: F401

# Live settings (branding, tiers, ...) are stored on the persistent Volume,
# not next to the code, so a redeploy doesn't reset them. See config_store.py.
import config_store
import content_store
import content_page
import email_sender
import backup
import announcements
import card_kinds
import card_looks
import public_url
import limits
import logo_utils
import looks_page
import member_registry
import reminders
import security
import widget_look
import custom_payment
import admin_theme

app = Flask(__name__)
CORS(app)  # allow requests from your own domain

BASE_DIR = Path(__file__).resolve().parent

# DATA_DIR points at a persistent Railway Volume in production (set via the
# DATA_DIR env var) so revocation_list.json survives redeploys — must match
# what credential_verifier.py reads from. Falls back to BASE_DIR locally.
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR)))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# No default value here on purpose — a template with a guessable fallback
# secret (e.g. "changeme") is how a creator ends up deployed with an admin
# endpoint anyone can hit. Unset ADMIN_SECRET just means /revoke, the admin
# login, and /admin/members refuse everything until it's set. See SETUP.md.
# It's also the admin login password — there's no separate password field.
ADMIN_SECRET = os.environ.get("ADMIN_SECRET")

# Signs the session cookie. Falls back to a random key generated at process
# start if unset — admin sessions just won't survive a restart/redeploy
# (you'll need to log in again), which is a fine default but worth setting
# explicitly in production so logins persist across deploys. See SETUP.md.
_session_secret = os.environ.get("SESSION_SECRET_KEY")
if not _session_secret:
    _session_secret = secrets.token_hex(32)
    print("⚠ SESSION_SECRET_KEY not set — using a random key for this process. "
          "Admin sessions will not survive a restart. See SETUP.md.")
app.secret_key = _session_secret
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=12)
# On Railway the site is always https, so the login cookie is marked
# "secure" (never sent over plain http). Locally (http) it stays off.
if (os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PUBLIC_DOMAIN")
        or os.environ.get("SESSION_COOKIE_SECURE") == "1"):
    app.config["SESSION_COOKIE_SECURE"] = True

# Uploaded members-only files (Content page). One file may be this big;
# the Railway Volume's own size is the real ceiling, so set MAX_UPLOAD_MB
# to suit it. See SETUP.md.
try:
    MAX_UPLOAD_MB = max(1, int(os.environ.get("MAX_UPLOAD_MB", "100")))
except ValueError:
    MAX_UPLOAD_MB = 100
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
FILE_TOKEN_TTL   = 15 * 60     # seconds a member's download link stays valid

# Largest backup zip that "Restore from a backup" accepts (a backup that
# includes uploaded files can be big). See SETUP.md.
try:
    MAX_RESTORE_MB = max(10, int(os.environ.get("MAX_RESTORE_MB", "1024")))
except ValueError:
    MAX_RESTORE_MB = 1024
MAX_RESTORE_BYTES = MAX_RESTORE_MB * 1024 * 1024

@app.before_request
def _limit_request_size():
    """Cap how much any request may send, per route. Nothing used to be
    capped, and a JSON endpoint reads its whole body into memory. Only the
    upload route takes big bodies; the dashboard form can carry a few logos."""
    path = request.path
    if path == "/admin/content/upload":
        request.max_content_length = MAX_UPLOAD_BYTES + 1024 * 1024
    elif path == "/admin/content/preview":
        request.max_content_length = content_store.MAX_PREVIEW_UPLOAD + 1024 * 1024
    elif path == "/admin/backup/restore":
        request.max_content_length = MAX_RESTORE_BYTES + 1024 * 1024
    elif path.startswith("/admin/dashboard"):
        request.max_content_length = 40 * 1024 * 1024
    else:
        request.max_content_length = 4 * 1024 * 1024

@app.errorhandler(413)
def _too_big(_e):
    if request.path == "/admin/backup/restore":
        return redirect("/admin/dashboard?backup_note=" + _q(f"That backup file is too big for this server to accept (the limit is {MAX_RESTORE_MB} MB).") + "#backup")
    msg = (f"That file is too big (the limit is {MAX_UPLOAD_MB} MB)." if request.path == "/admin/content/upload"
           else "That picture is too big (over 10 MB). Use a smaller one." if request.path == "/admin/content/preview"
           else "That request is too large.")
    return jsonify({"success": False, "error": msg}), 413

# ── Rate limits (see security.py) ──
# Wrong admin passwords lock the guesser out; the public endpoints (signup,
# verify, member content/files) are capped per visitor so one script cannot
# flood the server, fill the disk with cards, or send endless emails.
try:
    SIGNUP_LIMIT_PER_HOUR = max(1, int(os.environ.get("SIGNUP_LIMIT_PER_HOUR", "300")))
except ValueError:
    SIGNUP_LIMIT_PER_HOUR = 300

_login_guard = security.LoginGuard()
_rate = security.SlidingLimiter()

# (path or prefix ending in "/", bucket name, hits allowed per visitor, window in seconds)
_PUBLIC_RULES = [
    ("/issue",          "signup", 10,  600),
    ("/checkout",       "signup", 10,  600),
    ("/verify",         "check",  120, 60),
    ("/member-content", "check",  120, 60),
    ("/member-file/",   "file",   60,  60),
    ("/member-card/",   "file",   60,  60),
    ("/member-preview/","thumb",  600, 60),     # a grid of pictures loads many at once
]

def _too_many(wait: int, msg: str = "Too many requests. Please wait a little and try again."):
    resp = jsonify({"success": False, "valid": False, "error": msg})
    resp.status_code = 429
    resp.headers["Retry-After"] = str(max(1, int(wait)))
    return resp

@app.before_request
def _rate_limit_public():
    if request.method not in ("POST", "GET"):
        return None
    path = request.path
    for prefix, bucket, limit, window in _PUBLIC_RULES:
        if path == prefix or (prefix.endswith("/") and path.startswith(prefix)):
            allowed, wait = _rate.hit((bucket, get_client_ip()), limit, window)
            if not allowed:
                return _too_many(wait)
            if bucket == "signup":
                allowed, wait = _rate.hit(("signup-all",), SIGNUP_LIMIT_PER_HOUR, 3600)
                if not allowed:
                    return _too_many(wait, "We're getting a lot of sign-ups right now. Please try again in a little while.")
            break
    return None

@app.before_request
def _csrf_protect():
    """Every state-changing admin request made from a logged-in browser must
    carry the page's CSRF token (added automatically by security.inject_csrf).
    Scripts that authenticate with the admin secret are not cookie-driven, so
    they are exempt."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    path = request.path
    if not (path.startswith("/admin/") or path == "/revoke") or path == "/admin/login":
        return None
    if not is_admin_session():
        return None            # the route's own auth check will refuse it
    if ADMIN_SECRET and (security.same_secret(request.headers.get("X-Admin-Secret"), ADMIN_SECRET)
                         or security.same_secret(request.args.get("secret"), ADMIN_SECRET)):
        return None
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    if not security.csrf_ok(session, supplied):
        return jsonify({"success": False, "valid": False,
                        "error": "Security check failed. Reload the page and try again."}), 403
    return None

@app.after_request
def _security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    path = request.path
    if path.startswith("/admin/") or path == "/revoke":
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        resp.headers.setdefault("Cache-Control", "no-store")
        if (request.method == "GET" and resp.status_code == 200 and resp.mimetype == "text/html"
                and is_admin_session() and not resp.direct_passthrough):
            resp.set_data(security.inject_csrf(resp.get_data(as_text=True), security.csrf_token(session)))
    return resp

# Stripe — payments are entirely opt-in. With these unset, /checkout still
# works for free (price 0) tiers; any tier with a price simply returns a
# clear "not configured" error instead of a broken checkout. See SETUP.md
# for how to get test-mode keys and wire up the webhook.
STRIPE_SECRET_KEY     = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
if stripe and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# Idempotency store for the Stripe webhook — Stripe retries delivery until
# it gets a 200, so the same checkout.session.completed event can arrive
# more than once. Keeps the last 500 processed session ids; a credential
# must never be issued twice for the same payment.
STRIPE_PROCESSED_FILE = DATA_DIR / "stripe_processed_sessions.json"

def _stripe_already_processed(session_id: str) -> bool:
    if not STRIPE_PROCESSED_FILE.exists():
        return False
    try:
        with open(STRIPE_PROCESSED_FILE) as f:
            return session_id in json.load(f)
    except Exception:
        return False

def _stripe_mark_processed(session_id: str):
    ids = []
    if STRIPE_PROCESSED_FILE.exists():
        try:
            with open(STRIPE_PROCESSED_FILE) as f:
                ids = json.load(f)
        except Exception:
            ids = []
    ids.append(session_id)
    ids = ids[-500:]
    with open(STRIPE_PROCESSED_FILE, "w") as f:
        json.dump(ids, f)

# ── HELPERS ──

def err(msg, code=400):
    return jsonify({"success": False, "valid": False, "error": msg}), code

def ok(data):
    return jsonify({"success": True, **data})

def get_client_ip():
    # Railway sits the app behind a proxy, so the real client address arrives
    # in X-Forwarded-For (its first entry), not the raw socket address —
    # request.remote_addr alone would just be the proxy every time.
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr

def _login_key() -> str:
    """Who to blame for wrong admin passwords. Uses the LAST X-Forwarded-For
    entry (the one Railway's proxy added), because the first entry is
    whatever the client chose to send. The site-wide backstop in
    security.LoginGuard covers the case where the proxy chain hides it."""
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        last = fwd.split(",")[-1].strip()
        if last:
            return last
    return request.remote_addr or "unknown"

def is_admin_session() -> bool:
    return bool(session.get("admin_authed"))

def check_admin(req) -> bool:
    """Shared admin auth check for API calls (/revoke). Accepts either a
    logged-in admin session (the browser flow, via /admin/login) or the
    X-Admin-Secret header / ?secret= query param (for scripts/curl — see
    SETUP.md). With ADMIN_SECRET unset, nothing can authenticate at all —
    fail closed, not open."""
    if is_admin_session():
        return True
    if not ADMIN_SECRET:
        return False
    secret = req.headers.get("X-Admin-Secret") or req.args.get("secret", "")
    if not secret:
        return False
    key = _login_key()
    if _login_guard.seconds_locked(key):
        return False
    if security.same_secret(secret, ADMIN_SECRET):
        return True
    _login_guard.fail(key)
    return False

def require_admin_page(next_path: str):
    """For admin PAGES (not API calls): redirect to the login page instead
    of a bare 401, carrying where to return to afterward. Returns None when
    already authenticated — caller proceeds as normal."""
    if is_admin_session():
        return None
    return redirect(f"/admin/login?next={next_path}")

def _read_config_file() -> dict:
    # DATA_DIR/config.json if the dashboard has ever saved one, otherwise
    # the repo's config.json as the first-boot default — see config_store.py.
    return config_store.read_config()

CARD_STYLES = card_looks.STYLES

def load_config() -> dict:
    """
    Load this deployment's identity/branding from config.json. Every value
    has a generic fallback so the API still runs with no config.json at
    all — but you'll want to fill this in before sending a real member a
    card or email, or do it through /admin/dashboard. See SETUP.md.
    """
    cfg = _read_config_file()
    return {
        "creator_name":  cfg.get("creator_name", "Your Creator Name"),
        "card_title":    cfg.get("card_title", "YOUR BRAND HERE"),
        "card_subtitle": cfg.get("card_subtitle", "Member Card"),
        "accent_color":  cfg.get("accent_color", "#00e87a"),
        # What was typed in Branding (may be empty), and the address actually
        # used: that, or this server's own built-in /members page.
        "members_page_saved": os.environ.get("MEMBERS_PAGE", cfg.get("members_page", "")),
        "members_page":  public_url.effective_members_page(os.environ.get("MEMBERS_PAGE", cfg.get("members_page", ""))),
        "api_base":      cfg.get("api_base", ""),
        "currency":      cfg.get("currency", "usd"),
        # Which payment plugin /checkout routes a paid tier through —
        # "manual" (default: admin-approval queue, no third-party account,
        # works in any country/category) or "stripe" (automatic card
        # checkout). See "Adding a new payment provider" in SETUP.md to
        # add another one without touching this fallback logic.
        "payment_provider": cfg.get("payment_provider", "manual"),
        "manual_payment_instructions": cfg.get("manual_payment_instructions", ""),
        # "custom" provider (custom_payment.py): the service's name, a default
        # pay link and optional per-tier links. Cleaned on every read, so a
        # hand-edited config.json can't smuggle in an unsafe link.
        "custom_provider_name":  custom_payment.clean_name(cfg.get("custom_provider_name")),
        "custom_payment_url":    custom_payment.clean_url(cfg.get("custom_payment_url")),
        "custom_payment_links":  custom_payment.clean_links(cfg.get("custom_payment_links")),
        # Wording of the welcome email (edited under "Welcome email" in the
        # dashboard). Blank subject/intro mean "use the built-in text".
        "email_subject": cfg.get("email_subject", email_sender.DEFAULT_SUBJECT),
        "email_intro":   cfg.get("email_intro", email_sender.DEFAULT_INTRO),
        "email_signoff": cfg.get("email_signoff", ""),
        # Expiry reminder: how many days before the end date a member is
        # emailed (0 = off), and its wording. See reminders.py.
        "reminder_days":    reminders.clean_reminder_days(cfg.get("reminder_days", 0)),
        "reminder_subject": cfg.get("reminder_subject", email_sender.DEFAULT_REMINDER_SUBJECT),
        "reminder_text":    cfg.get("reminder_text", email_sender.DEFAULT_REMINDER_TEXT),
        "reminder_renew_url": cfg.get("reminder_renew_url", ""),
        "extended_subject": cfg.get("extended_subject", email_sender.DEFAULT_EXTENDED_SUBJECT),
        "extended_text":    cfg.get("extended_text", email_sender.DEFAULT_EXTENDED_TEXT),
        # Card look: the logo (a data: URI saved from the dashboard — "" for
        # none) and the style, "distressed" or "clean".
        "logo_data_uri": cfg.get("logo_data_uri", "") or "",
        "card_style":    cfg.get("card_style", "distressed") if cfg.get("card_style") in CARD_STYLES else "distressed",
        "qr_style":      cfg.get("qr_style") if cfg.get("qr_style") in card_looks.QR_STYLES else "solid",
        # The Default look's optional background picture, and the saved
        # "card looks" (card_looks.py) a tier can pick instead of the default.
        "bg_data_uri":   cfg.get("bg_data_uri") if logo_utils.is_logo_data_uri(cfg.get("bg_data_uri")) else "",
        "bg_dim":        cfg.get("bg_dim") if cfg.get("bg_dim") in card_looks.DIMS else card_looks.DEFAULT_DIM,
        "card_looks":    card_looks.clean_looks(cfg.get("card_looks")),
        # How the member widget looks on the creator's site (widget_look.py).
        **widget_look.from_config(cfg),
        # How the admin pages look (admin_theme.py). A deployment that never
        # chose one keeps the original look.
        "admin_style":   admin_theme.clean_style(cfg.get("admin_style")),
        "tiers":         cfg.get("tiers", []),
    }

def save_config(updates: dict):
    """Merge `updates` into the current settings and write them back to the
    live copy in DATA_DIR (the persistent Volume in production — never next
    to the code, which a redeploy rebuilds). Used by /admin/dashboard's
    save — never overwrites fields the dashboard form doesn't send (e.g.
    nothing today, but keeps this safe as the form grows)."""
    cfg = _read_config_file()
    cfg.update(updates)
    config_store.write_config(cfg)

def get_tier(cfg: dict, tier_name: str) -> dict:
    """The configured tier matching `tier_name`, or None if it isn't one of
    the tiers set up in /admin/dashboard (e.g. an ad-hoc name used for
    manual/demo testing via /issue directly)."""
    return next((t for t in cfg.get("tiers", []) if t.get("name") == tier_name), None)

def resolve_look(cfg: dict, look: dict = None, legacy_design: dict = None) -> dict:
    """
    The final values for drawing a card: one saved look (or, for a tier not
    yet converted, its old-style `design` block, or neither = the Default look
    from Branding). A blank field in a look follows the Default look. The
    background picture does not follow: only the Default look itself, or a look
    that has its own, shows one.
    """
    own = look if look is not None else (legacy_design or None)
    d = own or {}
    style = d.get("card_style")
    if style not in CARD_STYLES:
        style = cfg.get("card_style") if cfg.get("card_style") in CARD_STYLES else "distressed"
    if own is None:
        bg, dim = cfg.get("bg_data_uri") or "", cfg.get("bg_dim")
    else:
        bg = d.get("bg_data_uri") if logo_utils.is_logo_data_uri(d.get("bg_data_uri")) else ""
        dim = d.get("bg_dim")
    return {
        "card_title":    d.get("card_title") or cfg["card_title"],
        "accent_color":  d.get("accent_color") or cfg["accent_color"],
        "show_barcode":  d.get("show_barcode", True),
        # the look's own logo, else the deployment's logo from Branding, else none
        "logo_data_uri": d.get("logo_data_uri") or cfg.get("logo_data_uri") or None,
        "card_label":    d.get("card_label") or cfg.get("card_subtitle") or "",
        "card_style":    style,
        "qr_style":      d.get("qr_style") if d.get("qr_style") in card_looks.QR_STYLES else cfg.get("qr_style", "solid"),
        "background_data_uri": bg or None,
        "background_dim":      dim if dim in card_looks.DIMS else card_looks.DEFAULT_DIM,
    }

def resolve_tier_design(cfg: dict, tier_name: str) -> dict:
    """
    The card values for a tier: the look it picked on the dashboard (Tiers &
    pricing -> Card look), else the Default look from Branding. A tier that
    still carries an old-style `design` block (settings saved before card
    looks existed, not opened on the dashboard since) keeps drawing exactly as
    it did. This is the one place that choice happens, so /issue and every
    preview stay in sync.
    """
    tier_cfg = next((t for t in cfg.get("tiers", []) if t.get("name") == tier_name), None) or {}
    look = card_looks.get(cfg.get("card_looks") or [], tier_cfg.get("look"))
    if look:
        return resolve_look(cfg, look)
    return resolve_look(cfg, None, tier_cfg.get("design"))

def _migrate_card_looks() -> bool:
    """Turn tiers' old per-tier designs into looks (once). Called whenever the
    dashboard is opened or saved; cards look exactly the same before and after."""
    raw = _read_config_file()
    if card_looks.migrate_tier_designs(raw):
        config_store.write_config(raw)
        return True
    return False

def _encode_background_upload(file_storage) -> tuple:
    """A card background upload -> (data: URI, "") or ("", reason it was not
    used); ("", "") when no file was chosen."""
    if not file_storage or not file_storage.filename:
        return "", ""
    raw = file_storage.read(logo_utils.BG_MAX_UPLOAD_BYTES + 1)
    return logo_utils.process_background(raw)


# ── Signup limits (see limits.py) ──
# Checking "is there room / has this email already got one" and then actually
# issuing must happen as one step, or two people could grab the last spot at
# the same moment. This lock makes the check and the registry write one unit.
_signup_lock = threading.RLock()

class SignupBlocked(Exception):
    """A signup refused by a tier limit (sold out, or email already used)."""
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message

def _signup_check(cfg: dict, tier_cfg: dict, tier: str, email: str):
    """None if allowed, else (reason, message). Call with _signup_lock held
    when the answer is about to be acted on."""
    if not tier_cfg:
        return None   # an unlisted/demo tier name has no limits to apply
    if card_kinds.is_ticket(tier_cfg):
        ev = card_kinds.event_of(tier_cfg)
        if not card_kinds.has_date(ev):
            return ("event_not_ready", "This ticket isn't ready yet: the event has no date.")
        if card_kinds.is_over(ev):
            return ("event_over", "This event has already happened.")
    if card_kinds.is_collectible(tier_cfg):
        state = card_kinds.drop_state(card_kinds.drop_of(tier_cfg))
        if state == "soon":
            opens = card_kinds.public_drop(tier_cfg)["opens"]
            return ("drop_not_open", "This drop hasn't opened yet" + (f": it opens {opens}." if opens else "."))
        if state == "closed":
            return ("drop_closed", "This drop is closed.")
    from member_registry import list_all as registry_list
    from payment_requests import list_all as requests_list
    return limits.check_signup(tier_cfg, tier, email, registry_list(), requests_list(),
                               creator=cfg.get("creator_name") or "the creator")

def _blocked_response(reason: str, message: str):
    resp = jsonify({"success": False, "valid": False, "error": message, "reason": reason})
    resp.status_code = 409
    return resp

def _issue_and_fulfill(name: str, email: str, tier: str, days: int, sections: list,
                        cfg: dict = None, payment_meta: dict = None, check=None,
                        send_email: bool = True) -> dict:
    """
    The actual issue → bundle → card → registry → email pipeline, shared
    by the free path in /issue, /checkout's free-tier shortcut, and the
    Stripe webhook after a paid checkout completes. This is an internal
    function, not a route — it has no HTTP-level auth of its own, so every
    *caller* is responsible for having already decided this fulfillment is
    allowed (price check, payment confirmation, etc.) before calling it.
    """
    from credential_issuer import issue_credential
    from credential_bundle import bundle_credential
    from card_generator    import generate_card
    from member_registry   import add_credential
    from email_sender      import send_credential_email

    cfg = cfg or load_config()
    design = resolve_tier_design(cfg, tier)

    # An event ticket works until its event ends, whatever number of days the
    # caller passed; its event details are signed into the card and shown on it.
    tier_cfg_t = get_tier(cfg, tier)
    kind, event, ends_at, drop = "pass", None, None, None
    if card_kinds.is_collectible(tier_cfg_t):
        # A collectible never expires. Its drop window is checked by the caller's
        # `check` (the creator can override that when giving one away by hand).
        kind, ends_at = "collectible", card_kinds.NEVER
        days = 36500
    if card_kinds.is_ticket(tier_cfg_t):
        ev = card_kinds.event_of(tier_cfg_t)
        ends_at = card_kinds.ends_utc(ev)
        if ends_at is None or ends_at <= datetime.now(timezone.utc):
            if ends_at is None:
                raise SignupBlocked("event_not_ready", "This ticket isn't ready yet: the event has no date.")
            raise SignupBlocked("event_over", "This event has already happened.")
        kind, event = "ticket", card_kinds.card_event(tier_cfg_t)
        days = max(1, -(-int((ends_at - datetime.now(timezone.utc)).total_seconds()) // 86400))

    # Steps 1–4 run under the signup lock so a limit check (`check`, when the
    # caller gives one) and the registry write can't be interleaved with
    # another signup. The email (slow, network) goes out after the lock.
    with _signup_lock:
        if check:
            blocked = check()
            if blocked:
                raise SignupBlocked(*blocked)

        # A collectible is one numbered copy of a limited edition: the next free
        # number, counted from the cards already issued for this tier (revoked
        # ones keep theirs).
        if kind == "collectible":
            from member_registry import list_all as _reg_all
            used = [int((e.get("drop") or {}).get("edition") or 0) for e in _reg_all()
                    if str(e.get("tier") or "").upper() == str(tier).upper()]
            drop = card_kinds.card_drop(tier_cfg_t, max(used + [0]) + 1, limits.tier_max(tier_cfg_t))

        # 1 — Issue
        result = issue_credential(
            name        = name,
            email       = email,
            tier        = tier,
            expiry_days = days,
            sections    = sections,
            metadata    = ({"kind": "ticket", "event": event} if kind == "ticket"
                           else {"kind": "collectible", "drop": drop} if kind == "collectible" else None),
            expires_at_override = ends_at,
        )

        # 2 — Bundle
        bundle = bundle_credential(result)

        # 3 — Card (tier's own design overrides the global look, if set)
        card_path = generate_card(
            credential_id = result["credential_id"],
            holder_name   = name,
            tier          = tier,
            issued_at     = result["entry"]["issued_at"],
            expires_at    = result["entry"]["expires_at"],
            bundle_hash   = bundle["bundle_hash"],
            signature_hex = result["entry"]["signature_hex"],
            sections      = result["entry"]["sections"],
            card_title    = design["card_title"],
            card_subtitle = f"{tier} Card",
            access_url    = cfg["members_page"],
            creator_name  = cfg["creator_name"],
            accent_color  = design["accent_color"],
            show_barcode  = design["show_barcode"],
            logo_data_uri = design["logo_data_uri"],
            card_label    = design["card_label"],
            card_style    = design["card_style"],
            qr_style      = design["qr_style"],
            background_data_uri = design["background_data_uri"],
            background_dim      = design["background_dim"],
            kind                = kind,
            event               = event,
            drop                = drop,
        )

        # 4 — Registry (payment_meta, if given, is recorded on the entry —
        # see member_registry.add_credential's "payment" field)
        add_credential({
            **result["entry"],
            "bundle_hash": bundle["bundle_hash"],
            "bundle_path": bundle["bundle_path"],
            "payment":     payment_meta,
            "kind":        kind,
            "event":       event,
            "drop":        drop,
        })

    # 5 — Email (skipped when the caller doesn't want one, e.g. the creator
    # issued a card by hand and will pass the link on personally)
    email_ok = None
    if send_email:
        email_ok = send_credential_email(
            to_name       = name,
            to_email      = email,
            tier          = tier,
            credential_id = result["credential_id"],
            bundle_hash   = bundle["bundle_hash"],
            bundle_path   = bundle["bundle_path"],
            card_path     = card_path,
            expires_at    = result["entry"]["expires_at"],
        )

    return {
        "credential_id":    result["credential_id"],
        "bundle_hash":      bundle["bundle_hash"],
        "fingerprint_hash": result["fingerprint_hash"],
        "email_sent":       email_ok,
        "expires_at":       result["entry"]["expires_at"],
    }


# ── POST /issue ──
# Direct, unauthenticated issuance — same as always for a FREE tier (or an
# ad-hoc tier name that isn't in config.json's tiers at all, kept for
# manual/demo use). A tier that's actually configured with a price can no
# longer be issued this way: that's the whole point of adding real payment
# below — go through /checkout instead. For any tier that IS configured,
# its own `sections`/`expiry_days` are now authoritative, not whatever the
# caller sends — otherwise a request could claim a cheap tier's name while
# asking for an expensive tier's sections, which would make pricing purely
# decorative.
@app.route("/issue", methods=["POST"])
def issue():
    data = request.get_json()
    if not data:
        return err("No JSON body")

    name  = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    tier  = (data.get("tier") or "DEMO").strip().upper()

    if not name:  return err("name is required")
    if not email: return err("email is required")
    if "@" not in email: return err("invalid email")

    cfg = load_config()
    tier_cfg = get_tier(cfg, tier)

    if tier_cfg:
        if (tier_cfg.get("price") or 0) > 0:
            return err("This tier requires payment — use POST /checkout instead.", 402)
        days     = tier_cfg.get("expiry_days", 31)
        sections = tier_cfg.get("sections", [])
    else:
        # Unlisted tier name — legacy permissive behavior for manual/demo
        # issuance, unchanged from before pricing existed.
        days = int(data.get("expiry_days") or 31)
        sections = data.get("sections")
        if sections is None:
            sections = ["downloads", "chat"]

    try:
        result = _issue_and_fulfill(name, email, tier, days, sections, cfg=cfg,
                                    check=lambda: _signup_check(cfg, tier_cfg, tier, email))
        return ok(result)
    except SignupBlocked as b:
        return _blocked_response(b.reason, b.message)
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return err(f"Issuance failed: {str(e)}", 500)


# ── POST /checkout ──
# The member-facing entry point for a PAID tier (and the only entry point
# cp.js actually calls now — a free tier issues immediately here too, so
# the signup widget never has to know which case it is). Nothing but a
# free tier is issued directly in this function: for any priced tier, this
# just STARTS the right flow for whichever provider is configured —
#   - "manual" (default): records a pending request and hands back
#     instructions; an admin approves it from /admin/dashboard, which is
#     what actually issues the credential. No payment account needed on
#     this deployment at all.
#   - "stripe": creates a Checkout Session and hands back its URL for the
#     caller to redirect the browser to; the credential is only actually
#     issued by /webhook/stripe once Stripe confirms payment.
# Either way, fulfillment happens through the same _issue_and_fulfill()
# pipeline, so a manually-approved credential and a Stripe one are
# otherwise indistinguishable. One-time payment per issuance — this does
# not set up recurring/subscription billing or auto-renewal, for either
# provider. See "Adding a new payment provider" in SETUP.md to plug in
# something else (PayPal, a regional/adult-friendly processor, etc.)
# without touching this dispatch.
@app.route("/checkout", methods=["POST"])
def checkout():
    data = request.get_json()
    if not data:
        return err("No JSON body")

    name  = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    tier  = (data.get("tier") or "").strip().upper()

    if not name:  return err("name is required")
    if not email: return err("email is required")
    if "@" not in email: return err("invalid email")
    if not tier:  return err("tier is required")

    cfg = load_config()
    tier_cfg = get_tier(cfg, tier)
    if not tier_cfg:
        return err(f"Unknown tier: {tier}", 400)

    price    = tier_cfg.get("price") or 0
    sections = tier_cfg.get("sections", [])
    days     = tier_cfg.get("expiry_days", 31)

    if price <= 0:
        try:
            result = _issue_and_fulfill(name, email, tier, days, sections, cfg=cfg,
                                        check=lambda: _signup_check(cfg, tier_cfg, tier, email))
            return ok(result)
        except SignupBlocked as b:
            return _blocked_response(b.reason, b.message)
        except Exception as e:
            import traceback
            print(traceback.format_exc())
            return err(f"Issuance failed: {str(e)}", 500)

    provider = (cfg.get("payment_provider") or "manual").strip().lower()
    currency = (cfg.get("currency") or "usd").lower()

    if provider == "stripe":
        if not (stripe and STRIPE_SECRET_KEY):
            return err("Stripe is not configured on this deployment yet. See SETUP.md.", 500)

        members_page = cfg["members_page"] or "https://example.com/members.html"

        # Refuse before taking anyone to a payment page. (Payments already in
        # flight are always honored by the webhook, so a rush can overshoot
        # a limit slightly rather than charge someone and give them nothing.)
        with _signup_lock:
            blocked = _signup_check(cfg, tier_cfg, tier, email)
        if blocked:
            return _blocked_response(*blocked)

        try:
            checkout_session = stripe.checkout.Session.create(
                mode="payment",
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency": currency,
                        "product_data": {
                            "name": f"{cfg['card_title']} — {tier_cfg.get('label') or tier}",
                        },
                        "unit_amount": int(round(price * 100)),
                    },
                    "quantity": 1,
                }],
                customer_email=email,
                metadata={"holder_name": name, "holder_email": email, "tier": tier},
                success_url=f"{members_page}?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{members_page}?checkout=cancelled",
            )
            return ok({"provider": "stripe", "checkout_url": checkout_session.url})
        except Exception as e:
            return err(f"Could not start checkout: {str(e)}", 500)

    # provider == "manual" or "custom", and the fallback for any unrecognized value —
    # the point of defaulting here rather than refusing is that this path
    # always works, in any country, with zero setup. Nothing is issued
    # yet; see /admin/payment-requests/<id>/approve below.
    from payment_requests import create_request as create_payment_request
    with _signup_lock:
        blocked = _signup_check(cfg, tier_cfg, tier, email)
        if blocked:
            return _blocked_response(*blocked)
        req = create_payment_request(name, email, tier, price, currency)
    instructions = cfg.get("manual_payment_instructions") or (
        "Contact the creator to arrange payment. Your access will be "
        "issued once payment is confirmed."
    )
    reply = {
        "provider":     "manual",
        "pending":      True,
        "request_id":   req["request_id"],
        "instructions": instructions,
    }
    if provider == "custom":
        # Same queue as manual approval, plus a "Pay with <name>" link for the
        # member (opened in a new tab by the widget). No link set up for this
        # tier -> they just see the written instructions.
        reply["provider"] = "custom"
        reply["reference"] = req["request_id"]
        pay_url = custom_payment.link_for(cfg, tier, name, email, price, currency, req["request_id"])
        if pay_url:
            reply["pay_url"] = pay_url
            reply["pay_label"] = custom_payment.button_label(cfg)
    return ok(reply)


# ── POST /webhook/stripe ──
# Stripe calls this directly (not a browser) once a Checkout Session's
# payment completes. This is the ONLY place a paid credential actually
# gets issued — /checkout never issues one itself for a paid tier. Signed
# and verified with STRIPE_WEBHOOK_SECRET; without it set, this refuses
# everything, same fail-closed stance as ADMIN_SECRET. Idempotent against
# Stripe's at-least-once retry behavior via _stripe_already_processed.
@app.route("/webhook/stripe", methods=["POST"])
def stripe_webhook():
    if not (stripe and STRIPE_WEBHOOK_SECRET):
        return err("Stripe webhook is not configured on this deployment.", 500)

    payload   = request.get_data()
    signature = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, signature, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        return err(f"Invalid webhook signature: {str(e)}", 400)

    if event.get("type") != "checkout.session.completed":
        return ok({"ignored": event.get("type")})

    session_obj = event["data"]["object"]
    session_id  = session_obj.get("id", "")
    meta        = session_obj.get("metadata") or {}
    name  = meta.get("holder_name")
    email = meta.get("holder_email")
    tier  = meta.get("tier")

    if not (name and email and tier):
        return err("Checkout session is missing holder metadata.", 400)

    if _stripe_already_processed(session_id):
        return ok({"already_processed": True})

    cfg = load_config()
    tier_cfg = get_tier(cfg, tier)
    if not tier_cfg:
        return err(f"Tier '{tier}' from this payment no longer exists in config.", 400)

    sections = tier_cfg.get("sections", [])
    days     = tier_cfg.get("expiry_days", 31)

    try:
        _issue_and_fulfill(name, email, tier, days, sections, cfg=cfg, payment_meta={
            "provider":          "stripe",
            "stripe_session_id": session_id,
            "amount_paid":       session_obj.get("amount_total"),
            "currency":          session_obj.get("currency"),
        })
        _stripe_mark_processed(session_id)
        return ok({"issued": True})
    except Exception as e:
        # Deliberately a 500, not 200 — Stripe will retry delivery, which
        # is what we want if fulfillment genuinely failed (e.g. a transient
        # disk error). _stripe_already_processed guards against the retry
        # double-issuing once this succeeds.
        import traceback
        print(traceback.format_exc())
        return err(f"Fulfillment failed: {str(e)}", 500)


# ── Admin: manual payment requests ──
# The fulfillment counterpart to the Stripe webhook above, but for the
# "manual" payment provider: nothing issues a credential until an admin
# looks at a pending request here and explicitly approves it, after
# confirming payment actually arrived however it does for this deployment
# (bank transfer, PayPal, cash, crypto, a local processor — whatever).
# Approve calls the exact same _issue_and_fulfill() pipeline the Stripe
# webhook does. mark_decided() only acts once per request (pending →
# approved/rejected), so a double-click or a retried request can't
# double-issue, same idempotency stance as the Stripe webhook.
@app.route("/admin/payment-requests/<request_id>/approve", methods=["POST"])
def admin_approve_payment_request(request_id):
    if not is_admin_session():
        return err("Unauthorized", 401)

    from payment_requests import get_request, mark_decided
    req = get_request(request_id)
    if not req:
        return err("Request not found", 404)
    if req["status"] != "pending":
        return err(f"Request already {req['status']}", 400)

    cfg = load_config()
    tier_cfg = get_tier(cfg, req["tier"])
    if not tier_cfg:
        return err(f"Tier '{req['tier']}' no longer exists in config.", 400)

    sections = tier_cfg.get("sections", [])
    days     = tier_cfg.get("expiry_days", 31)

    try:
        result = _issue_and_fulfill(
            req["holder_name"], req["holder_email"], req["tier"], days, sections,
            cfg=cfg,
            payment_meta={
                "provider":    "custom" if (cfg.get("payment_provider") or "") == "custom" else "manual",
                "amount_paid": req.get("price"),
                "currency":    req.get("currency"),
                "approved_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return err(f"Fulfillment failed: {str(e)}", 500)

    if not mark_decided(request_id, "approved"):
        # Fulfillment above succeeded but something else (a concurrent
        # approve/reject) already resolved this request — the credential
        # is issued either way; this just stops the UI from double-acting.
        return ok({**result, "note": "Request was already resolved, but the credential was issued."})
    return ok(result)


@app.route("/admin/payment-requests/<request_id>/reject", methods=["POST"])
def admin_reject_payment_request(request_id):
    if not is_admin_session():
        return err("Unauthorized", 401)

    from payment_requests import get_request, mark_decided
    req = get_request(request_id)
    if not req:
        return err("Request not found", 404)
    if req["status"] != "pending":
        return err(f"Request already {req['status']}", 400)

    mark_decided(request_id, "rejected")
    return ok({"rejected": True})


# ── POST /verify ──
@app.route("/verify", methods=["POST"])
def verify():
    data = request.get_json()
    if not data:
        return err("No JSON body")

    credential_id = (data.get("credential_id") or "").strip()
    bundle_hash   = (data.get("bundle_hash") or "").strip()

    if not credential_id:
        return err("credential_id is required")

    try:
        from credential_verifier import verify_credential
        result = verify_credential(
            credential_id = credential_id,
            bundle_hash   = bundle_hash or None,
            ip            = get_client_ip(),
        )
        return jsonify(result)

    except Exception as e:
        return err(f"Verification failed: {str(e)}", 500)


def _add_to_revocation_list(credential_id: str):
    """Put a credential ID on the public revocation list (a no-op if it is
    already there). Written to a temp file and swapped in, like the settings."""
    rev_file = DATA_DIR / "revocation_list.json"
    if rev_file.exists():
        with open(rev_file) as f:
            revlist = json.load(f)
    else:
        revlist = {"credential_ids": [], "bundle_hashes": [], "updated_at": ""}
    if credential_id not in revlist["credential_ids"]:
        revlist["credential_ids"].append(credential_id)
    revlist["updated_at"] = datetime.now(timezone.utc).isoformat()
    fd, tmp = tempfile.mkstemp(prefix=".revocation-", suffix=".tmp", dir=str(DATA_DIR))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(revlist, f, indent=2)
        os.replace(tmp, rev_file)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# ── POST /revoke ──
@app.route("/revoke", methods=["POST"])
def revoke():
    if not check_admin(request):
        return err("Unauthorized", 401)

    data = request.get_json()
    credential_id = (data.get("credential_id") or "").strip()
    if not credential_id:
        return err("credential_id is required")

    try:
        from member_registry import revoke as reg_revoke
        success = reg_revoke(credential_id)

        # Also write to revocation list file
        _add_to_revocation_list(credential_id)

        return ok({"revoked": success, "credential_id": credential_id})

    except Exception as e:
        return err(f"Revocation failed: {str(e)}", 500)


# ── POST /admin/members/delete ──
# Erases a member: their registry entry, their card, bundle and certificate
# files, and finished payment-request records for their email. Their ID goes
# on the revocation list first, so any copy of the card or bundle they still
# hold is dead for good and the ID can never be used again. Their tier spot
# and email are free again. (Revoke is the gentler choice: it cuts access but
# keeps the record.) Downloaded backups still contain them.
_CID_OK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

@app.route("/admin/members/delete", methods=["POST"])
def admin_members_delete():
    if not check_admin(request):
        return err("Unauthorized", 401)
    data = request.get_json(silent=True) or {}
    cid = str(data.get("credential_id") or "").strip()
    if not _CID_OK.match(cid):
        return err("credential_id is required")
    if str(data.get("confirm") or "") != "DELETE":
        return err("Type DELETE to confirm.")

    from credential_issuer import CREDENTIALS_DIR
    from credential_bundle import BUNDLES_DIR
    from card_generator import CARDS_DIR
    import shutil
    from payment_requests import forget_decided

    problems = []
    removed_files = 0
    with _signup_lock:
        entry = member_registry.get_by_id(cid)
        if not entry:
            return err("No such member.", 404)
        _add_to_revocation_list(cid)            # first: the card is dead even if a later step fails
        member_registry.delete(cid)

        targets = [CARDS_DIR / f"card_{cid}.html"]
        targets += list(BUNDLES_DIR.glob(f"credential_{cid}_*"))
        bp = entry.get("bundle_path")
        if bp:
            for extra in (Path(bp), Path(str(bp) + ".sha256")):
                if extra not in targets:
                    targets.append(extra)
        for t in targets:
            try:
                if t.exists() and t.resolve().parent in (CARDS_DIR.resolve(), BUNDLES_DIR.resolve()):
                    t.unlink()
                    removed_files += 1
            except OSError as e:
                problems.append(f"{t.name}: {e}")
        cdir = CREDENTIALS_DIR / cid
        try:
            if cdir.is_dir() and cdir.resolve().parent == CREDENTIALS_DIR.resolve():
                removed_files += sum(1 for _ in cdir.rglob("*") if _.is_file())
                shutil.rmtree(cdir)
        except OSError as e:
            problems.append(f"credentials/{cid}: {e}")

        # Forget finished payment requests for this person, but only when
        # they hold no other card (then those records still belong to it).
        key = limits.normalize_email(entry.get("holder_email"))
        requests_removed = 0
        if key and not any(limits.normalize_email(e.get("holder_email")) == key for e in member_registry.list_all()):
            try:
                requests_removed = forget_decided(lambda em: limits.normalize_email(em) == key)
            except Exception as e:
                problems.append(f"payment requests: {e}")
    return ok({"credential_id": cid, "files_removed": removed_files,
               "requests_removed": requests_removed, "problems": problems})


# ── POST /admin/members/issue ──
# The creator hands someone a card directly (a friend, a collaborator, a
# winner, a refund-and-keep): no checkout, no payment, no sign-up form.
# Same pipeline as every other card, so it is signed, bundled, registered
# and works exactly like a bought one. It is marked as "comped" in the
# registry so it's recognisable later. Tier limits (full tier, one card per
# email) apply unless the creator ticks "ignore limits".
@app.route("/admin/members/issue", methods=["POST"])
def admin_members_issue():
    if not check_admin(request):
        return err("Unauthorized", 401)
    data = request.get_json(silent=True) or {}
    name  = str(data.get("name") or "").strip()
    email = str(data.get("email") or "").strip().lower()
    tier  = str(data.get("tier") or "").strip()
    if not name or len(name) > 100:
        return err("Enter the person's name (up to 100 characters).")
    if (len(email) > 254 or "@" not in email[1:] or email.count("@") != 1 or "." not in email.split("@")[1]
            or any(c in email for c in " \r\n<>,;")):
        return err("That doesn't look like an email address.")
    cfg = load_config()
    tier_cfg = get_tier(cfg, tier)
    if not tier_cfg:
        return err("Choose one of your tiers.")
    raw_days = data.get("days")
    if raw_days in (None, ""):
        days = member_registry.clean_extend_days(tier_cfg.get("expiry_days", 31)) or 31
    else:
        days = member_registry.clean_extend_days(raw_days)
        if days is None:
            return err(f"Days must be a whole number from 1 to {member_registry.MAX_EXTEND_DAYS}.")
    notify = bool(data.get("notify"))
    ignore = bool(data.get("ignore_limits"))
    send = notify and email_sender.is_configured()

    try:
        result = _issue_and_fulfill(
            name, email, tier_cfg["name"], days, tier_cfg.get("sections", []), cfg=cfg,
            payment_meta={"comped": True},
            check=None if ignore else (lambda: _signup_check(cfg, tier_cfg, tier_cfg["name"], email)),
            send_email=send)
    except SignupBlocked as b:
        resp = _blocked_response(b.reason, b.message if b.reason.startswith("event_")
                                 else b.message + " Tick \"Ignore limits\" to issue it anyway.")
        return resp
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return err(f"Issuing failed: {str(e)}", 500)

    members_page = (cfg.get("members_page") or "").strip()
    link = ""
    if members_page:
        sep = "&" if "?" in members_page else "?"
        link = (f"{members_page}{sep}id={_q(result['credential_id'], safe='')}"
                f"&h={_q(result['bundle_hash'][:32], safe='')}")
    if not notify:
        email_status = "not_requested"
    elif not send:
        email_status = "not_configured"
    else:
        email_status = "sent" if result.get("email_sent") else "failed"
    return ok({"credential_id": result["credential_id"], "expires_at": result["expires_at"],
               "tier": tier_cfg["name"], "link": link, "email": email_status})


# ── POST /admin/members/extend ──
# Gives a member more time without re-issuing anything: same card, same
# access link, only the end date moves (see member_registry.extend). The
# printed date on the member's original card file stays what it was — the
# live check always uses the server's date, so the card keeps working.
@app.route("/admin/members/extend", methods=["POST"])
def admin_members_extend():
    if not check_admin(request):
        return err("Unauthorized", 401)
    data = request.get_json(silent=True) or {}
    cid = str(data.get("credential_id") or "").strip()
    if not cid:
        return err("credential_id is required")
    days = member_registry.clean_extend_days(data.get("days"))
    if days is None:
        return err(f"Days must be a whole number from 1 to {member_registry.MAX_EXTEND_DAYS}.")
    notify = bool(data.get("notify"))
    cfg = load_config()

    with _signup_lock:
        entry = member_registry.get_by_id(cid)
        if not entry:
            return err("No such member.", 404)
        if entry.get("revoked"):
            return err("This member's access was revoked, so it can't be extended.", 409)
        if entry.get("kind") == "collectible":
            return err("A collectible never expires, so there is nothing to extend.", 409)
        was_active = limits.is_active(entry)
        if not was_active:
            # An ended card that comes back takes a spot again, so a full tier
            # has to be checked first.
            tier_cfg = get_tier(cfg, entry.get("tier"))
            cap = limits.tier_max(tier_cfg)
            if cap is not None:
                from payment_requests import list_all as requests_list
                if limits.count_taken(member_registry.list_all(), requests_list(), entry.get("tier")) >= cap:
                    return err(f"{(tier_cfg or {}).get('label') or entry.get('tier')} is full ({cap} members), "
                               "so this ended card can't be brought back. Raise the limit on the Dashboard first.", 409)
        try:
            updated = member_registry.extend(cid, days)
        except ValueError as e:
            return err("This member's access was revoked, so it can't be extended." if str(e) == "revoked"
                       else f"Days must be a whole number from 1 to {member_registry.MAX_EXTEND_DAYS}.", 409)
        if updated is None:
            return err("No such member.", 404)

    email_status = "not_requested"
    if notify:
        if not email_sender.is_configured():
            email_status = "not_configured"
        else:
            try:
                sent, _detail = email_sender.send_extended_email(
                    updated.get("holder_name", ""), updated.get("holder_email", ""), updated.get("tier", ""),
                    updated["credential_id"], updated.get("bundle_hash", ""), updated["expires_at"], days)
                email_status = "sent" if sent else "failed"
            except Exception as e:
                print(f"❌ Extension email failed: {e}")
                email_status = "failed"
    return ok({"credential_id": cid, "expires_at": updated["expires_at"],
               "was_active": was_active, "days_added": days, "email": email_status})


# ── Event tickets: Check-in ──
# For the door. /admin/checkin is the page (camera or pasted link); /scan looks
# a ticket up and, unless told only to look, checks it off at once; /use and
# /undo are the buttons on the Members screen (and "undo" on the Check-in page).
def _ticket_info(entry: dict) -> dict:
    ev = entry.get("event") if isinstance(entry.get("event"), dict) else {}
    return {"credential_id": entry.get("credential_id"), "name": entry.get("holder_name"),
            "tier": entry.get("tier"), "event": ev.get("name") or "", "when": ev.get("when") or "",
            "note": ev.get("note") or ""}

def _checkin_stats() -> list:
    import checkin_page
    from member_registry import list_all
    return checkin_page.stats(list_all())

@app.route("/admin/checkin", methods=["GET"])
def admin_checkin():
    redirect_resp = require_admin_page("/admin/checkin")
    if redirect_resp:
        return redirect_resp
    import checkin_page
    cfg = load_config()
    html = checkin_page.render(
        admin_theme.css(cfg["admin_style"], cfg["accent_color"], "wide"),
        admin_theme.shell_js(cfg["admin_style"]),
        admin_theme.body_attrs(cfg["admin_style"], "checkin", cfg["card_title"]),
        cfg["card_title"], _checkin_stats(),
        any(card_kinds.is_ticket(t) for t in (cfg.get("tiers") or [])))
    resp = app.response_class(html, mimetype="text/html")
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.route("/admin/checkin/scan", methods=["POST"])
def admin_checkin_scan():
    if not check_admin(request):
        return err("Unauthorized", 401)
    import checkin_page
    from member_registry import get_by_id, mark_used
    data = request.get_json(silent=True) or {}
    mark = data.get("mark") is not False
    cid, h = checkin_page.parse_code(data.get("code"))
    def reply(state, title="", error="", entry=None, marked=False):
        return jsonify({"success": True, "state": state, "title": title, "error": error, "marked": marked,
                        "ticket": _ticket_info(entry) if entry else None, "stats": _checkin_stats()})
    if not cid:
        return reply("bad", "Not a ticket", "That doesn't look like a ticket link or code.")
    entry = get_by_id(cid)
    if not entry:
        return reply("bad", "Unknown ticket", "No ticket with that code was found.")
    if h:
        stored = (entry.get("bundle_hash") or "").lower()
        n = min(len(h), 32)
        if len(stored) < 16 or len(h) < 16 or not hmac.compare_digest(stored[:n], h[:n]):
            return reply("bad", "Not valid", "This code doesn't match the ticket.")
    if entry.get("kind") != "ticket":
        return reply("bad", "Not a ticket", "This is an access pass, not an event ticket.", entry)
    if entry.get("revoked"):
        return reply("bad", "Cancelled", "This ticket was revoked.", entry)
    if not limits.is_active(entry):
        return reply("bad", "Expired", "The event is over, so this ticket no longer works.", entry)
    if entry.get("used_at"):
        return reply("bad", "Already used", "Checked in at " + str(entry["used_at"])[:16].replace("T", " ") + " UTC.", entry)
    if not mark:
        return reply("valid", entry=entry)
    mark_used(cid)
    return reply("ok", entry=entry, marked=True)

def _checkin_toggle(undo: bool):
    if not check_admin(request):
        return err("Unauthorized", 401)
    from member_registry import get_by_id, mark_used, unmark_used
    data = request.get_json(silent=True) or {}
    cid = str(data.get("credential_id") or "").strip()
    entry = get_by_id(cid) if cid else None
    if not entry:
        return err("No such ticket.", 404)
    if entry.get("kind") != "ticket":
        return err("That card is an access pass, not an event ticket.", 400)
    if undo:
        unmark_used(cid)
    else:
        if entry.get("revoked") or not limits.is_active(entry):
            return err("That ticket is revoked or expired.", 400)
        mark_used(cid)
    return jsonify({"success": True, "stats": _checkin_stats()})

@app.route("/admin/checkin/use", methods=["POST"])
def admin_checkin_use():
    return _checkin_toggle(False)

@app.route("/admin/checkin/undo", methods=["POST"])
def admin_checkin_undo():
    return _checkin_toggle(True)


# ── Announcements ──
# One note, pinned at the top of every member's page and/or emailed to a group
# (see announcements.py). The emails are sent one by one in a background thread,
# so the page answers at once and shows progress; only one send runs at a time.
_announce_lock = threading.Lock()
_announce_run = {"id": None}          # the history entry being sent right now, if any
ANNOUNCE_PAUSE = 0.15                 # seconds between emails, to stay inside the email service's rate limits

def _announce_state() -> dict:
    d = announcements.load()
    from member_registry import list_all
    running = _announce_run.get("id")
    hist = []
    for h in d["history"]:
        h = dict(h)
        e = h.get("email")
        if isinstance(e, dict) and not e.get("done") and h.get("id") != running:
            h["email"] = {**e, "interrupted": True}      # the server restarted part-way
        hist.append(h)
    cfg = load_config()
    return {"success": True, "current": d["current"], "history": hist,
            "groups": announcements.groups(list_all(), cfg.get("tiers") or []),
            "email_ready": email_sender.is_configured(), "running": bool(running)}

def _run_announcement_emails(entry_id: str, recips: list, title: str, text: str, link: str):
    sent = failed = 0
    first_error = ""
    try:
        for e in recips:
            try:
                ok_, detail = email_sender.send_announcement_email(
                    e.get("holder_name") or "there", e["holder_email"], e.get("tier") or "",
                    e["credential_id"], e.get("bundle_hash") or "", title, text, link)
            except Exception as ex:                       # one bad address must not stop the rest
                ok_, detail = False, str(ex)
            if ok_:
                sent += 1
            else:
                failed += 1
                first_error = first_error or str(detail)[:200]
            if (sent + failed) % 5 == 0:
                announcements.set_email_status(entry_id, sent=sent, failed=failed, first_error=first_error)
            time.sleep(ANNOUNCE_PAUSE)
    finally:
        announcements.set_email_status(entry_id, sent=sent, failed=failed, first_error=first_error, done=True,
                                       finished_at=datetime.now(timezone.utc).isoformat())
        _announce_run["id"] = None
        _announce_lock.release()

@app.route("/admin/announce", methods=["GET"])
def admin_announce():
    redirect_resp = require_admin_page("/admin/announce")
    if redirect_resp:
        return redirect_resp
    import announce_page
    cfg = load_config()
    html = announce_page.render(
        admin_theme.css(cfg["admin_style"], cfg["accent_color"], "wide"),
        admin_theme.shell_js(cfg["admin_style"]),
        admin_theme.body_attrs(cfg["admin_style"], "announce", cfg["card_title"]),
        cfg["card_title"], _announce_state())
    resp = app.response_class(html, mimetype="text/html")
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.route("/admin/announce/status", methods=["GET"])
def admin_announce_status():
    if not check_admin(request):
        return err("Unauthorized", 401)
    resp = jsonify(_announce_state())
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.route("/admin/announce/post", methods=["POST"])
def admin_announce_post():
    if not check_admin(request):
        return err("Unauthorized", 401)
    from member_registry import list_all
    data = request.get_json(silent=True) or {}
    title, text = announcements.clean_title(data.get("title")), announcements.clean_text(data.get("text"))
    link = announcements.clean_link(data.get("link"))
    if str(data.get("link") or "").strip() and not link:
        return err("The link has to start with http:// or https://")
    if not title and not text:
        return err("Write a title or a message first.")
    pin, mail = bool(data.get("pin")), bool(data.get("email"))
    if not pin and not mail:
        return err("Choose at least one: pin it, or email it.")
    recips = []
    if mail:
        if not email_sender.is_configured():
            return err("Email isn't set up on this server yet, so it can only be pinned.")
        recips = announcements.recipients(list_all(), str(data.get("group") or ""))
        if not recips:
            return err("Nobody is in that group right now.")
        if not _announce_lock.acquire(blocking=False):
            return err("An email send is still running. Wait for it to finish.", 409)
    group = str(data.get("group") or "")
    label = next((g["label"] for g in announcements.groups(list_all(), load_config().get("tiers") or []) if g["key"] == group), group)
    try:
        entry = announcements.post(title, text, link, pin)
        if mail:
            announcements.set_email_status(entry["id"], group=group, group_label=label, total=len(recips),
                                           sent=0, failed=0, first_error="", done=False,
                                           started_at=datetime.now(timezone.utc).isoformat())
            _announce_run["id"] = entry["id"]
    except Exception:
        if mail:
            _announce_lock.release()
        raise
    if mail:
        try:
            threading.Thread(target=_run_announcement_emails, args=(entry["id"], recips, title, text, link), daemon=True).start()
        except Exception:
            _announce_run["id"] = None
            _announce_lock.release()
            raise
    return jsonify({"success": True, "id": entry["id"], "pinned": pin, "total": len(recips)})

@app.route("/admin/announce/unpin", methods=["POST"])
def admin_announce_unpin():
    if not check_admin(request):
        return err("Unauthorized", 401)
    announcements.unpin()
    return jsonify({"success": True})

@app.route("/admin/announce/preview", methods=["POST"])
def admin_announce_preview():
    if not check_admin(request):
        return jsonify({"success": False, "error": "Not logged in."}), 401
    data = request.get_json(silent=True) or {}
    t, x = announcements.clean_title(data.get("title")), announcements.clean_text(data.get("text"))
    if not t and not x:
        return jsonify({"success": False, "error": "Write a title or a message first."}), 400
    msg = email_sender.preview_announcement(t, x, announcements.clean_link(data.get("link")), _sample_tier())
    return jsonify({"success": True, "subject": msg["subject"], "html": msg["html"]})

@app.route("/admin/announce/test", methods=["POST"])
def admin_announce_test():
    if not check_admin(request):
        return jsonify({"success": False, "error": "Not logged in."}), 401
    data = request.get_json(silent=True) or {}
    to = str(data.get("to") or "").strip()
    if len(to) > 254 or "@" not in to[1:] or any(c in to for c in " \r\n<>,;"):
        return jsonify({"success": False, "message": "That doesn't look like an email address."}), 400
    t, x = announcements.clean_title(data.get("title")), announcements.clean_text(data.get("text"))
    if not t and not x:
        return jsonify({"success": False, "message": "Write a title or a message first."}), 400
    ok_, message = email_sender.send_test_announcement(to, t, x, announcements.clean_link(data.get("link")), _sample_tier())
    return jsonify({"success": ok_, "message": message}), (200 if ok_ else 502)


# ── GET /revocation-list ──
@app.route("/revocation-list", methods=["GET"])
def revocation_list():
    rev_file = DATA_DIR / "revocation_list.json"
    if not rev_file.exists():
        return jsonify({"credential_ids": [], "bundle_hashes": [], "updated_at": None})
    with open(rev_file) as f:
        return jsonify(json.load(f))


# ── GET /status ──
@app.route("/status", methods=["GET"])
def status():
    cfg = load_config()
    issuer = cfg['creator_name']
    try:
        from member_registry import stats
        s = stats()
        return ok({
            "service":    "Credential Protocol API",
            "issuer":     issuer,
            "stats":      s,
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        return ok({
            "service":   "Credential Protocol API",
            "issuer":    issuer,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

# ── GET /admin/members ──
# Creator view of every issued credential, with a Revoke button per row.
# Gated by a real login (see /admin/login) — no more secret sitting in a
# bookmarked URL. /revoke itself still also accepts the old header/query
# secret for scripts (see check_admin), this page just no longer needs to.
@app.route("/admin/members", methods=["GET"])
def admin_members():
    redirect_resp = require_admin_page("/admin/members")
    if redirect_resp:
        return redirect_resp

    cfg = load_config()

    from member_registry import list_all
    from urllib.parse import quote
    members = sorted(list_all(), key=lambda m: m.get("issued_at", ""), reverse=True)

    # Where a member's personal access link points: the same
    # `{members page}?id=..&h=..` shape email_sender.py puts in the welcome
    # email. With no email service set up (or when an email just didn't
    # arrive), the creator copies it from here and sends it by hand — it's
    # the member's way in. "Members page address" must be set to the real page
    # where the widget is embedded, or the link goes nowhere useful.
    members_page = (cfg.get("members_page") or "").strip()
    members_page_unset = not members_page          # empty only if the server's own address is unknown

    # "Expiring soon" uses the reminder window when reminders are on, else a week.
    soon_days = cfg.get("reminder_days") or 7
    email_ready = email_sender.is_configured()
    now_utc = datetime.now(timezone.utc)

    rows = ""
    for m in members:
        revoked = bool(m.get("revoked"))
        active_now = limits.is_active(m, now_utc)
        if revoked:
            status_label = "REVOKED"
        elif not active_now:
            status_label = "EXPIRED"
        elif reminders.is_expiring_soon(m, soon_days, now_utc):
            status_label = f"active · ends in {reminders.days_left(m, now_utc)}d"
        else:
            status_label = "active"
        is_tk = m.get("kind") == "ticket"
        used_at = m.get("used_at") if is_tk else None
        if used_at and not revoked:
            status_label = f'USED<br><span class="small">{esc_html(str(used_at)[:16].replace("T", " "))} UTC</span>'
        if m.get("reminded_at") and m.get("reminded_for") == m.get("expires_at"):
            status_label += f'<br><span class="small">reminded {esc_html(m["reminded_at"][:10])}</span>'
        if m.get("extended_at"):
            status_label += f'<br><span class="small">extended {esc_html(m["extended_at"][:10])}</span>'
        # Distinct-IP count — a lightweight, opt-in-free signal for spotting
        # a shared/copied credential. A normal member is usually 1-2 (home +
        # phone); many distinct addresses is worth a manual look. Hover the
        # number to see the actual addresses (from the bounded log kept in
        # member_registry.mark_verified — not a full audit trail).
        ip_log      = m.get('verification_log', [])
        ip_list     = sorted(set(e.get('ip') for e in ip_log if e.get('ip')))
        ip_count    = len(ip_list) if ip_list else '—'
        ip_title    = ', '.join(ip_list)

        # holder_name/email/tier/sections all come from the public signup
        # form, so they're escaped before landing in this admin page — an
        # unescaped version here would be a stored-XSS opening (a signup
        # with a <script> tag as their name running in the admin's browser).
        cred_id  = esc_html(m.get('credential_id', ''))
        name_esc = esc_html(m.get('holder_name', ''))
        email_esc = esc_html(m.get('holder_email', ''))
        tier_esc  = esc_html(m.get('tier', ''))
        sections_esc = esc_html(', '.join(m.get('sections', [])) or '—')

        tier_cfg_m = get_tier(cfg, m.get("tier")) or {}
        try:
            default_days = int(tier_cfg_m.get("expiry_days") or 30)
        except (ValueError, TypeError):
            default_days = 30
        default_days = min(max(default_days, 1), member_registry.MAX_EXTEND_DAYS)
        is_cl = m.get("kind") == "collectible"
        if revoked or is_cl:                    # a collectible never expires: nothing to extend
            extend_cell = '—'
        else:
            notify_box = ('<label class="small"><input type="checkbox" class="extend-notify" checked> email them</label>'
                          if email_ready else '')
            extend_cell = (f'<div class="extend-box"><input class="extend-days" type="number" min="1" '
                           f'max="{member_registry.MAX_EXTEND_DAYS}" value="{default_days}" aria-label="Days to add"> '
                           f'<button class="extend-btn" data-id="{cred_id}" data-name="{name_esc}">Extend</button>'
                           f'{notify_box}<span class="small extend-msg"></span></div>')

        if is_tk:
            _ev = m.get("event") if isinstance(m.get("event"), dict) else {}
            tier_esc += ('<br><span class="small">ticket'
                         + (f' · {esc_html(str(_ev.get("name") or ""))}' if _ev.get("name") else "") + '</span>')
        if is_cl:
            _dr = m.get("drop") if isinstance(m.get("drop"), dict) else {}
            _num = f' · #{esc_html(str(_dr.get("edition")))}' + (f' of {esc_html(str(_dr.get("of")))}' if _dr.get("of") else "") if _dr.get("edition") else ""
            tier_esc += f'<br><span class="small">collectible{_num}</span>'
        if isinstance(m.get("payment"), dict) and m["payment"].get("comped"):
            tier_esc += '<br><span class="small">given free</span>'

        revoke_cell = '—' if revoked else (
            f'<button class="revoke-btn" data-id="{cred_id}" data-name="{name_esc}">Revoke</button>'
        )
        if is_tk and not revoked:
            if used_at:
                use_btn = f'<button class="use-btn undo" data-id="{cred_id}" data-name="{name_esc}" data-do="undo">Undo check-in</button>'
            elif active_now:
                use_btn = f'<button class="use-btn" data-id="{cred_id}" data-name="{name_esc}" data-do="use">Mark as used</button>'
            else:
                use_btn = ''
            revoke_cell = f'<div class="use-box">{use_btn}{revoke_cell}</div>'

        # The link carries the member's credential ID and the first 32
        # characters of their bundle hash — exactly what the welcome email
        # sends. No link for a revoked credential (it would just be
        # rejected) or for an old entry that never stored a bundle hash.
        bundle_hash = m.get("bundle_hash") or ""
        if revoked or not bundle_hash or not members_page:
            link_cell = '—'
        else:
            sep = "&" if "?" in members_page else "?"
            access_link = (f"{members_page}{sep}id={quote(m.get('credential_id', ''), safe='')}"
                           f"&h={quote(bundle_hash[:32], safe='')}")
            link_cell = (f'<button class="copy-link-btn" data-link="{esc_html(access_link)}">'
                         f'Copy link</button>')

        if revoked:
            st = "revoked"
        elif not active_now:
            st = "expired"
        elif reminders.is_expiring_soon(m, soon_days, now_utc):
            st = "soon"
        else:
            st = "active"
        na = lambda cell: " na" if cell == "—" else ""
        rows += f"""
        <tr class="mrow" data-st="{st}">
          <td class="c-name" data-label="Name">{name_esc}</td>
          <td class="c-email" data-label="Email">{email_esc}</td>
          <td class="c-tier" data-label="Tier">{tier_esc}</td>
          <td class="c-sections" data-label="Sections">{sections_esc}</td>
          <td class="c-issued" data-label="Issued">{(m.get('issued_at') or '')[:16].replace('T',' ')}</td>
          <td class="exp-cell c-exp" data-label="Expires">{"never" if is_cl else (m.get('expires_at') or '')[:16].replace('T',' ')}</td>
          <td class="status-cell c-status" data-label="Status">{status_label}</td>
          <td class="c-ver" data-label="Verified">{m.get('verified_count', 0)}</td>
          <td class="c-ips" data-label="IPs" title="{esc_html(ip_title)}">{ip_count}</td>
          <td class="c-link{na(link_cell)}" data-label="Access link">{link_cell}</td>
          <td class="c-extend{na(extend_cell)}" data-label="Extend by (days)">{extend_cell}</td>
          <td class="c-revoke{na(revoke_cell)}" data-label="Revoke">{revoke_cell}</td>
          <td class="c-delete" data-label="Delete"><button class="delete-btn" data-id="{cred_id}" data-name="{name_esc}">Delete</button></td>
        </tr>"""

    accent = esc_html(cfg["accent_color"])
    title  = esc_html(cfg["card_title"])
    theme_css = admin_theme.css(cfg["admin_style"], cfg["accent_color"], "wide")
    theme_js = admin_theme.shell_js(cfg["admin_style"])
    body_attrs = admin_theme.body_attrs(cfg["admin_style"], "members", cfg["card_title"])

    members_page_warning = ""
    if members_page_unset:
        members_page_warning = (
            '<div class="warn">⚠ Your <b>Members page address</b> isn\'t set yet '
            f'(it\'s currently "{esc_html(members_page) or "empty"}"), so copied links won\'t work. '
            'Set it on the <a href="/admin/dashboard">Dashboard</a> (Branding → Members page address) to the page '
            'of your site with the widget, save, then come back.</div>'
        )

    checkin_link = '<a href="/admin/checkin">Check-in (tickets) →</a>' if any(card_kinds.is_ticket(t) for t in (cfg.get("tiers") or [])) else ""
    tier_opts = ""
    for t in (cfg.get("tiers") or []):
        try:
            td = int(t.get("expiry_days") or 30)
        except (ValueError, TypeError):
            td = 30
        tk_attr = ' data-ticket="1"' if card_kinds.is_ticket(t) else ""
        tier_opts += (f'<option value="{esc_html(t.get("name", ""))}" data-days="{td}"{tk_attr}>'
                      f'{esc_html(t.get("label") or t.get("name", ""))} ({esc_html(t.get("name", ""))})</option>')
    if tier_opts:
        issue_notify = ('<label class="small"><input type="checkbox" id="issue-notify" checked> email them their card</label>'
                        if email_ready else
                        '<span class="small">Email isn\'t set up, so you\'ll copy their link and send it yourself.</span>')
        issue_box = f"""
  <details class="issue-box" id="issue-box">
    <summary>+ Send a card (free)</summary>
    <div class="issue-grid">
      <label>Name<input id="issue-name" maxlength="100"></label>
      <label>Email<input id="issue-email" type="email" maxlength="254"></label>
      <label>Tier<select id="issue-tier">{tier_opts}</select></label>
      <label>Days (blank = the tier's length)<input id="issue-days" type="number" min="1" max="{member_registry.MAX_EXTEND_DAYS}" placeholder=""></label>
    </div>
    <div class="issue-opts">
      {issue_notify}
      <label class="small"><input type="checkbox" id="issue-ignore"> ignore limits (full tier / email already has a card)</label>
    </div>
    <button type="button" class="issue-submit" id="issue-btn">Send card</button>
    <div class="small" id="issue-msg" style="margin-top:8px;min-height:14px;"></div>
    <div id="issue-link-row" style="display:none;margin-top:6px;">
      <button type="button" class="copy-link-btn" id="issue-copy">Copy their link</button>
      <a href="/admin/members" class="small" style="color:var(--accent-text);margin-left:10px;">Reload the list</a>
    </div>
    <div class="small" style="margin-top:8px;">No payment is recorded; the card works exactly like a bought one and is marked "given free" in the list. Revoke or Extend it like any other.</div>
  </details>"""
    else:
        issue_box = ""

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Members — Admin</title>
<style>
  body {{ background:var(--bg); color:var(--fg); font-family:var(--font); padding:32px; }}
  h1 {{ color:var(--accent-text); font-size:16px; letter-spacing:2px; text-transform:uppercase; }}
  table {{ width:100%; border-collapse:collapse; margin-top:20px; font-size:12px; }}
  th, td {{ text-align:left; padding:8px 12px; border-bottom:1px solid var(--line); }}
  th {{ color:var(--accent-text); text-transform:uppercase; font-size:10px; letter-spacing:1px; }}
  tr:hover {{ background:var(--field); }}
  .count {{ color:var(--muted); font-size:11px; margin-top:6px; }}
  .revoke-btn {{
    background:transparent; border:1px solid var(--accent-text); color:var(--accent-text);
    font-family:var(--font); font-size:10px; letter-spacing:1px;
    text-transform:uppercase; padding:5px 10px; cursor:pointer;
  }}
  .revoke-btn:hover {{ background:var(--accent); color:var(--on-accent); }}
  .revoke-btn:disabled {{ opacity:0.5; cursor:default; }}
  .use-box {{ display:flex; gap:6px; flex-wrap:wrap; align-items:center; }}
  .use-btn {{ background:var(--accent); border:1px solid var(--accent-text); color:var(--on-accent); font-family:var(--font); font-size:10px;
    letter-spacing:1px; text-transform:uppercase; padding:5px 10px; cursor:pointer; white-space:nowrap; }}
  .use-btn.undo {{ background:transparent; color:var(--accent-text); }}
  .use-btn:disabled {{ opacity:0.5; cursor:default; }}
  .copy-link-btn {{
    background:var(--accent); border:1px solid var(--accent-text); color:var(--on-accent);
    font-family:var(--font); font-size:10px; letter-spacing:1px;
    text-transform:uppercase; padding:5px 10px; cursor:pointer; white-space:nowrap;
  }}
  .small {{ color:var(--muted); font-size:10px; }}
  .delete-btn {{ background:transparent; border:1px solid var(--muted); color:var(--soft); font-family:var(--font); font-size:10px;
    letter-spacing:1px; text-transform:uppercase; padding:5px 10px; cursor:pointer; }}
  .delete-btn:hover {{ border-color:var(--bad); color:var(--bad); }}
  .delete-btn:disabled {{ opacity:0.5; cursor:default; }}
  .extend-box {{ display:flex; gap:6px; align-items:center; flex-wrap:wrap; min-width:190px; }}
  .extend-days {{ width:64px; background:var(--field); border:1px solid var(--line); color:var(--fg);
                  font-family:var(--font); font-size:12px; padding:4px 6px; }}
  .extend-btn, .issue-submit {{
    background:transparent; border:1px solid var(--accent-text); color:var(--accent-text);
    font-family:var(--font); font-size:10px; letter-spacing:1px;
    text-transform:uppercase; padding:5px 10px; cursor:pointer;
  }}
  .extend-btn:hover, .issue-submit:hover {{ background:var(--accent); color:var(--on-accent); }}
  .extend-btn:disabled, .issue-submit:disabled {{ opacity:0.5; cursor:default; }}
  .issue-box {{ border:1px solid var(--line); padding:12px 16px; margin:16px 0 0; max-width:760px; }}
  .issue-box summary {{ cursor:pointer; color:var(--accent-text); font-size:11px; letter-spacing:1px; text-transform:uppercase; }}
  .issue-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:10px; margin:12px 0; }}
  .issue-grid label {{ display:block; color:var(--muted); font-size:10px; letter-spacing:1px; text-transform:uppercase; }}
  .issue-grid input, .issue-grid select {{ display:block; width:100%; box-sizing:border-box; margin-top:4px; background:var(--field); border:1px solid var(--line);
    color:var(--fg); font-family:var(--font); font-size:12px; padding:6px 8px; text-transform:none; letter-spacing:0; }}
  .issue-opts {{ display:flex; gap:18px; flex-wrap:wrap; margin-bottom:12px; }}
  .warn {{ background:var(--warn-bg); color:var(--warn); font-size:11px; line-height:1.6; padding:10px 14px; margin:14px 0 0; }}
  .warn a {{ color:var(--warn); }}
  .nav {{ margin-bottom:18px; font-size:11px; letter-spacing:1px; }}
  .nav a {{ color:var(--accent-text); text-decoration:none; margin-right:18px; }}
  .nav a:hover {{ text-decoration:underline; }}
{theme_css}</style></head>
<body {body_attrs}>
  <div class="nav"><a href="/admin/dashboard">← Dashboard</a><a href="/admin/content">Content →</a><a href="/admin/announce">Announce →</a>{checkin_link}<a href="/admin/logout">Log out</a></div>
  <h1>{title} — Members ({len(members)})</h1>
  <div class="count">Newest first.</div>
  <details class="mhelp" open><summary>What do these columns and buttons mean?</summary>
  <div class="count"><b>IPs</b>: how many different places used this card. 1-2 is normal. Many more may mean it's being shared.</div>
  <div class="count"><b>Extend</b>: adds days to a member's access. Same card, same link; only the end date moves. An expired card restarts from today.</div>
  <div class="count"><b>Delete</b>: removes a member for good. Their card and link stop working. To only cut off access and keep the record, use Revoke.</div>
  <div class="count"><b>Copy link</b>: copies the member's personal link. Send it yourself if email isn't set up. Treat it like a password.</div>
  <div class="count"><b>Mark as used</b> (event tickets): lets the person in and switches their ticket off, so a copy can't be used twice. At the door the <a href="/admin/checkin" style="color:var(--accent-text);">Check-in</a> page does this for you.</div>
  </details>
  {members_page_warning}
  {issue_box}
  <table>
    <tr class="mhead"><th>Name</th><th>Email</th><th>Tier</th><th>Sections</th><th>Issued</th><th>Expires</th><th>Status</th><th>Verified ×</th><th>IPs</th><th>Access link</th><th>Extend by (days)</th><th>Revoke</th><th>Delete</th></tr>
    {rows}
  </table>
  <script>
    (function() {{
      // Phone + app layout: members are cards (tap one to open it) and the long help text starts folded.
      const help = document.querySelector('.mhelp');
      try {{ if (help && document.body.getAttribute('data-layout') === 'app' && window.matchMedia && window.matchMedia('(max-width:899px)').matches) help.open = false; }} catch (e) {{}}
      document.querySelectorAll('tr.mrow').forEach(row => {{
        row.addEventListener('click', e => {{
          if (e.target.closest('button, input, a, label, select, textarea')) return;
          row.classList.toggle('open');
        }});
      }});
    }})();

    // Event tickets: mark as used (let in) / undo a mistaken check-in.
    document.querySelectorAll('.use-btn').forEach(btn => {{
      btn.addEventListener('click', () => {{
        const undo = btn.dataset.do === 'undo';
        if (!confirm(undo ? `Undo the check-in for ${{btn.dataset.name}}? Their ticket works again.`
                          : `Mark ${{btn.dataset.name}}'s ticket as used? It stops working after this.`)) return;
        btn.disabled = true;
        fetch('/admin/checkin/' + (undo ? 'undo' : 'use'), {{
          method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ credential_id: btn.dataset.id }}),
        }}).then(r => r.json()).then(d => {{
          if (d.success) location.reload(); else {{ btn.disabled = false; alert(d.error || 'Failed.'); }}
        }}).catch(() => {{ btn.disabled = false; alert('Could not reach the server.'); }});
      }});
    }});

    document.querySelectorAll('.copy-link-btn').forEach(btn => {{
      btn.addEventListener('click', () => {{
        const link = btn.dataset.link;
        const original = btn.textContent;
        const done = () => {{
          btn.textContent = 'Copied \\u2713';
          setTimeout(() => {{ btn.textContent = original; }}, 1800);
        }};
        const fallback = () => {{
          const ta = document.createElement('textarea');
          ta.value = link;
          document.body.appendChild(ta);
          ta.select();
          try {{ document.execCommand('copy'); done(); }}
          catch (e) {{ window.prompt('Copy this link:', link); }}
          ta.remove();
        }};
        if (navigator.clipboard && window.isSecureContext) {{
          navigator.clipboard.writeText(link).then(done, fallback);
        }} else {{
          fallback();
        }}
      }});
    }});

    (function() {{
      const btn = document.getElementById('issue-btn');
      if (!btn) return;
      const f = id => document.getElementById(id);
      const msg = f('issue-msg'), linkRow = f('issue-link-row');
      let link = '';
      function say(t, good) {{ msg.textContent = t; msg.style.color = good ? 'var(--ok)' : 'var(--bad)'; }}
      function defaultDays() {{
        const o = f('issue-tier').selectedOptions[0];
        const tk = !!(o && o.dataset.ticket);
        f('issue-days').placeholder = tk ? 'until the event ends' : (o ? o.dataset.days : '');
        f('issue-days').disabled = tk;
        if (tk) f('issue-days').value = '';
      }}
      f('issue-tier').addEventListener('change', defaultDays); defaultDays();
      btn.addEventListener('click', () => {{
        const name = f('issue-name').value.trim(), email = f('issue-email').value.trim();
        if (!name) {{ say('Enter their name.', false); return; }}
        if (email.indexOf('@') < 1) {{ say('Enter their email address.', false); return; }}
        const tier = f('issue-tier').value;
        if (!confirm(`Give ${{name}} (${{email}}) a free ${{tier}} card?`)) return;
        btn.disabled = true; linkRow.style.display = 'none'; say('Sending…', true);
        const nb = f('issue-notify');
        fetch('/admin/members/issue', {{
          method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ name: name, email: email, tier: tier, days: f('issue-days').value,
                                 notify: !!(nb && nb.checked), ignore_limits: f('issue-ignore').checked }}),
        }}).then(r => r.json()).then(data => {{
          btn.disabled = false;
          if (!data.success) {{ say(data.error || 'Failed.', false); return; }}
          const mail = {{ sent: ' The card was emailed to them.', failed: ' (The email could not be sent. Copy their link and send it yourself.)',
                         not_configured: ' (Email is not set up. Copy their link and send it yourself.)',
                         not_requested: ' Copy their link and send it to them.' }}[data.email] || '';
          say('Card issued, valid until ' + data.expires_at.slice(0, 10) + '.' + mail, data.email !== 'failed');
          link = data.link || '';
          linkRow.style.display = '';
          f('issue-copy').style.display = link ? '' : 'none';
          if (!link) say(msg.textContent + ' (Set the Members page address on the Dashboard to get a copyable link.)', true);
          f('issue-name').value = ''; f('issue-email').value = ''; f('issue-days').value = '';
        }}).catch(e => {{ btn.disabled = false; say('Failed: ' + e.message, false); }});
      }});
      f('issue-copy').addEventListener('click', () => {{
        const b = f('issue-copy'), orig = 'Copy their link';
        const done = () => {{ b.textContent = 'Copied \\u2713'; setTimeout(() => {{ b.textContent = orig; }}, 1800); }};
        if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(link).then(done, () => window.prompt('Copy this link:', link));
        else window.prompt('Copy this link:', link);
      }});
    }})();

    document.querySelectorAll('.delete-btn').forEach(btn => {{
      btn.addEventListener('click', () => {{
        const name = btn.dataset.name;
        if (!confirm(`Delete ${{name}} for good? Their record, card and files are erased and this can't be undone.`)) return;
        const typed = window.prompt('To confirm, type DELETE (in capitals):');
        if (typed !== 'DELETE') return;
        btn.disabled = true; btn.textContent = 'Deleting...';
        fetch('/admin/members/delete', {{
          method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ credential_id: btn.dataset.id, confirm: 'DELETE' }}),
        }}).then(r => r.json()).then(data => {{
          if (data.success) {{
            if (data.problems && data.problems.length) alert('Deleted, but some files could not be removed:\\n' + data.problems.join('\\n'));
            location.reload();
          }} else {{
            alert('Delete failed: ' + (data.error || 'unknown error'));
            btn.disabled = false; btn.textContent = 'Delete';
          }}
        }}).catch(e => {{ alert('Delete failed: ' + e.message); btn.disabled = false; btn.textContent = 'Delete'; }});
      }});
    }});

    document.querySelectorAll('.extend-btn').forEach(btn => {{
      btn.addEventListener('click', () => {{
        const box   = btn.closest('.extend-box');
        const row   = btn.closest('tr');
        const msg   = box.querySelector('.extend-msg');
        const days  = parseInt(box.querySelector('.extend-days').value, 10);
        const notifyBox = box.querySelector('.extend-notify');
        if (!(days >= 1)) {{ msg.textContent = 'Enter a number of days.'; msg.style.color = 'var(--bad)'; return; }}
        if (!confirm(`Add ${{days}} days to ${{btn.dataset.name}}'s access?`)) return;
        btn.disabled = true;
        msg.textContent = '';
        fetch('/admin/members/extend', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ credential_id: btn.dataset.id, days: days, notify: !!(notifyBox && notifyBox.checked) }}),
        }})
          .then(r => r.json())
          .then(data => {{
            btn.disabled = false;
            if (!data.success) {{ msg.textContent = data.error || 'Failed.'; msg.style.color = 'var(--bad)'; return; }}
            row.querySelector('.exp-cell').textContent = data.expires_at.slice(0, 16).replace('T', ' ');
            row.querySelector('.status-cell').textContent = 'active · extended just now';
            const mail = {{ sent: ' Email sent.', failed: ' (Email could not be sent.)',
                           not_configured: ' (Email is not set up, so nobody was emailed.)' }}[data.email] || '';
            msg.textContent = '+' + data.days_added + ' days.' + mail;
            msg.style.color = data.email === 'failed' ? 'var(--bad)' : 'var(--ok)';
          }})
          .catch(e => {{ btn.disabled = false; msg.textContent = 'Failed: ' + e.message; msg.style.color = 'var(--bad)'; }});
      }});
    }});

    // No secret to embed here anymore — the browser's session cookie
    // (set at /admin/login) is what authorizes this fetch call now.
    document.querySelectorAll('.revoke-btn').forEach(btn => {{
      btn.addEventListener('click', () => {{
        const id   = btn.dataset.id;
        const name = btn.dataset.name;
        if (!confirm(`Revoke access for ${{name}}? This takes effect immediately and can't be undone from here.`)) return;

        btn.disabled = true;
        btn.textContent = 'Revoking...';

        fetch('/revoke', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ credential_id: id }}),
        }})
          .then(r => r.json())
          .then(data => {{
            if (data.success) {{
              location.reload();
            }} else {{
              alert('Revoke failed: ' + (data.error || 'unknown error'));
              btn.disabled = false;
              btn.textContent = 'Revoke';
            }}
          }})
          .catch(e => {{
            alert('Revoke failed: ' + e.message);
            btn.disabled = false;
            btn.textContent = 'Revoke';
          }});
      }});
    }});
  </script>
{theme_js}
</body></html>"""
    return html


# ── Admin login (replaces the old ?secret= URL param) ──
# One admin, one password (ADMIN_SECRET) — no accounts system. The point
# isn't multi-user auth, it's getting the secret out of the URL/history/
# logs and into a real session cookie instead.
def _login_page(error: str = None, next_path: str = "/admin/dashboard") -> str:
    cfg = load_config()
    accent = esc_html(cfg["accent_color"])
    title  = esc_html(cfg["card_title"])
    next_esc = esc_html(next_path)
    theme_css = admin_theme.css(cfg["admin_style"], cfg["accent_color"], "login")
    error_html = f'<div class="error">{esc_html(error)}</div>' if error else ""
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Admin Login</title>
<style>
  body {{ background:var(--bg); color:var(--fg); font-family:var(--font);
          display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; }}
  .box {{ width:100%; max-width:320px; padding:32px; }}
  h1 {{ color:var(--accent-text); font-size:14px; letter-spacing:2px; text-transform:uppercase; margin-bottom:24px; }}
  input {{ width:100%; background:var(--field); border:1px solid var(--line); color:var(--fg);
           font-family:var(--font); font-size:13px; padding:10px 12px; margin-bottom:14px; }}
  button {{ width:100%; background:var(--accent); color:var(--on-accent); border:none; font-family:var(--font);
            font-size:12px; letter-spacing:2px; text-transform:uppercase; padding:12px; cursor:pointer; }}
  .error {{ color:var(--bad); font-size:11px; margin-bottom:14px; }}
{theme_css}</style></head>
<body>
  <form class="box" method="POST" action="/admin/login">
    <h1>{title} — Admin</h1>
    {error_html}
    <input type="hidden" name="next" value="{next_esc}">
    <input type="password" name="password" placeholder="Admin password" autofocus required>
    <button type="submit">Log in</button>
  </form>
</body></html>"""

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    next_path = request.values.get("next") or "/admin/dashboard"
    if not next_path.startswith("/"):
        next_path = "/admin/dashboard"  # guard against an open redirect via ?next=

    if request.method == "GET":
        if is_admin_session():
            return redirect(next_path)
        return _login_page(next_path=next_path)

    if not ADMIN_SECRET:
        return _login_page(error="ADMIN_SECRET is not set on this deployment — no login is possible yet. See SETUP.md.", next_path=next_path)

    key = _login_key()
    wait = _login_guard.seconds_locked(key)
    if wait:
        mins = max(1, (wait + 59) // 60)
        return _login_page(error=f"Too many wrong passwords. Try again in about {mins} minute{'s' if mins != 1 else ''}.",
                           next_path=next_path), 429

    password = request.form.get("password", "")
    if not security.same_secret(password, ADMIN_SECRET):
        _login_guard.fail(key)
        return _login_page(error="Wrong password.", next_path=next_path)

    _login_guard.success(key)
    session.clear()
    session.permanent = True
    session["admin_authed"] = True
    session["csrf"] = secrets.token_urlsafe(32)
    return redirect(next_path)

@app.route("/admin/logout", methods=["GET"])
def admin_logout():
    session.clear()
    return redirect("/admin/login")


# ── GET/POST /admin/dashboard ──
# Edit this deployment's branding and tiers (config.json) through a UI
# instead of hand-editing the file. Email theming (email_sender.py) and
# the member card already read config.json, so a save here takes effect
# everywhere without touching code. Payment is a placeholder for now —
# tier prices are display-only until real billing is wired up.
@app.route("/admin/dashboard", methods=["GET"])
def admin_dashboard():
    redirect_resp = require_admin_page("/admin/dashboard")
    if redirect_resp:
        return redirect_resp
    _migrate_card_looks()
    return _dashboard_page()

def _encode_upload_as_data_uri(file_storage) -> tuple:
    """A dashboard logo upload -> (data: URI, "") or ("", reason it was not
    used). ("", "") when no file was chosen at all (an empty file input
    still submits a FileStorage with an empty filename). The picture is
    validated, shrunk and re-encoded in logo_utils.py."""
    if not file_storage or not file_storage.filename:
        return "", ""
    raw = file_storage.read(logo_utils.MAX_UPLOAD_BYTES + 1)
    return logo_utils.process_logo(raw)

@app.route("/admin/dashboard", methods=["POST"])
def admin_dashboard_save():
    redirect_resp = require_admin_page("/admin/dashboard")
    if redirect_resp:
        return redirect_resp

    tier_names    = request.form.getlist("tier_name")
    tier_labels   = request.form.getlist("tier_label")
    tier_prices   = request.form.getlist("tier_price")
    tier_expiries = request.form.getlist("tier_expiry_days")
    tier_sections = request.form.getlist("tier_sections")
    tier_max_members = request.form.getlist("tier_max_members")
    tier_kinds       = request.form.getlist("tier_kind")
    ev_names         = request.form.getlist("tier_event_name")
    ev_starts        = request.form.getlist("tier_event_start")
    ev_ends          = request.form.getlist("tier_event_end")
    ev_places        = request.form.getlist("tier_event_place")
    ev_notes         = request.form.getlist("tier_event_note")
    ev_tzs           = request.form.getlist("tier_event_tz")
    dr_names         = request.form.getlist("tier_drop_name")
    dr_opens         = request.form.getlist("tier_drop_opens")
    dr_closes        = request.form.getlist("tier_drop_closes")
    dr_notes         = request.form.getlist("tier_drop_note")
    dr_tzs           = request.form.getlist("tier_drop_tz")
    have_kinds       = "tier_kind" in request.form
    tier_show_spots  = request.form.getlist("tier_show_spots")
    tier_per_email   = request.form.getlist("tier_per_email")

    # Each tier picks one of the saved card looks (or none = the Default look).
    # Tiers are matched by name to what was saved before, so a tier keeps its
    # look even if this save came from something that doesn't send the picker.
    _migrate_card_looks()
    saved_cfg  = _read_config_file()
    looks_now  = card_looks.clean_looks(saved_cfg.get("card_looks"))
    old_by_name = {str(t.get("name", "")).upper(): t for t in (saved_cfg.get("tiers") or []) if isinstance(t, dict)}
    tier_looks = request.form.getlist("tier_look")
    have_picker = "tier_look" in request.form
    logo_notes = []   # reasons an uploaded picture wasn't used, shown after the save

    tiers = []
    for i in range(len(tier_names)):
        name = (tier_names[i] or "").strip()
        if not name:
            continue  # a blank row from the "add tier" UI — skip it, not an error
        try:
            price = float(tier_prices[i])
        except (ValueError, IndexError):
            price = 0
        try:
            expiry_days = int(tier_expiries[i])
        except (ValueError, IndexError):
            expiry_days = 31
        sections = [s.strip() for s in (tier_sections[i] if i < len(tier_sections) else "").split(",") if s.strip()]

        old_t = old_by_name.get(name.upper()) or {}
        if have_picker:
            look_id = (tier_looks[i] if i < len(tier_looks) else "").strip()
            if not card_looks.get(looks_now, look_id):
                look_id = ""
            legacy_design = None
        else:
            look_id = old_t.get("look") if card_looks.get(looks_now, old_t.get("look")) else ""
            legacy_design = old_t.get("design") if not look_id else None

        # Limits: only stored when they differ from the defaults, so a tier
        # with no limits looks exactly like it always did in config.json.
        max_members = limits.clean_max_members(tier_max_members[i] if i < len(tier_max_members) else "")
        show_spots  = (tier_show_spots[i] if i < len(tier_show_spots) else "show") != "hide"
        per_email   = (tier_per_email[i] if i < len(tier_per_email) else limits.DEFAULT_PER_EMAIL)
        if per_email not in limits.PER_EMAIL_MODES:
            per_email = limits.DEFAULT_PER_EMAIL

        # Card type: an Access pass (the default, stored as nothing) or an Event
        # ticket with its event details. A save that doesn't send the picker keeps
        # what was saved for that tier.
        if have_kinds:
            kind = card_kinds.clean_kind(tier_kinds[i] if i < len(tier_kinds) else "")
            event = card_kinds.clean_event(
                ev_names[i] if i < len(ev_names) else "", ev_starts[i] if i < len(ev_starts) else "",
                ev_ends[i] if i < len(ev_ends) else "", ev_places[i] if i < len(ev_places) else "",
                ev_notes[i] if i < len(ev_notes) else "", ev_tzs[i] if i < len(ev_tzs) else 0)
        else:
            kind = card_kinds.clean_kind(old_t.get("kind"))
            event = card_kinds.event_of(old_t)
        if have_kinds:
            drop = card_kinds.clean_drop(
                dr_names[i] if i < len(dr_names) else "", dr_opens[i] if i < len(dr_opens) else "",
                dr_closes[i] if i < len(dr_closes) else "", dr_notes[i] if i < len(dr_notes) else "",
                dr_tzs[i] if i < len(dr_tzs) else 0)
        else:
            drop = card_kinds.drop_of(old_t)
        if kind == "ticket" and not event["starts_at"]:
            logo_notes.append(f"Ticket \u201c{name.upper()}\u201d needs a start date and time before anyone can get it.")

        tiers.append({
            "name":        name.upper(),
            **({"kind": "ticket", "event": event} if kind == "ticket" else {}),
            **({"kind": "collectible", "drop": drop} if kind == "collectible" else {}),
            "label":       (tier_labels[i] if i < len(tier_labels) else "").strip(),
            "price":       price,
            "expiry_days": expiry_days,
            "sections":    sections,
            **({"max_members": max_members} if max_members else {}),
            **({"show_spots_left": False} if not show_spots else {}),
            **({"per_email": per_email} if (per_email != limits.DEFAULT_PER_EMAIL or kind == "collectible") else {}),
            **({"look": look_id} if look_id else {}),
            **({"design": legacy_design} if legacy_design else {}),
        })

    # Deployment-wide card logo: a new upload wins; otherwise "Remove" clears
    # it; otherwise whatever was saved stays.
    old_global_logo = _read_config_file().get("logo_data_uri", "") or ""
    new_global_logo, g_err = _encode_upload_as_data_uri(request.files.get("global_logo"))
    if g_err:
        logo_notes.append(f"Card logo: {g_err}")
    if new_global_logo:
        global_logo = new_global_logo
    elif request.form.get("global_logo_clear") == "1":
        global_logo = ""
    else:
        global_logo = old_global_logo if logo_utils.is_logo_data_uri(old_global_logo) else ""
    card_style = (request.form.get("card_style") or "").strip()
    if card_style not in CARD_STYLES:
        card_style = "distressed"
    qr_style = (request.form.get("qr_style") or "").strip()
    if qr_style not in card_looks.QR_STYLES:
        qr_style = load_config().get("qr_style", "solid")      # field absent: keep what was saved

    # The Default look's background picture, same rules as the logo.
    old_global_bg = saved_cfg.get("bg_data_uri", "") or ""
    new_global_bg, bg_err = _encode_background_upload(request.files.get("global_bg"))
    if bg_err:
        logo_notes.append(f"Background picture: {bg_err}")
    if new_global_bg:
        global_bg = new_global_bg
    elif request.form.get("global_bg_clear") == "1":
        global_bg = ""
    else:
        global_bg = old_global_bg if logo_utils.is_logo_data_uri(old_global_bg) else ""
    global_bg_dim = (request.form.get("global_bg_dim") or "").strip()
    if global_bg_dim not in card_looks.DIMS:
        old_dim = saved_cfg.get("bg_dim")
        global_bg_dim = old_dim if old_dim in card_looks.DIMS else card_looks.DEFAULT_DIM

    save_config({
        "logo_data_uri": global_logo,
        "bg_data_uri":   global_bg,
        "bg_dim":        global_bg_dim,
        "card_style":    card_style,
        "qr_style":      qr_style,
        "creator_name":  (request.form.get("creator_name") or "").strip() or "Your Creator Name",
        "card_title":     (request.form.get("card_title") or "").strip() or "YOUR BRAND HERE",
        "card_subtitle":  (request.form.get("card_subtitle") or "").strip() or "Member Card",
        "accent_color":   (request.form.get("accent_color") or "").strip() or "#00e87a",
        "members_page":   (request.form.get("members_page") or "").strip(),
        "api_base":       (request.form.get("api_base") or "").strip(),
        "currency":       (request.form.get("currency") or "usd").strip().lower()[:3] or "usd",
        "payment_provider": (request.form.get("payment_provider") or "manual").strip().lower()
                            if (request.form.get("payment_provider") or "").strip().lower() in ("manual", "stripe", "custom")
                            else "manual",
        "manual_payment_instructions": (request.form.get("manual_payment_instructions") or "").strip(),
        "custom_provider_name": custom_payment.clean_name(request.form.get("custom_provider_name")),
        "custom_payment_url":   custom_payment.clean_url(request.form.get("custom_payment_url")),
        "custom_payment_links": custom_payment.clean_links(request.form.get("custom_payment_links")),
        "email_subject":  (request.form.get("email_subject") or "").strip()[:email_sender.MAX_SUBJECT],
        "email_intro":    (request.form.get("email_intro") or "").strip()[:email_sender.MAX_INTRO],
        "email_signoff":  (request.form.get("email_signoff") or "").strip()[:email_sender.MAX_SIGNOFF],
        "reminder_days":    reminders.clean_reminder_days(request.form.get("reminder_days")),
        "reminder_subject": (request.form.get("reminder_subject") or "").strip()[:email_sender.MAX_REMINDER_SUBJECT],
        "reminder_text":    (request.form.get("reminder_text") or "").strip()[:email_sender.MAX_REMINDER_TEXT],
        "reminder_renew_url": email_sender.safe_renew_url(request.form.get("reminder_renew_url")),
        "extended_subject": (request.form.get("extended_subject") or "").strip()[:email_sender.MAX_EXTENDED_SUBJECT],
        "extended_text":    (request.form.get("extended_text") or "").strip()[:email_sender.MAX_EXTENDED_TEXT],
        **widget_look.from_form(request.form),
        "admin_style":    admin_theme.clean_style(request.form.get("admin_style"), load_config()["admin_style"]),
        "tiers":          tiers,
    })

    # Come back to the screen the creator was on (app-style layouts show one
    # settings screen at a time); only known screen names are honoured.
    sec = (request.form.get("sec") or "").strip()
    back = ("#/s/" + sec) if sec in admin_theme.SETTINGS_IDS else ""
    note = (" ".join(logo_notes))[:300]
    if note:
        from urllib.parse import quote as _q
        return redirect("/admin/dashboard?saved=1&logo_note=" + _q(note) + back)
    return redirect("/admin/dashboard?saved=1" + back)

def _setup_checklist_html(cfg: dict, provider: str) -> str:
    """The dashboard's "Setup checklist": what's done and what still needs
    attention on this deployment, worked out from the live state (settings,
    environment variables, storage) rather than anything the creator ticks
    off by hand. Items a deployment can't act on (e.g. Railway volume
    advice when running locally) aren't shown at all."""
    on_railway = bool(os.environ.get("RAILWAY_PROJECT_ID") or os.environ.get("RAILWAY_ENVIRONMENT_NAME"))
    has_storage = DATA_DIR.resolve() != BASE_DIR.resolve()
    members_page = (cfg.get("members_page") or "").strip()
    tiers = cfg.get("tiers") or []
    has_paid_tier = any((t.get("price") or 0) > 0 for t in tiers)

    items = []   # (done, label, detail)

    items.append((
        cfg["creator_name"] != "Your Creator Name" and cfg["card_title"] != "YOUR BRAND HERE",
        "Set your branding",
        "Enter your Creator name and Card title under Branding, then Save.",
    ))

    if on_railway:
        items.append((
            has_storage,
            "Persistent storage (Volume)",
            "No permanent storage yet, so members, your key and settings would be wiped on every redeploy. "
            "In Railway, add a Volume (mount path /data) to this service and redeploy before issuing real cards."
            if not has_storage else
            "Your members, key and settings are saved on a permanent Volume.",
        ))

    items.append((
        bool(os.environ.get("SESSION_SECRET_KEY")),
        "Admin login stays signed in across deploys",
        "Set a SESSION_SECRET_KEY variable (any long random text), or you will be logged out each time the app restarts.",
    ))

    # Always satisfied: with no address of your own, the server's built-in
    # /members page is used (see public_url.py), so links and emails work.
    items.append((
        bool(members_page),
        "Members page",
        "Members open their access link on this page. Leave Branding → Members page address empty to use the one built into this server.",
    ))

    if has_paid_tier:
        if provider == "stripe":
            pay_done = bool(stripe and STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET)
            pay_detail = "Stripe needs the STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET variables (see SETUP.md), or choose another way to pay under Payment."
        elif provider == "custom":
            pay_done = bool(cfg.get("custom_payment_url") or cfg.get("custom_payment_links"))
            pay_detail = "You have a paid tier that sends members to a payment link — paste that link under Payment (and, if you like, a short message for the member), then Save."
        else:
            pay_done = bool((cfg.get("manual_payment_instructions") or "").strip())
            pay_detail = "You have a paid tier you approve yourself — tell members how to pay you by filling in \"Message to the member\" under Payment, then Save."
        items.append((pay_done, "Payments for your paid tier", pay_detail))

    items.append((
        content_store.has_any_content(content_store.load()),
        "Add your members-only content",
        "Nothing is in your members-only area yet. Open Content and add the links, downloads or discount code your members get.",
    ))

    items.append((
        backup.backup_is_recent(DATA_DIR),
        "Download a backup",
        "Download a backup file (Backup & restore) and keep it somewhere safe. This ticks again when your last backup is under 30 days old.",
    ))

    items.append((
        bool(os.environ.get("BREVO_API_KEY") and os.environ.get("GMAIL_ADDRESS")),
        "Email (optional)",
        "Not set up, so members won't be emailed. That's fine: copy each member's link from Members and send it yourself. "
        "To turn emails on, set BREVO_API_KEY and GMAIL_ADDRESS (see SETUP.md).",
    ))

    done_count = sum(1 for d, _, _ in items if d)
    all_done = done_count == len(items)

    rows = ""
    for done, label, detail in items:
        mark = '<span class="chk-ok">✓</span>' if done else '<span class="chk-todo">○</span>'
        rows += (f'<div class="chk-row">{mark}<div><b>{esc_html(label)}</b>'
                 f'<div class="hint">{esc_html(detail)}</div></div></div>')

    summary = ("Setup checklist — all done ✓" if all_done
               else f"Setup checklist — {done_count} of {len(items)} done")
    return f"""
  <details class="checklist" {"" if all_done else "open"}>
    <summary>{summary}</summary>
    {rows}
    <div class="chk-row"><span class="chk-todo">→</span><div><b>Add the widget to your website</b>
      <div class="hint">Copy the two lines from "Embed on your website" just below and paste them into your site. This can't be detected automatically, so it's never ticked.</div></div></div>
  </details>"""

def _welcome_html(cfg: dict) -> str:
    """A short "start here" box for a brand-new deployment: shown until the
    creator has set their branding (or hides it with the button)."""
    fresh = cfg["creator_name"] == "Your Creator Name" and cfg["card_title"] == "YOUR BRAND HERE"
    if not fresh or _read_config_file().get("welcome_hidden"):
        return ""
    return """
  <div class="welcome-box">
    <h2 style="margin-top:0;">Welcome — three steps and you're live</h2>
    <ol>
      <li><b>Name your brand.</b> Under <b>Branding</b>, enter your name and the title for your cards, then press Save.</li>
      <li><b>Check your tiers.</b> Under <b>Tiers &amp; pricing</b> you already have two examples. Rename them, set a price, or add your own.</li>
      <li><b>Put two lines on your website.</b> Copy them from <b>Embed on your website</b> just below and paste them where you want the sign-up box and members area.</li>
    </ol>
    <div class="hint">Everything else (emails, content, tickets, announcements) can wait. You can come back to it any time.</div>
    <form method="POST" action="/admin/welcome/hide" style="margin-top:10px;"><button type="submit" class="copy-btn">Got it, hide this</button></form>
  </div>"""


@app.route("/admin/welcome/hide", methods=["POST"])
def admin_welcome_hide():
    page = require_admin_page("/admin/dashboard")
    if page is not None:
        return page
    save_config({"welcome_hidden": True})
    return redirect("/admin/dashboard")


def _dashboard_page() -> str:
    cfg = load_config()
    accent = esc_html(cfg["accent_color"])
    title  = esc_html(cfg["card_title"])
    theme_css = admin_theme.css(cfg["admin_style"], cfg["accent_color"], "page")
    theme_js = admin_theme.shell_js(cfg["admin_style"])
    body_attrs = admin_theme.body_attrs(cfg["admin_style"], "dashboard", cfg["card_title"])

    try:
        from member_registry import stats
        s = stats()
    except Exception:
        s = {"total": 0, "active": 0, "revoked": 0, "expired": 0}

    if stripe and STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET:
        payment_status_html = '<b style="color:var(--ok);">✓ Stripe is configured</b> — paid tiers will route through checkout.<br>'
    elif stripe and STRIPE_SECRET_KEY:
        payment_status_html = '<b style="color:var(--bad);">⚠ STRIPE_SECRET_KEY is set but STRIPE_WEBHOOK_SECRET is not</b> — checkout will start, but payments will never actually fulfill.<br>'
    else:
        payment_status_html = '<b style="color:var(--bad);">Stripe is not set up yet</b> — add the two keys before using it, or pick another way to pay above.<br>'

    provider = (cfg.get("payment_provider") or "manual").strip().lower()
    if provider not in ("manual", "stripe", "custom"):
        provider = "manual"

    checklist_html = _welcome_html(cfg) + _setup_checklist_html(cfg, provider)

    # What "Sections" on a tier can refer to: the keys of the sections made on
    # the Content page. Warn about any tier section nobody has created yet.
    content_keys = [sec["key"] for sec in content_store.load()["sections"]]
    missing = sorted({str(k).lower() for t in (cfg.get("tiers") or []) for k in (t.get("sections") or [])} - set(content_keys))
    tier_sections_hint = (
        '<div class="hint" style="margin-bottom:8px;">"Sections" are the names of the members-only content you set up on the '
        '<a href="/admin/content" style="color:' + accent + ';">Content</a> page. Right now you have: <b>'
        + (esc_html(", ".join(content_keys)) if content_keys else "none yet") + '</b>.</div>'
        + ('<div class="warn" style="background:var(--warn-bg);color:var(--warn);font-size:11px;line-height:1.6;padding:10px 14px;margin:8px 0;">'
           '⚠ A tier lists section(s) that don\'t exist on the Content page: <b>' + esc_html(", ".join(missing))
           + '</b>. Members of that tier would not get anything for them — create a section with that key, or fix the name.</div>' if missing else "")
    )

    try:
        from payment_requests import list_pending
        pending_requests = list_pending()
    except Exception:
        pending_requests = []

    if pending_requests:
        req_rows = ""
        for r in pending_requests:
            amount = f"{r.get('price','')} {(r.get('currency') or '').upper()}".strip()
            req_rows += f"""
            <tr>
              <td>{esc_html(r.get('holder_name',''))}</td>
              <td>{esc_html(r.get('holder_email',''))}</td>
              <td>{esc_html(r.get('tier',''))}</td>
              <td>{esc_html(amount)}</td>
              <td><code>{esc_html(r.get('request_id',''))}</code></td>
              <td>{(r.get('requested_at') or '')[:16].replace('T',' ')}</td>
              <td>
                <button type="button" class="approve-req-btn" data-id="{esc_html(r['request_id'])}">Approve</button>
                <button type="button" class="reject-req-btn" data-id="{esc_html(r['request_id'])}">Reject</button>
              </td>
            </tr>"""
        pending_requests_html = f"""
        <table>
          <tr><th>Name</th><th>Email</th><th>Tier</th><th>Amount</th><th>Reference</th><th>Requested</th><th></th></tr>
          {req_rows}
        </table>"""
    else:
        pending_requests_html = '<div class="hint">Nothing is waiting right now.</div>'

    try:
        from member_registry import list_all as _registry_list
        from payment_requests import list_all as _requests_list
        _registry, _requests = _registry_list(), _requests_list()
    except Exception:
        _registry, _requests = [], []

    def _limits_panel(t: dict) -> str:
        cap = limits.tier_max(t)
        taken = limits.count_taken(_registry, _requests, t.get("name", ""), ever=limits.is_numbered(t)) if cap else 0
        numbered = limits.is_numbered(t)
        if numbered:
            usage = (f'{taken} of {cap} copies claimed{" — SOLD OUT" if taken >= cap else ""}.' if cap
                     else "No edition size set: anyone can claim one while the drop is open.")
        else:
            usage = (f'Right now: {taken} of {cap} spots in use'
                     f'{" — SOLD OUT" if taken >= cap else ""}.') if cap else "No limit set."
        mode = limits.per_email_mode(t)
        show = t.get("show_spots_left", True) is not False
        def sel(cond): return "selected" if cond else ""
        return f"""
            <div class="design-panel limits-panel">
              <div class="design-field">
                <label><span class="lbl-members">Max members (blank = no limit)</span><span class="lbl-edition">Edition size (blank = open edition)</span></label>
                <input name="tier_max_members" type="number" min="1" step="1" value="{esc_html(str(cap) if cap else '')}" placeholder="no limit">
                <div class="hint" style="margin-top:4px;">{esc_html(usage)}</div>
              </div>
              <div class="design-field">
                <label>Show visitors how many spots are left?</label>
                <select name="tier_show_spots">
                  <option value="show" {sel(show)}>Yes, e.g. "12 left"</option>
                  <option value="hide" {sel(not show)}>No, only show "Sold out" when full</option>
                </select>
              </div>
              <div class="design-field">
                <label>Cards per email address</label>
                <select name="tier_per_email">
                  <option value="one_active" {sel(mode == "one_active")}>One working card at a time</option>
                  <option value="one_ever" {sel(mode == "one_ever")}>Only one ever (good for a free trial)</option>
                  <option value="unlimited" {sel(mode == "unlimited")}>No limit</option>
                </select>
              </div>
            </div>"""

    def _kind_select(kind: str) -> str:
        return ('<select name="tier_kind">'
                + "".join(f'<option value="{k}"{" selected" if k == kind else ""}>{card_kinds.KIND_NAMES[k]}</option>'
                          for k in card_kinds.KINDS)
                + '</select>')

    def _event_panel(t: dict) -> str:
        e = card_kinds.event_of(t)
        return f"""
            <div class="design-panel event-block">
              <div class="design-field wide">
                <label>Event name</label>
                <input name="tier_event_name" maxlength="{card_kinds.MAX_NAME}" value="{esc_html(e['name'])}" placeholder="Halloween Live Show">
              </div>
              <div class="design-field">
                <label>Starts</label>
                <input name="tier_event_start" type="datetime-local" value="{esc_html(e['starts_at'])}">
              </div>
              <div class="design-field">
                <label>Ends (optional)</label>
                <input name="tier_event_end" type="datetime-local" value="{esc_html(e['ends_at'])}">
              </div>
              <div class="design-field">
                <label>Place</label>
                <input name="tier_event_place" maxlength="{card_kinds.MAX_PLACE}" value="{esc_html(e['place'])}" placeholder="Venue, city or link">
              </div>
              <div class="design-field">
                <label>Note on the ticket (optional)</label>
                <input name="tier_event_note" maxlength="{card_kinds.MAX_NOTE}" value="{esc_html(e['note'])}" placeholder="Doors 19:00, standing">
              </div>
              <input type="hidden" name="tier_event_tz" value="{esc_html(str(e['tz']))}">
              <div class="hint event-hint">The ticket stops working when the event ends. If you leave <b>Ends</b> empty, it works for {card_kinds.DEFAULT_HOURS} hours after it starts. Times are the ones you type here, in your own time zone.</div>
            </div>"""

    def _drop_panel(t: dict) -> str:
        d = card_kinds.drop_of(t)
        return f"""
            <div class="design-panel drop-block">
              <div class="design-field wide">
                <label>Drop name (shown on the card)</label>
                <input name="tier_drop_name" maxlength="{card_kinds.MAX_NAME}" value="{esc_html(d['name'])}" placeholder="Midnight Photo Set">
              </div>
              <div class="design-field">
                <label>Opens (optional)</label>
                <input name="tier_drop_opens" type="datetime-local" value="{esc_html(d['opens_at'])}">
              </div>
              <div class="design-field">
                <label>Closes (optional)</label>
                <input name="tier_drop_closes" type="datetime-local" value="{esc_html(d['closes_at'])}">
              </div>
              <div class="design-field wide">
                <label>Note on the card (optional)</label>
                <input name="tier_drop_note" maxlength="{card_kinds.MAX_NOTE}" value="{esc_html(d['note'])}" placeholder="Signed digital print">
              </div>
              <input type="hidden" name="tier_drop_tz" value="{esc_html(str(d['tz']))}">
              <div class="hint event-hint">People can only claim it between <b>Opens</b> and <b>Closes</b> (leave them empty for no window, so it runs until it sells out). Set <b>Edition size</b> below to how many copies exist; every card gets its own number, like #37 of 100. A collectible never expires. Put the drop's links in <b>Content</b> and tick them for this tier. Times are in your own time zone.</div>
            </div>"""

    tier_rows = ""
    for t in cfg["tiers"]:
        look_sel = t.get("look") if card_looks.get(cfg["card_looks"], t.get("look")) else ""
        _tk = card_kinds.clean_kind(t.get("kind"))
        _tcls = " is-ticket" if _tk == "ticket" else " is-collectible" if _tk == "collectible" else ""
        tier_rows += f"""
        <tr class="tier-row{_tcls}">
          <td data-label="Name"><input name="tier_name" value="{esc_html(t.get('name',''))}"></td>
          <td data-label="Label"><input name="tier_label" value="{esc_html(t.get('label',''))}"></td>
          <td data-label="Price"><input name="tier_price" type="number" step="0.01" value="{esc_html(str(t.get('price',0)))}"></td>
          <td data-label="Card type">{_kind_select(_tk)}</td>
          <td data-label="Days of access" class="c-days"><input name="tier_expiry_days" type="number" value="{esc_html(str(t.get('expiry_days',31)))}"><span class="days-note">Until the event ends</span></td>
          <td data-label="Sections (separated by commas)"><input name="tier_sections" value="{esc_html(', '.join(t.get('sections',[])))}" placeholder="downloads, chat"></td>
          <td data-label="Card look"><select name="tier_look">{looks_page.picker_options(cfg, look_sel)}</select></td>
          <td><button type="button" class="design-toggle">More ▾</button></td>
          <td><button type="button" class="remove-tier" title="Remove this tier">×</button></td>
        </tr>
        <tr class="design-row{_tcls}" style="display:none">
          <td colspan="9">
            {_event_panel(t)}
            {_drop_panel(t)}
            {_limits_panel(t)}
          </td>
        </tr>"""

    saved_banner = '<div class="banner">Saved.</div>' if request.args.get("saved") else ""
    if request.args.get("logo_note"):
        saved_banner += ('<div class="banner" style="background:var(--warn-bg);color:var(--warn);text-transform:none;">'
                         '⚠ ' + esc_html(request.args.get("logo_note")[:300]) + '</div>')

    if request.args.get("backup_note"):
        good = bool(request.args.get("backup_ok"))
        saved_banner += (f'<div class="banner" style="{"" if good else "background:var(--warn-bg);color:var(--warn);"}text-transform:none;">'
                         + ('✓ ' if good else '⚠ ') + esc_html(request.args.get("backup_note")[:400]) + '</div>')

    # Backup & restore box (below the main form).
    def _hb(n: int) -> str:
        for unit in ("bytes", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{n:.0f} {unit}" if unit in ("bytes", "KB") else f"{n:.1f} {unit}"
            n /= 1024
    _sz = backup.sizes(DATA_DIR)
    _last = backup.last_backup_at(DATA_DIR)
    if _last:
        _age = (datetime.now(timezone.utc) - _last).days
        _when = _last.strftime("%Y-%m-%d %H:%M UTC") + (" (today)" if _age == 0 else f" ({_age} day{'s' if _age != 1 else ''} ago)")
        _old = _age >= 30
        _last_html = (f'<div class="bk-status {"warn" if _old else "ok"}">{"!" if _old else "&#10003;"} '
                      f'Last backup downloaded: <b>{esc_html(_when)}</b>'
                      + (" — it's getting old, download a fresh one." if _old else '') + '</div>')
    else:
        _last_html = '<div class="bk-status warn">! You have not downloaded a backup yet.</div>'
    _up_btn = (f'<a class="bk-btn" href="/admin/backup/download?files=1">Download backup with uploaded files ({_hb(_sz["data_bytes"] + _sz["uploads_bytes"])})</a>'
               if _sz["uploads_bytes"] else '')
    backup_html = f"""
  <div id="backup" class="backup-box">
    <h2>Backup &amp; restore</h2>
    <div class="hint">Your members ({_sz["members"]}), signing key, settings and content live in one place on this server. If it were ever lost, every card you issued would stop working. A backup is one file you keep somewhere safe.</div>
    {_last_html}
    <div class="warn">The backup file holds your private signing key and your members' emails. Keep it private; don't email it or share it.</div>
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin:10px 0;">
      <a class="bk-btn" href="/admin/backup/download">Download backup ({_hb(_sz["data_bytes"])}: members, key, settings)</a>
      {_up_btn}
    </div>
    <details class="bk-restore">
      <summary>Restore from a backup</summary>
      <div class="hint" style="margin:8px 0;">Use this on a new or empty copy of the app to get everything back, or to go back to an earlier state. It replaces what is on this server now (the old data is kept aside, not deleted). If you're not sure, download a backup first.</div>
      <form method="POST" action="/admin/backup/restore" enctype="multipart/form-data">
        <label>Backup file (.zip)</label>
        <input type="file" name="backup" accept=".zip,application/zip" required>
        <label>Type RESTORE to confirm</label>
        <input name="confirm" autocomplete="off" placeholder="RESTORE" style="max-width:200px;" required>
        <button type="submit" class="bk-btn" style="margin-top:12px;">Restore this backup</button>
      </form>
    </details>
  </div>"""

    g_logo = cfg.get("logo_data_uri") if logo_utils.is_logo_data_uri(cfg.get("logo_data_uri")) else ""
    global_logo_thumb = (f'<img class="logo-thumb" id="global-logo-thumb" src="{esc_html(g_logo)}">' if g_logo
                         else '<span class="no-logo">none — cards show no logo</span>')
    g_style = cfg.get("card_style", "distressed")
    global_bg_state = ('<span class="no-logo" id="global-bg-state">&#10003; picture added</span>' if cfg.get("bg_data_uri")
                       else '<span class="no-logo" id="global-bg-state">none</span>')
    global_qr_options = "".join('<option value="%s"%s>%s</option>' % (q, " selected" if cfg.get("qr_style") == q else "", esc_html(card_looks.QR_NAMES[q]))
                                for q in card_looks.QR_STYLES)
    global_dim_options = "".join('<option value="%s"%s>%s</option>' % (d, " selected" if cfg.get("bg_dim") == d else "", esc_html(card_looks.DIM_NAMES[d]))
                                 for d in card_looks.DIMS)
    looks_section = looks_page.section_html(cfg)

    style_cards = ""
    for k in admin_theme.STYLES:
        nm, desc = admin_theme.LABELS[k]
        sw = admin_theme.swatch(k)
        chips = "".join(f'<i style="background:{c};"></i>' for c in sw)
        style_cards += (f'<label class="style-card{" on" if cfg["admin_style"] == k else ""}">'
                        f'<input type="radio" name="admin_style" value="{k}" {"checked" if cfg["admin_style"] == k else ""}>'
                        f'<span class="sc-sw">{chips}</span><span class="sc-name">{esc_html(nm)}</span>'
                        f'<span class="sc-desc">{esc_html(desc)}</span></label>')

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dashboard — {title}</title>
<style>
  body {{ background:var(--bg); color:var(--fg); font-family:var(--font); padding:32px; max-width:900px; margin:0 auto; }}
  h1 {{ color:var(--accent-text); font-size:16px; letter-spacing:2px; text-transform:uppercase; margin-bottom:4px; }}
  h2 {{ color:var(--accent-text); font-size:12px; letter-spacing:1.5px; text-transform:uppercase; margin:32px 0 12px; border-bottom:1px solid var(--line); padding-bottom:8px; }}
  .nav {{ margin-bottom:18px; font-size:11px; letter-spacing:1px; }}
  .nav a {{ color:var(--accent-text); text-decoration:none; margin-right:18px; }}
  .nav a:hover {{ text-decoration:underline; }}
  .hint {{ color:var(--muted); font-size:11px; line-height:1.6; }}
  .stats {{ display:flex; gap:24px; margin:16px 0 8px; font-size:11px; }}
  .stats b {{ color:var(--accent-text); font-size:16px; display:block; }}
  label {{ display:block; font-size:10px; letter-spacing:1px; color:var(--soft); text-transform:uppercase; margin-bottom:4px; margin-top:14px; }}
  input {{ width:100%; background:var(--field); border:1px solid var(--line); color:var(--fg);
           font-family:var(--font); font-size:12px; padding:8px 10px; box-sizing:border-box; }}
  input[type=color] {{ width:60px; padding:2px; height:32px; }}
  .style-cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:12px; }}
  .style-card {{ display:block !important; margin:0 !important; padding:12px 14px; border:1px solid var(--line); background:var(--panel); cursor:pointer;
                 border-radius:var(--radius); text-transform:none !important; letter-spacing:0 !important; }}
  .style-card input {{ position:absolute; opacity:0; pointer-events:none; width:1px !important; height:1px; }}
  .style-card.on {{ border-color:var(--accent-text); box-shadow:0 0 0 1px var(--accent-text); }}
  .style-card:hover {{ border-color:var(--accent-text); }}
  .sc-sw {{ display:flex; height:22px; margin-bottom:10px; border:1px solid var(--line); border-radius:var(--radius); overflow:hidden; }}
  .sc-sw i {{ flex:1; display:block; }}
  .sc-name {{ display:block; color:var(--fg); font-size:13px !important; font-weight:600; text-transform:none !important; letter-spacing:0 !important; }}
  .sc-desc {{ display:block; color:var(--muted); font-size:11px !important; line-height:1.5; margin-top:3px; text-transform:none !important; letter-spacing:0 !important; font-weight:400; }}
  .wl-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:10px 18px; }}
  .wl-previews {{ display:flex; gap:16px; flex-wrap:wrap; margin-top:14px; }}
  .wl-previews > div {{ flex:1 1 320px; min-width:0; }}
  .wl-frame {{ width:100%; height:460px; border:1px solid var(--line); display:block; }}
  select, textarea {{ width:100%; background:var(--field); border:1px solid var(--line); color:var(--fg);
           font-family:var(--font); font-size:12px; padding:8px 10px; box-sizing:border-box; }}
  textarea {{ resize:vertical; }}
  .approve-req-btn, .reject-req-btn {{
    background:transparent; border:1px solid var(--accent-text); color:var(--accent-text);
    font-family:var(--font); font-size:10px; letter-spacing:1px;
    text-transform:uppercase; padding:5px 10px; cursor:pointer; margin-right:6px;
  }}
  .approve-req-btn:hover {{ background:var(--accent); color:var(--on-accent); }}
  .reject-req-btn {{ border-color:var(--line-strong); color:var(--soft); }}
  .reject-req-btn:hover {{ background:var(--line); color:var(--fg); }}
  .approve-req-btn:disabled, .reject-req-btn:disabled {{ opacity:0.5; cursor:default; }}
  table {{ width:100%; border-collapse:collapse; margin-top:8px; }}
  th {{ text-align:left; font-size:9px; letter-spacing:1px; color:var(--muted); text-transform:uppercase; padding:4px 6px; }}
  td {{ padding:4px 6px; }}
  {looks_page.CSS}
  .remove-tier {{ background:transparent; border:1px solid var(--line); color:var(--soft); cursor:pointer; width:28px; height:28px; }}
  .add-tier, .save-btn {{ background:var(--accent); color:var(--on-accent); border:none; font-family:var(--font);
           font-size:11px; letter-spacing:1.5px; text-transform:uppercase; padding:10px 18px; cursor:pointer; margin-top:12px; }}
  .add-tier {{ background:transparent; border:1px solid var(--accent-text); color:var(--accent-text); }}
  .bk-btn {{ display:inline-block; background:transparent; border:1px solid var(--accent-text); color:var(--accent-text); font-family:var(--font);
             font-size:11px; letter-spacing:1px; text-transform:uppercase; padding:10px 14px; cursor:pointer; text-decoration:none; }}
  .bk-btn:hover {{ background:color-mix(in srgb, var(--accent-text) 14%, transparent); }}
  .backup-box {{ border:1px solid var(--line); background:var(--panel); padding:2px 22px 20px; margin:44px 0 8px; border-radius:var(--radius-lg, 0); }}
  .backup-box h2 {{ margin-top:22px; }}
  .bk-status {{ display:inline-block; font-size:11px; padding:6px 12px; margin:8px 0 4px; border:1px solid var(--line); border-radius:var(--radius, 0); }}
  .bk-status.ok {{ color:var(--ok); background:var(--ok-bg); border-color:transparent; }}
  .bk-status.warn {{ color:var(--warn); background:var(--warn-bg); border-color:transparent; }}
  .backup-box .warn {{ background:var(--warn-bg); color:var(--warn); font-size:11px; line-height:1.6; padding:10px 14px; margin:12px 0; border-radius:var(--radius, 0); }}
  .bk-restore summary {{ cursor:pointer; color:var(--soft); font-size:11px; letter-spacing:1px; text-transform:uppercase; margin:6px 0; }}
  .adv-box summary {{ cursor:pointer; color:var(--accent-text); font-size:12px; margin:4px 0; }}
  .placeholder {{ color:var(--muted); font-size:11px; line-height:1.7; border-left:2px solid var(--line); padding:10px 14px; }}
  .banner {{ background:var(--ok-bg); color:var(--ok); font-size:11px; padding:10px 14px; margin-bottom:16px; letter-spacing:1px; text-transform:uppercase; }}
  .design-toggle {{ background:transparent; border:1px solid var(--line); color:var(--soft); font-family:var(--font);
           font-size:10px; padding:6px 10px; cursor:pointer; white-space:nowrap; }}
  .design-panel {{ background:var(--panel); border:1px solid var(--line); padding:16px; margin:6px 0; display:flex; flex-wrap:wrap; gap:16px; align-items:flex-start; }}
  .design-field {{ flex:1 1 180px; min-width:160px; }}
  .design-field.wide {{ flex:1 1 100%; }}
  .design-field label {{ margin-top:0; }}
  .design-field input {{ width:100%; box-sizing:border-box; }}
  .event-hint {{ flex:1 1 100%; margin:0; }}
  /* Card type: a ticket has no "days", and shows its event details */
  .days-note {{ display:none; color:var(--muted); font-size:11px; }}
  tr.tier-row.is-ticket .c-days input, tr.tier-row.is-collectible .c-days input {{ display:none; }}
  tr.tier-row.is-ticket .c-days .days-note, tr.tier-row.is-collectible .c-days .days-note {{ display:inline; }}
  tr.design-row:not(.is-ticket) .event-block {{ display:none; }}
  tr.design-row:not(.is-collectible) .drop-block {{ display:none; }}
  .lbl-edition {{ display:none; }}
  tr.design-row.is-collectible .lbl-edition {{ display:inline; }}
  tr.design-row.is-collectible .lbl-members {{ display:none; }}
  .design-field select {{ width:100%; background:var(--field); border:1px solid var(--line); color:var(--fg);
           font-family:var(--font); font-size:12px; padding:8px 10px; }}
  .logo-row {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
  .logo-thumb {{ height:32px; max-width:80px; object-fit:contain; background:#000; }}
  .no-logo {{ color:var(--muted); font-size:10px; }}
  .remove-logo {{ background:transparent; border:1px solid var(--line); color:var(--soft); font-family:var(--font);
           font-size:9px; padding:4px 8px; cursor:pointer; }}
  .preview-btn {{ background:transparent; border:1px solid var(--accent-text); color:var(--accent-text); font-family:var(--font);
           font-size:10px; letter-spacing:1px; padding:8px 14px; cursor:pointer; flex:1 1 100%; }}
  .preview-frame {{ width:100%; height:480px; border:1px solid var(--line); margin-top:10px; flex:1 1 100%; background:var(--frame-bg); }}
  .welcome-box {{ border:1px solid var(--accent-text); background:var(--panel); padding:14px 18px; margin:18px 0 0; }}
  .welcome-box ol {{ margin:8px 0 10px; padding-left:20px; font-size:12px; line-height:1.8; }}
  .checklist {{ border:1px solid var(--line); background:var(--panel); padding:12px 16px; margin:18px 0 0; }}
  .checklist summary {{ cursor:pointer; color:var(--accent-text); font-size:12px; letter-spacing:1.5px; text-transform:uppercase; }}
  .chk-row {{ display:flex; gap:12px; align-items:flex-start; margin-top:12px; font-size:12px; }}
  .chk-ok {{ color:var(--ok); font-size:14px; width:16px; flex:0 0 16px; }}
  .chk-todo {{ color:var(--warn); font-size:14px; width:16px; flex:0 0 16px; }}
  .embed-code {{ background:var(--panel); border:1px solid var(--line); color:var(--fg); font-family:var(--font);
           font-size:12px; line-height:1.7; padding:12px 14px; margin:8px 0; white-space:pre-wrap; word-break:break-all; }}
  .copy-btn {{ background:var(--accent); color:var(--on-accent); border:none; font-family:var(--font);
           font-size:11px; letter-spacing:1.5px; text-transform:uppercase; padding:8px 16px; cursor:pointer; }}
  /* Tiers on a wide screen: keep the type and look pickers readable, the number boxes small. */
  @media (min-width:900px) {{
    #sec-tiers td[data-label="Card type"] select, #sec-tiers td[data-label="Card look"] select {{ min-width:116px; }}
    #sec-tiers td[data-label="Price"] input, #sec-tiers td.c-days input {{ max-width:84px; }}
  }}
  /* Tiers on a phone: one card per tier instead of a table you have to scroll sideways. */
  @media (max-width:899px) {{
    #sec-tiers table, #sec-tiers tbody {{ display:block; width:100%; }}
    #sec-tiers tr:has(> th) {{ display:none; }}
    #sec-tiers tr.tier-row {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:10px 12px; margin-top:12px; padding:14px;
      background:var(--panel); border:1px solid var(--line); border-radius:var(--radius-lg, 8px); }}
    #sec-tiers tr.tier-row > td {{ display:block; padding:0; min-width:0; }}
    #sec-tiers tr.tier-row > td[data-label]::before {{ content:attr(data-label); display:block; font-size:12px; color:var(--muted); margin-bottom:4px; letter-spacing:0; text-transform:none; }}
    #sec-tiers tr.tier-row > td:nth-child(6), #sec-tiers tr.tier-row > td:nth-child(7) {{ grid-column:1 / -1; }}
    #sec-tiers tr.tier-row select {{ width:100%; box-sizing:border-box; padding:11px 12px; font-size:16px; }}
    #sec-tiers tr.tier-row input {{ width:100%; box-sizing:border-box; padding:11px 12px; font-size:16px; }}
    #sec-tiers .design-toggle, #sec-tiers .remove-tier {{ width:100%; height:auto; box-sizing:border-box; padding:11px 12px; font-size:13px; }}
    #sec-tiers .remove-tier {{ font-size:0 !important; line-height:1; }}
    #sec-tiers .remove-tier::after {{ content:"Remove tier"; font-size:13px; font-family:var(--font); }}
    #sec-tiers tr.design-row {{ display:block; margin-top:6px; }}
    #sec-tiers tr.design-row > td {{ display:block; padding:0; }}
    #sec-tiers .design-panel {{ padding:14px; gap:14px; }}
    #sec-tiers .design-field {{ flex:1 1 100%; min-width:0; }}
    #sec-tiers .design-field input[type=datetime-local] {{ min-height:44px; }}
    #sec-tiers .design-field input, #sec-tiers .design-field select {{ width:100%; max-width:100%; box-sizing:border-box; padding:11px 12px; font-size:16px; }}
    #sec-tiers .design-field input[type=file] {{ font-size:13px; padding:8px 0; }}
    #sec-tiers .preview-btn {{ padding:12px 14px; font-size:13px; }}
  }}
{theme_css}</style></head>
<body {body_attrs}>
  <div class="nav"><a href="/admin/members">Members →</a><a href="/admin/content">Content →</a><a href="/admin/announce">Announce →</a><a href="/admin/logout">Log out</a></div>
  <h1>{title} — Dashboard</h1>
  {saved_banner}

  <section class="dsec" id="sec-home" data-title="Home">
  <div class="stats">
    <div><b>{s['total']}</b>total</div>
    <div><b>{s['active']}</b>active</div>
    <div><b>{s['revoked']}</b>revoked</div>
    <div><b>{s['expired']}</b>expired</div>
  </div>

  {checklist_html}

  <h2>Embed on your website</h2>
  <div class="hint">Paste these two lines into the page of your site where you want the member widget. Open this dashboard at your real public address before copying, because the address below comes from the page you are on.</div>
  <pre class="embed-code" id="embed-code"></pre>
  <button type="button" class="copy-btn" id="embed-copy">Copy</button>
  </section>

  <form method="POST" action="/admin/dashboard" enctype="multipart/form-data">

    <section class="dsec" id="sec-style" data-title="Dashboard style">
    <h2>Dashboard style</h2>
    <div class="hint" style="margin-bottom:10px;">How these admin pages look. Only you see it; cards, emails and the widget don't change. Press <b>Save changes</b> to apply.</div>
    <div class="style-cards">{style_cards}</div>

    </section>

    <section class="dsec" id="sec-branding" data-title="Branding &amp; cards">
    <h2>Branding</h2>
    <div class="hint" style="margin-bottom:6px;">This is the <b>default look</b> for your cards. To make other looks (like Trial or Monthly), open <b>Card looks</b>, then pick one for each tier under <b>Tiers &amp; pricing</b>.</div>
    <label>Creator name</label>
    <input name="creator_name" value="{esc_html(cfg['creator_name'])}">
    <label>Card title (the big name on cards and emails)</label>
    <input name="card_title" value="{esc_html(cfg['card_title'])}">
    <label>Small line under the title (like "Member Keycard")</label>
    <input name="card_subtitle" value="{esc_html(cfg['card_subtitle'])}" maxlength="40">
    <label>Accent color</label>
    <input name="accent_color" type="color" value="{esc_html(cfg['accent_color'])}">
    <label>Card style</label>
    <select name="card_style">
      <option value="distressed" {"selected" if g_style == "distressed" else ""}>{esc_html(card_looks.STYLE_NAMES["distressed"])}</option>
      <option value="clean" {"selected" if g_style == "clean" else ""}>{esc_html(card_looks.STYLE_NAMES["clean"])}</option>
      <option value="holographic" {"selected" if g_style == "holographic" else ""}>{esc_html(card_looks.STYLE_NAMES["holographic"])}</option>
      <option value="minimal" {"selected" if g_style == "minimal" else ""}>{esc_html(card_looks.STYLE_NAMES["minimal"])}</option>
      <option value="ticket" {"selected" if g_style == "ticket" else ""}>{esc_html(card_looks.STYLE_NAMES["ticket"])}</option>
      <option value="gradient" {"selected" if g_style == "gradient" else ""}>{esc_html(card_looks.STYLE_NAMES["gradient"])}</option>
      <option value="neon" {"selected" if g_style == "neon" else ""}>{esc_html(card_looks.STYLE_NAMES["neon"])}</option>
    </select>
    <label>QR code on the card</label>
    <select name="qr_style">{global_qr_options}</select>
    <div class="hint">Blended keeps the QR code on the card but makes it blend into a background picture. Members can still use their link or drop the card file.</div>
    <label>Card logo (PNG, JPG, GIF or WEBP; shrunk automatically)</label>
    <div class="logo-row">
      {global_logo_thumb}
      <input type="file" name="global_logo" accept="image/png,image/jpeg,image/gif,image/webp">
      <button type="button" class="remove-logo" id="remove-global-logo">Remove logo</button>
    </div>
    <input type="hidden" name="global_logo_clear" id="global-logo-clear" value="0">
    <label>Background picture (optional, your own design)</label>
    <div class="logo-row">
      {global_bg_state}
      <input type="file" name="global_bg" accept="image/png,image/jpeg,image/gif,image/webp">
      <button type="button" class="remove-logo" id="remove-global-bg">Remove picture</button>
    </div>
    <input type="hidden" name="global_bg_clear" id="global-bg-clear" value="0">
    <label>Darken the picture so the text is readable</label>
    <select name="global_bg_dim">{global_dim_options}</select>
    <button type="button" class="preview-btn" id="global-preview-btn" style="display:block;margin-top:12px;max-width:260px;">Preview the card →</button>
    <iframe class="preview-frame" id="global-preview-frame" style="display:none"></iframe>
    <label>Members page address (optional)</label>
    <input name="members_page" value="{esc_html(cfg['members_page_saved'] if public_url.is_real(cfg['members_page_saved']) else '')}" placeholder="{esc_html(cfg['members_page'])}">
    <div class="hint">Leave this empty to use the page this server makes for you (shown above). Only fill it in if the widget sits on a page of your own website.</div>
    <label>This server's address (just for your notes)</label>
    <input name="api_base" value="{esc_html(cfg['api_base'])}">


    </section>

    <section class="dsec" id="sec-widget" data-title="Widget look">
    <h2>Widget look</h2>
    <div class="hint" style="margin-bottom:8px;">How the member widget looks on your site. <b>Match my page</b> copies the colors and font of the page it sits on. The previews follow your changes before you save. The accent color is under Branding.</div>
    <div class="wl-grid">
      <div>
        <label>Colors</label>
        <select name="widget_theme" id="wl-theme">
          <option value="match" {"selected" if cfg['widget_theme'] == "match" else ""}>Match my page (recommended)</option>
          <option value="dark" {"selected" if cfg['widget_theme'] == "dark" else ""}>Always dark</option>
          <option value="light" {"selected" if cfg['widget_theme'] == "light" else ""}>Always light</option>
          <option value="custom" {"selected" if cfg['widget_theme'] == "custom" else ""}>My own colors</option>
        </select>
      </div>
      <div>
        <label>Lettering</label>
        <select name="widget_font" id="wl-font">
          <option value="page" {"selected" if cfg['widget_font'] == "page" else ""}>My page's font (recommended)</option>
          <option value="keycard" {"selected" if cfg['widget_font'] == "keycard" else ""}>Keycard lettering (like the cards)</option>
        </select>
      </div>
      <div>
        <label>Corners</label>
        <select name="widget_corners" id="wl-corners">
          <option value="square" {"selected" if cfg['widget_corners'] == "square" else ""}>Square</option>
          <option value="rounded" {"selected" if cfg['widget_corners'] == "rounded" else ""}>Rounded</option>
        </select>
      </div>
    </div>
    <div id="wl-custom" style="display:{"flex" if cfg['widget_theme'] == "custom" else "none"};gap:24px;flex-wrap:wrap;margin-top:6px;">
      <div><label>Background color</label><input type="color" name="widget_bg" id="wl-bg" value="{esc_html(cfg['widget_bg'])}"></div>
      <div><label>Text color</label><input type="color" name="widget_text" id="wl-text" value="{esc_html(cfg['widget_text'])}"></div>
    </div>
    <label style="margin-top:14px;">Wording (leave a box empty to use the standard words)</label>
    <div class="wl-grid">
      <div><div class="hint">Banner</div><input name="widget_banner_text" id="wl-banner" maxlength="80" value="{esc_html(cfg['widget_banner_text'])}" placeholder="{esc_html(widget_look.TEXTS['widget_banner_text'][1])}"></div>
      <div><div class="hint">Card drop box: title</div><input name="widget_drop_title" id="wl-drop-title" maxlength="60" value="{esc_html(cfg['widget_drop_title'])}" placeholder="{esc_html(widget_look.TEXTS['widget_drop_title'][1])}"></div>
      <div><div class="hint">Card drop box: small line</div><input name="widget_drop_sub" id="wl-drop-sub" maxlength="100" value="{esc_html(cfg['widget_drop_sub'])}" placeholder="{esc_html(widget_look.TEXTS['widget_drop_sub'][1])}"></div>
      <div><div class="hint">Sign-up pop-up: title</div><input name="widget_signup_title" id="wl-signup-title" maxlength="60" value="{esc_html(cfg['widget_signup_title'])}" placeholder="{esc_html(widget_look.TEXTS['widget_signup_title'][1])}"></div>
      <div><div class="hint">Sign-up pop-up: button</div><input name="widget_button_text" id="wl-button" maxlength="40" value="{esc_html(cfg['widget_button_text'])}" placeholder="{esc_html(widget_look.TEXTS['widget_button_text'][1])}"></div>
    </div>
    <div class="wl-grid" style="margin-top:8px;">
      <div><div class="hint">Terms link (optional)</div><input name="widget_terms_url" id="wl-terms" maxlength="300" value="{esc_html(cfg['widget_terms_url'])}" placeholder="https://your-site.com/terms"></div>
      <div><div class="hint">Privacy link (optional)</div><input name="widget_privacy_url" id="wl-privacy" maxlength="300" value="{esc_html(cfg['widget_privacy_url'])}" placeholder="https://your-site.com/privacy"></div>
    </div>
    <div class="hint" style="margin-top:4px;">If you add a link, the sign-up pop-up says "By getting a card you agree to the Terms and Privacy Policy." with those words linked.</div>
    <div class="hint" style="margin-top:8px;">Sign-up pop-up: text under the title</div>
    <textarea name="widget_signup_sub" id="wl-signup-sub" rows="2" maxlength="200" placeholder="{esc_html(widget_look.TEXTS['widget_signup_sub'][1])}">{esc_html(cfg['widget_signup_sub'])}</textarea>
    <div style="margin-top:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
      <button type="button" class="add-tier" id="wl-popup-btn" style="margin-top:0;">Show the sign-up pop-up in the previews</button>
    </div>
    <div class="wl-previews">
      <div><div class="hint">On a dark page</div><iframe class="wl-frame" id="wl-frame-dark" sandbox="allow-scripts"></iframe></div>
      <div><div class="hint">On a light page</div><iframe class="wl-frame" id="wl-frame-light" sandbox="allow-scripts"></iframe></div>
    </div>
    <div class="hint">The previews are your real widget.</div>

    </section>

    <section class="dsec" id="sec-tiers" data-title="Tiers &amp; pricing">
    <h2>Tiers &amp; pricing</h2>
    {tier_sections_hint}
    <div class="hint" style="margin-bottom:8px;">Each tier is its own kind of card (for example Monthly, Trial or VIP). Pick a <b>Card look</b> for each one; make and edit looks under <b>Card looks</b>. <b>Card type</b> is <b>Access pass</b> (a membership that lasts a number of days) or <b>Event ticket</b> (for one event: it shows the event on the card, stops working when the event ends, and can be checked in at the door) or <b>Collectible</b> (a limited-edition drop: every card is numbered, like #37 of 100, and never expires). <b>More</b> opens the event or drop details, how many members a tier can have and how many cards one email can get.</div>
    <table>
      <tr><th>Name</th><th>Label</th><th>Price</th><th>Card type</th><th>Expiry (days)</th><th>Sections (separated by commas)</th><th>Card look</th><th></th><th></th></tr>
      <tbody id="tier-body">{tier_rows}</tbody>
    </table>
    <button type="button" class="add-tier" id="add-tier">+ Add tier</button>

    </section>

    <section class="dsec" id="sec-payment" data-title="Payment">
    <h2>Payment</h2>
    <label>How do members pay?</label>
    <select name="payment_provider">
      <option value="manual" {"selected" if provider == "manual" else ""}>I arrange it myself (bank transfer, cash, anything)</option>
      <option value="custom" {"selected" if provider == "custom" else ""}>Send them to a payment link (PayPal, Ko-fi, Gumroad...)</option>
      <option value="stripe" {"selected" if provider == "stripe" else ""}>Automatic card payments (Stripe)</option>
    </select>
    <div class="hint pv-hint" data-for="manual" style="margin-top:4px;{"" if provider == "manual" else "display:none;"}">The member asks for a tier and sees your message below. When you have been paid, press Approve in the list at the bottom and they get their card.</div>
    <div class="hint pv-hint" data-for="custom" style="margin-top:4px;{"" if provider == "custom" else "display:none;"}">The member asks for a tier and gets a button that opens your payment link. When the money arrives, press Approve in the list at the bottom and they get their card.</div>
    <div class="hint pv-hint" data-for="stripe" style="margin-top:4px;{"" if provider == "stripe" else "display:none;"}">Members pay by card and get their card automatically, with nothing for you to approve. Needs a Stripe account (see below).</div>

    <label>Currency (3 letters, like usd, eur, gbp)</label>
    <input name="currency" value="{esc_html(cfg.get('currency','usd'))}" maxlength="3" style="max-width:100px;">

    <div id="custom-box" class="custom-box"{"" if provider == "custom" else ' style="display:none"'}>
      <label>Name of the service (shown on the button)</label>
      <input name="custom_provider_name" value="{esc_html(cfg.get('custom_provider_name',''))}" maxlength="{custom_payment.MAX_NAME}" placeholder="PayPal" style="max-width:260px;">
      <label>Payment link</label>
      <input name="custom_payment_url" value="{esc_html(cfg.get('custom_payment_url',''))}" maxlength="{custom_payment.MAX_URL}" placeholder="https://paypal.me/yourname">
      <div class="hint" style="margin-top:4px;">Paste the link where members pay. It has to start with https://</div>
      <div class="hint" style="margin-top:8px;">Just trying it out? <button type="button" class="mini" id="use-practice-link" data-link="{esc_html(public_url.base_url())}/practice-pay?ref={{reference}}&amp;amount={{amount}}">Use the practice page</button> A pretend payment page on this server: no money moves, and it tells you what to press next.</div>
      <details class="adv-box" style="margin-top:10px;">
        <summary>More options (you can skip this)</summary>
        <label>A different link for one tier</label>
        <textarea name="custom_payment_links" rows="3" placeholder="MEMBER = https://ko-fi.com/s/abc123&#10;VIP = https://ko-fi.com/s/def456">{esc_html(cfg.get('custom_payment_links',''))}</textarea>
        <div class="hint" style="margin-top:4px;">One per line: the tier's name, an equals sign, then its link. Your tiers: <b>{esc_html(", ".join(str(t.get("name","")) for t in (cfg.get("tiers") or [])) or "none yet")}</b>. Tiers without a line use the link above.</div>
        <div class="hint" style="margin-top:8px;">In any link you can write <b>{{amount}}</b>, <b>{{currency}}</b>, <b>{{tier}}</b>, <b>{{email}}</b>, <b>{{name}}</b> or <b>{{reference}}</b> and it is filled in for each member (for example <code>https://paypal.me/yourname/{{amount}}{{currency}}</code>). <b>{{reference}}</b> is a short code that also appears in the list at the bottom, so you can match a payment to a request.</div>
      </details>
    </div>


    <label>Message to the member (optional)</label>
    <textarea name="manual_payment_instructions" rows="3" placeholder="e.g. Send $9.99 to you@example.com, then I'll approve your access within a day.">{esc_html(cfg.get('manual_payment_instructions',''))}</textarea>

    <div id="stripe-box" class="placeholder" style="margin-top:14px;{"" if provider == "stripe" else "display:none;"}">
      {payment_status_html}
      Stripe keys are secrets, so they are not typed here. They are set as
      environment variables (<code>STRIPE_SECRET_KEY</code>,
      <code>STRIPE_WEBHOOK_SECRET</code>); see SETUP.md.
    </div>
    <div class="hint" style="margin-top:10px;">A tier that costs 0 is always free and instant, whatever you pick here.</div>

    <label style="margin-top:20px;">Payments waiting for your OK</label>
    {pending_requests_html}

    </section>

    <section class="dsec" id="sec-emails" data-title="Emails">
    <h2>Welcome email</h2>
    <div class="hint" style="margin-bottom:8px;">The email a member gets with their card and access link (those are always included). You can write <b>{{name}}</b>, <b>{{tier}}</b>, <b>{{creator}}</b>, <b>{{brand}}</b> and <b>{{expires}}</b>, and they are filled in for each member. Leave a box empty to use the standard words.</div>
    <label>Subject</label>
    <input name="email_subject" id="email-subject" maxlength="150" value="{esc_html(cfg['email_subject'])}">
    <label>Welcome text</label>
    <textarea name="email_intro" id="email-intro" rows="3" maxlength="1000">{esc_html(cfg['email_intro'])}</textarea>
    <label>Sign-off (optional, like "See you inside. — {{creator}}")</label>
    <textarea name="email_signoff" id="email-signoff" rows="2" maxlength="600">{esc_html(cfg['email_signoff'])}</textarea>
    <div style="margin-top:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
      <button type="button" class="add-tier" id="email-preview-btn" style="margin-top:0;">Preview email →</button>
      <input id="email-test-to" type="email" placeholder="send a test to this address" style="max-width:260px;">
      <button type="button" class="add-tier" id="email-test-btn" style="margin-top:0;">Send test</button>
    </div>
    <div class="hint" id="email-status" style="margin-top:8px;min-height:14px;"></div>
    <div class="hint">Preview and test use what is typed above, even before you save. Sending a test needs email set up (see SETUP.md).</div>
    <iframe id="email-preview-frame" sandbox="" style="display:none;width:100%;height:620px;border:1px solid var(--line);margin-top:10px;background:var(--frame-bg);"></iframe>

    <h2>Expiry reminder</h2>
    <div class="hint" style="margin-bottom:8px;">Emails a member a few days before their access ends, once per end date. Needs email set up (see SETUP.md). Turning it on also reminds members who are already inside the window. You can write <b>{{name}}</b>, <b>{{tier}}</b>, <b>{{creator}}</b>, <b>{{brand}}</b>, <b>{{expires}}</b> and <b>{{days}}</b>. The member's access link is always included.</div>
    <label>Days before access ends to send it (0 = off)</label>
    <input name="reminder_days" id="reminder-days" type="number" min="0" max="{reminders.MAX_REMINDER_DAYS}" step="1" value="{cfg['reminder_days']}" style="max-width:100px;">
    <div class="hint" style="margin-top:4px;">Passes that last no longer than this are not reminded.</div>
    <label>Subject</label>
    <input name="reminder_subject" id="reminder-subject" maxlength="150" value="{esc_html(cfg['reminder_subject'])}">
    <label>Reminder text</label>
    <textarea name="reminder_text" id="reminder-text" rows="3" maxlength="1000">{esc_html(cfg['reminder_text'])}</textarea>
    <label>Renew link (optional, adds a "Renew" button)</label>
    <input name="reminder_renew_url" id="reminder-renew" type="url" maxlength="500" placeholder="https://..." value="{esc_html(cfg['reminder_renew_url'])}">
    <div style="margin-top:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
      <button type="button" class="add-tier" id="reminder-preview-btn" style="margin-top:0;">Preview reminder →</button>
      <input id="reminder-test-to" type="email" placeholder="send a test to this address" style="max-width:260px;">
      <button type="button" class="add-tier" id="reminder-test-btn" style="margin-top:0;">Send test</button>
    </div>
    <div class="hint" id="reminder-status" style="margin-top:8px;min-height:14px;"></div>
    <iframe id="reminder-preview-frame" sandbox="" style="display:none;width:100%;height:520px;border:1px solid var(--line);margin-top:10px;background:var(--frame-bg);"></iframe>

    <h2>Access extended email</h2>
    <div class="hint" style="margin-bottom:8px;">What a member gets when you press Extend on the Members page and leave "email them" ticked. You can write <b>{{name}}</b>, <b>{{tier}}</b>, <b>{{creator}}</b>, <b>{{brand}}</b>, <b>{{expires}}</b> and <b>{{days}}</b> (how many days were added). The member's access link is always included. Leave a box empty to use the standard words.</div>
    <label>Subject</label>
    <input name="extended_subject" id="extended-subject" maxlength="150" value="{esc_html(cfg['extended_subject'])}">
    <label>Message</label>
    <textarea name="extended_text" id="extended-text" rows="3" maxlength="1000">{esc_html(cfg['extended_text'])}</textarea>
    <div style="margin-top:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
      <button type="button" class="add-tier" id="extended-preview-btn" style="margin-top:0;">Preview email →</button>
      <input id="extended-test-to" type="email" placeholder="send a test to this address" style="max-width:260px;">
      <button type="button" class="add-tier" id="extended-test-btn" style="margin-top:0;">Send test</button>
    </div>
    <div class="hint" id="extended-status" style="margin-top:8px;min-height:14px;"></div>
    <iframe id="extended-preview-frame" sandbox="" style="display:none;width:100%;height:520px;border:1px solid var(--line);margin-top:10px;background:var(--frame-bg);"></iframe>

    </section>

    <h2></h2>
    <button type="submit" class="save-btn">Save changes</button>
  </form>
  {looks_section}
  <section class="dsec" id="sec-backup" data-title="Backup &amp; restore">
  {backup_html}
  </section>

  <template id="tier-row-template">
    <tr class="tier-row">
      <td data-label="Name"><input name="tier_name" value=""></td>
      <td data-label="Label"><input name="tier_label" value=""></td>
      <td data-label="Price"><input name="tier_price" type="number" step="0.01" value="0"></td>
      <td data-label="Card type">{_kind_select("pass")}</td>
      <td data-label="Days of access" class="c-days"><input name="tier_expiry_days" type="number" value="31"><span class="days-note">Until the event ends</span></td>
      <td data-label="Sections (separated by commas)"><input name="tier_sections" value="" placeholder="downloads, chat"></td>
      <td data-label="Card look"><select name="tier_look">{looks_page.picker_options(cfg, "")}</select></td>
      <td><button type="button" class="design-toggle">More ▾</button></td>
      <td><button type="button" class="remove-tier" title="Remove this tier">×</button></td>
    </tr>
    <tr class="design-row" style="display:none">
      <td colspan="9">
        {_event_panel({})}
        {_drop_panel({})}
        <div class="design-panel limits-panel">
          <div class="design-field">
            <label><span class="lbl-members">Max members (blank = no limit)</span><span class="lbl-edition">Edition size (blank = open edition)</span></label>
            <input name="tier_max_members" type="number" min="1" step="1" value="" placeholder="no limit">
          </div>
          <div class="design-field">
            <label>Show visitors how many spots are left?</label>
            <select name="tier_show_spots">
              <option value="show" selected>Yes, e.g. "12 left"</option>
              <option value="hide">No, only show "Sold out" when full</option>
            </select>
          </div>
          <div class="design-field">
            <label>Cards per email address</label>
            <select name="tier_per_email">
              <option value="one_active" selected>One working card at a time</option>
              <option value="one_ever">Only one ever (good for a free trial)</option>
              <option value="unlimited">No limit</option>
            </select>
          </div>
        </div>
      </td>
    </tr>
  </template>

  <script>
    // Embed snippet — built here (not in the HTML above) for two reasons:
    // the address comes from window.location so it's always this exact
    // deployment's real public URL with nothing to configure, and the
    // closing script tag has to be assembled from pieces, since a literal
    // one inside this inline script would end it early.
    (function() {{
      const code = '<div id="credential-widget"></div>\\n<' + 'script src="' +
                   window.location.origin + '/cp.js"></' + 'script>';
      document.getElementById('embed-code').textContent = code;
      const btn = document.getElementById('embed-copy');
      function done() {{
        btn.textContent = 'Copied \\u2713';
        setTimeout(() => {{ btn.textContent = 'Copy'; }}, 1800);
      }}
      function fallback() {{
        const ta = document.createElement('textarea');
        ta.value = code;
        document.body.appendChild(ta);
        ta.select();
        try {{ document.execCommand('copy'); done(); }}
        catch (e) {{ btn.textContent = 'Select the text and copy it by hand'; }}
        ta.remove();
      }}
      btn.addEventListener('click', () => {{
        if (navigator.clipboard && window.isSecureContext) {{
          navigator.clipboard.writeText(code).then(done, fallback);
        }} else {{
          fallback();
        }}
      }});
    }})();

    document.getElementById('add-tier').addEventListener('click', () => {{
      const tpl = document.getElementById('tier-row-template');
      const rows = tpl.content.cloneNode(true);
      document.getElementById('tier-body').appendChild(rows);
    }});

    // Card type: show or hide the event details; remember the browser's time zone for the event.
    (function() {{
      const body = document.getElementById('tier-body');
      function designRowOf(row) {{ const d = row.nextElementSibling; return d && d.classList.contains('design-row') ? d : null; }}
      function sync(row, open) {{
        const sel = row.querySelector('[name="tier_kind"]');
        if (!sel) return;
        const t = sel.value === 'ticket', c = sel.value === 'collectible';
        row.classList.toggle('is-ticket', t);
        row.classList.toggle('is-collectible', c);
        const note = row.querySelector('.days-note');
        if (note) note.textContent = c ? 'Never expires' : 'Until the event ends';
        const d = designRowOf(row);
        if (d) {{
          d.classList.toggle('is-ticket', t); d.classList.toggle('is-collectible', c);
          if ((t || c) && open) d.style.display = '';
          // a collectible is one copy per person by default
          const pe = d.querySelector('select[name=tier_per_email]');
          if (c && open && pe && pe.value === 'one_active') pe.value = 'one_ever';
        }}
      }}
      function setTz(d) {{
        const st = d.querySelector('[name="tier_event_start"]'), tz = d.querySelector('[name="tier_event_tz"]');
        if (st && tz && st.value) {{
          const when = new Date(st.value);
          if (!isNaN(when)) tz.value = String(when.getTimezoneOffset());
        }}
        const o = d.querySelector('[name="tier_drop_opens"]'), c = d.querySelector('[name="tier_drop_closes"]'), dz = d.querySelector('[name="tier_drop_tz"]');
        const dv = o && o.value ? o.value : (c && c.value ? c.value : '');
        if (dz && dv) {{ const w = new Date(dv); if (!isNaN(w)) dz.value = String(w.getTimezoneOffset()); }}
      }}
      body.addEventListener('change', (e) => {{
        const row = e.target.closest('tr');
        if (!row) return;
        if (e.target.name === 'tier_kind') {{ sync(row, true); return; }}
        if (e.target.name === 'tier_event_start' || e.target.name === 'tier_drop_opens' || e.target.name === 'tier_drop_closes') {{ const d = row.classList.contains('design-row') ? row : null; if (d) setTz(d); }}
      }});
      Array.from(body.querySelectorAll('tr.tier-row')).forEach((r) => sync(r, false));
      document.getElementById('add-tier').addEventListener('click', () => {{
        const rows = body.querySelectorAll('tr.tier-row'); if (rows.length) sync(rows[rows.length - 1], false);
      }});
    }})();

    document.getElementById('tier-body').addEventListener('click', (e) => {{
      if (e.target.classList.contains('remove-tier')) {{
        const mainRow = e.target.closest('tr');
        const designRow = mainRow.nextElementSibling;
        mainRow.remove();
        if (designRow && designRow.classList.contains('design-row')) designRow.remove();
        return;
      }}
      if (e.target.classList.contains('design-toggle')) {{
        const designRow = e.target.closest('tr').nextElementSibling;
        designRow.style.display = (designRow.style.display === 'none') ? '' : 'none';
        return;
      }}
    }});

    // Payment: "Use the practice page" fills in the pretend payment link.
    (function() {{
      var b = document.getElementById('use-practice-link');
      if (!b) return;
      b.addEventListener('click', function () {{
        var u = document.querySelector('[name="custom_payment_url"]'), n = document.querySelector('[name="custom_provider_name"]');
        u.value = b.getAttribute('data-link'); if (!n.value) n.value = 'Practice page';
        // tell the page something changed, so the Save bar shows up
        [u, n].forEach(function (f) {{ f.dispatchEvent(new Event('input', {{ bubbles: true }})); f.dispatchEvent(new Event('change', {{ bubbles: true }})); }});
        b.textContent = 'Added. Now press Save';
      }});
    }})();

    // Branding: card logo + preview of the deployment-wide card look. Uses what's
    // typed/picked right now (saved or not).
    (function() {{
      const btn = document.getElementById('global-preview-btn');
      const frame = document.getElementById('global-preview-frame');
      const clear = document.getElementById('global-logo-clear');
      const fileInput = document.querySelector('input[name="global_logo"]');
      const bgInput = document.querySelector('input[name="global_bg"]');
      const bgClear = document.getElementById('global-bg-clear');
      document.getElementById('remove-global-bg').addEventListener('click', () => {{
        bgClear.value = '1';
        bgInput.value = '';
        document.getElementById('global-bg-state').textContent = 'removed — takes effect when you save';
      }});
      bgInput.addEventListener('change', () => {{ if (bgInput.files[0]) {{ bgClear.value = '0'; document.getElementById('global-bg-state').textContent = 'new picture chosen'; }} }});
      document.getElementById('remove-global-logo').addEventListener('click', () => {{
        clear.value = '1';
        fileInput.value = '';
        const thumb = document.getElementById('global-logo-thumb');
        if (thumb) {{
          const span = document.createElement('span');
          span.className = 'no-logo';
          span.textContent = 'removed — takes effect when you save';
          thumb.replaceWith(span);
        }}
      }});
      btn.addEventListener('click', () => {{
        const fd = new FormData();
        fd.append('scope', 'global');
        ['creator_name', 'card_title', 'card_subtitle', 'accent_color', 'card_style', 'qr_style'].forEach(n => {{
          fd.append(n, document.querySelector('[name="' + n + '"]').value);
        }});
        fd.append('logo_clear', clear.value);
        if (fileInput.files[0]) fd.append('logo', fileInput.files[0]);
        fd.append('bg_clear', bgClear.value);
        fd.append('bg_dim', document.querySelector('[name="global_bg_dim"]').value);
        if (bgInput.files[0]) fd.append('bg', bgInput.files[0]);
        const label = btn.textContent;
        btn.textContent = 'Loading preview...';
        fetch('/admin/dashboard/preview-card', {{ method: 'POST', body: fd, credentials: 'same-origin' }})
          .then(r => r.text())
          .then(html => {{ frame.srcdoc = html; frame.style.display = ''; btn.textContent = label; }})
          .catch(err => {{ btn.textContent = label; frame.srcdoc = '<p style="font-family:monospace;color:#e8232b">Preview failed: ' + String(err.message).replace(/</g, '&lt;') + '</p>'; frame.style.display = ''; }});
      }});
    }})();

    // Welcome email: preview and test-send use whatever is typed in the
    // three fields right now (saved or not).
    (function() {{
      const subj = document.getElementById('email-subject');
      const intro = document.getElementById('email-intro');
      const sign = document.getElementById('email-signoff');
      const frame = document.getElementById('email-preview-frame');
      const status = document.getElementById('email-status');
      const pbtn = document.getElementById('email-preview-btn');
      const tbtn = document.getElementById('email-test-btn');
      const to = document.getElementById('email-test-to');
      function fields() {{
        return {{ email_subject: subj.value, email_intro: intro.value, email_signoff: sign.value }};
      }}
      function say(text, good) {{
        status.textContent = text;
        status.style.color = good ? 'var(--ok)' : 'var(--bad)';
      }}
      function post(url, body) {{
        return fetch(url, {{ method: 'POST', credentials: 'same-origin',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify(body) }})
          .then(r => r.json().then(j => ({{ status: r.status, body: j }})));
      }}
      pbtn.addEventListener('click', () => {{
        pbtn.disabled = true; say('Loading preview…', true);
        post('/admin/email/preview', fields()).then(res => {{
          pbtn.disabled = false;
          if (!res.body.success) {{ say(res.body.error || 'Preview failed.', false); return; }}
          frame.srcdoc = res.body.html; frame.style.display = '';
          say('Subject: ' + res.body.subject, true);
        }}).catch(() => {{ pbtn.disabled = false; say('Could not reach the server.', false); }});
      }});
      tbtn.addEventListener('click', () => {{
        const addr = to.value.trim();
        if (!addr || addr.indexOf('@') < 1) {{ say('Type the address to send the test to.', false); return; }}
        tbtn.disabled = true; say('Sending…', true);
        post('/admin/email/test', Object.assign({{ to: addr }}, fields())).then(res => {{
          tbtn.disabled = false;
          say(res.body.message || res.body.error || 'Failed.', !!res.body.success);
        }}).catch(() => {{ tbtn.disabled = false; say('Could not reach the server.', false); }});
      }});
    }})();

    // Expiry reminder: same preview/test routes, kind = "reminder".
    (function() {{
      const f = id => document.getElementById(id);
      const frame = f('reminder-preview-frame'), status = f('reminder-status');
      const pbtn = f('reminder-preview-btn'), tbtn = f('reminder-test-btn'), to = f('reminder-test-to');
      function fields() {{
        return {{ kind: 'reminder', reminder_subject: f('reminder-subject').value,
                 reminder_text: f('reminder-text').value, reminder_renew_url: f('reminder-renew').value }};
      }}
      function say(text, good) {{ status.textContent = text; status.style.color = good ? 'var(--ok)' : 'var(--bad)'; }}
      function post(url, body) {{
        return fetch(url, {{ method: 'POST', credentials: 'same-origin',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify(body) }})
          .then(r => r.json().then(j => ({{ status: r.status, body: j }})));
      }}
      pbtn.addEventListener('click', () => {{
        pbtn.disabled = true; say('Loading preview…', true);
        post('/admin/email/preview', fields()).then(res => {{
          pbtn.disabled = false;
          if (!res.body.success) {{ say(res.body.error || 'Preview failed.', false); return; }}
          frame.srcdoc = res.body.html; frame.style.display = '';
          say('Subject: ' + res.body.subject, true);
        }}).catch(() => {{ pbtn.disabled = false; say('Could not reach the server.', false); }});
      }});
      tbtn.addEventListener('click', () => {{
        const addr = to.value.trim();
        if (!addr || addr.indexOf('@') < 1) {{ say('Type the address to send the test to.', false); return; }}
        tbtn.disabled = true; say('Sending…', true);
        post('/admin/email/test', Object.assign({{ to: addr }}, fields())).then(res => {{
          tbtn.disabled = false;
          say(res.body.message || res.body.error || 'Failed.', !!res.body.success);
        }}).catch(() => {{ tbtn.disabled = false; say('Could not reach the server.', false); }});
      }});
    }})();

    // Access extended: same preview/test routes, kind = "extended".
    (function() {{
      const f = id => document.getElementById(id);
      const frame = f('extended-preview-frame'), status = f('extended-status');
      const pbtn = f('extended-preview-btn'), tbtn = f('extended-test-btn'), to = f('extended-test-to');
      function fields() {{
        return {{ kind: 'extended', extended_subject: f('extended-subject').value,
                 extended_text: f('extended-text').value }};
      }}
      function say(text, good) {{ status.textContent = text; status.style.color = good ? 'var(--ok)' : 'var(--bad)'; }}
      function post(url, body) {{
        return fetch(url, {{ method: 'POST', credentials: 'same-origin',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify(body) }})
          .then(r => r.json().then(j => ({{ status: r.status, body: j }})));
      }}
      pbtn.addEventListener('click', () => {{
        pbtn.disabled = true; say('Loading preview…', true);
        post('/admin/email/preview', fields()).then(res => {{
          pbtn.disabled = false;
          if (!res.body.success) {{ say(res.body.error || 'Preview failed.', false); return; }}
          frame.srcdoc = res.body.html; frame.style.display = '';
          say('Subject: ' + res.body.subject, true);
        }}).catch(() => {{ pbtn.disabled = false; say('Could not reach the server.', false); }});
      }});
      tbtn.addEventListener('click', () => {{
        const addr = to.value.trim();
        if (!addr || addr.indexOf('@') < 1) {{ say('Type the address to send the test to.', false); return; }}
        tbtn.disabled = true; say('Sending…', true);
        post('/admin/email/test', Object.assign({{ to: addr }}, fields())).then(res => {{
          tbtn.disabled = false;
          say(res.body.message || res.body.error || 'Failed.', !!res.body.success);
        }}).catch(() => {{ tbtn.disabled = false; say('Could not reach the server.', false); }});
      }});
    }})();

    // Widget look: two live previews (dark page / light page). Each is the
    // real /cp.js running in a sandboxed frame with the unsaved form values
    // handed to it, so what you see is what a visitor will get once saved.
    (function() {{
      const f = id => document.getElementById(id);
      const dark = f('wl-frame-dark'), light = f('wl-frame-light');
      const form = f('wl-theme').form;
      function values() {{
        const v = {{ accent_color: form.elements['accent_color'].value }};
        ['widget_theme', 'widget_font', 'widget_corners', 'widget_bg', 'widget_text',
         'widget_banner_text', 'widget_drop_title', 'widget_drop_sub',
         'widget_signup_title', 'widget_signup_sub', 'widget_button_text',
         'widget_terms_url', 'widget_privacy_url'].forEach(n => {{ v[n] = form.elements[n].value; }});
        return v;
      }}
      function pageDoc(bg, fg, font) {{
        const S = '<' + '/script>';
        return '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>' +
          '<body style="margin:0;padding:18px;background:' + bg + ';color:' + fg + ';font-family:' + font + ';">' +
          '<p style="margin:0 0 14px;font-size:13px;opacity:.7;">Your page &mdash; the widget sits below.</p>' +
          '<div id="credential-widget"></div>' +
          '<script>window.__cpOverride = ' + JSON.stringify(values()).replace(/</g, '\\\\u003c') + ';' + S +
          '<script src="' + window.location.origin + '/cp.js">' + S +
          '<script>window.addEventListener("message", function(e) {{ if (e.data === "wl-popup") {{ var b = document.getElementById("ca-banner"); if (b) b.click(); }} }});' + S +
          '</body></html>';
      }}
      let timer = null;
      function refresh() {{
        f('wl-custom').style.display = f('wl-theme').value === 'custom' ? 'flex' : 'none';
        dark.srcdoc  = pageDoc('#0d0d0f', '#e8e6e3', 'Georgia, serif');
        light.srcdoc = pageDoc('#f6f3ec', '#26231f', 'Helvetica, Arial, sans-serif');
      }}
      function later() {{ clearTimeout(timer); timer = setTimeout(refresh, 450); }}
      ['wl-theme', 'wl-font', 'wl-corners', 'wl-bg', 'wl-text', 'wl-banner', 'wl-drop-title', 'wl-drop-sub',
       'wl-signup-title', 'wl-signup-sub', 'wl-button', 'wl-terms', 'wl-privacy'].forEach(id => {{
        f(id).addEventListener('input', later); f(id).addEventListener('change', later);
      }});
      form.elements['accent_color'].addEventListener('input', later);
      f('wl-popup-btn').addEventListener('click', () => {{
        [dark, light].forEach(fr => {{ try {{ fr.contentWindow.postMessage('wl-popup', '*'); }} catch (e) {{}} }});
      }});
      refresh();
    }})();

    // Dashboard style picker: highlight the chosen card.
    document.querySelectorAll('.style-card input').forEach(r => r.addEventListener('change', () => {{
      document.querySelectorAll('.style-card').forEach(c => c.classList.toggle('on', c.querySelector('input').checked));
    }}));

    function decidePaymentRequest(id, action, btn) {{
      const verb = action === 'approve' ? 'Approve this payment and issue the credential?'
                                         : 'Reject this request? No credential will be issued.';
      if (!confirm(verb)) return;
      const row = btn.closest('tr');
      row.querySelectorAll('button').forEach(b => b.disabled = true);
      fetch(`/admin/payment-requests/${{id}}/${{action}}`, {{ method: 'POST' }})
        .then(r => r.json())
        .then(data => {{
          if (data.success) {{
            location.reload();
          }} else {{
            alert((action === 'approve' ? 'Approve' : 'Reject') + ' failed: ' + (data.error || 'unknown error'));
            row.querySelectorAll('button').forEach(b => b.disabled = false);
          }}
        }})
        .catch(e => {{
          alert((action === 'approve' ? 'Approve' : 'Reject') + ' failed: ' + e.message);
          row.querySelectorAll('button').forEach(b => b.disabled = false);
        }});
    }}
    (function() {{
      const sel = document.querySelector('select[name=payment_provider]');
      if (!sel) return;
      const box = document.getElementById('custom-box'), sbox = document.getElementById('stripe-box');
      const show = () => {{
        if (box) box.style.display = sel.value === 'custom' ? '' : 'none';
        if (sbox) sbox.style.display = sel.value === 'stripe' ? '' : 'none';
        document.querySelectorAll('.pv-hint').forEach(h => {{ h.style.display = h.dataset.for === sel.value ? '' : 'none'; }});
      }};
      sel.addEventListener('change', show);
    }})();

    document.querySelectorAll('.approve-req-btn').forEach(btn => {{
      btn.addEventListener('click', () => decidePaymentRequest(btn.dataset.id, 'approve', btn));
    }});
    document.querySelectorAll('.reject-req-btn').forEach(btn => {{
      btn.addEventListener('click', () => decidePaymentRequest(btn.dataset.id, 'reject', btn));
    }});
  </script>
{theme_js}
</body></html>"""


# ── POST /admin/email/preview, /admin/email/test ──
# The dashboard's "Welcome email" section. Both take the three wording
# fields as currently typed (saved or not). Preview renders the email for a
# made-up member and sends nothing; test sends that same sample to one
# address (no attachments). Neither touches the registry.
def _email_overrides(data: dict) -> dict:
    return {
        "email_subject": str(data.get("email_subject") or "")[:email_sender.MAX_SUBJECT * 2],
        "email_intro":   str(data.get("email_intro") or "")[:email_sender.MAX_INTRO * 2],
        "email_signoff": str(data.get("email_signoff") or "")[:email_sender.MAX_SIGNOFF * 2],
    }

def _reminder_overrides(data: dict) -> dict:
    return {
        "reminder_subject": str(data.get("reminder_subject") or "")[:email_sender.MAX_REMINDER_SUBJECT * 2],
        "reminder_text":    str(data.get("reminder_text") or "")[:email_sender.MAX_REMINDER_TEXT * 2],
        "reminder_renew_url": str(data.get("reminder_renew_url") or ""),
    }

def _extended_overrides(data: dict) -> dict:
    return {
        "extended_subject": str(data.get("extended_subject") or "")[:email_sender.MAX_EXTENDED_SUBJECT * 2],
        "extended_text":    str(data.get("extended_text") or "")[:email_sender.MAX_EXTENDED_TEXT * 2],
    }

def _sample_tier() -> str:
    tiers = load_config().get("tiers") or []
    return (tiers[0].get("name") if tiers else "") or "MEMBER"

@app.route("/admin/email/preview", methods=["POST"])
def admin_email_preview():
    if not check_admin(request):
        return jsonify({"success": False, "error": "Not logged in."}), 401
    data = request.get_json(silent=True) or {}
    if data.get("kind") == "reminder":
        msg = email_sender.preview_reminder(_sample_tier(), _reminder_overrides(data))
    elif data.get("kind") == "extended":
        msg = email_sender.preview_extended(_sample_tier(), _extended_overrides(data))
    else:
        msg = email_sender.preview_email(_sample_tier(), _email_overrides(data))
    return jsonify({"success": True, "subject": msg["subject"], "html": msg["html"]})

@app.route("/admin/email/test", methods=["POST"])
def admin_email_test():
    if not check_admin(request):
        return jsonify({"success": False, "error": "Not logged in."}), 401
    data = request.get_json(silent=True) or {}
    to = str(data.get("to") or "").strip()
    if len(to) > 254 or "@" not in to[1:] or any(c in to for c in " \r\n<>,;"):
        return jsonify({"success": False, "message": "That doesn't look like an email address."}), 400
    if data.get("kind") == "reminder":
        ok_, message = email_sender.send_test_email(to, _sample_tier(), _reminder_overrides(data), kind="reminder")
    elif data.get("kind") == "extended":
        ok_, message = email_sender.send_test_email(to, _sample_tier(), _extended_overrides(data), kind="extended")
    else:
        ok_, message = email_sender.send_test_email(to, _sample_tier(), _email_overrides(data))
    return jsonify({"success": ok_, "message": message}), (200 if ok_ else 502)


# ── Card previews ──
# Every preview renders a real card through card_generator (the same code
# /issue uses) with dummy member data; nothing is saved and the registry is
# never touched.
def _render_preview_card(cfg: dict, design: dict, tier_name: str = "MEMBER", creator_name: str = None,
                         kind: str = "pass") -> str:
    from datetime import timedelta as _td
    from card_generator import generate_card
    now = datetime.now(timezone.utc)
    return generate_card(
        credential_id = "preview0000demo",
        holder_name   = "Preview Member",
        tier          = tier_name,
        issued_at     = now.isoformat(),
        expires_at    = (now + _td(days=31)).isoformat(),
        bundle_hash   = "0" * 64,
        signature_hex = "0" * 128,
        sections      = [],
        card_title    = design["card_title"],
        card_subtitle = f"{tier_name} Card",
        access_url    = cfg["members_page"] or "https://example.com/members.html",
        creator_name  = creator_name or cfg["creator_name"],
        accent_color  = design["accent_color"],
        show_barcode  = design["show_barcode"],
        logo_data_uri = design["logo_data_uri"],
        card_label    = design["card_label"],
        card_style    = design["card_style"],
        qr_style      = design["qr_style"],
        background_data_uri = design.get("background_data_uri"),
        background_dim      = design.get("background_dim", card_looks.DEFAULT_DIM),
        kind          = kind if kind in ("ticket", "collectible") else "pass",
        event         = card_kinds.sample_event() if kind == "ticket" else None,
        drop          = card_kinds.sample_drop() if kind == "collectible" else None,
        save          = False,
    )

def _preview_error_page(message: str) -> str:
    return ('<body style="background:#050403;color:#f0c674;font-family:monospace;padding:24px">'
            f'⚠ {esc_html(message)}</body>')

# POST /admin/dashboard/preview-card — the Default look, from what is typed in
# Branding right now (saved or not).
@app.route("/admin/dashboard/preview-card", methods=["POST"])
def admin_dashboard_preview_card():
    if not is_admin_session():
        return err("Unauthorized", 401)

    cfg = load_config()
    typed_style = (request.form.get("card_style") or "").strip()
    uploaded, logo_err = _encode_upload_as_data_uri(request.files.get("logo"))
    if logo_err:
        return _preview_error_page(logo_err), 400
    bg_up, bg_err = _encode_background_upload(request.files.get("bg"))
    if bg_err:
        return _preview_error_page(bg_err), 400

    tiers = cfg.get("tiers") or []
    bg = bg_up or ("" if request.form.get("bg_clear") == "1" else cfg.get("bg_data_uri") or "")
    dim = (request.form.get("bg_dim") or "").strip()
    design = {
        "card_title":    (request.form.get("card_title") or "").strip() or cfg["card_title"],
        "accent_color":  card_looks.clean_color(request.form.get("accent_color")) or cfg["accent_color"],
        "show_barcode":  True,
        "logo_data_uri": uploaded or (None if request.form.get("logo_clear") == "1" else (cfg.get("logo_data_uri") or None)),
        "card_label":    (request.form.get("card_subtitle") or "").strip() or cfg["card_subtitle"],
        "card_style":    typed_style if typed_style in CARD_STYLES else cfg["card_style"],
        "qr_style":      (request.form.get("qr_style") or "").strip() if (request.form.get("qr_style") or "").strip() in card_looks.QR_STYLES else cfg["qr_style"],
        "background_data_uri": bg or None,
        "background_dim": dim if dim in card_looks.DIMS else cfg["bg_dim"],
    }
    try:
        return _render_preview_card(cfg, design,
                                    tier_name=(tiers[0].get("name") if tiers else "") or "MEMBER",
                                    creator_name=(request.form.get("creator_name") or "").strip() or cfg["creator_name"])
    except Exception as e:
        return err(f"Preview failed: {str(e)}", 500)


# ── Card looks ──
# The "Card looks" screen (looks_page.py): a list of saved looks, each with a
# name; a tier picks one. These routes save/copy/delete a look and render its
# preview. Pictures arrive as uploads and are shrunk and re-encoded here.
def _looks_payload(cfg: dict = None) -> dict:
    cfg = cfg or load_config()
    return {"looks": [card_looks.summary(l, cfg["tiers"]) for l in cfg["card_looks"]]}

def _look_from_form(base: dict = None):
    """The look typed in the editor -> (clean look, "" ) or (None, reason).
    `base` is the saved look being edited (its pictures are kept unless
    replaced or removed)."""
    f = request.form
    logo, e1 = _encode_upload_as_data_uri(request.files.get("logo"))
    bg, e2 = _encode_background_upload(request.files.get("bg"))
    if e1 or e2:
        return None, e1 or e2
    base = base or {}
    return card_looks.clean_look({
        "id":            base.get("id") or "000000000000",
        "name":          f.get("name"),
        "card_title":    f.get("card_title"),
        "accent_color":  "" if f.get("accent_same") == "1" else f.get("accent_color"),
        "card_label":    f.get("card_label"),
        "card_style":    f.get("card_style"),
        "qr_style":      f.get("qr_style"),
        "show_barcode":  f.get("barcode", "on") != "off",
        "logo_data_uri": logo or ("" if f.get("logo_clear") == "1" else base.get("logo_data_uri", "")),
        "bg_data_uri":   bg or ("" if f.get("bg_clear") == "1" else base.get("bg_data_uri", "")),
        "bg_dim":        f.get("bg_dim"),
    }), ""

def _looks_error(message: str, status: int = 400):
    return jsonify({"success": False, "error": message}), status

@app.route("/admin/looks/save", methods=["POST"])
def admin_looks_save():
    if not is_admin_session():
        return _looks_error("Not logged in.", 401)
    _migrate_card_looks()
    raw = _read_config_file()
    looks = card_looks.clean_looks(raw.get("card_looks"))
    look_id = (request.form.get("id") or "").strip()
    base = card_looks.get(looks, look_id) if look_id else None
    if look_id and not base:
        return _looks_error("That look no longer exists. Reload the page.", 404)
    if not base and len(looks) >= card_looks.MAX_LOOKS:
        return _looks_error(f"You can have up to {card_looks.MAX_LOOKS} looks. Delete one you don't use first.", 409)
    look, problem = _look_from_form(base)
    if problem:
        return _looks_error(problem)
    problem = card_looks.name_problem(looks, card_looks.clean_name(request.form.get("name")), own_id=base["id"] if base else None)
    if problem:
        return _looks_error(problem)
    if base:
        look["id"] = base["id"]
        looks = [look if l["id"] == base["id"] else l for l in looks]
    else:
        look["id"] = card_looks.new_id(looks)
        looks.append(look)
    save_config({"card_looks": looks})
    cfg = load_config()
    payload = _looks_payload(cfg)
    payload.update({"success": True, "id": look["id"]})
    return jsonify(payload)

@app.route("/admin/looks/copy", methods=["POST"])
def admin_looks_copy():
    if not is_admin_session():
        return _looks_error("Not logged in.", 401)
    _migrate_card_looks()
    raw = _read_config_file()
    looks = card_looks.clean_looks(raw.get("card_looks"))
    src = card_looks.get(looks, (request.form.get("id") or "").strip())
    if not src:
        return _looks_error("That look no longer exists. Reload the page.", 404)
    if len(looks) >= card_looks.MAX_LOOKS:
        return _looks_error(f"You can have up to {card_looks.MAX_LOOKS} looks. Delete one you don't use first.", 409)
    dup = dict(src)
    dup["id"] = card_looks.new_id(looks)
    dup["name"] = card_looks.unique_name(looks, f"{src['name']} copy")
    looks.append(dup)
    save_config({"card_looks": looks})
    payload = _looks_payload()
    payload.update({"success": True, "id": dup["id"]})
    return jsonify(payload)

@app.route("/admin/looks/delete", methods=["POST"])
def admin_looks_delete():
    if not is_admin_session():
        return _looks_error("Not logged in.", 401)
    _migrate_card_looks()
    raw = _read_config_file()
    looks = card_looks.clean_looks(raw.get("card_looks"))
    look_id = (request.form.get("id") or "").strip()
    if not card_looks.get(looks, look_id):
        return _looks_error("That look no longer exists. Reload the page.", 404)
    # Tiers that used it go back to the Default look (their cards already
    # issued keep the look they were made with).
    tiers = raw.get("tiers") if isinstance(raw.get("tiers"), list) else []
    moved = []
    for t in tiers:
        if isinstance(t, dict) and t.get("look") == look_id:
            t.pop("look", None)
            moved.append(str(t.get("name", "")))
    save_config({"card_looks": [l for l in looks if l["id"] != look_id], "tiers": tiers})
    payload = _looks_payload()
    payload.update({"success": True, "moved": moved})
    return jsonify(payload)

@app.route("/admin/looks/preview", methods=["POST"])
def admin_looks_preview():
    """A card drawn from what is typed in the editor (saved or not). Sends
    `id` when editing, so pictures already saved are still shown."""
    if not is_admin_session():
        return err("Unauthorized", 401)
    cfg = load_config()
    base = card_looks.get(cfg["card_looks"], (request.form.get("id") or "").strip())
    look, problem = _look_from_form(base)
    if problem:
        return _preview_error_page(problem), 400
    tiers = cfg.get("tiers") or []
    try:
        return _render_preview_card(cfg, resolve_look(cfg, look),
                                    tier_name=(tiers[0].get("name") if tiers else "") or "MEMBER",
                                    kind=request.form.get("preview_kind") or "pass")
    except Exception as e:
        return err(f"Preview failed: {str(e)}", 500)

@app.route("/admin/looks/preview/<look_id>", methods=["GET"])
def admin_looks_preview_saved(look_id):
    """A saved look as a card ("default" = the Default look from Branding)."""
    if not is_admin_session():
        return err("Unauthorized", 401)
    cfg = load_config()
    tiers = cfg.get("tiers") or []
    if look_id == "default":
        design = resolve_look(cfg)
    else:
        look = card_looks.get(cfg["card_looks"], look_id)
        if not look:
            return err("Not found", 404)
        design = resolve_look(cfg, look)
    try:
        return _render_preview_card(cfg, design, tier_name=(tiers[0].get("name") if tiers else "") or "MEMBER")
    except Exception as e:
        return err(f"Preview failed: {str(e)}", 500)


# ── GET/POST /admin/content ──
# The Content manager: what members see after they verify (see
# content_store.py / content_page.py). Saves to DATA_DIR/content.json, so it
# survives redeploys like the rest of the settings.
def _storage_numbers():
    """(bytes used by members, key and settings, size of the storage the data
    lives on). The total comes from the disk itself (the Railway Volume when
    attached); 0 when it can't be read."""
    try:
        data = backup.sizes(DATA_DIR)["data_bytes"]
    except Exception:
        data = 0
    try:
        import shutil
        total = shutil.disk_usage(str(DATA_DIR)).total
    except Exception:
        total = 0
    return data, total

@app.route("/admin/content", methods=["GET"])
def admin_content():
    redirect_resp = require_admin_page("/admin/content")
    if redirect_resp:
        return redirect_resp
    cfg = load_config()
    resp = app.response_class(
        content_page.render(cfg["accent_color"], cfg["card_title"], content_store.load(), cfg.get("tiers") or [],
                            max_mb=MAX_UPLOAD_MB, used_bytes=content_store.used_bytes(),
                            data_bytes=_storage_numbers()[0], disk_total=_storage_numbers()[1],
                            theme_css=admin_theme.css(cfg["admin_style"], cfg["accent_color"], "page"),
                            theme_js=admin_theme.shell_js(cfg["admin_style"]),
                            body_attrs=admin_theme.body_attrs(cfg["admin_style"], "content", cfg["card_title"])),
        mimetype="text/html")
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.route("/admin/content", methods=["POST"])
def admin_content_save():
    if not check_admin(request):
        return jsonify({"success": False, "error": "Not logged in."}), 401
    payload = request.get_json(silent=True) if request.is_json else None
    # Refuse anything that isn't {"sections": [...]} rather than treating it
    # as "empty" and wiping the saved content.
    if not isinstance(payload, dict) or not isinstance(payload.get("sections"), list):
        return jsonify({"success": False, "error": "Expected JSON like {\"sections\": [...]}."}), 400
    clean, warnings = content_store.save(payload)
    content_store.cleanup_orphans(clean)   # files no item uses any more (after a grace period)
    return jsonify({"success": True, "content": clean, "warnings": warnings})

# Upload a file for an item on the Content page. The file is stored right
# away, but only becomes part of the content once the page is saved.
@app.route("/admin/content/upload", methods=["POST"])
def admin_content_upload():
    if not check_admin(request):
        return jsonify({"success": False, "error": "Not logged in."}), 401
    meta, error = content_store.save_upload(request.files.get("file"), MAX_UPLOAD_BYTES)
    if not meta:
        return jsonify({"success": False, "error": error}), 400
    # An uploaded picture gets its thumbnail automatically (None for other files).
    preview = content_store.make_preview_from_stored(meta["id"])
    return jsonify({"success": True, "file": meta, "preview": preview, "used_bytes": content_store.used_bytes()})


# A preview picture for an item (any item: a link, a file, something for sale).
# Stored as a small JPEG thumbnail; becomes part of the content once saved.
@app.route("/admin/content/preview", methods=["POST"])
def admin_content_preview():
    if not check_admin(request):
        return jsonify({"success": False, "error": "Not logged in."}), 401
    meta, error = content_store.make_preview(request.files.get("file"))
    if not meta:
        return jsonify({"success": False, "error": error}), 400
    return jsonify({"success": True, "preview": meta, "used_bytes": content_store.used_bytes()})


# The thumbnail itself, for the Content page's own display (admin only).
@app.route("/admin/content/preview/<pid>", methods=["GET"])
def admin_content_preview_get(pid):
    if not check_admin(request):
        return app.response_class("Not logged in.", status=401, mimetype="text/plain")
    return _send_thumb(pid)


def _send_thumb(pid):
    """A stored thumbnail as an image. Thumbnails are always re-encoded JPEGs
    made by content_store.make_preview, so the type is fixed here."""
    from flask import send_file
    path = content_store.path_for(pid)
    if path is None or not path.is_file():
        return app.response_class("Not found.", status=404, mimetype="text/plain")
    resp = send_file(path, mimetype="image/jpeg", conditional=True, max_age=0)
    resp.headers["Cache-Control"] = "private, no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


# ── Backup and restore (see backup.py) ──
# Download one zip with everything this deployment owns. Works from the
# dashboard (logged in) and from a script with the admin secret header, so a
# creator can also automate it: curl -H "X-Admin-Secret: …" -o backup.zip
# "https://your-domain/admin/backup/download?files=1"
@app.route("/admin/backup/download", methods=["GET"])
def admin_backup_download():
    if not check_admin(request):
        return redirect("/admin/login?next=/admin/dashboard")
    include_uploads = request.args.get("files") == "1"
    sz = backup.sizes(DATA_DIR)
    need = sz["data_bytes"] + (sz["uploads_bytes"] if include_uploads else 0)
    if backup.free_bytes(DATA_DIR) < need + backup.SPARE_BYTES:
        return redirect("/admin/dashboard?backup_note=" + _q("There isn't enough free storage on this server to prepare that backup. "
                        "Try the one without uploaded files.") + "#backup")
    for stale in DATA_DIR.glob(".backup-*.zip"):          # leftovers from an interrupted earlier backup
        try:
            if time.time() - stale.stat().st_mtime > 600:
                stale.unlink()
        except OSError:
            pass
    fd, tmp_path = tempfile.mkstemp(dir=str(DATA_DIR), prefix=".backup-", suffix=".zip")
    try:
        with os.fdopen(fd, "wb") as f:
            backup.build_backup(DATA_DIR, f, include_uploads=include_uploads,
                                creator_name=load_config().get("creator_name", ""))
    except Exception as e:
        try: os.remove(tmp_path)
        except OSError: pass
        print("Backup failed:", e)
        return redirect("/admin/dashboard?backup_note=" + _q(f"The backup could not be prepared: {e}") + "#backup")
    backup.record_backup(DATA_DIR)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    name = f"credential-backup-{stamp}{'-with-files' if include_uploads else ''}.zip"
    from flask import send_file
    # Open the finished zip, then delete its name: on Linux the open handle
    # keeps the bytes readable until the download ends, and nothing is left
    # behind to clean up afterwards. (Where a file can't be deleted while it
    # is open, e.g. Windows, it stays and is swept up by the next download.)
    fh = open(tmp_path, "rb")
    try:
        os.remove(tmp_path)
    except OSError:
        pass
    resp = send_file(fh, mimetype="application/zip", as_attachment=True, download_name=name, conditional=False)
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.route("/admin/backup/restore", methods=["POST"])
def admin_backup_restore():
    if not check_admin(request):
        return redirect("/admin/login?next=/admin/dashboard")
    def back(msg, good=False):
        return redirect("/admin/dashboard?" + ("backup_ok=1&" if good else "") + "backup_note=" + _q(msg[:400]) + "#backup")
    if (request.form.get("confirm") or "").strip().upper() != "RESTORE":
        return back("Nothing was restored. Type RESTORE in the box to confirm.")
    up = request.files.get("backup")
    if not up or not up.filename:
        return back("Nothing was restored. Choose a backup file first.")
    fd, tmp_path = tempfile.mkstemp(dir=str(DATA_DIR), prefix=".upload-", suffix=".zip")
    os.close(fd)
    try:
        up.save(tmp_path)
        info = backup.restore_backup(Path(tmp_path), DATA_DIR, MAX_RESTORE_BYTES * 2, lock=_signup_lock)
    except backup.BackupError as e:
        return back(str(e))
    except Exception as e:
        print("Restore failed:", e)
        return back(f"The restore failed and nothing was changed ({e}).")
    finally:
        try: os.remove(tmp_path)
        except OSError: pass
    n = info.get("members")
    return back(f"Backup restored ({n if n is not None else 'unknown number of'} members). "
                "Your previous data was kept aside on the server in case you need it.", good=True)

@app.route("/config", methods=["GET"])
def get_config():
    cfg = config_store.read_config()
    if not cfg:
        return err("config.json not found", 404)
    # Public on purpose (the widget draws itself from it), so only what a
    # visitor needs: branding and the tier list. Not the card logos (large),
    # payment instructions, email wording or any per-tier design.
    public = {k: cfg[k] for k in ("creator_name", "card_title", "card_subtitle", "accent_color",
                                  "currency", "payment_provider", "members_page", "api_base") if k in cfg}
    # The widget's look (colors/wording choices) is public by nature too.
    public.update(widget_look.from_config(cfg))
    tiers = [t for t in (cfg.get("tiers") or []) if isinstance(t, dict)]
    public["tiers"] = [{**{k: t[k] for k in ("name", "label", "price", "expiry_days", "sections") if k in t},
                        **({"kind": "ticket", "event": card_kinds.public_event(t)} if card_kinds.is_ticket(t) else {}),
                        **({"kind": "collectible", "drop": card_kinds.public_drop(t)} if card_kinds.is_collectible(t) else {})}
                       for t in tiers]
    # An optional locked preview of the members-only content: item titles only,
    # for the sections the creator marked as a teaser (never links or files).
    try:
        tz_list = content_store.teaser(content_store.load(), tiers)
    except Exception:
        tz_list = []
    if tz_list:
        public["teaser"] = tz_list
    # Tiers with a member limit also say whether they are full (and, unless
    # the creator hides it, how many spots are left). Only read the member
    # list when at least one tier has a limit.
    if any(limits.tier_max(t) for t in tiers):
        from member_registry import list_all as registry_list
        from payment_requests import list_all as requests_list
        registry, requests = registry_list(), requests_list()
        for pub, t in zip(public["tiers"], tiers):
            pub.update(limits.public_state(t, registry, requests))
    return jsonify(public)

@app.route("/content", methods=["GET"])
def get_content():
    # Deliberately empty. Members-only content used to be served here to
    # anyone who asked, with the widget merely hiding it — so every download
    # link was readable by visiting this URL. It's now only ever returned by
    # POST /member-content, to a caller who proves they hold a valid credential.
    resp = jsonify({})
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ── Who may see members-only content ──
def _member_entry(cid: str, h: str = None):
    """The registry entry for a credential that is currently good: exists,
    not revoked, not expired, not on the revocation list — and, when `h`
    (the access code from the member's link / card / bundle) is given, the
    code matches. None otherwise. Checked against the live registry every
    time, so revoking or expiring someone cuts them off immediately."""
    try:
        from member_registry import get_by_id
        from credential_verifier import is_on_revocation_list
        entry = get_by_id(cid)
        if not entry or entry.get("revoked"):
            return None
        if datetime.fromisoformat(entry["expires_at"]) < datetime.now(timezone.utc):
            return None
        if entry.get("used_at"):          # an event ticket that was already checked in
            return None
        if h is not None:
            stored = (entry.get("bundle_hash") or "").lower()
            n = min(len(h), 32)
            if len(h) < 16 or len(stored) < 16 or not hmac.compare_digest(stored[:n], h[:n]):
                return None
        if is_on_revocation_list(cid, entry.get("bundle_hash")):
            return None
        return entry
    except Exception:
        return None


def _file_token(cid: str, fid: str) -> str:
    """A short-lived, signed download ticket for one member and one file.
    A plain link can't carry the member's credentials safely, so
    /member-content hands out these instead."""
    msg = f"{cid}|{fid}|{int(time.time()) + FILE_TOKEN_TTL}"
    sig = hmac.new(app.secret_key.encode(), b"file-download|" + msg.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(msg.encode()).decode().rstrip("=") + "." + sig


def _check_file_token(token: str, fid: str):
    """The credential id a download ticket was issued to, or None if it is
    forged, for a different file, or expired."""
    try:
        body, sig = token.split(".", 1)
        msg = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode()
        want = hmac.new(app.secret_key.encode(), b"file-download|" + msg.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, want):
            return None
        cid, tok_fid, exp = msg.split("|")
        if tok_fid != fid or int(exp) < time.time():
            return None
        return cid
    except Exception:
        return None


# ── POST /member-content ──
# The members-only content a credential unlocks. Needs BOTH the credential
# id and its access hash (the `h` in the member's link / card QR), checked
# against the live registry on every call, and returns only the sections
# that credential's tier includes. Any failure gets the same generic
# answer, so this can't be used to probe which ids exist. Uploaded files
# come back as a `download` path with a short-lived ticket (/member-file).
@app.route("/member-content", methods=["POST"])
def member_content():
    denied = lambda: (jsonify({"success": False, "error": "Access denied."}), 403)
    data = request.get_json(silent=True) or {}
    cid  = str(data.get("credential_id") or "").strip()
    h    = str(data.get("bundle_hash") or "").strip().lower()
    if not cid or len(h) < 16:
        return denied()
    entry = _member_entry(cid, h)
    if not entry:
        return denied()
    try:
        sections = []
        for sec in content_store.sections_for_member(content_store.load(), entry.get("sections", [])):
            sec = dict(sec)
            if sec.get("type") == "links":
                items = []
                for it in sec.get("items", []):
                    it = dict(it)
                    f = it.pop("file", None)
                    pv = it.pop("preview", None)
                    if pv:
                        it["thumb"] = f"/member-preview/{pv['id']}?t={_file_token(cid, pv['id'])}"
                    if it.get("buy_url"):
                        # For sale: a Buy button only. The file/link behind it isn't offered here.
                        it["url"] = ""
                    elif f:
                        it["file"] = {"name": f["name"], "size": f["size"]}
                        it["download"] = f"/member-file/{f['id']}?t={_file_token(cid, f['id'])}"
                    items.append(it)
                sec["items"] = items
            sections.append(sec)
        out = {"success": True, "sections": sections}
        note = announcements.public_current()
        if note:
            out["announcement"] = note
        if _card_path(cid).is_file():
            t = _file_token(cid, "card")
            out["card"] = {"view": f"/member-card/{cid}?t={t}", "download": f"/member-card/{cid}?t={t}&dl=1"}
        resp = jsonify(out)
        resp.headers["Cache-Control"] = "no-store"
        return resp
    except Exception:
        return denied()


def _card_path(cid: str):
    """Where a member's card page is kept (the file need not exist)."""
    from card_generator import CARDS_DIR
    safe = re.sub(r"[^A-Za-z0-9_-]", "", str(cid))[:64]
    return CARDS_DIR / f"card_{safe}.html"


# ── GET /member-card/<credential id>?t=<ticket>[&dl=1] ──
# The member's own card, shown in the widget once they have proved their
# credential (the ticket comes from /member-content) and offered as a
# download. Re-checks that the credential is still good, like /member-file.
# Shown inside a sandbox so nothing on the page can reach the rest of the site.
@app.route("/member-card/<cid>", methods=["GET"])
def member_card(cid):
    from flask import send_file
    def denied():
        r = app.response_class("Access denied.", status=403, mimetype="text/plain")
        r.headers["Cache-Control"] = "no-store"
        return r
    if _check_file_token(request.args.get("t", ""), "card") != cid or not _member_entry(cid):
        return denied()
    path = _card_path(cid)
    if not path.is_file():
        return denied()
    download = request.args.get("dl") == "1"
    resp = send_file(path, mimetype="text/html", as_attachment=download,
                     download_name="membership-card.html", conditional=False, max_age=0)
    resp.headers["Cache-Control"] = "private, no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    if not download:
        resp.headers["Content-Security-Policy"] = "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox"
    return resp


# ── GET /member-preview/<id>?t=<ticket> ──
# An item's thumbnail. Same ticket rules as /member-file: the credential must
# still be good and the picture must belong to a section its tier includes.
@app.route("/member-preview/<pid>", methods=["GET"])
def member_preview(pid):
    def denied():
        r = app.response_class("Access denied.", status=403, mimetype="text/plain")
        r.headers["Cache-Control"] = "no-store"
        return r
    cid = _check_file_token(request.args.get("t", ""), pid)
    entry = _member_entry(cid) if cid else None
    if not entry or not content_store.find_preview_item(content_store.load(), pid, entry.get("sections", [])):
        return denied()
    return _send_thumb(pid)


# ── GET /member-file/<id>?t=<ticket> ──
# Download an uploaded file. Needs a ticket from /member-content (so the
# caller proved a valid credential moments ago), and re-checks that the
# credential is STILL good and that the file sits in a section its tier
# includes. Always sent as a download of unknown type — never displayed by
# the browser — so an uploaded .html file can't run on this site.
@app.route("/member-file/<fid>", methods=["GET"])
def member_file(fid):
    from flask import send_file
    def denied():
        r = app.response_class("Access denied.", status=403, mimetype="text/plain")
        r.headers["Cache-Control"] = "no-store"
        return r
    cid = _check_file_token(request.args.get("t", ""), fid)
    entry = _member_entry(cid) if cid else None
    if not entry:
        return denied()
    item = content_store.find_file_item(content_store.load(), fid, entry.get("sections", []))
    path = content_store.path_for(fid)
    if not item or path is None or not path.is_file():
        return denied()
    resp = send_file(path, mimetype="application/octet-stream", as_attachment=True,
                     download_name=item["file"]["name"], conditional=True, max_age=0)
    resp.headers["Cache-Control"] = "private, no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.route("/practice-pay", methods=["GET"])
def practice_pay():
    """A pretend payment page, for trying "Custom payment link" without a real
    service. Nothing is stored and no money moves; it only shows what it was
    given and says what to press next."""
    def clip(v, n=60):
        return esc_html("".join(ch for ch in str(v or "") if ch >= " " and ch != "\x7f")[:n])
    ref, amount, cur = clip(request.args.get("ref")), clip(request.args.get("amount"), 20), clip(request.args.get("currency"), 5)
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>Practice payment page</title>
<style>
  :root {{ color-scheme: light dark; --bg:#f5f5f2; --fg:#1b1b1b; --panel:#fff; --line:#d8d8d2; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#101112; --fg:#ececec; --panel:#1a1c1e; --line:#33363a; }} }}
  html,body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }}
  main {{ max-width:480px; margin:0 auto; padding:40px 16px; }}
  .box {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:24px; }}
  h1 {{ font-size:1.2rem; margin:0 0 6px; }}
  .tag {{ display:inline-block; font-size:.75rem; padding:2px 8px; border:1px solid var(--line); border-radius:99px; margin-bottom:14px; }}
  code {{ background:rgba(128,128,128,.18); padding:2px 6px; border-radius:4px; word-break:break-all; }}
  ol {{ padding-left:20px; }}
</style></head><body><main><div class="box">
<span class="tag">PRACTICE: no real payment</span>
<h1>This is a pretend payment page</h1>
<p>Nothing here takes money. It only shows that the "Pay" button sent you to the right place{(" with your details filled in" if (ref or amount) else "")}.</p>
{f'<p>Your reference: <code>{ref}</code></p>' if ref else ''}{f'<p>Amount: <code>{amount} {cur}</code></p>' if amount else ''}
<p><b>Now, as the creator:</b></p>
<ol><li>Open your dashboard and the <b>Payment</b> screen.</li><li>Find this request under <b>Payments waiting for your OK</b>.</li><li>Press <b>Approve</b>. That sends the member their card.</li></ol>
</div></main></body></html>"""
    resp = make_response(html)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/members", methods=["GET"])
@app.route("/members.html", methods=["GET"])
def members_page_builtin():
    """The built-in Members page: the widget on a plain page, so links work
    without a website of your own."""
    cfg = load_config()
    name = esc_html(cfg.get("creator_name") or "Members")
    accent = cfg.get("accent_color") or "#00e87a"
    accent = accent if re.fullmatch(r"#[0-9a-fA-F]{3,8}", accent) else "#00e87a"
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} - Members</title>
<style>
  :root {{ color-scheme: light dark; --bg:#f5f5f2; --fg:#1b1b1b; --accent:{accent}; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#101112; --fg:#ececec; }} }}
  html,body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }}
  main {{ max-width:560px; margin:0 auto; padding:32px 16px 64px; }}
  h1 {{ font-size:1.4rem; margin:0 0 20px; }}
</style></head>
<body><main>
<h1>{name}</h1>
<div id="credential-widget"></div>
<script src="/cp.js"></script>
</main></body></html>"""
    resp = make_response(html)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp


@app.route("/cp.js", methods=["GET"])
def serve_widget():
    from flask import send_file
    return send_file(BASE_DIR / "cp.js", mimetype="application/javascript")

# ── Expiry reminders (rules in reminders.py) ──
# A small background thread wakes up about once an hour, and emails every
# member whose access is about to end (once per end date). It does nothing
# unless reminders are switched on in the dashboard AND email is set up.
# Set REMINDERS_DISABLED=1 to keep it from starting (used by the tests).
def _send_reminder(entry: dict, days_left: int) -> bool:
    return email_sender.send_reminder_email(
        entry.get("holder_name", ""), entry.get("holder_email", ""), entry.get("tier", ""),
        entry["credential_id"], entry.get("bundle_hash", ""), entry["expires_at"], days_left)

def run_reminders_now(now=None) -> dict:
    """One pass of the reminder job; returns {"sent": n, "failed": n}."""
    window = load_config().get("reminder_days") or 0
    if not window or not email_sender.is_configured():
        return {"sent": 0, "failed": 0}
    return reminders.run_once(window, _send_reminder, now)

def _reminder_loop(first_delay: float, interval: float):
    time.sleep(first_delay)
    while True:
        try:
            done = run_reminders_now()
            if done["sent"] or done["failed"]:
                print(f"ℹ Reminders: {done['sent']} sent, {done['failed']} failed")
        except Exception as e:   # never let the job die quietly for good
            print(f"❌ Reminder job error: {e}")
        time.sleep(interval)

_reminder_thread = None

def start_reminder_thread(first_delay: float = 120, interval: float = reminders.CHECK_EVERY_SECONDS):
    global _reminder_thread
    if _reminder_thread and _reminder_thread.is_alive():
        return _reminder_thread
    _reminder_thread = threading.Thread(target=_reminder_loop, args=(first_delay, interval),
                                        name="reminders", daemon=True)
    _reminder_thread.start()
    return _reminder_thread

if os.environ.get("REMINDERS_DISABLED", "").strip().lower() not in ("1", "true", "yes"):
    start_reminder_thread()

# Startup warnings, printed at import time rather than under __main__ so
# they show up in the logs however the app is started: `python
# credential_api.py` locally, or gunicorn on Railway (which imports this
# module and never runs the __main__ block below).
if not ADMIN_SECRET:
    print("⚠ ADMIN_SECRET is not set — admin login, /revoke, and /admin/members will refuse everyone until it is.")
print("ℹ Payment provider defaults to 'manual' (admin-approval queue, no account needed) until changed in /admin/dashboard.")
if not (stripe and STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET):
    print("⚠ Stripe is not fully configured — switching payment_provider to 'stripe' will refuse checkout until it is. See SETUP.md.")

if __name__ == "__main__":
    # Local development entry point (`python credential_api.py`) — Flask's
    # built-in dev server. In production, Railway starts the app with
    # gunicorn instead (see Procfile), which imports `app` directly.
    port = int(os.environ.get("PORT", 5001))
    print(f"Credential Protocol API — http://localhost:{port}")
    print(f"POST /issue          — issue a free-tier credential directly")
    print(f"POST /checkout       — start a paid-tier purchase (free tiers issue instantly;")
    print(f"                       paid tiers route through config.json's payment_provider)")
    print(f"POST /webhook/stripe — Stripe calls this on payment completion (payment_provider=stripe only)")
    print(f"POST /admin/payment-requests/<id>/approve, /reject — decide a manual payment request")
    print(f"POST /verify         — verify a credential")
    print(f"POST /revoke         — revoke a credential")
    print(f"GET  /status         — health check")
    print(f"GET  /revocation-list — revocation list")
    print()
    print("GET  /admin/login     — admin login (password = ADMIN_SECRET)")
    print("GET  /admin/dashboard — edit branding/tiers/pricing/payment provider")
    print("GET  /admin/members   — view/revoke credentials")
    print("GET  /admin/content   — manage the members-only content (and upload files for it)")
    print()
    print("Set these env vars before running (see SETUP.md):")
    print("  GMAIL_ADDRESS      — your verified Brevo sender address")
    print("  BREVO_API_KEY      — your Brevo transactional API key")
    print("  MEMBERS_PAGE       — https://your-domain.com/members.html")
    print("  ADMIN_SECRET       — admin login password / API secret")
    print("  SESSION_SECRET_KEY — signs the admin session cookie (set for persistent logins)")
    print("  DATA_DIR           — persistent storage path in production (also where the")
    print("                       signing keypair lives — see credential_issuer.py)")
    print("  STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET — only needed if payment_provider is 'stripe'")
    # Debug mode is OFF unless explicitly turned on — fine (and useful) for
    # local testing, a real risk on a public deployment: an unhandled
    # error can expose Flask's interactive debugger, which lets whoever
    # triggered it run code on the server. Set FLASK_DEBUG=1 locally if
    # you want tracebacks/auto-reload back; never set it on Railway.
    debug_mode = os.environ.get("FLASK_DEBUG", "").strip().lower() in ("1", "true", "yes")
    if debug_mode:
        print("⚠ FLASK_DEBUG is on — fine for local testing, never set this on a public deployment.")
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
