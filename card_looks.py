"""
Credential Protocol — card looks

A "look" is a saved, named card design: title, accent color, style, logo,
barcode on/off and an optional background picture. The creator makes as many
as they like (up to MAX_LOOKS) on the dashboard's "Card looks" screen and then
picks one for each tier. The Branding settings are the "Default look": any
field a look leaves blank follows the default.

Looks live in the live settings (config.json on the Volume) under
"card_looks", so backups and restores carry them without extra work. Anything
read back from the file is cleaned again here, so a hand-edited settings file
can't put an unsafe color or picture into a card page.

Older settings kept a card design inside each tier ("design"). migrate_tier_designs()
turns those into looks once, without changing how any card looks.
"""

import re
import secrets

from logo_utils import is_logo_data_uri

MAX_LOOKS   = 12
MAX_NAME    = 40
MAX_TITLE   = 60
MAX_LABEL   = 40

STYLES      = ("distressed", "clean", "holographic", "minimal", "ticket", "gradient", "neon")
STYLE_NAMES = {
    "distressed":  "Distressed: worn keycard",
    "clean":       "Clean: smooth and unworn",
    "holographic": "Holographic: rainbow sheen",
    "minimal":     "Minimal: light paper",
    "ticket":      "Ticket: notches and a tear line",
    "gradient":    "Gradient: wash of your color",
    "neon":        "Neon: glowing outline",
}
QR_STYLES   = ("solid", "blend", "off")
QR_NAMES    = {
    "solid": "Solid: white square (easiest to scan)",
    "blend": "Blended: see-through, melts into the picture",
    "off":   "Hidden: no QR code on the card",
}
DIMS        = ("none", "soft", "medium", "strong")
DIM_NAMES   = {"none": "Not at all", "soft": "A little", "medium": "Some (recommended)", "strong": "A lot"}
DEFAULT_DIM = "medium"

_ID    = re.compile(r"^[a-f0-9]{12}$")
_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

# Names that would be confused with the built-in default entry.
_RESERVED = ("default", "default look")


def new_id(existing=()) -> str:
    taken = {l.get("id") for l in existing}
    while True:
        i = secrets.token_hex(6)
        if i not in taken:
            return i


def clean_name(value) -> str:
    return " ".join(str(value or "").split())[:MAX_NAME]


def clean_color(value) -> str:
    v = str(value or "").strip()
    return v if _COLOR.match(v) else ""


def clean_look(raw):
    """One look as stored on disk -> a safe, complete look, or None if it has
    no usable id. Missing or unusable fields become blank ("same as default")."""
    if not isinstance(raw, dict):
        return None
    lid = str(raw.get("id") or "")
    if not _ID.match(lid):
        return None
    style = raw.get("card_style")
    dim = raw.get("bg_dim")
    return {
        "id":            lid,
        "name":          clean_name(raw.get("name")) or "My look",
        "card_title":    " ".join(str(raw.get("card_title") or "").split())[:MAX_TITLE],
        "accent_color":  clean_color(raw.get("accent_color")),
        "card_label":    " ".join(str(raw.get("card_label") or "").split())[:MAX_LABEL],
        "card_style":    style if style in STYLES else "",
        "qr_style":      raw.get("qr_style") if raw.get("qr_style") in QR_STYLES else "",
        "show_barcode":  raw.get("show_barcode", True) is not False,
        "logo_data_uri": raw.get("logo_data_uri") if is_logo_data_uri(raw.get("logo_data_uri")) else "",
        "bg_data_uri":   raw.get("bg_data_uri") if is_logo_data_uri(raw.get("bg_data_uri")) else "",
        "bg_dim":        dim if dim in DIMS else DEFAULT_DIM,
    }


def clean_looks(raw) -> list:
    """The stored list -> a clean list: bad entries dropped, ids unique, at most MAX_LOOKS."""
    out, seen = [], set()
    for item in (raw if isinstance(raw, list) else []):
        look = clean_look(item)
        if look and look["id"] not in seen:
            seen.add(look["id"])
            out.append(look)
        if len(out) >= MAX_LOOKS:
            break
    return out


def get(looks, look_id):
    if not look_id:
        return None
    return next((l for l in looks if l.get("id") == look_id), None)


def name_problem(looks, name, own_id=None):
    """None if `name` is fine for a look, else a short reason."""
    if not name:
        return "Give the look a name."
    if name.lower() in _RESERVED:
        return "That name is used by the built-in default look. Pick another."
    for l in looks:
        if l["id"] != own_id and l["name"].lower() == name.lower():
            return f"You already have a look called \"{l['name']}\"."
    return None


def unique_name(looks, base) -> str:
    """`base`, or `base 2`, `base 3`... whichever isn't taken."""
    base = clean_name(base) or "My look"
    if base.lower() in _RESERVED:
        base = base + " 2"
    names = {l["name"].lower() for l in looks}
    if base.lower() not in names:
        return base
    n = 2
    while True:
        tail = f" {n}"
        cand = base[:MAX_NAME - len(tail)] + tail
        if cand.lower() not in names:
            return cand
        n += 1


def users_of(look_id, tiers) -> list:
    return [t.get("name", "") for t in (tiers or []) if t.get("look") == look_id]


def summary(look, tiers) -> dict:
    """What the dashboard needs to list a look (never the pictures themselves)."""
    return {
        "id":           look["id"],
        "name":         look["name"],
        "card_title":   look["card_title"],
        "accent_color": look["accent_color"],
        "card_label":   look["card_label"],
        "card_style":   look["card_style"],
        "qr_style":     look["qr_style"],
        "show_barcode": look["show_barcode"],
        "has_logo":     bool(look["logo_data_uri"]),
        "has_bg":       bool(look["bg_data_uri"]),
        "bg_dim":       look["bg_dim"],
        "used_by":      users_of(look["id"], tiers),
    }


def from_design(design, looks, name) -> dict:
    """A tier's old-style `design` block -> a look (named uniquely among `looks`)."""
    design = design if isinstance(design, dict) else {}
    return clean_look({
        "id":            new_id(looks),
        "name":          unique_name(looks, name),
        "card_title":    design.get("card_title"),
        "accent_color":  design.get("accent_color"),
        "card_label":    design.get("card_label"),
        "card_style":    design.get("card_style"),
        "show_barcode":  design.get("show_barcode", True),
        "logo_data_uri": design.get("logo_data_uri"),
    })


def migrate_tier_designs(raw_cfg: dict) -> bool:
    """Turn every tier's old `design` block into a look and point the tier at
    it. Changes `raw_cfg` in place; True if anything changed. Safe to run
    again: tiers that already use a look, or never had a design, are left alone.
    If the MAX_LOOKS limit would be passed, the remaining designs stay as they
    are (they keep working: see resolve in credential_api.py)."""
    tiers = raw_cfg.get("tiers")
    if not isinstance(tiers, list):
        return False
    looks = clean_looks(raw_cfg.get("card_looks"))
    changed = False
    for t in tiers:
        if not isinstance(t, dict) or "design" not in t:
            continue
        design = t.get("design")
        if t.get("look") and get(looks, t.get("look")):
            t.pop("design", None)          # a look already wins; the old block is dead weight
            changed = True
            continue
        if not isinstance(design, dict) or not design:
            t.pop("design", None)
            changed = True
            continue
        if len(looks) >= MAX_LOOKS:
            continue
        label = str(t.get("label") or t.get("name") or "Tier").strip()
        look = from_design(design, looks, f"{label} look")
        looks.append(look)
        t["look"] = look["id"]
        t.pop("design", None)
        changed = True
    if changed:
        raw_cfg["card_looks"] = looks
    return changed
