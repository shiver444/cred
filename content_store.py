"""
Credential Protocol — members-only content

What a member sees after they verify: a set of named sections, each one of
three kinds —

  links  — a list of items, each with a title, a link, and a short note
           (downloads, videos, posts... anything you can link to)
  merch  — a single discount: a label, a shop link and a code
  chat   — the chat panel (a demo for now: messages stay in the browser)

A links item can carry an uploaded file instead of a link: the file lives
on the server (DATA_DIR/uploads/<id>.bin) and is only ever handed to a
verified member (see credential_api.py: /member-content, /member-file).

A section's `key` is the name tiers refer to in their "Sections" field
(e.g. a tier with sections "downloads, chat" unlocks the sections whose
keys are `downloads` and `chat`).

Stored as:
  {"sections": [
     {"key": "downloads", "title": "Downloads", "type": "links",
      "button": "↓ Download",
      "items": [{"title": "...", "url": "https://...", "note": "..."},
                {"title": "...", "url": "", "note": "...",
                 "file": {"id": "<24 hex>", "name": "ep1.mp4", "size": 123456}}]},
     {"key": "merch", "title": "Merch Discount", "type": "merch",
      "label": "...", "url": "https://...", "code": "..."},
     {"key": "chat", "title": "Chat", "type": "chat"}
  ]}

The older shape this project started with — {"downloads": [...], "bts":
[...], "chat": true, "merch": {...}} — is still read fine (`normalize`), so
an existing content.json keeps working; saving from the dashboard writes
the new shape.
"""

import os
import re
import secrets
import time
from pathlib import Path

import config_store

KEY_RE     = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
FILE_ID_RE = re.compile(r"^[a-f0-9]{24}$")
TYPES = ("links", "merch", "chat")

MAX_SECTIONS = 30
MAX_ITEMS    = 200
MAX_TEXT     = 300
MAX_URL      = 2000

_LEGACY_TITLES = {"downloads": "Downloads", "bts": "Behind The Scenes",
                  "merch": "Merch Discount", "chat": "Chat"}
_LEGACY_BUTTONS = {"downloads": "↓ Download"}


def safe_url(url: str) -> str:
    """Only links a member can safely click: http(s), mailto, a relative path
    or '#'. Anything else — javascript:, data:, vbscript: and so on — is
    dropped to '' rather than ever being rendered as a link."""
    url = (url or "").strip()
    if not url or len(url) > MAX_URL:
        return ""
    if url == "#" or url.startswith("/") and not url.startswith("//"):
        return url
    if re.match(r"^(https?://|mailto:)", url, re.I):
        return url
    return ""


def _text(value, limit=MAX_TEXT) -> str:
    return str(value if value is not None else "").strip()[:limit]


def _legacy_url(url) -> str:
    """The old sample file used "#" as a stand-in for 'no link yet'."""
    url = str(url or "").strip()
    return "" if url == "#" else url


def normalize(raw) -> dict:
    """Any stored shape -> {"sections": [...]} in the current shape."""
    if not isinstance(raw, dict):
        return {"sections": []}
    if isinstance(raw.get("sections"), list):
        return _clean(raw)

    # Legacy shape
    sections = []
    for key in ("downloads", "bts"):
        items = raw.get(key)
        if isinstance(items, list) and items:
            sections.append({
                "key": key, "title": _LEGACY_TITLES[key], "type": "links",
                "button": _LEGACY_BUTTONS.get(key, ""),
                "items": [{"title": i.get("title", ""), "url": _legacy_url(i.get("url")),
                           "note": i.get("meta", "")} for i in items if isinstance(i, dict)],
            })
    if isinstance(raw.get("merch"), dict):
        m = raw["merch"]
        sections.append({"key": "merch", "title": _LEGACY_TITLES["merch"], "type": "merch",
                         "label": m.get("label", ""), "url": _legacy_url(m.get("url")), "code": m.get("code", "")})
    if raw.get("chat"):
        sections.append({"key": "chat", "title": _LEGACY_TITLES["chat"], "type": "chat"})
    return _clean({"sections": sections})


