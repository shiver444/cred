"""
Credential Protocol — the Check-in page (event tickets).

For the door: scan a ticket's QR code with the camera (or paste its link or
code) and the ticket is checked off straight away, so a copy can't be used a
second time. The answer is a big green "Let in" or a red reason.

This file only draws the page; credential_api.py does the look-ups
(`/admin/checkin/scan`, `/admin/checkin/use`, `/admin/checkin/undo`).
"""

import json
import admin_theme
import re
from datetime import datetime, timezone
from html import escape

_CODE = re.compile(r"[A-Za-z0-9_-]{8,64}")


def parse_code(text: str):
    """What was scanned or pasted -> (credential id, access code or ""), or
    (None, ""). Accepts the QR's link (…?id=…&h=…), a bare id, or id plus h."""
    t = str(text or "").strip()[:600]
    if not t:
        return None, ""
    m = re.search(r"[?&#]id=([A-Za-z0-9_-]{8,64})", t)
    if m:
        h = re.search(r"[?&#]h=([A-Fa-f0-9]{16,128})", t)
        return m.group(1), (h.group(1).lower() if h else "")
    if _CODE.fullmatch(t):
        return t, ""
    return None, ""


def stats(registry: list, now=None) -> list:
    """Per event: how many tickets were issued and how many are checked in.
    [{"name": "Halloween Live", "total": 12, "used": 7}, ...] (revoked tickets
    are not counted)."""
    out = {}
    for e in registry or []:
        if e.get("kind") != "ticket" or e.get("revoked"):
            continue
        ev = e.get("event") if isinstance(e.get("event"), dict) else {}
        key = (ev.get("name") or e.get("tier") or "Tickets", ev.get("starts_at") or "")
        row = out.setdefault(key, {"name": key[0], "when": ev.get("when") or "", "total": 0, "used": 0})
        row["total"] += 1
        if e.get("used_at"):
            row["used"] += 1
    return sorted(out.values(), key=lambda r: (r["when"], r["name"]))


