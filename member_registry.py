"""
Credential Protocol — Member Registry
Tracks all issued credentials locally in a JSON file.
Simple, no database needed.
"""

import json
import os
import tempfile
import threading
from pathlib import Path
from datetime import datetime, timedelta, timezone

BASE_DIR = Path(__file__).resolve().parent

# See credential_issuer.py — DATA_DIR is the persistent Volume mount in
# production, BASE_DIR as a local-dev fallback. This file is exactly the
# runtime state that gets wiped on redeploy without a Volume.
DATA_DIR      = Path(os.environ.get("DATA_DIR", str(BASE_DIR)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
REGISTRY_FILE = DATA_DIR / "member_registry.json"


# Every change below is "read the file, change it, write it back". The lock
# makes those steps one unit inside this process, so e.g. the reminder
# thread marking a member can't overwrite a signup that landed in between.
# The app runs as a single worker (railway.json), so one process-wide lock
# is enough.
_lock = threading.RLock()


def _load() -> list:
    if not REGISTRY_FILE.exists():
        return []
    with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(registry: list):
    # Written to a temp file first and swapped in, so a crash or a full disk
    # in the middle of a write can never leave a half-written registry.
    fd, tmp = tempfile.mkstemp(prefix=".registry-", suffix=".tmp", dir=str(REGISTRY_FILE.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, REGISTRY_FILE)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def add_credential(entry: dict):
    """Add a newly issued credential to the registry."""
    with _lock:
        _add_credential_locked(entry)


def _add_credential_locked(entry: dict):
    registry = _load()
    registry.append({
        "credential_id":    entry["credential_id"],
        "holder_name":      entry["holder_name"],
        "holder_email":     entry["holder_email"],
        "tier":             entry["tier"],
        "sections":         entry.get("sections", []),
        "issued_at":        entry["issued_at"],
        "expires_at":       entry["expires_at"],
        "bundle_hash":      entry.get("bundle_hash", ""),
        "bundle_path":      entry.get("bundle_path", ""),
        "fingerprint_hash": entry.get("fingerprint_hash", "NOT_ANCHORED"),
        # Set only for credentials issued through a paid checkout (see
        # credential_api.py's Stripe webhook) — {stripe_session_id,
        # amount_paid, currency}. None for free-tier/manual issuance.
        "payment":          entry.get("payment"),
        # "ticket" (with the event's details) for an event ticket; absent for
        # an ordinary access pass. `used_at` is set by mark_used().
        **({"kind": entry["kind"], "event": entry.get("event") or {}} if entry.get("kind") == "ticket" else {}),
        # "collectible": the numbered drop card ({name, note, edition, of}).
        **({"kind": "collectible", "drop": entry.get("drop") or {}} if entry.get("kind") == "collectible" else {}),
        "revoked":          False,
        "revoked_at":       None,
        "verified_count":   0,
        "last_verified_at": None,
        # Bounded log of {ip, at} per successful verification — a lightweight
        # signal for spotting a shared/copied credential (one member = 1-2
        # distinct IPs over time; many distinct IPs is worth a manual look),
        # not a full audit trail. See mark_verified().
        "verification_log": [],
        "registered_at":    datetime.now(timezone.utc).isoformat(),
    })
    _save(registry)
    print(f"✔ Registry: added {entry['credential_id']} for {entry['holder_email']}")


def get_by_id(credential_id: str) -> dict | None:
    for entry in _load():
        if entry["credential_id"] == credential_id:
            return entry
    return None


def get_by_hash(bundle_hash: str) -> dict | None:
    for entry in _load():
        if entry.get("bundle_hash", "").startswith(bundle_hash[:16]):
            return entry
    return None


def get_by_email(email: str) -> list:
    return [e for e in _load() if e["holder_email"].lower() == email.lower()]


def list_all() -> list:
    return _load()


def mark_verified(credential_id: str, ip: str = None):
    """
    Record a successful verification, and — when an IP is given — append it
    to a bounded log used purely as a sharing signal (see add_credential).
    Not logged on failed attempts; only successful, already-valid checks.
    """
    with _lock:
        _mark_verified_locked(credential_id, ip)


def _mark_verified_locked(credential_id, ip):
    registry = _load()
    for entry in registry:
        if entry["credential_id"] == credential_id:
            entry["verified_count"]   = entry.get("verified_count", 0) + 1
            entry["last_verified_at"] = datetime.now(timezone.utc).isoformat()
            if ip:
                log = entry.setdefault("verification_log", [])
                log.append({"ip": ip, "at": entry["last_verified_at"]})
                # Keep it bounded — this is a lightweight signal, not a
                # growing-forever audit log.
                if len(log) > 30:
                    entry["verification_log"] = log[-30:]
            break
    _save(registry)


def revoke(credential_id: str) -> bool:
    """Revoke a credential by ID."""
    with _lock:
        return _revoke_locked(credential_id)


def _revoke_locked(credential_id: str) -> bool:
    registry = _load()
    for entry in registry:
        if entry["credential_id"] == credential_id:
            entry["revoked"]    = True
            entry["revoked_at"] = datetime.now(timezone.utc).isoformat()
            _save(registry)
            print(f"✔ Revoked: {credential_id}")
            return True
    return False


def mark_used(credential_id: str, now=None) -> str | None:
    """Mark an event ticket as used (let in at the door). Returns the time it
    was used, or None if there is no such credential. A ticket already used
    keeps its first time."""
    with _lock:
        registry = _load()
        for entry in registry:
            if entry["credential_id"] == credential_id:
                if not entry.get("used_at"):
                    entry["used_at"] = (now or datetime.now(timezone.utc)).isoformat()
                    _save(registry)
                return entry["used_at"]
    return None


def unmark_used(credential_id: str) -> bool:
    """Undo a mistaken check-in."""
    with _lock:
        registry = _load()
        for entry in registry:
            if entry["credential_id"] == credential_id:
                entry.pop("used_at", None)
                _save(registry)
                return True
    return False


MAX_EXTEND_DAYS = 3650     # ten years; a typo like 36500 is refused, not honoured
RETRY_REMINDER_HOURS = 6   # after a failed reminder, wait this long before trying again


def _parse(ts):
    try:
        d = datetime.fromisoformat(str(ts))
    except (ValueError, TypeError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def clean_extend_days(value):
    """A whole number of days from 1 to MAX_EXTEND_DAYS, or None."""
    try:
        n = int(str(value).strip())
    except (ValueError, TypeError):
        return None
    return n if 1 <= n <= MAX_EXTEND_DAYS else None


def extend(credential_id: str, days, now=None):
    """
    Give a member more time, in place: same credential, same access link,
    same card — only the expiry moves. A card that is still running gets the
    days added to its current end date (so renewing early loses nothing); a
    card that already ran out restarts from now. A revoked card can't be
    extended (that's an explicit decision to cut the person off).

    Returns the updated entry, or None when there is no such credential.
    Raises ValueError("revoked") / ValueError("days") for the refused cases.
    """
    n = clean_extend_days(days)
    if n is None:
        raise ValueError("days")
    now = now or datetime.now(timezone.utc)
    with _lock:
        registry = _load()
        for entry in registry:
            if entry["credential_id"] != credential_id:
                continue
            if entry.get("revoked"):
                raise ValueError("revoked")
            old_end = _parse(entry.get("expires_at"))
            start = old_end if (old_end and old_end > now) else now
            new_end = start + timedelta(days=n)
            log = entry.setdefault("extensions", [])
            log.append({"at": now.isoformat(), "days": n,
                        "from": entry.get("expires_at"), "to": new_end.isoformat()})
            if len(log) > 20:
                entry["extensions"] = log[-20:]
            entry["expires_at"] = new_end.isoformat()
            entry["extended_at"] = now.isoformat()
            # a new end date means a new reminder is owed when it gets close
            entry.pop("reminded_for", None)
            entry.pop("reminder_attempt_at", None)
            _save(registry)
            print(f"✔ Extended {credential_id} by {n} days → {entry['expires_at']}")
            return entry
    return None


def delete(credential_id: str):
    """Remove a member's entry for good. Returns the removed entry, or None
    if there was no such credential. (Files and the revocation list are
    handled by the caller — see credential_api.admin_members_delete.)"""
    with _lock:
        registry = _load()
        for i, entry in enumerate(registry):
            if entry["credential_id"] == credential_id:
                removed = registry.pop(i)
                _save(registry)
                print(f"✔ Deleted {credential_id}")
                return removed
    return None


def claim_reminder(credential_id: str, expires_at: str, now=None) -> bool:
    """
    Ask for the right to send this member's expiry reminder. True means "go
    ahead": no reminder has gone out for this expiry date yet, the expiry
    date is still the one the caller looked at (it wasn't extended in the
    meantime) and no attempt was made in the last few hours. The attempt is
    recorded straight away, so a second caller (or a retry loop) can't send
    the same email twice. Follow with mark_reminded() once it really went out.
    """
    now = now or datetime.now(timezone.utc)
    with _lock:
        registry = _load()
        for entry in registry:
            if entry["credential_id"] != credential_id:
                continue
            if entry.get("revoked") or entry.get("expires_at") != expires_at:
                return False
            if entry.get("reminded_for") == expires_at:
                return False
            last = _parse(entry.get("reminder_attempt_at"))
            if last and now - last < timedelta(hours=RETRY_REMINDER_HOURS):
                return False
            entry["reminder_attempt_at"] = now.isoformat()
            _save(registry)
            return True
    return False


def mark_reminded(credential_id: str, expires_at: str, now=None) -> bool:
    """Record that the reminder for this expiry date was sent."""
    now = now or datetime.now(timezone.utc)
    with _lock:
        registry = _load()
        for entry in registry:
            if entry["credential_id"] == credential_id and entry.get("expires_at") == expires_at:
                entry["reminded_for"] = expires_at
                entry["reminded_at"] = now.isoformat()
                _save(registry)
                return True
    return False


def is_revoked(credential_id: str) -> bool:
    entry = get_by_id(credential_id)
    return entry["revoked"] if entry else False


def is_expired(credential_id: str) -> bool:
    entry = get_by_id(credential_id)
    if not entry:
        return True
    return datetime.fromisoformat(entry["expires_at"]) < datetime.now(timezone.utc)


def stats() -> dict:
    registry = _load()
    now = datetime.now(timezone.utc)
    active   = [e for e in registry if not e["revoked"] and
                datetime.fromisoformat(e["expires_at"]) > now]
    revoked  = [e for e in registry if e["revoked"]]
    expired  = [e for e in registry if not e["revoked"] and
                datetime.fromisoformat(e["expires_at"]) <= now]
    return {
        "total":   len(registry),
        "active":  len(active),
        "revoked": len(revoked),
        "expired": len(expired),
    }


# ── Quick test ──
if __name__ == "__main__":
    # Add a test entry
    add_credential({
        "credential_id": "test1234abcd5678",
        "holder_name":   "Test Member",
        "holder_email":  "test@example.com",
        "tier":          "DEMO",
        "sections":      ["downloads", "bts", "chat"],
        "issued_at":     datetime.now(timezone.utc).isoformat(),
        "expires_at":    "2026-12-31T00:00:00+00:00",
        "bundle_hash":   "abc123def456",
        "fingerprint_hash": "NOT_ANCHORED",
    })

    print("\nRegistry stats:", stats())
    print("By ID:", get_by_id("test1234abcd5678")["holder_name"])
    print("Is revoked:", is_revoked("test1234abcd5678"))
    print("Is expired:", is_expired("test1234abcd5678"))

    mark_verified("test1234abcd5678")
    print("Verified count:", get_by_id("test1234abcd5678")["verified_count"])
