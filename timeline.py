"""
Credential Protocol: the clock for members-only content (timeline).

A links item can carry a "when" rule, so content opens over time instead of all
at once (an advent calendar, "a new picture on the 1st of every month", a
course that releases a lesson a week):

  opens   {"mode": "date",  "at": "2026-12-01T09:00", "tz": -60}
              opens on that date and time for everyone. The time is kept the way
              the creator typed it plus `tz`, the browser's offset in minutes
              (JavaScript's getTimezoneOffset), exactly like event dates on tickets.
          {"mode": "after", "days": 7}
              opens that many days after the person's card was issued
              (a drip: day 0 = right away).
  until   {"at": "2027-01-01T00:00", "tz": -60}   (optional)
              after this the item closes ("ended").

No rule = open from the start, as before. Repeating dates ("every month on the
1st") are made by the content editor's "Spread dates" helper, which simply fills
in one date per item, so there is nothing hidden that runs later.

Everything a member's browser is told about a closed item is decided here and in
credential_api.member_content: a locked or ended item never carries its link,
file, picture, note or price (and, in a "mystery" section, not even its title).
"""

import calendar
import re
from datetime import datetime, timedelta, timezone

import card_kinds

MODES = ("date", "after")
MAX_DAYS = 3650
LOCKED_VIEWS = ("title", "mystery")
ID_RE = re.compile(r"^[a-f0-9]{8}$")


def clean_id(value) -> str:
    v = str(value or "").strip().lower()
    return v if ID_RE.match(v) else ""


def clean_opens(raw):
    """A cleaned "opens" rule, or None (open from the start)."""
    if not isinstance(raw, dict):
        return None
    mode = str(raw.get("mode") or "").strip().lower()
    if mode == "date":
        at = card_kinds._local(raw.get("at"))
        return {"mode": "date", "at": at, "tz": card_kinds._tz(raw.get("tz"))} if at else None
    if mode == "after":
        try:
            days = int(float(raw.get("days")))
        except (TypeError, ValueError, OverflowError):
            return None
        return {"mode": "after", "days": max(0, min(MAX_DAYS, days))}
    return None


def clean_until(raw):
    if not isinstance(raw, dict):
        return None
    at = card_kinds._local(raw.get("at"))
    return {"at": at, "tz": card_kinds._tz(raw.get("tz"))} if at else None


def clean_locked_view(value) -> str:
    v = str(value or "").strip().lower()
    return v if v in LOCKED_VIEWS else "title"


def is_scheduled(item) -> bool:
    return isinstance(item, dict) and bool(item.get("opens") or item.get("until"))


def _parse(ts):
    try:
        d = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


_NEVER = datetime(9999, 12, 31, tzinfo=timezone.utc)


def _days(o) -> int:
    """The number of days of a "days after joining" rule, always a whole number from 0 to MAX_DAYS."""
    try:
        return max(0, min(MAX_DAYS, int(float(o.get("days", 0)))))
    except (TypeError, ValueError, OverflowError):
        return 0


def opens_utc(item, issued_at=None):
    """When the item opens for this person (None = from the start). A rule that cannot be worked
    out (a hand-edited, absurd value) keeps the item locked rather than opening it."""
    o = item.get("opens") if isinstance(item, dict) else None
    if not o:
        return None
    if not isinstance(o, dict):
        return _NEVER
    try:
        if o.get("mode") == "date":
            return card_kinds._utc(o["at"], o.get("tz", 0))
        if o.get("mode") == "after":
            base = _parse(issued_at)
            if base is None:
                return None
            return base + timedelta(days=_days(o))
    except (OverflowError, ValueError, TypeError, KeyError):
        return _NEVER
    return None


def until_utc(item):
    """When the item closes (None = never). An unusable value means it simply does not close."""
    u = item.get("until") if isinstance(item, dict) else None
    if not isinstance(u, dict):
        return None
    try:
        return card_kinds._utc(u["at"], u.get("tz", 0)) if u else None
    except (OverflowError, ValueError, TypeError, KeyError):
        return None


