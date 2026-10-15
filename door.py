"""
Credential Protocol — the door link.

A private web address the creator can give to door staff. It opens a check-in page that can ONLY scan
tickets and vouchers (and take back a mistake made in the last few minutes): no member list, no settings,
no way into the admin area. It works for a chosen number of hours and then stops by itself, and the creator
can switch it off (or make a new one) at any time.

Only one link exists at a time. Making a new one cancels the old one. Stored in DATA_DIR/door.json.
"""

import hmac
import json
import os
import secrets
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR)))
FILE = DATA_DIR / "door.json"

HOURS = (6, 12, 24, 72, 168)       # what the creator can choose
DEFAULT_HOURS = 24
UNDO_WINDOW_MINUTES = 10           # staff can take back a scan only this soon after it

_lock = threading.RLock()


def _now():
    return datetime.now(timezone.utc)


def _read() -> dict:
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(d: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".door-", suffix=".tmp", dir=str(DATA_DIR))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, FILE)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def clean_hours(v) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return DEFAULT_HOURS
    return n if n in HOURS else DEFAULT_HOURS


def current(now=None):
    """The working link as {"token", "expires_at", "created_at"}, or None (none made, switched off, or run out)."""
    with _lock:
        d = _read()
    try:
        exp = datetime.fromisoformat(str(d.get("expires_at")))
    except ValueError:
        return None
    if not d.get("token") or exp <= (now or _now()):
        return None
    return {"token": d["token"], "expires_at": d["expires_at"], "created_at": d.get("created_at", "")}


def make(hours=DEFAULT_HOURS, now=None) -> dict:
    now = now or _now()
    d = {"token": secrets.token_hex(16), "created_at": now.isoformat(),
         "expires_at": (now + timedelta(hours=clean_hours(hours))).isoformat()}
    with _lock:
        _write(d)
    return d


def off():
    with _lock:
        _write({})


def valid(token, now=None) -> bool:
    cur = current(now)
    return bool(cur) and isinstance(token, str) and len(token) == len(cur["token"]) and hmac.compare_digest(token, cur["token"])


def can_undo(entry: dict, now=None) -> bool:
    """True when this ticket or voucher was last used only a few minutes ago."""
    times = []
    for t in [entry.get("used_at")] + list((entry.get("use_log") or [])[-1:]):
        try:
            times.append(datetime.fromisoformat(str(t)))
        except ValueError:
            pass
    if not times:
        return False
    return (now or _now()) - max(times) <= timedelta(minutes=UNDO_WINDOW_MINUTES)
