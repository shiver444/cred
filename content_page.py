"""
Credential Protocol — the "Content" page of the admin dashboard

Renders the editor where the creator manages what members see after they
verify: sections (links / merch / chat) and the items inside them. The page
is a single self-contained HTML document. Everything the creator typed (and
anything already stored) reaches the browser as JSON inside a data block and
is turned into DOM with textContent / value only — never HTML — so a stray
`<` or quote in a title can't break the page or run as script.

The save itself is POST /admin/content (credential_api.py), which validates
again server-side through content_store.save().
"""

import json
from html import escape as esc_html


def _json_for_script(obj) -> str:
    """JSON that is safe inside <script type="application/json">: `<` (and
    the odd line-separator characters) are written as \\u escapes, so the
    data can never close the tag or open a comment."""
    return (json.dumps(obj)
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
            .replace(" ", "\\u2028")
            .replace(" ", "\\u2029"))


def render(accent: str, title: str, content: dict, tiers: list, max_mb: int = 100, used_bytes: int = 0,
           theme_css: str = "", data_bytes: int = 0, disk_total: int = 0,
           theme_js: str = "", body_attrs: str = "") -> str:
    tier_info = [{"name": t.get("name", ""), "sections": list(t.get("sections") or [])}
                 for t in (tiers or [])]
    return (_TEMPLATE
            .replace("__ACCENT__", esc_html(accent, quote=True))
            .replace("__TITLE__", esc_html(title))
            .replace("__CONTENT__", _json_for_script(content))
            .replace("__TIERS__", _json_for_script(tier_info))
            .replace("__THEME__", theme_css)
            .replace("__BODY_ATTRS__", body_attrs)
            .replace("__THEME_JS__", theme_js)
            .replace("__META__", _json_for_script({"max_mb": int(max_mb), "used_bytes": int(used_bytes),
                                                   "data_bytes": int(data_bytes), "disk_total": int(disk_total)})))


_TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Content — Admin</title>
<style>
  
  body { background:var(--bg); color:var(--fg); font-family:var(--font); padding:32px; max-width:900px; margin:0 auto; }
  h1 { color:var(--accent-text); font-size:16px; letter-spacing:2px; text-transform:uppercase; margin-bottom:4px; }
  .nav { margin-bottom:18px; font-size:11px; letter-spacing:1px; }
  .nav a { color:var(--accent-text); text-decoration:none; margin-right:18px; }
  .nav a:hover { text-decoration:underline; }
  .hint { color:var(--muted); font-size:11px; line-height:1.6; margin:6px 0; }
  .hint b { color:var(--soft); }
  label { display:block; font-size:10px; letter-spacing:1px; color:var(--soft); text-transform:uppercase; margin:10px 0 4px; }
  input, select, textarea { width:100%; background:var(--field); border:1px solid var(--line); color:var(--fg);
           font-family:var(--font); font-size:12px; padding:8px 10px; box-sizing:border-box; }
  input.bad { border-color:var(--bad); }
  button { font-family:var(--font); cursor:pointer; }
  .btn { background:var(--accent); color:var(--on-accent); border:none; font-size:11px; letter-spacing:1.5px;
         text-transform:uppercase; padding:10px 18px; }
  .btn.ghost { background:transparent; border:1px solid var(--accent-text); color:var(--accent-text); }
  .btn:disabled { opacity:.5; cursor:default; }
  .mini { background:transparent; border:1px solid var(--line); color:var(--soft); font-size:11px; width:28px; height:28px; padding:0; }
  .mini:hover { border-color:var(--accent-text); color:var(--accent-text); }
  .sec { border:1px solid var(--line); background:var(--panel); padding:14px 16px; margin:16px 0; }
  .sec-head { display:flex; gap:10px; align-items:flex-end; flex-wrap:wrap; }
  .sec-head > div { flex:1 1 160px; }
  .sec-head .tools { flex:0 0 auto; display:flex; gap:4px; }
  .badge { display:inline-block; border:1px solid var(--line); color:var(--accent-text); font-size:10px; letter-spacing:1px;
           text-transform:uppercase; padding:2px 8px; margin-left:8px; }
  .item { display:flex; gap:8px; align-items:flex-start; margin-top:10px; padding-top:10px; border-top:1px dashed var(--dash); }
  .item .fields { flex:1 1 auto; display:flex; gap:8px; flex-wrap:wrap; }
  .item .fields > div { flex:1 1 200px; }
  .item .fields > div.wide { flex:1 1 100%; }
  .item .fields label { margin-top:0; }
  .bar { display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin:18px 0; }
  .msg { font-size:11px; letter-spacing:1px; text-transform:uppercase; }
  .msg.ok { color:var(--ok); } .msg.err { color:var(--bad); }
  .warn { background:var(--warn-bg); color:var(--warn); font-size:11px; line-height:1.6; padding:10px 14px; margin:10px 0; }
  .warn ul { margin:4px 0 0 18px; padding:0; }
  .tiers { border:1px solid var(--line); padding:12px 16px; margin:16px 0; font-size:12px; line-height:1.8; }
  .ok-k { color:var(--ok); } .no-k { color:var(--bad); }
  .empty { color:var(--muted); font-size:11px; padding:8px 0; }
  .chip { display:flex; align-items:center; gap:8px; flex-wrap:wrap; background:var(--field); border:1px solid var(--line); padding:7px 10px; font-size:12px; }
  .chip .nm { word-break:break-all; }
  .chip .sz { color:var(--muted); }
  .small { background:transparent; border:1px solid var(--line); color:var(--soft); font-size:10px; letter-spacing:1px; text-transform:uppercase; padding:5px 9px; }
  .small:hover { border-color:var(--accent-text); color:var(--accent-text); }
  .stor { }
  #storage-info { border:1px solid var(--line); background:var(--panel); padding:14px 16px; margin:14px 0; border-radius:var(--radius, 0); }
  .stor-head { display:flex; justify-content:space-between; gap:10px; align-items:baseline; flex-wrap:wrap; font-size:12px; color:var(--fg); }
  .stor-head span { color:var(--muted); font-size:11px; }
  .stor-bar { display:flex; height:12px; margin:10px 0 8px; background:var(--dash); border-radius:var(--radius, 0); overflow:hidden; }
  .stor-bar i { display:block; height:100%; }
  .stor-bar i.u { background:var(--accent); }
  .stor-bar i.d { background:var(--soft); opacity:.75; }
  .stor-bar.full i.u { background:var(--warn); }
  .stor-legend { display:flex; gap:16px; flex-wrap:wrap; font-size:11px; color:var(--muted); }
  .lg::before { content:""; display:inline-block; width:9px; height:9px; margin-right:6px; vertical-align:-1px; border-radius:50%; background:var(--dash); border:1px solid var(--line-strong); }
  .lg.u::before { background:var(--accent); border-color:var(--accent); }
  .lg.d::before { background:var(--soft); border-color:var(--soft); opacity:.75; }
  .stor-note { font-size:11px; color:var(--muted); margin-top:8px; }
  .upmsg { font-size:11px; margin-top:4px; min-height:14px; color:var(--muted); }
  .upmsg.err { color:var(--bad); }
