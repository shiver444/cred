"""
Backup and restore of everything a deployment owns.

Everything lives in DATA_DIR (the Railway Volume): the signing key, the
member registry, settings, content, issued cards and bundles, and uploaded
files. If that storage is ever lost, so are all of those. A backup is one
zip file the creator keeps somewhere safe; a restore puts it back, on the
same deployment or on a brand-new one.

The zip holds (relative to DATA_DIR):
  manifest.json  what this is, when, and how many members
  keys/  config.json  content.json  member_registry.json
  payment_requests.json  revocation_list.json  stripe_processed_sessions.json
  credentials/  bundles/  cards/            small
  uploads/                                  optional, can be large

Restoring is deliberately careful: the zip is fully checked first (nothing
outside the list above is ever written, no paths that climb out of the
folder, no links, sizes capped, the key must be a real matching pair, the
JSON files must be valid), it is unpacked to a staging folder, and only
then swapped in. What it replaces is moved aside, not deleted, so a wrong
restore can be undone by hand. A failed restore changes nothing.
"""

import json
import os
import secrets
import shutil
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

FORMAT = "credential-protocol-backup"
VERSION = 1

DATA_FILES = ("config.json", "content.json", "member_registry.json",
              "payment_requests.json", "revocation_list.json",
              "stripe_processed_sessions.json")
DATA_DIRS = ("keys", "credentials", "bundles", "cards")
UPLOADS = "uploads"
PRIVATE_KEY = "keys/credential_private.pem"
PUBLIC_KEY = "keys/credential_public.pem"
STATE_FILE = "backup_state.json"
MAX_ENTRIES = 200_000
SPARE_BYTES = 50 * 1024 * 1024        # free space to leave over when checking room

# Expected top-level JSON shape of each data file.
_JSON_SHAPE = {
    "config.json": dict, "content.json": dict, "member_registry.json": list,
    "payment_requests.json": list, "revocation_list.json": dict,
    "stripe_processed_sessions.json": (list, dict),
}


class BackupError(Exception):
    """Something wrong with a backup or a restore, in words for the creator."""


