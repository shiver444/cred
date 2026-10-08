"""
Credential Protocol — the dashboard's "Card looks" screen

A list of saved card looks (see card_looks.py), each shown as a small live
preview of the real card, with Edit / Copy / Delete, a "+ New look" button and
an editor with a live preview. The screen sits outside the dashboard's big
settings form and talks to /admin/looks/* by itself, so saving a look never
touches the other settings. After any change the tier pickers on the Tiers
screen are refreshed, so a new look can be chosen right away.
"""

import json
from html import escape

import card_looks

CSS = """
  .looks-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:14px; margin:14px 0 6px; }
  .look-tile { border:1px solid var(--line); background:var(--panel); border-radius:var(--radius-lg, 8px); padding:12px; display:flex; flex-direction:column; gap:10px; min-width:0; }
  .lk-thumb { position:relative; width:100%; overflow:hidden; border-radius:var(--radius, 6px); background:var(--frame-bg); }
  .lk-thumb iframe { position:absolute; top:0; left:0; width:420px; height:600px; border:0; transform-origin:0 0; pointer-events:none; }
  .lk-name { font-weight:600; color:var(--fg); font-size:14px; overflow-wrap:anywhere; }
  .lk-sub { font-size:12px; color:var(--muted); line-height:1.5; }
  .lk-btns { display:flex; gap:8px; flex-wrap:wrap; margin-top:auto; }
  .lk-btns button, .lk-btns a, .look-back { background:transparent; border:1px solid var(--line-strong, var(--line)); color:var(--soft); font-family:var(--font);
    font-size:12px; padding:8px 12px; cursor:pointer; text-decoration:none; border-radius:var(--radius, 0); }
  .lk-btns button:hover, .lk-btns a:hover, .look-back:hover { color:var(--fg); border-color:var(--accent-text); }
  .lk-btns .danger.sure { border-color:var(--bad); color:var(--bad); }
  .look-back { margin:2px 0 8px; }
  .look-cols { display:grid; grid-template-columns:minmax(0,1fr) 360px; grid-template-areas:"fields preview" "actions preview"; grid-template-rows:auto 1fr; gap:0 22px; align-items:start; }
  .look-fields { grid-area:fields; } .look-preview { grid-area:preview; } .lk-actions { grid-area:actions; }
  .look-fields label { display:block; }
  .look-fields input:not([type=color]):not([type=checkbox]):not([type=file]), .look-fields select { width:100%; box-sizing:border-box; }
  .lk-row { display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
  .lk-row input[type=color] { width:52px; height:36px; padding:2px; }
  .look-fields .lk-check { display:flex; gap:8px; align-items:center; margin:0; font-size:13px; font-weight:400; color:var(--soft); text-transform:none; letter-spacing:0; white-space:nowrap; }
  .look-fields .lk-check input { width:auto; flex:0 0 auto; margin:0; }
  .lk-primary { background:var(--accent); color:var(--on-accent); border:0; padding:11px 22px; font-family:var(--font); font-size:13px; font-weight:600; cursor:pointer; border-radius:var(--radius, 0); }
  .lk-primary:disabled { opacity:.6; cursor:default; }
  .lk-actions { display:flex; gap:14px; align-items:center; flex-wrap:wrap; margin-top:18px; }
  .look-preview iframe { width:100%; height:640px; border:1px solid var(--line); background:var(--frame-bg); display:block; }
  @media (max-width:899px) {
    .look-cols { grid-template-columns:minmax(0,1fr); grid-template-areas:"fields" "preview" "actions"; grid-template-rows:none; }
    .look-preview { margin-top:18px; }
    .look-preview iframe { height:600px; }
    .look-fields input:not([type=color]):not([type=checkbox]):not([type=file]), .look-fields select { padding:11px 12px; font-size:16px; }
    .looks-grid { grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:10px; }
    .lk-btns button, .lk-btns a { padding:9px 10px; }
  }
"""

