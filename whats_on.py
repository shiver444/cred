"""
Credential Protocol: the public "What's on" page (and its calendar feed).

One plain page, /whats-on, that lists what is coming up by date, so people can
see it without signing up for anything. It is built only from things that are
already public in the sign-up list, plus the opening dates of members-only
items the creator chose to show as a locked preview ("teaser"):

  * event tickets        the event, its time and place
  * limited drops        when the drop opens (and closes)
  * vouchers             the last day of the offer
  * "On sale from"       when a card goes on sale
  * locked-preview items when an item with a fixed opening date opens
                          (never the link, the file, the note, or a mystery title)

Cards marked "only I give it out" are never listed. /whats-on.ics is the same
list as a calendar feed that Google Calendar, Apple Calendar and Outlook can
subscribe to.
"""

import hashlib
from datetime import datetime, timedelta, timezone
from html import escape as esc

import card_kinds
import timeline

MAX_ROWS = 200
ICS_DEFAULT_HOURS = 1


def _utc_or_none(local, tz):
    try:
        return card_kinds._utc(local, tz)
    except (ValueError, TypeError, KeyError):
        return None


def _row(at, end, kind, title, detail="", local="", key=""):
    return {"at": at, "end": end, "kind": kind, "title": title, "detail": detail,
            "when": card_kinds._stamp(local) if local else "", "key": key}


def entries(cfg: dict, content: dict, now=None) -> list:
    """Upcoming (or running) things, soonest first: a list of dicts with `at`/`end`
    (UTC datetimes), `kind`, `title`, `detail`, `when` (the creator's own wording)."""
    now = now or datetime.now(timezone.utc)
    rows = []
    for t in (cfg.get("tiers") or []):
        if not isinstance(t, dict) or t.get("hidden"):
            continue
        name = str(t.get("label") or t.get("name") or "").strip()
        if card_kinds.is_ticket(t):
            ev = card_kinds.event_of(t)
            if card_kinds.has_date(ev) and not card_kinds.is_over(ev, now):
                start, end = card_kinds.starts_utc(ev), card_kinds.ends_utc(ev)
                rows.append(_row(start, end, "Event", ev.get("name") or name,
                                 " · ".join(x for x in (ev.get("place"), ev.get("note")) if x),
                                 ev["starts_at"], "ev:" + str(t.get("name"))))
        elif card_kinds.is_collectible(t):
            d = card_kinds.drop_of(t)
            title = d.get("name") or name
            state = card_kinds.drop_state(d, now)
            if d["opens_at"] and state == "soon":
                rows.append(_row(_utc_or_none(d["opens_at"], d["tz"]), _utc_or_none(d["closes_at"], d["tz"]) if d["closes_at"] else None,
                                 "Drop opens", title, d.get("note", ""), d["opens_at"], "drop:" + str(t.get("name"))))
            elif d["closes_at"] and state == "open":
                rows.append(_row(_utc_or_none(d["closes_at"], d["tz"]), None, "Drop closes", title, d.get("note", ""),
                                 d["closes_at"], "dropc:" + str(t.get("name"))))
        elif card_kinds.is_voucher(t):
            v = card_kinds.voucher_of(t)
            if v["until"] and not card_kinds.voucher_ended(v, now):
                rows.append(_row(_utc_or_none(v["until"], v["tz"]), None, "Offer ends", v.get("name") or name,
                                 v.get("terms", ""), v["until"], "vo:" + str(t.get("name"))))
        if not card_kinds.is_collectible(t) and card_kinds.sale_state(t, now) == "soon":
            sale = card_kinds.sale_of(t)
            rows.append(_row(_utc_or_none(sale["at"], sale["tz"]), None, "On sale", name,
                             "", sale["at"], "sale:" + str(t.get("name"))))
    # Items of a locked preview ("teaser") that open on a fixed date.
    for sec in (content or {}).get("sections", []):
        if sec.get("type") != "links" or sec.get("teaser") is not True or sec.get("locked_view") == "mystery":
            continue
        for it in sec.get("items", []):
            o = it.get("opens") or {}
            if o.get("mode") != "date":
                continue
            at = timeline.opens_utc(it, None)
            if at is None or at <= now or (timeline.until_utc(it) is not None and timeline.until_utc(it) <= now):
                continue
            rows.append(_row(at, None, "Opens", str(it.get("title") or "").strip() or "Something new",
                             str(sec.get("title") or ""), o["at"], "item:" + str(it.get("id") or it.get("title"))))
    rows = [r for r in rows if r["at"] is not None]
    rows.sort(key=lambda r: (r["at"], r["title"]))
    return rows[:MAX_ROWS]


# ── the page ──
def _month_of(r):
    # the creator's own date text: "Tue 01 Dec 2026, 09:00" -> "Dec 2026"
    parts = r["when"].replace(",", "").split()
    return (parts[2] + " " + parts[3]) if len(parts) >= 4 else ""


