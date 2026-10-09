"""
Credential Protocol: the Emails screen of the dashboard (Settings > Emails).

One short list instead of a long form per email. Each row names the email,
says when it is sent and whether it is on; Edit opens just that email (subject,
message, clickable {placeholder} chips, Preview, Send test, Reset to standard
words). The fields are ordinary form inputs named after their settings keys, so
the page's normal "Save changes" button saves them (the list is built from
email_templates.registry()).
"""

from html import escape as _esc

import email_templates as et

CHIP_HELP = {
    "name": "The member's name", "tier": "The card's name", "creator": "Your creator name",
    "brand": "Your card title", "expires": "The date access ends", "days": "How many days",
    "event": "The event's name", "when": "Date and time of the event", "place": "Where it is",
    "drop": "The drop's name", "edition": "The number, like #37 of 100",
    "price": "The price", "reference": "Their payment reference",
}

CSS = """
<style>
  #sec-emails .em-ready { margin:10px 0 4px; padding:10px 14px; border:1px solid var(--line); background:var(--panel); font-size:13px; }
  #sec-emails .em-ready.ok b { color:var(--ok); }
  #sec-emails .em-ready.no b { color:var(--bad); }
  #sec-emails .em-test { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin:12px 0 4px; }
  #sec-emails .em-test label { margin:0; }
  #sec-emails .em-test input { max-width:280px; width:100%; box-sizing:border-box; }
  #sec-emails .em-group { margin:22px 0 8px; font-size:12px; letter-spacing:1.4px; text-transform:uppercase; color:var(--accent-text); }
  #sec-emails .em-list { display:flex; flex-direction:column; gap:10px; }
  #sec-emails .em-row { background:var(--panel); border:1px solid var(--line); border-radius:var(--radius-lg, 0); }
  #sec-emails .em-head { display:flex; align-items:center; gap:14px; padding:12px 16px; flex-wrap:wrap; }
  #sec-emails .em-main { flex:1 1 260px; min-width:0; }
  #sec-emails .em-title { font-weight:600; }
  #sec-emails .em-tag { margin-left:8px; font-size:10px; letter-spacing:1px; text-transform:uppercase; color:var(--accent-text); border:1px solid var(--accent-text); padding:1px 6px; font-weight:400; }
  #sec-emails .em-when { color:var(--muted); font-size:12.5px; margin-top:2px; }
  #sec-emails .em-state { font-size:12.5px; white-space:nowrap; color:var(--muted); }
  #sec-emails .em-state.on { color:var(--ok); }
  #sec-emails .em-panel { padding:2px 16px 16px; border-top:1px solid var(--line); }
  #sec-emails .em-panel input, #sec-emails .em-panel textarea, #sec-emails .em-panel select { width:100%; box-sizing:border-box; }
  #sec-emails .em-chips { margin-top:10px; font-size:12px; color:var(--muted); display:flex; gap:6px; flex-wrap:wrap; align-items:center; }
  #sec-emails .em-chip-btn { font-family:inherit; font-size:12px; padding:3px 9px; cursor:pointer; background:transparent; border:1px solid var(--line); color:var(--fg, inherit); border-radius:999px; }
  #sec-emails .em-chip-btn:hover { border-color:var(--accent-text); color:var(--accent-text); }
  #sec-emails .em-note { margin-top:10px; font-size:12.5px; color:var(--muted); }
  #sec-emails .em-actions { margin-top:12px; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  #sec-emails .em-status { margin-top:8px; min-height:14px; font-size:12.5px; }
  #sec-emails .em-frame { display:none; width:100%; height:560px; border:1px solid var(--line); margin-top:10px; background:var(--frame-bg); }
  @media (max-width: 640px) {
    #sec-emails .em-head { padding:12px; gap:8px; }
    #sec-emails .em-panel { padding:2px 12px 14px; }
    #sec-emails .em-panel input, #sec-emails .em-panel textarea, #sec-emails .em-panel select { font-size:16px; padding:11px 12px; }
  }
</style>
"""