_SECTION = """
    <section class="dsec" id="sec-looks" data-title="Card looks">
    <h2>Card looks</h2>
    <div id="looks-view">
      <div class="hint">A look is a saved card design. Make as many as you like (for example Monthly, Trial or VIP), then pick one for each tier under <b>Tiers &amp; pricing</b>. Editing a look changes cards issued from then on; cards members already have stay as they are.</div>
      <div class="looks-grid" id="looks-grid"></div>
      <button type="button" class="add-tier" id="look-new">+ New look</button>
      <div class="hint" id="looks-msg" style="margin-top:10px;min-height:16px;"></div>
    </div>

    <div id="look-editor" style="display:none">
      <button type="button" class="look-back" id="look-back">← All looks</button>
      <h2 id="look-title">New look</h2>
      <div class="look-cols">
        <div class="look-fields">
          <label for="lk-name">Name (only you see it)</label>
          <input id="lk-name" maxlength="__MAXNAME__" placeholder="Monthly">
          <label for="lk-title">Card title</label>
          <input id="lk-title" maxlength="__MAXTITLE__" placeholder="same as the default look">
          <label for="lk-label">Small line under the title</label>
          <input id="lk-label" maxlength="__MAXLABEL__" placeholder="same as the default look">
          <label for="lk-style">Card style</label>
          <select id="lk-style"></select>
          <label for="lk-accent">Accent color</label>
          <div class="lk-row">
            <input type="color" id="lk-accent" value="#00e87a">
            <label class="lk-check"><input type="checkbox" id="lk-accent-same"> Same as the default look</label>
          </div>
          <label for="lk-barcode">Barcode strip</label>
          <select id="lk-barcode"><option value="on">On</option><option value="off">Off</option></select>
          <label>Logo</label>
          <div class="logo-row">
            <span class="no-logo" id="lk-logo-state"></span>
            <input type="file" id="lk-logo" accept="image/png,image/jpeg,image/gif,image/webp">
            <button type="button" class="remove-logo" id="lk-logo-remove">Remove logo</button>
          </div>
          <label>Background picture (your own design)</label>
          <div class="hint">Your own picture behind the card's text. A tall picture works best (about 3 wide by 4 high). Dark pictures keep the text easiest to read.</div>
          <div class="logo-row" style="margin-top:6px;">
            <span class="no-logo" id="lk-bg-state"></span>
            <input type="file" id="lk-bg" accept="image/png,image/jpeg,image/gif,image/webp">
            <button type="button" class="remove-logo" id="lk-bg-remove">Remove picture</button>
          </div>
          <label for="lk-dim">Darken the picture so the text is readable</label>
          <select id="lk-dim"></select>
        </div>
        <div class="look-preview">
          <div class="hint" style="margin-bottom:6px;">Preview (updates as you type)</div>
          <iframe id="lk-frame" sandbox="" title="Card preview"></iframe>
        </div>
        <div class="lk-actions">
          <button type="button" class="lk-primary" id="lk-save">Save look</button>
          <span class="hint" id="lk-msg" style="min-height:16px;"></span>
        </div>
      </div>
    </div>
    </section>
"""