def render_page(rows: list, name: str, accent: str, base: str = "", members_url: str = "") -> str:
    accent = accent if (isinstance(accent, str) and len(accent) in (4, 7) and accent.startswith("#")
                        and all(c in "0123456789abcdefABCDEF" for c in accent[1:])) else "#00e87a"
    out, last = [], None
    for r in rows:
        m = _month_of(r)
        if m != last:
            if last is not None:
                out.append("</div>")
            out.append(f'<h2>{esc(m)}</h2><div class="list">')
            last = m
        out.append('<div class="row"><div class="when">' + esc(r["when"]) + '</div><div><div class="kind">'
                   + esc(r["kind"]) + '</div><div class="title">' + esc(r["title"]) + '</div>'
                   + (f'<div class="detail">{esc(r["detail"])}</div>' if r["detail"] else "") + '</div></div>')
    if last is not None:
        out.append("</div>")
    body = "".join(out) or '<p class="none">Nothing is planned right now. Check back soon.</p>'
    feed = (esc(base.rstrip("/")) + "/whats-on.ics") if base else "/whats-on.ics"
    join = (f'<p class="join"><a href="{esc(members_url, quote=True)}">Get your card →</a></p>'
            if members_url and members_url.startswith(("http://", "https://", "/")) else "")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(name)} - What's on</title>
<style>
  :root {{ color-scheme: light dark; --bg:#f5f5f2; --fg:#1b1b1b; --muted:#6b6b66; --line:#d8d8d2; --accent:{accent}; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#101112; --fg:#ececec; --muted:#9a9a94; --line:#33363a; }} }}
  html,body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }}
  main {{ max-width:620px; margin:0 auto; padding:32px 16px 64px; }}
  h1 {{ font-size:1.4rem; margin:0 0 4px; }}
  .sub {{ color:var(--muted); margin:0 0 18px; font-size:.95rem; }}
  h2 {{ font-size:.8rem; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); margin:26px 0 8px; }}
  .row {{ display:flex; gap:16px; padding:12px 0; border-bottom:1px solid var(--line); }}
  .when {{ flex:0 0 150px; font-size:.9rem; color:var(--muted); }}
  .kind {{ font-size:.72rem; letter-spacing:.1em; text-transform:uppercase; color:var(--accent); filter:brightness(.8); }}
  .title {{ font-weight:600; overflow-wrap:anywhere; }}
  .detail {{ font-size:.9rem; color:var(--muted); overflow-wrap:anywhere; }}
  .none {{ color:var(--muted); }}
  .join a, .feed a {{ color:inherit; }}
  .feed {{ margin-top:28px; font-size:.85rem; color:var(--muted); }}
  @media (max-width:480px) {{ .row {{ flex-direction:column; gap:2px; }} .when {{ flex:none; }} }}
</style></head>
<body><main>
<h1>{esc(name)}</h1>
<p class="sub">What's on</p>
{body}
{join}
<p class="feed">Add this to your calendar: <a href="{feed}">{feed}</a></p>
</main></body></html>"""


# ── the calendar feed ──
def _ics_text(v: str) -> str:
    v = str(v or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return v.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def _fold(line: str) -> str:
    """Lines longer than 75 bytes are folded onto continuation lines (RFC 5545)."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        limit = 75 if not out else 74
        if len(cur) + len(b) > limit:
            out.append(cur.decode("utf-8"))
            cur = b
        else:
            cur += b
    out.append(cur.decode("utf-8"))
    return "\r\n ".join(out)


def _stamp_utc(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def render_ics(rows: list, name: str, now=None, host: str = "credential-protocol") -> str:
    now = now or datetime.now(timezone.utc)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Credential Protocol//Whats on//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", "X-WR-CALNAME:" + _ics_text(f"{name} - What's on")]
    for r in rows:
        end = r["end"] if (r["end"] and r["end"] > r["at"]) else r["at"] + timedelta(hours=ICS_DEFAULT_HOURS)
        uid = hashlib.sha256(f"{r['key']}|{r['kind']}|{r['at'].isoformat()}".encode()).hexdigest()[:24] + "@" + host
        title = (r["title"] + (" opens" if r["kind"] == "Opens" else "")) if r["kind"] != "Event" else r["title"]
        lines += ["BEGIN:VEVENT", "UID:" + uid, "DTSTAMP:" + _stamp_utc(now),
                  "DTSTART:" + _stamp_utc(r["at"]), "DTEND:" + _stamp_utc(end),
                  "SUMMARY:" + _ics_text(f"{r['kind']}: {title}" if r["kind"] not in ("Event", "Opens") else title)]
        if r["detail"]:
            lines.append("DESCRIPTION:" + _ics_text(r["detail"]))
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"
