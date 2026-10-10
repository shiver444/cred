"""
Credential Protocol: the list of emails a creator can edit (Settings > Emails).

This module is plain data and small helpers. It knows every email's name, when
it is sent, which settings (wording, switches) belong to it and which
{placeholders} it understands. The dashboard builds its Emails screen from it
(emails_page.py), the preview/test routes read the typed values through it, and
email_sender.py takes the default wording from it.

Every email the creator edits lives under its own settings keys in config.json:

  welcome      email_subject, email_intro, email_signoff        (older keys, unchanged)
  reminder     reminder_days, reminder_subject, reminder_text, reminder_renew_url
  extended     extended_subject, extended_text
  ticket       ticket_subject, ticket_text
  collectible  collectible_subject, collectible_text
  voucher      voucher_subject, voucher_text
  certificate  certificate_subject, certificate_text
  howtopay     howtopay_on, howtopay_subject, howtopay_text
  declined     declined_on, declined_subject, declined_text
  evremind     evremind_hours, evremind_subject, evremind_text
  alert        alert_email                                      (goes to the creator)
  lostlink     lostlink_on, lostlink_subject, lostlink_text     (a member asks for their link again)
  ended        ended_on, ended_subject, ended_text              (a card is revoked; off by default)
  follow1..5   followN_on, followN_days, followN_for, followN_subject, followN_text
                                                                (automatic follow-up emails; off by default)

The first three kinds keep the keys they always had, so nothing saved earlier
changes. A blank subject or text always means "use the standard words".
"""

# ── default wording of the newer emails ──
DEFAULT_TICKET_SUBJECT = "Your ticket for {event}"
DEFAULT_TICKET_TEXT = ("{name} — you're in! Your ticket for {event} is attached.\n"
                       "Show the QR code on it at the door.")

DEFAULT_COLLECTIBLE_SUBJECT = "You now own {drop} {edition}"
DEFAULT_COLLECTIBLE_TEXT = ("{name} — {drop} {edition} is yours. It never expires, "
                            "and it opens whatever is listed on the card.")

DEFAULT_VOUCHER_SUBJECT = "Your voucher: {offer}"
DEFAULT_VOUCHER_TEXT = ("{name} — here's your voucher: {offer}.\n"
                        "Show the QR code on it when you redeem it. It can be used once.")

DEFAULT_CERT_SUBJECT = "Your certificate: {title}"
DEFAULT_CERT_TEXT = ("{name} — congratulations! Your certificate is attached: {title}.\n"
                     "Anyone can check that it is real by scanning its QR code.")

DEFAULT_HOWTOPAY_SUBJECT = "How to pay for {tier}"
DEFAULT_HOWTOPAY_TEXT = ("{name} — thanks for asking for {tier} ({price}).\n"
                         "Your card will be sent as soon as your payment is confirmed.")

DEFAULT_DECLINED_SUBJECT = "About your {tier} request"
DEFAULT_DECLINED_TEXT = ("{name} — we couldn't confirm your payment for {tier}, so no card was issued.\n"
                         "If you think this is a mistake, just reply or get in touch with {creator}.")

DEFAULT_EVREMIND_SUBJECT = "Reminder: {event} is coming up"
DEFAULT_EVREMIND_TEXT = ("{name} — {event} starts {when}, at {place}.\n"
                         "Have your ticket ready: open it from the button below and show the QR code at the door.")

DEFAULT_LOSTLINK_SUBJECT = "Your access link"
DEFAULT_LOSTLINK_TEXT = ("{name} — here's the link you asked for. Use it to get back into your member area.\n"
                         "If you didn't ask for it, you can ignore this email.")

DEFAULT_ENDED_SUBJECT = "Your {tier} access has ended"
DEFAULT_ENDED_TEXT = ("{name} — your {tier} access with {creator} has ended.\n"
                      "If you think this is a mistake, just reply or get in touch with {creator}.")

