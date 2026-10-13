"""
Credential Protocol: claim codes.

A creator makes a batch of one-time codes for a card ("200 codes for the Founders pass") and
hands them out on flyers, bottle labels, tickets, packaging. Whoever enters a code on the claim
page (name + email) gets that card, and the code is used up. A code can also carry a fixed number
(bottle 112 gets collectible #112, whoever claims it).

This file is the rules and the stored data only (credential_api.py does the HTTP and the issuing):

  * the data is one dict, kept in DATA_DIR/claim_codes.json:
        {"batches": {batch_id: {"id", "name", "tier", "created_at", "count", "numbered", "start"}},
         "codes":   {"ABCDEFGHJK": {"b": batch_id, "n": number or None, "state": "new" | "pending" | "used" | "cancelled",
                                    "at": when it last changed, "email": who, "cid": their card}}}
  * a code is 10 characters from a 31-letter alphabet without lookalikes (no 0 O 1 I L), shown as
    ABCDE-FGHJK: about 8 x 10^14 possibilities, so guessing one is not realistic, and wrong guesses
    from one visitor are limited too (FailGuard).
  * claiming is two steps so two people can never use one code: `reserve` (marks it "pending" for a
    few minutes) -> the card is issued -> `finish` (marks it used) or `release` (the issue failed).
"""

import io
import re
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timezone

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"        # 31 letters and digits, nothing that looks like another
CODE_LEN = 10
MAX_PER_BATCH = 1000
MAX_CODES = 20000
MAX_BATCHES = 200
MAX_NAME = 60
PENDING_SECONDS = 300                               # a claim that never finished frees its code after this long
STATES = ("new", "pending", "used", "cancelled")

_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def empty() -> dict:
    return {"batches": {}, "codes": {}}


def clean_data(raw) -> dict:
    """Whatever was on disk -> a usable dict (never raises)."""
    if not isinstance(raw, dict):
        return empty()
    batches, codes = {}, {}
    for bid, b in (raw.get("batches") or {}).items() if isinstance(raw.get("batches"), dict) else []:
        if isinstance(b, dict) and re.fullmatch(r"[a-f0-9]{8}", str(bid)):
            batches[bid] = {"id": bid, "name": _name(b.get("name")), "tier": str(b.get("tier") or "")[:80],
                            "created_at": str(b.get("created_at") or "")[:40], "count": _int(b.get("count")),
                            "numbered": bool(b.get("numbered")), "start": _int(b.get("start"))}
    for code, c in (raw.get("codes") or {}).items() if isinstance(raw.get("codes"), dict) else []:
        if isinstance(c, dict) and re.fullmatch("[%s]{%d}" % (ALPHABET, CODE_LEN), str(code)) and c.get("b") in batches:
            n = c.get("n")
            codes[code] = {"b": c["b"], "n": n if isinstance(n, int) and not isinstance(n, bool) and 0 < n < 10**9 else None,
                           "state": c.get("state") if c.get("state") in STATES else "new",
                           "at": str(c.get("at") or "")[:40], "email": str(c.get("email") or "")[:254], "cid": str(c.get("cid") or "")[:80]}
    return {"batches": batches, "codes": codes}


def _int(v) -> int:
    try:
        return max(0, int(v))
    except (TypeError, ValueError, OverflowError):
        return 0


def _name(v) -> str:
    return _CTRL.sub("", str(v or "")).strip()[:MAX_NAME]


def _now(now=None) -> datetime:
    return now or datetime.now(timezone.utc)


def normalize(text) -> str:
    """What a person typed -> the stored form (letters and digits only, upper case). "" if it can't be a code."""
    s = re.sub(r"[\s\-_.]", "", str(text or "")).upper()
    return s if len(s) == CODE_LEN and all(ch in ALPHABET for ch in s) else ""


def fmt(code: str) -> str:
    return f"{code[:5]}-{code[5:]}" if len(code) == CODE_LEN else code


