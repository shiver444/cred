"""
Credential Protocol — card kinds.

A tier is one of three kinds of card:

  "pass"    Access pass (the original): a membership that lasts a number of
            days and unlocks members-only content.
  "ticket"  Event ticket: for one event. It carries the event's name, time,
            place and a note (like a seat), is good until the event ends, and
            can be marked as used at the door (Check-in).
  "collectible"  A limited-edition drop (photo set, album, single...). Each
            person who claims one gets a numbered card ("#37 of 100"). It can
            only be claimed inside the drop's window (or until it sells out),
            and it never expires. The edition size is the tier's "max members".

Only the kind and the event details live here. How a card is drawn is a Card
look (card_looks.py); what it unlocks is the tier's sections.

Times are kept the way the creator typed them ("2026-10-12T20:00" = 20:00 on
the 12th, wherever they are) plus `tz`, the browser's offset in minutes
(JavaScript's getTimezoneOffset, so UTC = typed time + tz). The card shows the
typed time; the server uses `tz` only to know when the ticket stops working.
"""

import re
from datetime import datetime, timedelta, timezone

KINDS = ("pass", "ticket", "collectible")
DEFAULT_KIND = "pass"
KIND_NAMES = {"pass": "Access pass", "ticket": "Event ticket", "collectible": "Collectible"}

# A collectible never expires. "Never" is stored as a date far in the future, so
# everything else (active checks, registry, signatures) works unchanged.
NEVER = datetime(2100, 1, 1, tzinfo=timezone.utc)

MAX_NAME = 80
MAX_PLACE = 80
MAX_NOTE = 60
DEFAULT_HOURS = 12      # a ticket with no end time works for this long after the start

_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_LOCAL = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")


def clean_kind(value) -> str:
    return value if value in KINDS else DEFAULT_KIND


def is_ticket(tier) -> bool:
    return isinstance(tier, dict) and tier.get("kind") == "ticket"


def is_collectible(tier) -> bool:
    return isinstance(tier, dict) and tier.get("kind") == "collectible"


def is_never(expires_at) -> bool:
    """True for the far-future date a collectible carries (it never expires)."""
    return str(expires_at or "")[:4] >= "2100"


def _text(value, limit) -> str:
    return _CTRL.sub(" ", str(value or "")).strip()[:limit]


def _local(value) -> str:
    """A typed date and time in the browser's "YYYY-MM-DDTHH:MM" shape, or ""."""
    s = str(value or "").strip().replace(" ", "T")[:16]
    if not _LOCAL.match(s):
        return ""
    try:
        datetime.strptime(s, "%Y-%m-%dT%H:%M")
    except ValueError:
        return ""
    return s


def _tz(value) -> int:
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return 0
    return n if -900 <= n <= 900 else 0


def clean_event(name="", starts_at="", ends_at="", place="", note="", tz=0) -> dict:
    """The event details of a ticket tier, cleaned for saving. An end that is
    not after the start is dropped."""
    start, end = _local(starts_at), _local(ends_at)
    if start and end and end <= start:
        end = ""
    return {"name": _text(name, MAX_NAME), "starts_at": start, "ends_at": end,
            "place": _text(place, MAX_PLACE), "note": _text(note, MAX_NOTE), "tz": _tz(tz)}


def event_of(tier) -> dict:
    """A tier's event details, always a complete dict (empty strings if none)."""
    e = tier.get("event") if isinstance(tier, dict) else None
    e = e if isinstance(e, dict) else {}
    return clean_event(e.get("name"), e.get("starts_at"), e.get("ends_at"),
                       e.get("place"), e.get("note"), e.get("tz"))


def _parse(local: str):
    return datetime.strptime(local, "%Y-%m-%dT%H:%M")


def _utc(local: str, tz: int) -> datetime:
    return (_parse(local) + timedelta(minutes=tz)).replace(tzinfo=timezone.utc)


def has_date(event) -> bool:
    return bool(event and event.get("starts_at"))


def starts_utc(event):
    return _utc(event["starts_at"], event.get("tz", 0)) if has_date(event) else None


