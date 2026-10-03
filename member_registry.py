"""
Credential Protocol — Member Registry
Tracks all issued credentials locally in a JSON file.
Simple, no database needed.
"""

import json
import os
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(__file__).resolve().parent

# See credential_issuer.py — DATA_DIR is the persistent Volume mount in
# production, BASE_DIR as a local-dev fallback. This file is exactly the
# runtime state that gets wiped on redeploy without a Volume.
DATA_DIR      = Path(os.environ.get("DATA_DIR", str(BASE_DIR)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
REGISTRY_FILE = DATA_DIR / "member_registry.json"


def _load() -> list:
    if not REGISTRY_FILE.exists():
        return []
    with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(registry: list):
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, default=str)


def add_credential(entry: dict):
    """Add a newly issued credential to the registry."""
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
    registry = _load()
    for entry in registry:
        if entry["credential_id"] == credential_id:
            entry["revoked"]    = True
            entry["revoked_at"] = datetime.now(timezone.utc).isoformat()
            _save(registry)
            print(f"✔ Revoked: {credential_id}")
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
