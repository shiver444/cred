"""
The "Custom payment link" provider (dashboard -> Payment).

For any payment service that gives you a link to send people to — PayPal.me,
Ko-fi, Buy Me a Coffee, Gumroad, a regional or adult-friendly processor, a
payment page of your own — without this app having to know anything about it.

How it works for a member: they pick a paid tier and enter name + email, the
request is queued exactly like "Manual approval", and the widget shows your
instructions plus a "Pay with <name>" button that opens your link in a new
tab. You see the payment arrive in that service, then press Approve in the
dashboard queue — that issues the card. (A link can't confirm payment on its
own; only approving does.)

The link may contain these words in curly brackets, filled in for each person
(and made safe for a web address):

    {amount}  {currency}  {tier}  {email}  {name}  {reference}

e.g.  https://paypal.me/yourname/{amount}{currency}

Everything here is plain checking, so a bad value can never turn into a
dangerous link on the visitor's page: only http:// and https:// links are
accepted, and the part up to the first "/" (the web site itself) can't
contain a bracketed word, so a visitor's name can never decide where they
are sent.
"""

import re
from urllib.parse import quote

MAX_NAME  = 40
MAX_URL   = 500
MAX_LINKS = 3000

PLACEHOLDERS = ("amount", "currency", "tier", "email", "name", "reference")

_HOST = re.compile(r"^https?://[A-Za-z0-9.\-]+(:\d{1,5})?(?=[/?#]|$)", re.I)
_BAD  = re.compile(r"[\s\x00-\x1f\x7f<>\"'\\]")


def clean_name(value) -> str:
    """The service's name, as shown on the button ("Pay with PayPal")."""
    v = "".join(ch for ch in str(value or "") if ch >= " " and ch != "\x7f").strip()
    return v[:MAX_NAME]


def clean_url(value) -> str:
    """A link template, or "" if it is not an acceptable http(s) link."""
    v = str(value or "").strip()
    if not v or len(v) > MAX_URL or _BAD.search(v):
        return ""
    if not _HOST.match(v):
        return ""
    # whatever sits in {...} must be a known word
    for word in re.findall(r"\{([^{}]*)\}", v):
        if word not in PLACEHOLDERS:
            return ""
    if v.count("{") != v.count("}"):
        return ""
    return v


def clean_links(value) -> str:
    """The per-tier list: one `TIER NAME = https://...` per line. Lines that
    are not in that shape, or whose link is not acceptable, are dropped."""
    out = []
    for line in str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if "=" not in line:
            continue
        tier, _, url = line.partition("=")
        tier, url = tier.strip().upper(), clean_url(url)
        if tier and url and len(tier) <= 100:
            out.append(f"{tier} = {url}")
    return "\n".join(out)[:MAX_LINKS]


def parse_links(value) -> dict:
    return {t.strip(): u.strip() for t, _, u in (l.partition(" = ") for l in clean_links(value).split("\n") if l)}


def _fmt_amount(price) -> str:
    try:
        n = float(price)
    except (TypeError, ValueError):
        return "0"
    return str(int(n)) if n == int(n) else ("%.2f" % n)


def link_for(cfg: dict, tier: str, name: str, email: str, price, currency: str, reference: str) -> str:
    """The finished link for this person and tier, or "" when none is set up
    (then the member just sees your written instructions)."""
    tmpl = parse_links(cfg.get("custom_payment_links")).get(str(tier or "").strip().upper()) \
        or clean_url(cfg.get("custom_payment_url"))
    if not tmpl:
        return ""
    values = {
        "amount": _fmt_amount(price), "currency": str(currency or "").upper(),
        "tier": tier, "email": email, "name": name, "reference": reference,
    }
    return re.sub(r"\{(\w+)\}", lambda m: quote(str(values.get(m.group(1), "")), safe=""), tmpl)


def button_label(cfg: dict) -> str:
    n = clean_name(cfg.get("custom_provider_name"))
    return f"Pay with {n}" if n else "Pay now"