def ends_utc(event):
    """When the ticket stops working: the end time if one was given, else
    DEFAULT_HOURS after the start. None if there is no date yet."""
    if not has_date(event):
        return None
    if event.get("ends_at"):
        return _utc(event["ends_at"], event.get("tz", 0))
    return starts_utc(event) + timedelta(hours=DEFAULT_HOURS)


def is_over(event, now=None) -> bool:
    end = ends_utc(event)
    return bool(end and end <= (now or datetime.now(timezone.utc)))


def when_text(event) -> str:
    """"Sat 12 Oct 2026, 20:00" (+ "-23:00" on the same day, or the end's date
    when it runs past midnight). Empty if there is no date."""
    if not has_date(event):
        return ""
    s = _parse(event["starts_at"])
    out = s.strftime("%a %d %b %Y, %H:%M")
    if event.get("ends_at"):
        e = _parse(event["ends_at"])
        out += e.strftime("-%H:%M") if e.date() == s.date() else e.strftime(" → %a %d %b, %H:%M")
    return out


def public_event(tier) -> dict:
    """What a visitor may see of a ticket tier (the sign-up list)."""
    e = event_of(tier)
    return {"name": e["name"], "when": when_text(e), "place": e["place"],
            "over": is_over(e)}


def card_event(tier) -> dict:
    """The event details as stored on an issued ticket and shown on its card."""
    e = event_of(tier)
    return {"name": e["name"], "starts_at": e["starts_at"], "ends_at": e["ends_at"],
            "place": e["place"], "note": e["note"], "tz": e["tz"], "when": when_text(e)}


def sample_event() -> dict:
    """Made-up details for previews."""
    return {"name": "Live Show", "starts_at": "2026-12-12T20:00", "ends_at": "2026-12-12T23:00",
            "place": "The Venue, Your City", "note": "Row B, seat 12", "tz": 0,
            "when": "Sat 12 Dec 2026, 20:00-23:00"}


# ── Collectibles (limited-edition drops) ──
# A drop tier keeps {name, opens_at, closes_at, note, tz} in `drop`. The edition
# size is the tier's max_members; the edition number a card gets is stored with
# the card. Times are typed local times plus `tz`, exactly as for events.

def clean_drop(name="", opens_at="", closes_at="", note="", tz=0) -> dict:
    """The drop details of a collectible tier, cleaned for saving. A closing time
    that is not after the opening time is dropped."""
    opens, closes = _local(opens_at), _local(closes_at)
    if opens and closes and closes <= opens:
        closes = ""
    return {"name": _text(name, MAX_NAME), "opens_at": opens, "closes_at": closes,
            "note": _text(note, MAX_NOTE), "tz": _tz(tz)}


def drop_of(tier) -> dict:
    """A tier's drop details, always a complete dict."""
    d = tier.get("drop") if isinstance(tier, dict) else None
    d = d if isinstance(d, dict) else {}
    return clean_drop(d.get("name"), d.get("opens_at"), d.get("closes_at"), d.get("note"), d.get("tz"))


def drop_state(drop, now=None) -> str:
    """"soon" (not open yet), "open", or "closed" (the window has ended)."""
    now = now or datetime.now(timezone.utc)
    if drop.get("opens_at") and _utc(drop["opens_at"], drop.get("tz", 0)) > now:
        return "soon"
    if drop.get("closes_at") and _utc(drop["closes_at"], drop.get("tz", 0)) <= now:
        return "closed"
    return "open"


def _stamp(local: str) -> str:
    return _parse(local).strftime("%a %d %b %Y, %H:%M")


def public_drop(tier) -> dict:
    """What a visitor may see of a collectible tier (the sign-up list)."""
    d = drop_of(tier)
    return {"name": d["name"], "state": drop_state(d),
            "opens": _stamp(d["opens_at"]) if d["opens_at"] else "",
            "closes": _stamp(d["closes_at"]) if d["closes_at"] else "",
            "note": d["note"]}


def card_drop(tier, edition: int, of=None) -> dict:
    """The drop details as stored on an issued collectible and shown on its card."""
    d = drop_of(tier)
    return {"name": d["name"], "note": d["note"], "edition": int(edition),
            "of": int(of) if of else 0}


def sample_drop() -> dict:
    """Made-up details for previews."""
    return {"name": "Midnight Photo Set", "note": "Signed digital print", "edition": 37, "of": 100}