# Follow-up emails: up to FOLLOW_STEPS automatic notes, each sent N days after
# someone joins (off until switched on). Each can be limited to one card type.
FOLLOW_STEPS = 5
FOLLOW_DAY_CHOICES = (1, 2, 3, 5, 7, 10, 14, 21, 30, 45, 60, 90)
FOLLOW_DEFAULT_DAYS = (1, 3, 7, 14, 30)
FOLLOW_DEFAULTS = (
    ("Welcome to {brand}",
     "{name} — glad you're here. You can open your member area any time from the button below; "
     "everything you have access to is listed there."),
    ("A few things to try",
     "{name} — a quick nudge from {creator}: have a look around your member area, there may be "
     "something you haven't opened yet."),
    ("How's it going?",
     "{name} — you've been with {brand} for a little while now. If you have a question or an idea, "
     "just reply to this email."),
    ("Something you might have missed",
     "{name} — here's a reminder that your {tier} card is waiting for you. Pop back in whenever you like."),
    ("A month with {brand}",
     "{name} — thank you for being part of {brand}. If there is anything you'd like to see more of, "
     "just reply and tell {creator}."),
)
FOLLOW_WINDOW_DAYS = 3        # a step is only sent within this many days after it falls due
FOLLOW_MAX_PER_RUN = 40       # per hourly check, so a big batch never floods the email service

MAX_SUBJECT = 150
MAX_TEXT = 1000

# The "send it N hours before" choices for the event reminder (0 = off).
EVREMIND_CHOICES = (0, 3, 12, 24, 48)
DEFAULT_EVREMIND_HOURS = 24
EVREMIND_LABELS = {0: "Off", 3: "3 hours before", 12: "12 hours before", 24: "1 day before", 48: "2 days before"}

GROUPS = (
    ("cards",    "When someone gets a card"),
    ("payments", "Payments"),
    ("reminders", "Reminders"),
    ("follow",   "Follow-up emails (sent automatically after someone joins)"),
    ("other",    "Other"),
)

CHIPS_MEMBER = ("name", "tier", "creator", "brand")


def clean_evremind_hours(value) -> int:
    """One of EVREMIND_CHOICES. Blank, junk or anything else falls back to the
    default (a day before); only an explicit 0 means off."""
    try:
        n = int(str(value).strip())
    except (ValueError, TypeError):
        return DEFAULT_EVREMIND_HOURS
    return n if n in EVREMIND_CHOICES else DEFAULT_EVREMIND_HOURS


def clean_on(value, default=True) -> str:
    """"1" or "0" (the dashboard sends the on/off choice as a menu)."""
    v = str(value if value is not None else "").strip()
    if v in ("1", "0"):
        return v
    return "1" if default else "0"


def clean_follow_days(value, default=3) -> int:
    """One of FOLLOW_DAY_CHOICES; anything else falls back to the step's own default."""
    try:
        n = int(str(value).strip())
    except (ValueError, TypeError):
        return default
    return n if n in FOLLOW_DAY_CHOICES else default


def clean_follow_for(value) -> str:
    """Which card a follow-up is for: "" = every card, otherwise a card name."""
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())[:80]


def follow_steps(cfg: dict) -> list:
    """The follow-ups that are switched on: [{"n", "days", "for"}], earliest first."""
    out = []
    for n in range(1, FOLLOW_STEPS + 1):
        if clean_on((cfg or {}).get("follow%d_on" % n), False) != "1":
            continue
        out.append({"n": n, "for": clean_follow_for((cfg or {}).get("follow%d_for" % n)),
                    "days": clean_follow_days((cfg or {}).get("follow%d_days" % n), FOLLOW_DEFAULT_DAYS[n - 1])})
    return sorted(out, key=lambda x: (x["days"], x["n"]))


