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
  "members_page": "https://your-domain.com/members.html",
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

This also holds the per-tier card designs and their uploaded logos. Your
members-only content (step 4) is stored the same way.

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
| `MEMBERS_PAGE` | Recommended | Overrides `config.json`'s `members_page` — the URL members land on (where `cp.js` is embedded). |
| `DATA_DIR` | Recommended in production | Path to persistent storage (e.g. a Railway Volume) so issued credentials, your signing key, and your dashboard settings survive redeploys. On Railway it's picked up automatically from an attached Volume if you don't set it; setting it yourself (to the Volume's mount path) always wins. Falls back to the local folder, which is fine for local dev only. |
| `STRIPE_SECRET_KEY` | Only if `payment_provider` is `"stripe"` | Your Stripe secret key (`sk_test_...` or `sk_live_...`). Not needed at all with the default `"manual"` provider — see step 6. |
| `STRIPE_WEBHOOK_SECRET` | Only if `payment_provider` is `"stripe"` | The signing secret for your Stripe webhook endpoint (`whsec_...`). Without it, `/webhook/stripe` refuses everything — there is no default/fallback secret, same philosophy as `ADMIN_SECRET`. |
| `MAX_UPLOAD_MB` | No | Largest single file you can upload on the Content page, in megabytes. Defaults to 100. Keep it well below your Volume's size. |
| `SIGNUP_LIMIT_PER_HOUR` | No | Most sign-ups (all visitors together) the server will accept per hour. Defaults to 300. Raise it for a big launch. |
| `PORT` | No | Defaults to 5001. |
| `FLASK_DEBUG` | No — leave unset in production | Set to `1` for local testing to get Flask's debugger/auto-reload back. Off by default on purpose — leaving it on in a public deployment can expose that interactive debugger to anyone who triggers an unhandled error. Never set this on Railway. |

### The welcome email

Once `BREVO_API_KEY` and `GMAIL_ADDRESS` are set, every new member is emailed
their card, bundle and personal access link. You can change the wording in
the dashboard under **Welcome email**: the subject, the welcome text, and an
optional sign-off. `{name}`, `{tier}`, `{creator}`, `{brand}` and `{expires}`
are filled in for each member. **Preview email** shows exactly what a member
would get (using a made-up member) and **Send test** emails that sample to
any address you type, both using whatever is in the boxes right now, even
before you save. With email not set up, members can still get in: copy their
link from **Members → Copy link** and send it yourself.

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

## 6. Taking payment for paid tiers

Any tier in `config.json` with a `price` above 0 goes through whichever
**payment provider** `config.json`'s `payment_provider` field names — set
from the dashboard's Payment section, not hand-edited. Free tiers
(`price: 0`) always issue instantly regardless of this setting. Payment is
deliberately **not hardcoded to one processor** — creators using this
template are in different countries, under different regulations, and not
every processor serves every category of business (Stripe in particular
won't serve some categories at all — adult content among them). There are
two providers built in, and a documented way to add more.

### 6a. "Manual approval" — the default, and the one that works everywhere

With `payment_provider` left at `"manual"` (or anything else unrecognized —
it fails *safe* to this, never to an unconfigured automated provider), no
payment account of any kind is required. The flow: a member requests a
paid tier, this app records a pending request and shows them whatever text
you put in **Manual payment instructions** in the dashboard (e.g. "Send
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

Everything about how the member card looks is set in the dashboard under
**Branding** (no files to upload to the server):

- **Card logo:** upload a PNG, JPG, GIF or WEBP. It's shrunk automatically
  to a sensible size (long side 600 px) and shown on every card. A tier can
  have its own logo under **Design ▾**, which wins over this one. Remove
  the logo and cards simply have none.
- **Card style:** *Distressed* (the worn keycard look, with film grain and
  scratches) or *Clean* (the same card, smooth and unworn). A tier can pick
  its own under **Design ▾**.
- **Card label:** the small line under the title, e.g. "Member Keycard".
  A tier can override it too.
- **Preview the card →** (under Branding, and inside each tier's Design
  panel) shows the result using what's currently on screen, before you save.

Only cards issued after a change use the new look; cards members already
have stay as they were.

(If you run the code by hand rather than through the dashboard, a
`logo.png` in `assets/` is still used as a last-resort logo.)
