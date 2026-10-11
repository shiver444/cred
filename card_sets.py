"""
Credential Protocol: card sets ("collect these cards, get a supercard").

A set names a few cards (the pieces) and one reward card. The moment one person
(one email address) holds every piece, the reward is issued to them
automatically, once, and they get one email about it.

  {"id": "a1b2c3d4", "name": "The Robot",
   "pieces": ["HEAD", "ARMS", "LEGS"],      card names, 2 to 12, all different
   "reward": "ROBOT",                         any other card (often one marked "only I give it out")
   "include_existing": false,                 also reward people who already had every piece when the set was made
   "active_from": "2026-10-11T08:00:00+00:00"}

Rules, kept simple on purpose:
  * A piece counts when the card was issued to that email and has not been
    revoked. A ticket that was used or a card that has run out still counts: it
    was collected.
  * People are told apart by email address (the same way limits.py does it), so
    the pieces can be bought with different names.
  * The reward is given once per person per set, even if they later lose a
    piece or the reward card is revoked. Someone you already sent the reward
    card to by hand does not get a second one.
  * Unless "include_existing" is ticked, only people who finish the set after it
    was made get the reward; nobody is surprised by a mass mailing.
  * A set whose card was deleted or renamed is shown with a warning and does
    nothing until it is fixed.

This module is plain functions on lists (config tiers, the registry), so it is
easy to test. credential_api.py does the issuing and the email.
"""

import re
import secrets
from datetime import datetime, timezone

import limits

MAX_SETS = 20
MIN_PIECES = 2
MAX_PIECES = 12
MAX_NAME = 60
_ID = re.compile(r"^[a-f0-9]{8}$")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def _name(value) -> str:
    return " ".join(_CTRL.sub(" ", str(value or "")).split())[:MAX_NAME]


def _tier_names(tiers) -> dict:
    """{UPPER name: the card's name as saved} for every card."""
    return {str(t.get("name") or "").strip().upper(): str(t.get("name") or "").strip()
            for t in (tiers or []) if isinstance(t, dict) and str(t.get("name") or "").strip()}


def tier_label(tiers, name) -> str:
    for t in tiers or []:
        if str(t.get("name") or "").strip().upper() == str(name or "").strip().upper():
            return str(t.get("label") or t.get("name") or "").strip()
    return str(name or "")


def clean(raw, tiers, old=None) -> tuple:
    """(sets to store, [plain-words warnings]). Anything that cannot work is
    dropped with a warning instead of being saved half-broken."""
    warnings = []
    names = _tier_names(tiers)
    old_by_id = {s.get("id"): s for s in (old or []) if isinstance(s, dict)}
    out, seen = [], set()
    now = datetime.now(timezone.utc).isoformat()
    for r in (raw if isinstance(raw, list) else [])[:MAX_SETS]:
        if not isinstance(r, dict):
            continue
        name = _name(r.get("name"))
        if not name:
            warnings.append("A set with no name was left out.")
            continue
        pieces = []
        for p in (r.get("pieces") if isinstance(r.get("pieces"), list) else []):
            key = str(p or "").strip().upper()
            if key in names and names[key].upper() not in [x.upper() for x in pieces]:
                pieces.append(names[key])
            elif key and key not in names:
                warnings.append(f"\"{name}\": there is no card called \"{str(p)[:40]}\", so it was left out of the pieces.")
        pieces = pieces[:MAX_PIECES]
        if len(pieces) < MIN_PIECES:
            warnings.append(f"\"{name}\" needs at least {MIN_PIECES} different cards as pieces, so it was not saved.")
            continue
        rk = str(r.get("reward") or "").strip().upper()
        if rk not in names:
            warnings.append(f"\"{name}\" needs a reward card, so it was not saved.")
            continue
        if rk in [p.upper() for p in pieces]:
            warnings.append(f"\"{name}\": the reward can't also be one of the pieces, so it was not saved.")
            continue
        sid = str(r.get("id") or "").strip().lower()
        if not _ID.match(sid) or sid in seen:
            sid = secrets.token_hex(4)
            while sid in seen:
                sid = secrets.token_hex(4)
        seen.add(sid)
        prev = old_by_id.get(sid) or {}
        out.append({"id": sid, "name": name, "pieces": pieces, "reward": names[rk],
                    "include_existing": r.get("include_existing") is True,
                    "active_from": prev.get("active_from") or now})
    return out, warnings


