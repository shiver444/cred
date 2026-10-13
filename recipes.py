"""
Credential Protocol: recipes.

A recipe is a short list of plain questions ("what is it called, how much, how long does it last") that builds
everything behind it: the card(s), the set, the batch of claim codes. The creator never has to know that a
"numbered bottle" is a collectible card plus a batch of numbered codes.

This file is only the rules (plain functions, easy to test). `plan(recipe, answers, ctx)` checks the answers and
returns either {"problem": "what to fix, in plain words"} or what to create:

    {"tiers":  [new card dicts, as saved in config.json],
     "edits":  {CARD NAME: {changes to an existing card}} (only the "collect" recipe, to allow repeat sign-ups),
     "set":    a raw set dict for card_sets.clean (or None),
     "codes":  {"name", "tier", "count", "numbered", "start", "size"} (or None),
     "lines":  ["what was made", ...]}

credential_api.py (`POST /admin/recipes/make`) saves it. Nothing is saved when anything is wrong.

The six recipes: membership, ticket, edition (numbered bottles / albums / prints), collect (collect and get a
reward), discount (one-time discount or gift codes), certificate.
"""

import re
from datetime import datetime, timezone

import card_kinds
import limits

RECIPES = ("membership", "ticket", "edition", "collect", "discount", "certificate")
MAX_NAME = 40                 # the card's internal name (capitals)
MAX_LABEL = 60                # what people see
MAX_CODES = 1000              # one batch of claim codes (claim_codes.MAX_PER_BATCH)
FOREVER = 36500               # days: "forever" (a membership that never ends)

# How long one membership lasts before it has to be renewed: (days, name for the summary).
LENGTHS = {"weekly": (7, "weekly"), "monthly": (31, "monthly"), "quarterly": (91, "every 3 months"),
           "yearly": (365, "yearly"), "forever": (FOREVER, "forever")}

_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def text(value, limit, commas=True) -> str:
    s = _CTRL.sub(" ", str(value if value is not None else ""))
    if not commas:
        s = s.replace(",", " ")
    return " ".join(s.split())[:limit]


def whole(value, lo, hi, default=None):
    """An integer between lo and hi, else `default` (None = "not given or not usable")."""
    try:
        n = int(float(str(value).strip()))
    except (TypeError, ValueError, OverflowError):
        return default
    return n if lo <= n <= hi else default


def money(value):
    """A price from 0 up (a missing price is free). None if it is not a number."""
    if value is None or str(value).strip() == "":
        return 0.0
    try:
        p = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return round(p, 2) if 0 <= p <= 1_000_000 else None


def flag(value) -> bool:
    return value is True or str(value).strip().lower() in ("1", "true", "yes", "on")


def unique_name(title, taken) -> str:
    """The card's internal name: the title in capitals, no commas, made different from every name in `taken`."""
    base = text(title, MAX_NAME, commas=False).upper() or "CARD"
    used = {str(t).strip().upper() for t in taken}
    name, n = base, 2
    while name in used:
        suffix = f" {n}"
        name, n = base[:MAX_NAME - len(suffix)] + suffix, n + 1
    return name


def voucher_tier(title, terms, days, taken) -> dict:
    """A free voucher card that only the creator can give out (the reward of a set, or a discount code card)."""
    title = text(title, 40, commas=False)
    return {"name": unique_name(title, taken), "kind": "voucher", "hidden": True, "label": title, "price": 0,
            "expiry_days": whole(days, 1, 3650, 90), "sections": [],
            "voucher": card_kinds.clean_voucher(title, terms or "", "", 0, ""), "per_email": "one_ever"}


def _names(tiers) -> list:
    return [str(t.get("name") or "") for t in tiers if isinstance(t, dict)]


def _find(tiers, name):
    key = str(name or "").strip().upper()
    return next((t for t in tiers if isinstance(t, dict) and str(t.get("name") or "").strip().upper() == key), None)


