"""
Credential Protocol: the "More looks" screen (under Design). It lists the ready-made card looks and email
looks from packs.py, and its Add buttons copy one into this site's own settings. Everything shown comes from
a cleaned list and is put on the page as text (textContent), never as HTML. The rules are in packs.py;
credential_api.py does the HTTP.
"""

import json
from html import escape as esc_html

import admin_theme


def _json_for_script(obj) -> str:
    return (json.dumps(obj).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def render(theme_css: str, theme_js: str, body_attrs: str, title: str, state: dict) -> str:
    return (_TEMPLATE
            .replace("__TITLE__", esc_html(title))
            .replace("__THEME__", theme_css)
            .replace("__NAV__", admin_theme.nav_html("packs"))
            .replace("__BODY_ATTRS__", body_attrs)
            .replace("__THEME_JS__", theme_js)
            .replace("__STATE__", _json_for_script(state)))


_TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>More looks — Admin</title>
<style>
  body { background:var(--bg); color:var(--fg); font-family:var(--font); padding:32px; max-width:900px; margin:0 auto; }
  h1 { color:var(--accent-text); font-size:16px; letter-spacing:2px; text-transform:uppercase; margin-bottom:4px; }
  h2 { font-size:12px; letter-spacing:2px; text-transform:uppercase; color:var(--soft); margin:28px 0 6px; }
  .nav { margin-bottom:18px; font-size:11px; letter-spacing:1px; }
  .nav a { color:var(--accent-text); text-decoration:none; margin-right:18px; }
  .nav a:hover { text-decoration:underline; }
  .hint { color:var(--muted); font-size:12px; line-height:1.6; margin:6px 0; }
  .hint b { color:var(--soft); }
  button { font-family:var(--font); cursor:pointer; }
  .small { display:inline-block; background:transparent; border:1px solid var(--line); color:var(--soft); font-size:10px; letter-spacing:1px;
           text-transform:uppercase; padding:7px 11px; border-radius:var(--radius, 0); }
  .small:hover { border-color:var(--accent-text); color:var(--accent-text); }
  .btn { background:var(--accent); color:var(--on-accent); border:none; font-size:11px; letter-spacing:1.5px; text-transform:uppercase; padding:10px 16px; border-radius:var(--radius, 0); }
  .btn:disabled { opacity:.5; cursor:default; }
  .note { background:var(--warn-bg); color:var(--warn); font-size:12px; line-height:1.6; padding:10px 14px; margin:10px 0; border-radius:var(--radius, 0); }
  .grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(240px, 1fr)); gap:14px; margin-top:12px; }
  .tile { border:1px solid var(--line); background:var(--panel); padding:12px; border-radius:var(--radius, 0); display:flex; flex-direction:column; gap:8px; min-width:0; }
  .tile .nm { font-size:14px; overflow-wrap:anywhere; }
  .tile .ds { color:var(--muted); font-size:12px; line-height:1.5; flex:1; overflow-wrap:anywhere; }
  .tile .ok { color:var(--ok); font-size:11px; letter-spacing:1px; text-transform:uppercase; }
  .pv-card { position:relative; height:92px; border-radius:8px; overflow:hidden; border:1px solid rgba(128,128,128,.35); }
  .pv-card i { position:absolute; left:0; top:0; bottom:0; width:16%; }
  .pv-card b { position:absolute; left:22%; top:18px; width:46%; height:9px; border-radius:3px; opacity:.9; }
  .pv-card u { position:absolute; left:22%; top:36px; width:30%; height:6px; border-radius:3px; opacity:.5; text-decoration:none; }
  .pv-card s { position:absolute; right:12px; bottom:12px; width:26px; height:26px; border-radius:4px; background:#fff; opacity:.9; }
  .pv-mail { position:relative; height:92px; border-radius:6px; overflow:hidden; border:1px solid rgba(128,128,128,.35); }
  .pv-mail b { position:absolute; left:14px; top:14px; width:50%; height:8px; border-radius:3px; opacity:.9; }
  .pv-mail u { position:absolute; left:14px; top:30px; width:70%; height:5px; border-radius:3px; opacity:.5; text-decoration:none; box-shadow:0 10px 0 currentColor; }
  .pv-mail s { position:absolute; left:14px; bottom:12px; width:70px; height:18px; border-radius:4px; }
  .pv-dash { position:relative; height:92px; border-radius:6px; overflow:hidden; border:1px solid rgba(128,128,128,.35); }
  .pv-dash i { position:absolute; left:12px; right:12px; top:12px; bottom:0; border-radius:6px 6px 0 0; }
  .pv-dash b { position:absolute; left:24px; top:26px; width:44%; height:8px; border-radius:3px; opacity:.9; }
  .pv-dash u { position:absolute; left:24px; top:42px; width:62%; height:5px; border-radius:3px; opacity:.5; text-decoration:none; box-shadow:0 10px 0 currentColor; }
  .msg { font-size:12px; min-height:1.2em; margin-top:10px; }
  .msg.ok { color:var(--ok); } .msg.err { color:var(--bad); }
  .empty { color:var(--muted); font-size:13px; padding:12px 0; }
__THEME__</style>
</head>
<body __BODY_ATTRS__>
__NAV__
<h1>__TITLE__ — More looks</h1>
<p class="hint">Ready-made designs you can add with one press. A <b>card look</b> is added to your list under <b>Design &gt; Card looks</b>, where you can change it or pick it for a card. An <b>email look</b> sets the colours and type of the emails you send (it replaces your current email look; you can change it again under Settings &gt; Emails). Nothing changes on cards or emails that were already sent. New looks can appear here from time to time without you having to update anything.</p>
<div id="note"></div>
<div><button type="button" class="small" id="refresh">Check for new looks</button></div>
<div class="msg" id="msg" role="status"></div>
<h2>Card looks</h2>
<div class="grid" id="g-card"></div>
<h2>Email looks</h2>
<div class="grid" id="g-email"></div>
<h2>Dashboard styles</h2>
<p class="hint">Colours for this admin dashboard. An added style shows up under <b>Design &gt; Dashboard style</b> next to the built-in ones, and you pick it there. You can keep up to 6; press Remove on one you no longer want. Your guests' cards and emails are not affected.</p>
<div class="grid" id="g-style"></div>
<script id="init-state" type="application/json">__STATE__</script>
<script>
(function () {
  var S = JSON.parse(document.getElementById('init-state').textContent);
  var $ = function (id) { return document.getElementById(id); };
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function say(t, good) { var m = $('msg'); m.textContent = t || ''; m.className = 'msg ' + (good ? 'ok' : 'err'); }
  function color(v, d) { return /^#[0-9a-f]{6}$/i.test(v || '') ? v : d; }
  function preview(p) {
    var sw = p.swatch || {}, bg = color(sw.bg, '#222222'), fg = color(sw.fg, '#ffffff'), ac = color(sw.accent, '#00e87a');
    var box;
    if (p.kind === 'card_look') {
      box = el('div', 'pv-card'); box.style.background = bg;
      var a = el('i'); a.style.background = ac; var b = el('b'); b.style.background = fg; var u = el('u'); u.style.background = fg; var s = el('s');
      [a, b, u, s].forEach(function (n) { box.appendChild(n); });
    } else if (p.kind === 'admin_style') {
      box = el('div', 'pv-dash'); box.style.background = ac; box.style.color = fg;
      var pn = el('i'); pn.style.background = bg; var b3 = el('b'); b3.style.background = fg; var u3 = el('u'); u3.style.background = fg;
      [pn, b3, u3].forEach(function (n) { box.appendChild(n); });
    } else {
      box = el('div', 'pv-mail'); box.style.background = bg; box.style.color = fg;
      var b2 = el('b'); b2.style.background = fg; var u2 = el('u'); u2.style.background = fg; var s2 = el('s'); s2.style.background = ac;
      [b2, u2, s2].forEach(function (n) { box.appendChild(n); });
    }
    return box;
  }
  function add(p, btn, confirmed) {
    btn.disabled = true; say('');
    fetch('/admin/packs/add', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: p.id, confirm: !!confirmed }) })
      .then(function (r) { return r.json().then(function (j) { return { s: r.status, j: j }; }); })
      .then(function (r) {
        btn.disabled = false;
        if (r.j && r.j.needs_confirm) { if (window.confirm(r.j.error)) add(p, btn, true); return; }
        if (!r.j || !r.j.success) { say((r.j && r.j.error) || 'That did not work.', false); return; }
        S = r.j.state; say(r.j.message, true); draw();
      })
      .catch(function () { btn.disabled = false; say('Could not reach the server.', false); });
  }
  function remove(p, btn) {
    if (!window.confirm('Remove \u201c' + p.name + '\u201d? If your dashboard uses it, it goes back to the standard look.')) return;
    btn.disabled = true; say('');
    fetch('/admin/packs/remove', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: p.id }) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        btn.disabled = false;
        if (!j || !j.success) { say((j && j.error) || 'That did not work.', false); return; }
        S = j.state; say(j.message, true); draw();
      })
      .catch(function () { btn.disabled = false; say('Could not reach the server.', false); });
  }
  function tile(p) {
    var t = el('div', 'tile'); t.appendChild(preview(p)); t.appendChild(el('div', 'nm', p.name)); t.appendChild(el('div', 'ds', p.description));
    if (p.kind === 'admin_style') {
      if (p.added) {
        t.appendChild(el('div', 'ok', 'Added. Pick it under Design > Dashboard style'));
        var rb = el('button', 'small', 'Remove'); rb.type = 'button'; rb.addEventListener('click', function () { remove(p, rb); }); t.appendChild(rb);
      } else {
        var ab = el('button', 'btn', 'Add this style'); ab.type = 'button'; ab.addEventListener('click', function () { add(p, ab, false); }); t.appendChild(ab);
      }
      return t;
    }
    if (p.added) t.appendChild(el('div', 'ok', p.kind === 'card_look' ? 'Added to your card looks' : 'In use or used before'));
    var b = el('button', p.added ? 'small' : 'btn', p.added ? (p.kind === 'card_look' ? 'Add another copy' : 'Use it again') : (p.kind === 'card_look' ? 'Add to my looks' : 'Use this email look'));
    b.type = 'button'; b.addEventListener('click', function () { add(p, b, false); }); t.appendChild(b);
    return t;
  }
  function fill(id, kind) {
    var g = $(id); g.textContent = '';
    var list = (S.packs || []).filter(function (p) { return p.kind === kind; });
    if (!list.length) { g.appendChild(el('div', 'empty', 'Nothing here yet.')); return; }
    list.forEach(function (p) { g.appendChild(tile(p)); });
  }
  function draw() {
    var n = $('note'); n.textContent = '';
    if (S.note) n.appendChild(el('div', 'note', S.note));
    fill('g-card', 'card_look'); fill('g-email', 'email_look'); fill('g-style', 'admin_style');
  }
  $('refresh').addEventListener('click', function () {
    var b = $('refresh'); b.disabled = true; say('Looking...', true);
    fetch('/admin/packs/list?refresh=1').then(function (r) { return r.json(); }).then(function (j) {
      b.disabled = false; if (j && j.success) { S = j.state; draw(); say('Up to date.', true); } else say((j && j.error) || 'That did not work.', false);
    }).catch(function () { b.disabled = false; say('Could not reach the server.', false); });
  });
  draw();
})();
</script>
__THEME_JS__
</body></html>"""