JS = """
<script>
(function () {
  var root = document.getElementById('sec-emails'); if (!root) return;
  var rows = [].slice.call(root.querySelectorAll('.em-row'));
  var testTo = document.getElementById('em-test-to');
  function post(url, body) {
    return fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body) }).then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); });
  }
  function closeRow(r) {
    r.querySelector('.em-panel').hidden = true; r.classList.remove('open');
    r.querySelector('.em-edit').textContent = 'Edit';
  }
  rows.forEach(function (row) {
    var panel = row.querySelector('.em-panel'), editBtn = row.querySelector('.em-edit');
    var status = row.querySelector('.em-status'), frame = row.querySelector('.em-frame');
    var last = null;
    function say(t, good) { status.textContent = t; status.style.color = good ? 'var(--ok)' : 'var(--bad)'; }
    function values() {
      var o = { kind: row.getAttribute('data-kind') };
      [].forEach.call(panel.querySelectorAll('[name]'), function (el) { o[el.name] = el.value; });
      return o;
    }
    editBtn.addEventListener('click', function () {
      var wasClosed = panel.hidden;
      rows.forEach(closeRow);
      if (wasClosed) {
        panel.hidden = false; row.classList.add('open'); editBtn.textContent = 'Close';
        if (row.scrollIntoView) row.scrollIntoView({ block: 'nearest' });
      }
    });
    // A box the browser rejects (e.g. "days" typed as 99) inside a closed email: open that email so the person sees it.
    panel.addEventListener('invalid', function () {
      if (!panel.hidden) return;
      rows.forEach(closeRow); panel.hidden = false; row.classList.add('open'); editBtn.textContent = 'Close';
    }, true);
    panel.addEventListener('focusin', function (e) {
      if (e.target.matches('textarea, input[type=text], input:not([type]), input[type=url]')) last = e.target;
    });
    [].forEach.call(panel.querySelectorAll('.em-chip-btn'), function (chip) {
      chip.addEventListener('mousedown', function (e) { e.preventDefault(); });
      chip.addEventListener('click', function () {
        var t = last || panel.querySelector('textarea');
        if (!t) return;
        var ins = chip.getAttribute('data-ins'), s = t.selectionStart, e2 = t.selectionEnd;
        if (typeof s !== 'number') { s = e2 = t.value.length; }
        t.value = t.value.slice(0, s) + ins + t.value.slice(e2);
        t.focus(); t.selectionStart = t.selectionEnd = s + ins.length;
        t.dispatchEvent(new Event('input', { bubbles: true }));
      });
    });
    var reset = row.querySelector('.em-reset');
    if (reset) reset.addEventListener('click', function () {
      [].forEach.call(panel.querySelectorAll('[data-default]'), function (el) { el.value = el.getAttribute('data-default'); });
      say('Standard words put back. Press “Save changes” to keep them.', true);
    });
    var pv = row.querySelector('.em-preview'), tt = row.querySelector('.em-testbtn');
    pv.addEventListener('click', function () {
      pv.disabled = true; say('Loading preview…', true);
      post('/admin/email/preview', values()).then(function (res) {
        pv.disabled = false;
        if (!res.body.success) { say(res.body.error || 'Preview failed.', false); return; }
        frame.srcdoc = res.body.html; frame.style.display = 'block';
        say('Subject: ' + res.body.subject, true);
      }).catch(function () { pv.disabled = false; say('Could not reach the server.', false); });
    });
    tt.addEventListener('click', function () {
      var addr = (testTo.value || '').trim();
      if (!addr || addr.indexOf('@') < 1) { say('Type the address to send tests to (at the top of this screen).', false); testTo.focus(); return; }
      tt.disabled = true; say('Sending…', true);
      post('/admin/email/test', Object.assign({ to: addr }, values())).then(function (res) {
        tt.disabled = false; say(res.body.message || res.body.error || 'Failed.', !!res.body.success);
      }).catch(function () { tt.disabled = false; say('Could not reach the server.', false); });
    });
  });
})();
</script>
"""


def _field_html(f: dict, value: str, tier_names=()) -> str:
    name, ident = f["name"], "em-" + f["name"].replace("_", "-")
    label = '<label for="%s">%s</label>' % (ident, _esc(f["label"]))
    d = (' data-default="%s"' % _esc(f["default"], quote=True)) if f["type"] in ("text", "area") and f["default"] else ""
    if f["type"] == "area":
        rows = 2 if name == "email_signoff" else 3
        inp = '<textarea name="%s" id="%s" rows="%d" maxlength="%d"%s>%s</textarea>' % (
            name, ident, rows, f["maxlen"], d, _esc(value))
    elif f["type"] == "select":
        opts = "".join('<option value="%s"%s>%s</option>' % (_esc(v, quote=True), " selected" if v == value else "", _esc(t))
                       for v, t in f["options"])
        inp = '<select name="%s" id="%s">%s</select>' % (name, ident, opts)
    elif f["type"] == "tier":
        names = [n for n in tier_names if n]
        if value and value not in names:
            names.append(value)          # a card that was renamed or removed still shows what is saved
        opts = '<option value=""%s>Everyone</option>' % ("" if value else " selected") + "".join(
            '<option value="%s"%s>Only %s</option>' % (_esc(n, quote=True), " selected" if n == value else "", _esc(n))
            for n in names)
        inp = '<select name="%s" id="%s">%s</select>' % (name, ident, opts)
    elif f["type"] == "number":
        inp = '<input name="%s" id="%s" type="number" min="0" max="60" step="1" value="%s" style="max-width:110px;">' % (
            name, ident, _esc(value, quote=True))
    elif f["type"] == "url":
        inp = '<input name="%s" id="%s" type="url" maxlength="%d" placeholder="https://..." value="%s">' % (
            name, ident, f["maxlen"], _esc(value, quote=True))
    else:
        inp = '<input name="%s" id="%s" type="text" maxlength="%d"%s value="%s">' % (
            name, ident, f["maxlen"], d, _esc(value, quote=True))
    return label + inp