def _unlocks(a, ctx) -> list:
    keys = [str(k) for k in (ctx.get("sections") or {})]
    want = a.get("unlocks")
    want = [str(w) for w in want] if isinstance(want, list) else []
    return [k for k in keys if k in want]


def _who_hidden(a) -> bool:
    return str(a.get("who") or "anyone") in ("invite", "hand", "labels")


def _codes_count(a, key, default, hi=MAX_CODES) -> int:
    return whole(a.get(key), 0, hi, default)


def plan(recipe, a, ctx) -> dict:
    """Checks the answers and says what to create. `ctx` = {"tiers": [existing cards], "sections": {key: title}}."""
    if recipe not in RECIPES:
        return {"problem": "Choose one of the recipes."}
    a = a if isinstance(a, dict) else {}
    ctx = ctx or {}
    ctx["tiers"] = [t for t in (ctx.get("tiers") or []) if isinstance(t, dict)]
    return globals()["_" + recipe](a, ctx)


# ── 1. Membership ──
def _membership(a, ctx):
    name = text(a.get("name"), MAX_LABEL)
    if not name:
        return {"problem": "Give the membership a name, for example \"Fan club\"."}
    price = money(a.get("price"))
    if price is None:
        return {"problem": "The price must be a number (0 for free)."}
    length = str(a.get("length") or "monthly")
    if length == "custom":
        days = whole(a.get("custom_days"), 1, FOREVER)
        if days is None:
            return {"problem": f"How many days does one membership last? Enter a whole number from 1 to {FOREVER}."}
        how = f"{days} days"
    elif length in LENGTHS:
        days, how = LENGTHS[length]
    else:
        return {"problem": "Choose how long a membership lasts."}
    hidden = _who_hidden(a)
    limit = limits.clean_max_members(a.get("limit"))
    unlocks = _unlocks(a, ctx)
    taken = _names(ctx["tiers"])
    main = {"name": unique_name(name, taken), "label": name, "price": price, "expiry_days": days, "sections": unlocks}
    if hidden:
        main["hidden"] = True
    if limit:
        main["max_members"] = limit
    tiers, lines = [main], [f"Membership “{name}” ({'free' if price == 0 else 'paid'}, {how})"]
    if flag(a.get("trial")):
        tdays = whole(a.get("trial_days"), 1, 365)
        if tdays is None:
            return {"problem": "How many days is the free trial? Enter a whole number from 1 to 365."}
        tlabel = text(f"{name} (free trial)", MAX_LABEL)
        trial = {"name": unique_name(f"{name} trial", taken + [main["name"]]), "label": tlabel, "price": 0, "expiry_days": tdays,
                 "sections": unlocks, "per_email": "one_ever"}
        if hidden:
            trial["hidden"] = True
        tiers.append(trial)
        lines.append(f"Free trial “{tlabel}” ({tdays} days)")
    codes = None
    count = _codes_count(a, "codes", 0) if str(a.get("who")) == "invite" else 0
    if count:
        codes = {"name": text(f"{name} invitations", 60), "tier": main["name"], "count": count, "numbered": False, "start": 0, "size": limit}
        lines.append(f"{count} invitation codes")
    return {"tiers": tiers, "set": None, "codes": codes, "lines": lines, "price": price}


# ── 2. Event ticket ──
def _ticket(a, ctx):
    name = text(a.get("name"), MAX_LABEL)
    if not name:
        return {"problem": "Give the event a name, for example \"Summer party\"."}
    starts = card_kinds._local(a.get("starts_at"))
    if not starts:
        return {"problem": "When does it start? Pick the date and time."}
    price = money(a.get("price"))
    if price is None:
        return {"problem": "The ticket price must be a number (0 for free)."}
    event = card_kinds.clean_event(name, starts, a.get("ends_at"), a.get("place"), "", a.get("tz") or 0, "", price > 0)
    if card_kinds.is_over(event):
        return {"problem": "That date has already passed. Pick a date in the future."}
    capacity = limits.clean_max_members(a.get("tickets"))
    tier = {"name": unique_name(name, _names(ctx["tiers"])), "kind": "ticket", "event": event, "label": name, "price": price,
            "expiry_days": 31, "sections": []}
    if _who_hidden(a):
        tier["hidden"] = True
    if capacity:
        tier["max_members"] = capacity
    lines = [f"Ticket “{name}” for {card_kinds.when_text(event)}" + (f" ({capacity} tickets)" if capacity else "")]
    codes = None
    count = _codes_count(a, "codes", 0) if str(a.get("who")) == "invite" else 0
    if count:
        codes = {"name": text(f"{name} invitations", 60), "tier": tier["name"], "count": count, "numbered": False, "start": 0, "size": capacity}
        lines.append(f"{count} invitation codes")
    return {"tiers": [tier], "set": None, "codes": codes, "lines": lines, "price": price}