def _clean(data: dict, warnings: list = None) -> dict:
    """Validate/sanitize the new shape. Never raises — drops what's unusable
    (bad keys, duplicate keys, unknown types, unsafe links) so a hand-edited
    or corrupt file can't take the member area down or inject a link.
    Anything dropped is described in `warnings` (when given), so the
    dashboard can tell the creator instead of silently losing their input."""
    warn = warnings if warnings is not None else []
    out, seen = [], set()
    for s in (data.get("sections") or [])[:MAX_SECTIONS]:
        if not isinstance(s, dict):
            continue
        key = _text(s.get("key"), 40).lower()
        typ = _text(s.get("type"), 20).lower() or "links"
        if not KEY_RE.match(key):
            warn.append(f"A section was skipped: its key \"{key}\" must be 1-32 characters: lowercase letters, numbers, - or _.")
            continue
        if key in seen:
            warn.append(f"A second section with the key \"{key}\" was skipped — keys must be unique.")
            continue
        if typ not in TYPES:
            warn.append(f"Section \"{key}\" was skipped: unknown type \"{typ}\".")
            continue
        seen.add(key)
        sec = {"key": key, "title": _text(s.get("title"), 80) or key.replace("-", " ").replace("_", " ").title(), "type": typ}
        if typ == "links":
            sec["button"] = _text(s.get("button"), 30)
            items = []
            for it in (s.get("items") or [])[:MAX_ITEMS]:
                if not isinstance(it, dict):
                    continue
                title = _text(it.get("title"), 160)
                if not title:
                    continue
                url = safe_url(it.get("url"))
                if _text(it.get("url"), MAX_URL) and not url:
                    warn.append(f"\"{title}\" in \"{key}\": the link isn't a valid http(s) or mailto address, so it was removed.")
                item = {"title": title, "url": url, "note": _text(it.get("note"))}
                f = it.get("file")
                if f:
                    fpath = path_for(f.get("id")) if isinstance(f, dict) else None
                    if fpath is not None and fpath.is_file():
                        # the size is what's actually on disk, never what the page claims
                        item["file"] = {"id": f["id"], "name": clean_filename(f.get("name")), "size": fpath.stat().st_size}
                        item["url"] = ""      # a file replaces the link
                    else:
                        warn.append(f"\"{title}\" in \"{key}\": its uploaded file is no longer on the server, so it was removed — upload it again.")
                items.append(item)
            sec["items"] = items
        elif typ == "merch":
            sec["label"] = _text(s.get("label"), 120)
            sec["url"]   = safe_url(s.get("url"))
            if _text(s.get("url"), MAX_URL) and not sec["url"]:
                warn.append(f"Merch link in \"{key}\" isn't a valid http(s) or mailto address, so it was removed.")
            sec["code"]  = _text(s.get("code"), 80)
        out.append(sec)
    return {"sections": out}


def load() -> dict:
    return normalize(config_store.read_content_raw())


def save(payload) -> tuple:
    """Validate and store what the dashboard sent. Returns (what was stored,
    [warnings about anything that had to be dropped])."""
    warnings = []
    data = payload if isinstance(payload, dict) and isinstance(payload.get("sections"), list) else {"sections": []}
    clean = _clean(data, warnings)
    config_store.write_content(clean)
    return clean, warnings


def sections_for_member(content: dict, member_sections) -> list:
    """The sections a member may see: only those whose key is in their
    credential's sections. Order follows the content manager's order."""
    allowed = {str(s).strip().lower() for s in (member_sections or [])}
    return [s for s in content.get("sections", []) if s["key"] in allowed]


def has_any_content(content: dict) -> bool:
    for s in content.get("sections", []):
        if s["type"] == "links" and s.get("items"):
            return True
        if s["type"] == "merch" and (s.get("label") or s.get("code") or s.get("url")):
            return True
    return False   # (the chat panel alone doesn't count — it has nothing for you to add)


