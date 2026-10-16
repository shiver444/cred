"""
Credential Protocol: packs.

A pack is a small DATA file that adds something ready-made to a site: a card look or an email look.
The site owner presses "Add" on the More looks screen and the pack is copied into their own settings.
Nothing in a pack is ever run as code, and everything in it is cleaned by the same rules as anything
typed by hand (colors, names, styles, pictures), so a bad or hand-edited pack can't do more than
a bad look.

Where the list comes from (in this order):
  1. the online list at PACKS_URL (a setting on the host; default below). This is how the template's
     author can hand out new looks without anyone redeploying.
  2. the packs/ folder that ships inside the code (works with no internet, and is what is shown if the
     online list can't be reached).
The address is never typed into the dashboard, so no visitor or member can point the server somewhere else.
Online files must be https, come from the same host and folder as the list, and are limited in size.
Redirects are refused.

File shapes (format 1):

  packs/index.json
    {"format": 1, "packs": [{"id": "ember-neon", "kind": "card_look", "name": "Ember", "description": "...",
                             "file": "card-looks/ember-neon.json", "swatch": {"bg": "#111", "fg": "#fff", "accent": "#ff6a3d"}}]}
  a card look:   {"format": 1, "id": "ember-neon", "kind": "card_look", "look": {"card_style": "neon", "accent_color": "#ff6a3d", ...}}
  an email look: {"format": 1, "id": "midnight-blue", "kind": "email_look", "email": {"email_look": "match", "email_bg": "#0b1220", ...}}
"""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import card_looks
import email_look

BASE_DIR = Path(__file__).resolve().parent
LOCAL_DIR = BASE_DIR / "packs"
DEFAULT_URL = "https://raw.githubusercontent.com/shiver444/cred/main/packs/index.json"

KINDS = ("card_look", "email_look")
KIND_NAMES = {"card_look": "Card look", "email_look": "Email look"}
MAX_INDEX_BYTES = 200_000
MAX_PACK_BYTES = 900_000          # a card look may carry a background picture
MAX_PACKS = 60
CACHE_SECONDS = 300
TIMEOUT = 6

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,100}\.json$")

_lock = threading.Lock()
_cache = {"at": 0.0, "url": "", "result": None}


class PackError(Exception):
    pass


def index_url() -> str:
    u = os.environ.get("PACKS_URL", "").strip()
    return u or DEFAULT_URL


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _fetch(url: str, limit: int) -> bytes:
    """Read one online file: https only, no redirects, small, quick."""
    if not url.lower().startswith("https://"):
        raise PackError("The online list must be an https address.")
    req = urllib.request.Request(url, headers={"User-Agent": "CredentialProtocol-packs/1"})
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=TIMEOUT) as r:
            data = r.read(limit + 1)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise PackError("Could not reach the online list.") from e
    if len(data) > limit:
        raise PackError("The online file is too big.")
    return data


def _json(data: bytes):
    try:
        return json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise PackError("That file is not valid.") from e


def _swatch(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {k: email_look.clean_hex(raw.get(k), d) for k, d in (("bg", "#222222"), ("fg", "#ffffff"), ("accent", "#00e87a"))}


def clean_index(raw) -> list:
    """The list file -> clean entries. Anything odd is dropped; nothing here can name another host."""
    if not isinstance(raw, dict) or raw.get("format") != 1 or not isinstance(raw.get("packs"), list):
        raise PackError("That list is not in a format this site understands.")
    out, seen = [], set()
    for e in raw["packs"]:
        if not isinstance(e, dict):
            continue
        pid, kind, file = str(e.get("id") or ""), e.get("kind"), str(e.get("file") or "")
        if not _ID.match(pid) or pid in seen or kind not in KINDS or not _FILE.match(file) or ".." in file or "//" in file:
            continue
        seen.add(pid)
        out.append({"id": pid, "kind": kind, "file": file,
                    "name": " ".join(str(e.get("name") or pid).split())[:40],
                    "description": " ".join(str(e.get("description") or "").split())[:160],
                    "swatch": _swatch(e.get("swatch"))})
        if len(out) >= MAX_PACKS:
            break
    return out


def _local_read(rel: str, limit: int) -> bytes:
    root = LOCAL_DIR.resolve()
    p = (root / rel).resolve()
    if root not in p.parents and p != root:
        raise PackError("That file is not part of this site.")
    try:
        if p.stat().st_size > limit:
            raise PackError("That file is too big.")
        return p.read_bytes()
    except OSError as e:
        raise PackError("That file is missing.") from e


def listing(force: bool = False):
    """(entries, source, note): source is "online" or "bundled"; note is a plain sentence when the online list failed."""
    url = index_url()
    now = time.time()
    with _lock:
        if not force and _cache["result"] and _cache["url"] == url and now - _cache["at"] < CACHE_SECONDS:
            return _cache["result"]
    note = ""
    try:
        entries = clean_index(_json(_fetch(url, MAX_INDEX_BYTES)))
        result = (entries, "online", "")
    except PackError as e:
        note = str(e)
        try:
            entries = clean_index(_json(_local_read("index.json", MAX_INDEX_BYTES)))
        except PackError:
            entries = []
        result = (entries, "bundled", f"{note} Showing the ones that came with your site.")
    with _lock:
        _cache.update(at=now, url=url, result=result)
    return result


def forget_cache():
    with _lock:
        _cache.update(at=0.0, url="", result=None)


def load_pack(entry: dict, source: str) -> dict:
    """The pack file for `entry` (online when the list came from there, with the bundled copy as a back-up)."""
    raws = []
    if source == "online":
        base = index_url().rsplit("/", 1)[0] + "/"
        try:
            raws.append(_fetch(base + urllib.parse.quote(entry["file"], safe="/._-"), MAX_PACK_BYTES))
        except PackError:
            pass
    try:
        raws.append(_local_read(entry["file"], MAX_PACK_BYTES))
    except PackError:
        pass
    if not raws:
        raise PackError("Could not get that pack. Try again in a moment.")
    last = None
    for raw in raws:
        try:
            d = _json(raw)
            if isinstance(d, dict) and d.get("format") == 1 and d.get("id") == entry["id"] and d.get("kind") == entry["kind"]:
                return d
            last = PackError("That pack does not match the list.")
        except PackError as e:
            last = e
    raise last


def card_look_from(pack: dict, looks: list) -> dict:
    """A clean card look (with a fresh id and an unused name) made from a card-look pack."""
    src = pack.get("look") if isinstance(pack.get("look"), dict) else {}
    fields = {k: src.get(k) for k in ("card_title", "accent_color", "card_label", "card_style", "qr_style", "layout",
                                      "show_barcode", "logo_data_uri", "bg_data_uri", "bg_dim")}
    look = card_looks.clean_look({"id": "000000000000", "name": pack.get("name") or "New look", **fields})
    look["id"] = card_looks.new_id(looks)
    look["name"] = card_looks.unique_name(looks, pack.get("name") or "New look")
    return look


def email_settings_from(pack: dict, saved: dict) -> dict:
    """The email-look settings a pack sets (nothing else is touched: logo and website stay as they are)."""
    src = pack.get("email") if isinstance(pack.get("email"), dict) else {}
    sent = {k: src[k] for k in ("email_look", "email_bg", "email_text", "email_accent", "email_font") if k in src}
    if sent.get("email_look") not in email_look.LOOKS:
        raise PackError("That pack has no usable email look.")
    out = email_look.clean_settings(sent, saved)
    return {k: out[k] for k in ("email_look", "email_bg", "email_text", "email_accent", "email_font")}
