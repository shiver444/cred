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

import card_kinds
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
    if entry.get("revoked") or entry.get("kind") in ("ticket", "voucher"):   # a ticket's end is just the event; a voucher has its own wording
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


# ── Event reminders: a note to ticket holders shortly before the event ──
# `hours` comes from the dashboard (email_templates.EVREMIND_CHOICES; 0 = off).
# A ticket gets at most one. Tickets already checked in, revoked ones, and
# tickets bought after the reminder time had already passed (their confirmation
# email just went out) are skipped.

def event_due(registry, hours, now=None) -> list:
    now = now or datetime.now(timezone.utc)
    out = []
    if not hours:
        return out
    window = timedelta(hours=hours)
    for e in registry:
        if e.get("kind") != "ticket" or e.get("revoked") or e.get("used_at") or e.get("event_reminded_at"):
            continue
        if not e.get("holder_email"):
            continue
        ev = e.get("event") or {}
        try:
            start = card_kinds.starts_utc(ev)
        except (ValueError, TypeError, KeyError):
            start = None
        if start is None or not (now < start <= now + window):
            continue
        issued = _parse(e.get("issued_at"))
        if issued and (start - issued) <= window:
            continue
        out.append(e)
    return out


def run_events_once(hours, send, now=None) -> dict:
    """Send every event reminder that is due. `send(entry)` returns True when
    the email really went out; claimed first, marked only on success (a failed
    one is retried after a few hours). Returns {"sent": n, "failed": n}."""
    now = now or datetime.now(timezone.utc)
    result = {"sent": 0, "failed": 0}
    for e in event_due(member_registry.list_all(), hours, now):
        cid = e["credential_id"]
        if not member_registry.claim_event_reminder(cid, now):
            continue
        try:
            ok = bool(send(e))
        except Exception as ex:
            print(f"❌ Event reminder for {cid} failed: {ex}")
            ok = False
        if ok:
            member_registry.mark_event_reminded(cid, now)
            result["sent"] += 1
        else:
            result["failed"] += 1
    return result


# ── Follow-up emails: automatic notes some days after someone joins ──
# `steps` comes from email_templates.follow_steps(cfg): [{"n", "days", "for"}].
# A step is sent once per person, N days after their join date, while their
# card still works and they haven't pressed "stop these emails". Only people
# for whom it fell due in the last FOLLOW_WINDOW_DAYS get it, so switching a
# step on later never emails the whole old list.

def followup_due(registry, steps, now=None) -> list:
    """[(entry, step)] that should get an email now, oldest due first."""
    import email_templates
    now = now or datetime.now(timezone.utc)
    window = timedelta(days=email_templates.FOLLOW_WINDOW_DAYS)
    out = []
    for e in registry:
        if e.get("revoked") or e.get("followups_off") or not e.get("holder_email"):
            continue
        issued, end = _parse(e.get("issued_at")), _parse(e.get("expires_at"))
        if issued is None or (end is not None and end <= now):
            continue
        sent = e.get("followups_sent") or {}
        for st in steps:
            if str(st["n"]) in sent:
                continue
            if st.get("for") and str(e.get("tier", "")).strip().lower() != st["for"].strip().lower():
                continue
            due_at = issued + timedelta(days=st["days"])
            if due_at <= now <= due_at + window:
                out.append((due_at, e, st))
    out.sort(key=lambda t: t[0])
    return [(e, st) for _d, e, st in out]


def run_followups_once(steps, send, now=None, limit=None) -> dict:
    """Send the follow-ups that are due (at most `limit` per call, the rest wait
    for the next hourly check). `send(entry, step)` returns True when the email
    really went out; claimed first, marked only on success. {"sent", "failed"}."""
    import email_templates
    now = now or datetime.now(timezone.utc)
    limit = email_templates.FOLLOW_MAX_PER_RUN if limit is None else limit
    result = {"sent": 0, "failed": 0}
    if not steps:
        return result
    for e, st in followup_due(member_registry.list_all(), steps, now):
        if result["sent"] + result["failed"] >= limit:
            break
        cid = e["credential_id"]
        if not member_registry.claim_followup(cid, st["n"], now):
            continue
        try:
            ok = bool(send(e, st))
        except Exception as ex:
            print(f"❌ Follow-up {st['n']} for {cid} failed: {ex}")
            ok = False
        if ok:
            member_registry.mark_followed_up(cid, st["n"], now)
            result["sent"] += 1
        else:
            result["failed"] += 1
    return result


