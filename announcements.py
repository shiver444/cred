"""
Credential Protocol — announcements.

The creator writes one note (for example "New photo set is up"). It can be:

  - pinned: shown at the top of every member's page until it is replaced or
    removed (only people with a working card ever see it), and/or
  - emailed to a group: everyone with a working card, one tier, or the ticket
    holders of one event.

This file holds the pinned note and the list of what was sent, and works out
who is in each group. Sending the emails is done in credential_api.py (in the
background) with email_sender.build_announcement_email.

Stored in DATA_DIR/announcement.json, so it survives redeploys with the rest.
"""

import json
import os
import re
import secrets
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

import limits

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR)))
FILE = DATA_DIR / "announcement.json"

MAX_TITLE = 80
MAX_TEXT = 1500
MAX_LINK = 500
MAX_HISTORY = 25
MAX_RECIPIENTS = 2000          # one send; a safety net, not a plan limit

_lock = threading.RLock()
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_title(v) -> str:
    return _CTRL.sub(" ", str(v or "")).replace("\r", " ").replace("\n", " ").strip()[:MAX_TITLE]


def clean_text(v) -> str:
    t = _CTRL.sub("", str(v or "")).replace("\r\n", "\n").replace("\r", "\n").strip()
    return re.sub(r"\n{3,}", "\n\n", t)[:MAX_TEXT]


def clean_link(v) -> str:
    u = str(v or "").strip()[:MAX_LINK]
    return u if re.match(r"^https?://[^\s<>\"']+$", u, re.I) else ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read() -> dict:
    try:
        with open(FILE, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return {"current": d.get("current") if isinstance(d.get("current"), dict) else None,
                    "history": [h for h in (d.get("history") or []) if isinstance(h, dict)][:MAX_HISTORY]}
    except (OSError, ValueError):
        pass
    return {"current": None, "history": []}


def _write(d: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".announcement-", suffix=".tmp", dir=str(DATA_DIR))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
        os.replace(tmp, FILE)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def load() -> dict:
    with _lock:
        return _read()


def current():
    """The pinned note, or None."""
    return load()["current"]


def public_current():
    """The pinned note as a member sees it (nothing private in it), or None."""
    c = current()
    if not c or not (c.get("text") or c.get("title")):
        return None
    return {"title": c.get("title", ""), "text": c.get("text", ""), "link": c.get("link", ""),
            "posted_at": (c.get("posted_at") or "")[:10]}


def post(title, text, link, pin: bool) -> dict:
    """Record a new announcement in the history and, if `pin`, make it the
    pinned note. Returns the history entry (with its id)."""
    entry = {"id": secrets.token_hex(6), "title": clean_title(title), "text": clean_text(text),
             "link": clean_link(link), "posted_at": _now(), "pinned": bool(pin), "email": None}
    with _lock:
        d = _read()
        if pin:
            d["current"] = {k: entry[k] for k in ("id", "title", "text", "link", "posted_at")}
        d["history"] = ([entry] + d["history"])[:MAX_HISTORY]
        _write(d)
    return entry


def unpin() -> bool:
    with _lock:
        d = _read()
        had = d["current"] is not None
        d["current"] = None
        _write(d)
    return had


def set_email_status(entry_id: str, **fields):
    """Update the "emailed to ..." part of a history entry (called while sending)."""
    with _lock:
        d = _read()
        for h in d["history"]:
            if h.get("id") == entry_id:
                h["email"] = {**(h.get("email") or {}), **fields}
                break
        _write(d)


# ── who gets an email ──
def _name_of(e: dict) -> str:
    return str(e.get("holder_name") or "").strip() or "there"


def groups(registry: list, tiers: list, now=None) -> list:
    """The groups an announcement can be emailed to, each with how many
    different people are in it: [{"key", "label", "count"}]. Only working cards
    (not revoked, not expired) with an email address count."""
    live = [e for e in registry or [] if e.get("holder_email") and limits.is_active(e, now)]
    out = [{"key": "all", "label": "Everyone with a working card", "count": len({_norm(e) for e in live})}]
    for t in tiers or []:
        name = str(t.get("name") or "")
        if not name:
            continue
        n = len({_norm(e) for e in live if str(e.get("tier") or "").upper() == name.upper()})
        out.append({"key": "tier:" + name, "label": f"{name} members", "count": n})
    events = {}
    for e in live:
        if e.get("kind") == "ticket":
            ev = e.get("event") if isinstance(e.get("event"), dict) else {}
            nm = str(ev.get("name") or e.get("tier") or "")
            if nm:
                events.setdefault(nm, set()).add(_norm(e))
    for nm in sorted(events):
        out.append({"key": "event:" + nm, "label": f"Ticket holders: {nm}", "count": len(events[nm])})
    return out


def _norm(e: dict) -> str:
    return str(e.get("holder_email") or "").strip().lower()


def recipients(registry: list, key: str, now=None) -> list:
    """The entries to email for group `key`: one per email address (the newest
    working card, so the personal link in the email works)."""
    if key != "all" and not key.startswith(("tier:", "event:")):
        return []
    chosen = {}
    for e in sorted(registry or [], key=lambda x: str(x.get("issued_at") or "")):
        if not e.get("holder_email") or not limits.is_active(e, now):
            continue
        if key.startswith("tier:") and str(e.get("tier") or "").upper() != key[5:].upper():
            continue
        if key.startswith("event:"):
            ev = e.get("event") if isinstance(e.get("event"), dict) else {}
            if e.get("kind") != "ticket" or str(ev.get("name") or e.get("tier") or "") != key[6:]:
                continue
        chosen[_norm(e)] = e
    return list(chosen.values())[:MAX_RECIPIENTS]
