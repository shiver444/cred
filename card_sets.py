"""
Credential Protocol: card sets ("collect these cards, get a supercard").

A set names a few cards (the pieces) and one reward card. The moment one person
(one email address) holds every piece, the reward is issued to them
automatically, once, and they get one email about it.

  {"id": "a1b2c3d4", "name": "The Robot",
   "pieces": ["HEAD", "ARMS", "LEGS"],      card names, 1 to 12, all different
   "need": 0,                                 0 = every piece; otherwise how many they must collect (see below)
   "reward": "ROBOT",                         any other card (often one marked "only I give it out")
   "include_existing": false,                 also reward people who already had every piece when the set was made
   "active_from": "2026-10-11T08:00:00+00:00"}

Three ways to use it (the "need" number):
  * every piece (need 0, two or more cards): head + arms + legs.
  * any N of a list (need 1 up to the number of cards less one, two or more cards): any 3 of 5 wines.
    Each different card counts once.
  * one card, N times (one card, need 1 to 20): "collect the stamp 5 times", or need 1 for "get this card, get
    that reward". Every copy counts, so the person must hold several copies (claim codes always work for that).

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
MIN_PIECES = 1
MAX_NEED = 20
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


def _need(value, n_pieces) -> int:
    """The stored "need": 0 = every piece. One card: how many copies (1 to 20). Several cards: 1 to one less than all of them."""
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError):
        n = 0
    if n_pieces == 1:
        return min(MAX_NEED, max(1, n))
    return n if 1 <= n < n_pieces else 0


def target(s) -> int:
    """How many cards a person must have for this set to be complete."""
    n = len(s["pieces"])
    need = _need(s.get("need"), n)
    return need if need else n


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
            warnings.append(f"\"{name}\" needs at least one card to collect, so it was not saved.")
            continue
        need = _need(r.get("need"), len(pieces))
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
        # Changing which cards count, or how many, starts the set again from now (unless the creator ticked "also give the
        # reward to people who already hold it"): lowering a number must not suddenly reward a batch of people.
        changed = bool(prev) and (sorted(str(x).upper() for x in prev.get("pieces") or []) != sorted(x.upper() for x in pieces)
                                  or (prev.get("pieces") and target({"pieces": prev["pieces"], "need": prev.get("need")}) != target({"pieces": pieces, "need": need})))
        out.append({"id": sid, "name": name, "pieces": pieces, "need": need, "reward": names[rk],
                    "include_existing": r.get("include_existing") is True,
                    "active_from": now if (changed and r.get("include_existing") is not True) else (prev.get("active_from") or now)})
    return out, warnings


def of_config(cfg) -> list:
    """The saved sets, tidied (a hand-edited config can't break anything)."""
    raw = (cfg or {}).get("sets")
    out = []
    for s in (raw if isinstance(raw, list) else [])[:MAX_SETS]:
        if (isinstance(s, dict) and isinstance(s.get("pieces"), list) and len(s["pieces"]) >= MIN_PIECES and s.get("reward")
                and _ID.match(str(s.get("id") or "")) and _name(s.get("name"))):
            pcs = [str(p) for p in s["pieces"]][:MAX_PIECES]
            out.append({"id": s["id"], "name": _name(s["name"]), "pieces": pcs, "need": _need(s.get("need"), len(pcs)),
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
        p = out.setdefault(key, {"name": e.get("holder_name") or "", "email": e.get("holder_email") or "", "pieces": {}, "copies": {}})
        p["name"] = e.get("holder_name") or p["name"]
        p["email"] = e.get("holder_email") or p["email"]
        tier, issued = str(e.get("tier") or "").strip().upper(), _parse(e.get("issued_at"))
        if tier and issued is not None:
            p["copies"].setdefault(tier, []).append(issued)
            if tier not in p["pieces"] or issued < p["pieces"][tier]:
                p["pieces"][tier] = issued
    return out


def rewarded_keys(registry, s, given=None) -> set:
    """Every person (email key) who already has this set's reward: it was given by the set (even if it was
    revoked or deleted later: `given` is the permanent record), or you sent them that card yourself.
    One pass over the registry, so a long member list stays fast."""
    reward = str(s["reward"]).strip().upper()
    keys = set((given or {}).get(s["id"]) or [])
    for e in registry:
        if (e.get("from_set") or {}).get("id") == s["id"] or str(e.get("tier") or "").strip().upper() == reward:
            k = limits.normalize_email(e.get("holder_email"))
            if k:
                keys.add(k)
    return keys


def rewarded(registry, s, key, given=None) -> bool:
    """True when this person already has this set's reward (see rewarded_keys)."""
    return bool(key) and key in rewarded_keys(registry, s, given)


def _times(s, person) -> list:
    """When each card that counts toward this set was obtained, oldest first (one card: every copy; several: each card once)."""
    if len(s["pieces"]) == 1:
        return sorted((person.get("copies") or {}).get(str(s["pieces"][0]).upper(), []))
    return sorted(t for t in (person["pieces"].get(str(p).upper()) for p in s["pieces"]) if t is not None)


def count_of(s, person) -> int:
    """How many cards this person has that count toward the set (may be more than needed)."""
    return len(_times(s, person))


def completed_at(s, person):
    """When the set was completed (the moment the last needed card was obtained), or None."""
    times, need = _times(s, person), target(s)
    return times[need - 1] if (times and len(times) >= need) else None


def due(sets, tiers, registry, given=None, only=None) -> list:
    """[(set, person, completed_at)] who should be given a reward now (`only` = one email key)."""
    ppl = people(registry)
    out = []
    for s in sets:
        if problems(s, tiers):
            continue
        since = _parse(s.get("active_from"))
        got = rewarded_keys(registry, s, given)
        for key, person in ppl.items():
            if only and key != only:
                continue
            done = completed_at(s, person)
            if done is None or key in got:
                continue
            if not s.get("include_existing") and since is not None and done <= since:
                continue
            out.append((s, person, done))
    out.sort(key=lambda t: t[2])
    return out


def waiting_now(s, tiers, registry, given=None, ppl=None) -> int:
    """How many people had already completed the set before it was made (or last changed) and have not been
    rewarded: the people the "also give the reward to people who already hold every piece" box is about."""
    if problems(s, tiers):
        return 0
    got = rewarded_keys(registry, s, given)
    since, n = _parse(s.get("active_from")), 0
    for key, person in (ppl if ppl is not None else people(registry)).items():
        done = completed_at(s, person)
        if done is not None and key not in got and (since is None or done <= since):
            n += 1
    return n


def counts(s, registry, given=None, ppl=None) -> dict:
    """{"rewarded": n, "collecting": n}: people who got the reward, and people who hold some but not all pieces."""
    ppl = ppl if ppl is not None else people(registry)
    got = rewarded_keys(registry, s, given)
    part = sum(1 for key, p in ppl.items() if key not in got and completed_at(s, p) is None and count_of(s, p) > 0)
    return {"rewarded": sum(1 for key in ppl if key in got), "collecting": part}


def held_by(registry, email) -> dict:
    """{CARD NAME in capitals: the newest unrevoked entry} for everything this email address holds (one pass)."""
    key, out = limits.normalize_email(email), {}
    if not key:
        return out
    for e in registry:
        if limits.normalize_email(e.get("holder_email")) != key or e.get("revoked"):
            continue
        t = str(e.get("tier") or "").strip().upper()
        if t and (t not in out or str(e.get("issued_at") or "") > str(out[t].get("issued_at") or "")):
            out[t] = e
    return out


def holding(registry, email, tier):
    """The newest card of this kind that this email address holds and that was not revoked (or None)."""
    return held_by(registry, email).get(str(tier or "").strip().upper())


def member_view(sets, tiers, registry, email, this_tier=None, given=None) -> list:
    """What one member sees: every set they have started (or whose piece/reward is the card they
    are looking at), with each slot filled or empty. Nothing for a card with no email address."""
    key = limits.normalize_email(email)
    if not key:
        return []
    person = people(registry).get(key) or {"pieces": {}, "copies": {}}
    out = []
    for s in sets:
        if problems(s, tiers):
            continue
        need = target(s)
        if len(s["pieces"]) == 1:
            have = len((person.get("copies") or {}).get(str(s["pieces"][0]).upper(), []))
            slots = [{"name": tier_label(tiers, s["pieces"][0]), "tier": str(s["pieces"][0]), "got": i < have} for i in range(need)]
        else:
            slots = [{"name": tier_label(tiers, p), "tier": str(p), "got": str(p).upper() in person["pieces"]} for p in s["pieces"]]
        has_reward = rewarded(registry, s, key, given)
        involved = any(sl["got"] for sl in slots) or has_reward or (
            this_tier and str(this_tier).upper() in [str(p).upper() for p in s["pieces"] + [s["reward"]]])
        if not involved:
            continue
        complete = count_of(s, person) >= need
        # "pending" = the reward is on its way. Someone who finished before the set existed (and the
        # "already complete" box is unticked) is never going to get it, so they are not promised one.
        done, since = completed_at(s, person), _parse(s.get("active_from"))
        pending = bool(complete and not has_reward and (s.get("include_existing") or since is None or (done is not None and done > since)))
        out.append({"name": s["name"], "got": min(need, count_of(s, person)), "total": need, "slots": slots,
                    "reward": {"name": tier_label(tiers, s["reward"]), "tier": str(s["reward"]), "got": has_reward},
                    "complete": complete, "pending": pending})
    return out