# ── helpers ──
def _walk(root: Path):
    """Every regular file under root (links are never followed or included)."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.is_file() and not p.is_symlink():
                yield p


def _dir_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in _walk(root)) if root.is_dir() else 0


def _read_json_bytes(path: Path, tries: int = 4) -> bytes:
    """The file's bytes, re-read if a write was in progress and it didn't
    parse (the registry is rewritten in place, not atomically)."""
    last = None
    for i in range(tries):
        data = path.read_bytes()
        try:
            json.loads(data.decode("utf-8"))
            return data
        except ValueError as e:
            last = e
            time.sleep(0.05 * (i + 1))
    raise BackupError(f"{path.name} could not be read cleanly ({last}). Try the backup again.")


def free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def member_count(data_dir: Path) -> int:
    try:
        reg = json.loads((Path(data_dir) / "member_registry.json").read_text(encoding="utf-8"))
        return len(reg) if isinstance(reg, list) else 0
    except Exception:
        return 0


def sizes(data_dir: Path) -> dict:
    """{"data_bytes", "uploads_bytes", "members"} for the dashboard."""
    data_dir = Path(data_dir)
    data = sum((data_dir / f).stat().st_size for f in DATA_FILES if (data_dir / f).is_file())
    data += sum(_dir_bytes(data_dir / d) for d in DATA_DIRS)
    return {"data_bytes": data, "uploads_bytes": _dir_bytes(data_dir / UPLOADS),
            "members": member_count(data_dir)}


# ── when was the last backup ──
def last_backup_at(data_dir: Path):
    try:
        raw = json.loads((Path(data_dir) / STATE_FILE).read_text(encoding="utf-8"))
        dt = datetime.fromisoformat(raw["last_backup_at"])
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def record_backup(data_dir: Path):
    data_dir = Path(data_dir)
    fd, tmp = tempfile.mkstemp(dir=str(data_dir), prefix=".backup-state-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"last_backup_at": datetime.now(timezone.utc).isoformat()}, f)
    os.replace(tmp, data_dir / STATE_FILE)


def backup_is_recent(data_dir: Path, days: int = 30) -> bool:
    dt = last_backup_at(data_dir)
    return bool(dt) and (datetime.now(timezone.utc) - dt).days < days


# ── making a backup ──
def build_backup(data_dir: Path, out_file, include_uploads: bool = False, creator_name: str = "") -> dict:
    """Write a backup zip to `out_file` (a binary file object). Returns the
    manifest that went into it."""
    data_dir = Path(data_dir)
    members = member_count(data_dir)
    manifest = {
        "format": FORMAT, "version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "creator_name": str(creator_name or "")[:200],
        "members": members, "includes_uploads": bool(include_uploads),
    }
    with zipfile.ZipFile(out_file, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        for name in DATA_FILES:
            p = data_dir / name
            if p.is_file():
                zf.writestr(name, _read_json_bytes(p))
        for d in DATA_DIRS:
            root = data_dir / d
            if root.is_dir():
                for p in _walk(root):
                    zf.write(p, PurePosixPath(*p.relative_to(data_dir).parts).as_posix())
        if include_uploads and (data_dir / UPLOADS).is_dir():
            for p in _walk(data_dir / UPLOADS):
                zf.write(p, PurePosixPath(*p.relative_to(data_dir).parts).as_posix(),
                         compress_type=zipfile.ZIP_STORED)
    return manifest


# ── checking a backup ──
def _clean_name(raw: str):
    """The safe path parts of a zip entry name, or raises BackupError."""
    name = raw.replace("\\", "/")
    if not name or name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise BackupError("This file isn't a valid backup (it contains an unsafe file path).")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." or "\x00" in p for p in parts):
        raise BackupError("This file isn't a valid backup (it contains an unsafe file path).")
    return parts


def validate_backup(zip_path: Path, max_uncompressed: int):
    """Check a backup zip completely before anything is touched.
    Returns (manifest, plan) where plan is a list of (zip name, path parts)
    to unpack. Raises BackupError with a plain-language reason."""
    zip_path = Path(zip_path)
    if not zipfile.is_zipfile(zip_path):
        raise BackupError("That doesn't look like a backup file (it isn't a zip file).")
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise BackupError("That backup file is damaged and can't be opened.")
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise BackupError("That backup has too many files to be a real one.")
        plan, total, names = [], 0, set()
        for info in infos:
            if info.is_dir():
                continue
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise BackupError("This file isn't a valid backup (it contains a link, which backups never do).")
            parts = _clean_name(info.filename)
            top = parts[0]
            if len(parts) == 1 and (top in DATA_FILES or top == "manifest.json"):
                pass
            elif len(parts) >= 2 and (top in DATA_DIRS or top == UPLOADS):
                pass
            else:
                continue          # not part of a backup: ignored, never written
            key = "/".join(parts)
            if key in names:
                raise BackupError("This file isn't a valid backup (the same file appears twice).")
            names.add(key)
            total += info.file_size
            if total > max_uncompressed:
                raise BackupError("That backup unpacks to far more data than this server accepts "
                                  f"(limit {max_uncompressed // (1024 * 1024)} MB).")
            plan.append((info.filename, parts))
        if "manifest.json" not in names:
            raise BackupError("That zip file isn't one of this app's backups (no manifest).")
        try:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        except (ValueError, KeyError):
            raise BackupError("That backup's manifest is unreadable.")
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
            raise BackupError("That zip file isn't one of this app's backups.")
        if manifest.get("version") != VERSION:
            raise BackupError("That backup was made by a different version of this app and can't be restored here.")
        for needed in (PRIVATE_KEY, PUBLIC_KEY):
            if needed not in names:
                raise BackupError("That backup has no signing key in it, so restoring it would make every card "
                                  "stop verifying. It was not restored.")
        bad = zf.testzip()
        if bad:
            raise BackupError(f"That backup is damaged (the file '{bad}' is corrupt). It was not restored.")
        # The key must be a real, matching pair, and the data files real JSON.
        try:
            from ecdsa import SigningKey, VerifyingKey
            sk = SigningKey.from_pem(zf.read(PRIVATE_KEY))
            vk = VerifyingKey.from_pem(zf.read(PUBLIC_KEY))
            if sk.verifying_key.to_string() != vk.to_string():
                raise ValueError("pair")
        except Exception:
            raise BackupError("The signing key in that backup is damaged or its two halves don't match. It was not restored.")
        for name, shape in _JSON_SHAPE.items():
            if name in names:
                try:
                    ok = isinstance(json.loads(zf.read(name).decode("utf-8")), shape)
                except ValueError:
                    ok = False
                if not ok:
                    raise BackupError(f"{name} in that backup is damaged. It was not restored.")
    return manifest, plan


# ── restoring ──
def restore_backup(zip_path: Path, data_dir: Path, max_uncompressed: int, lock=None) -> dict:
    """Validate, unpack to a staging folder, then swap in. Whatever is
    replaced is moved to `.replaced-<time>` (older ones are removed). Returns
    a summary dict. Raises BackupError and changes nothing on any problem."""
    data_dir = Path(data_dir)
    manifest, plan = validate_backup(zip_path, max_uncompressed)
    need = sum(zipfile.ZipFile(zip_path).getinfo(n).file_size for n, _ in plan)
    if free_bytes(data_dir) < need + SPARE_BYTES:
        raise BackupError("There isn't enough free storage on this server to unpack that backup.")

    staging = data_dir / f".restore-{secrets.token_hex(6)}"
    replaced = data_dir / f".replaced-{int(time.time())}-{secrets.token_hex(3)}"
    moved = []          # (replaced_path, live_path) for rollback
    swapped = []        # live paths now holding restored data
    try:
        staging.mkdir()
        written = 0
        with zipfile.ZipFile(zip_path) as zf:
            for name, parts in plan:
                if parts == ["manifest.json"]:
                    continue
                dest = staging.joinpath(*parts)
                if staging.resolve() not in dest.resolve().parents:
                    raise BackupError("This file isn't a valid backup (it contains an unsafe file path).")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, open(dest, "wb") as out:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > max_uncompressed:
                            raise BackupError("That backup unpacks to far more data than this server accepts.")
                        out.write(chunk)

        # The backup is the whole truth about the items it covers: an item
        # that isn't in it didn't exist when it was made, so the live copy is
        # moved aside too. Uploads are only touched if the backup included them.
        present = {parts[0] for _, parts in plan if parts != ["manifest.json"]}
        items = sorted(present | set(DATA_FILES) | set(DATA_DIRS)
                       | ({UPLOADS} if manifest.get("includes_uploads") else set()))
        ctx = lock if lock is not None else _NoLock()
        with ctx:
            replaced.mkdir()
            for item in items:
                live = data_dir / item
                if live.exists() or live.is_symlink():
                    os.replace(live, replaced / item)
                    moved.append((replaced / item, live))
                if (staging / item).exists():
                    os.replace(staging / item, live)
                    swapped.append(live)
    except BaseException:
        # Put back whatever was already swapped, newest first.
        for live in reversed(swapped):
            try:
                if live.is_dir() and not live.is_symlink():
                    shutil.rmtree(live, ignore_errors=True)
                else:
                    live.unlink()
            except OSError:
                pass
        for old, live in reversed(moved):
            try:
                os.replace(old, live)
            except OSError:
                pass
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(replaced, ignore_errors=True)
        raise
    shutil.rmtree(staging, ignore_errors=True)
    for old in data_dir.glob(".replaced-*"):
        if old != replaced:
            shutil.rmtree(old, ignore_errors=True)
    return {"members": manifest.get("members"), "includes_uploads": bool(manifest.get("includes_uploads")),
            "created_at": manifest.get("created_at"), "items": sorted(present), "kept_previous": replaced.name}


class _NoLock:
    def __enter__(self): return self
    def __exit__(self, *a): return False
