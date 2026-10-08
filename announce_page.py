"""
Credential Protocol — the Announce page.

Write one note, then choose: pin it at the top of every member's page, and/or
email it to a group (everyone, one tier, or the holders of one event's
tickets). Emails go out in the background; the page shows the progress.

This file only draws the page. credential_api.py does the work
(/admin/announce/post, /unpin, /preview, /test, /status).
"""

import json
from html import escape


def render(theme_css: str, theme_js: str, body_attrs: str, title: str, state: dict) -> str:
    data = json.dumps(state).replace("<", "\\u003c")
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Announce — Admin</title>
<style>
  body {{ background:var(--bg); color:var(--fg); font-family:var(--font); padding:32px; }}
  h1 {{ color:var(--accent-text); font-size:16px; letter-spacing:2px; text-transform:uppercase; }}
  h2 {{ color:var(--accent-text); font-size:12px; letter-spacing:2px; text-transform:uppercase; margin:28px 0 8px; }}
  .nav {{ margin-bottom:18px; font-size:11px; letter-spacing:1px; }}
  .nav a {{ color:var(--accent-text); text-decoration:none; margin-right:18px; }}
  .nav a:hover {{ text-decoration:underline; }}
  .an {{ max-width:640px; }}
  .an .hint {{ color:var(--muted); font-size:12px; line-height:1.6; margin:6px 0; }}
  .an label {{ display:block; color:var(--muted); font-size:11px; letter-spacing:1px; text-transform:uppercase; margin:14px 0 4px; }}
  .an input[type=text], .an input[type=url], .an input[type=email], .an textarea, .an select {{ width:100%; box-sizing:border-box; background:var(--field);
    border:1px solid var(--line); color:var(--fg); font-family:var(--font); font-size:16px; padding:10px 12px; border-radius:var(--radius, 0); }}
  .an textarea {{ min-height:130px; resize:vertical; line-height:1.5; }}
  .an .opt {{ display:flex; gap:10px; align-items:flex-start; color:var(--fg); font-size:14px; text-transform:none; letter-spacing:0; margin:12px 0 4px; cursor:pointer; }}
  .an .opt input {{ margin-top:3px; }}
  .an .sub {{ margin:6px 0 0 26px; }}
  .an-btn {{ background:var(--accent); border:1px solid var(--accent-text); color:var(--on-accent); font-family:var(--font); font-size:13px;
    padding:12px 18px; cursor:pointer; border-radius:var(--radius, 0); }}
  .an-btn.ghost {{ background:transparent; color:var(--accent-text); }}
  .an-btn:disabled {{ opacity:.5; cursor:default; }}
  .an-row {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin:14px 0; }}
  .an-row input[type=email] {{ flex:1 1 200px; min-width:0; width:auto; }}
  #an-msg {{ min-height:18px; font-size:13px; margin-top:6px; }}
  .an-card {{ border:1px solid var(--line); border-left:3px solid var(--accent-text); padding:12px 14px; margin:8px 0; border-radius:var(--radius, 0); background:var(--panel); }}
  .an-card .t {{ font-weight:700; margin-bottom:4px; }}
  .an-card .x {{ font-size:13px; line-height:1.55; white-space:pre-wrap; overflow-wrap:anywhere; color:var(--soft); }}
  .an-card .m {{ font-size:11px; color:var(--muted); margin-top:6px; }}
  .an-card button {{ margin-top:8px; background:transparent; border:1px solid var(--line2); color:var(--soft); font-family:var(--font); font-size:12px; padding:6px 10px; cursor:pointer; }}
  .an-hist {{ border-bottom:1px solid var(--line); padding:10px 0; font-size:13px; }}
  .an-hist .m {{ color:var(--muted); font-size:11px; margin-top:3px; }}
  .an-prog {{ height:6px; background:var(--field); border:1px solid var(--line); margin-top:6px; }}
  .an-prog > i {{ display:block; height:100%; background:var(--accent); width:0; }}
  .warn {{ background:var(--warn-bg); color:var(--warn); font-size:12px; line-height:1.6; padding:10px 14px; margin:14px 0 0; }}
  #an-frame {{ display:none; width:100%; height:520px; border:1px solid var(--line); margin-top:10px; background:var(--frame-bg); }}
{theme_css}</style></head>
<body {body_attrs}>
  <div class="nav"><a href="/admin/dashboard">← Dashboard</a><a href="/admin/members">Members →</a><a href="/admin/content">Content →</a><a href="/admin/logout">Log out</a></div>
  <h1>{escape(title)} — Announce</h1>
  <div class="an">
    <div class="hint">Tell your members about something new, like a new post or upload. Pin it at the top of their page, email it to a group, or both.</div>

    <h2>Pinned now</h2>
    <div id="an-current"></div>

    <h2>Write it</h2>
    <label for="an-title">Title (optional)</label>
    <input type="text" id="an-title" maxlength="80" placeholder="New photo set is up">
    <label for="an-text">Message</label>
    <textarea id="an-text" maxlength="1500" placeholder="Write a few lines. Members see it as you type it."></textarea>
    <label for="an-link">Link (optional)</label>
    <input type="url" id="an-link" maxlength="500" placeholder="https://...">

    <label class="opt"><input type="checkbox" id="an-pin" checked> <span>Pin it at the top of every member's page<span class="hint sub" style="display:block;margin:2px 0 0;font-weight:400;">It replaces the note that is pinned now. Only people with a working card see it.</span></span></label>
    <label class="opt"><input type="checkbox" id="an-email"> <span>Also email it to…</span></label>
    <div class="sub"><select id="an-group" aria-label="Who gets the email"></select></div>
    <div class="hint sub" id="an-email-note"></div>

    <div class="an-row">
      <button type="button" class="an-btn" id="an-post">Post</button>
      <button type="button" class="an-btn ghost" id="an-preview">Preview the email</button>
    </div>
    <div id="an-msg" role="status" aria-live="polite"></div>
    <div class="an-prog" id="an-prog" style="display:none"><i></i></div>

    <div class="an-row">
      <input type="email" id="an-test-to" placeholder="send a test email to this address" aria-label="Test address">
      <button type="button" class="an-btn ghost" id="an-test">Send test</button>
    </div>
    <iframe id="an-frame" sandbox="" title="Email preview"></iframe>

    <h2>Sent before</h2>
    <div id="an-history"></div>
  </div>
  <script type="application/json" id="an-data">{data}</script>
  <script>
  (function () {{
    var $ = function (id) {{ return document.getElementById(id); }};
    var S = JSON.parse($('an-data').textContent), timer = null;
    function el(tag, cls, text) {{ var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }}
    function say(t, good) {{ var m = $('an-msg'); m.textContent = t || ''; m.style.color = good ? 'var(--ok)' : 'var(--bad)'; }}
    function post(url, body) {{
      return fetch(url, {{ method: 'POST', credentials: 'same-origin', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify(body || {{}}) }})
        .then(function (r) {{ return r.json().then(function (j) {{ return {{ status: r.status, body: j }}; }}); }});
    }}
    function when(iso) {{ return String(iso || '').slice(0, 16).replace('T', ' ') + ' UTC'; }}

    function drawGroups() {{
      var sel = $('an-group'), keep = sel.value; sel.textContent = '';
      (S.groups || []).forEach(function (g) {{ var o = document.createElement('option'); o.value = g.key; o.textContent = g.label + ' (' + g.count + ')'; sel.appendChild(o); }});
      if (keep) sel.value = keep;
      var ok = !!S.email_ready;
      $('an-email').disabled = !ok; sel.disabled = !ok || !$('an-email').checked; $('an-test').disabled = !ok; $('an-test-to').disabled = !ok;
      $('an-email-note').textContent = ok ? 'Each person gets one email, with their own access link in it.'
        : 'Email is not set up on this server yet, so you can only pin for now (see SETUP.md to set email up).';
      if (!ok) $('an-email').checked = false;
    }}
    function drawCurrent() {{
      var box = $('an-current'); box.textContent = '';
      var c = S.current;
      if (!c) {{ var n = el('div', 'hint', 'Nothing is pinned right now.'); box.appendChild(n); return; }}
      var card = el('div', 'an-card');
      if (c.title) card.appendChild(el('div', 't', c.title));
      card.appendChild(el('div', 'x', c.text));
      card.appendChild(el('div', 'm', 'Pinned ' + when(c.posted_at)));
      var b = el('button', '', 'Unpin it'); b.type = 'button';
      b.onclick = function () {{ b.disabled = true; post('/admin/announce/unpin').then(function (r) {{ if (r.body.success) {{ S.current = null; drawCurrent(); say('Unpinned.', true); }} else {{ b.disabled = false; say(r.body.error || 'Failed.', false); }} }}); }};
      card.appendChild(b); box.appendChild(card);
    }}
    function drawHistory() {{
      var box = $('an-history'); box.textContent = '';
      if (!(S.history || []).length) {{ box.appendChild(el('div', 'hint', 'Nothing yet.')); return; }}
      S.history.forEach(function (h) {{
        var row = el('div', 'an-hist');
        row.appendChild(el('div', '', h.title || (h.text || '').slice(0, 70) || '(no text)'));
        var bits = [when(h.posted_at)];
        if (h.pinned) bits.push('pinned');
        var e = h.email;
        if (e) {{
          if (e.interrupted) bits.push('email stopped early: ' + e.sent + ' of ' + e.total + ' sent');
          else if (!e.done) bits.push('emailing ' + e.group_label + '… ' + (e.sent + e.failed) + ' of ' + e.total + ' done');
          else bits.push('emailed ' + e.group_label + ': ' + e.sent + ' of ' + e.total + ' sent' + (e.failed ? ', ' + e.failed + ' failed' : ''));
          if (e.failed && e.first_error) bits.push('first problem: ' + e.first_error);
        }}
        row.appendChild(el('div', 'm', bits.join(' · ')));
        box.appendChild(row);
      }});
    }}
    function progress() {{
      var run = (S.history || []).filter(function (h) {{ return h.email && !h.email.done && !h.email.interrupted; }})[0];
      var p = $('an-prog');
      if (!run) {{ p.style.display = 'none'; return false; }}
      p.style.display = ''; p.firstChild.style.width = Math.round(100 * (run.email.sent + run.email.failed) / Math.max(1, run.email.total)) + '%';
      return true;
    }}
    function refresh() {{
      return fetch('/admin/announce/status', {{ credentials: 'same-origin' }}).then(function (r) {{ return r.json(); }}).then(function (j) {{
        if (!j.success) return;
        S.current = j.current; S.history = j.history; S.groups = j.groups; S.email_ready = j.email_ready;
        drawCurrent(); drawHistory(); drawGroups();
        if (progress()) {{ clearTimeout(timer); timer = setTimeout(refresh, 1500); }} else if (S._wasRunning) {{ S._wasRunning = false; say('The emails have all been sent.', true); }}
        S._wasRunning = S._wasRunning || false;
      }}).catch(function () {{}});
    }}
    $('an-email').addEventListener('change', function () {{ $('an-group').disabled = !$('an-email').checked || !S.email_ready; }});

    function fields() {{ return {{ title: $('an-title').value, text: $('an-text').value, link: $('an-link').value }}; }}
    $('an-post').addEventListener('click', function () {{
      var f = fields(), pin = $('an-pin').checked, mail = $('an-email').checked && S.email_ready;
      if (!f.title.trim() && !f.text.trim()) {{ say('Write a title or a message first.', false); return; }}
      if (!pin && !mail) {{ say('Tick "Pin it" and/or "Also email it".', false); return; }}
      var g = (S.groups || []).filter(function (x) {{ return x.key === $('an-group').value; }})[0];
      if (mail && (!g || !g.count)) {{ say('Nobody is in that group right now.', false); return; }}
      var q = 'Post this' + (pin ? ' and pin it' : '') + (mail ? (pin ? ', and' : '') + ' email it to ' + g.count + ' ' + (g.count === 1 ? 'person' : 'people') + ' (' + g.label + ')' : '') + '?';
      if (!window.confirm(q)) return;
      $('an-post').disabled = true; say('Posting…', true);
      post('/admin/announce/post', Object.assign({{ pin: pin, email: mail, group: $('an-group').value }}, f)).then(function (r) {{
        $('an-post').disabled = false;
        if (!r.body.success) {{ say(r.body.error || 'Failed.', false); return; }}
        say(mail ? 'Posted. Sending ' + r.body.total + ' emails now. You can leave this page; it keeps going.' : 'Posted and pinned.', true);
        $('an-title').value = ''; $('an-text').value = ''; $('an-link').value = '';
        S._wasRunning = !!mail; refresh();
      }}).catch(function () {{ $('an-post').disabled = false; say('Could not reach the server.', false); }});
    }});
    $('an-preview').addEventListener('click', function () {{
      var f = fields(); if (!f.title.trim() && !f.text.trim()) {{ say('Write a title or a message first.', false); return; }}
      say('Loading preview…', true);
      post('/admin/announce/preview', f).then(function (r) {{
        if (!r.body.success) {{ say(r.body.error || 'Preview failed.', false); return; }}
        $('an-frame').srcdoc = r.body.html; $('an-frame').style.display = 'block'; say('Subject: ' + r.body.subject, true);
      }});
    }});
    $('an-test').addEventListener('click', function () {{
      var a = $('an-test-to').value.trim(), f = fields();
      if (!a || a.indexOf('@') < 1) {{ say('Type the address to send the test to.', false); return; }}
      if (!f.title.trim() && !f.text.trim()) {{ say('Write a title or a message first.', false); return; }}
      $('an-test').disabled = true; say('Sending…', true);
      post('/admin/announce/test', Object.assign({{ to: a }}, f)).then(function (r) {{ $('an-test').disabled = !S.email_ready; say(r.body.message || r.body.error || 'Failed.', !!r.body.success); }})
        .catch(function () {{ $('an-test').disabled = false; say('Could not reach the server.', false); }});
    }});

    drawCurrent(); drawHistory(); drawGroups(); if (progress()) {{ S._wasRunning = true; timer = setTimeout(refresh, 1500); }}
  }})();
  </script>
  {theme_js}
</body></html>"""
