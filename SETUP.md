# Credential Protocol — Setup

This is the generic template: a signed, revocation-respecting membership/
credential system. Everything a specific deployment needs to customize —
name, branding, tiers, pricing, content — is edited in the admin dashboard
(saved to two starter files, `config.json` and `content.json`, plus
environment variables). Nothing about
any one creator is hardcoded in the Python/JS engine.

## 1. Install dependencies

```
pip install -r requirements.txt
```

## 2. The signing keypair — generated for you automatically

Every deployment needs its own ECDSA keypair, and nothing to do here: the
app generates one itself, the first time it boots with none present, and
reuses that same one forever after — never regenerating it on a later
restart or redeploy. It's never committed to git (`.gitignore` already
excludes it) and never shared between deployments.

The one thing that matters: this key lives in `DATA_DIR`, not next to the
code — because a `git push` rebuilds the code checkout from scratch every
time (that's what makes Railway's auto-deploy auto-deploy), so anything
living next to the code instead of in `DATA_DIR` would vanish on every
redeploy. If the key vanished and a new one silently generated in its
place, every previously-issued credential's signature would stop
verifying with no warning. So: **`DATA_DIR` must point at real persistent
storage (a Railway Volume) before you issue a single real credential** —
see step 8. Running locally without `DATA_DIR` set is fine for poking
around, since the key just lives in a local `keys/` folder next to the
code and nothing's being redeployed anyway.

Want to generate (and back up) the key yourself ahead of time instead of
letting the app do it on first boot? `python create_keys.py` still works,
writing to the same place the app would — but never run it against a
`DATA_DIR` that already has issued credentials, since overwriting an
existing key breaks verification for everything signed with the old one.

## 3. Fill in `config.json` — or do it after deploying, through `/admin/dashboard`

```json
{
  "creator_name": "...",      // shown on cards, emails, admin page
  "card_title": "...",        // the headline brand name
  "accent_color": "#...",     // used on the card, email, admin page, and the member widget
  "members_page": "",         // optional: leave empty to use the page this server makes (/members)
  "tiers": [ ... ]            // your actual pricing/tier structure
}
```

You don't have to hand-edit this file — once deployed, `/admin/dashboard`
(step 5 below covers logging in) edits all of this through a form.

**Where your settings actually live.** The `config.json` in the repo is
only the *starting* copy. The first time you save in the dashboard, your
settings are written to `config.json` inside your persistent storage
(`DATA_DIR` — the Railway Volume in production), and from then on that
copy is the one the app reads. That's deliberate: Railway rebuilds the
code from GitHub on every push, so settings stored next to the code would
be reset every time you deployed. Two things follow from this:

- Changing settings in the dashboard survives redeploys. 
- Once you've saved in the dashboard even once, editing the repo's
  `config.json` no longer changes anything on the live site — use the
  dashboard. (Running locally with no `DATA_DIR` set, both are the same
  file, so editing it by hand still works there.)

This also holds your saved card looks and their uploaded pictures. Your
members-only content (step 4) is stored the same way.

### Card kinds: Membership, Event ticket, Limited drop, Voucher or Certificate

Every card is one box on the **Cards** screen. Press **+ New card** and pick what
kind it is (you can also change the **Kind of card** later):

- **Membership** (the default, and what every tier was before): access for a
  number of days that unlocks your members-only content.
- **Event ticket**: for one event. The **Days** box turns into "Until the event
  ends" and the box shows the event's details:
  **Event name**, **Starts**, **Ends** (optional), **Place** and a **Note on the
  ticket** (a seat, "doors 19:00"...). Type the times in your own time zone.
- **Limited drop** (a collectible): a limited-edition drop (an exclusive photo set, an album, a
  single, a one-day-only release). See "Collectibles" below.
- **Voucher**: an offer that can be used once ("One free coffee", "20% off"). Fill in
  **The offer** (shown big on the card), optional **Terms** ("Any size, any day") and,
  if you like, **Valid until** (a fixed date; when it is set it wins over the **Days** box).
  Your staff redeem it on the **Check-in** page, exactly like a ticket, and then it stops working.
  Once a fixed end date has passed nobody can get that voucher any more.
- **Certificate**: a named certificate or badge ("Completed the course", "Volunteer 2026").
  Write **What it is for**, an optional note and the line at the bottom. It carries the
  person's name, never expires, and anyone can check it is real by scanning its QR code.
  It cannot be redeemed or extended.

For a voucher or certificate you often want to hand them out yourself rather than list them
for everyone: open **Advanced** and choose **Only me** under "Who can get this card?". The card then
does not appear in the sign-up list, and you give it out with **People > Send a card**
(a new certificate starts as "Only me").

A ticket card shows the event, the time, the place and the note in place of the
plain "access class" row, says "Event Ticket" under the title and a small line
at the bottom, and has no barcode strip. That bottom line is yours to write
(**Line at the bottom of the ticket**, up to 40 characters; left empty it says
"Show this at the door", e.g. "Doors 19:00" or "Bring ID"). Tick **Show the
price on the ticket** (off by default) to add a PRICE row; free tickets never
show one. Limited drops have the same kind of bottom line (default "Limited
edition"). Its look (style, colors, background
picture) is chosen the same way as for any other tier; in the Card looks editor
use **Show as an event ticket** above the preview to see a look as a ticket.

A ticket works until the event ends (or 12 hours after it starts if you left
**Ends** empty); after that it shows as expired. Nobody can get a ticket to an
event that has already ended. Tickets can be free or paid, they go through the same
sign-up, payment and approval steps as any tier, and the tier's sections still
unlock content if you want a ticket to include some (a stream link, a download).
Tickets never get the "your access is ending" reminder, and the event details
are part of what is signed into the card.

