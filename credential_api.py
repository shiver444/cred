"""
Credential Protocol — API Server
Flask HTTP server handling:
  POST /issue       — issue a FREE-tier credential directly
  POST /checkout    — start a paid-tier purchase. Free tiers issue
                       instantly; paid tiers route through whichever
                       `payment_provider` config.json names — "manual"
                       (default: an admin-approval queue, no payment
                       account needed, works in any country) or "stripe"
                       (automatic card checkout, needs STRIPE_SECRET_KEY).
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

from flask import Flask, request, jsonify, session, redirect
from flask_cors import CORS
from pathlib import Path
from datetime import datetime, timezone, timedelta
from html import escape as esc_html
import json
import os
import secrets

try:
    import stripe
except ImportError:
    stripe = None  # payments simply stay disabled — see check_payments_configured()

# Importing this at startup (not lazily, inside a route) guarantees the
# signing keypair exists — generated automatically on first boot if
# missing — before this app serves a single request, not just after the
# first /issue call. See credential_issuer.py's _ensure_keypair().
import credential_issuer  # noqa: F401

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
    return secret == ADMIN_SECRET

def require_admin_page(next_path: str):
    """For admin PAGES (not API calls): redirect to the login page instead
    of a bare 401, carrying where to return to afterward. Returns None when
    already authenticated — caller proceeds as normal."""
    if is_admin_session():
        return None
    return redirect(f"/admin/login?next={next_path}")

def _read_config_file() -> dict:
    config_file = BASE_DIR / "config.json"
    if not config_file.exists():
        return {}
    try:
        with open(config_file) as f:
            return json.load(f)
    except Exception:
        return {}

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
        "members_page":  os.environ.get("MEMBERS_PAGE", cfg.get("members_page", "")),
        "api_base":      cfg.get("api_base", ""),
        "currency":      cfg.get("currency", "usd"),
        # Which payment plugin /checkout routes a paid tier through —
        # "manual" (default: admin-approval queue, no third-party account,
        # works in any country/category) or "stripe" (automatic card
        # checkout). See "Adding a new payment provider" in SETUP.md to
        # add another one without touching this fallback logic.
        "payment_provider": cfg.get("payment_provider", "manual"),
        "manual_payment_instructions": cfg.get("manual_payment_instructions", ""),
        "tiers":         cfg.get("tiers", []),
    }

def save_config(updates: dict):
    """Merge `updates` into config.json and write it back. Used by
    /admin/dashboard's save — never overwrites fields the dashboard form
    doesn't send (e.g. nothing today, but keeps this safe as the form
    grows)."""
    cfg = _read_config_file()
    cfg.update(updates)
    with open(BASE_DIR / "config.json", "w") as f:
        json.dump(cfg, f, indent=2)

def get_tier(cfg: dict, tier_name: str) -> dict:
    """The configured tier matching `tier_name`, or None if it isn't one of
    the tiers set up in /admin/dashboard (e.g. an ad-hoc name used for
    manual/demo testing via /issue directly)."""
    return next((t for t in cfg.get("tiers", []) if t.get("name") == tier_name), None)

def resolve_tier_design(cfg: dict, tier_name: str) -> dict:
    """
    A tier can optionally carry its own `design` block (set via the
    per-tier "Edit design" panel in /admin/dashboard) that overrides the
    deployment's global look for just that pass type — e.g. a "DAILY"
    pass can look different from "VIP" without touching the others.
    Anything the tier's design doesn't set falls back to the global
    config.json values. This is the one place that fallback happens, so
    /issue and the dashboard's live preview stay in sync.
    """
    tier_cfg = next((t for t in cfg.get("tiers", []) if t.get("name") == tier_name), None)
    design = (tier_cfg or {}).get("design") or {}
    return {
        "card_title":    design.get("card_title") or cfg["card_title"],
        "accent_color":  design.get("accent_color") or cfg["accent_color"],
        "show_barcode":  design.get("show_barcode", True),
        "logo_data_uri": design.get("logo_data_uri") or None,
    }


def _issue_and_fulfill(name: str, email: str, tier: str, days: int, sections: list,
                        cfg: dict = None, payment_meta: dict = None) -> dict:
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

    # 1 — Issue
    result = issue_credential(
        name        = name,
        email       = email,
        tier        = tier,
        expiry_days = days,
        sections    = sections,
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
    )

    # 4 — Registry (payment_meta, if given, is recorded on the entry —
    # see member_registry.add_credential's "payment" field)
    add_credential({
        **result["entry"],
        "bundle_hash": bundle["bundle_hash"],
        "bundle_path": bundle["bundle_path"],
        "payment":     payment_meta,
    })

    # 5 — Email
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
        result = _issue_and_fulfill(name, email, tier, days, sections, cfg=cfg)
        return ok(result)
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
            result = _issue_and_fulfill(name, email, tier, days, sections, cfg=cfg)
            return ok(result)
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

    # provider == "manual", and the fallback for any unrecognized value —
    # the point of defaulting here rather than refusing is that this path
    # always works, in any country, with zero setup. Nothing is issued
    # yet; see /admin/payment-requests/<id>/approve below.
    from payment_requests import create_request as create_payment_request
    req = create_payment_request(name, email, tier, price, currency)
    instructions = cfg.get("manual_payment_instructions") or (
        "Contact the creator to arrange payment. Your access will be "
        "issued once payment is confirmed."
    )
    return ok({
        "provider":     "manual",
        "pending":      True,
        "request_id":   req["request_id"],
        "instructions": instructions,
    })


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
                "provider":    "manual",
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
        rev_file = DATA_DIR / "revocation_list.json"
        if rev_file.exists():
            with open(rev_file) as f:
                revlist = json.load(f)
        else:
            revlist = {"credential_ids": [], "bundle_hashes": [], "updated_at": ""}

        if credential_id not in revlist["credential_ids"]:
            revlist["credential_ids"].append(credential_id)
        revlist["updated_at"] = datetime.now(timezone.utc).isoformat()

        with open(rev_file, "w") as f:
            json.dump(revlist, f, indent=2)

        return ok({"revoked": success, "credential_id": credential_id})

    except Exception as e:
        return err(f"Revocation failed: {str(e)}", 500)


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
    issuer = f"{cfg['creator_name']} / CrithLabs"
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
    members = sorted(list_all(), key=lambda m: m.get("issued_at", ""), reverse=True)

    rows = ""
    for m in members:
        revoked = bool(m.get("revoked"))
        status_label = "REVOKED" if revoked else "active"
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

        revoke_cell = '—' if revoked else (
            f'<button class="revoke-btn" data-id="{cred_id}" data-name="{name_esc}">Revoke</button>'
        )

        rows += f"""
        <tr>
          <td>{name_esc}</td>
          <td>{email_esc}</td>
          <td>{tier_esc}</td>
          <td>{sections_esc}</td>
          <td>{(m.get('issued_at') or '')[:16].replace('T',' ')}</td>
          <td>{(m.get('expires_at') or '')[:16].replace('T',' ')}</td>
          <td>{status_label}</td>
          <td>{m.get('verified_count', 0)}</td>
          <td title="{esc_html(ip_title)}">{ip_count}</td>
          <td>{revoke_cell}</td>
        </tr>"""

    accent = esc_html(cfg["accent_color"])
    title  = esc_html(cfg["card_title"])

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>Members — Admin</title>
<style>
  body {{ background:#0a0908; color:#e6dfd2; font-family:'Courier New',monospace; padding:32px; }}
  h1 {{ color:{accent}; font-size:16px; letter-spacing:2px; text-transform:uppercase; }}
  table {{ width:100%; border-collapse:collapse; margin-top:20px; font-size:12px; }}
  th, td {{ text-align:left; padding:8px 12px; border-bottom:1px solid #3a1210; }}
  th {{ color:{accent}; text-transform:uppercase; font-size:10px; letter-spacing:1px; }}
  tr:hover {{ background:#1a100e; }}
  .count {{ color:#6b6058; font-size:11px; margin-top:6px; }}
  .revoke-btn {{
    background:transparent; border:1px solid {accent}; color:{accent};
    font-family:'Courier New',monospace; font-size:10px; letter-spacing:1px;
    text-transform:uppercase; padding:5px 10px; cursor:pointer;
  }}
  .revoke-btn:hover {{ background:{accent}; color:#0a0908; }}
  .revoke-btn:disabled {{ opacity:0.5; cursor:default; }}
  .nav {{ margin-bottom:18px; font-size:11px; letter-spacing:1px; }}
  .nav a {{ color:{accent}; text-decoration:none; margin-right:18px; }}
  .nav a:hover {{ text-decoration:underline; }}
</style></head>
<body>
  <div class="nav"><a href="/admin/dashboard">← Dashboard</a><a href="/admin/logout">Log out</a></div>
  <h1>{title} — Members ({len(members)})</h1>
  <div class="count">Newest first. This reads whatever's currently in the live registry.</div>
  <div class="count">"IPs" = distinct addresses seen verifying this credential (hover for the list) — 1-2 is normal for one person, a lot more is worth a look and a manual revoke if it's being shared.</div>
  <table>
    <tr><th>Name</th><th>Email</th><th>Tier</th><th>Sections</th><th>Issued</th><th>Expires</th><th>Status</th><th>Verified ×</th><th>IPs</th><th>Revoke</th></tr>
    {rows}
  </table>
  <script>
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
    error_html = f'<div class="error">{esc_html(error)}</div>' if error else ""
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>Admin Login</title>
<style>
  body {{ background:#0a0908; color:#e6dfd2; font-family:'Courier New',monospace;
          display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; }}
  .box {{ width:100%; max-width:320px; padding:32px; }}
  h1 {{ color:{accent}; font-size:14px; letter-spacing:2px; text-transform:uppercase; margin-bottom:24px; }}
  input {{ width:100%; background:#1a100e; border:1px solid #3a1210; color:#e6dfd2;
           font-family:'Courier New',monospace; font-size:13px; padding:10px 12px; margin-bottom:14px; }}
  button {{ width:100%; background:{accent}; color:#0a0908; border:none; font-family:'Courier New',monospace;
            font-size:12px; letter-spacing:2px; text-transform:uppercase; padding:12px; cursor:pointer; }}
  .error {{ color:#e8232b; font-size:11px; margin-bottom:14px; }}
</style></head>
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

    password = request.form.get("password", "")
    if password != ADMIN_SECRET:
        return _login_page(error="Wrong password.", next_path=next_path)

    session.permanent = True
    session["admin_authed"] = True
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
    return _dashboard_page()

def _encode_upload_as_data_uri(file_storage) -> str:
    """Read a Flask-uploaded image file and return it as a data: URI, the
    same shape card_generator embeds into the card HTML. Returns "" if no
    file was actually chosen (an empty file input still submits a
    FileStorage with an empty filename)."""
    if not file_storage or not file_storage.filename:
        return ""
    import base64
    raw = file_storage.read()
    if not raw:
        return ""
    mimetype = file_storage.mimetype or "image/png"
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mimetype};base64,{b64}"

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

    # Per-tier design overrides. Logos are matched POSITIONALLY against
    # whatever was already saved at that row index — fine as long as tiers
    # aren't reordered in the same save that also changes a logo; if a row
    # was moved, just re-upload its logo. Good enough for a single-admin
    # tool; not worth the complexity of id-based tracking for this.
    old_tiers          = _read_config_file().get("tiers", [])
    design_card_titles = request.form.getlist("tier_design_card_title")
    design_accents     = request.form.getlist("tier_design_accent_color")
    design_barcodes    = request.form.getlist("tier_design_barcode")
    design_logo_clears = request.form.getlist("tier_design_logo_clear")
    design_logo_files  = request.files.getlist("tier_design_logo")

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

        design = {}
        d_title  = (design_card_titles[i] if i < len(design_card_titles) else "").strip()
        d_accent = (design_accents[i] if i < len(design_accents) else "").strip()
        d_bar    = (design_barcodes[i] if i < len(design_barcodes) else "on").strip()
        d_clear  = (design_logo_clears[i] if i < len(design_logo_clears) else "0") == "1"
        new_logo = _encode_upload_as_data_uri(design_logo_files[i]) if i < len(design_logo_files) else ""

        if d_title:
            design["card_title"] = d_title
        if d_accent:
            design["accent_color"] = d_accent
        if d_bar == "off":
            design["show_barcode"] = False

        if new_logo:
            design["logo_data_uri"] = new_logo
        elif not d_clear and i < len(old_tiers):
            old_logo = (old_tiers[i].get("design") or {}).get("logo_data_uri")
            if old_logo:
                design["logo_data_uri"] = old_logo
        # else: cleared, or no previous logo — leave unset (inherits global)

        tiers.append({
            "name":        name.upper(),
            "label":       (tier_labels[i] if i < len(tier_labels) else "").strip(),
            "price":       price,
            "expiry_days": expiry_days,
            "sections":    sections,
            **({"design": design} if design else {}),
        })

    save_config({
        "creator_name":  (request.form.get("creator_name") or "").strip() or "Your Creator Name",
        "card_title":     (request.form.get("card_title") or "").strip() or "YOUR BRAND HERE",
        "card_subtitle":  (request.form.get("card_subtitle") or "").strip() or "Member Card",
        "accent_color":   (request.form.get("accent_color") or "").strip() or "#00e87a",
        "members_page":   (request.form.get("members_page") or "").strip(),
        "api_base":       (request.form.get("api_base") or "").strip(),
        "currency":       (request.form.get("currency") or "usd").strip().lower()[:3] or "usd",
        "payment_provider": (request.form.get("payment_provider") or "manual").strip().lower()
                            if (request.form.get("payment_provider") or "").strip().lower() in ("manual", "stripe")
                            else "manual",
        "manual_payment_instructions": (request.form.get("manual_payment_instructions") or "").strip(),
        "tiers":          tiers,
    })

    return redirect("/admin/dashboard?saved=1")

def _dashboard_page() -> str:
    cfg = load_config()
    accent = esc_html(cfg["accent_color"])
    title  = esc_html(cfg["card_title"])

    try:
        from member_registry import stats
        s = stats()
    except Exception:
        s = {"total": 0, "active": 0, "revoked": 0, "expired": 0}

    if stripe and STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET:
        payment_status_html = '<b style="color:#5fd98a;">✓ Stripe is configured</b> — paid tiers will route through checkout.<br>'
    elif stripe and STRIPE_SECRET_KEY:
        payment_status_html = '<b style="color:#e8232b;">⚠ STRIPE_SECRET_KEY is set but STRIPE_WEBHOOK_SECRET is not</b> — checkout will start, but payments will never actually fulfill.<br>'
    else:
        payment_status_html = '<b style="color:#a8a094;">✗ Stripe is not configured</b> — switch the provider below to "Manual approval" to sell paid tiers without it.<br>'

    provider = (cfg.get("payment_provider") or "manual").strip().lower()
    if provider not in ("manual", "stripe"):
        provider = "manual"

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
              <td>{(r.get('requested_at') or '')[:16].replace('T',' ')}</td>
              <td>
                <button type="button" class="approve-req-btn" data-id="{esc_html(r['request_id'])}">Approve</button>
                <button type="button" class="reject-req-btn" data-id="{esc_html(r['request_id'])}">Reject</button>
              </td>
            </tr>"""
        pending_requests_html = f"""
        <table>
          <tr><th>Name</th><th>Email</th><th>Tier</th><th>Amount</th><th>Requested</th><th></th></tr>
          {req_rows}
        </table>"""
    else:
        pending_requests_html = '<div class="hint">No pending manual payment requests right now.</div>'

    tier_rows = ""
    for t in cfg["tiers"]:
        design = t.get("design") or {}
        logo_uri = design.get("logo_data_uri") or ""
        logo_thumb = f'<img class="logo-thumb" src="{logo_uri}">' if logo_uri else '<span class="no-logo">none — uses global</span>'
        barcode_on = design.get("show_barcode", True)
        tier_rows += f"""
        <tr class="tier-row">
          <td><input name="tier_name" value="{esc_html(t.get('name',''))}"></td>
          <td><input name="tier_label" value="{esc_html(t.get('label',''))}"></td>
          <td><input name="tier_price" type="number" step="0.01" value="{esc_html(str(t.get('price',0)))}"></td>
          <td><input name="tier_expiry_days" type="number" value="{esc_html(str(t.get('expiry_days',31)))}"></td>
          <td><input name="tier_sections" value="{esc_html(', '.join(t.get('sections',[])))}" placeholder="downloads, chat"></td>
          <td><button type="button" class="design-toggle">Design ▾</button></td>
          <td><button type="button" class="remove-tier">×</button></td>
        </tr>
        <tr class="design-row" style="display:none">
          <td colspan="7">
            <div class="design-panel">
              <div class="design-field">
                <label>Card title override</label>
                <input name="tier_design_card_title" value="{esc_html(design.get('card_title',''))}" placeholder="blank = use global &quot;{esc_html(cfg['card_title'])}&quot;">
              </div>
              <div class="design-field">
                <label>Accent color override</label>
                <input name="tier_design_accent_color" value="{esc_html(design.get('accent_color',''))}" placeholder="blank = use global {esc_html(cfg['accent_color'])}">
              </div>
              <div class="design-field">
                <label>Barcode strip</label>
                <select name="tier_design_barcode">
                  <option value="on" {"selected" if barcode_on else ""}>On</option>
                  <option value="off" {"selected" if not barcode_on else ""}>Off</option>
                </select>
              </div>
              <div class="design-field">
                <label>Logo override</label>
                <div class="logo-row">
                  {logo_thumb}
                  <input type="file" name="tier_design_logo" accept="image/*">
                  <button type="button" class="remove-logo">Remove logo</button>
                </div>
                <input type="hidden" name="tier_design_logo_clear" value="0">
              </div>
              <button type="button" class="preview-btn">Preview this pass's card →</button>
              <iframe class="preview-frame" style="display:none"></iframe>
            </div>
          </td>
        </tr>"""

    saved_banner = '<div class="banner">Saved.</div>' if request.args.get("saved") else ""

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>Dashboard — {title}</title>
<style>
  body {{ background:#0a0908; color:#e6dfd2; font-family:'Courier New',monospace; padding:32px; max-width:900px; margin:0 auto; }}
  h1 {{ color:{accent}; font-size:16px; letter-spacing:2px; text-transform:uppercase; margin-bottom:4px; }}
  h2 {{ color:{accent}; font-size:12px; letter-spacing:1.5px; text-transform:uppercase; margin:32px 0 12px; border-bottom:1px solid #3a1210; padding-bottom:8px; }}
  .nav {{ margin-bottom:18px; font-size:11px; letter-spacing:1px; }}
  .nav a {{ color:{accent}; text-decoration:none; margin-right:18px; }}
  .nav a:hover {{ text-decoration:underline; }}
  .hint {{ color:#6b6058; font-size:11px; line-height:1.6; }}
  .stats {{ display:flex; gap:24px; margin:16px 0 8px; font-size:11px; }}
  .stats b {{ color:{accent}; font-size:16px; display:block; }}
  label {{ display:block; font-size:10px; letter-spacing:1px; color:#a8a094; text-transform:uppercase; margin-bottom:4px; margin-top:14px; }}
  input {{ width:100%; background:#1a100e; border:1px solid #3a1210; color:#e6dfd2;
           font-family:'Courier New',monospace; font-size:12px; padding:8px 10px; box-sizing:border-box; }}
  input[type=color] {{ width:60px; padding:2px; height:32px; }}
  select, textarea {{ width:100%; background:#1a100e; border:1px solid #3a1210; color:#e6dfd2;
           font-family:'Courier New',monospace; font-size:12px; padding:8px 10px; box-sizing:border-box; }}
  textarea {{ resize:vertical; }}
  .approve-req-btn, .reject-req-btn {{
    background:transparent; border:1px solid {accent}; color:{accent};
    font-family:'Courier New',monospace; font-size:10px; letter-spacing:1px;
    text-transform:uppercase; padding:5px 10px; cursor:pointer; margin-right:6px;
  }}
  .approve-req-btn:hover {{ background:{accent}; color:#0a0908; }}
  .reject-req-btn {{ border-color:#5a4a42; color:#a8a094; }}
  .reject-req-btn:hover {{ background:#3a1210; color:#e6dfd2; }}
  .approve-req-btn:disabled, .reject-req-btn:disabled {{ opacity:0.5; cursor:default; }}
  table {{ width:100%; border-collapse:collapse; margin-top:8px; }}
  th {{ text-align:left; font-size:9px; letter-spacing:1px; color:#6b6058; text-transform:uppercase; padding:4px 6px; }}
  td {{ padding:4px 6px; }}
  .remove-tier {{ background:transparent; border:1px solid #3a1210; color:#a8a094; cursor:pointer; width:28px; height:28px; }}
  .add-tier, .save-btn {{ background:{accent}; color:#0a0908; border:none; font-family:'Courier New',monospace;
           font-size:11px; letter-spacing:1.5px; text-transform:uppercase; padding:10px 18px; cursor:pointer; margin-top:12px; }}
  .add-tier {{ background:transparent; border:1px solid {accent}; color:{accent}; }}
  .placeholder {{ color:#6b6058; font-size:11px; line-height:1.7; border-left:2px solid #3a1210; padding:10px 14px; }}
  .banner {{ background:#13371f; color:#5fd98a; font-size:11px; padding:10px 14px; margin-bottom:16px; letter-spacing:1px; text-transform:uppercase; }}
  .design-toggle {{ background:transparent; border:1px solid #3a1210; color:#a8a094; font-family:'Courier New',monospace;
           font-size:10px; padding:6px 10px; cursor:pointer; white-space:nowrap; }}
  .design-panel {{ background:#13100f; border:1px solid #3a1210; padding:16px; margin:6px 0; display:flex; flex-wrap:wrap; gap:16px; align-items:flex-start; }}
  .design-field {{ flex:1 1 180px; min-width:160px; }}
  .design-field label {{ margin-top:0; }}
  .design-field select {{ width:100%; background:#1a100e; border:1px solid #3a1210; color:#e6dfd2;
           font-family:'Courier New',monospace; font-size:12px; padding:8px 10px; }}
  .logo-row {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
  .logo-thumb {{ height:32px; max-width:80px; object-fit:contain; background:#000; }}
  .no-logo {{ color:#6b6058; font-size:10px; }}
  .remove-logo {{ background:transparent; border:1px solid #3a1210; color:#a8a094; font-family:'Courier New',monospace;
           font-size:9px; padding:4px 8px; cursor:pointer; }}
  .preview-btn {{ background:transparent; border:1px solid {accent}; color:{accent}; font-family:'Courier New',monospace;
           font-size:10px; letter-spacing:1px; padding:8px 14px; cursor:pointer; flex:1 1 100%; }}
  .preview-frame {{ width:100%; height:480px; border:1px solid #3a1210; margin-top:10px; flex:1 1 100%; background:#050403; }}
  .embed-code {{ background:#13100f; border:1px solid #3a1210; color:#e6dfd2; font-family:'Courier New',monospace;
           font-size:12px; line-height:1.7; padding:12px 14px; margin:8px 0; white-space:pre-wrap; word-break:break-all; }}
  .copy-btn {{ background:{accent}; color:#0a0908; border:none; font-family:'Courier New',monospace;
           font-size:11px; letter-spacing:1.5px; text-transform:uppercase; padding:8px 16px; cursor:pointer; }}
</style></head>
<body>
  <div class="nav"><a href="/admin/members">Members →</a><a href="/admin/logout">Log out</a></div>
  <h1>{title} — Dashboard</h1>
  {saved_banner}

  <div class="stats">
    <div><b>{s['total']}</b>total</div>
    <div><b>{s['active']}</b>active</div>
    <div><b>{s['revoked']}</b>revoked</div>
    <div><b>{s['expired']}</b>expired</div>
  </div>

  <h2>Embed on your website</h2>
  <div class="hint">Paste these two lines into any page of your site, wherever you want the member widget to appear. That's all it takes — the widget finds this server by itself. (The address below is filled in from the page you're on right now, so open this dashboard at your real public address before copying.)</div>
  <pre class="embed-code" id="embed-code"></pre>
  <button type="button" class="copy-btn" id="embed-copy">Copy</button>

  <form method="POST" action="/admin/dashboard" enctype="multipart/form-data">

    <h2>Branding</h2>
    <label>Creator name</label>
    <input name="creator_name" value="{esc_html(cfg['creator_name'])}">
    <label>Card title (the headline brand shown on cards/emails)</label>
    <input name="card_title" value="{esc_html(cfg['card_title'])}">
    <label>Card subtitle</label>
    <input name="card_subtitle" value="{esc_html(cfg['card_subtitle'])}">
    <label>Accent color (used on cards, email, the member widget, and this dashboard)</label>
    <input name="accent_color" type="color" value="{esc_html(cfg['accent_color'])}">
    <label>Members page URL (where cp.js is embedded — overridden at runtime if the MEMBERS_PAGE env var is set)</label>
    <input name="members_page" value="{esc_html(cfg['members_page'])}">
    <label>API base URL (informational — where this API is deployed)</label>
    <input name="api_base" value="{esc_html(cfg['api_base'])}">

    <h2>Tiers &amp; pricing</h2>
    <div class="hint" style="margin-bottom:8px;">Each tier is a pass type. "Design ▾" lets a specific tier (e.g. a Daily Pass) look different from the rest — title, accent color, logo, barcode — without affecting the others. Anything left blank there just uses the branding above.</div>
    <table>
      <tr><th>Name</th><th>Label</th><th>Price</th><th>Expiry (days)</th><th>Sections (comma-separated)</th><th></th><th></th></tr>
      <tbody id="tier-body">{tier_rows}</tbody>
    </table>
    <button type="button" class="add-tier" id="add-tier">+ Add tier</button>

    <h2>Payment</h2>
    <label>Payment provider (how a paid tier actually gets fulfilled)</label>
    <select name="payment_provider">
      <option value="manual" {"selected" if provider == "manual" else ""}>Manual approval — works in any country, no payment account needed</option>
      <option value="stripe" {"selected" if provider == "stripe" else ""}>Stripe — automatic card checkout</option>
    </select>
    <div class="hint" style="margin-top:4px;">"Manual approval" needs nothing set up: a member requests a paid tier, you confirm payment arrived however it actually did for you, and approve it in the queue below — that issues the credential. Switch to Stripe once you want automatic card checkout; Stripe isn't available (or allowed) everywhere, so manual is the default. See "Adding a new payment provider" in SETUP.md to wire in something else entirely (PayPal, a regional or adult-friendly processor, etc.) without touching this dropdown's code.</div>

    <label>Currency (3-letter code, e.g. usd, eur, gbp)</label>
    <input name="currency" value="{esc_html(cfg.get('currency','usd'))}" maxlength="3" style="max-width:100px;">

    <label>Manual payment instructions (shown to a member when they request a paid tier, while "Manual approval" is the active provider)</label>
    <textarea name="manual_payment_instructions" rows="3" placeholder="e.g. Send $9.99 via PayPal to you@example.com or by bank transfer to ..., then message me your email and I'll approve your access within a day.">{esc_html(cfg.get('manual_payment_instructions',''))}</textarea>

    <div class="placeholder" style="margin-top:14px;">
      {payment_status_html}
      Stripe keys are secrets and aren't entered here — they're set as
      environment variables (<code>STRIPE_SECRET_KEY</code>,
      <code>STRIPE_WEBHOOK_SECRET</code>) so they're never stored in
      config.json or rendered into this page. See SETUP.md for how to get
      them and wire up the webhook. A tier priced at 0 always issues
      instantly with no payment step, regardless of which provider is active.
    </div>

    <label style="margin-top:20px;">Pending manual payment requests</label>
    {pending_requests_html}

    <h2></h2>
    <button type="submit" class="save-btn">Save changes</button>
  </form>

  <template id="tier-row-template">
    <tr class="tier-row">
      <td><input name="tier_name" value=""></td>
      <td><input name="tier_label" value=""></td>
      <td><input name="tier_price" type="number" step="0.01" value="0"></td>
      <td><input name="tier_expiry_days" type="number" value="31"></td>
      <td><input name="tier_sections" value="" placeholder="downloads, chat"></td>
      <td><button type="button" class="design-toggle">Design ▾</button></td>
      <td><button type="button" class="remove-tier">×</button></td>
    </tr>
    <tr class="design-row" style="display:none">
      <td colspan="7">
        <div class="design-panel">
          <div class="design-field">
            <label>Card title override</label>
            <input name="tier_design_card_title" value="" placeholder="blank = use global">
          </div>
          <div class="design-field">
            <label>Accent color override</label>
            <input name="tier_design_accent_color" value="" placeholder="blank = use global">
          </div>
          <div class="design-field">
            <label>Barcode strip</label>
            <select name="tier_design_barcode">
              <option value="on" selected>On</option>
              <option value="off">Off</option>
            </select>
          </div>
          <div class="design-field">
            <label>Logo override</label>
            <div class="logo-row">
              <span class="no-logo">none — uses global</span>
              <input type="file" name="tier_design_logo" accept="image/*">
              <button type="button" class="remove-logo">Remove logo</button>
            </div>
            <input type="hidden" name="tier_design_logo_clear" value="0">
          </div>
          <button type="button" class="preview-btn">Preview this pass's card →</button>
          <iframe class="preview-frame" style="display:none"></iframe>
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
      const code = '<div id="crith-access"></div>\\n<' + 'script src="' +
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
      if (e.target.classList.contains('remove-logo')) {{
        const panel = e.target.closest('.design-panel');
        panel.querySelector('input[name="tier_design_logo_clear"]').value = '1';
        const thumb = panel.querySelector('.logo-thumb');
        if (thumb) {{
          const span = document.createElement('span');
          span.className = 'no-logo';
          span.textContent = 'removed — will use global on save';
          thumb.replaceWith(span);
        }}
        return;
      }}
      if (e.target.classList.contains('preview-btn')) {{
        const panel = e.target.closest('.design-panel');
        const designRow = e.target.closest('tr');
        const mainRow = designRow.previousElementSibling;
        const frame = panel.querySelector('.preview-frame');

        const fd = new FormData();
        fd.append('name', mainRow.querySelector('input[name="tier_name"]').value || 'PREVIEW');
        fd.append('card_title', panel.querySelector('input[name="tier_design_card_title"]').value || '');
        fd.append('accent_color', panel.querySelector('input[name="tier_design_accent_color"]').value || '');
        fd.append('barcode', panel.querySelector('select[name="tier_design_barcode"]').value);
        const fileInput = panel.querySelector('input[name="tier_design_logo"]');
        if (fileInput.files[0]) fd.append('logo', fileInput.files[0]);

        e.target.textContent = 'Loading preview...';
        fetch('/admin/dashboard/preview-card', {{ method: 'POST', body: fd }})
          .then(r => r.text())
          .then(html => {{
            frame.srcdoc = html;
            frame.style.display = '';
            e.target.textContent = "Preview this pass's card →";
          }})
          .catch(err => {{
            alert('Preview failed: ' + err.message);
            e.target.textContent = "Preview this pass's card →";
          }});
        return;
      }}
    }});

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
    document.querySelectorAll('.approve-req-btn').forEach(btn => {{
      btn.addEventListener('click', () => decidePaymentRequest(btn.dataset.id, 'approve', btn));
    }});
    document.querySelectorAll('.reject-req-btn').forEach(btn => {{
      btn.addEventListener('click', () => decidePaymentRequest(btn.dataset.id, 'reject', btn));
    }});
  </script>
</body></html>"""


# ── POST /admin/dashboard/preview-card ──
# Renders a real card (via card_generator, same code path /issue uses) from
# whatever is currently typed into a tier's design panel — nothing here is
# saved. Dummy credential data only; never touches the registry.
@app.route("/admin/dashboard/preview-card", methods=["POST"])
def admin_dashboard_preview_card():
    if not is_admin_session():
        return err("Unauthorized", 401)

    cfg = load_config()
    tier_name    = (request.form.get("name") or "PREVIEW").strip().upper()
    title_override  = (request.form.get("card_title") or "").strip()
    accent_override  = (request.form.get("accent_color") or "").strip()
    show_barcode     = (request.form.get("barcode") or "on") != "off"
    logo_data_uri    = _encode_upload_as_data_uri(request.files.get("logo")) or None

    from datetime import timedelta as _td
    now = datetime.now(timezone.utc)

    try:
        from card_generator import generate_card
        card_path_str = generate_card(
            credential_id = "preview0000demo",
            holder_name   = "Preview Member",
            tier          = tier_name,
            issued_at     = now.isoformat(),
            expires_at    = (now + _td(days=31)).isoformat(),
            bundle_hash   = "0" * 64,
            signature_hex = "0" * 128,
            sections      = [],
            card_title    = title_override or cfg["card_title"],
            card_subtitle = f"{tier_name} Card",
            access_url    = cfg["members_page"] or "https://example.com/members.html",
            creator_name  = cfg["creator_name"],
            accent_color  = accent_override or cfg["accent_color"],
            show_barcode  = show_barcode,
            logo_data_uri = logo_data_uri,
        )
        # generate_card() writes the card to disk (cards/) and returns that
        # path — a preview has no real credential behind it, so read it
        # back and delete the throwaway file immediately.
        card_file = Path(card_path_str)
        rendered = card_file.read_text(encoding="utf-8")
        card_file.unlink(missing_ok=True)
        return rendered
    except Exception as e:
        return err(f"Preview failed: {str(e)}", 500)


@app.route("/config", methods=["GET"])
def get_config():
    config_file = BASE_DIR / "config.json"
    if not config_file.exists():
        return err("config.json not found", 404)
    with open(config_file) as f:
        return jsonify(json.load(f))

@app.route("/content", methods=["GET"])
def get_content():
    content_file = BASE_DIR / "content.json"
    if not content_file.exists():
        return jsonify({})
    with open(content_file) as f:
        return jsonify(json.load(f))

@app.route("/cp.js", methods=["GET"])
def serve_widget():
    from flask import send_file
    return send_file(BASE_DIR / "cp.js", mimetype="application/javascript")

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