# ── "Something new opened": a note when an item with an opening date opens ──
# Checked every hour. For each member, everything that opened for THEM since the
# last note (or since their card was issued, or since the creator switched the
# email on, or in the last NEWITEM_WINDOW_DAYS, whichever is latest) is listed in
# one email. Nothing old is ever announced, and "stop these emails" is honoured.

def newitem_titles(content, entry, t0, t1) -> list:
    """Titles of the items that opened for this member after t0 and up to t1."""
    import content_store
    import timeline
    out = []
    for sec in content_store.sections_for_member(content, entry.get("sections", [])):
        if sec.get("type") != "links":
            continue
        for it in sec.get("items", []):
            if timeline.is_scheduled(it) and timeline.opened_between(it, entry.get("issued_at"), t0, t1):
                out.append((timeline.opens_utc(it, entry.get("issued_at")), str(it.get("title") or "").strip() or "something new"))
    out.sort(key=lambda x: x[0])
    return [t for _d, t in out]


def newitem_due(registry, content, since, now=None) -> list:
    """[(entry, titles, t1, ids)] to email now, ONE per person (by email address): someone who holds several
    cards that unlock the same item gets one email listing it once. `ids` are the credential ids of every
    card that contributed, all marked once the email went out. `since` is when the creator switched this on."""
    import email_templates
    import limits
    now = now or datetime.now(timezone.utc)
    floor = now - timedelta(days=email_templates.NEWITEM_WINDOW_DAYS)
    people, order = {}, []
    for e in registry:
        if e.get("revoked") or e.get("followups_off") or not e.get("holder_email"):
            continue
        issued, end = _parse(e.get("issued_at")), _parse(e.get("expires_at"))
        if issued is None or (end is not None and end <= now):
            continue
        marks = [m for m in (_parse(e.get("newitem_upto")), since, issued, floor) if m is not None]
        titles = newitem_titles(content, e, max(marks), now)
        if not titles:
            continue
        key = limits.normalize_email(e.get("holder_email")) or e.get("credential_id")
        if key not in people:
            people[key] = {"entry": e, "titles": [], "ids": []}
            order.append(key)
        p = people[key]
        p["ids"].append(e["credential_id"])
        for t in titles:
            if t not in p["titles"]:
                p["titles"].append(t)
    return [(people[k]["entry"], people[k]["titles"], now, people[k]["ids"]) for k in order]


def run_newitems_once(content, since, send, now=None, limit=None) -> dict:
    """Send the "something new opened" emails that are due (at most `limit` per
    call). `send(entry, titles)` returns True when the email really went out;
    claimed first, marked only on success. {"sent", "failed"}."""
    import email_templates
    now = now or datetime.now(timezone.utc)
    limit = email_templates.FOLLOW_MAX_PER_RUN if limit is None else limit
    result = {"sent": 0, "failed": 0}
    if since is None:
        return result
    for e, titles, t1, ids in newitem_due(member_registry.list_all(), content, since, now):
        if result["sent"] + result["failed"] >= limit:
            break
        cid = e["credential_id"]
        if not member_registry.claim_newitem(cid, now):
            continue
        try:
            ok = bool(send(e, titles))
        except Exception as ex:
            print(f"❌ New-item email for {cid} failed: {ex}")
            ok = False
        if ok:
            for x in ids:
                member_registry.mark_newitem(x, t1, now)
            result["sent"] += 1
        else:
            result["failed"] += 1
    return result