def clean_alert_email(value) -> str:
    """The address for "a payment is waiting" alerts, or "" if it isn't a plain address."""
    v = str(value or "").strip()[:254]
    if not v:
        return ""
    if "@" not in v[1:] or any(c in v for c in " \r\n<>,;\"'"):
        return ""
    local, _, domain = v.rpartition("@")
    return v if local and "." in domain and not domain.startswith(".") and not domain.endswith(".") else ""


def _f(name, label, type="text", maxlen=MAX_TEXT, default="", options=None, clean=None, hint=""):
    return {"name": name, "label": label, "type": type, "maxlen": maxlen,
            "default": default, "options": options, "clean": clean, "hint": hint}


def registry() -> list:
    """Every editable email, in the order the dashboard lists them."""
    import email_sender as es
    import reminders
    return [
        {"key": "welcome", "group": "cards", "title": "Welcome (membership)",
         "when": "Sent with the card when someone gets a membership.",
         "chips": CHIPS_MEMBER + ("expires",), "state": None,
         "fields": [
             _f("email_subject", "Subject", "text", es.MAX_SUBJECT, es.DEFAULT_SUBJECT),
             _f("email_intro", "Message", "area", es.MAX_INTRO, es.DEFAULT_INTRO),
             _f("email_signoff", "Sign-off (optional, like “See you inside. — {creator}”)", "area", es.MAX_SIGNOFF, ""),
         ],
         "note": "The card, the signed bundle and their personal access link are always included."},
        {"key": "ticket", "group": "cards", "title": "Ticket confirmation",
         "when": "Sent with the ticket instead of the Welcome email.",
         "chips": CHIPS_MEMBER + ("event", "when", "place"), "state": None,
         "fields": [
             _f("ticket_subject", "Subject", "text", MAX_SUBJECT, DEFAULT_TICKET_SUBJECT),
             _f("ticket_text", "Message", "area", MAX_TEXT, DEFAULT_TICKET_TEXT),
         ],
         "note": "The ticket, the event, the time and the place are always included."},
        {"key": "collectible", "group": "cards", "title": "Collectible claimed",
         "when": "Sent with the collectible instead of the Welcome email.",
         "chips": CHIPS_MEMBER + ("drop", "edition"), "state": None,
         "fields": [
             _f("collectible_subject", "Subject", "text", MAX_SUBJECT, DEFAULT_COLLECTIBLE_SUBJECT),
             _f("collectible_text", "Message", "area", MAX_TEXT, DEFAULT_COLLECTIBLE_TEXT),
         ],
         "note": "{edition} becomes the number, like “#37 of 100”."},
        {"key": "voucher", "group": "cards", "title": "Voucher",
         "when": "Sent with the voucher instead of the Welcome email.",
         "chips": CHIPS_MEMBER + ("offer", "until"), "state": None,
         "fields": [
             _f("voucher_subject", "Subject", "text", MAX_SUBJECT, DEFAULT_VOUCHER_SUBJECT),
             _f("voucher_text", "Message", "area", MAX_TEXT, DEFAULT_VOUCHER_TEXT),
         ],
         "note": "The voucher and its offer are always included. {until} is the date it stops working (empty if it has no end date)."},
        {"key": "certificate", "group": "cards", "title": "Certificate",
         "when": "Sent with the certificate instead of the Welcome email.",
         "chips": CHIPS_MEMBER + ("title",), "state": None,
         "fields": [
             _f("certificate_subject", "Subject", "text", MAX_SUBJECT, DEFAULT_CERT_SUBJECT),
             _f("certificate_text", "Message", "area", MAX_TEXT, DEFAULT_CERT_TEXT),
         ],
         "note": "The certificate is attached and the button opens it."},
        {"key": "howtopay", "group": "payments", "title": "How to pay",
         "when": "Sent the moment someone asks for a paid card and pays by hand or with your own link.",
         "chips": CHIPS_MEMBER + ("price", "reference"), "state": "on",
         "fields": [
             _f("howtopay_on", "Send this email?", "select", 1, "1", options=(("1", "Yes"), ("0", "No")),
                clean=lambda v: clean_on(v, True)),
             _f("howtopay_subject", "Subject", "text", MAX_SUBJECT, DEFAULT_HOWTOPAY_SUBJECT),
             _f("howtopay_text", "Message", "area", MAX_TEXT, DEFAULT_HOWTOPAY_TEXT),
         ],
         "note": "Your “Message to the member” from Payment, the pay button (if you set a link) and their reference are added automatically."},
        {"key": "declined", "group": "payments", "title": "Payment not confirmed",
         "when": "Sent when you press Reject on a payment waiting for your OK.",
         "chips": CHIPS_MEMBER + ("price", "reference"), "state": "on",
         "fields": [
             _f("declined_on", "Send this email?", "select", 1, "1", options=(("1", "Yes"), ("0", "No")),
                clean=lambda v: clean_on(v, True)),
             _f("declined_subject", "Subject", "text", MAX_SUBJECT, DEFAULT_DECLINED_SUBJECT),
             _f("declined_text", "Message", "area", MAX_TEXT, DEFAULT_DECLINED_TEXT),
         ],
         "note": ""},
        {"key": "alert", "group": "payments", "title": "New payment waiting (to you)",
         "when": "Sent to you when someone asks for a paid card, so a payment never sits unnoticed.",
         "chips": (), "state": "alert",
         "fields": [
             _f("alert_email", "Send it to this address (empty = off)", "text", 254, "", clean=clean_alert_email),
         ],
         "note": "This one is for you, not for members. Its wording is fixed."},
        {"key": "reminder", "group": "reminders", "title": "Access ends soon",
         "when": "Sent a few days before a membership ends.",
         "chips": CHIPS_MEMBER + ("expires", "days"), "state": "days",
         "fields": [
             _f("reminder_days", "Days before access ends to send it (0 = off)", "number", 2, "0",
                clean=reminders.clean_reminder_days),
             _f("reminder_subject", "Subject", "text", es.MAX_REMINDER_SUBJECT, es.DEFAULT_REMINDER_SUBJECT),
             _f("reminder_text", "Message", "area", es.MAX_REMINDER_TEXT, es.DEFAULT_REMINDER_TEXT),
             _f("reminder_renew_url", "Renew link (optional, adds a “Renew” button)", "url", es.MAX_RENEW_URL, "",
                clean=es.safe_renew_url),
         ],
         "note": "Memberships that last no longer than this are not reminded. Tickets never get this one."},
        {"key": "evremind", "group": "reminders", "title": "Event reminder",
         "when": "Sent to ticket holders shortly before the event starts.",
         "chips": CHIPS_MEMBER + ("event", "when", "place"), "state": "hours",
         "fields": [
             _f("evremind_hours", "Send it", "select", 3, str(DEFAULT_EVREMIND_HOURS),
                options=tuple((str(h), EVREMIND_LABELS[h]) for h in EVREMIND_CHOICES), clean=clean_evremind_hours),
             _f("evremind_subject", "Subject", "text", MAX_SUBJECT, DEFAULT_EVREMIND_SUBJECT),
             _f("evremind_text", "Message", "area", MAX_TEXT, DEFAULT_EVREMIND_TEXT),
         ],
         "note": "Tickets already checked in, and tickets bought too late for the reminder, don't get one."},
        {"key": "extended", "group": "reminders", "title": "Access extended",
         "when": "Sent when you press Extend on the Members page (with “email them” ticked).",
         "chips": CHIPS_MEMBER + ("expires", "days"), "state": None,
         "fields": [
             _f("extended_subject", "Subject", "text", es.MAX_EXTENDED_SUBJECT, es.DEFAULT_EXTENDED_SUBJECT),
             _f("extended_text", "Message", "area", es.MAX_EXTENDED_TEXT, es.DEFAULT_EXTENDED_TEXT),
         ],
         "note": "Their access link is always included."},
        {"key": "lostlink", "group": "other", "title": "Lost link (member asks)",
         "when": "Sent when someone presses “Lost your link? Email it to me” in your widget.",
         "chips": ("name", "creator", "brand"), "state": "on",
         "fields": [
             _f("lostlink_on", "Offer “Email me my link” in the widget?", "select", 1, "1", options=(("1", "Yes"), ("0", "No")),
                clean=lambda v: clean_on(v, True)),
             _f("lostlink_subject", "Subject", "text", MAX_SUBJECT, DEFAULT_LOSTLINK_SUBJECT),
             _f("lostlink_text", "Message", "area", MAX_TEXT, DEFAULT_LOSTLINK_TEXT),
         ],
         "note": "They only get it if that address has a card that still works. The widget always answers the same way, so nobody can find out who is a member. Needs email set up."},
        {"key": "ended", "group": "other", "title": "Access ended",
         "when": "Sent to a member when you revoke their card on the Members page.",
         "chips": CHIPS_MEMBER, "state": "on",
         "fields": [
             _f("ended_on", "Send this email?", "select", 1, "0", options=(("1", "Yes"), ("0", "No")),
                clean=lambda v: clean_on(v, False)),
             _f("ended_subject", "Subject", "text", MAX_SUBJECT, DEFAULT_ENDED_SUBJECT),
             _f("ended_text", "Message", "area", MAX_TEXT, DEFAULT_ENDED_TEXT),
         ],
         "note": "Off unless you switch it on. Think about whether you want to tell someone, before you turn it on."},
    ] + _follow_kinds()


