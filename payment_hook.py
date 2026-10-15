"""
Credential Protocol — "payment received" hook.

For a payment service you use with the Custom payment link (or by hand): when that service (or a small
automation such as Zapier, Make or n8n) tells this site "request ABC was paid", the card is issued with
no one pressing Approve.

It is only accepted when the message is SIGNED with a secret that only you and the service know:

    X-Signature: sha256=<HMAC-SHA256 of the exact request body, using the secret, as hex>

and the message says what was paid, so a payment that is too small, or in another currency, is refused:

    {"reference": "<the payment request's reference>", "amount": 9.99, "currency": "eur", "timestamp": <unix seconds>}

A message older (or newer) than 5 minutes is refused, so a copy of an old message can't be replayed later.
The secret is kept in DATA_DIR/payment_hook.json (or set as the PAYMENT_HOOK_SECRET variable instead).
Nothing here approves anything by itself: credential_api.py does that after these checks pass.
"""

import hashlib
import hmac
import json
import os
import secrets as _secrets
import tempfile
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR)))
FILE = DATA_DIR / "payment_hook.json"
MAX_AGE_SECONDS = 300
MAX_BODY = 4096

_lock = threading.RLock()


def secret() -> str:
    """The secret in use ("" when none has been made yet). The PAYMENT_HOOK_SECRET variable wins over the file."""
    env = os.environ.get("PAYMENT_HOOK_SECRET", "").strip()
    if len(env) >= 16:
        return env
    with _lock:
        try:
            d = json.loads(FILE.read_text(encoding="utf-8"))
            s = str(d.get("secret") or "") if isinstance(d, dict) else ""
        except (OSError, ValueError):
            s = ""
    return s if len(s) >= 16 else ""


def from_env() -> bool:
    return len(os.environ.get("PAYMENT_HOOK_SECRET", "").strip()) >= 16


def make_secret() -> str:
    """Make (and keep) a new secret. The old one stops working at once."""
    s = _secrets.token_hex(24)
    with _lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".hook-", suffix=".tmp", dir=str(DATA_DIR))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"secret": s}, f)
            os.replace(tmp, FILE)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    return s


def sign(body: bytes, key: str) -> str:
    return hmac.new(key.encode("utf-8"), body, hashlib.sha256).hexdigest()


def signature_ok(body: bytes, header: str, key: str) -> bool:
    """True when `header` ("sha256=<hex>") is the right signature of the exact `body`."""
    if not key or not isinstance(body, (bytes, bytearray)) or len(body) > MAX_BODY:
        return False
    h = str(header or "").strip()
    if h.lower().startswith("sha256="):
        h = h[7:]
    return hmac.compare_digest(h.lower().encode(), sign(bytes(body), key).encode())


def parse(body: bytes, now_ts: float):
    """The message as (reference, amount, currency) or (None, reason) when it is malformed or not fresh."""
    try:
        d = json.loads(body.decode("utf-8"))
    except Exception:
        return None, "The message is not JSON."
    if not isinstance(d, dict):
        return None, "The message is not a JSON object."
    try:
        ts = float(d.get("timestamp"))
    except (TypeError, ValueError):
        return None, "The message has no timestamp."
    if abs(now_ts - ts) > MAX_AGE_SECONDS:
        return None, "The message is too old (or the clock is wrong)."
    ref = str(d.get("reference") or "").strip()
    cur = str(d.get("currency") or "").strip().lower()
    try:
        amount = float(d.get("amount"))
    except (TypeError, ValueError):
        return None, "The message has no amount."
    if not ref or len(ref) > 64 or not cur or amount != amount or amount <= 0:
        return None, "The message needs a reference, an amount above 0 and a currency."
    return (ref, amount, cur), ""