__THEME__</style></head>
<body __BODY_ATTRS__>
  <div class="nav"><a href="/admin/dashboard">← Dashboard</a><a href="/admin/members">Members →</a><a href="/admin/logout">Log out</a></div>
  <h1>__TITLE__ — Content</h1>
  <div class="hint">What members see after they verify. Each <b>section</b> has a <b>key</b> (a short lowercase name, like <b>downloads</b>); a tier unlocks the sections whose keys are listed in its "Sections" field on the Dashboard. Changes only take effect when you press <b>Save content</b>.</div>
  <div class="hint">Members' content is only sent to someone holding a valid, unrevoked, unexpired credential for a tier that includes the section. An item can be a <b>link</b> or an <b>uploaded file</b>. Uploaded files live on this server and can only be downloaded by a verified member of a tier that includes the section (the download link a member gets stops working after 15 minutes, and revoking a member cuts them off). A plain <b>link</b> you add can still be opened by anyone who is given it, so for truly private files, upload them here or use a link that is private on its own side.</div>
  <div id="storage-info"></div>

  <div class="tiers" id="tier-check"></div>

  <div id="sections"></div>

  <div class="bar">
    <select id="new-type" style="width:auto">
      <option value="links">Links (downloads, videos, posts…)</option>
      <option value="merch">Merch discount</option>
      <option value="chat">Chat panel</option>
    </select>
    <button type="button" class="btn ghost" id="add-section">+ Add section</button>
  </div>

  <div class="bar">
    <button type="button" class="btn" id="save">Save content</button>
    <span class="msg" id="msg"></span>
  </div>
  <div id="warnings"></div>

