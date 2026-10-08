# Credential Protocol

Signed membership cards for creators, on a server you own. Members sign up
on your website, get a cryptographically signed card and a personal access
link, and the content you gate behind it opens for them. No platform in the
middle, no platform cut: your members, your keys, your money.

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/credential-protocol)


## Get it running in four steps

1. **Click Deploy on Railway** (above). Railway asks you to choose an admin
   password (`ADMIN_SECRET`) and then builds your own private copy. Storage
   for your members and signing key is set up for you.

   Note: Railway's Free plan is too small for this (it has no usage credit
   and only a tiny volume). Plan on a paid Railway plan; at the time of
   writing the Hobby plan is about $5 a month and includes enough for a small
   membership site. Check railway.com/pricing for current prices.
2. **Open your dashboard.** In Railway, open the new service, generate a
   public domain under Settings → Networking if there isn't one yet, and go
   to `https://your-domain/admin/login`. Log in with the password you chose.
3. **Fill in your info.** The dashboard has a setup checklist at the top:
   your name and brand, your tiers and prices, how members pay you, and the
   members-only content (links, uploaded files, a discount code) on the
   Content page. Only verified members can see that content.
4. **Add two lines to your website.** The dashboard's "Embed on your
   website" box shows them with your real address filled in, ready to copy:

   ```html
   <div id="credential-widget"></div>
   <script src="https://your-domain/cp.js"></script>
   ```

That's it. Members sign up in the widget; you see them in the dashboard and
can revoke any of them at any time.

## What you get

- A signup and access widget that works on any site (two lines of HTML) and
  adapts to your page's colors and font by itself; you can also set its colors,
  corners and wording in the dashboard.
- An admin dashboard (five looks to choose from: Daylight, Studio, Midnight, the original
  Spaceship, or Spaceship lite, which has the same look in app-style screens): branding, tiers and pricing, saved card looks (seven styles, logos, background pictures) you pick per tier,
  payment settings, a member list with one-click revoke, and a "copy link"
  button that gives you any member's personal access link.
- Cards and credentials signed with ECDSA, with a private key generated for
  your deployment and kept on your own storage.
- Paid tiers without needing a payment processor: members request a paid
  tier, you confirm you were paid however you like, and approve it with one
  click. A "custom payment link" option sends members to your own
  PayPal, Ko-fi, Gumroad or other payment link first. Stripe is built in as an
  optional automatic alternative.
- Members-only content: links, files you upload (only verified members of the
  right tier can download them) and a merch discount, shown per tier, with
  picture thumbnails, a list or grid view, and a Buy button on single items.
- Backup and restore: one downloadable file with your members, signing key,
  settings and content, and a restore that works on a brand-new server.
- A built-in Members page at /members, so personal access links work from day one without a website of your own (use your own page by typing its address in Branding).
- Send a card to anyone for free (a friend, a winner) from the Members page,
  emailed to them or copied as a link to send yourself.
- Delete a member and their files when you need to (e.g. a data-removal
  request).
- Renewals: one click on the Members page extends a member (same card, same
  link), and an optional email reminds members shortly before their access
  ends.
- Limits per tier: cap how many members a tier can have (it shows as
  "Sold out" when full) and allow one card per email address.
- Built-in protections: admin login lockout, forged-request protection and
  rate limits on public pages.
- Email delivery (optional): connect Brevo and members get their card and
  link by email. Without it, copy each member's link from the dashboard and
  send it yourself.

## Good to know

- You pay Railway for hosting your copy; see Railway's pricing.
- Paid tiers are one-time payments for a set number of days. There are no
  subscriptions or automatic renewals.
- One admin login (the `ADMIN_SECRET` password) per deployment.
- Stripe support is built in but has only been tested against Stripe's test
  mode.
- Your settings are saved on your deployment's storage, not in the code,
  so updating the code never resets them.

## Docs

[SETUP.md](SETUP.md) covers everything in detail: every setting, email
setup, payments (manual and Stripe), adding another payment provider, and
deploying from your own GitHub copy instead of the button.

## License

Not yet specified.
