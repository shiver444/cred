"""
Credential Protocol: the "Codes" screen of the admin dashboard (under Cards), the printable sheet of
codes, and the public claim page. The rules are in claim_codes.py; credential_api.py does the HTTP.
Everything typed by the creator or a visitor is shown as text (textContent / escaped), never as HTML.
"""

import json
import admin_theme
from html import escape as esc_html


def _json_for_script(obj) -> str:
    return (json.dumps(obj).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def render(theme_css: str, theme_js: str, body_attrs: str, title: str, state: dict) -> str:
    return (_TEMPLATE
            .replace("__TITLE__", esc_html(title))
            .replace("__THEME__", theme_css)
            .replace("__NAV__", admin_theme.nav_html("codes"))
            .replace("__BODY_ATTRS__", body_attrs)
            .replace("__THEME_JS__", theme_js)
            .replace("__STATE__", _json_for_script(state)))


# ── The printable sheet: one tile per unused code (QR + the code) ──
def render_sheet(batch_name: str, card_label: str, tiles: list, claim_url: str) -> str:
    """tiles = [{"code": "ABCDE-FGHJK", "number": 12 or None, "svg": "<svg ...>"}]"""
    cells = []
    for t in tiles:
        num = f'<div class="n">No. {esc_html(str(t["number"]))}</div>' if t.get("number") else ""
        cells.append(f'<div class="tile">{t["svg"]}{num}<div class="c">{esc_html(t["code"])}</div></div>')
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc_html(batch_name)} - codes</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 20px; color: #111; background: #fff; }}
  h1 {{ font-size: 16px; margin: 0 0 4px; }}
  p.sub {{ font-size: 12px; color: #555; margin: 0 0 14px; }}
  .bar {{ margin: 0 0 14px; }}
  .bar button {{ font-size: 13px; padding: 8px 14px; cursor: pointer; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }}
  .tile {{ border: 1px dashed #999; padding: 8px; text-align: center; break-inside: avoid; }}
  .tile svg {{ width: 100%; max-width: 120px; height: auto; }}
  .tile .c {{ font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 13px; letter-spacing: 1px; margin-top: 4px; }}
  .tile .n {{ font-size: 11px; color: #555; }}
  @media print {{ .bar {{ display: none; }} body {{ margin: 8mm; }} .grid {{ grid-template-columns: repeat(4, 1fr); }} }}
</style></head><body>
<div class="bar"><button onclick="window.print()">Print this sheet</button></div>
<h1>{esc_html(batch_name)}</h1>
<p class="sub">{esc_html(card_label)} &middot; {len(tiles)} unused code{'' if len(tiles) == 1 else 's'} &middot; claim at {esc_html(claim_url)}</p>
<div class="grid">{''.join(cells) or '<p>No unused codes in this batch.</p>'}</div>
</body></html>"""


# ── The public claim page ──
def render_claim(*, creator: str, accent: str, code: str = "", card: str = "", number=None, of=None, message: str = "",
                 good: bool = False, done: dict = None, name: str = "", email: str = "", show_form: bool = True) -> str:
    """The page a visitor sees. `done` = {"link": members-page link, "emailed": bool, "card": label} after a successful claim."""
    acc = accent if (accent or "").startswith("#") and len(accent) in (4, 7) and all(c in "0123456789abcdefABCDEF" for c in accent[1:]) else "#2a6df4"
    hx = acc[1:] if len(acc) == 7 else "".join(ch * 2 for ch in acc[1:])
    def _lin(v):
        v = int(v, 16) / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    lum = 0.2126 * _lin(hx[0:2]) + 0.7152 * _lin(hx[2:4]) + 0.0722 * _lin(hx[4:6])
    on_acc = "#111" if (lum + 0.05) / (0.0 + 0.05 + 0.0067) >= (1.05) / (lum + 0.05) else "#fff"   # whichever of near-black / white reads better
    msg = f'<div class="msg {"ok" if good else "err"}">{esc_html(message)}</div>' if message else ""
    if done:
        link = esc_html(done.get("link") or "")
        btn = f'<a class="btn" href="{link}">Open your card</a>' if link else ""
        note = "We also emailed it to you." if done.get("emailed") else "Keep this page's link safe: it is how you open your card."
        body = (f'<h2>Your card is ready</h2><p class="big">{esc_html(done.get("card") or "")}</p>'
                + (f'<p>No. {esc_html(str(done["number"]))}' + (f' of {esc_html(str(done["of"]))}' if done.get("of") else "") + "</p>" if done.get("number") else "")
                + f"<p>{esc_html(note)}</p>{btn}")
    else:
        what = ""
        if card:
            what = f'<p class="big">{esc_html(card)}</p>' + (f'<p>No. {esc_html(str(number))}' + (f' of {esc_html(str(of))}' if of else "") + "</p>" if number else "")
        form = ""
        if show_form:
            form = f"""<form method="post" action="/claim" autocomplete="on">
  <label>Your code<input name="code" value="{esc_html(code)}" maxlength="24" autocapitalize="characters" autocomplete="off" spellcheck="false" required placeholder="ABCDE-FGHJK"></label>
  <label>Your name<input name="name" value="{esc_html(name)}" maxlength="100" autocomplete="name" required></label>
  <label>Your email<input name="email" type="email" value="{esc_html(email)}" maxlength="254" autocomplete="email" required></label>
  <div class="hp" aria-hidden="true"><label>Leave this empty<input name="hp_x9f3" tabindex="-1" autocomplete="off" data-lpignore="true" data-1p-ignore></label></div>
  <button class="btn" type="submit">Get my card</button>
</form>"""
        body = f"<h2>Claim your card</h2>{what}{msg}{form}"
        msg = ""
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>Claim your card</title>
<style>
  :root {{ --bg:#fff; --fg:#161616; --muted:#666; --line:#d6d6d6; --field:#fafafa; --acc:{acc}; --on-acc:{on_acc}; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#101012; --fg:#f2f2f2; --muted:#9a9aa2; --line:#303036; --field:#18181b; }} }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg); font-family:system-ui,-apple-system,Segoe UI,sans-serif; min-height:100vh; display:flex; align-items:center; justify-content:center; padding:16px; }}
  main {{ width:100%; max-width:420px; }}
  .who {{ font-size:12px; letter-spacing:2px; text-transform:uppercase; color:var(--muted); margin-bottom:10px; }}
  h2 {{ margin:0 0 10px; font-size:22px; }}
  .big {{ font-size:20px; margin:4px 0; }}
  p {{ line-height:1.5; margin:8px 0; }}
  label {{ display:block; font-size:12px; color:var(--muted); margin:14px 0 4px; }}
  input {{ width:100%; font-size:16px; padding:11px 12px; background:var(--field); color:var(--fg); border:1px solid var(--line); border-radius:8px; }}
  .btn {{ display:inline-block; margin-top:18px; width:100%; text-align:center; background:var(--acc); color:var(--on-acc); border:0; font-size:16px; padding:13px 16px; border-radius:8px; text-decoration:none; cursor:pointer; }}
  .msg {{ padding:10px 12px; border-radius:8px; font-size:14px; margin:12px 0; }}
  .msg.err {{ background:rgba(220,60,60,.12); color:#c0392b; }}
  .msg.ok {{ background:rgba(40,160,90,.14); color:#1e8449; }}
  .hp {{ position:absolute; left:-9999px; height:0; overflow:hidden; }}
</style></head><body><main>
<div class="who">{esc_html(creator)}</div>
{body}{msg}
</main></body></html>"""


_TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Codes — Admin</title>
<style>
  body { background:var(--bg); color:var(--fg); font-family:var(--font); padding:32px; max-width:900px; margin:0 auto; }
  h1 { color:var(--accent-text); font-size:16px; letter-spacing:2px; text-transform:uppercase; margin-bottom:4px; }
  h2 { font-size:12px; letter-spacing:2px; text-transform:uppercase; color:var(--soft); margin:26px 0 6px; }
  .nav { margin-bottom:18px; font-size:11px; letter-spacing:1px; }
  .nav a { color:var(--accent-text); text-decoration:none; margin-right:18px; }
  .nav a:hover { text-decoration:underline; }
  .hint { color:var(--muted); font-size:12px; line-height:1.6; margin:6px 0; }
  .hint b { color:var(--soft); }
  label.l { display:block; font-size:10px; letter-spacing:1px; color:var(--soft); text-transform:uppercase; margin:12px 0 4px; }
  input[type=text], input[type=number], select { width:100%; background:var(--field); border:1px solid var(--line); color:var(--fg);
           font-family:var(--font); font-size:14px; padding:9px 10px; box-sizing:border-box; border-radius:var(--radius, 0); }
  button { font-family:var(--font); cursor:pointer; }
  .btn { background:var(--accent); color:var(--on-accent); border:none; font-size:11px; letter-spacing:1.5px; text-transform:uppercase; padding:11px 18px; border-radius:var(--radius, 0); }
  .btn:disabled { opacity:.5; cursor:default; }
  .small { display:inline-block; background:transparent; border:1px solid var(--line); color:var(--soft); font-size:10px; letter-spacing:1px; text-transform:uppercase; padding:6px 10px; border-radius:var(--radius, 0); text-decoration:none; }
  .small:hover { border-color:var(--accent-text); color:var(--accent-text); }
  .small.danger:hover { border-color:var(--bad); color:var(--bad); }
  .panel { border:1px solid var(--line); background:var(--panel); padding:14px 16px; margin:14px 0; border-radius:var(--radius, 0); }
  .row { display:flex; gap:10px; flex-wrap:wrap; align-items:flex-end; }
  .row > div { flex:1 1 180px; }
  .opt { display:flex; gap:8px; align-items:flex-start; font-size:13px; text-transform:none; letter-spacing:0; color:var(--fg); margin:12px 0 0; cursor:pointer; }
  .opt input { width:auto; margin-top:3px; }
  .batch-head { display:flex; justify-content:space-between; gap:10px; flex-wrap:wrap; align-items:baseline; }
  .batch-name { font-size:15px; }
  .stat { font-size:12px; color:var(--soft); margin:6px 0 10px; }
  .acts { display:flex; gap:8px; flex-wrap:wrap; }
  .msg { font-size:12px; margin-top:10px; min-height:1em; }
  .msg.ok { color:var(--ok); } .msg.err { color:var(--bad); }
  .warn { background:var(--warn-bg); color:var(--warn); font-size:12px; line-height:1.6; padding:10px 14px; margin:10px 0; border-radius:var(--radius, 0); }
  table.codes { width:100%; border-collapse:collapse; font-size:12px; margin-top:10px; }
  table.codes th { text-align:left; color:var(--muted); font-weight:normal; letter-spacing:1px; text-transform:uppercase; font-size:10px; padding:4px 6px; }
  table.codes td { padding:5px 6px; border-top:1px solid var(--line); word-break:break-all; }
  td.mono { font-family:ui-monospace, Menlo, Consolas, monospace; letter-spacing:1px; }
  .empty { color:var(--muted); font-size:13px; padding:16px 0; }
  .urlbox { display:flex; gap:8px; }
  .urlbox input { flex:1; }
__THEME__</style>
</head>
<body __BODY_ATTRS__>
__NAV__
<h1>__TITLE__ — Codes</h1>
<p class="hint">A <b>claim code</b> is a one-time code for a card. Make a batch, print or send the codes (flyers, bottle labels, tickets, packaging, giveaways). Whoever enters a code on your claim page gets that card, and the code is used up. A code <b>always works</b>, even if that email already has the card; it still stops when the card is sold out or its window is closed.</p>
<div class="panel">
  <label class="l">People enter their code here</label>
  <div class="urlbox"><input type="text" id="claimurl" readonly><button type="button" class="small" id="copyurl">Copy</button></div>
  <p class="hint">A code's own QR on the printed sheet already points at this page with the code filled in.</p>
</div>

<h2>Make codes</h2>
<div class="panel" id="maker">
  <div id="needcards"></div>
  <div class="row">
    <div><label class="l" for="bname">Name of the batch</label><input type="text" id="bname" maxlength="60" placeholder="Bottle labels spring 2027"></div>
    <div><label class="l" for="bcard">Card they unlock</label><select id="bcard"></select></div>
    <div style="flex:0 1 120px"><label class="l" for="bcount">How many</label><input type="number" id="bcount" min="1" max="1000" value="50"></div>
  </div>
  <div id="numbering" style="display:none">
    <label class="opt"><input type="checkbox" id="bnum"><span>Give every code its own fixed number. Bottle 112's code always gives card #112, whoever claims it.</span></label>
    <div style="max-width:200px"><label class="l" for="bstart">Start at number</label><input type="number" id="bstart" min="1" value="1"></div>
  </div>
  <p class="hint" id="cardnote"></p>
  <div style="margin-top:14px"><button type="button" class="btn" id="make">Make codes</button></div>
  <div class="msg" id="makemsg"></div>
</div>

<h2>Your batches</h2>
<div id="batches"></div>

<script id="init-state" type="application/json">__STATE__</script>
<script>
(function () {
  var S = JSON.parse(document.getElementById('init-state').textContent);
  var batches = S.batches || [], cards = S.cards || [];
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') n.textContent = attrs[k]; else if (k === 'on') Object.keys(attrs.on).forEach(function (e) { n.addEventListener(e, attrs.on[e]); });
      else if (attrs[k] !== null && attrs[k] !== undefined) n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c) n.appendChild(c); });
    return n;
  }
  function up(v) { return String(v || '').toUpperCase(); }
  function cardOf(name) { return cards.filter(function (c) { return up(c.name) === up(name); })[0]; }
  function labelOf(c) { return c ? (c.label && up(c.label) !== up(c.name) ? c.label + ' (' + c.name + ')' : c.name) : ''; }
  var makeMsg = document.getElementById('makemsg');
  function say(t, good) { makeMsg.textContent = t || ''; makeMsg.className = 'msg ' + (good ? 'ok' : 'err'); }

  document.getElementById('claimurl').value = S.claim_url || '';
  document.getElementById('copyurl').addEventListener('click', function () {
    var i = document.getElementById('claimurl'); i.select();
    try { navigator.clipboard.writeText(i.value); } catch (e) { try { document.execCommand('copy'); } catch (e2) {} }
    this.textContent = 'Copied'; var b = this; setTimeout(function () { b.textContent = 'Copy'; }, 1500);
  });

  var sel = document.getElementById('bcard');
  function fillCards() {
    sel.textContent = '';
    cards.forEach(function (c) { sel.appendChild(el('option', { value: c.name, text: labelOf(c) })); });
    document.getElementById('needcards').textContent = '';
    if (!cards.length) document.getElementById('needcards').appendChild(el('div', { class: 'warn', text: 'Make a card first (Cards > Cards), then come back here.' }));
    document.getElementById('make').disabled = !cards.length;
    cardChanged();
  }
  function cardChanged() {
    var c = cardOf(sel.value) || {};
    document.getElementById('numbering').style.display = c.kind === 'collectible' ? '' : 'none';
    if (c.kind !== 'collectible') document.getElementById('bnum').checked = false;
    var notes = [];
    if (c.kind === 'collectible') notes.push(c.size ? 'This edition has ' + c.size + ' numbers.' : 'This edition has no size limit.');
    if (c.size && c.kind !== 'collectible') notes.push('This card has a limit of ' + c.size + ' people; codes stop working when it is full.');
    if (c.hidden) notes.push('This card is set to "Only I give it out", which is fine: codes are exactly how you hand it out.');
    document.getElementById('cardnote').textContent = notes.join(' ');
  }
  sel.addEventListener('change', cardChanged);

  document.getElementById('make').addEventListener('click', function () {
    var btn = this; btn.disabled = true; say('Making codes…', true);
    var num = document.getElementById('bnum').checked;
    fetch('/admin/codes/make', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: document.getElementById('bname').value, tier: sel.value, count: parseInt(document.getElementById('bcount').value, 10) || 0,
                             numbered: num, start: parseInt(document.getElementById('bstart').value, 10) || 1 }) })
      .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
      .then(function (res) {
        btn.disabled = false;
        if (res.status === 401) { say('You were logged out. Log in again.', false); return; }
        if (!res.body.success) { say(res.body.error || 'Could not make the codes.', false); return; }
        batches = res.body.batches || batches; cards = res.body.cards || cards;
        say('Made ' + res.body.made + ' code' + (res.body.made === 1 ? '' : 's') + '. Press Show codes below to see them, or print the sheet.', true);
        document.getElementById('bname').value = '';
        renderBatches(res.body.batch && res.body.batch.id);
      }).catch(function () { btn.disabled = false; say('Could not reach the server.', false); });
  });

  var openIds = {};
  try { var q = new URLSearchParams(location.search).get('open'); if (q) openIds[q] = true; } catch (e) {}
  function copyText(text, btn, label) {
    var ok = false;
    try { navigator.clipboard.writeText(text); ok = true; } catch (e) {}
    if (!ok) { try { var ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); ok = document.execCommand('copy'); document.body.removeChild(ta); } catch (e2) {} }
    btn.textContent = ok ? 'Copied' : 'Could not copy'; setTimeout(function () { btn.textContent = label; }, 1800);
  }
  function renderBatches(openId) {
    var root = document.getElementById('batches'); root.textContent = '';
    if (openId) openIds[openId] = true;
    if (!batches.length) { root.appendChild(el('div', { class: 'empty', text: 'No batches yet.' })); return; }
    batches.forEach(function (b) { root.appendChild(renderBatch(b)); });
  }
  function renderBatch(b) {
    var c = cardOf(b.tier), msg = el('div', { class: 'msg' }), listBox = el('div');
    var stat = b.claimed + ' of ' + b.count + ' claimed · ' + b.unused + ' unused' + (b.cancelled ? ' · ' + b.cancelled + ' cancelled' : '') + (b.numbered ? ' · numbered from ' + b.start : '');
    function showList() {
      listBox.textContent = ''; listBox.appendChild(el('div', { class: 'hint', text: 'Loading…' }));
      fetch('/admin/codes/list?batch=' + encodeURIComponent(b.id), { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (j) {
        listBox.textContent = '';
        if (!j.success) { listBox.appendChild(el('div', { class: 'msg err', text: j.error || 'Could not load.' })); return; }
        var link = function (r) { return (S.claim_url || '') + '?code=' + r.code; };
        var fresh = j.codes.filter(function (r) { return r.state === 'new'; });
        var bar = el('div', { class: 'acts' }, []);
        if (fresh.length) {
          var b1 = el('button', { type: 'button', class: 'small', text: 'Copy all links' }), b2 = el('button', { type: 'button', class: 'small', text: 'Copy all codes' });
          b1.addEventListener('click', function () { copyText(fresh.map(link).join('\n'), b1, 'Copy all links'); });
          b2.addEventListener('click', function () { copyText(fresh.map(function (r) { return r.shown; }).join('\n'), b2, 'Copy all codes'); });
          bar.appendChild(b1); bar.appendChild(b2);
          listBox.appendChild(el('div', { class: 'hint', text: 'These copy the ' + fresh.length + ' unused code' + (fresh.length === 1 ? '' : 's') + ', one per line. Paste them into an email, a message or a document.' }));
          listBox.appendChild(bar);
        }
        var t = el('table', { class: 'codes' }, [el('tr', {}, [el('th', { text: 'Code' }), el('th', { text: 'Link' }), el('th', { text: 'No.' }), el('th', { text: 'Status' }), el('th', { text: 'Claimed by' })])]);
        j.codes.forEach(function (r) {
          t.appendChild(el('tr', {}, [el('td', { class: 'mono', text: r.shown }), el('td', { class: 'mono', text: link(r) }), el('td', { text: r.number ? String(r.number) : '' }),
            el('td', { text: r.state === 'new' ? 'unused' : r.state === 'used' ? 'claimed' : r.state }), el('td', { text: r.email || '' })]));
        });
        listBox.appendChild(t);
      }).catch(function () { listBox.textContent = ''; listBox.appendChild(el('div', { class: 'msg err', text: 'Could not reach the server.' })); });
    }
    var showBtn = el('button', { type: 'button', class: 'small', 'data-act': 'show', text: openIds[b.id] ? 'Hide codes' : 'Show codes' });
    showBtn.addEventListener('click', function () {
      if (listBox.firstChild) { listBox.textContent = ''; delete openIds[b.id]; showBtn.textContent = 'Show codes'; }
      else { openIds[b.id] = true; showBtn.textContent = 'Hide codes'; showList(); }
    });
    function twoStep(label, sure, path, after) {
      var bt = el('button', { type: 'button', class: 'small danger', 'data-act': path, text: label }), armed = false, tm = null;
      bt.addEventListener('click', function () {
        if (!armed) { armed = true; bt.textContent = sure; tm = setTimeout(function () { armed = false; bt.textContent = label; }, 5000); return; }
        clearTimeout(tm); armed = false; bt.textContent = label; bt.disabled = true;
        fetch('/admin/codes/' + path, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ batch: b.id }) })
          .then(function (r) { return r.json(); }).then(function (j) {
            bt.disabled = false;
            if (!j.success) { msg.textContent = j.error || 'Failed.'; msg.className = 'msg err'; return; }
            batches = j.batches || batches; renderBatches();
          }).catch(function () { bt.disabled = false; msg.textContent = 'Could not reach the server.'; msg.className = 'msg err'; });
      });
      return bt;
    }
    var acts = el('div', { class: 'acts' }, [
      showBtn,
      el('a', { class: 'small', href: '/admin/codes/print?batch=' + encodeURIComponent(b.id), target: '_blank', rel: 'noopener', text: 'Printable sheet' }),
      el('a', { class: 'small', href: '/admin/codes/txt?batch=' + encodeURIComponent(b.id), text: 'Download (text file)' }),
      el('a', { class: 'small', href: '/admin/codes/csv?batch=' + encodeURIComponent(b.id), text: 'Download (spreadsheet file)' }),
      b.unused ? twoStep('Cancel unused codes', 'Really cancel ' + b.unused + '?', 'cancel') : null,
      !b.claimed ? twoStep('Remove batch', 'Really remove?', 'delete') : null
    ]);
    var box = el('div', { class: 'panel' }, [
      el('div', { class: 'batch-head' }, [el('div', { class: 'batch-name', text: b.name }), el('div', { class: 'hint', text: (c ? labelOf(c) : b.tier + ' (card removed)') + ' · ' + String(b.created_at || '').slice(0, 10) })]),
      el('div', { class: 'stat', text: stat }), acts, msg, listBox]);
    if (openIds[b.id]) showList();
    return box;
  }
  fillCards(); renderBatches();
})();
</script>
__THEME_JS__
</body></html>
"""