def _follow_kinds() -> list:
    out = []
    for n in range(1, FOLLOW_STEPS + 1):
        subj, text = FOLLOW_DEFAULTS[n - 1]
        dd = FOLLOW_DEFAULT_DAYS[n - 1]
        out.append({
            "key": "follow%d" % n, "group": "follow", "title": "Follow-up %d" % n,
            "when": "Sent automatically some days after someone joins. Off until you switch it on.",
            "chips": CHIPS_MEMBER, "state": "follow",
            "fields": [
                _f("follow%d_on" % n, "Send this follow-up?", "select", 1, "0", options=(("1", "Yes"), ("0", "No")),
                   clean=lambda v: clean_on(v, False)),
                _f("follow%d_days" % n, "Send it", "select", 3, str(dd),
                   options=tuple((str(d), ("1 day" if d == 1 else "%d days" % d) + " after they join") for d in FOLLOW_DAY_CHOICES),
                   clean=lambda v, dd=dd: clean_follow_days(v, dd)),
                _f("follow%d_for" % n, "Send it to", "tier", 80, "", clean=clean_follow_for),
                _f("follow%d_subject" % n, "Subject", "text", MAX_SUBJECT, subj),
                _f("follow%d_text" % n, "Message", "area", MAX_TEXT, text),
            ],
            "note": ("Each person gets it once, from their own join date. It stops if their card is revoked or has ended, "
                     "and every email has a “stop these emails” link. Only people who joined in the last few days before "
                     "it fell due are sent it, so switching it on never emails your whole old list at once."
                     if n == 1 else "Same rules as Follow-up 1: once per person, from their join date, with a “stop these emails” link."),
        })
    return out


