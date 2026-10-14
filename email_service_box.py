"""
Credential Protocol: the "Email service" box at the top of Settings > Emails.

The creator picks Brevo, Mailjet, Resend or any email server, pastes the keys the service gave them and the sender address,
and presses Save. Nothing has to be set in Railway. The box talks to /admin/email-service (see credential_api.py) with its own
buttons: it has no form of its own, its boxes have no `name`, and it stops their typing from reaching the dashboard's form, so
the dashboard's "unsaved changes" bar is not triggered by it.

Secrets are never put in the page: a saved key shows only its last 4 characters.
"""

import json
from html import escape as _esc

import mail_providers as mp

LABELS = {
    "BREVO_API_KEY": "API key", "MAILJET_API_KEY": "API key", "MAILJET_SECRET_KEY": "Secret key", "RESEND_API_KEY": "API key",
    "SMTP_HOST": "Server (host)", "SMTP_PORT": "Port", "SMTP_USER": "User name", "SMTP_PASSWORD": "Password",
    "SMTP_SECURITY": "Security",
}
PLACEHOLDERS = {"SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587", "SMTP_USER": "usually your email address", "SMTP_SECURITY": "starttls"}
HELP = {
    "brevo": "In Brevo, open SMTP &amp; API, then API keys, and create a key. Also verify your sender address in Brevo (it emails you a link).",
    "mailjet": "In Mailjet, click your name (top right), then Account settings, then API Key Management: it shows the API key and the Secret key. "
               "Then open Senders &amp; Domains, add your email address and click the link Mailjet sends you. No domain needed.",
    "resend": "In Resend, create an API key (API Keys), and add your own domain (Domains) with the DNS records it shows. "
              "The sender address must use that domain.",
    "smtp": "Your email service shows its server, port, user name and password on its SMTP settings page. "
            "<b>Railway blocks this on its free and hobby plans</b>: there, use Brevo, Mailjet or Resend.",
}

CSS = """
<style>
  #es-box { margin:14px 0 6px; padding:14px 16px 16px; border:1px solid var(--line); background:var(--panel); }
  #es-box h3 { margin:0 0 4px; font-size:15px; }
  #es-box .es-now { margin:8px 0 12px; font-size:13px; }
  #es-box .es-now b { color:var(--ok); }
  #es-box .es-now.no b { color:var(--bad); }
  #es-box .es-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:12px 16px; margin-top:8px; }
  #es-box .es-grid label { display:flex; flex-direction:column; gap:4px; font-size:12.5px; color:var(--muted); }
  #es-box .es-grid input, #es-box .es-grid select, #es-box #es-provider { box-sizing:border-box; width:100%; max-width:420px; }
  #es-box .es-f[hidden], #es-box .es-help[hidden] { display:none; }
  #es-box .es-help { margin-top:10px; font-size:12.5px; color:var(--muted); line-height:1.5; }
  #es-box .es-bar { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:14px; }
  #es-box .es-msg { font-size:13px; min-height:16px; }
  #es-box .es-msg.good { color:var(--ok); }
  #es-box .es-msg.bad { color:var(--bad); }
  @media (max-width: 640px) { #es-box input, #es-box select { font-size:16px; padding:11px 12px; } }
</style>
"""

JS = """
<script>
(function () {
  var box = document.getElementById('es-box'); if (!box) return;
  ['input', 'change'].forEach(function (ev) { box.addEventListener(ev, function (e) { e.stopPropagation(); }); });
  var sel = document.getElementById('es-provider'), msg = box.querySelector('.es-msg'), now = box.querySelector('.es-now');
  var from = document.getElementById('es-from'), save = document.getElementById('es-save'), clear = document.getElementById('es-clear'), test = document.getElementById('es-test');
  var NAMES = JSON.parse(box.getAttribute('data-names'));
  function say(t, cls) { msg.textContent = t || ''; msg.className = 'es-msg' + (cls ? ' ' + cls : ''); }
  function show() {
    [].forEach.call(box.querySelectorAll('.es-f, .es-help'), function (el) { el.hidden = el.getAttribute('data-for') !== sel.value; });
  }
  function banner(st) {
    var b = document.querySelector('#sec-emails .em-ready'); if (!b) return;
    b.className = 'em-ready ' + (st.configured ? 'ok' : 'no'); b.textContent = '';
    var strong = document.createElement('b');
    strong.textContent = st.configured ? 'Email sending is on.' : "Email sending isn't set up yet.";
    b.appendChild(strong); b.appendChild(document.createTextNode(st.configured ? ' The emails below go out as described.' : ' You can still edit and preview everything here; nothing is sent until you connect an email service above.'));
  }
  function paint(st) {
    now.className = 'es-now' + (st.configured ? '' : ' no'); now.textContent = '';
    var b = document.createElement('b'); b.textContent = st.configured ? ('Right now: ' + st.name + ' sends your emails.') : 'Right now: no email is sent.';
    now.appendChild(b);
    if (st.saved) now.appendChild(document.createTextNode(' (settings from this screen)'));
    else if (st.configured) now.appendChild(document.createTextNode(' (settings from Railway)'));
    [].forEach.call(box.querySelectorAll('[data-name]'), function (el) {
      var f = st.fields[el.getAttribute('data-name')] || {};
      if (el.type === 'password') { el.value = ''; el.placeholder = f.where === 'dashboard' ? ('Saved ' + (f.tail || '') + '. Leave empty to keep it.') : (f.where === 'railway' ? 'Set in Railway. Type here to replace it.' : ''); }
      else if (f.value !== undefined && f.where) el.value = f.value;
    });
    if (st.from_email) from.value = st.from_email;
    if (st.saved) sel.value = st.provider;
    show(); banner(st);
  }
  function post(url, body, done) {
    fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(done).catch(function () { say('Could not reach the server. Try again.', 'bad'); save.disabled = false; });
  }
  sel.addEventListener('change', function () { show(); say(''); });
  save.addEventListener('click', function () {
    var values = {};
    [].forEach.call(box.querySelectorAll('.es-f[data-for="' + sel.value + '"] [data-name]'), function (el) { values[el.getAttribute('data-name')] = el.value; });
    save.disabled = true; say('Saving…');
    post('/admin/email-service', { provider: sel.value, values: values, from_email: from.value }, function (x) {
      save.disabled = false;
      if (x.ok && x.j.success) { paint(x.j); say(x.j.message, 'good'); } else say(x.j.error || 'Could not save.', 'bad');
    });
  });
  var armed = false;
  clear.addEventListener('click', function () {
    if (!armed) { armed = true; clear.textContent = 'Click again to remove'; setTimeout(function () { armed = false; clear.textContent = 'Remove saved settings'; }, 4000); return; }
    armed = false; clear.textContent = 'Remove saved settings';
    post('/admin/email-service/clear', {}, function (x) { if (x.ok && x.j.success) { paint(x.j); say(x.j.message, 'good'); } else say(x.j.error || 'Could not remove.', 'bad'); });
  });
  test.addEventListener('click', function () {
    var to = (document.getElementById('em-test-to') || {}).value || '';
    if (!to) { say('Type your own address in "Send tests to" below, then press this again.', 'bad'); return; }
    say('Sending…');
    post('/admin/email/test', { to: to, kind: 'welcome' }, function (x) { say(x.j.message || x.j.error || 'No answer.', x.ok && x.j.success ? 'good' : 'bad'); });
  });
  show();
})();
</script>
"""