# ── 3. Numbered edition (bottles, albums, prints) ──
def _edition(a, ctx):
    name = text(a.get("name"), MAX_LABEL)
    if not name:
        return {"problem": "Give it a name, for example \"Cabernet Sauvignon 2024\" or \"First album\"."}
    numbered = a.get("numbered") is not False and str(a.get("numbered")).strip().lower() not in ("0", "false", "no", "off")
    blank_size = str(a.get("size") if a.get("size") is not None else "").strip() == ""
    if not numbered and blank_size:
        size = None                          # not numbered and no limit: as many as people want
    else:
        size = whole(a.get("size"), 1, limits.MAX_MEMBERS_CEILING)
        if size is None:
            return {"problem": ("How many copies will there be? Enter a whole number (for example 100)." if not numbered
                                else "How many numbered copies will there be? Enter a whole number (for example 100).")}
    price = money(a.get("price"))
    if price is None:
        return {"problem": "The price must be a number (0 for free)."}
    how = str(a.get("who") or "labels")
    if how not in ("labels", "anyone", "hand"):
        how = "labels"
    drop = card_kinds.clean_drop(name, "", "", "", 0, "", numbered)
    tier = {"name": unique_name(name, _names(ctx["tiers"])), "kind": "collectible", "drop": drop,
            "label": name, "price": price, "expiry_days": FOREVER, "sections": _unlocks(a, ctx), "per_email": "one_ever"}
    if size is not None:
        tier["max_members"] = size
    if how != "anyone":
        tier["hidden"] = True
    if numbered:
        lines = [f"Numbered edition \u201c{name}\u201d (1 to {size})"]
    else:
        lines = [f"Collectible \u201c{name}\u201d (no numbers" + (f", {size} copies)" if size else ", no limit)")]
    codes = None
    if how == "labels":
        blank = lambda k: str(a.get(k) if a.get(k) is not None else "").strip() == ""
        start = 1 if (blank("start") or not numbered) else whole(a.get("start"), 1, 10**9 - 1)
        if blank("codes"):
            if size is None:
                return {"problem": f"How many codes do you need? Enter a whole number from 1 to {MAX_CODES}."}
            count = min(size, MAX_CODES)
        else:
            count = whole(a.get("codes"), 1, MAX_CODES)
        if start is None:
            return {"problem": "The first number must be a whole number from 1 up."}
        if count is None:
            return {"problem": f"How many codes (labels) do you need? Enter a whole number from 1 to {MAX_CODES}."}
        if size is not None and numbered and start + count - 1 > size:
            return {"problem": f"Numbers {start} to {start + count - 1} don't fit in an edition of {size}. Make fewer labels or start lower."}
        if size is not None and not numbered and count > size:
            return {"problem": f"You asked for {count} codes but only {size} copies exist. Make fewer codes."}
        codes = {"name": text(f"{name} labels" if numbered else f"{name} codes", 60), "tier": tier["name"], "count": count,
                 "numbered": numbered, "start": start, "size": size}
        lines.append(f"{count} numbered codes for your labels (numbers {start} to {start + count - 1})" if numbered
                     else f"{count} codes to print or send (no numbers)")
    return {"tiers": [tier], "set": None, "codes": codes, "lines": lines, "price": price}


