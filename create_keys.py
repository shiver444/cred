"""
Optional: generate this deployment's signing keypair by hand, ahead of
first boot. credential_issuer.py now generates one automatically the
first time the app runs if none exists yet, so running this script is no
longer required — it's here for anyone who wants to generate (and back
up) the key before ever starting the app, or regenerate it deliberately.

Writes to the same place credential_issuer.py reads from: DATA_DIR/keys
(the persistent Volume mount in production), falling back to a local
./keys folder when DATA_DIR isn't set. Never run this against a DATA_DIR
that already has issued credentials — overwriting an existing key breaks
signature verification for every credential signed with the old one.
"""

import os
from pathlib import Path
from ecdsa import SigningKey, SECP256k1

data_dir = Path(os.environ.get("DATA_DIR", "."))
keys_dir = data_dir / "keys"
keys_dir.mkdir(parents=True, exist_ok=True)

private_path = keys_dir / "credential_private.pem"
public_path  = keys_dir / "credential_public.pem"

if private_path.exists() or public_path.exists():
    print(f"A keypair already exists at {keys_dir} — not overwriting it.")
    print("Delete those files yourself first if you really mean to replace them")
    print("(only safe if no credential has been issued with the old one yet).")
else:
    sk = SigningKey.generate(curve=SECP256k1)
    with open(private_path, "wb") as f:
        f.write(sk.to_pem())
    with open(public_path, "wb") as f:
        f.write(sk.verifying_key.to_pem())
    print(f"Keys generated at {keys_dir}.")