def _new_code(existing) -> str:
    for _ in range(50):
        c = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))
        if c not in existing:
            return c
    raise RuntimeError("could not make a unique code")


def make_batch(data: dict, name, tier: str, count, numbered=False, start=1, size=None, taken=(), now=None):
    """Adds a batch of codes to `data`. Returns (batch, [codes in order], None) or (None, [], "what is wrong").
    `size` = the card's edition size (None = open), `taken` = numbers of this card that are already issued."""
    name = _name(name)
    if not name:
        return None, [], "Give the batch a name, for example \"Bottle labels spring 2027\"."
    try:
        count = int(count)
    except (TypeError, ValueError):
        return None, [], f"How many codes? Enter a whole number from 1 to {MAX_PER_BATCH}."
    if not 1 <= count <= MAX_PER_BATCH:
        return None, [], f"How many codes? Enter a whole number from 1 to {MAX_PER_BATCH}."
    if len(data["batches"]) >= MAX_BATCHES:
        return None, [], f"You have {MAX_BATCHES} batches already. Cancel or ask for an older batch to be removed first."
    if len(data["codes"]) + count > MAX_CODES:
        return None, [], f"That would be more than {MAX_CODES} codes in total. Make a smaller batch."
    start = _int(start) if numbered else 0
    if numbered:
        if start < 1:
            return None, [], "Numbering starts at 1 or higher."
        last = start + count - 1
        if last >= 10**9:
            return None, [], "Numbering starts too high. Use a starting number below 1,000,000,000."
        if size is not None and last > size:
            return None, [], f"This card has {size} numbers, so numbering {start} to {last} doesn't fit. Make fewer codes or raise the card's edition size."
        used = set(taken) | {c["n"] for c in data["codes"].values()
                             if c["n"] and c["state"] != "cancelled" and data["batches"].get(c["b"], {}).get("tier", "").upper() == str(tier).upper()}
        clash = [n for n in range(start, last + 1) if n in used]
        if clash:
            return None, [], f"Number {clash[0]} of this card is already taken (issued or in another batch). Choose a different starting number."
    bid = secrets.token_hex(4)
    while bid in data["batches"]:
        bid = secrets.token_hex(4)
    batch = {"id": bid, "name": name, "tier": str(tier), "created_at": _now(now).isoformat(), "count": count,
             "numbered": bool(numbered), "start": start}
    data["batches"][bid] = batch
    made = []
    for i in range(count):
        code = _new_code(data["codes"])
        data["codes"][code] = {"b": bid, "n": (start + i) if numbered else None, "state": "new", "at": "", "email": "", "cid": ""}
        made.append(code)
    return batch, made, None


def _expire_pending(c: dict, now):
    if c["state"] == "pending":
        try:
            if (now - datetime.fromisoformat(c["at"])).total_seconds() > PENDING_SECONDS:
                c["state"], c["at"] = "new", ""
        except (ValueError, TypeError):
            c["state"], c["at"] = "new", ""


def lookup(data: dict, code: str, now=None):
    """(status, code record, batch) where status is "ok" (can be claimed), "unknown", "used",
    "pending" (someone is claiming it this very moment) or "cancelled"."""
    code = normalize(code)
    c = data["codes"].get(code) if code else None
    if not c:
        return "unknown", None, None
    _expire_pending(c, _now(now))
    b = data["batches"].get(c["b"])
    if c["state"] == "new":
        return "ok", c, b
    return {"used": "used", "pending": "pending", "cancelled": "cancelled"}[c["state"]], c, b


def reserve(data: dict, code: str, now=None):
    """Takes a code for one claim. Returns (status, record, batch); "ok" means it is now pending for this caller."""
    status, c, b = lookup(data, code, now)
    if status == "ok":
        c["state"], c["at"] = "pending", _now(now).isoformat()
    return status, c, b


