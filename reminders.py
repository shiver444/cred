"""
Expiry reminders: an email a few days before a member's card runs out.

The rules live here as plain functions (they take the registry, the clock
and a "send" function as arguments) so they are easy to test; the server
runs `run_once` every hour from a small background thread.

  reminder_days   in config.json: 0 = off (the default), otherwise how many
                  days before the end date the email goes out (1 to 60).

A member gets at most one reminder per end date. If the creator extends the
card, the end date changes and a fresh reminder is owed for the new date.
"""

from datetime import datetime, timedelta, timezone

import member_registry

MAX_REMINDER_DAYS = 60
CHECK_EVERY_SECONDS = 3600   # how often the server looks (one hour)


def clean_reminder_days(value) -> int:
    """0 (off) or a whole number from 1 to MAX_REMINDER_DAYS. Anything else
    — blank, junk, negative, too big — means off, never "some surprise value"."""
    try:
        n = int(str(value).strip())
    except (ValueError, TypeError):
        return 0
    return n if 1 <= n <= MAX_REMINDER_DAYS else 0


def _parse(ts):
    try:
        d = datetime.fromisoformat(str(ts))
    except (ValueError, TypeError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def days_left(entry, now=None) -> int:
    """Whole days until the card ends, counted upwards (a card with 20 hours
    left is "1 day"). 0 if it has already ended or the date is unreadable."""
    now = now or datetime.now(timezone.utc)
    end = _parse(entry.get("expires_at"))
    if end is None or end <= now:
        return 0
    return max(1, -(-int((end - now).total_seconds()) // 86400))


def is_expiring_soon(entry, window_days, now=None) -> bool:
    """Active (not revoked, not ended) and ending within `window_days`."""
    now = now or datetime.now(timezone.utc)
    if entry.get("revoked") or entry.get("kind") == "ticket":   # a ticket's end is just the event
        return False
    end = _parse(entry.get("expires_at"))
    return bool(end and now < end <= now + timedelta(days=window_days))


def due(registry, window_days, now=None) -> list:
    """Members who should get a reminder now. A card whose whole lifetime is
    no longer than the reminder window (e.g. a 3-day pass with a 3-day
    reminder) is skipped — it would be reminded the moment it was issued."""
    now = now or datetime.now(timezone.utc)
    out = []
    if not window_days:
        return out
    for e in registry:
        if not e.get("holder_email") or e.get("reminded_for") == e.get("expires_at"):
            continue
        if not is_expiring_soon(e, window_days, now):
            continue
        issued, end = _parse(e.get("issued_at")), _parse(e.get("expires_at"))
        if issued and end and (end - issued) <= timedelta(days=window_days):
            continue
        out.append(e)
    return out


def run_once(window_days, send, now=None) -> dict:
    """Send every reminder that is due. `send(entry, days_left)` returns True
    when the email really went out. Each member is "claimed" first (so the
    same email is never sent twice, even if this runs again right away) and
    marked as reminded only after a successful send; a failed one is retried
    after a few hours. Returns {"sent": n, "failed": n}."""
    now = now or datetime.now(timezone.utc)
    result = {"sent": 0, "failed": 0}
    for e in due(member_registry.list_all(), window_days, now):
        cid, exp = e["credential_id"], e["expires_at"]
        if not member_registry.claim_reminder(cid, exp, now):
            continue
        try:
            ok = bool(send(e, days_left(e, now)))
        except Exception as ex:   # one bad member must not stop the rest
            print(f"❌ Reminder for {cid} failed: {ex}")
            ok = False
        if ok:
            member_registry.mark_reminded(cid, exp, now)
            result["sent"] += 1
        else:
            result["failed"] += 1
    return result
