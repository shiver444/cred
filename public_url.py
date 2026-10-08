"""
Credential Protocol — the Members page address

Members reach their content through a "Members page": a page that has the
widget on it. Creators with their own website put the widget there and type
that page's address in Branding. Everyone else (and anyone just testing) can
leave the field empty: the server then serves its own simple Members page at
/members, and links, emails and checkout use that.

effective_members_page() turns whatever is saved into the address to use.
"""

import os

# The sample address shipped in config.json. It's a placeholder, not a real page.
_PLACEHOLDER = "your-domain.com"


def is_real(value) -> bool:
    v = (value or "").strip()
    return bool(v) and _PLACEHOLDER not in v


def base_url() -> str:
    """This server's public address with no trailing slash ("" if unknown).

    PUBLIC_URL (if you set it) or Railway's own domain come first. They can't
    be spoofed by a visitor, which matters because this address goes into
    emails sent to other people. Only when neither exists (running on your own
    computer) is the address of the current request used."""
    explicit = (os.environ.get("PUBLIC_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    domain = (os.environ.get("RAILWAY_PUBLIC_DOMAIN") or "").strip()
    if domain:
        return f"https://{domain}"
    try:
        from flask import request, has_request_context
        if has_request_context() and request.host:
            return f"{request.scheme}://{request.host}"
    except Exception:
        pass
    return ""


def effective_members_page(saved) -> str:
    """The saved address if it's a real one, else this server's own /members page."""
    if is_real(saved):
        return saved.strip()
    base = base_url()
    return f"{base}/members" if base else ""