**Check-in (at the door or counter).** Open it from the big **Check-in at the door** button at the top of **Home**, or from **People**, the **Check-in** tab (it appears once you
have an event ticket or a voucher card) opens a page for the door. Press **Scan with the camera** and point it at a ticket's QR
code, or paste the ticket's link or code. A good ticket is checked off right away
and the page shows a big green **Let in** with the name and event; a ticket that
was already used, cancelled or expired shows a red reason. The page counts how many
tickets of each event are checked in. If you checked someone in by mistake, press
**Undo**. A ticket that has been used no longer opens its content or its card, and
the member's own page tells them "This ticket has already been used". On the
Members screen a ticket shows **Mark as used** / **Undo check-in** buttons too, and
"Only look, don't mark the ticket as used" on the Check-in page lets you test a
ticket without using it. For a voucher the same page says **Redeemed**, and **Undo (used by mistake)** brings it back. (The camera needs a phone or computer browser that allows
camera use for this site; if it can't, paste the link instead.)

### Limits per tier: spots and one card per email

Each card box on the **Cards** screen has the limits: **Max members** sits in the main grid, and an **Advanced** fold holds the other two. (An event ticket also shows the event details in its box, see below.)

- **Max members** — leave blank for no limit. With a number, the tier shows
  as "Sold out" in the signup widget once it's full, and anyone who still
  tries gets a "sold out" message. Spots in use = members whose card is still
  active (not revoked, not expired) **plus** paid requests waiting for your
  approval, so you can't oversell while requests sit in the queue. When a card
  expires or you revoke it, that spot opens again. The dashboard shows
  "Right now: 12 of 50 spots in use."
- **Show visitors how many spots are left** — "12 left" in the widget, or hide
  the number and only show "Sold out" when it's full.
- **Cards per email address** — *One working card at a time* (the default):
  an email can't sign up again for a tier while it still has a working card
  or a request waiting. *Only one ever* is right for a free trial: an email
  can't get a second card for that tier even after the first expires or is
  revoked. *No limit* turns the check off. This applies per tier, so someone
  on Member can still sign up for VIP.

The email check ignores capital letters, a "+tag" (`pat+1@x.com` counts as
`pat@x.com`) and, for Gmail, dots. It stops casual repeat sign-ups, not a
determined person with many different addresses.

Good to know: with Stripe, a tier's limit is checked when someone starts to
pay. Someone who has already paid is always given their card, so a rush of
simultaneous payments can overshoot the limit by a few. A member who wants to
renew while their card is still working is blocked by the default one-card
rule until it expires. Choose *No limit* on that tier if you'd rather allow it.

### Collectibles (limited-edition drops)

Press **+ New card → Limited drop** to sell or give away a numbered edition. The
**Days** box turns into "Never expires" and the box shows:

- **Drop name** (shown on the card), **Opens** and **Closes** (both optional: people can
  only claim it inside that window; leave both empty and it stays open until it sells
  out) and a **Note on the card** ("Signed print").
- **Edition size**: how many copies exist (the same box other tiers call "Max members").
  Every card gets its own number, like **#37 of 100**, printed on the card and signed
  into it. Leave it empty for an open edition (numbered, but no limit).

A collectible card says "Collectible" under the title and "Limited edition" at the bottom,
shows "forever" instead of an expiry date, and never expires, so it never gets a
reminder and can't be extended. The tier picker on your site shows the drop and when
it closes; before it opens the tier says "Opens ..." and after it closes "Drop closed",
and neither can be picked. A revoked copy keeps its number, so a sold-out edition stays
sold out. By default one person can claim one copy (change "Cards per email address" in
**Advanced** if you want otherwise). Free or paid, it works like any other tier. When you
give one away by hand from Members, "Ignore limits" lets you hand out a copy outside
the window.

What the collector gets is the **drop content**: make a section on the **Content** page
with the links (a Drive or Bandcamp link, a YouTube video, a download) and list its key
under that tier's "Sections". Only people holding that card can see it. Uploaded files
count against your storage, so for big albums or photo sets a link to where they live is
usually easier. Cards can't be transferred or resold in this version: the card belongs
to the email it was claimed with.

## 4. Add your members-only content

Log in to the dashboard and open **Content** (top of the page). Here you
decide what a member sees once they're verified:

- A **section** is one tab in the member area. Give it a title and a
  **key** (a short lowercase name such as `downloads`). Three kinds:
  **Links** (a list of items, each with a title, a link and a short note —
  downloads, videos, posts, anything you can link to), **Merch discount**
  (a label, a shop link and a code), and the **Chat panel** (a demo for
  now; messages stay in the visitor's browser).
- Which members get which sections: on the **Dashboard**, each tier has a
  "Sections" field. List the keys that tier unlocks, e.g. `downloads, chat`.
  The Content page shows who sees what, and flags a tier that names a
  section which doesn't exist.
- **Thumbnails**: an item with a YouTube link gets that video's picture automatically.
  Any item can also have its own preview picture (upload one) or be a file you upload.
- **Locked preview**: tick "Show the item titles to visitors as a locked preview" on a
  Links section and visitors who have no card yet see a "What members get" box above the
  sign-up with the titles (and which tiers include them). They never see links, files or
  notes. The box disappears once someone is signed in.
- Items and sections can be reordered with the arrows (↑ ↓) next to each.
- Press **Save content**. It's stored on your Volume next to your other
  settings, so it survives redeploys. (`content.json` in the repo is only
  the starter you get on first boot; after your first save, edit in the
  dashboard.)

Content is only sent to a member who proves they hold a valid credential
(their access link, card file or bundle) for a tier that includes the
section, and it is checked again every time the page loads — so revoking
or expiring a member shuts them out immediately. The `/content` address
no longer lists anything.

**Links and uploaded files.** Each item in a Links section is either a link
or an uploaded file (press "or upload a file instead…" on the item, pick the
file, then **Save content**). Uploaded files are stored on your Volume and
can only be downloaded by a verified member whose tier includes that
section: the download link a member's page gets works for 15 minutes and
stops working at once if you revoke them. Files are always sent as a
download, never displayed, so an uploaded web page can't run on your site.
A plain **link** you add is different: whoever is given it can open it, so for
files that must stay private, upload them here or use a link that's private
on its own side. Files you remove from an item are deleted from the server
about an hour after you save.

**Pictures (thumbnails).** If an item is an uploaded picture (PNG, JPG, GIF or
WEBP), a small preview is made automatically, so a section of pictures looks
like a gallery. For anything else (a zip, a video link) you can add your own
preview picture with "Add preview picture". Preview pictures are shrunk to a
small JPEG and are only shown to verified members of the right tier. Set a
section to **Grid** (pictures side by side) or **List** (one per row) at the
top of the section.

**Selling one item.** Open "Sell this item" on an item, type a price (for
example `$5`) and a buy link (a PayPal, Gumroad or Ko-fi link; it must start
with `https://`). Members then see a **Buy** button on that item. This is a
simple shop link: it does not unlock anything by itself, so send or
publish the file after you get paid.

Mind your storage: uploads live on the same Volume as your members and
signing key, and the Volume has a fixed size (see your Railway plan). The
Content page shows how much the uploads use. One file can be up to
`MAX_UPLOAD_MB` (default 100) megabytes. For big videos, a link to a video
host is usually the better choice.

## 5. Set environment variables

| Variable | Required | Purpose |
|---|---|---|
| `ADMIN_SECRET` | **Yes** | The admin login password, and the secret `/revoke` accepts from scripts. With this unset, the login page, `/revoke`, and `/admin/members` all refuse everyone — there is no default/fallback secret on purpose. |
| `SESSION_SECRET_KEY` | Recommended | Signs the admin login session cookie. If unset, a random key is generated each time the app starts, which means every restart/redeploy logs the admin out. Set a fixed random value (e.g. `python -c "import secrets; print(secrets.token_hex(32))"`) so logins persist. |
| `BREVO_API_KEY` | Yes (to send email) | Brevo transactional email API key. |
| `GMAIL_ADDRESS` | Yes (to send email) | Your Brevo-verified sender address. |
| `MEMBERS_PAGE` | Optional | Overrides the Members page address from Branding. Leave it out to use the built-in page at `/members`. |
| `PUBLIC_URL` | Optional | This server's public address (for example `https://club.example.org`), used in the links in emails when the address you browse differs from Railway's. Railway's own domain is used automatically. |
| `DATA_DIR` | Recommended in production | Path to persistent storage (e.g. a Railway Volume) so issued credentials, your signing key, and your dashboard settings survive redeploys. On Railway it's picked up automatically from an attached Volume if you don't set it; setting it yourself (to the Volume's mount path) always wins. Falls back to the local folder, which is fine for local dev only. |
| `STRIPE_SECRET_KEY` | Only if `payment_provider` is `"stripe"` | Your Stripe secret key (`sk_test_...` or `sk_live_...`). Not needed at all with the default `"manual"` provider — see step 6. |
| `STRIPE_WEBHOOK_SECRET` | Only if `payment_provider` is `"stripe"` | The signing secret for your Stripe webhook endpoint (`whsec_...`). Without it, `/webhook/stripe` refuses everything — there is no default/fallback secret, same philosophy as `ADMIN_SECRET`. |
| `MAX_UPLOAD_MB` | No | Largest single file you can upload on the Content page, in megabytes. Defaults to 100. Keep it well below your Volume's size. |
| `SIGNUP_LIMIT_PER_HOUR` | No | Most sign-ups (all visitors together) the server will accept per hour. Defaults to 300. Raise it for a big launch. |
| `MAX_RESTORE_MB` | No | Largest backup file the dashboard's "Restore from a backup" will accept, in megabytes. Defaults to 1024 (1 GB). |
| `PORT` | No | Defaults to 5001. |
| `FLASK_DEBUG` | No — leave unset in production | Set to `1` for local testing to get Flask's debugger/auto-reload back. Off by default on purpose — leaving it on in a public deployment can expose that interactive debugger to anyone who triggers an unhandled error. Never set this on Railway. |

### Emails (Settings → Emails)

Once `BREVO_API_KEY` and `GMAIL_ADDRESS` are set, your server sends the emails
below. The **Emails** screen is one short list: each row names an email, says
when it is sent and whether it is on. Press **Edit** to open just that one:
subject, message, and clickable chips (`{name}`, `{tier}`...) that drop the right
placeholder into the text where your cursor is. **Preview** shows exactly what a
member would get (using a made-up member), **Send test** emails that sample to
the address you typed at the top of the screen, both using whatever is in the
boxes right now, even before you save, and **Reset to standard words** puts the
built-in text back. A leave-it-alone email keeps the standard words. A row tagged
*Edited* has your own wording. Press **Save changes** to keep your edits. With email
not set up, members can still get in: copy their link from **Members → Copy link**
and send it yourself.

*How your emails look.* At the top of the Emails screen, **How your emails look** picks one
look for every email (and the News emails): **Dark** (the original), **Light and clean** (white,
plain type), **Paper** (warm off-white, classic type), **Bold** (a big band in your accent color) or
**Match my website**. For the last one, type your website address and press **Read my website's colors**:
the server reads that one page (and its stylesheets) once and fills in the page color, text color,
heading/button color and type style. It is only a first guess, so change anything you like with the color
boxes, press **Preview this look**, then **Save changes**. The colors are saved as plain values, so your
emails never depend on your website being up, and nothing is fetched when an email goes out. Only ordinary
public websites can be read (not addresses inside a private network). If your logo is uploaded under
Design → Branding, tick **Show my logo at the top of every email** (it is served from your server at
`/email-logo`). Light looks are the safest in mail apps that re-color dark emails.

*When someone gets a card:*

- **Welcome (membership):** the card, the signed bundle and their personal access
  link. Placeholders: `{name}`, `{tier}`, `{creator}`, `{brand}`, `{expires}`.
- **Ticket confirmation:** sent instead of the Welcome email for an event ticket,
  with the event, time and place. Extra placeholders: `{event}`, `{when}`, `{place}`.
- **Collectible claimed:** sent instead for a collectible; `{drop}` is the drop's
  name and `{edition}` the number ("#37 of 100").

*Payments:*

- **How to pay:** when someone asks for a paid card and you take payment by hand
  or with your own link, they get an email at once with your "Message to the
  member" from Payment, the pay button (if you set a link) and their reference,
  so nothing is lost when the browser tab closes. `{price}` and `{reference}` are
  available. You can switch it off.
- **Payment not confirmed:** sent when you press **Reject** on a payment waiting for
  your OK. You can switch it off. (When you **Approve**, they get the Welcome,
  ticket or collectible email as usual.) Stripe sends its own receipt, so Stripe
  buyers just get the card email once they have paid.
- **New payment waiting (to you):** type your own address and you get a short note
  with the person, card, amount and reference each time someone asks for a paid
  card, with a link to the dashboard. Empty = off. Its wording is fixed.

*Reminders:*

- **Access ends soon:** see the next section.
- **Event reminder:** ticket holders get "see you soon" shortly before the event.
  Choose when (3 hours, 12 hours, 1 day or 2 days before) or Off. Tickets already
  checked in, revoked tickets, and tickets bought after the reminder time had
  already passed don't get one. One per ticket. The server checks about once an hour.
- **Access extended:** see the next section.

*Follow-up emails (automatic):*

Up to five notes that go out by themselves some days after someone joins. Think of
it as a short email sequence: day 1 "welcome again", day 7 "how's it going?", day 30
"thank you". They are all **off** until you switch one on under **Settings > Emails >
Follow-up emails**.

- For each one choose **Send this follow-up? Yes**, **when** (1, 2, 3, 5, 7, 10, 14,
  21, 30, 45, 60 or 90 days after they join), and **who** (everyone, or only one of
  your cards). Then write the subject and message; the usual placeholders work
  (`{name}`, `{tier}`, `{creator}`, `{brand}`). Preview and Send test work like the
  others.
- Each person gets each follow-up once, counted from their own join date. Nothing is
  sent to someone whose card is revoked or has ended, or who has no email.
- Switching one on does **not** email your whole old list. A follow-up only goes to
  people for whom it fell due in the last 3 days, so only recent joiners get it.
- Every follow-up has a **Stop these emails** link (and a one-click unsubscribe for
  mail programs). It asks first, and stops all follow-ups for that email address.
  Their card and member area are not affected.
- The server checks once an hour and sends at most 40 follow-ups per check, so a big
  batch is spread out. Your email service (Brevo) has its own daily limit on the free
  plan, so for a large list switch them on gradually.
- This is not a newsletter: it is a few set notes after joining. For a one-off note to
  members, use **News**.

*Other:*

- **Link again (lost link):** under the sign-up box the member area shows "Lost your
  link? Email me my card". The visitor types their address and, if that address has a
  card that still works, we email the link. The answer on screen is always the same
  ("If that address has a card, we've just emailed the link"), so nobody can use it to
  find out who is a member. It is limited (a few asks per address and per visitor per
  hour) and only shows when email is set up; switch it off here and the button
  disappears. `{name}`, `{creator}`, `{brand}` are available.
- **Access ended:** an optional note to a member when you revoke their card. **Off by
  default**; switch it on here. It is sent once, only when a card is newly revoked.
  `{name}`, `{tier}`, `{creator}`, `{brand}` are available.

When you take payment by hand, the sign-up box also tells the person "We've also
emailed you how to pay" (only when that email was really sent).

News emails (a note to some or all members) are written on the **News** page.

### Renewing a member (Extend) and the expiry reminder

**Extend.** On **Members**, every row that isn't revoked has an **Extend by
(days)** box, pre-filled with that tier's length, and an **Extend** button.
Use it when a member pays again: their end date moves forward, and the card
and personal access link they already have keep working. A card that is still
running gets the days added to its current end date (renewing early loses
nothing); a card that already ran out restarts from today. Tick **email them**
(shown when email is set up) to send a short "your access has been extended"
note. You can change its wording under **Emails → Access extended**
(subject and message; `{name}`, `{tier}`, `{creator}`, `{brand}`, `{expires}` and
`{days}`, which is how many days were added), with Preview and **Send test** like
the other emails. A revoked member can't be extended, and an ended card in a tier that is
now full can't be brought back until there's room. The date printed on the
member's original card file doesn't change; the live check always uses the
date kept on your server.

**Expiry reminder.** Under **Emails → Access ends soon**, this emails a member
a few days before their access ends, once per end date (extending a member
starts a fresh reminder for the new date). Set "days before" to 0 to keep it
off (the default). It needs email set up on the server (`BREVO_API_KEY` and
`GMAIL_ADDRESS`); without it nothing is sent. The subject and text are
editable (`{name}`, `{tier}`, `{creator}`, `{brand}`, `{expires}` and `{days}`),
and an optional "where to renew" address adds a **Renew** button. Preview and
**Send test** work like the welcome email. The server checks about once an
hour. When you switch reminders on, members already inside the window get
their reminder at the next check. A pass that lasts no longer than the reminder
window isn't reminded. Members who are about to end show "ends in Nd" on the
Members page, with a note once a reminder went out.

### Announcements: tell your members about something new

Open **Content → News** (the **Content** place in the menu has two small tabs: Content and News). Write a **title** (optional), a **message** and an optional **link**, then choose:

- **Pin it at the top of every member's page.** Members who open their link see it in a
  "Latest from you" box above their card, with the link as a button. It stays until you
  pin something else or press **Unpin it**. Only people with a working card ever see it.
- **Also email it to…** one of: **Everyone with a working card**, one tier (for example
  "GOLD members"), or the **ticket holders** of one event. The list shows how many people
  are in each group. Each person gets one email, even if they hold several cards, with
  their own access link and a line saying why they received it. Needs email set up
  (`BREVO_API_KEY` and `GMAIL_ADDRESS`, see above); without it you can still pin.

You can do both at once. **Preview the email** shows what members will get, and **Send test**
sends it to one address first. Press **Post** and confirm. Emails go out one by one in the
background, so you can leave the page; the **Sent before** list shows how many went out, how
many failed and the first problem. Only one email send runs at a time, and the last 25
announcements are kept in that list. Your email service has its own sending limits, so very
large lists may need to be sent in parts.

### Giving someone a card (no payment)

On **Members**, open **+ Send a card (free)**, enter their name and
email, pick a tier and press **Send card**. Use it for a friend, a
collaborator, a contest winner, or someone who paid you some other way. The
card is signed and registered like any other and works the same way; the list
marks it "given free". Leave **Days** blank to use the tier's length (an event ticket always lasts until its event ends). If email
is set up, the card is emailed to them; otherwise (or if you untick it) press
**Copy their link** and send it yourself. The usual limits apply (a full tier,
or an email that already has a working card, is refused) unless you tick
**ignore limits**. You can Extend or Revoke it like any other member.

### Deleting a member

Each row on **Members** has a **Delete** button. It asks twice (a confirmation,
then you type `DELETE`) because it can't be undone. It erases the member's
entry, their card, bundle and certificate files, and finished (approved or
rejected) payment requests for their email, unless that person still has
another card. Their ID goes on the revocation list first, so any copy of the
card they still hold stops working for good. Their tier spot and email are
free again, so they could sign up as a new member. A payment request still
waiting for your decision is left alone. **Revoke** is the gentler choice: it
cuts off access but keeps the record. Backups you downloaded earlier still
contain the deleted person, so delete those too if you need them gone
completely.

### Admin login

Go to `https://<your-domain>/admin/login` and log in with `ADMIN_SECRET`
as the password. From there: **Dashboard** (branding, tiers, pricing —
see step 3) and **Members** (view/revoke issued credentials). There's no
`?secret=` link to bookmark — the browser uses a real session cookie.
Scripts/curl can still authenticate to `/revoke` with the
`X-Admin-Secret` header if you need to automate revocation.

**Built-in protections** (nothing to set up):

- **Login lockout.** After 5 wrong passwords in a row the visitor is locked
  out for 15 minutes — even the right password is refused during that time.
  Wrong `X-Admin-Secret` guesses count the same way. If you lock *yourself*
  out, wait 15 minutes, or restart the service in Railway (that clears it).
  There is also a site-wide backstop for guessing spread over many addresses.
- **Forged-request protection.** Every admin action made from your browser
  carries a hidden token that only the admin pages know, so another website
  can't make your logged-in browser change settings, revoke members or upload
  files. (Scripts using the `X-Admin-Secret` header don't need it.) If you
  ever see "Security check failed. Reload the page", just reload and retry —
  it happens after a redeploy or if the page was open for a very long time.
- **Rate limits on public endpoints.** Each visitor can sign up about 10
  times per 10 minutes, and make 120 verify/content requests per minute (60
  file downloads per minute). On top of that, all sign-ups together are
  capped at `SIGNUP_LIMIT_PER_HOUR` (default 300) so nobody can fill your
  disk with cards or burn your email quota. Raise it before a big launch.
- The login cookie is marked secure on Railway, admin pages can't be shown
  inside another site's frame, and admin pages are never cached.

## Backups: keep a copy of what you own

Everything that matters lives in one place on your server: your **signing
key**, your **members**, your settings, your content, the cards you issued
and any files you uploaded. If that storage were ever lost (a deleted
Railway project or Volume, for example), all of it would be gone, and every
card you ever issued would stop working, because the key that signed them
would be gone too. A backup is one `.zip` file you keep somewhere safe.

**Make one:** **Settings → Backup** →
**Download backup**. The first button saves your members, key, settings and
content (usually well under a few MB). If you have uploaded files, a second
button includes them too (as big as your uploads are). The checklist at the
top of the dashboard reminds you until you have one under 30 days old.

**Keep it safe and private.** The file contains your private signing key and
your members' email addresses. Don't email it or leave it anywhere others can
open it. A private cloud folder or an encrypted drive is fine. Make a fresh
one now and then, and always after something important (for example before a
big launch).

**Restore it:** on the same server, or on a brand-new copy of the app (deploy
the template again, log in, open **Backup & restore → Restore from a
backup**), choose the file, type `RESTORE` and press the button. Your members,
key, settings and content come back, old cards keep working, and the people
whose cards you revoked stay revoked. A restore replaces what is on that
server now; what it replaced is kept aside on the server (a folder named
`.replaced-…`, only the latest one is kept) rather than deleted. If anything
about the file looks wrong (damaged, not one of this app's backups, a missing
key, files that try to escape the folder) nothing is changed and you get a
plain message saying why.

**Automate it (optional):** you can fetch the same file from a script with
your admin password, for example on a schedule on your own computer:

```
curl -H "X-Admin-Secret: YOUR_ADMIN_SECRET" -o backup.zip "https://your-domain/admin/backup/download?files=1"
```

(Leave off `?files=1` for the small one without uploaded files.) Wrong
passwords from a script count toward the same lockout as the login page.

## 6. Taking payment for paid tiers

Any tier in `config.json` with a `price` above 0 goes through whichever
**payment provider** `config.json`'s `payment_provider` field names — set
from the dashboard's Payment section, not hand-edited. Free tiers
(`price: 0`) always issue instantly regardless of this setting. Payment is
deliberately **not hardcoded to one processor** — creators using this
template are in different countries, under different regulations, and not
every processor serves every category of business (Stripe in particular
won't serve some categories at all — adult content among them). There are
three providers built in (Manual approval, Custom payment link and Stripe),
and a documented way to add more.

### 6a. "Manual approval" — the default, and the one that works everywhere

With `payment_provider` left at `"manual"` (or anything else unrecognized —
it fails *safe* to this, never to an unconfigured automated provider), no
payment account of any kind is required. The flow: a member requests a
paid tier, this app records a pending request and shows them whatever text
you put in **Message to the member** in the dashboard (e.g. "Send
$9.99 via PayPal to me@example.com, or by e-transfer to..., then message
me your email"). You confirm payment arrived however it actually does for
you, then click **Approve** next to that request in the dashboard's
pending-requests list — that's what actually issues the credential (same
pipeline a Stripe webhook uses). **Reject** just closes the request with
no credential issued. Nothing here needs deploying with real money or a
third-party account to test — you can run through the entire flow (request
→ instructions → approve → credential issued and emailed) today, locally.

This is the right default for: anywhere Stripe won't operate or won't
serve your content category, any country where none of the big processors
are available, or simply not wanting to hand a third party your business
details yet. The trade-off is it's manual — there's no automatic "payment
received" signal, so there will be a delay between someone paying and you
approving.

### 6a-2. Send members to a payment link (PayPal, Ko-fi, Gumroad...)

In the dashboard's Payment screen, choose **Send them to a payment link**.
Type the **name of the service** (for example PayPal) and paste the **payment
link** where members pay. It has to start with `https://`. That is all you
need.

What happens: the member picks a paid tier and enters name and email. The
widget shows your message, a short reference code and a **Pay with ...**
button that opens your link in a new tab. The request also lands in the
**Payments waiting for your OK** list, the same list used when you arrange
payment yourself. A link can't tell this app that the money arrived, so when
you see the payment in that service you press **Approve** and the member gets
their card.

**Want to try it first?** Under the link field, press **Use the practice
page**, then **Save**. It fills in a pretend payment page on your own server
(no money moves). Sign up for a paid tier on your Members page, press the Pay
button, and the practice page shows your reference and what to press next:
**Approve** in the waiting list.

Under **More options** (you can skip it): a different link for one tier (one
per line, like `MEMBER = https://ko-fi.com/s/abc123`), and fill-in words you
can write inside any link: `{amount}`, `{currency}`, `{tier}`, `{email}`,
`{name}` and `{reference}`, for example
`https://paypal.me/yourname/{amount}{currency}`. The reference is a short code
that also appears in the waiting list, so you can match a payment to a
request. Only `https` links are accepted, and a visitor's name can never decide
where they are sent.

### 6b. Stripe — automatic card checkout

Switch `payment_provider` to `"stripe"` in the dashboard once you want
members charged by card automatically, with no manual approval step.

**How it works:** `POST /checkout` creates a Stripe Checkout Session and
returns a `checkout_url` to redirect the member to. Stripe hosts the
actual card-entry page — this app never sees card numbers. Once the member
pays, Stripe calls your `/webhook/stripe` endpoint, and **that webhook
call is the only thing that actually issues the credential** — not the
redirect back to your success page. This matters: if a member closes the
tab right after paying, the webhook still fires and they still get issued,
because Stripe retries delivery until it gets a 200 back. The webhook is
idempotent — a retried/duplicate delivery of the same payment will not
issue a second credential.

**Setup steps:**

1. Create a Stripe account (or use an existing one) at
   [stripe.com](https://stripe.com). Start in **test mode** — Stripe gives
   you separate test and live API keys, and test mode lets you run through
   the whole flow with fake card numbers before touching real money. Note
   that Stripe's terms restrict what categories of business it will serve
   at all (adult content is a notable exclusion) — if that's a concern,
   use the manual provider, or a processor that explicitly serves your
   category, instead.
2. In the Stripe Dashboard, under **Developers → API keys**, copy your
   **Secret key** (`sk_test_...` while testing) into `STRIPE_SECRET_KEY`.
3. Set up the webhook endpoint so Stripe can tell this app when a payment
   completes:
   - **Once deployed** (recommended): in the Stripe Dashboard, go to
     **Developers → Webhooks → Add endpoint**, set the URL to
     `https://<your-domain>/webhook/stripe`, and select the
     `checkout.session.completed` event. Stripe shows you a **Signing
     secret** (`whsec_...`) — set that as `STRIPE_WEBHOOK_SECRET`.
   - **Local testing, before you have a public URL**: install the
     [Stripe CLI](https://stripe.com/docs/stripe-cli), run
     `stripe listen --forward-to localhost:5001/webhook/stripe`, and use
     the `whsec_...` value it prints as `STRIPE_WEBHOOK_SECRET` for that
     session.
4. Set both env vars, redeploy, switch `payment_provider` to `"stripe"` in
   the dashboard, and its Payment section will show both keys as
   configured.
5. Run one real test purchase end-to-end using
   [Stripe's test card numbers](https://stripe.com/docs/testing)
   (`4242 4242 4242 4242`, any future expiry/CVC) before switching to live
   keys. Confirm the credential actually gets issued and emailed.
6. When ready to take real money, swap `sk_test_...` for your `sk_live_...`
   key and repeat step 3 for the live webhook endpoint (test and live mode
   have separate webhook configurations in Stripe).

### 6c. Adding a new payment provider

Neither built-in provider will fit every creator — different countries,
different regulations, different acceptable-use policies per processor.
Adding one (PayPal, a regional processor, an adult-friendly processor like
CCBill/Segpay/Vendo/Epoch, anything) means touching `credential_api.py`'s
`/checkout` route and, if that processor uses webhooks, adding a route for
it — but never touching `_issue_and_fulfill()` or the core issuance
pipeline, which every provider shares. Concretely:

1. In `/checkout`'s provider dispatch (the `if provider == "stripe": ...`
   block), add an `elif provider == "yourprovider":` branch that either
   returns a redirect URL (like Stripe's `checkout_url`) or a
   `{"pending": True, ...}` response (like the manual provider), whichever
   fits how that processor actually works.
2. If it confirms payment via a server-to-server callback, add a new
   `/webhook/yourprovider` route that verifies the callback is genuinely
   from that processor (however it signs requests) and then calls
   `_issue_and_fulfill(name, email, tier, days, sections, cfg=cfg,
   payment_meta={...})` — the same function every other provider calls.
   Build in idempotency the same way `_stripe_already_processed` does, if
   that processor can redeliver the same notification more than once.
3. Add `"yourprovider"` as a new `<option>` in the dashboard's Payment
   provider dropdown (`_dashboard_page()`), and any provider-specific
   fields (an account ID, say) the same way `manual_payment_instructions`
   was added — a new `config.json` field, read in `load_config()`, written
   in the dashboard's save handler.

No core file needs rewriting to do this — `_issue_and_fulfill`, the
registry, the card/bundle/email pipeline, and the admin dashboard's
tiers/branding are all provider-agnostic already.

**Important limitation, for every provider:** this is **one-time payment
only**. Each paid tier is "pay once, get N days of access"
(`expiry_days`) — there is no subscription billing, no automatic renewal,
and no automatic charge when a credential expires. A returning member who
wants another period simply goes through `/checkout` again. If you need
recurring billing, that's a deliberate scope boundary of this build, not a
bug — it would need a different kind of integration (subscriptions, not
one-off charges) and member-facing renewal UI that don't exist here yet.

## 7. Embed the member widget on your actual site

The easy way: open your dashboard (at its real public address), scroll to
**Embed on your website**, and click **Copy**. Paste it into any page of
your site, wherever you want the widget to appear. It's two lines:

```html
<div id="credential-widget"></div>
<script src="https://your-railway-domain/cp.js"></script>
```

That's all. The widget works out where your server is from the address
`cp.js` was loaded from, so there's nothing else to fill in — no API
address, no keys. It fetches your branding from the server at runtime, and your members-only
content only after a member has been verified, so nothing needs editing in
`cp.js` itself.

Notes:

- The div's id has to be exactly `credential-widget` (the widget's
  older id, `crith-access`, is still accepted so earlier embeds keep
  working). If the div is missing, the widget now prints a visible note on the page and an
  error in the browser console instead of silently showing nothing.
- The script tag can go before or after the div; the widget waits for the
  page to finish loading.
- **Optional:** if you ever serve `cp.js` from somewhere other than your
  server itself (a CDN, or a copy hosted on your own site), tell it where
  the API is with `data-api`:
  `<script src="..." data-api="https://your-railway-domain"></script>`.
  You don't need this for a normal install.
- To try it before touching your real site, save the two lines in a plain
  file called `test.html` and open it in your browser.

### How the widget looks (Widget look)

Out of the box the widget copies the page it sits on: it reads the page's
background color, text color and font and builds its boxes, borders and
sign-up pop-up from them, so it fits a dark page, a light page, a colorful
page or one with a photo behind it. If your site switches between dark and
light, the widget follows.

To change that, open **Design → Widget look**. You can set:

- **Colors** — *Match my page* (default), *Always dark*, *Always light*, or
  *My own colors* (a background color and a text color you pick).
- **Lettering** — your page's own font (default), or the keycard lettering
  used on the cards (Bebas Neue and JetBrains Mono, loaded from Google Fonts
  only when you pick this).
- **Corners** — square or rounded.
- **Wording** — the banner, the card drop box (title and small line) and the
  sign-up pop-up (title, text and button). Leave a box empty to keep the
  standard wording. Text is shown exactly as typed; HTML in it is not
  interpreted.
- **Terms and privacy links** (optional) — add a link to your terms and/or privacy page
  and the sign-up pop-up says "By getting a card you agree to the Terms and Privacy
  Policy." with those words linked (opens in a new tab). Only http and https links are
  accepted. Leave both empty for no line at all.

Two live previews (one on a dark page, one on a light page) show your real
widget and follow every change before you save. The **accent color** (under
Branding) is used for buttons and highlights; the widget makes sure text
stays readable on whatever background it ends up on. Changes apply to the
page as soon as you save — nothing to edit on your site.

### Dashboard style

The pages only you see (dashboard, Members, Content and the login page) can
look five different ways. Open **Design → Dashboard style**,
click a card and press **Save changes**:

- **Spaceship** — near-black with typewriter lettering and small capitals
  (the original look).
- **Spaceship lite** — the same colors and typewriter lettering, but split
  into screens with a menu (like Daylight and Midnight) instead of one long page.
- **Daylight** — clean and light with friendly lettering and rounded cards.
  New installs start with this one, because it is the easiest to read.
- **Studio** — warm ivory paper, serif headings and thin lines.
- **Midnight** — modern dark blue-grey with soft depth.

The styles also differ in how the dashboard is laid out, not just how it
looks:

- **Spaceship** keeps the single long page you scroll through. As soon as you
  change something, a **Save changes** bar appears at the bottom of the screen,
  so you never have to scroll down to find the button; after saving you land
  back where you were.
- **Studio** is also one long page, with a small contents list beside it on a
  wide screen to jump between sections. It has the same Save changes bar.
- **Spaceship lite**, **Daylight** and **Midnight** work like an app. On a computer there is a
  menu down the left with six places: **Home**, **People** (Members and
  Check-in), **Cards**, **Content** (Content and News), **Design** (Branding,
  Card looks, Widget look, Dashboard style) and **Settings** (Payment, Emails,
  Backup). On a phone the same six sit along the bottom. Places with more than
  one screen show them as small tabs under the title. When you change something, a **Save changes** bar appears; nothing is
  saved until you press it.
  On a phone, the Members page shows each member as a card: tap a card to open
  it and see the email, dates and the Copy link, Extend, Revoke and Delete
  buttons. The Content page keeps its **Save content** button in reach at the
  bottom of the screen.

This only changes your own admin pages. Cards, emails and the member widget
are not affected (the widget has its own look settings, see above). Your
accent color is kept in every style; where it would be hard to read as text
it is darkened or lightened a little automatically. An existing install that
never picked a style keeps the Spaceship look until you choose another.

## 8. Deploy — Railway, connected to GitHub, so pushes auto-deploy

This covers getting from "files on disk" to a real, public dashboard URL
that redeploys itself every time you push a change — no further manual
deploy step after this one-time setup. It needs a GitHub repo first,
since that's what Railway watches for pushes. Any host that runs
the start command in `Procfile` works in principle (it runs the app with
**gunicorn**, a production web server — Flask's built-in server is only
for local testing, and `python credential_api.py` still starts that one
on your own machine). Gunicorn only runs on Linux/macOS, which is fine for
Railway; on Windows, just keep using `python credential_api.py` locally.
The Procfile deliberately runs a single worker with a few threads: the
member registry and the other runtime data are plain files, and a single
process is what keeps writes to them from colliding.

**Shortcut:** if this project's README has a **Deploy on Railway** button,
that does steps 3-5 below for you in one click (it creates the project,
the persistent storage and the secret keys). The manual steps below are
for deploying from your own GitHub copy instead.

1. **Create a new, empty GitHub repository** (github.com → New repository
   → don't initialize it with a README/license/`.gitignore`, this folder
   already has one). Decide public or private — a public repo is what
   lets a future "Deploy on Railway" button work for other creators later
   (step 8's note at the end); private just means only people you invite
   can see or deploy it. Either works fine for your own use right now.
2. **Push this folder to it.** From a terminal in this folder (PyCharm's
   terminal works fine):
   ```
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<your-username>/<your-repo>.git
   git push -u origin main
   ```
   (If `git` asks you to sign in, follow its prompts — same as any other
   GitHub push.)
3. **In Railway**, create a **new project** (a brand-new project, not one you already use for something else) → **Deploy from GitHub repo** → pick the repo you just pushed.
   Railway detects `requirements.txt` + `Procfile` automatically; no extra
   config needed for it to build and run this.
4. **Add a Volume** to that service (Railway's Volumes tab) and set
   `DATA_DIR` to its mount path. Do this *before* issuing any real
   credential — it's what makes the registry, issued credentials, and the
   signing key (step 2) all survive a redeploy.
5. **Set the rest of the env vars** from step 5 in that service's
   Variables tab (`ADMIN_SECRET` at minimum; `BREVO_API_KEY`/
   `GMAIL_ADDRESS` to actually send email; Stripe's two keys only if
   you're using that provider).
6. Railway gives you a public URL once it finishes building. `/admin/login`
   on that URL is your dashboard from anywhere now, not just localhost.
7. If you're using Stripe, come back and point its webhook at this real
   URL (step 6b.3) — the Stripe CLI forwarding from earlier only covered
   local testing.

**From here on, every `git push` to this repo redeploys automatically** —
that's Railway's normal behavior once a service is connected to a repo,
nothing extra to configure for it. This is the "automatic deploy" piece:
it's a one-time setup, not something repeated per change.

A literal one-click **"Deploy on Railway" button** — so another creator
could deploy their own copy without touching git or a terminal at all —
is a separate, later step on top of this: it's created from Railway's own
dashboard (New → Template, pointed at this same GitHub repo), not a file
in this codebase. Worth doing once this deployment itself is tested and
working, if the plan is to hand this template to other creators.

## 9. Test before telling anyone it's live

Issue a real test credential through `/issue`, confirm all four access
paths work (personal link, QR scan, pasted link, file drop), then log in
at `/admin/login` and revoke it through `/admin/members` — confirm all
four now correctly reject it. This is the only real proof the revocation
path works in your specific deployment — don't skip it.

If you have any paid tiers, also run through one full purchase before
telling anyone it's live. With the default manual provider that costs
nothing and needs no account: request the tier, confirm the instructions
text shows up, approve it in the dashboard, confirm the credential is
issued and emailed. With Stripe, run one real test purchase (step 6b.5)
instead — that's the only real proof payment → webhook → issuance
actually works in your specific deployment.

## What's intentionally NOT here

No offline bundle verifier, no device-binding, no single-active-session
enforcement. Real access control happens entirely through the live
`/verify` API call — see the architecture notes carried over from the
original build for why that trade-off was made.

Every built-in payment provider is one-time payment only — no
subscriptions/auto-renewal (see step 6). The "manual" provider also has no
automatic payment confirmation by design — approving is a human decision,
on purpose. The admin is a single-password, single-admin tool (no
accounts, no two-factor) — fine for a small/direct-support deployment, and
protected by the login lockout, forged-request token and rate limits
described under "Admin login" — but worth more before this is ever
multi-tenant or exposed more broadly.

## Your card's look

Card designs are called **card looks**. They live in the dashboard (no files to
upload to the server) in two places:

- **Branding** holds your **Default look**: the card title, accent color,
  label, style, logo, barcode on/off and an optional background picture.
- **Card looks** (its own screen) is where you keep extra, named looks: for
  example "Monthly member", "Trial" or "VIP". It shows every look as a small
  card preview. **+ New look** opens an editor with a live preview that updates
  as you type. Each saved look has **Edit**, **Copy** (a quick way to make a
  variation) and **Delete** (press twice). You can keep up to 12.

Then open **Cards**: every card has a **Card look** menu. Pick
which look that tier's members get. A tier left on "Default look" uses what's
in Branding. If you delete a look that a tier uses, that tier goes back to
the Default look (the dashboard tells you which).

What you can set in a look:

- **Title, label and color:** anything you leave blank follows the Default
  look, so you only fill in what's different.
- **Style** (seven built in): *Distressed* (worn keycard with film grain and
  scratches), *Clean* (smooth and unworn), *Holographic* (rainbow sheen),
  *Minimal* (light paper), *Ticket* (notches and a tear line), *Gradient*
  (a wash of your color) and *Neon* (glowing outline).
- **Logo:** PNG, JPG, GIF or WEBP, shrunk automatically (long side 600 px).
  A look's own logo wins over the Default look's. Remove it and the look
  falls back to the Default logo.
- **Background picture:** optional, any PNG, JPG, GIF or WEBP up to 10 MB;
  it's shrunk to 1000 px on the long side. **Darkening** (not at all, a little,
  some, a lot) keeps the text readable on top of a busy picture. Unlike the
  other fields, **a background picture is not inherited**: a look only shows
  one if it has its own (or it is the Default look itself). The picture is
  built into each card file, so keep pictures modest.
- **QR code:** *Solid* (the white square, easiest to scan), *Blended* (the code
  is drawn see-through so it melts into a background picture; it sits on a very
  faint dark patch and was tested to still scan, but a solid code is always the
  most reliable) or *Hidden* (no QR code drawn). Members can always use their
  personal link, and a hidden code is still inside the card file, so dropping
  the card file into the widget keeps working. Set it for the Default look under
  Branding, and per look in the editor ("Same as the default look" by default).
- **Layout:** *Classic* (the details sit on top of the picture) or *Art front*:
  the card first shows just your picture, clean, with a small label in the
  corner (the event or drop name, or your brand), and a tap turns it over to
  the details and QR code. It works for memberships, tickets and collectibles.
  Printing a card always prints the details side. Set it for everything under
  Branding (**Card layout**) and per look in the editor ("Same as the default
  look" by default).
- **Show barcode:** on or off.
- **Preview:** both the Branding and the Card looks screens show the result
  using what's currently on screen, before you save.

If you used an earlier version that kept a design inside each tier, those
designs are converted into looks automatically the first time you open the
dashboard (named "<tier> look") and the cards look exactly the same.

The **Minimal** style is light paper, so a light-colored logo can disappear on
it; check the preview.

Only cards issued after a change use the new look; cards members already
have stay as they were.

(If you run the code by hand rather than through the dashboard, a
`logo.png` in `assets/` is still used as a last-resort logo.)

## The Members page

Members open their personal access link on a **Members page**: a page with the
widget on it. You don't need a website for this. The server makes one for you
at `https://<your-address>/members`, and every link, email and checkout uses it
automatically. You can also open it yourself to check what members see.

When a member opens their link, the page shows their card (scaled to fit the
screen) with a **Download your card** button, above their members-only content.
The card stops showing the moment you revoke them.

If you have your own website, put the two embed lines (dashboard → Embed on
your website) on a page of yours and type that page's address under
**Branding → Members page address**. Leave it empty to go back to the built-in
page. The old sample address from earlier versions is treated as empty.