_JS = r"""
(function () {
  var dataEl = document.getElementById('looks-data');
  if (!dataEl) return;
  var D = JSON.parse(dataEl.textContent), looks = D.looks || [];
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
  var grid = $('looks-grid'), listView = $('looks-view'), editor = $('look-editor'), msg = $('looks-msg'), emsg = $('lk-msg');
  var cur = null, logoCleared = false, bgCleared = false, timer = null, seq = 0;

  function say(text, bad) { msg.textContent = text || ''; msg.style.color = bad ? 'var(--bad)' : 'var(--muted)'; }
  function esay(text, bad) { emsg.textContent = text || ''; emsg.style.color = bad ? 'var(--bad)' : 'var(--muted)'; }
  function fail(r, j) { return (j && j.error) || (r.status === 413 ? 'That picture is too big.' : 'Something went wrong. Reload the page and try again.'); }
  function post(url, fd) {
    return fetch(url, { method: 'POST', body: fd, credentials: 'same-origin' })
      .then(function (r) { return r.json().then(function (j) { return { r: r, j: j }; }, function () { return { r: r, j: null }; }); });
  }
  function names(list) { return list.join(', '); }

  // ── the tier pickers on the Tiers screen ──
  function fillPicker(sel) {
    var keep = sel.value;
    while (sel.firstChild) sel.removeChild(sel.firstChild);
    var o = document.createElement('option'); o.value = ''; o.textContent = 'Default look'; sel.appendChild(o);
    looks.forEach(function (l) { var x = document.createElement('option'); x.value = l.id; x.textContent = l.name; sel.appendChild(x); });
    sel.value = looks.some(function (l) { return l.id === keep; }) ? keep : '';
  }
  function syncPickers() {
    [].slice.call(document.querySelectorAll('select[name="tier_look"]')).forEach(fillPicker);
    var tpl = document.getElementById('tier-row-template');
    if (tpl && tpl.content) [].slice.call(tpl.content.querySelectorAll('select[name="tier_look"]')).forEach(fillPicker);
  }

  // ── the list ──
  var observer = null;
  function loadThumb(frame) {
    if (frame.getAttribute('data-loaded')) return;
    frame.setAttribute('data-loaded', '1');
    fetch('/admin/looks/preview/' + frame.getAttribute('data-look'), { credentials: 'same-origin' })
      .then(function (r) { return r.text(); }).then(function (h) { frame.srcdoc = h; }).catch(function () {});
  }
  function fit() {
    [].slice.call(grid.querySelectorAll('.lk-thumb')).forEach(function (t) {
      var w = t.clientWidth; if (!w) return;
      var k = w / 420;
      t.style.height = Math.round(600 * k) + 'px';
      t.firstChild.style.transform = 'scale(' + k + ')';
    });
  }
  function usedText(l) { return l.used_by.length ? 'Used by: ' + names(l.used_by) : 'Not used by any tier yet'; }
  function tile(l) {
    var isDef = !l;
    var t = el('div', 'look-tile'); t.setAttribute('data-look', isDef ? 'default' : l.id);
    var th = el('div', 'lk-thumb'), fr = document.createElement('iframe');
    fr.setAttribute('sandbox', ''); fr.setAttribute('title', 'Preview'); fr.tabIndex = -1; fr.setAttribute('data-look', isDef ? 'default' : l.id);
    th.appendChild(fr); t.appendChild(th);
    var box = el('div');
    box.appendChild(el('div', 'lk-name', isDef ? 'Default look' : l.name));
    box.appendChild(el('div', 'lk-sub', isDef ? ('Set under Branding & cards. ' + (D.default_used_by.length ? 'Used by: ' + names(D.default_used_by) : 'Every tier has its own look')) : usedText(l)));
    t.appendChild(box);
    var b = el('div', 'lk-btns');
    if (isDef) {
      var a = el('a', '', 'Edit in Branding');
      a.href = document.body.getAttribute('data-layout') === 'app' ? '#/s/branding' : '#sec-branding';
      b.appendChild(a);
    } else {
      var e = el('button', '', 'Edit'); e.type = 'button'; e.addEventListener('click', function () { openEditor(l); });
      var c = el('button', '', 'Copy'); c.type = 'button'; c.addEventListener('click', function () { copyLook(l, c); });
      var d = el('button', 'danger', 'Delete'); d.type = 'button';
      var armed = null;
      d.addEventListener('click', function () {
        if (!armed) {
          d.textContent = 'Really delete?'; d.className = 'danger sure';
          armed = setTimeout(function () { armed = null; d.textContent = 'Delete'; d.className = 'danger'; }, 4000);
          return;
        }
        clearTimeout(armed); armed = null; deleteLook(l, d);
      });
      b.appendChild(e); b.appendChild(c); b.appendChild(d);
    }
    t.appendChild(b);
    return t;
  }
  function render() {
    while (grid.firstChild) grid.removeChild(grid.firstChild);
    grid.appendChild(tile(null));
    looks.forEach(function (l) { grid.appendChild(tile(l)); });
    $('look-new').style.display = looks.length >= D.max ? 'none' : '';
    syncPickers();
    var thumbs = [].slice.call(grid.querySelectorAll('.lk-thumb'));
    if (observer) observer.disconnect();
    if ('IntersectionObserver' in window) {
      // load a preview only when its tile comes into view (the screen may be hidden at first)
      observer = new IntersectionObserver(function (items) {
        items.forEach(function (i) { if (i.isIntersecting) { loadThumb(i.target.firstChild); observer.unobserve(i.target); } });
        fit();
      });
      thumbs.forEach(function (t) { observer.observe(t); });
    } else {
      thumbs.forEach(function (t) { loadThumb(t.firstChild); });
    }
    fit();
  }
  window.addEventListener('resize', fit);
  window.addEventListener('hashchange', function () { setTimeout(fit, 0); });
  if (window.ResizeObserver) new ResizeObserver(fit).observe(grid);

  function copyLook(l, btn) {
    btn.disabled = true; say('Copying…');
    var fd = new FormData(); fd.append('id', l.id);
    post('/admin/looks/copy', fd).then(function (x) {
      btn.disabled = false;
      if (!x.j || !x.j.success) { say(fail(x.r, x.j), true); return; }
      looks = x.j.looks; render(); say('Copied. You can rename the copy with Edit.');
    }).catch(function () { btn.disabled = false; say('Could not reach the server.', true); });
  }
  function deleteLook(l, btn) {
    btn.disabled = true; say('Deleting…');
    var fd = new FormData(); fd.append('id', l.id);
    post('/admin/looks/delete', fd).then(function (x) {
      btn.disabled = false;
      if (!x.j || !x.j.success) { say(fail(x.r, x.j), true); return; }
      looks = x.j.looks; D.default_used_by = D.default_used_by.concat(x.j.moved || []);
      render();
      say('Deleted.' + ((x.j.moved || []).length ? ' ' + names(x.j.moved) + ' now uses the default look.' : ''));
    }).catch(function () { btn.disabled = false; say('Could not reach the server.', true); });
  }
  $('look-new').addEventListener('click', function () { openEditor(null); });

  // ── the editor ──
  var fName = $('lk-name'), fTitle = $('lk-title'), fLabel = $('lk-label'), fStyle = $('lk-style'), fAccent = $('lk-accent'), fSame = $('lk-accent-same'),
      fBar = $('lk-barcode'), fLogo = $('lk-logo'), fBg = $('lk-bg'), fDim = $('lk-dim'), frame = $('lk-frame');
  (function () {
    var o = document.createElement('option'); o.value = ''; o.textContent = 'Same as the default look'; fStyle.appendChild(o);
    D.styles.forEach(function (s) { var x = document.createElement('option'); x.value = s[0]; x.textContent = s[1]; fStyle.appendChild(x); });
    D.dims.forEach(function (s) { var x = document.createElement('option'); x.value = s[0]; x.textContent = s[1]; fDim.appendChild(x); });
    fTitle.placeholder = 'same as the default look (' + D.default.title + ')';
    fLabel.placeholder = 'same as the default look (' + D.default.label + ')';
  })();

  function states() {
    $('lk-logo-state').textContent = fLogo.files[0] ? 'new logo chosen' : (cur && cur.has_logo && !logoCleared ? '✓ logo added' : 'none (uses the default logo)');
    $('lk-bg-state').textContent = fBg.files[0] ? 'new picture chosen' : (cur && cur.has_bg && !bgCleared ? '✓ picture added' : 'none');
    $('lk-logo-remove').style.display = (fLogo.files[0] || (cur && cur.has_logo && !logoCleared)) ? '' : 'none';
    $('lk-bg-remove').style.display = (fBg.files[0] || (cur && cur.has_bg && !bgCleared)) ? '' : 'none';
    fAccent.disabled = fSame.checked;
  }
  function formData() {
    var fd = new FormData();
    if (cur) fd.append('id', cur.id);
    fd.append('name', fName.value); fd.append('card_title', fTitle.value); fd.append('card_label', fLabel.value);
    fd.append('card_style', fStyle.value); fd.append('accent_color', fAccent.value); fd.append('accent_same', fSame.checked ? '1' : '0');
    fd.append('barcode', fBar.value); fd.append('bg_dim', fDim.value);
    fd.append('logo_clear', logoCleared ? '1' : '0'); fd.append('bg_clear', bgCleared ? '1' : '0');
    if (fLogo.files[0]) fd.append('logo', fLogo.files[0]);
    if (fBg.files[0]) fd.append('bg', fBg.files[0]);
    return fd;
  }
  function preview() {
    var mine = ++seq;
    fetch('/admin/looks/preview', { method: 'POST', body: formData(), credentials: 'same-origin' })
      .then(function (r) { return r.text().then(function (h) { return { ok: r.ok, h: h }; }); })
      .then(function (x) { if (mine === seq) frame.srcdoc = x.h; })
      .catch(function () { if (mine === seq) frame.srcdoc = '<p style="font-family:sans-serif;color:#b00">Preview failed.</p>'; });
  }
  function later() { clearTimeout(timer); timer = setTimeout(preview, 700); }
  [fName, fTitle, fLabel, fStyle, fAccent, fSame, fBar, fDim].forEach(function (f) { f.addEventListener('input', later); f.addEventListener('change', later); });
  fSame.addEventListener('change', states);
  fLogo.addEventListener('change', function () { if (fLogo.files[0]) logoCleared = false; states(); later(); });
  fBg.addEventListener('change', function () { if (fBg.files[0]) bgCleared = false; states(); later(); });
  $('lk-logo-remove').addEventListener('click', function () { fLogo.value = ''; logoCleared = true; states(); later(); });
  $('lk-bg-remove').addEventListener('click', function () { fBg.value = ''; bgCleared = true; states(); later(); });

  function openEditor(l) {
    cur = l || null; logoCleared = false; bgCleared = false; fLogo.value = ''; fBg.value = '';
    $('look-title').textContent = l ? 'Edit look' : 'New look';
    fName.value = l ? l.name : ''; fTitle.value = l ? l.card_title : ''; fLabel.value = l ? l.card_label : '';
    fStyle.value = l ? l.card_style : ''; fBar.value = (l && !l.show_barcode) ? 'off' : 'on'; fDim.value = l ? l.bg_dim : 'medium';
    fSame.checked = !l || !l.accent_color; fAccent.value = (l && l.accent_color) || D.default.accent;
    esay(''); states();
    listView.style.display = 'none'; editor.style.display = '';
    frame.srcdoc = '';
    if (editor.scrollIntoView) editor.scrollIntoView({ block: 'start' });
    preview();
  }
  function closeEditor() { editor.style.display = 'none'; listView.style.display = ''; cur = null; fit(); }
  $('look-back').addEventListener('click', closeEditor);

  $('lk-save').addEventListener('click', function () {
    if (!fName.value.trim()) { esay('Give the look a name.', true); fName.focus(); return; }
    var btn = $('lk-save'); btn.disabled = true; esay('Saving…');
    post('/admin/looks/save', formData()).then(function (x) {
      btn.disabled = false;
      if (!x.j || !x.j.success) { esay(fail(x.r, x.j), true); return; }
      var wasNew = !cur;
      looks = x.j.looks; render(); closeEditor();
      say('Saved. ' + (wasNew ? 'Now pick it for a tier under Tiers & pricing.' : 'New cards use the updated look.'));
    }).catch(function () { btn.disabled = false; esay('Could not reach the server.', true); });
  });

  render();
})();
"""


