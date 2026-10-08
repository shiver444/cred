"""
Credential Protocol — Issuer
Generates and signs credential manifests.
"""

import json
import hashlib
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from ecdsa import SigningKey, SECP256k1
from ecdsa.util import sigencode_der

# ── Paths ──
BASE_DIR = Path(__file__).resolve().parent

# DATA_DIR points at a persistent Railway Volume in production (set via the
# DATA_DIR env var) so credentials issued at runtime survive redeploys.
# Falls back to BASE_DIR for local dev, where nothing gets wiped anyway.
DATA_DIR        = Path(os.environ.get("DATA_DIR", str(BASE_DIR)))
CREDENTIALS_DIR = DATA_DIR / "credentials"
CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)

# The signing keypair lives in DATA_DIR, NOT next to the code (BASE_DIR) —
# this matters a lot. A `git push` to a Railway-connected repo rebuilds the
# code checkout from scratch every time (that's what makes auto-deploy
# auto-deploy); anything living next to the code instead of in DATA_DIR
# vanishes on every redeploy. If the key lived there, auto-generating a
# replacement on each boot would silently re-sign under a brand new key —
# invalidating every previously-issued credential's signature with no
# warning. Keeping it in DATA_DIR means it survives exactly as long as
# issued credentials do, which is required: they're both runtime state
# for this specific deployment, generated once and never regenerated.
KEYS_DIR         = DATA_DIR / "keys"
PRIVATE_KEY_PATH = KEYS_DIR / "credential_private.pem"
PUBLIC_KEY_PATH  = KEYS_DIR / "credential_public.pem"


def _ensure_keypair():
    """
    Generate this deployment's signing keypair on first boot if one isn't
    there yet — so a fresh deploy doesn't need a manual `python
    create_keys.py` step first. Only happens once per DATA_DIR: after
    that, the existing key is always reused, which is what has to happen
    for previously-issued credentials to keep verifying. See the KEYS_DIR
    note above — this *requires* DATA_DIR to point at real persistent
    storage (a Railway Volume) in production, or the key this generates
    is lost on the next restart/redeploy along with every credential
    signed with it.
    """
    if PRIVATE_KEY_PATH.exists() and PUBLIC_KEY_PATH.exists():
        return
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    sk = SigningKey.generate(curve=SECP256k1)
    with open(PRIVATE_KEY_PATH, "wb") as f:
        f.write(sk.to_pem())
    with open(PUBLIC_KEY_PATH, "wb") as f:
        f.write(sk.verifying_key.to_pem())
    print(f"⚠ No signing keypair found at {KEYS_DIR} — generated a new one. "
          "This key makes every credential issued from now on verifiable. "
          "Make sure DATA_DIR points at real persistent storage (a Railway "
          "Volume in production) — losing this file later breaks "
          "signature verification for every credential signed with it. "
          "See SETUP.md.")

_ensure_keypair()


def load_signing_key():
    with open(PRIVATE_KEY_PATH, "rb") as f:
        return SigningKey.from_pem(f.read())


def load_public_key_hex():
    sk = load_signing_key()
    return "0x" + sk.verifying_key.to_string().hex()


def hash_string(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def issue_credential(
    name: str,
    email: str,
    tier: str,
    expiry_days: int = 31,
    sections: list = None,
    metadata: dict = None,
    expires_at_override: datetime = None,
) -> dict:
    """
    Issue a signed credential for a member.

    Returns a dict with all credential data including the signed manifest.

    `expires_at_override` (a timezone-aware datetime) sets the exact moment the
    credential stops working, instead of now + `expiry_days` (an event ticket
    ends when its event does).
    """

    now        = datetime.now(timezone.utc)
    expiry     = expires_at_override if expires_at_override is not None else now + timedelta(days=expiry_days)
    issued_at  = now.isoformat()
    expires_at = expiry.isoformat()

    credential_id = hash_string(f"{email}{issued_at}")[:16]

    # No actual blockchain/timestamp anchoring is implemented — this is a
    # placeholder for that future feature, always this value today. It
    # MUST be in the manifest before signing, not patched in afterward:
    # the signature covers the manifest's exact bytes, so mutating any
    # field post-signature (as this used to do — setting "PENDING" here,
    # signing, then overwriting it to "NOT_ANCHORED" before saving) means
    # the saved manifest.json no longer matches what was actually signed,
    # and every full cryptographic bundle verification fails with a false
    # "signature invalid" — a real bug, caught while testing the key
    # changes above, not introduced by them.
    fingerprint_hash = "NOT_ANCHORED"

    # ── Build manifest ──
    manifest = {
        "credential_id":    credential_id,
        "bundle_type":      "credential",
        "bundle_spec":      "1.0",
        "holder_name":      name,
        "holder_email":     email,
        "tier":             tier,
        "sections":         sections or [],
        "issued_at":        issued_at,
        "expires_at":       expires_at,
        "expiry_days":      expiry_days,
        "metadata":         metadata or {},
        "public_key":       load_public_key_hex(),
        "fingerprint_hash": fingerprint_hash,
    }

    # ── Sign manifest (over its final, as-saved content) ──
    sk = load_signing_key()
    manifest_bytes = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    signature     = sk.sign(manifest_bytes, sigencode=sigencode_der)
    signature_hex = signature.hex()

    # ── Save manifest and sig ──
    cred_dir = CREDENTIALS_DIR / credential_id
    cred_dir.mkdir(exist_ok=True)

    manifest_path = cred_dir / "manifest.json"
    sig_path      = cred_dir / "manifest.sig"
    entry_path    = cred_dir / "credential_entry.json"

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    with open(sig_path, "wb") as f:
        f.write(bytes.fromhex(signature_hex))

    entry = {
        "credential_id":    credential_id,
        "holder_name":      name,
        "holder_email":     email,
        "tier":             tier,
        "sections":         sections or [],
        "issued_at":        issued_at,
        "expires_at":       expires_at,
        "metadata":         metadata or {},
        "fingerprint_hash": fingerprint_hash,
        "signature_hex":    signature_hex,
    }

    with open(entry_path, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2)

    print(f"✔ Credential issued: {credential_id}")
    print(f"  Holder: {name} <{email}>")
    print(f"  Tier: {tier}")
    print(f"  Expires: {expires_at}")

    return {
        "credential_id":    credential_id,
        "manifest_path":    str(manifest_path),
        "sig_path":         str(sig_path),
        "entry_path":       str(entry_path),
        "cred_dir":         str(cred_dir),
        "fingerprint_hash": fingerprint_hash,
        "signature_hex":    signature_hex,
        "manifest":         manifest,
        "entry":            entry,
    }


# ── Quick test ──
if __name__ == "__main__":
    result = issue_credential(
        name        = "Test Member",
        email       = "test@example.com",
        tier        = "MEMBER",
        expiry_days = 31,
        sections    = ["posts", "community", "downloads"],
        metadata    = {"source": "test"}
    )
    print("\nResult:")
    print(f"  credential_id: {result['credential_id']}")
    print(f"  manifest: {result['manifest_path']}")
    print(f"  fingerprint: {result['fingerprint_hash']}")