def render(service: dict) -> str:
    """The box, from `mail_providers.status(...)`."""
    service = service or {}
    fields = service.get("fields") or {}
    chosen = service.get("provider") if service.get("provider") in mp.PROVIDERS else "brevo"
    opts = "".join('<option value="%s"%s>%s</option>' % (p, " selected" if p == chosen else "", _esc(mp.NAMES[p] if p != "smtp" else "Any other email server (SMTP)"))
                   for p in mp.PROVIDERS)
    groups, helps = [], []
    for p in mp.PROVIDERS:
        inner = []
        for name, secret in mp.FIELDS[p]:
            f = fields.get(name) or {}
            label = LABELS[name] + ("" if name in mp.REQUIRED[p] else " (optional)")
            if name == "SMTP_SECURITY":
                cur = (f.get("value") or "starttls")
                inp = '<select data-name="%s">%s</select>' % (name, "".join(
                    '<option value="%s"%s>%s</option>' % (v, " selected" if v == cur else "", t)
                    for v, t in (("starttls", "starttls (port 587, the usual)"), ("ssl", "ssl (port 465)"), ("none", "none"))))
            elif secret:
                ph = ("Saved %s. Leave empty to keep it." % (f.get("tail") or "")) if f.get("where") == "dashboard" else (
                     "Set in Railway. Type here to replace it." if f.get("where") == "railway" else "")
                inp = '<input type="password" data-name="%s" autocomplete="new-password" placeholder="%s">' % (name, _esc(ph))
            else:
                inp = '<input type="text" data-name="%s" value="%s" placeholder="%s" autocomplete="off" maxlength="%d">' % (
                    name, _esc(f.get("value") or ""), _esc(PLACEHOLDERS.get(name, "")), mp.MAX_VALUE)
            inner.append("<label>%s%s</label>" % (_esc(label), inp))
        groups.append('<div class="es-f es-grid" data-for="%s"%s>%s</div>' % (p, "" if p == chosen else " hidden", "".join(inner)))
        helps.append('<div class="es-help" data-for="%s"%s>%s</div>' % (p, "" if p == chosen else " hidden", HELP[p]))
    configured = bool(service.get("configured"))
    where = " (settings from this screen)" if service.get("saved") else (" (settings from Railway)" if configured else "")
    now = ('<div class="es-now%s"><b>%s</b>%s</div>' % (
        "" if configured else " no",
        _esc("Right now: %s sends your emails." % service.get("name", "Brevo")) if configured else "Right now: no email is sent.", _esc(where)))
    return (
        CSS +
        '<div id="es-box" data-names="%s"><h3>Email service</h3>'
        '<div class="hint">Which company sends your emails. Pick one, paste the keys it gave you, and Save. '
        'Brevo and Mailjet are the easiest: no domain needed.</div>' % _esc(json.dumps(service.get("names") or {}), quote=True)
        + now +
        '<label for="es-provider" style="font-size:12.5px;color:var(--muted);">Service</label>'
        '<select id="es-provider">%s</select>' % opts
        + "".join(groups) +
        '<div class="es-grid" style="margin-top:12px;"><label>Sender address (the "from" of your emails)'
        '<input id="es-from" type="email" value="%s" placeholder="you@example.com" autocomplete="off" maxlength="254"></label></div>'
        % _esc(service.get("from_email") or "")
        + "".join(helps) +
        '<div class="es-bar"><button type="button" class="add-tier" style="margin-top:0;" id="es-save">Save</button>'
        '<button type="button" class="add-tier" style="margin-top:0;" id="es-test">Send a test email</button>'
        '<button type="button" class="add-tier" style="margin-top:0;" id="es-clear">Remove saved settings</button>'
        '<span class="es-msg" role="status"></span></div></div>' + JS
    )