<script id="init-content" type="application/json">__CONTENT__</script>
<script id="init-tiers" type="application/json">__TIERS__</script>
<script id="init-meta" type="application/json">__META__</script>
<script>
(function () {
  var KEY_RE = /^[a-z0-9][a-z0-9_-]{0,31}$/;
  var state = JSON.parse(document.getElementById('init-content').textContent);
  var tiers = JSON.parse(document.getElementById('init-tiers').textContent);
  var meta = JSON.parse(document.getElementById('init-meta').textContent);
  var dirty = false;

  var root = document.getElementById('sections');
  var msg  = document.getElementById('msg');

  function el(tag, props, kids) {
    var n = document.createElement(tag);
    Object.keys(props || {}).forEach(function (k) {
      if (k === 'text') n.textContent = props[k];
      else if (k === 'class') n.className = props[k];
      else if (k === 'on') Object.keys(props.on).forEach(function (ev) { n.addEventListener(ev, props.on[ev]); });
      else n.setAttribute(k, props[k]);
    });
    (kids || []).forEach(function (c) { if (c) n.appendChild(c); });
    return n;
  }
  function touch() { dirty = true; msg.textContent = ''; msg.className = 'msg'; renderTierCheck(); }
  function move(arr, i, d) {
    var j = i + d; if (j < 0 || j >= arr.length) return;
    var t = arr[i]; arr[i] = arr[j]; arr[j] = t; touch(); render();
  }
  // A labelled text input bound to obj[field]
  function field(label, obj, f, opts) {
    opts = opts || {};
    var inp = el('input', { type: 'text', placeholder: opts.placeholder || '', maxlength: opts.max || 300 });
    inp.value = obj[f] || '';
    inp.addEventListener('input', function () {
      obj[f] = inp.value;
      if (opts.key) inp.className = (inp.value === '' || KEY_RE.test(inp.value)) ? '' : 'bad';
      touch();
    });
    if (opts.key && inp.value && !KEY_RE.test(inp.value)) inp.className = 'bad';
    return el('div', { class: opts.wide ? 'wide' : '' }, [el('label', { text: label }), inp]);
  }

  function fmtSize(n) {
    if (n >= 1073741824) return (n / 1073741824).toFixed(1) + ' GB';
    if (n >= 1048576) return (n / 1048576).toFixed(1) + ' MB';
    if (n >= 1024) return Math.round(n / 1024) + ' KB';
    return n + ' B';
  }
  // The storage panel: a bar for how much of this server's storage is used
  // (uploaded files + members/key/settings), with the free space, and the
  // per-file limit underneath. Without a known total it shows sizes only.
  function renderStorage() {
    var box = document.getElementById('storage-info');
    var up = Math.max(0, +meta.used_bytes || 0), dat = Math.max(0, +meta.data_bytes || 0), total = Math.max(0, +meta.disk_total || 0);
    var used = up + dat, free = total ? Math.max(0, total - used) : 0;
    while (box.firstChild) box.removeChild(box.firstChild);
    box.appendChild(el('div', { class: 'stor-head' }, [
      el('b', { text: 'Storage' }),
      el('span', { text: total ? fmtSize(used) + ' of ' + fmtSize(total) + ' used' : fmtSize(used) + ' used' })
    ]));
    if (total) {
      var pu = up ? Math.max(0.8, up * 100 / total) : 0, pd = dat ? Math.max(0.8, dat * 100 / total) : 0;
      var bar = el('div', { class: 'stor-bar', role: 'img', 'aria-label': Math.round(used * 100 / total) + ' percent used' }, [
        pu ? el('i', { class: 'u', style: 'width:' + pu.toFixed(2) + '%' }) : null,
        pd ? el('i', { class: 'd', style: 'width:' + pd.toFixed(2) + '%' }) : null
      ]);
      if (used * 100 / total >= 85) bar.className += ' full';
      box.appendChild(bar);
    }
    box.appendChild(el('div', { class: 'stor-legend' }, [
      el('span', { class: 'lg u', text: 'Uploaded files ' + fmtSize(up) }),
      el('span', { class: 'lg d', text: 'Members, key and settings ' + fmtSize(dat) }),
      total ? el('span', { class: 'lg f', text: 'Free ' + fmtSize(free) }) : null
    ]));
    box.appendChild(el('div', { class: 'stor-note', text: 'One file can be up to ' + meta.max_mb + ' MB. Files and members all live on this server\'s storage.' }));
  }
  // Upload one file; reports progress; calls done(file meta or null, error text).
  function uploadFile(file, onProgress, done) {
    if (file.size > meta.max_mb * 1048576) { done(null, 'That file is ' + fmtSize(file.size) + ' — the limit is ' + meta.max_mb + ' MB.'); return; }
    var fd = new FormData(); fd.append('file', file);
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/admin/content/upload');
    xhr.upload.onprogress = function (e) { if (e.lengthComputable) onProgress(Math.round(e.loaded * 100 / e.total)); };
    xhr.onload = function () {
      var j; try { j = JSON.parse(xhr.responseText); } catch (e) { j = { success: false, error: 'The server sent an unexpected answer (status ' + xhr.status + ').' }; }
      if (xhr.status === 401) { done(null, 'You were logged out — log in again, then upload.'); return; }
      if (j.success) { if (typeof j.used_bytes === 'number') { meta.used_bytes = j.used_bytes; renderStorage(); } done(j.file, ''); }
      else done(null, j.error || 'Upload failed.');
    };
    xhr.onerror = function () { done(null, 'Could not reach the server — nothing was uploaded.'); };
    xhr.send(fd);
  }
  // The "link or file" part of one item
  function itemSource(it) {
    var wrap = el('div', { class: 'wide' });
    var msg = el('div', { class: 'upmsg' });
    var picker = el('input', { type: 'file', style: 'display:none' });
    picker.addEventListener('change', function () {
      var f = picker.files[0]; if (!f) return;
      msg.className = 'upmsg'; msg.textContent = 'Uploading… 0%';
      uploadFile(f, function (pct) { msg.textContent = 'Uploading… ' + pct + '%'; }, function (file, error) {
        picker.value = '';
        if (!file) { msg.className = 'upmsg err'; msg.textContent = error; return; }
        it.file = file; it.url = ''; touch(); render();
      });
    });
    if (it.file) {
      wrap.appendChild(el('label', { text: 'File (members download it from here)' }));
      wrap.appendChild(el('div', { class: 'chip' }, [
        el('span', { text: '📎' }),
        el('span', { class: 'nm', text: it.file.name }),
        el('span', { class: 'sz', text: fmtSize(it.file.size) }),
        el('button', { type: 'button', class: 'small', text: 'Replace', on: { click: function () { picker.click(); } } }),
        el('button', { type: 'button', class: 'small', text: 'Remove file', on: { click: function () { delete it.file; touch(); render(); } } })
      ]));
    } else {
      wrap.appendChild(field('Link (https://…)', it, 'url', { max: 2000, placeholder: 'https://…' }));
      wrap.appendChild(el('button', { type: 'button', class: 'small', style: 'margin-top:6px', text: 'or upload a file instead…', on: { click: function () { picker.click(); } } }));
    }
    wrap.appendChild(picker); wrap.appendChild(msg);
    return wrap;
  }

  function renderLinks(sec) {
    var box = el('div');
    box.appendChild(field('Button text on each item (optional, e.g. "↓ Download")', sec, 'button', { max: 30 }));
    sec.items = sec.items || [];
    if (!sec.items.length) box.appendChild(el('div', { class: 'empty', text: 'No items yet.' }));
    sec.items.forEach(function (it, i) {
      box.appendChild(el('div', { class: 'item' }, [
        el('div', { class: 'fields' }, [
          field('Title', it, 'title', { max: 160, placeholder: 'Episode 12 — Raw Footage' }),
          itemSource(it),
          field('Short note (optional)', it, 'note', { wide: true, placeholder: 'Raw footage, 12 minutes' })
        ]),
        el('div', { class: 'tools' }, [
          el('button', { type: 'button', class: 'mini', text: '↑', title: 'Move up', on: { click: function () { move(sec.items, i, -1); } } }),
          el('button', { type: 'button', class: 'mini', text: '↓', title: 'Move down', on: { click: function () { move(sec.items, i, 1); } } }),
          el('button', { type: 'button', class: 'mini', text: '×', title: 'Delete item', on: { click: function () { sec.items.splice(i, 1); touch(); render(); } } })
        ])
      ]));
    });
    box.appendChild(el('button', { type: 'button', class: 'btn ghost', style: 'margin-top:12px', text: '+ Add item',
      on: { click: function () { sec.items.push({ title: '', url: '', note: '' }); touch(); render(); } } }));
    return box;
  }

  function renderMerch(sec) {
    return el('div', {}, [
      field('What the discount is', sec, 'label', { max: 120, placeholder: '20% off the whole shop' }),
      field('Shop link (https://…)', sec, 'url', { max: 2000, placeholder: 'https://…' }),
      field('Discount code', sec, 'code', { max: 80, placeholder: 'MEMBER20' })
    ]);
  }

  function renderChat() {
    return el('div', { class: 'hint', text: 'Shows the chat panel to members of tiers that include this section. (The chat is a demo for now: messages stay in the visitor\'s own browser.) Nothing to fill in.' });
  }

  function render() {
    root.textContent = '';
    if (!state.sections.length) root.appendChild(el('div', { class: 'empty', text: 'No sections yet — add one below.' }));
    state.sections.forEach(function (sec, i) {
      var typeLabel = { links: 'Links', merch: 'Merch', chat: 'Chat' }[sec.type] || sec.type;
      var head = el('div', { class: 'sec-head' }, [
        field('Section title (shown to members)', sec, 'title', { max: 80 }),
        field('Key (tiers refer to this)', sec, 'key', { max: 32, key: true, placeholder: 'downloads' }),
        el('div', { class: 'tools' }, [
          el('span', { class: 'badge', text: typeLabel }),
          el('button', { type: 'button', class: 'mini', text: '↑', title: 'Move section up', on: { click: function () { move(state.sections, i, -1); } } }),
          el('button', { type: 'button', class: 'mini', text: '↓', title: 'Move section down', on: { click: function () { move(state.sections, i, 1); } } }),
          el('button', { type: 'button', class: 'mini', text: '×', title: 'Delete section', on: { click: function () { state.sections.splice(i, 1); touch(); render(); } } })
        ])
      ]);
      var body = sec.type === 'merch' ? renderMerch(sec) : sec.type === 'chat' ? renderChat() : renderLinks(sec);
      root.appendChild(el('div', { class: 'sec' }, [head, body]));
    });
    renderTierCheck();
  }

  function renderTierCheck() {
    var box = document.getElementById('tier-check');
    box.textContent = '';
    box.appendChild(el('div', { class: 'hint', text: 'WHO SEES WHAT (from the "Sections" column of your tiers on the Dashboard)' }));
    if (!tiers.length) { box.appendChild(el('div', { class: 'hint', text: 'You have no tiers yet — add some on the Dashboard.' })); return; }
    var keys = {}; state.sections.forEach(function (s) { keys[s.key] = true; });
    tiers.forEach(function (t) {
      var line = el('div', {}, [el('b', { text: t.name + ': ' })]);
      if (!t.sections.length) {
        line.appendChild(document.createTextNode('no members-only sections'));
      } else {
        t.sections.forEach(function (k, idx) {
          var good = !!keys[String(k).toLowerCase()];
          line.appendChild(el('span', { class: good ? 'ok-k' : 'no-k', text: (idx ? ', ' : '') + k + (good ? ' ✓' : ' ✗ no section has this key') }));
        });
      }
      box.appendChild(line);
    });
  }

  document.getElementById('add-section').addEventListener('click', function () {
    var type = document.getElementById('new-type').value;
    var base = type === 'links' ? 'section' : type;
    var n = 1, used = {}; state.sections.forEach(function (s) { used[s.key] = true; });
    var key = base; while (used[key]) { n++; key = base + '-' + n; }
    var title = { links: 'New section', merch: 'Merch Discount', chat: 'Chat' }[type];
    var sec = { key: key, title: title, type: type };
    if (type === 'links') { sec.button = ''; sec.items = []; }
    if (type === 'merch') { sec.label = ''; sec.url = ''; sec.code = ''; }
    state.sections.push(sec); touch(); render();
  });

  function showWarnings(list) {
    var w = document.getElementById('warnings');
    w.textContent = '';
    if (!list || !list.length) return;
    var ul = el('ul');
    list.forEach(function (t) { ul.appendChild(el('li', { text: t })); });
    w.appendChild(el('div', { class: 'warn' }, [el('b', { text: 'Saved, but some things were left out:' }), ul]));
  }

  var saveBtn = document.getElementById('save');
  saveBtn.addEventListener('click', function () {
    saveBtn.disabled = true; msg.className = 'msg'; msg.textContent = 'Saving…';
    fetch('/admin/content', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sections: state.sections })
    }).then(function (r) {
      return r.json().then(function (j) { return { status: r.status, body: j }; });
    }).then(function (res) {
      saveBtn.disabled = false;
      if (res.status === 401) { msg.className = 'msg err'; msg.textContent = 'You were logged out — log in again, then save.'; return; }
      if (!res.body.success) { msg.className = 'msg err'; msg.textContent = res.body.error || 'Save failed.'; return; }
      state = res.body.content; dirty = false;
      render(); showWarnings(res.body.warnings);
      msg.className = 'msg ok'; msg.textContent = 'Saved.';
    }).catch(function () {
      saveBtn.disabled = false; msg.className = 'msg err'; msg.textContent = 'Could not reach the server — nothing was saved.';
    });
  });

  window.addEventListener('beforeunload', function (e) { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
  renderStorage();
  render();
})();
</script>
__THEME_JS__
</body></html>
"""
