"""
Credential Protocol — Verifier
Verifies a presented credential bundle.
Checks: ECDSA signature, expiry, revocation.
"""

import json
import os
import hashlib
import zipfile
from pathlib import Path
from datetime import datetime, timezone
from ecdsa import VerifyingKey, BadSignatureError
from ecdsa.util import sigdecode_der

BASE_DIR        = Path(__file__).resolve().parent

# See credential_issuer.py — DATA_DIR is the persistent Volume mount in
# production, BASE_DIR as a local-dev fallback. Must match the DATA_DIR
# credential_api.py's /revoke route writes revocation_list.json to, and
# the KEYS_DIR credential_issuer.py generates/reads the signing key from —
# this file only ever reads that key, never generates one, so it has to
# agree on exactly where credential_issuer.py put it.
DATA_DIR        = Path(os.environ.get("DATA_DIR", str(BASE_DIR)))
KEYS_DIR        = DATA_DIR / "keys"
PUBLIC_KEY_PATH = KEYS_DIR / "credential_public.pem"
REVOCATION_FILE = DATA_DIR / "revocation_list.json"


def load_public_key():
    with open(PUBLIC_KEY_PATH, "rb") as f:
        return VerifyingKey.from_pem(f.read())


def hash_file(filepath) -> str:
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


def is_on_revocation_list(credential_id: str, bundle_hash: str = None) -> bool:
    if not REVOCATION_FILE.exists():
        return False
    with open(REVOCATION_FILE, "r") as f:
        revoked = json.load(f)
    ids    = revoked.get("credential_ids", [])
    hashes = revoked.get("bundle_hashes", [])
    if credential_id in ids:
        return True
    if bundle_hash and bundle_hash in hashes:
        return True
    return False


def verify_credential(credential_id: str = None,
                      bundle_hash: str = None,
                      bundle_path: str = None,
                      ip: str = None) -> dict:
    """
    Verify a credential by ID + hash (fast, no file needed)
    or by bundle path (full cryptographic check).

    `ip` (optional) is the requester's address, logged only on a successful
    check — a lightweight signal for spotting a shared credential later,
    surfaced in /admin/members. Never affects the valid/invalid verdict.

    Returns dict with: valid, holder_name, holder_email, tier,
    sections, issued_at, expires_at, credential_id, error
    """

    # ── Fast path: ID + hash lookup from registry ──
    if credential_id and not bundle_path:
        from member_registry import get_by_id, is_revoked, is_expired, mark_verified

        entry = get_by_id(credential_id)

        if not entry:
            return {"valid": False, "error": "Credential not found."}

        if entry["revoked"]:
            return {"valid": False, "error": "Credential has been revoked."}

        now    = datetime.now(timezone.utc)
        expiry = datetime.fromisoformat(entry["expires_at"])
        is_ticket = entry.get("kind") == "ticket"
        if expiry < now:
            return {"valid": False, "error": "This ticket has expired. The event is over." if is_ticket
                    else "Credential has expired."}

        # An event ticket that was already scanned in at the door
        if entry.get("used_at"):
            return {"valid": False, "used_at": entry["used_at"], "kind": "ticket",
                    "error": "This ticket has already been used."}

        # Verify bundle hash matches if provided
        if bundle_hash and entry.get("bundle_hash"):
            if not entry["bundle_hash"].startswith(bundle_hash[:16]):
                return {"valid": False, "error": "Bundle hash mismatch."}

        # Check revocation list
        if is_on_revocation_list(credential_id, bundle_hash):
            return {"valid": False, "error": "Credential has been revoked."}

        mark_verified(credential_id, ip=ip)

        days_left = (expiry - now).days

        return {
            "valid":         True,
            "credential_id": entry["credential_id"],
            "holder_name":   entry["holder_name"],
            "holder_email":  entry["holder_email"],
            "tier":          entry["tier"],
            "sections":      entry.get("sections", []),
            "issued_at":     entry["issued_at"],
            "expires_at":    entry["expires_at"],
            "days_left":     days_left,
            "fingerprint_hash": entry.get("fingerprint_hash", "NOT_ANCHORED"),
            **({"kind": "ticket", "event": entry.get("event") or {}} if is_ticket else {}),
            **({"kind": "collectible", "drop": entry.get("drop") or {}} if entry.get("kind") == "collectible" else {}),
        }

    # ── Full path: verify from bundle ZIP ──
    if bundle_path:
        return _verify_from_bundle(bundle_path, ip=ip)

    return {"valid": False, "error": "No credential_id or bundle_path provided."}