def _row_html(kind: dict, values: dict, tier_names=()) -> str:
    label, on = et.state_text(kind, values)
    edited = et.is_edited(kind, values)
    fields = "".join(_field_html(f, values.get(f["name"], ""), tier_names) for f in kind["fields"])
    chips = ""
    if kind["chips"]:
        chips = ('<div class="em-chips">Add to the text: ' + "".join(
            '<button type="button" class="em-chip-btn" data-ins="{%s}" title="%s">%s</button>' % (
                c, _esc(CHIP_HELP.get(c, ""), quote=True), c) for c in kind["chips"]) + "</div>")
    note = ('<div class="em-note">%s</div>' % _esc(kind["note"])) if kind.get("note") else ""
    has_default = any(f["type"] in ("text", "area") and f["default"] for f in kind["fields"])
    reset = '<button type="button" class="add-tier em-reset" style="margin-top:0;">Reset to standard words</button>' if has_default else ""
    return (
        '<div class="em-row" data-kind="%s">'
        '<div class="em-head"><div class="em-main"><div class="em-title">%s%s</div><div class="em-when">%s</div></div>'
        '<div class="em-state%s">%s</div>'
        '<button type="button" class="mini em-edit">Edit</button></div>'
        '<div class="em-panel" hidden>%s%s%s'
        '<div class="em-actions"><button type="button" class="add-tier em-preview" style="margin-top:0;">Preview →</button>'
        '<button type="button" class="add-tier em-testbtn" style="margin-top:0;">Send test</button>%s</div>'
        '<div class="em-status"></div><iframe class="em-frame" sandbox="" title="Email preview"></iframe></div></div>'
    ) % (kind["key"], _esc(kind["title"]), ' <span class="em-tag">Edited</span>' if edited else "",
         _esc(kind["when"]), " on" if on else "", _esc(label), fields, chips, note, reset)


def section_html(cfg_values: dict, email_ready: bool) -> str:
    """The whole Emails section. `cfg_values` is a dict of the dashboard's
    current settings (email_templates.values_for-style values are filled in here)."""
    values = et.values_for(cfg_values)
    # the older kinds keep non-string values in the dashboard's settings; values_for already stringifies
    reg = et.registry()
    tier_names = [str(t.get("name") or "") for t in (cfg_values.get("tiers") or []) if isinstance(t, dict)]
    ready = ('<div class="em-ready ok"><b>Email sending is on.</b> The emails below go out as described.</div>'
             if email_ready else
             '<div class="em-ready no"><b>Email sending isn\'t set up yet.</b> You can still edit and preview everything here; '
             'nothing is sent until you add your email key (see SETUP.md).</div>')
    groups = []
    for gkey, gtitle in et.GROUPS:
        rows = "".join(_row_html(k, values, tier_names) for k in reg if k["group"] == gkey)
        groups.append('<h3 class="em-group">%s</h3><div class="em-list">%s</div>' % (_esc(gtitle), rows))
    return (
        '<section class="dsec" id="sec-emails" data-title="Emails">' + CSS +
        '<h2>Emails</h2>'
        '<div class="hint">Every email your members get, in one place. Press <b>Edit</b> to change one. '
        'Leave a box as it is to keep the standard words. Preview and Send test use what is typed, even before you save.</div>'
        + ready +
        '<div class="em-test"><label for="em-test-to">Send tests to</label>'
        '<input id="em-test-to" type="email" placeholder="your own address" autocomplete="email"></div>'
        + "".join(groups) +
        '<div class="hint" style="margin-top:18px;">News emails (a note to all or some of your members) are written on the '
        '<a href="/admin/announce" style="color:var(--accent-text);">News</a> page.</div>'
        + JS + '</section>'
    )