def of_config(cfg) -> list:
    """The saved sets, tidied (a hand-edited config can't break anything)."""
    raw = (cfg or {}).get("sets")
    out = []
    for s in (raw if isinstance(raw, list) else [])[:MAX_SETS]:
        if (isinstance(s, dict) and isinstance(s.get("pieces"), list) and s.get("reward")
                and _ID.match(str(s.get("id") or "")) and _name(s.get("name"))):
            out.append({"id": s["id"], "name": _name(s["name"]), "pieces": [str(p) for p in s["pieces"]][:MAX_PIECES],
                        "reward": str(s["reward"]), "include_existing": s.get("include_existing") is True,
                        "active_from": str(s.get("active_from") or "")})
    return out


def problems(s, tiers) -> list:
    """What is wrong with a set right now (a card was deleted or renamed)."""
    names = _tier_names(tiers)
    bad = [p for p in s["pieces"] if str(p).upper() not in names]
    if str(s["reward"]).upper() not in names:
        bad.append(s["reward"])
    return bad


def _parse(ts):
    try:
        d = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def people(registry) -> dict:
    """{email key: {"name", "email", "pieces": {CARD NAME: when they first got it}}} for every
    card that has an email and was not revoked."""
    out = {}
    for e in registry:
        key = limits.normalize_email(e.get("holder_email"))
        if not key or e.get("revoked"):
            continue
        p = out.setdefault(key, {"name": e.get("holder_name") or "", "email": e.get("holder_email") or "", "pieces": {}})
        p["name"] = e.get("holder_name") or p["name"]
        p["email"] = e.get("holder_email") or p["email"]
        tier, issued = str(e.get("tier") or "").strip().upper(), _parse(e.get("issued_at"))
        if tier and issued is not None and (tier not in p["pieces"] or issued < p["pieces"][tier]):
            p["pieces"][tier] = issued
    return out


def rewarded(registry, s, key) -> bool:
    """True when this person already has this set's reward: it was given by the set (even if it was
    revoked later) or you sent them that card yourself."""
    reward = str(s["reward"]).strip().upper()
    return any(limits.normalize_email(e.get("holder_email")) == key
               and ((e.get("from_set") or {}).get("id") == s["id"] or str(e.get("tier") or "").strip().upper() == reward)
               for e in registry)


def completed_at(s, person):
    got = [person["pieces"].get(str(p).upper()) for p in s["pieces"]]
    return None if any(g is None for g in got) else max(got)


def due(sets, tiers, registry) -> list:
    """[(set, person, completed_at)] who should be given a reward now."""
    ppl = people(registry)
    out = []
    for s in sets:
        if problems(s, tiers):
            continue
        since = _parse(s.get("active_from"))
        for key, person in ppl.items():
            done = completed_at(s, person)
            if done is None or rewarded(registry, s, key):
                continue
            if not s.get("include_existing") and since is not None and done <= since:
                continue
            out.append((s, person, done))
    out.sort(key=lambda t: t[2])
    return out


def waiting_now(s, tiers, registry) -> int:
    """How many people already hold every piece and have not been rewarded (for the screen)."""
    if problems(s, tiers):
        return 0
    return sum(1 for key, person in people(registry).items()
               if completed_at(s, person) is not None and not rewarded(registry, s, key))


def counts(s, registry) -> dict:
    """{"rewarded": n, "collecting": n}: people who got the reward, and people who hold some but not all pieces."""
    ppl = people(registry)
    got = sum(1 for key in ppl if rewarded(registry, s, key))
    part = sum(1 for key, p in ppl.items()
               if completed_at(s, p) is None and any(str(x).upper() in p["pieces"] for x in s["pieces"]))
    return {"rewarded": got, "collecting": part}


def member_view(sets, tiers, registry, email, this_tier=None) -> list:
    """What one member sees: every set they have started (or whose piece/reward is the card they
    are looking at), with each slot filled or empty."""
    key = limits.normalize_email(email)
    person = people(registry).get(key) or {"pieces": {}}
    out = []
    for s in sets:
        if problems(s, tiers):
            continue
        slots = [{"name": tier_label(tiers, p), "got": str(p).upper() in person["pieces"]} for p in s["pieces"]]
        has_reward = rewarded(registry, s, key)
        involved = any(sl["got"] for sl in slots) or has_reward or (
            this_tier and str(this_tier).upper() in [str(p).upper() for p in s["pieces"] + [s["reward"]]])
        if not involved:
            continue
        out.append({"name": s["name"], "got": sum(1 for sl in slots if sl["got"]), "total": len(slots), "slots": slots,
                    "reward": {"name": tier_label(tiers, s["reward"]), "got": has_reward},
                    "complete": all(sl["got"] for sl in slots)})
    return out