def _json_for_script(obj) -> str:
    return json.dumps(obj, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def section_html(cfg: dict) -> str:
    """The Card looks screen: markup, its data and its script. `cfg` is
    load_config()'s result."""
    tiers = cfg.get("tiers") or []
    default_used = [t.get("name", "") for t in tiers if not card_looks.get(cfg.get("card_looks") or [], t.get("look"))]
    data = {
        "looks": [card_looks.summary(l, tiers) for l in (cfg.get("card_looks") or [])],
        "styles": [[s, card_looks.STYLE_NAMES[s]] for s in card_looks.STYLES],
        "dims": [[d, card_looks.DIM_NAMES[d]] for d in card_looks.DIMS],
        "default": {
            "accent": card_looks.clean_color(cfg.get("accent_color")) or "#00e87a",
            "title": cfg.get("card_title", ""),
            "label": cfg.get("card_subtitle", ""),
        },
        "default_used_by": default_used,
        "max": card_looks.MAX_LOOKS,
    }
    body = (_SECTION.replace("__MAXNAME__", str(card_looks.MAX_NAME))
                    .replace("__MAXTITLE__", str(card_looks.MAX_TITLE))
                    .replace("__MAXLABEL__", str(card_looks.MAX_LABEL)))
    return (body + '<script id="looks-data" type="application/json">' + _json_for_script(data) + "</script>"
            + "<script>" + _JS.replace("</", "<\\/") + "</script>")


def picker_options(cfg: dict, selected: str = "") -> str:
    """<option>s for a tier's "Card look" picker."""
    out = ['<option value=""%s>Default look</option>' % (" selected" if not selected else "")]
    for l in (cfg.get("card_looks") or []):
        out.append('<option value="%s"%s>%s</option>' % (
            escape(l["id"], quote=True), " selected" if l["id"] == selected else "", escape(l["name"])))
    return "".join(out)
