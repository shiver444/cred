"""
Signup limits: how many members a tier can have, and how often one email
address may hold a card for it.

Pure functions only (they take the registry and the pending payment
requests as arguments), so the rules are easy to test and the server
decides in one place. Per tier, in config.json:

  max_members   a whole number, or missing for "no limit". Counts members
                whose card is still active (not revoked, not expired) plus
                manual payment requests waiting for approval, so a tier
                can't be oversold while requests sit in the queue. When a
                card expires or is revoked its spot frees up again.
  show_spots_left   false hides the "N left" number from visitors; the
                tier still shows "Sold out" when it is full. Default true.
  per_email     "one_active" (default): one working card per email at a
                time; "one_ever": an email can only ever get one card for
                this tier (right for a free trial); "unlimited".
"""

from datetime import datetime, timezone

PER_EMAIL_MODES = ("one_active", "one_ever", "unlimited")
DEFAULT_PER_EMAIL = "one_active"
MAX_MEMBERS_CEILING = 1_000_000


def normalize_email(email) -> str:
    """The form of an email used to tell people apart. Lower-case, a
    "+tag" in the name part is dropped (a+1@x.com is a@x.com), and for
    Gmail the dots are dropped too (they never matter there). It can't
    catch every trick, it just stops the easy ones."""
    e = (email or "").strip().lower()
    if "@" not in e:
        return e
    local, _, domain = e.rpartition("@")
    plain = local.split("+", 1)[0]
    if plain:
        local = plain
    if domain in ("gmail.com", "googlemail.com"):
        local = local.replace(".", "") or local
        domain = "gmail.com"
    return f"{local}@{domain}"


def clean_max_members(value):
    """A whole number from 1 up, or None for "no limit" (blank, 0, junk)."""
    try:
        n = int(str(value).strip())
    except (ValueError, TypeError):
        return None
    return n if 1 <= n <= MAX_MEMBERS_CEILING else None


def tier_max(tier_cfg):
    return clean_max_members((tier_cfg or {}).get("max_members"))


def per_email_mode(tier_cfg) -> str:
    m = (tier_cfg or {}).get("per_email")
    return m if m in PER_EMAIL_MODES else DEFAULT_PER_EMAIL


def _now(now):
    return now or datetime.now(timezone.utc)


def is_active(entry, now=None) -> bool:
    if entry.get("revoked"):
        return False
    try:
        exp = datetime.fromisoformat(str(entry.get("expires_at")))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False
    return exp > _now(now)


def _same_tier(a, b) -> bool:
    return str(a or "").strip().upper() == str(b or "").strip().upper()


def count_taken(registry, requests, tier_name, now=None) -> int:
    """Spots in use: active members plus requests waiting for approval."""
    active = sum(1 for e in registry if _same_tier(e.get("tier"), tier_name) and is_active(e, now))
    pending = sum(1 for r in requests if r.get("status") == "pending" and _same_tier(r.get("tier"), tier_name))
    return active + pending


def public_state(tier_cfg, registry, requests, now=None) -> dict:
    """What a visitor may be told about a tier: {} when it has no limit,
    otherwise {"sold_out": bool} plus {"spots_left": n} unless hidden."""
    cap = tier_max(tier_cfg)
    if cap is None:
        return {}
    left = max(0, cap - count_taken(registry, requests, tier_cfg.get("name"), now))
    state = {"sold_out": left == 0}
    if tier_cfg.get("show_spots_left", True) is not False:
        state["spots_left"] = left
    return state


def check_signup(tier_cfg, tier_name, email, registry, requests, creator="the creator", now=None):
    """None when this signup may go ahead, otherwise (reason, message) with
    reason "already_member" or "sold_out"."""
    label = (tier_cfg or {}).get("label") or tier_name
    key = normalize_email(email)
    mode = per_email_mode(tier_cfg)

    if mode != "unlimited":
        mine = [e for e in registry
                if _same_tier(e.get("tier"), tier_name) and normalize_email(e.get("holder_email")) == key]
        waiting = [r for r in requests
                   if r.get("status") == "pending" and _same_tier(r.get("tier"), tier_name)
                   and normalize_email(r.get("holder_email")) == key]
        if waiting:
            return ("already_member",
                    f"There is already a request for {label} waiting for approval for this email. "
                    f"Contact {creator} if you have questions.")
        if mode == "one_ever" and (mine or any(
                r.get("status") == "approved" and _same_tier(r.get("tier"), tier_name)
                and normalize_email(r.get("holder_email")) == key for r in requests)):
            return ("already_member",
                    f"This email has already been used for {label}, so it can't be used again. "
                    f"Contact {creator} if you think that's a mistake.")
        if mode == "one_active" and any(is_active(e, now) for e in mine):
            return ("already_member",
                    f"This email already has an active card for {label}. Check your inbox (and spam folder), "
                    f"or contact {creator} if you can't find it.")

    cap = tier_max(tier_cfg)
    if cap is not None and count_taken(registry, requests, tier_name, now) >= cap:
        return ("sold_out", f"Sorry, {label} is sold out.")
    return None
