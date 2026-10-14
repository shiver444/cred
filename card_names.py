"""
Credential Protocol: readable file names for the cards people download or get by email.

A card used to be saved as collectible_<64 random letters and numbers>.html. Now it is named for what it is:
Midnight-Sessions-No-7.html, Halloween-Live-ticket.html, Free-coffee-voucher.html, Acme-Gold-membership.html.
Only letters, numbers and dashes are kept (any language), so the name is safe on every computer.
"""

import re

MAX_PART = 40
MAX_STEM = 80


def slug(text, limit: int = MAX_PART) -> str:
    """`text` as one safe file-name piece: words joined by dashes, nothing else."""
    s = re.sub(r"[^\w]+", "-", str(text or ""), flags=re.UNICODE).replace("_", "-")
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:limit].strip("-")


def _edition(drop) -> int:
    try:
        return max(0, int((drop or {}).get("edition") or 0))
    except (ValueError, TypeError):
        return 0


def stem(kind, tier_label="", card_title="", event=None, drop=None, detail=None, credential_id="") -> str:
    """The file name without its ending. `kind` is "ticket", "collectible", "voucher", "certificate" or anything else
    (a membership). Falls back to the kind's own word (and a short piece of the id) when nothing else is known."""
    event, drop, detail = event or {}, drop or {}, detail or {}
    if kind == "ticket":
        parts = [event.get("name") or tier_label, "ticket"]
    elif kind == "collectible":
        n = _edition(drop)
        parts = [drop.get("name") or tier_label, ("No-%d" % n) if n else "collectible"]
    elif kind == "voucher":
        parts = [detail.get("name") or tier_label, "voucher"]
    elif kind == "certificate":
        parts = [detail.get("title") or tier_label, "certificate"]
    else:
        title = card_title if slug(card_title) != slug(tier_label) else ""
        parts = [title, tier_label, "membership"]
    pieces, seen = [], set()
    for p in parts:
        s = slug(p)
        if s and s.lower() not in seen:
            pieces.append(s); seen.add(s.lower())
    out = "-".join(pieces)[:MAX_STEM].strip("-")
    if not out or out.lower() in ("ticket", "collectible", "voucher", "certificate", "membership"):
        tail = slug(credential_id, 8)
        out = "-".join(x for x in (out or (kind if kind in ("ticket", "collectible", "voucher", "certificate") else "membership"), tail) if x)
    return out


def card_file(kind, tier_label="", card_title="", event=None, drop=None, detail=None, credential_id="") -> str:
    return stem(kind, tier_label, card_title, event, drop, detail, credential_id) + ".html"


def bundle_file(kind, tier_label="", card_title="", event=None, drop=None, detail=None, credential_id="") -> str:
    """The signed backup copy that comes with the email."""
    return stem(kind, tier_label, card_title, event, drop, detail, credential_id) + "-signed-copy.zip"
