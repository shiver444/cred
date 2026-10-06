"""
Credential Protocol — config store

Where this deployment's live settings (branding, tiers, pricing, payment
instructions, per-tier card designs and their logos) are read from and
saved to.

Why this isn't just "config.json next to the code": on Railway, every
`git push` rebuilds the code checkout from scratch. A settings file that
lived next to the code would be silently reset to whatever is in the repo
every time — wiping what the creator saved in /admin/dashboard. So:

  * The LIVE copy lives in DATA_DIR/config.json (DATA_DIR is the persistent
    Volume in production), which a redeploy never touches. The dashboard
    saves here.
  * The repo's config.json (next to the code) is only the first-boot
    default: used until the first dashboard save creates the live copy.
    After that, edits to the repo's config.json no longer take effect —
    change settings in the dashboard instead.

Locally, DATA_DIR falls back to the code folder, so both paths are the same
file and everything behaves exactly as it always did.
"""

import json
import os
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR)))

DEFAULT_CONFIG_PATH = BASE_DIR / "config.json"   # ships in the repo
LIVE_CONFIG_PATH    = DATA_DIR / "config.json"   # lives on the Volume


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("config.json must contain a JSON object")
    return data


def read_config() -> dict:
    """The current settings: the live copy if there is one, otherwise the
    repo's default. An unreadable/corrupt file is skipped (with a note in
    the logs) rather than crashing the app; {} if nothing usable exists."""
    for path in (LIVE_CONFIG_PATH, DEFAULT_CONFIG_PATH):
        if not path.exists():
            continue
        try:
            return _load(path)
        except Exception as e:
            print(f"⚠ Could not read {path} ({e}) — skipping it.")
    return {}


def _write_atomic(path: Path, obj: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(DATA_DIR), prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def write_config(cfg: dict) -> None:
    """Save settings to the live copy in DATA_DIR. Written to a temp file
    and swapped into place, so a crash or restart mid-save can never leave
    a half-written (and therefore unreadable) config behind."""
    _write_atomic(LIVE_CONFIG_PATH, cfg)


# ── Members-only content (what the Content page in /admin edits) ──
# Same arrangement as the settings above: the live copy is on the Volume
# (DATA_DIR/content.json), the repo's content.json is just the starter
# content used until the first save from the dashboard.
DEFAULT_CONTENT_PATH = BASE_DIR / "content.json"
LIVE_CONTENT_PATH    = DATA_DIR / "content.json"


def read_content_raw() -> dict:
    """The stored content as-is (old or new shape — content_store.py
    normalizes it): the live copy if there is one, else the repo starter."""
    for path in (LIVE_CONTENT_PATH, DEFAULT_CONTENT_PATH):
        if not path.exists():
            continue
        try:
            return _load(path)
        except Exception as e:
            print(f"⚠ Could not read {path} ({e}) — skipping it.")
    return {}


def write_content(obj: dict) -> None:
    """Save content to the live copy in DATA_DIR (atomic, like write_config)."""
    _write_atomic(LIVE_CONTENT_PATH, obj)