# ── Uploaded files ──────────────────────────────────────────────────────
# Stored as DATA_DIR/uploads/<id>.bin — the id is random, the display name
# lives in content.json, and nothing the uploader typed ever becomes part of
# a path. They are only ever served as a download (never rendered), and
# only to a verified member: see /member-file in credential_api.py.

def uploads_dir() -> Path:
    return config_store.DATA_DIR / "uploads"


def path_for(file_id: str):
    """The stored file for this id, or None if the id isn't a well-formed
    upload id (so a hostile id can never point outside the uploads folder)."""
    if not isinstance(file_id, str) or not FILE_ID_RE.match(file_id):
        return None
    return uploads_dir() / f"{file_id}.bin"


def clean_filename(name) -> str:
    """A display name safe to show and to send in a download header: no
    path parts, no control characters, not empty, not absurdly long."""
    name = str(name or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f\"]", "", name).strip().strip(".")
    return name[:120] or "file"


def save_upload(file_storage, max_bytes: int) -> tuple:
    """Store an uploaded file. Returns ({"id","name","size"}, "") or
    (None, reason). Checks free disk space first and removes a partial file
    if anything goes wrong while writing."""
    import shutil
    if not file_storage or not file_storage.filename:
        return None, "No file was chosen."
    d = uploads_dir()
    d.mkdir(parents=True, exist_ok=True)
    declared = getattr(file_storage, "content_length", None) or 0
    try:
        free = shutil.disk_usage(d).free
    except OSError:
        free = None
    if free is not None and max(declared, 0) + 20 * 1024 * 1024 > free:
        return None, "There isn't enough free storage space on the server for that file."
    fid  = secrets.token_hex(12)
    path = d / f"{fid}.bin"
    try:
        written = 0
        with open(path, "wb") as out:
            while True:
                chunk = file_storage.stream.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError("too big")
                out.write(chunk)
        if written == 0:
            raise ValueError("empty")
    except ValueError as e:
        path.unlink(missing_ok=True)
        if str(e) == "empty":
            return None, "That file is empty."
        return None, f"That file is too big (the limit is {max_bytes // (1024 * 1024)} MB)."
    except OSError:
        path.unlink(missing_ok=True)
        return None, "The file couldn't be saved (the server may be out of storage space)."
    return {"id": fid, "name": clean_filename(file_storage.filename), "size": written}, ""


def referenced_ids(content: dict) -> set:
    return {it["file"]["id"] for s in content.get("sections", []) if s.get("type") == "links"
            for it in s.get("items", []) if it.get("file")}


def find_file_item(content: dict, file_id: str, allowed_keys) -> dict:
    """The item (and so the display name) for `file_id` — but only if it sits
    in a section whose key is in `allowed_keys` (the member's tier)."""
    allowed = {str(k).strip().lower() for k in (allowed_keys or [])}
    for s in content.get("sections", []):
        if s.get("type") == "links" and s["key"] in allowed:
            for it in s.get("items", []):
                if it.get("file") and it["file"]["id"] == file_id:
                    return it
    return None


def cleanup_orphans(content: dict, grace_seconds: int = 3600) -> int:
    """Delete stored files no item refers to any more (removed items, replaced
    files, abandoned uploads). Files younger than `grace_seconds` are left
    alone, so an upload that hasn't been saved into the content yet — say,
    in another browser tab — isn't deleted from under the person doing it."""
    keep, removed, now = referenced_ids(content), 0, time.time()
    d = uploads_dir()
    if not d.is_dir():
        return 0
    for f in d.glob("*.bin"):
        if f.stem in keep or not FILE_ID_RE.match(f.stem):
            continue
        try:
            if now - f.stat().st_mtime >= grace_seconds:
                f.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def used_bytes() -> int:
    d = uploads_dir()
    try:
        return sum(f.stat().st_size for f in d.glob("*.bin")) if d.is_dir() else 0
    except OSError:
        return 0
