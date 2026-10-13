"""
Credential Protocol: the "Recipes" screen of the admin dashboard (under Cards).

Six starting points, each a short list of plain questions. Pressing the button builds everything behind it
(the card(s), the set, the batch of claim codes: see recipes.py) and says what to do next.
Everything reaches the browser as JSON in a data block and becomes DOM with textContent / value only, never HTML.
"""

import json
import admin_theme
from html import escape as esc_html


def _json_for_script(obj) -> str:
    return (json.dumps(obj).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _f(id, label, type="text", hint="", default="", options=None, show=None, placeholder="", required=False):
    return {"id": id, "label": label, "type": type, "hint": hint, "default": default, "options": options or [],
            "show": show, "placeholder": placeholder, "required": required}


_WHO = [["anyone", "Anyone can sign up on my page"], ["invite", "Only people I invite (with a link or code)"]]

# What each recipe asks. Field types: text, number, select, check, datetime, card (one card), cards (several), sections.
SPEC = [
    {"id": "membership", "title": "Membership", "blurb": "People join and get access for a week, a month, a year, forever, or any length you choose. Free or paid, with an optional free trial.",
     "button": "Create the membership",
     "fields": [
         _f("name", "Name", placeholder="Fan club", required=True),
         _f("price", "Price (0 = free)", "number", default="0"),
         _f("length", "How long does one membership last?", "select", default="monthly", hint="After this, the member can renew.",
            options=[["weekly", "One week"], ["monthly", "One month"], ["quarterly", "Three months"], ["yearly", "One year"],
                     ["forever", "Forever (never ends)"], ["custom", "A number of days I choose"]]),
         _f("custom_days", "Number of days", "number", default="14", show={"field": "length", "is": ["custom"]}),
         _f("trial", "Offer a free trial first", "check", hint="Makes a second, free card that people can try before they join."),
         _f("trial_days", "Free trial: how many days?", "number", default="7", show={"field": "trial", "is": [True]}),
         _f("who", "Who can sign up?", "select", default="anyone", options=_WHO),
         _f("codes", "Make invitation codes: how many? (0 for none)", "number", default="0", show={"field": "who", "is": ["invite"]},
            hint="Each code gives one person the membership. You print or send them."),
         _f("limit", "Limit the number of members (leave empty for no limit)", "number"),
         _f("unlocks", "What do members unlock?", "sections", hint="The sections of your Content. You can add more later under Content."),
     ]},
    {"id": "ticket", "title": "Event ticket", "blurb": "One event with a date and place. Sell tickets, give them away, or send invitation codes. Check people in on the day.",
     "button": "Create the ticket",
     "fields": [
         _f("name", "Name of the event", placeholder="Summer party", required=True),
         _f("starts_at", "Starts", "datetime", required=True),
         _f("ends_at", "Ends (optional)", "datetime"),
         _f("place", "Place", placeholder="The old warehouse, Main Street 1"),
         _f("price", "Ticket price (0 = free)", "number", default="0"),
         _f("tickets", "How many tickets? (leave empty for no limit)", "number"),
         _f("who", "Who can get a ticket?", "select", default="anyone", options=_WHO),
         _f("codes", "Make invitation codes: how many? (0 for none)", "number", default="0", show={"field": "who", "is": ["invite"]}),
     ]},
    {"id": "edition", "title": "Collectible or numbered edition", "blurb": "Photo sets, albums, wine bottles, art prints. Numbered (\"No. 37 of 100\") or not numbered, your choice. Print a code for each one, let anyone sign up, or hand them out yourself.",
     "button": "Create the collectible",
     "fields": [
         _f("name", "Name", placeholder="Cabernet Sauvignon 2024", required=True),
         _f("numbered", "Number each copy (No. 1 of 100, No. 2 of 100...)", "check", default=True, hint="Untick for a collectible with no numbers."),
         _f("size", "How many copies? (empty = no limit, only when not numbered)", "number", default="100"),
         _f("price", "Price (0 = free)", "number", default="0", hint="Leave at 0 if you sell the bottle or album yourself and the card is the bonus."),
         _f("who", "How do people get theirs?", "select", default="labels",
            options=[["labels", "I print a code for each one (labels, stickers, inserts)"], ["anyone", "Anyone can sign up on my page"], ["hand", "I give them out myself"]]),
         _f("codes", "How many codes to print?", "number", default="", show={"field": "who", "is": ["labels"]}, hint="Leave empty for one per copy (up to 1000 at a time)."),
         _f("start", "First number", "number", default="1", show={"field": "numbered", "is": [True]}, hint="Only for printed codes. Use another number to print the next batch, for example 101."),
         _f("unlocks", "What does the owner unlock? (for example the album downloads)", "sections"),
     ]},
    {"id": "series", "title": "Release in parts", "blurb": "An EP, a photo book, a course: a new part opens every week. Fans collect the parts, and everyone who gets them all receives a bonus edition by itself.",
     "button": "Create the release",
     "fields": [
         _f("name", "Name of the release", placeholder="Midnight EP", required=True),
         _f("parts", "Names of the parts, separated by commas", placeholder="Song 1, Song 2, Song 3, Song 4", required=True, hint="2 to 12 parts. Each part is its own card."),
         _f("starts_at", "First part opens (leave empty for right now)", "datetime"),
         _f("gap", "A new part opens", "select", default="weekly", options=[["weekly", "Every week"], ["daily", "Every day"], ["biweekly", "Every two weeks"], ["monthly", "Every 30 days"], ["custom", "Every number of days I choose"]]),
         _f("gap_days", "Number of days between parts", "number", default="7", show={"field": "gap", "is": ["custom"]}),
         _f("price", "Price of each part (0 = free)", "number", default="0"),
         _f("bonus", "Give a bonus edition to everyone who collects all the parts", "check", default=True),
         _f("bonus_name", "Name of the bonus (empty = the name plus Deluxe)", "text", placeholder="Midnight EP Deluxe", show={"field": "bonus", "is": [True]}),
         _f("bonus_numbered", "Number the bonus (No. 1 of 100...)", "check", show={"field": "bonus", "is": [True]}),
         _f("bonus_size", "How many bonus editions?", "number", default="100", show={"field": "bonus_numbered", "is": [True]}),
         _f("unlocks", "Anything already in Content that the bonus should unlock too (optional)", "sections", show={"field": "bonus", "is": [True]},
            hint="Each part and the bonus get their own empty shelf in Content. You put the music there afterwards."),
     ]},
    {"id": "collect", "title": "Collect and get a reward", "blurb": "\"Collect 3 bottles, get 15% off\", \"5 stamps, a free coffee\", \"all four album parts unlock the bonus\". The reward arrives by itself.",
     "button": "Create the reward",
     "fields": [
         _f("mode", "What do people collect?", "select", default="same",
            options=[["same", "The same card, several times"], ["different", "Different cards"]]),
         _f("card", "Which card?", "card", show={"field": "mode", "is": ["same"]}, hint="Make it first with one of the other recipes."),
         _f("need", "How many must they collect?", "number", default="3", show={"field": "mode", "is": ["same"]}),
         _f("repeat", "Let one person get this card several times", "check", default=True, show={"field": "mode", "is": ["same"]},
            hint="Needed to collect the same card. Untick it if you only hand the card out with codes (codes always work)."),
         _f("cards", "Which cards? (tick two or more)", "cards", show={"field": "mode", "is": ["different"]}),
         _f("need", "How many of them? (leave empty for all of them)", "number", show={"field": "mode", "is": ["different"]}, hint="For example 2 means any 2 of the ticked cards."),
         _f("reward_title", "What is the reward?", placeholder="15% off your next order", required=True),
         _f("reward_terms", "Small print (optional)", placeholder="Show this when you order"),
         _f("reward_days", "Valid for how many days after they earn it?", "number", default="90"),
         _f("include_existing", "Also reward people who already have enough", "check"),
     ]},
    {"id": "discount", "title": "Discount or gift codes", "blurb": "One-time codes for an offer such as \"10% off\" or \"one free coffee\". Put one on each receipt, package or flyer.",
     "button": "Create the codes",
     "fields": [
         _f("title", "What is the offer?", placeholder="15% off your next order", required=True),
         _f("terms", "Small print (optional)", placeholder="Show this when you order"),
         _f("days", "Valid for how many days after someone claims it?", "number", default="90"),
         _f("count", "How many codes?", "number", default="50"),
     ]},
    {"id": "certificate", "title": "Certificate", "blurb": "A certificate that never expires, for finishing a course, a workshop or a challenge.",
     "button": "Create the certificate",
     "fields": [
         _f("title", "What is it for?", placeholder="Completed the workshop", required=True),
         _f("note", "A line under the title (optional)", placeholder="Spring 2027 class"),
         _f("how", "How do people get it?", "select", default="codes",
            options=[["codes", "I hand out one-time codes"], ["hand", "I give it out myself, one by one"]]),
         _f("count", "How many codes?", "number", default="20", show={"field": "how", "is": ["codes"]}),
     ]},
]


def render(theme_css: str, theme_js: str, body_attrs: str, title: str, state: dict) -> str:
    return (_TEMPLATE
            .replace("__TITLE__", esc_html(title))
            .replace("__THEME__", theme_css)
            .replace("__NAV__", admin_theme.nav_html("recipes"))
            .replace("__BODY_ATTRS__", body_attrs)
            .replace("__THEME_JS__", theme_js)
            .replace("__STATE__", _json_for_script({**state, "spec": SPEC})))


_TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Recipes — Admin</title>
<style>
  body { background:var(--bg); color:var(--fg); font-family:var(--font); padding:32px; max-width:900px; margin:0 auto; }
  h1 { color:var(--accent-text); font-size:16px; letter-spacing:2px; text-transform:uppercase; margin-bottom:4px; }
  h2 { font-size:18px; margin:18px 0 6px; font-weight:600; color:var(--fg); letter-spacing:0; text-transform:none; }
  .nav { margin-bottom:18px; font-size:11px; letter-spacing:1px; }
  .nav a { color:var(--accent-text); text-decoration:none; margin-right:18px; }
  .hint { color:var(--muted); font-size:12px; line-height:1.6; margin:6px 0; }
  .tiles { display:grid; grid-template-columns:repeat(auto-fill, minmax(250px, 1fr)); gap:14px; margin:18px 0; }
  .tile { text-align:left; background:var(--panel); border:1px solid var(--line); color:var(--fg); font-family:var(--font); cursor:pointer;
          padding:16px; border-radius:var(--radius, 0); display:block; }
  .tile:hover, .tile:focus { border-color:var(--accent-text); outline:none; }
  .tile b { display:block; font-size:16px; margin-bottom:6px; color:var(--accent-text); }
  .tile span { font-size:13px; line-height:1.5; color:var(--soft); }
  label.l { display:block; font-size:10px; letter-spacing:1px; color:var(--soft); text-transform:uppercase; margin:14px 0 4px; }
  input[type=text], input[type=number], input[type=datetime-local], select { width:100%; background:var(--field); border:1px solid var(--line); color:var(--fg);
           font-family:var(--font); font-size:14px; padding:9px 10px; box-sizing:border-box; border-radius:var(--radius, 0); }
  .opt { display:flex; gap:8px; align-items:flex-start; font-size:14px; color:var(--fg); margin:6px 0; cursor:pointer; }
  .opt input { width:auto; margin-top:3px; }
  .form { border:1px solid var(--line); background:var(--panel); padding:6px 18px 18px; margin:14px 0; border-radius:var(--radius, 0); }
  button { font-family:var(--font); cursor:pointer; }
  .btn { background:var(--accent); color:var(--on-accent); border:none; font-size:12px; letter-spacing:1.5px; text-transform:uppercase; padding:12px 20px; border-radius:var(--radius, 0); }
  .btn:disabled { opacity:.5; cursor:default; }
  .btn.ghost { background:transparent; border:1px solid var(--accent-text); color:var(--accent-text); }
  .bar { display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin:20px 0 4px; }
  .msg { font-size:13px; } .msg.err { color:var(--bad); }
  .done { border:1px solid var(--accent-text); background:var(--panel); padding:6px 18px 18px; margin:14px 0; border-radius:var(--radius, 0); }
  .done ul { margin:6px 0 10px 18px; padding:0; font-size:14px; line-height:1.7; }
  .next { display:block; text-decoration:none; border:1px solid var(--line); padding:12px 14px; margin:8px 0; color:var(--fg); border-radius:var(--radius, 0); }
  .next:hover { border-color:var(--accent-text); }
  .next b { color:var(--accent-text); display:block; font-size:14px; }
  .next small { color:var(--muted); font-size:12px; }
  .pick { display:grid; grid-template-columns:repeat(auto-fill, minmax(200px, 1fr)); gap:2px 14px; }
__THEME__</style></head>
<body __BODY_ATTRS__>
  __NAV__
  <h1>__TITLE__ — Recipes</h1>
  <div class="hint" id="intro">Start here. Pick what you want to do, answer a few questions, and everything behind it is built for you: the cards, the rewards and the codes. You can fine-tune anything afterwards under Cards.</div>
  <div class="tiles" id="tiles"></div>
  <div id="stage"></div>

<script id="state" type="application/json">__STATE__</script>
<script>
(function () {
  var S = JSON.parse(document.getElementById('state').textContent);
  var spec = S.spec, cards = S.cards || [], sections = S.sections || [];
  var tiles = document.getElementById('tiles'), stage = document.getElementById('stage'), intro = document.getElementById('intro');
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
  spec.forEach(function (r) {
    tiles.appendChild(el('button', { type: 'button', class: 'tile', 'data-recipe': r.id, on: { click: function () { openRecipe(r); } } },
      [el('b', { text: r.title }), el('span', { text: r.blurb })]));
  });

  function openRecipe(r) {
    tiles.style.display = 'none'; intro.style.display = 'none'; stage.textContent = '';
    var vals = {}, rows = [];
    var form = el('div', { class: 'form' }, [el('h2', { text: r.title }), el('div', { class: 'hint', text: r.blurb })]);
    var msg = el('div', { class: 'msg err', role: 'status', 'aria-live': 'polite' });
    r.fields.forEach(function (f, idx) {
      var key = f.id + '#' + idx, input, row;
      if (f.type === 'select') {
        input = el('select', { 'data-field': f.id });
        f.options.forEach(function (o) { input.appendChild(el('option', { value: o[0], text: o[1] })); });
        input.value = f.default || f.options[0][0];
        vals[key] = function () { return input.value; };
        input.addEventListener('change', refresh);
        row = el('div', {}, [el('label', { class: 'l', text: f.label }), input]);
      } else if (f.type === 'check') {
        input = el('input', { type: 'checkbox', 'data-field': f.id });
        input.checked = f.default === true;
        vals[key] = function () { return input.checked; };
        input.addEventListener('change', refresh);
        row = el('div', {}, [el('label', { class: 'opt' }, [input, el('span', { text: f.label })])]);
      } else if (f.type === 'card') {
        input = el('select', { 'data-field': f.id });
        input.appendChild(el('option', { value: '', text: cards.length ? 'Choose a card…' : 'No cards yet: make one with another recipe first' }));
        cards.forEach(function (c) { input.appendChild(el('option', { value: c.name, text: c.label && c.label.toUpperCase() !== c.name ? c.label + ' (' + c.name + ')' : c.name })); });
        vals[key] = function () { return input.value; };
        row = el('div', {}, [el('label', { class: 'l', text: f.label }), input]);
      } else if (f.type === 'cards' || f.type === 'sections') {
        var list = f.type === 'cards' ? cards.map(function (c) { return { v: c.name, t: c.label || c.name }; }) : sections.map(function (c) { return { v: c.key, t: c.title }; });
        var boxes = list.map(function (o) {
          var cb = el('input', { type: 'checkbox', 'data-pick': o.v });
          if (f.type === 'sections') cb.checked = true;
          return { cb: cb, v: o.v, node: el('label', { class: 'opt' }, [cb, el('span', { text: o.t })]) };
        });
        vals[key] = function () { return boxes.filter(function (b) { return b.cb.checked; }).map(function (b) { return b.v; }); };
        row = el('div', {}, [el('label', { class: 'l', text: f.label }),
          boxes.length ? el('div', { class: 'pick' }, boxes.map(function (b) { return b.node; })) : el('div', { class: 'hint', text: f.type === 'cards' ? 'No cards yet: make some with the other recipes first.' : 'You have no content sections yet. Add some under Content; you can connect them to this card later.' })]);
      } else {
        input = el('input', { type: f.type === 'number' ? 'number' : f.type === 'datetime' ? 'datetime-local' : 'text', 'data-field': f.id });
        if (f.type === 'number') { input.setAttribute('min', '0'); input.setAttribute('step', 'any'); }
        if (f.placeholder) input.setAttribute('placeholder', f.placeholder);
        input.value = f.default || '';
        vals[key] = function () { return input.value; };
        row = el('div', {}, [el('label', { class: 'l', text: f.label + (f.required ? ' *' : '') }), input]);
      }
      if (f.hint) row.appendChild(el('div', { class: 'hint', text: f.hint }));
      rows.push({ f: f, row: row, key: key });
      form.appendChild(row);
    });
    function current(id) {
      var hit = rows.filter(function (x) { return x.f.id === id && x.row.style.display !== 'none'; })[0] || rows.filter(function (x) { return x.f.id === id; })[0];
      return hit ? vals[hit.key]() : undefined;
    }
    function refresh() {
      rows.forEach(function (x) {
        var s = x.f.show; if (!s) { x.row.style.display = ''; return; }
        var v = rows.filter(function (y) { return y.f.id === s.field; }).map(function (y) { return vals[y.key](); })[0];
        x.row.style.display = s.is.indexOf(v) > -1 ? '' : 'none';
      });
    }
    var go = el('button', { type: 'button', class: 'btn', id: 'make', text: r.button });
    var back = el('button', { type: 'button', class: 'btn ghost', text: 'Back to the recipes', on: { click: function () { stage.textContent = ''; tiles.style.display = ''; intro.style.display = ''; } } });
    form.appendChild(el('div', { class: 'bar' }, [go, back, msg]));
    stage.appendChild(form); refresh();
    go.addEventListener('click', function () {
      var answers = { tz: new Date().getTimezoneOffset() };
      rows.forEach(function (x) { if (x.row.style.display !== 'none') answers[x.f.id] = vals[x.key](); });
      go.disabled = true; msg.textContent = 'Working…'; msg.className = 'msg';
      fetch('/admin/recipes/make', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recipe: r.id, answers: answers }) })
        .then(function (res) { return res.json().then(function (j) { return { status: res.status, body: j }; }); })
        .then(function (res) {
          go.disabled = false;
          if (res.status === 401) { msg.textContent = 'You were logged out. Log in again, then try again.'; msg.className = 'msg err'; return; }
          if (!res.body.success) { msg.textContent = res.body.error || 'That did not work.'; msg.className = 'msg err'; return; }
          showDone(r, res.body);
        }).catch(function () { go.disabled = false; msg.textContent = 'Could not reach the server. Nothing was made.'; msg.className = 'msg err'; });
    });
  }

  function showDone(r, b) {
    stage.textContent = '';
    var ul = el('ul', {}); (b.lines || []).forEach(function (t) { ul.appendChild(el('li', { text: t })); });
    var box = el('div', { class: 'done', id: 'result' }, [el('h2', { text: 'Done. Here is what was made:' }), ul]);
    if (b.claim_url) box.appendChild(el('div', { class: 'hint', text: 'People enter their code at ' + b.claim_url + ' (the QR codes on the sheet open it by themselves).' }));
    if (b.issued) box.appendChild(el('div', { class: 'hint', text: b.issued + (b.issued === 1 ? ' reward was' : ' rewards were') + ' given out right away.' }));
    box.appendChild(el('h2', { text: 'What to do next' }));
    (b.next || []).forEach(function (n) {
      box.appendChild(el('a', { class: 'next', href: n.url }, [el('b', { text: n.label }), el('small', { text: n.note || '' })]));
    });
    box.appendChild(el('div', { class: 'bar' }, [el('button', { type: 'button', class: 'btn ghost', id: 'again', text: 'Make something else', on: { click: function () { location.reload(); } } })]));
    stage.appendChild(box);
    window.scrollTo(0, 0);
  }
})();
</script>
__THEME_JS__
</body></html>
"""