def _verify_from_bundle(bundle_path: str, ip: str = None) -> dict:
    """Full cryptographic verification from a bundle ZIP file."""
    try:
        path = Path(bundle_path)
        if not path.exists():
            return {"valid": False, "error": "Bundle file not found."}

        with zipfile.ZipFile(path, "r") as z:
            names = z.namelist()

            # Check required files
            required = ["manifest.json", "manifest.sig", "credential_entry.json"]
            for req in required:
                if req not in names:
                    return {"valid": False, "error": f"Missing {req} in bundle."}

            manifest  = json.loads(z.read("manifest.json"))
            sig_bytes = z.read("manifest.sig")
            entry     = json.loads(z.read("credential_entry.json"))

        # Check bundle type
        if manifest.get("bundle_type") != "credential":
            return {"valid": False, "error": "Not a credential bundle."}

        # Verify ECDSA signature
        try:
            vk = load_public_key()
            manifest_check = {k: v for k, v in manifest.items()}
            manifest_bytes = json.dumps(
                manifest_check, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            vk.verify(sig_bytes, manifest_bytes, sigdecode=sigdecode_der)
        except BadSignatureError:
            return {"valid": False, "error": "Signature invalid — bundle may be tampered with."}
        except Exception as e:
            return {"valid": False, "error": f"Signature check failed: {e}"}

        # Check expiry
        now    = datetime.now(timezone.utc)
        expiry = datetime.fromisoformat(manifest["expires_at"])
        if expiry < now:
            return {"valid": False, "error": "Credential has expired."}

        # Check revocation
        cred_id = manifest.get("credential_id", "")
        if is_on_revocation_list(cred_id):
            return {"valid": False, "error": "Credential has been revoked."}

        # An event ticket already scanned in at the door
        try:
            from member_registry import get_by_id
            reg = get_by_id(cred_id)
            if reg and reg.get("used_at"):
                return {"valid": False, "used_at": reg["used_at"], "kind": "ticket",
                        "error": "This ticket has already been used."}
        except Exception:
            pass

        # Update registry if available
        try:
            from member_registry import mark_verified
            mark_verified(cred_id, ip=ip)
        except Exception:
            pass

        days_left = (expiry - now).days

        return {
            "valid":         True,
            "credential_id": cred_id,
            "holder_name":   manifest.get("holder_name"),
            "holder_email":  manifest.get("holder_email"),
            "tier":          manifest.get("tier"),
            "sections":      manifest.get("sections", []),
            "issued_at":     manifest.get("issued_at"),
            "expires_at":    manifest.get("expires_at"),
            "days_left":     days_left,
            "fingerprint_hash": manifest.get("fingerprint_hash", "NOT_ANCHORED"),
            **({"kind": "ticket", "event": (manifest.get("metadata") or {}).get("event") or {}}
               if (manifest.get("metadata") or {}).get("kind") == "ticket" else {}),
            **({"kind": "collectible", "drop": (manifest.get("metadata") or {}).get("drop") or {}}
               if (manifest.get("metadata") or {}).get("kind") == "collectible" else {}),
        }

    except Exception as e:
        return {"valid": False, "error": f"Verification error: {e}"}


# ── Quick test ──
if __name__ == "__main__":
    # Test fast path using registry
    result = verify_credential(credential_id="test1234abcd5678")
    print("Fast path result:", result)

    # Test bundle path if bundles exist
    bundles = list(Path("bundles").glob("*.zip")) if Path("bundles").exists() else []
    if bundles:
        result = verify_credential(bundle_path=str(bundles[0]))
        print("Bundle path result:", result)