def kind_of(key):
    return next((k for k in registry() if k["key"] == key), None)


# Newer emails only: their settings are saved by clean_new_from_form().
NEW_KEYS = ("ticket", "collectible", "voucher", "certificate", "howtopay", "declined", "evremind", "alert", "lostlink", "ended") + tuple(
    "follow%d" % n for n in range(1, FOLLOW_STEPS + 1))


def values_for(cfg: dict) -> dict:
    """What every field currently holds, for the dashboard: the saved value, or
    the standard wording when nothing was saved."""
    out = {}
    for k in registry():
        for f in k["fields"]:
            raw = cfg.get(f["name"])
            if f["type"] == "select":
                out[f["name"]] = str(f["clean"](raw if raw is not None else f["default"]))
            elif f["type"] == "tier":
                out[f["name"]] = clean_follow_for(raw)
            elif f["type"] == "number":
                out[f["name"]] = str(f["clean"](raw) if f["clean"] else (raw or 0))
            elif f["name"] in ("reminder_renew_url", "alert_email"):
                out[f["name"]] = str(raw or "")
            else:
                s = str(raw if raw is not None else "")
                out[f["name"]] = s if s.strip() else f["default"]
    return out


def new_values(cfg: dict) -> dict:
    """values_for(), limited to the newer emails (the older ones are read by their own code)."""
    names = {f["name"] for k in registry() if k["key"] in NEW_KEYS for f in k["fields"]}
    return {n: v for n, v in values_for(cfg).items() if n in names}