# ── 4. Collect and get a reward ──
def _collect(a, ctx):
    tiers = ctx["tiers"]
    edits = {}
    title = text(a.get("reward_title"), 40, commas=False)
    if not title:
        return {"problem": "What is the reward? For example \"15% off your next order\"."}
    mode = "different" if str(a.get("mode")) == "different" else "same"
    if mode == "same":
        card = _find(tiers, a.get("card"))
        if not card:
            return {"problem": "Choose the card people collect. Make it first with one of the other recipes."}
        pieces = [card["name"]]
        need = whole(a.get("need"), 1, 20)
        if need is None:
            return {"problem": "How many must they collect? Enter a whole number from 1 to 20."}
        what = f"{need} × {card.get('label') or card['name']}"
        if need > 1 and a.get("repeat") is not False and limits.per_email_mode(card) != "unlimited":
            edits = {card["name"]: {"per_email": "unlimited"}}
    else:
        raw = a.get("cards") if isinstance(a.get("cards"), list) else []
        pieces = []
        for c in raw:
            t = _find(tiers, c)
            if t and t["name"] not in pieces:
                pieces.append(t["name"])
        if len(pieces) < 2:
            return {"problem": "Tick at least two cards for people to collect."}
        need = whole(a.get("need"), 1, len(pieces) - 1, 0) if str(a.get("need") or "").strip() else 0
        what = f"{need if need else 'all'} of {len(pieces)} cards"
    taken = _names(tiers)
    voucher = voucher_tier(title, a.get("reward_terms"), a.get("reward_days"), taken)
    name = text(a.get("name"), 60) or text(f"Collect for {title}", 60)
    s = {"name": name, "pieces": pieces, "need": need or 0, "reward": voucher["name"], "include_existing": flag(a.get("include_existing"))}
    lines = [f"Set “{name}”: collect {what}, get “{title}”", f"Voucher card “{title}” (only you give it out)"]
    if edits:
        lines.append(f"“{next(iter(edits))}” can now be got more than once by the same person (needed to collect it several times)")
    return {"tiers": [voucher], "set": s, "codes": None, "edits": edits, "lines": lines}


# ── 5. Discount or gift codes ──
def _discount(a, ctx):
    title = text(a.get("title"), 40, commas=False)
    if not title:
        return {"problem": "What is the offer? For example \"15% off your next order\" or \"One free coffee\"."}
    count = whole(a.get("count"), 1, MAX_CODES)
    if count is None:
        return {"problem": f"How many codes? Enter a whole number from 1 to {MAX_CODES}."}
    v = voucher_tier(title, a.get("terms"), a.get("days"), _names(ctx["tiers"]))
    codes = {"name": text(title, 60), "tier": v["name"], "count": count, "numbered": False, "start": 0, "size": None}
    return {"tiers": [v], "set": None, "codes": codes,
            "lines": [f"Voucher “{title}” (valid {v['expiry_days']} days after someone claims it)", f"{count} one-time codes"]}


# ── 6. Certificate ──
def _certificate(a, ctx):
    title = text(a.get("title"), 40, commas=False)
    if not title:
        return {"problem": "What is the certificate for? For example \"Completed the workshop\"."}
    cert = card_kinds.clean_cert(title, a.get("note") or "", "")
    tier = {"name": unique_name(title, _names(ctx["tiers"])), "kind": "certificate", "cert": cert, "label": title, "price": 0,
            "expiry_days": FOREVER, "sections": [], "hidden": True, "per_email": "one_ever"}
    lines = [f"Certificate “{title}” (never expires)"]
    codes = None
    if str(a.get("how") or "codes") == "codes":
        count = whole(a.get("count"), 1, MAX_CODES)
        if count is None:
            return {"problem": f"How many codes? Enter a whole number from 1 to {MAX_CODES}."}
        codes = {"name": text(title, 60), "tier": tier["name"], "count": count, "numbered": False, "start": 0, "size": None}
        lines.append(f"{count} one-time codes")
    return {"tiers": [tier], "set": None, "codes": codes, "lines": lines}
