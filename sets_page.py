"""
Credential Protocol: the "Sets" screen of the admin dashboard (under Cards).

A set = a few cards to collect (the pieces) + one reward card. When one person
holds every piece, the reward is issued to them automatically (card_sets.py has
the rules, credential_api.run_sets_now does the issuing). Everything the creator
typed or saved reaches the browser as JSON in a data block and becomes DOM with
textContent / value only, never HTML.
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
            .replace("__NAV__", admin_theme.nav_html("sets"))
            .replace("__BODY_ATTRS__", body_attrs)
            .replace("__THEME_JS__", theme_js)
            .replace("__STATE__", _json_for_script(state)))


_TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sets — Admin</title>
<style>
  body { background:var(--bg); color:var(--fg); font-family:var(--font); padding:32px; max-width:900px; margin:0 auto; }
  h1 { color:var(--accent-text); font-size:16px; letter-spacing:2px; text-transform:uppercase; margin-bottom:4px; }
  .nav { margin-bottom:18px; font-size:11px; letter-spacing:1px; }
  .nav a { color:var(--accent-text); text-decoration:none; margin-right:18px; }
  .nav a:hover { text-decoration:underline; }
  .hint { color:var(--muted); font-size:12px; line-height:1.6; margin:6px 0; }
  .hint b { color:var(--soft); }
  label.l { display:block; font-size:10px; letter-spacing:1px; color:var(--soft); text-transform:uppercase; margin:12px 0 4px; }
  input[type=text], select { width:100%; background:var(--field); border:1px solid var(--line); color:var(--fg);
           font-family:var(--font); font-size:14px; padding:9px 10px; box-sizing:border-box; border-radius:var(--radius, 0); }
  button { font-family:var(--font); cursor:pointer; }
  .btn { background:var(--accent); color:var(--on-accent); border:none; font-size:11px; letter-spacing:1.5px; text-transform:uppercase; padding:11px 18px; border-radius:var(--radius, 0); }
  .btn.ghost { background:transparent; border:1px solid var(--accent-text); color:var(--accent-text); }
  .btn:disabled { opacity:.5; cursor:default; }
  .small { background:transparent; border:1px solid var(--line); color:var(--soft); font-size:10px; letter-spacing:1px; text-transform:uppercase; padding:6px 10px; border-radius:var(--radius, 0); }
  .small:hover { border-color:var(--accent-text); color:var(--accent-text); }
  .set { border:1px solid var(--line); background:var(--panel); padding:14px 16px; margin:16px 0; border-radius:var(--radius, 0); }
  .set-head { display:flex; gap:10px; align-items:flex-end; flex-wrap:wrap; }
  .set-head > div { flex:1 1 220px; }
  .pieces { display:grid; grid-template-columns:repeat(auto-fill, minmax(190px, 1fr)); gap:6px 14px; margin:4px 0; }
  .pc { display:flex; gap:8px; align-items:center; font-size:14px; text-transform:none; letter-spacing:0; color:var(--fg); margin:0; cursor:pointer; }
  .pc input { width:auto; margin:0; }
  .pc small { color:var(--muted); font-size:11px; }
  .pc.off { opacity:.45; cursor:default; }
  .opt { display:flex; gap:8px; align-items:flex-start; font-size:13px; text-transform:none; letter-spacing:0; color:var(--fg); margin:12px 0 0; cursor:pointer; }
  .opt input { width:auto; margin-top:3px; }
  .stat { font-size:12px; color:var(--soft); margin-top:10px; }
  .warn { background:var(--warn-bg); color:var(--warn); font-size:12px; line-height:1.6; padding:10px 14px; margin:10px 0; border-radius:var(--radius, 0); }
  .warn ul { margin:4px 0 0 18px; padding:0; }
  .bar { display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin:18px 0; }
  .msg { font-size:12px; }
  .msg.ok { color:var(--ok); } .msg.err { color:var(--bad); }
  .empty { color:var(--muted); font-size:13px; padding:8px 0; }
  .newreward { border-left:3px solid var(--accent-text); padding:2px 0 6px 12px; margin:10px 0; }
  input[type=number] { background:var(--field); border:1px solid var(--line); color:var(--fg); font-family:var(--font); font-size:14px; padding:9px 10px; box-sizing:border-box; border-radius:var(--radius, 0); }
__THEME__</style></head>
<body __BODY_ATTRS__>
  __NAV__
  <h1>__TITLE__ — Sets</h1>
  <div class="hint">A <b>set</b> is something people collect to earn a <b>reward card</b>, which they get automatically with one email. Three ways to use it: <b>every card in a list</b> (a robot built from head, arms and legs), <b>any few of a list</b> (any 3 of my 5 wines), or <b>the same card several times</b> ("collect the stamp 5 times, get a free coffee"). The reward can be a <b>voucher</b> such as "15% off your next order": you can create it right here.</div>
  <div class="hint">People are matched by <b>email address</b> (they can use different names). A card still counts after it ran out or a ticket was used, but not if you revoked it. The reward is given <b>once per person</b>. The reward is usually a card set to <b>Only me</b> (on the card press <b>Advanced</b>, then <b>Who can get this card?</b>), so nobody can just sign up for it.</div>
  <div id="needcards"></div>
  <div id="sets"></div>
  <div class="bar">
    <button type="button" class="btn ghost" id="add">+ New set</button>
    <span class="hint">or start from:</span>
    <button type="button" class="small" id="tpl-all">Every card in a list</button>
    <button type="button" class="small" id="tpl-same">The same card, 5 times</button>
    <button type="button" class="small" id="tpl-one">Get one card, get a reward</button>
    <button type="button" class="btn" id="save">Save sets</button>
    <span class="msg" id="msg" role="status" aria-live="polite"></span>
  </div>
  <div id="warnings"></div>
  <div class="hint" id="emailnote"></div>

<script id="state" type="application/json">__STATE__</script>
<script>
(function () {
  var S = JSON.parse(document.getElementById('state').textContent);
  var sets = S.sets, cards = S.cards || [], dirty = false;
  var root = document.getElementById('sets'), msg = document.getElementById('msg');
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
  function say(t, good) { msg.textContent = t || ''; msg.className = 'msg ' + (good ? 'ok' : 'err'); }
  function touch() { dirty = true; msg.textContent = ''; }
  function up(v) { return String(v || '').toUpperCase(); }
  function has(arr, name) { return arr.some(function (p) { return up(p) === up(name); }); }
  function cardOf(name) { return cards.filter(function (c) { return up(c.name) === up(name); })[0]; }

  function renderNeed() {
    var n = document.getElementById('needcards'); n.textContent = '';
    if (cards.length < 1) n.appendChild(el('div', { class: 'warn', text: 'Make the card people collect under Cards first (a collectible, a pass, anything). The reward can be created here as a voucher.' }));
  }
  function renderSet(s, i) {
    var name = el('input', { type: 'text', maxlength: '60', placeholder: 'The Robot', 'data-role': 'name' }); name.value = s.name || '';
    name.addEventListener('input', function () { s.name = name.value; touch(); });
    var reward = el('select', { 'data-role': 'reward' });
    reward.appendChild(el('option', { value: '', text: 'Choose the reward card…' }));
    reward.appendChild(el('option', { value: '__new__', text: '+ Create a new voucher as the reward (like "15% off")' }));
    cards.forEach(function (c) {
      if (has(s.pieces, c.name)) return;
      reward.appendChild(el('option', { value: c.name, text: c.label && up(c.label) !== up(c.name) ? c.label + ' (' + c.name + ')' : c.name }));
    });
    reward.value = s.reward && !has(s.pieces, s.reward) && cardOf(s.reward) ? cardOf(s.reward).name : (s.new_reward ? '__new__' : '');
    reward.addEventListener('change', function () {
      if (reward.value === '__new__') { s.reward = ''; s.new_reward = s.new_reward || { title: '', terms: '', days: 90 }; }
      else { s.reward = reward.value; s.new_reward = null; }
      touch(); render();
    });
    var head = el('div', { class: 'set-head' }, [
      el('div', {}, [el('label', { class: 'l', text: 'Name of the set' }), name]),
      el('div', {}, [el('label', { class: 'l', text: 'Reward (given when the set is complete)' }), reward]),
      el('button', { type: 'button', class: 'small', text: 'Delete set', on: { click: function () { sets.splice(i, 1); touch(); render(); } } })
    ]);
    var grid = el('div', { class: 'pieces', 'data-role': 'pieces' });
    cards.forEach(function (c) {
      var isReward = up(s.reward) === up(c.name);
      var cb = el('input', { type: 'checkbox', 'data-card': c.name });
      cb.checked = has(s.pieces, c.name); cb.disabled = isReward;
      cb.addEventListener('change', function () {
        s.pieces = (s.pieces || []).filter(function (p) { return up(p) !== up(c.name); });
        if (cb.checked) s.pieces.push(c.name);
        if (cb.checked && up(s.reward) === up(c.name)) s.reward = '';
        touch(); render();
      });
      grid.appendChild(el('label', { class: 'pc' + (isReward ? ' off' : '') }, [cb, el('span', { text: c.label && up(c.label) !== up(c.name) ? c.label : c.name }),
        c.hidden ? el('small', { text: 'only me' }) : null]));
    });
    var picked = (s.pieces || []).length;
    var needIn = el('input', { type: 'number', min: '1', max: picked === 1 ? '20' : String(Math.max(1, picked - 1)), 'data-role': 'need',
      placeholder: picked > 1 ? 'all ' + picked : '1', style: 'width:110px' });
    needIn.value = s.need ? String(s.need) : '';
    needIn.addEventListener('input', function () { s.need = needIn.value; touch(); });
    var needHint = picked === 0 ? 'Tick the card or cards people collect.'
      : picked === 1 ? 'One card: how many copies must a person hold? Every copy counts. People get extra copies from claim codes (a code always works), or from you under People. To let people sign up for it again on their own, set the card\'s one-per-email rule to unlimited under Cards, Advanced.'
      : 'Leave empty to need every card (' + picked + '), or type a smaller number to reward "any ' + (s.need && s.need < picked ? s.need : 'few') + ' of these". Each different card counts once.';
    var need = el('div', {}, [
      el('label', { class: 'l', text: picked === 1 ? 'How many copies?' : 'How many must they collect?' }), needIn,
      el('div', { class: 'hint', text: needHint })]);
    var nr = null;
    if (s.new_reward) {
      var t1 = el('input', { type: 'text', maxlength: '40', placeholder: '15% off your next order', 'data-role': 'nr-title' }); t1.value = s.new_reward.title || '';
      t1.addEventListener('input', function () { s.new_reward.title = t1.value; touch(); });
      var t2 = el('input', { type: 'text', maxlength: '60', placeholder: 'Show this when you order (optional)', 'data-role': 'nr-terms' }); t2.value = s.new_reward.terms || '';
      t2.addEventListener('input', function () { s.new_reward.terms = t2.value; touch(); });
      var t3 = el('input', { type: 'number', min: '1', max: '3650', 'data-role': 'nr-days', style: 'width:110px' }); t3.value = s.new_reward.days || 90;
      t3.addEventListener('input', function () { s.new_reward.days = t3.value; touch(); });
      nr = el('div', { class: 'newreward' }, [
        el('div', { class: 'hint', text: 'This makes a voucher card (only you can give it out) when you save. You can restyle it later under Cards.' }),
        el('label', { class: 'l', text: 'What is the reward?' }), t1,
        el('label', { class: 'l', text: 'Small print' }), t2,
        el('label', { class: 'l', text: 'Valid for how many days after they earn it?' }), t3]);
    }
    var inc = el('input', { type: 'checkbox', 'data-role': 'existing' }); inc.checked = !!s.include_existing;
    inc.addEventListener('change', function () { s.include_existing = inc.checked; touch(); });
    var box = el('div', { class: 'set' }, [head, nr,
      el('label', { class: 'l', text: 'Card(s) to collect' }), grid, need,
      el('label', { class: 'opt' }, [inc, el('span', { text: 'Also give the reward to people who already hold every piece' + (s.waiting ? ' (' + s.waiting + ' right now)' : '') + '. Left unticked, only people who finish the set from now on get it.' })])]);
    if (s.id) {
      var bits = [(s.collecting || 0) + ' collecting', (s.rewarded || 0) + ' rewarded'];
      if (s.waiting && !s.include_existing) bits.push(s.waiting + ' already complete (not rewarded)');
      box.appendChild(el('div', { class: 'stat', text: bits.join(' · ') }));
    }
    if (s.problems && s.problems.length) box.appendChild(el('div', { class: 'warn', text: 'This set is paused: no card called ' + s.problems.join(', ') + ' any more. Pick the cards again and save.' }));
    return box;
  }
  function render() {
    root.textContent = '';
    if (!sets.length) root.appendChild(el('div', { class: 'empty', text: 'No sets yet. Press "+ New set".' }));
    sets.forEach(function (s, i) { root.appendChild(renderSet(s, i)); });
    renderNeed();
  }
  document.getElementById('add').addEventListener('click', function () {
    sets.push({ name: '', pieces: [], need: '', reward: '', include_existing: false }); touch(); render();
  });
  [['tpl-all', 'Every card in a list', ''], ['tpl-same', 'The same card, 5 times', 5], ['tpl-one', 'Get one card, get a reward', 1]].forEach(function (t) {
    document.getElementById(t[0]).addEventListener('click', function () {
      sets.push({ name: '', pieces: [], need: t[2], reward: '', new_reward: { title: '', terms: '', days: 90 }, include_existing: false }); touch(); render();
    });
  });
  function showWarnings(list) {
    var w = document.getElementById('warnings'); w.textContent = '';
    if (!list || !list.length) return;
    var ul = el('ul'); list.forEach(function (t) { ul.appendChild(el('li', { text: t })); });
    w.appendChild(el('div', { class: 'warn' }, [el('b', { text: 'Saved, but some things were left out:' }), ul]));
  }
  var saveBtn = document.getElementById('save');
  saveBtn.addEventListener('click', function () {
    saveBtn.disabled = true; say('Saving…', true);
    fetch('/admin/sets', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sets: sets.map(function (s) { return { id: s.id, name: s.name, pieces: s.pieces, need: parseInt(s.need, 10) || 0, reward: s.reward,
        new_reward: (!s.reward && s.new_reward) ? s.new_reward : undefined, include_existing: !!s.include_existing }; }) }) })
      .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
      .then(function (res) {
        saveBtn.disabled = false;
        if (res.status === 401) { say('You were logged out. Log in again, then save.', false); return; }
        if (!res.body.success) { say(res.body.error || 'Save failed.', false); return; }
        sets = res.body.sets; cards = res.body.cards || cards; dirty = false; render(); showWarnings(res.body.warnings);
        say('Saved.' + (res.body.created && res.body.created.length ? ' Created the voucher "' + res.body.created.join('", "') + '".' : '') + (res.body.issued ? ' ' + res.body.issued + (res.body.issued === 1 ? ' reward was' : ' rewards were') + ' given out right now.' : '') + (res.body.more ? ' ' + res.body.more + ' more will go out over the next hour or so.' : ''), true);
      }).catch(function () { saveBtn.disabled = false; say('Could not reach the server. Nothing was saved.', false); });
  });
  window.addEventListener('beforeunload', function (e) { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
  document.getElementById('emailnote').textContent = S.email_ready
    ? 'When someone completes a set they get the "Set completed" email (edit it under Settings, Emails). The button in it opens their reward card.'
    : 'Email is not set up yet, so rewards are still given automatically but nobody is emailed. People find their new card on their member page.';
  render();
})();
</script>
__THEME_JS__
</body></html>
"""