def state(item, issued_at=None, now=None) -> str:
    """"open", "locked" (not yet) or "ended" for one item and one person."""
    now = now or datetime.now(timezone.utc)
    end = until_utc(item)
    if end is not None and end <= now:
        return "ended"
    start = opens_utc(item, issued_at)
    if start is not None and start > now:
        return "locked"
    return "open"


def when_text(item) -> str:
    """The opening time in the creator's own words: "Tue 01 Dec 2026" (plus the
    time when it is not midnight), or "Day 7" for a drip."""
    o = item.get("opens") if isinstance(item, dict) else None
    if not o or not isinstance(o, dict):
        return ""
    if o.get("mode") == "after":
        d = _days(o)
        return "Right away" if d == 0 else f"Day {d}"
    try:
        s = datetime.strptime(o["at"], "%Y-%m-%dT%H:%M")
    except (ValueError, TypeError, KeyError):
        return ""
    return s.strftime("%a %d %b %Y") + ("" if (s.hour, s.minute) == (0, 0) else s.strftime(", %H:%M"))


def until_text(item) -> str:
    u = item.get("until") if isinstance(item, dict) else None
    if not u or not isinstance(u, dict):
        return ""
    try:
        s = datetime.strptime(u["at"], "%Y-%m-%dT%H:%M")
    except (ValueError, TypeError, KeyError):
        return ""
    return s.strftime("%a %d %b %Y") + ("" if (s.hour, s.minute) == (0, 0) else s.strftime(", %H:%M"))


def opened_between(item, issued_at, t0, t1) -> bool:
    """True when the item became open for this person after t0 and up to t1."""
    start = opens_utc(item, issued_at)
    if start is None:
        return False
    end = until_utc(item)
    if end is not None and end <= t1:
        return False
    return t0 < start <= t1


def spread(count: int, start_local: str, step: str, tz: int = 0) -> list:
    """`count` typed dates, one per item, from `start_local` ("YYYY-MM-DDTHH:MM"),
    stepping by "day", "week" or "month" (the same day of the month; a short
    month uses its last day). The helper behind the editor's "Spread dates"."""
    start = card_kinds._local(start_local)
    if not start or step not in ("day", "week", "month"):
        return []
    s = datetime.strptime(start, "%Y-%m-%dT%H:%M")
    out = []
    for i in range(max(0, min(int(count), 400))):
        if step == "day":
            d = s + timedelta(days=i)
        elif step == "week":
            d = s + timedelta(weeks=i)
        else:
            m = s.month - 1 + i
            y, mo = s.year + m // 12, m % 12 + 1
            d = s.replace(year=y, month=mo, day=min(s.day, calendar.monthrange(y, mo)[1]))
        out.append({"mode": "date", "at": d.strftime("%Y-%m-%dT%H:%M"), "tz": card_kinds._tz(tz)})
    return out


def when_fields(item, issued_at) -> dict:
    """How a scheduled item says when it opens: `opens_text` (a date), `opens_at`
    (a precise UTC time, for sorting, month headings and a countdown) and, for
    a drip, `day` (the "Day 7" number)."""
    start = opens_utc(item, issued_at)
    o = item.get("opens") or {}
    out = {
        "opens_text": when_text(item) if o.get("mode") == "date" else (
            start.strftime("%a %d %b %Y") if start is not None else when_text(item)),
        "opens_at": start.isoformat() if start is not None else "",
    }
    if o.get("mode") == "after":
        out["day"] = _days(o)
    if until_utc(item) is not None:
        out["until_text"] = until_text(item)
    return out


def open_item(item, issued_at) -> dict:
    """An item that is open now: everything it has, but with its rule replaced by
    the plain words and times above (a member's browser never needs the rule)."""
    out = {k: v for k, v in item.items() if k not in ("opens", "until")}
    out["state"] = "open"
    out.update(when_fields(item, issued_at))
    return out


def closed_item(item, st, issued_at, mystery=False) -> dict:
    """The only thing a member learns about a locked or ended item."""
    out = {"id": item.get("id", ""), "state": st, "locked": st == "locked"}
    out["title"] = "" if (mystery and st == "locked") else item.get("title", "")
    out.update(when_fields(item, issued_at))
    return out