def is_edited(kind: dict, values: dict) -> bool:
    """True when any of the wording (subject/message/sign-off) differs from the standard words."""
    for f in kind["fields"]:
        if f["type"] in ("text", "area") and f["default"] and f["name"] not in ("alert_email",):
            if (values.get(f["name"]) or "").strip() not in ("", f["default"].strip()):
                return True
        if f["name"] in ("email_signoff",) and (values.get(f["name"]) or "").strip():
            return True
    return False


def state_text(kind: dict, values: dict) -> tuple:
    """(label, on) for a row on the Emails screen. `on` is False when the email is switched off."""
    mode = kind.get("state")
    if mode == "on":
        f0 = kind["fields"][0]
        on = clean_on(values.get(f0["name"]), f0["default"] == "1") == "1"
        return ("On" if on else "Off"), on
    if mode == "days":
        n = reminders_days(values)
        return (("On · %d day%s before" % (n, "" if n == 1 else "s")) if n else "Off"), bool(n)
    if mode == "hours":
        h = clean_evremind_hours(values.get("evremind_hours"))
        return (("On · " + EVREMIND_LABELS[h].lower()) if h else "Off"), bool(h)
    if mode == "follow":
        n = int(kind["key"][6:])
        if clean_on(values.get("follow%d_on" % n), False) != "1":
            return "Off", False
        d = clean_follow_days(values.get("follow%d_days" % n), FOLLOW_DEFAULT_DAYS[n - 1])
        who = clean_follow_for(values.get("follow%d_for" % n))
        return "On · day %d%s" % (d, " · " + who if who else ""), True
    if mode == "alert":
        a = clean_alert_email(values.get("alert_email"))
        return (("On · " + a) if a else "Off · add your address"), bool(a)
    return "Always sent", True


def reminders_days(values) -> int:
    import reminders
    return reminders.clean_reminder_days(values.get("reminder_days"))


def overrides_from_data(key: str, data: dict) -> dict:
    """The typed (maybe unsaved) values of one email, from a preview/test
    request. Only that email's own fields are read, each capped in length."""
    k = kind_of(key)
    if not k:
        return {}
    out = {}
    for f in k["fields"]:   # a field not sent counts as empty = the standard words
        out[f["name"]] = str(data.get(f["name"]) or "")[:max(f["maxlen"] * 2, 8)]
    return out


def clean_new_from_form(form, saved_cfg: dict) -> dict:
    """The settings of the newer emails from the dashboard form, cleaned. A
    field the form didn't send keeps its saved value, so a save from a page
    that doesn't have this screen can't wipe anything."""
    out = {}
    for k in registry():
        if k["key"] not in NEW_KEYS:
            continue
        for f in k["fields"]:
            n = f["name"]
            if n not in form:
                if n in saved_cfg:
                    out[n] = saved_cfg[n]
                continue
            raw = form.get(n)
            if f["type"] == "select":
                out[n] = f["clean"](raw)
            elif f["clean"]:
                out[n] = f["clean"](raw)
            else:
                out[n] = str(raw or "").strip()[:f["maxlen"]]
    return out
