"""
Credential Protocol — Manual Payment Requests
A payment-provider-agnostic queue backing the "manual" payment provider
(see credential_api.py's /checkout and /admin/payment-requests routes).

The idea: a member requests a paid tier, the creator confirms payment
arrived however it actually did for them — bank transfer, PayPal, cash,
crypto, a local processor, whatever's legal and available in their
country — and approves the request from /admin/dashboard. Approval calls
the exact same _issue_and_fulfill() pipeline a Stripe webhook would, so a
manually-approved credential is otherwise indistinguishable from an
automated one. No payment account of any kind is required to use this —
that's the point. It exists specifically so creators outside the handful
of countries/categories Stripe (or any one processor) will serve aren't
locked out of selling access at all while they set up something more
automated.
"""

import json
import os
import secrets
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(__file__).resolve().parent

# Matches credential_issuer.py / member_registry.py's DATA_DIR convention —
# the persistent Volume mount in production, BASE_DIR as local-dev fallback.
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
REQUESTS_FILE = DATA_DIR / "payment_requests.json"


def _load() -> list:
    if not REQUESTS_FILE.exists():
        return []
    try:
        with open(REQUESTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(requests: list):
    with open(REQUESTS_FILE, "w", encoding="utf-8") as f:
        json.dump(requests, f, indent=2, default=str)


def create_request(name: str, email: str, tier: str, price: float, currency: str) -> dict:
    """Record a new pending request. Returns the stored record, including
    its request_id — handed back to the member so they (or the creator)
    can reference it."""
    req = {
        "request_id":   secrets.token_hex(8),
        "holder_name":  name,
        "holder_email": email,
        "tier":         tier,
        "price":        price,
        "currency":     currency,
        "status":       "pending",  # pending | approved | rejected
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "decided_at":   None,
    }
    reqs = _load()
    reqs.append(req)
    _save(reqs)
    return req


def get_request(request_id: str) -> dict | None:
    for r in _load():
        if r.get("request_id") == request_id:
            return r
    return None


def list_pending() -> list:
    return [r for r in _load() if r.get("status") == "pending"]


def list_all() -> list:
    return _load()


def mark_decided(request_id: str, status: str) -> bool:
    """status: 'approved' or 'rejected'. Only moves a request out of
    'pending' — calling this twice on the same request is a no-op the
    second time (the caller should check the return value and refuse,
    same idempotency stance as the Stripe webhook)."""
    reqs = _load()
    for r in reqs:
        if r.get("request_id") == request_id and r.get("status") == "pending":
            r["status"] = status
            r["decided_at"] = datetime.now(timezone.utc).isoformat()
            _save(reqs)
            return True
    return False