def finish(data: dict, code: str, email: str, cid: str, now=None) -> bool:
    c = data["codes"].get(normalize(code))
    if not c:
        return False
    c.update(state="used", at=_now(now).isoformat(), email=str(email or "")[:254], cid=str(cid or "")[:80])
    return True


def release(data: dict, code: str, at=None):
    """Gives a pending code back. With `at` (the time stamp from reserve) it only does so if the
    reservation is still the caller's own."""
    c = data["codes"].get(normalize(code))
    if c and c["state"] == "pending" and (at is None or c["at"] == at):
        c["state"], c["at"] = "new", ""


def cancel(data: dict, batch_id: str) -> int:
    """Cancels every unused code of a batch. Returns how many."""
    n = 0
    for c in data["codes"].values():
        if c["b"] == batch_id and c["state"] in ("new", "pending"):
            c["state"], n = "cancelled", n + 1
    return n


def delete_batch(data: dict, batch_id: str) -> bool:
    """Removes a batch that has no claimed codes left in it (a batch with claims is kept as the record)."""
    if batch_id not in data["batches"]:
        return False
    if any(c["b"] == batch_id and c["state"] == "used" for c in data["codes"].values()):
        return False
    data["codes"] = {k: c for k, c in data["codes"].items() if c["b"] != batch_id}
    del data["batches"][batch_id]
    return True


def summary(data: dict, now=None) -> list:
    """One row per batch, newest first, with counts."""
    now = _now(now)
    rows = {}
    for c in data["codes"].values():
        _expire_pending(c, now)
        r = rows.setdefault(c["b"], {"new": 0, "pending": 0, "used": 0, "cancelled": 0})
        r[c["state"]] += 1
    out = []
    for b in data["batches"].values():
        r = rows.get(b["id"], {"new": 0, "pending": 0, "used": 0, "cancelled": 0})
        out.append({**b, "unused": r["new"] + r["pending"], "claimed": r["used"], "cancelled": r["cancelled"]})
    out.sort(key=lambda x: x["created_at"], reverse=True)
    return out


def codes_of(data: dict, batch_id: str) -> list:
    """[{code, number, state, email, at}] in number/creation order for one batch."""
    rows = [{"code": k, "shown": fmt(k), "number": c["n"], "state": c["state"], "email": c["email"], "at": c["at"]}
            for k, c in data["codes"].items() if c["b"] == batch_id]
    rows.sort(key=lambda r: (r["number"] is None, r["number"] or 0))
    return rows


def csv_cell(v) -> str:
    """A value for a spreadsheet cell: safe against 'formula' injection and quoted properly."""
    s = _CTRL.sub(" ", str(v if v is not None else ""))
    if s[:1] in ("=", "+", "-", "@", "\t", "\r"):
        s = "'" + s
    return '"' + s.replace('"', '""') + '"'


def qr_svg(text: str) -> str:
    """A QR code as a small inline <svg> string (no external files)."""
    import qrcode
    import qrcode.image.svg
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(image_factory=qrcode.image.svg.SvgPathImage).save(buf)
    svg = buf.getvalue().decode("utf-8")
    svg = svg[svg.index("<svg"):]
    return svg


class FailGuard:
    """Limits wrong guesses: after `limit` wrong codes within `window` seconds a visitor must wait."""

    def __init__(self, limit=10, window=900):
        self.limit, self.window, self._fails = limit, window, {}
        self._lock = threading.Lock()

    def wait(self, key, now=None) -> int:
        """Seconds this visitor still has to wait (0 = fine)."""
        now = time.time() if now is None else now
        with self._lock:
            q = self._fails.get(key)
            if not q:
                return 0
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return max(1, int(q[0] + self.window - now) + 1)
            return 0

    def fail(self, key, now=None):
        now = time.time() if now is None else now
        with self._lock:
            self._fails.setdefault(key, deque()).append(now)
            if len(self._fails) > 5000:
                for k in [k for k, q in self._fails.items() if not q or q[-1] <= now - self.window]:
                    del self._fails[k]