def render(theme_css: str, theme_js: str, body_attrs: str, title: str, stat_rows: list, has_tickets: bool) -> str:
    data = json.dumps({"stats": stat_rows}).replace("<", "\\u003c")
    note = ("" if has_tickets else
            '<div class="warn">You have no event ticket tiers yet. On the Dashboard, open <b>Tiers &amp; pricing</b> and '
            'set a tier\'s <b>Card type</b> to <b>Event ticket</b>.</div>')
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Check-in — Admin</title>
<style>
  body {{ background:var(--bg); color:var(--fg); font-family:var(--font); padding:32px; }}
  h1 {{ color:var(--accent-text); font-size:16px; letter-spacing:2px; text-transform:uppercase; }}
  .nav {{ margin-bottom:18px; font-size:11px; letter-spacing:1px; }}
  .nav a {{ color:var(--accent-text); text-decoration:none; margin-right:18px; }}
  .nav a:hover {{ text-decoration:underline; }}
  .ci {{ max-width:560px; }}
  .ci .hint {{ color:var(--muted); font-size:12px; line-height:1.6; margin:8px 0; }}
  .ci-btn {{ background:var(--accent); border:1px solid var(--accent-text); color:var(--on-accent); font-family:var(--font); font-size:13px;
    padding:12px 16px; cursor:pointer; border-radius:var(--radius, 0); }}
  .ci-btn.ghost {{ background:transparent; color:var(--accent-text); }}
  .ci-btn:disabled {{ opacity:.5; cursor:default; }}
  .ci-row {{ display:flex; gap:8px; flex-wrap:wrap; margin:12px 0; }}
  .ci-row input[type=text] {{ flex:1 1 220px; min-width:0; box-sizing:border-box; background:var(--field); border:1px solid var(--line); color:var(--fg);
    font-family:var(--font); font-size:16px; padding:12px; border-radius:var(--radius, 0); }}
  .ci-opt {{ color:var(--muted); font-size:12px; display:flex; gap:8px; align-items:center; margin:6px 0; }}
  .ci-cam {{ display:none; margin:12px 0; }}
  .ci-cam video {{ width:100%; max-height:46vh; background:#000; border-radius:var(--radius, 0); object-fit:cover; }}
  .ci-res {{ display:none; margin:16px 0; padding:18px; border:1px solid var(--line); border-radius:var(--radius, 0); }}
  .ci-res.ok {{ display:block; background:var(--ok-bg); color:var(--ok); border-color:var(--ok); }}
  .ci-res.bad {{ display:block; background:var(--warn-bg); color:var(--bad); border-color:var(--bad); }}
  .ci-res.peek {{ display:block; background:var(--panel); color:var(--fg); }}
  .ci-big {{ font-size:22px; font-weight:700; margin-bottom:6px; }}
  .ci-line {{ font-size:14px; line-height:1.6; color:inherit; overflow-wrap:anywhere; }}
  .ci-undo {{ margin-top:10px; background:transparent; border:1px solid currentColor; color:inherit; font-family:var(--font); font-size:12px; padding:8px 12px; cursor:pointer; }}
  .ci-stats {{ margin-top:22px; }}
  .ci-stat {{ display:flex; justify-content:space-between; gap:12px; padding:9px 0; border-bottom:1px solid var(--line); font-size:13px; }}
  .ci-stat span:last-child {{ color:var(--soft); white-space:nowrap; }}
  .warn {{ background:var(--warn-bg); color:var(--warn); font-size:12px; line-height:1.6; padding:10px 14px; margin:14px 0 0; }}
{theme_css}</style></head>
<body {body_attrs}>
  {admin_theme.nav_html("checkin", True)}
  <h1>{escape(title)} — Check-in</h1>
  <div class="ci">
    <div class="hint">Scan a ticket's QR code, or paste its link or code. A good ticket is checked off right away and can't be used again.</div>
    {note}
    <div class="ci-row">
      <button type="button" class="ci-btn" id="ci-cam-btn">Scan with the camera</button>
    </div>
    <div class="ci-cam" id="ci-cam"><video id="ci-video" playsinline muted></video><div class="hint" id="ci-cam-msg"></div></div>
    <form class="ci-row" id="ci-form" autocomplete="off">
      <input type="text" id="ci-code" placeholder="Paste a ticket link or code" aria-label="Ticket link or code">
      <button type="submit" class="ci-btn ghost" id="ci-go">Check in</button>
    </form>
    <label class="ci-opt"><input type="checkbox" id="ci-peek"> Only look, don't mark the ticket as used</label>
    <div class="ci-res" id="ci-res" role="status" aria-live="polite"></div>
    <div class="ci-stats" id="ci-stats"></div>
  </div>
  <script type="application/json" id="ci-data">{data}</script>
  <script>
  (function () {{
    var $ = function (id) {{ return document.getElementById(id); }};
    var state = JSON.parse($('ci-data').textContent);
    function drawStats() {{
      var box = $('ci-stats'); box.textContent = '';
      (state.stats || []).forEach(function (r) {{
        var row = document.createElement('div'); row.className = 'ci-stat';
        var a = document.createElement('span'); a.textContent = r.name + (r.when ? ' · ' + r.when : '');
        var b = document.createElement('span'); b.textContent = r.used + ' of ' + r.total + ' checked in';
        row.appendChild(a); row.appendChild(b); box.appendChild(row);
      }});
    }}
    drawStats();

    var busy = false, lastCode = '', lastAt = 0;
    function show(cls, big, lines, undoId) {{
      var el = $('ci-res'); el.className = 'ci-res ' + cls; el.textContent = '';
      var b = document.createElement('div'); b.className = 'ci-big'; b.textContent = big; el.appendChild(b);
      (lines || []).forEach(function (t) {{ if (!t) return; var d = document.createElement('div'); d.className = 'ci-line'; d.textContent = t; el.appendChild(d); }});
      if (undoId) {{
        var u = document.createElement('button'); u.type = 'button'; u.className = 'ci-undo'; u.textContent = 'Undo (checked in by mistake)';
        u.onclick = function () {{
          u.disabled = true;
          post('/admin/checkin/undo', {{ credential_id: undoId }}).then(function (d) {{
            if (d.stats) {{ state.stats = d.stats; drawStats(); }}
            show('peek', 'Undone', ['The ticket works again.']);
          }});
        }};
        el.appendChild(u);
      }}
      try {{ if (navigator.vibrate) navigator.vibrate(cls === 'ok' ? 60 : [60, 40, 60]); }} catch (e) {{}}
    }}
    function post(url, body) {{
      return fetch(url, {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify(body) }})
        .then(function (r) {{ return r.json(); }});
    }}
    function check(code) {{
      code = String(code || '').trim();
      if (!code || busy) return;
      busy = true; $('ci-go').disabled = true;
      post('/admin/checkin/scan', {{ code: code, mark: !$('ci-peek').checked }}).then(function (d) {{
        busy = false; $('ci-go').disabled = false;
        if (d.stats) {{ state.stats = d.stats; drawStats(); }}
        var t = d.ticket || {{}};
        var who = [t.name, t.event, t.when, t.note].filter(Boolean);
        if (d.state === 'ok') show('ok', '\\u2713 Let in', who, d.marked ? t.credential_id : null);
        else if (d.state === 'valid') show('peek', 'Valid ticket', who.concat(['Not marked as used.']));
        else show('bad', d.title || 'Not valid', [d.error].concat(who));
        $('ci-code').value = '';
      }}).catch(function () {{ busy = false; $('ci-go').disabled = false; show('bad', 'No connection', ['Could not reach the server. Try again.']); }});
    }}
    $('ci-form').addEventListener('submit', function (e) {{ e.preventDefault(); check($('ci-code').value); }});

    // Camera: the phone's built-in QR reader where it has one, else the same reader the widget uses.
    var stream = null, scanning = false;
    function stopCam() {{ scanning = false; if (stream) stream.getTracks().forEach(function (t) {{ t.stop(); }}); stream = null; $('ci-cam').style.display = 'none'; $('ci-cam-btn').textContent = 'Scan with the camera'; }}
    function loadScript(src) {{ return new Promise(function (ok, no) {{ var s = document.createElement('script'); s.src = src; s.onload = ok; s.onerror = no; document.head.appendChild(s); }}); }}
    $('ci-cam-btn').addEventListener('click', async function () {{
      if (stream) {{ stopCam(); return; }}
      var msg = $('ci-cam-msg');
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {{ $('ci-cam').style.display = 'block'; msg.textContent = 'This browser cannot use the camera here. Paste the ticket link instead.'; return; }}
      try {{
        stream = await navigator.mediaDevices.getUserMedia({{ video: {{ facingMode: 'environment' }}, audio: false }});
      }} catch (e) {{ $('ci-cam').style.display = 'block'; msg.textContent = 'The camera is not allowed. Allow it for this site, or paste the ticket link instead.'; return; }}
      var v = $('ci-video'); v.srcObject = stream; await v.play().catch(function () {{}});
      $('ci-cam').style.display = 'block'; $('ci-cam-btn').textContent = 'Stop the camera'; msg.textContent = 'Point the camera at the ticket\\u2019s QR code.';
      var det = null;
      if ('BarcodeDetector' in window) {{ try {{ det = new BarcodeDetector({{ formats: ['qr_code'] }}); }} catch (e) {{}} }}
      if (!det && !window.jsQR) {{ try {{ await loadScript('https://cdnjs.cloudflare.com/ajax/libs/jsqr/1.4.0/jsQR.js'); }} catch (e) {{ msg.textContent = 'Could not load the QR reader. Paste the ticket link instead.'; }} }}
      var cv = document.createElement('canvas'), cx = cv.getContext('2d', {{ willReadFrequently: true }});
      scanning = true;
      (async function tick() {{
        if (!scanning) return;
        var text = '';
        try {{
          if (det) {{ var codes = await det.detect(v); if (codes && codes[0]) text = codes[0].rawValue || ''; }}
          else if (window.jsQR && v.videoWidth) {{
            cv.width = v.videoWidth; cv.height = v.videoHeight; cx.drawImage(v, 0, 0);
            var im = cx.getImageData(0, 0, cv.width, cv.height), r = window.jsQR(im.data, im.width, im.height);
            if (r) text = r.data || '';
          }}
        }} catch (e) {{}}
        var now = Date.now();
        if (text && !busy && (text !== lastCode || now - lastAt > 4000)) {{ lastCode = text; lastAt = now; check(text); }}
        setTimeout(tick, 250);
      }})();
    }});
    window.addEventListener('pagehide', stopCam);
  }})();
  </script>
  {theme_js}
</body></html>"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
