/**
 * Credential Protocol Widget — cp.js
 * Drop two lines on any site. Everything else is handled.
 *
 * Usage (the two lines — your dashboard's "Embed on your website" box
 * shows them with your real address filled in, ready to copy):
 *
 * <div id="credential-widget"></div>
 * <script src="https://your-api.com/cp.js"></script>
 *
 * The widget finds its server automatically from the address cp.js was
 * loaded from. `data-api="https://..."` on the script tag is an optional
 * override, only needed if cp.js is served from somewhere other than the
 * API itself (a CDN or a copy hosted on your own site, say).
 */

(async function() {
  // Must be captured synchronously, before anything is awaited —
  // document.currentScript is null once this function has yielded.
  const script = document.currentScript

  // Where's the API? An explicit data-api wins; otherwise it's wherever
  // this very script was loaded from (cp.js is served by the API itself,
  // so that's the right answer on a normal install); otherwise the old
  // local-development default.
  const API_BASE = (function() {
    const explicit = script && script.getAttribute('data-api')
    if (explicit) return explicit.replace(/\/+$/, '')
    if (script && script.src) {
      try { return new URL(script.src, window.location.href).origin } catch (e) {}
    }
    return 'http://localhost:5001'
  })()

  // The script tag is often placed before the div it fills (or in <head>),
  // in which case the div doesn't exist yet when this first runs — wait
  // for the page to finish parsing rather than silently finding nothing.
  if (document.readyState === 'loading') {
    await new Promise(resolve => document.addEventListener('DOMContentLoaded', resolve))
  }

  // `crith-access` is accepted too: it was this widget's original id, and
  // sites embedded back then keep working. It's renamed so the widget's
  // styles (scoped to #credential-widget) apply to it.
  const container = document.getElementById('credential-widget') ||
                    document.getElementById('crith-access')
  if (!container) {
    // Never fail silently — a missing div used to just produce a blank
    // page with nothing to say why.
    console.error('Credential widget: no <div id="credential-widget"></div> found on this page, so there is nowhere to draw the widget. Add that line where you want it to appear.')
    if (script && script.parentNode) {
      const note = document.createElement('p')
      note.style.cssText = 'color:#888;font-family:monospace;font-size:11px;'
      note.textContent = 'Credential widget: add <div id="credential-widget"></div> where this should appear.'
      script.parentNode.insertBefore(note, script)
    }
    return
  }
  if (container.id !== 'credential-widget') container.id = 'credential-widget'

  // ── Text and link safety ──
  // Anything that comes from the server (names typed into the signup form,
  // titles and links the creator entered) is escaped before it goes into
  // HTML, and links are only ever http(s), mailto or relative.
  function esc(v) {
    return String(v == null ? '' : v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;')
  }
  function safeUrl(u) {
    u = String(u == null ? '' : u).trim()
    if (u === '#' || (u.charAt(0) === '/' && u.charAt(1) !== '/')) return u
    return /^(https?:\/\/|mailto:)/i.test(u) ? u : ''
  }

  function fmtSize(n) {
    n = Number(n) || 0
    if (n >= 1073741824) return (n / 1073741824).toFixed(1) + ' GB'
    if (n >= 1048576) return (n / 1048576).toFixed(1) + ' MB'
    if (n >= 1024) return Math.round(n / 1024) + ' KB'
    return n ? n + ' B' : ''
  }

  // ── Load config ──
  // Members-only content is NOT loaded here. It is requested only after a
  // member has proved they hold a valid credential (see loadMemberContent).
  let config  = {}

  try {
    config = await fetch(`${API_BASE}/config`).then(r => r.json())
  } catch(e) {
    container.innerHTML = '<p style="color:#888;font-family:monospace;font-size:11px;">Credential widget: could not reach API.</p>'
    return
  }

  // The dashboard's "Widget look" preview loads this same file with a few
  // look settings swapped in, before they are saved. Only look settings are
  // taken (never tiers or anything else).
  if (window.__cpOverride && typeof window.__cpOverride === 'object') {
    Object.keys(window.__cpOverride).forEach(k => {
      if (k === 'accent_color' || /^widget_[a-z_]+$/.test(k)) config[k] = window.__cpOverride[k]
    })
  }

  // Accent: a #rgb or #rrggbb color; anything else falls back to green.
  const accent = (function() {
    let a = String(config.accent_color || '').trim()
    if (/^#[0-9a-f]{3}$/i.test(a)) a = '#' + a.slice(1).split('').map(c => c + c).join('')
    return /^#[0-9a-f]{6}$/i.test(a) ? a.toLowerCase() : '#00e87a'
  })()

  // ── The look (set in the dashboard under "Widget look") ──
  const pick = (v, allowed, dflt) => allowed.indexOf(v) >= 0 ? v : dflt
  const text = (v, dflt, max) => { v = String(v == null ? '' : v).trim().slice(0, max); return v || dflt }
  const look = {
    theme:   pick(config.widget_theme,   ['match', 'dark', 'light', 'custom'], 'match'),
    font:    pick(config.widget_font,    ['page', 'keycard'], 'page'),
    corners: pick(config.widget_corners, ['square', 'rounded'], 'square'),
    bg:      /^#[0-9a-f]{6}$/i.test(String(config.widget_bg   || '').trim()) ? config.widget_bg.trim()   : '#121214',
    fg:      /^#[0-9a-f]{6}$/i.test(String(config.widget_text || '').trim()) ? config.widget_text.trim() : '#ecebe8',
  }
  const T = {
    banner:    text(config.widget_banner_text,   'Get your card \u2014 click here', 80),
    dropTitle: text(config.widget_drop_title,    'Insert card here', 60),
    dropSub:   text(config.widget_drop_sub,      'drop your card file \u00b7 or click to browse', 100),
    signupT:   text(config.widget_signup_title,  'Get your card', 60),
    signupSub: text(config.widget_signup_sub,    'Pick a tier, enter your name and email.\nYour card arrives instantly.', 200),
    send:      text(config.widget_button_text,   'Send my card', 40),
  }
  const name    = config.creator_name || 'Creator'
  const tiers   = (config.tiers && config.tiers.length) ? config.tiers : [{ name: 'MEMBER', label: 'Free', price: 0 }]
  // A tier with a member limit that is full comes with sold_out: true; start on
  // the first one that still has room.
  let selectedTier = tiers.find(t => !t.sold_out) || tiers[0]

  // ── Inject base styles ──
  const style = document.createElement('style')
  style.textContent = `
    #credential-widget * { box-sizing: border-box; }
    #credential-widget {
      --ca-bg:       #121214;
      --ca-fg:       #ecebe8;
      --ca-panel:    #1b1b1e;
      --ca-panel-2:  #232327;
      --ca-ash:      #a09d98;
      --ca-line:     #3a3a3f;
      --ca-accent-text: ${accent};
      --ca-on-accent: #0a0908;
      --ca-bad:      #ff6b6b;
      --ca-overlay:  rgba(18,18,20,.92);
      --ca-radius:   0px;
      --ca-font:         'JetBrains Mono', monospace;
      --ca-font-display: 'Bebas Neue', sans-serif;
      font-family: var(--ca-font);
      color: var(--ca-fg);
    }
    .ca-display {
      font-family: var(--ca-font-display);
      letter-spacing: 0.04em;
    }
    .ca-banner {
      background: ${accent}22;
      border: 1px solid ${accent}44;
      padding: 12px 20px;
      text-align: center;
      cursor: pointer;
      margin-bottom: 32px;
      transition: background .2s;
    }
    .ca-banner:hover { background: ${accent}33; }
    .ca-banner-text {
      font-size: 11px;
      letter-spacing: 3px;
      text-transform: uppercase;
      color: var(--ca-accent-text);
    }
    .ca-drop-zone {
      border: 1px dashed var(--ca-line);
      padding: 48px 24px;
      text-align: center;
      cursor: pointer;
      transition: all .2s;
      margin-bottom: 12px;
    }
    .ca-drop-zone:hover,
    .ca-drop-zone.drag-over {
      border-color: ${accent};
      background: ${accent}08;
    }
    .ca-drop-title {
      font-family: var(--ca-font-display);
      font-size: 26px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--ca-fg);
      margin-bottom: 6px;
    }
    .ca-drop-sub {
      font-size: 9px;
      letter-spacing: 2px;
      text-transform: uppercase;
      color: var(--ca-ash);
    }
    .ca-token-row {
      display: flex;
      gap: 0;
      margin-bottom: 32px;
    }
    .ca-token-input {
      flex: 1;
      background: transparent;
      border: 1px solid var(--ca-line);
      border-right: none;
      color: inherit;
      font-family: var(--ca-font);
      font-size: 9px;
      letter-spacing: 1px;
      padding: 11px 14px;
      outline: none;
      text-transform: uppercase;
    }
    .ca-token-input:focus { border-color: ${accent}; }
    .ca-token-btn {
      background: ${accent};
      border: none;
      color: var(--ca-on-accent);
      font-family: var(--ca-font);
      font-size: 9px;
      letter-spacing: 2px;
      text-transform: uppercase;
      padding: 11px 18px;
      cursor: pointer;
    }
    .ca-scan-row {
      text-align: center;
      margin: -4px 0 20px;
    }
    .ca-scan-link {
      background: none;
      border: none;
      color: var(--ca-ash);
      font-family: var(--ca-font);
      font-size: 9px;
      letter-spacing: 2px;
      text-transform: uppercase;
      text-decoration: underline;
      cursor: pointer;
      padding: 4px;
    }
    .ca-scan-link:hover { color: var(--ca-accent-text); }
    .ca-qr-modal .ca-modal { max-width: 360px; }
    .ca-qr-video-wrap {
      position: relative;
      width: 100%;
      aspect-ratio: 1 / 1;
      background: #000;
      overflow: hidden;
      margin-bottom: 16px;
    }
    .ca-qr-video-wrap video {
      width: 100%; height: 100%;
      object-fit: cover;
    }
    .ca-qr-frame {
      position: absolute;
      inset: 14%;
      border: 2px solid ${accent};
      opacity: .8;
      pointer-events: none;
    }
    .ca-qr-status {
      font-size: 9px;
      letter-spacing: 1px;
      text-transform: uppercase;
      color: var(--ca-ash);
      text-align: center;
      margin-bottom: 14px;
      min-height: 12px;
    }
    .ca-result {
      padding: 14px 18px;
      font-size: 10px;
      letter-spacing: 1px;
      margin-bottom: 20px;
      display: none;
    }
    .ca-result.valid   { border-left: 3px solid ${accent}; color: var(--ca-accent-text); }
    .ca-result.invalid { border-left: 3px solid var(--ca-bad);   color: var(--ca-bad); }
    .ca-result.checking { border-left: 3px solid var(--ca-ash); color: var(--ca-ash); }
    .ca-member-area { display: none; }
    .ca-member-header {
      position: relative;
      padding: 18px 20px 16px;
      margin-bottom: 1px;
      background: var(--ca-panel);
      border: 1px solid var(--ca-line);
      border-bottom: none;
      overflow: hidden;
    }
    .ca-member-header::before {
      content: "";
      position: absolute;
      inset: 0;
      opacity: 0.12;
      mix-blend-mode: overlay;
      pointer-events: none;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
    }
    .ca-member-name {
      position: relative;
      font-family: var(--ca-font-display);
      font-size: 20px;
      letter-spacing: 0.04em;
      color: var(--ca-fg);
      line-height: 1.2;
    }
    .ca-member-tier {
      position: relative;
      font-size: 9px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--ca-accent-text);
      margin-top: 2px;
    }
    .ca-member-hr {
      position: relative;
      height: 1px;
      background: var(--ca-line);
      margin: 12px 0 10px;
    }
    .ca-member-meta {
      position: relative;
      font-size: 8.5px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--ca-ash);
      line-height: 1.9;
    }
    .ca-member-meta b { color: var(--ca-ash); font-weight: 400; }
    .ca-member-meta span { color: var(--ca-fg); }
    .ca-tabs {
      display: flex;
      gap: 1px;
      background: var(--ca-line);
      margin-bottom: 1px;
    }
    .ca-tab {
      flex: 1;
      background: var(--ca-panel);
      border: none;
      color: var(--ca-ash);
      font-family: var(--ca-font);
      font-size: 9px;
      letter-spacing: 2px;
      text-transform: uppercase;
      padding: 11px;
      cursor: pointer;
      transition: all .15s;
    }
    .ca-tab:hover { color: var(--ca-fg); background: var(--ca-panel-2); }
    .ca-tab.active { background: ${accent}; color: var(--ca-on-accent); }
    .ca-panel {
      position: relative;
      display: none;
      background: var(--ca-panel);
      border: 1px solid var(--ca-line);
      border-top: none;
      padding: 28px;
      min-height: 240px;
      overflow: hidden;
    }
    .ca-panel::before {
      content: "";
      position: absolute;
      inset: 0;
      opacity: 0.07;
      mix-blend-mode: overlay;
      pointer-events: none;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
    }
    .ca-panel.active { display: block; }
    .ca-panel-title {
      position: relative;
      font-family: var(--ca-font-display);
      font-size: 16px;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      color: var(--ca-accent-text);
      margin-bottom: 20px;
    }
    .ca-track {
      position: relative;
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 0;
      border-bottom: 1px solid var(--ca-line);
      gap: 12px;
    }
    .ca-track-main { display: flex; align-items: center; gap: 12px; min-width: 0; }
    .ca-thumb { width: 56px; height: 56px; flex: 0 0 56px; object-fit: cover; display: block;
                border: 1px solid var(--ca-line); background: var(--ca-line); }
    .ca-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 12px; margin-top: 6px; }
    .ca-card { display: flex; flex-direction: column; gap: 8px; border: 1px solid var(--ca-line); padding: 8px; min-width: 0; }
    .ca-card .ca-thumb { width: 100%; height: auto; aspect-ratio: 1 / 1; flex: none; border: 0; }
    .ca-card .ca-dl-btn { text-align: center; }
    .ca-track-title { font-size: 11px; margin-bottom: 3px; color: var(--ca-fg); }
    .ca-track-meta  { font-size: 8px; color: var(--ca-ash); letter-spacing: 1px; }
    .ca-dl-btn {
      font-size: 8px;
      letter-spacing: 2px;
      text-transform: uppercase;
      padding: 7px 14px;
      border: 1px solid ${accent};
      color: var(--ca-accent-text);
      text-decoration: none;
      white-space: nowrap;
      transition: all .15s;
    }
    .ca-dl-btn:hover { background: ${accent}; color: var(--ca-on-accent); }
    .ca-video-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }
    .ca-video-card { cursor: pointer; }
    .ca-video-thumb {
      aspect-ratio: 16/9;
      background: var(--ca-panel-2);
      border: 1px solid var(--ca-line);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 22px;
      color: var(--ca-accent-text);
      margin-bottom: 8px;
    }
    .ca-video-title { font-size: 9px; letter-spacing: 1px; text-transform: uppercase; color: var(--ca-fg); }
    .ca-video-meta  { font-size: 8px; color: var(--ca-ash); margin-top: 3px; }
    .ca-chat-messages {
      height: 240px;
      overflow-y: auto;
      border: 1px solid var(--ca-line);
      padding: 14px;
      margin-bottom: 1px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .ca-msg-author { font-size: 7px; letter-spacing: 2px; color: var(--ca-accent-text); text-transform: uppercase; margin-bottom: 3px; }
    .ca-msg-text   { font-size: 10px; color: var(--ca-ash); line-height: 1.5; }
    .ca-chat-row   { display: flex; }
    .ca-chat-input {
      flex: 1;
      background: transparent;
      border: 1px solid var(--ca-line);
      border-right: none;
      color: inherit;
      font-family: var(--ca-font);
      font-size: 9px;
      padding: 11px 14px;
      outline: none;
    }
    .ca-chat-send {
      background: ${accent};
      border: none;
      color: var(--ca-on-accent);
      font-family: var(--ca-font);
      font-size: 9px;
      letter-spacing: 2px;
      padding: 11px 16px;
      cursor: pointer;
    }
    .ca-modal-overlay {
      display: none;
      position: fixed; inset: 0;
      background: var(--ca-overlay);
      z-index: 9999;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }
    .ca-modal-overlay.open { display: flex; }
    .ca-modal {
      position: relative;
      background: var(--ca-panel);
      border: 1px solid var(--ca-line);
      max-width: 440px;
      width: 100%;
      padding: 40px;
      overflow: hidden;
    }
    .ca-modal::before {
      content: "";
      position: absolute;
      inset: 0;
      opacity: 0.1;
      mix-blend-mode: overlay;
      pointer-events: none;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
    }
    .ca-modal > * { position: relative; }
    .ca-modal-title {
      font-family: var(--ca-font-display);
      font-size: 30px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--ca-fg);
      margin-bottom: 6px;
    }
    .ca-modal-sub {
      font-size: 9px;
      color: var(--ca-ash);
      letter-spacing: 1px;
      margin-bottom: 28px;
      line-height: 1.8;
      text-transform: uppercase;
    }
    .ca-tier-picker {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-bottom: 16px;
    }
    .ca-tier-option {
      display: flex;
      align-items: center;
      justify-content: space-between;
      border: 1px solid var(--ca-line);
      padding: 10px 14px;
      cursor: pointer;
      font-size: 9px;
      letter-spacing: 1px;
      text-transform: uppercase;
      color: var(--ca-ash);
    }
    .ca-tier-option:hover { border-color: ${accent}88; }
    .ca-tier-option.sold-out { opacity: 0.45; cursor: not-allowed; }
    .ca-tier-option.sold-out:hover { border-color: var(--ca-line); }
    .ca-tier-option.sold-out .ca-tier-name { text-decoration: line-through; }
    .ca-tier-option.selected {
      border-color: ${accent};
      color: var(--ca-accent-text);
      background: ${accent}14;
    }
    .ca-tier-name { font-weight: bold; }
    .ca-tier-price { color: inherit; opacity: 0.8; }
    .ca-field {
      width: 100%;
      background: transparent;
      border: 1px solid var(--ca-line);
      color: inherit;
      font-family: var(--ca-font);
      font-size: 9px;
      letter-spacing: 1px;
      padding: 12px 14px;
      outline: none;
      margin-bottom: 8px;
      text-transform: uppercase;
      display: block;
    }
    .ca-field:focus { border-color: ${accent}; }
    .ca-submit-row { display: flex; gap: 0; margin-top: 8px; }
    .ca-submit {
      flex: 1;
      background: ${accent};
      border: none;
      color: var(--ca-on-accent);
      font-family: var(--ca-font);
      font-size: 10px;
      letter-spacing: 3px;
      text-transform: uppercase;
      padding: 13px;
      cursor: pointer;
    }
    .ca-close {
      background: transparent;
      border: 1px solid var(--ca-line);
      color: var(--ca-ash);
      font-family: var(--ca-font);
      font-size: 10px;
      padding: 13px 18px;
      cursor: pointer;
    }
    .ca-msg-ok  { font-size: 9px; color: var(--ca-accent-text); letter-spacing: 1px; margin-top: 12px; display: none; line-height: 1.8; }
    .ca-msg-err { font-size: 9px; color: var(--ca-bad); letter-spacing: 1px; margin-top: 8px; display: none; }
    @media (max-width: 600px) {
      .ca-video-grid { grid-template-columns: 1fr; }
    }

    /* ── Look: surface, corners, typography ── */
    #credential-widget.ca-keycard .ca-banner-text { text-shadow: 0 0 12px ${accent}55; }
    #credential-widget.ca-solid { background: var(--ca-bg); padding: 24px; border-radius: var(--ca-radius); }
    #credential-widget .ca-banner, #credential-widget .ca-drop-zone, #credential-widget .ca-modal,
    #credential-widget .ca-field, #credential-widget .ca-tier-option, #credential-widget .ca-dl-btn, #credential-widget .ca-thumb, #credential-widget .ca-card,
    #credential-widget .ca-chat-messages, #credential-widget .ca-result, #credential-widget .ca-video-thumb,
    #credential-widget .ca-qr-video-wrap, #credential-widget .ca-submit, #credential-widget .ca-close { border-radius: var(--ca-radius); }
    #credential-widget .ca-token-input, #credential-widget .ca-chat-input { border-radius: var(--ca-radius) 0 0 var(--ca-radius); }
    #credential-widget .ca-token-btn, #credential-widget .ca-chat-send { border-radius: 0 var(--ca-radius) var(--ca-radius) 0; }
    #credential-widget .ca-member-header, #credential-widget .ca-tabs { border-radius: var(--ca-radius) var(--ca-radius) 0 0; overflow: hidden; }
    #credential-widget .ca-panel { border-radius: 0 0 var(--ca-radius) var(--ca-radius); }
    #credential-widget .ca-submit-row .ca-submit { border-radius: var(--ca-radius) 0 0 var(--ca-radius); }
    #credential-widget .ca-submit-row .ca-close { border-radius: 0 var(--ca-radius) var(--ca-radius) 0; }
    #credential-widget .ca-submit-row .ca-close:only-child { border-radius: var(--ca-radius); }
    #credential-widget.ca-clean, #credential-widget.ca-clean * { font-family: inherit; }
    #credential-widget.ca-clean .ca-member-header::before,
    #credential-widget.ca-clean .ca-panel::before,
    #credential-widget.ca-clean .ca-modal::before { display: none; }
    #credential-widget.ca-clean .ca-banner-text { font-size: 14px; letter-spacing: .02em; text-transform: none; }
    #credential-widget.ca-clean .ca-drop-title { font-size: 20px; font-weight: 600; letter-spacing: 0; text-transform: none; }
    #credential-widget.ca-clean .ca-drop-sub { font-size: 12px; letter-spacing: 0; text-transform: none; }
    #credential-widget.ca-clean .ca-token-input { font-size: 13px; letter-spacing: 0; text-transform: none; padding: 12px 14px; }
    #credential-widget.ca-clean .ca-token-btn { font-size: 12px; font-weight: 600; letter-spacing: .04em; text-transform: none; }
    #credential-widget.ca-clean .ca-scan-link { font-size: 12px; letter-spacing: 0; text-transform: none; }
    #credential-widget.ca-clean .ca-qr-status { font-size: 12px; letter-spacing: 0; text-transform: none; }
    #credential-widget.ca-clean .ca-result { font-size: 13px; letter-spacing: 0; }
    #credential-widget.ca-clean .ca-member-name { font-size: 20px; font-weight: 600; letter-spacing: 0; }
    #credential-widget.ca-clean .ca-member-tier { font-size: 12px; letter-spacing: .04em; }
    #credential-widget.ca-clean .ca-member-meta { font-size: 12px; letter-spacing: 0; text-transform: none; }
    #credential-widget.ca-clean .ca-tab { font-size: 12px; font-weight: 600; letter-spacing: .04em; text-transform: none; }
    #credential-widget.ca-clean .ca-panel-title { font-size: 16px; font-weight: 600; letter-spacing: 0; text-transform: none; }
    #credential-widget.ca-clean .ca-track-title { font-size: 14px; }
    #credential-widget.ca-clean .ca-track-meta { font-size: 12px; letter-spacing: 0; }
    #credential-widget.ca-clean .ca-dl-btn { font-size: 12px; font-weight: 600; letter-spacing: .02em; text-transform: none; }
    #credential-widget.ca-clean .ca-video-title { font-size: 13px; letter-spacing: 0; text-transform: none; }
    #credential-widget.ca-clean .ca-video-meta { font-size: 12px; }
    #credential-widget.ca-clean .ca-msg-author { font-size: 11px; letter-spacing: .04em; }
    #credential-widget.ca-clean .ca-msg-text { font-size: 13px; }
    #credential-widget.ca-clean .ca-chat-input { font-size: 13px; }
    #credential-widget.ca-clean .ca-chat-send { font-size: 12px; letter-spacing: .04em; }
    #credential-widget.ca-clean .ca-modal-title { font-size: 26px; font-weight: 600; letter-spacing: 0; text-transform: none; }
    #credential-widget.ca-clean .ca-modal-sub { font-size: 13px; letter-spacing: 0; text-transform: none; line-height: 1.6; }
    #credential-widget.ca-clean .ca-tier-option { font-size: 13px; letter-spacing: 0; text-transform: none; }
    #credential-widget.ca-clean .ca-field { font-size: 14px; letter-spacing: 0; text-transform: none; }
    #credential-widget.ca-clean .ca-submit { font-size: 13px; font-weight: 600; letter-spacing: .04em; text-transform: none; }
    #credential-widget.ca-clean .ca-close { font-size: 13px; }
    #credential-widget.ca-clean .ca-msg-ok, #credential-widget.ca-clean .ca-msg-err { font-size: 12px; letter-spacing: 0; }
  `
  document.head.appendChild(style)

  // ── Look engine: works out the colors and applies the look ──
  // "match" (default) reads the page the widget sits on: its background,
  // its text color and its font, and builds the widget's panels, borders and
  // pop-up from those, so it fits dark pages, light pages and everything in
  // between. "dark", "light" and "custom" bring their own background instead.
  let _cx = null
  // Any CSS color -> {r,g,b,a}. Plain rgb()/rgba() (what browsers report for
  // almost everything) is read directly; anything newer (oklch, color(), ...)
  // is converted by the browser itself through a one-pixel canvas.
  function toRGBA(str) {
    str = String(str == null ? '' : str).trim()
    if (!str) return null
    if (str.toLowerCase() === 'transparent') return { r: 0, g: 0, b: 0, a: 0 }
    const m = str.match(/^rgba?\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/i)
    if (m) {
      let a = m[4] == null ? 1 : (m[4].slice(-1) === '%' ? parseFloat(m[4]) / 100 : parseFloat(m[4]))
      return { r: Math.round(+m[1]), g: Math.round(+m[2]), b: Math.round(+m[3]), a: isNaN(a) ? 1 : a }
    }
    try {
      if (!_cx) {
        const cv = document.createElement('canvas'); cv.width = cv.height = 1
        _cx = cv.getContext('2d', { willReadFrequently: true })
      }
      _cx.clearRect(0, 0, 1, 1); _cx.fillStyle = '#000000'; _cx.fillStyle = str
      _cx.fillRect(0, 0, 1, 1)
      const d = _cx.getImageData(0, 0, 1, 1).data
      return { r: d[0], g: d[1], b: d[2], a: d[3] / 255 }
    } catch (e) { return null }
  }
  const hex = h => { h = h.replace('#', ''); return { r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16), b: parseInt(h.slice(4, 6), 16), a: 1 } }
  const mix = (a, b, t) => ({ r: Math.round(a.r + (b.r - a.r) * t), g: Math.round(a.g + (b.g - a.g) * t), b: Math.round(a.b + (b.b - a.b) * t), a: 1 })
  const rgb = c => `rgb(${c.r}, ${c.g}, ${c.b})`
  function lum(c) {
    const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b)
  }
  function contrast(a, b) { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05) }
  const WHITE = { r: 255, g: 255, b: 255, a: 1 }, BLACK = { r: 10, g: 9, b: 8, a: 1 }
  const DARK_BG = hex('#121214'), DARK_FG = hex('#ecebe8'), LIGHT_BG = hex('#ffffff'), LIGHT_FG = hex('#1b1b1d')

  // What colors is the page actually showing behind the widget?
  function detectPage() {
    const start = container.parentElement || document.body
    let fg = toRGBA(getComputedStyle(start).color) || LIGHT_FG
    let base = null, imageSeen = false
    const layers = []
    for (let n = start; n && n.nodeType === 1; n = n.parentElement) {
      const cs = getComputedStyle(n)
      const c = toRGBA(cs.backgroundColor)
      if (cs.backgroundImage && cs.backgroundImage !== 'none') imageSeen = true
      if (c && c.a >= 0.97) { base = c; break }
      if (c && c.a > 0.04) layers.push(c)
    }
    let bg = base || WHITE
    for (let i = layers.length - 1; i >= 0; i--) {
      const l = layers[i]; bg = { r: Math.round(bg.r * (1 - l.a) + l.r * l.a), g: Math.round(bg.g * (1 - l.a) + l.g * l.a), b: Math.round(bg.b * (1 - l.a) + l.b * l.a), a: 1 }
    }
    // A picture or gradient may sit over that color, or there may be no
    // color at all: when the text and background clash, trust the text
    // (light text means a dark page, and the other way round).
    if (contrast(fg, bg) < 3 || (imageSeen && !base)) {
      bg = lum(fg) > 0.5 ? DARK_BG : LIGHT_BG
    }
    return { bg: { ...bg, a: 1 }, fg: { ...fg, a: 1 } }
  }

  function applyLook() {
    let bg, fg
    if (look.theme === 'dark')        { bg = DARK_BG;  fg = DARK_FG }
    else if (look.theme === 'light')  { bg = LIGHT_BG; fg = LIGHT_FG }
    else if (look.theme === 'custom') { bg = hex(look.bg); fg = hex(look.fg) }
    else { const d = detectPage(); bg = d.bg; fg = d.fg }
    // Text must stay readable whatever was picked or detected.
    if (contrast(fg, bg) < 4.5) {
      // Pick whichever of the two standard text colors reads better on this
      // background (on a mid-grey, dark text beats light text even though
      // the grey is "darker" than half); pure black/white as a last resort.
      const cands = [DARK_FG, LIGHT_FG, WHITE, BLACK].sort((x, y) => contrast(y, bg) - contrast(x, bg))
      fg = cands.find(c => contrast(c, bg) >= 4.5) || cands[0]
    }
    const darkBg = lum(bg) < 0.4
    // Secondary text: a softer shade of the text color that still reads well.
    let ash = mix(bg, fg, 0.62)
    for (let t = 0.62; contrast(ash, bg) < 4.5 && t < 1; t += 0.04) ash = mix(bg, fg, Math.min(1, t))
    // The accent used as text color has to stand out from this background.
    const acc = hex(accent)
    let accText = acc
    for (let i = 0; i < 12 && contrast(accText, bg) < 3; i++) accText = mix(accText, fg, 0.15)
    const onAccent = contrast(acc, BLACK) >= contrast(acc, WHITE) ? '#0a0908' : '#ffffff'
    const bad = darkBg ? '#ff6b6b' : '#c62828'
    const set = (k, v) => container.style.setProperty(k, v)
    set('--ca-bg', rgb(bg)); set('--ca-fg', rgb(fg))
    set('--ca-panel',   rgb(mix(bg, fg, 0.06)))
    set('--ca-panel-2', rgb(mix(bg, fg, 0.10)))
    set('--ca-line',    rgb(mix(bg, fg, 0.22)))
    set('--ca-ash', rgb(ash))
    set('--ca-accent-text', rgb(accText)); set('--ca-on-accent', onAccent); set('--ca-bad', bad)
    set('--ca-overlay', `rgba(${bg.r}, ${bg.g}, ${bg.b}, .92)`)
    set('--ca-radius', look.corners === 'rounded' ? '10px' : '0px')
    container.classList.toggle('ca-solid', look.theme !== 'match')
    container.classList.toggle('ca-clean', look.font === 'page')
    container.classList.toggle('ca-keycard', look.font === 'keycard')
    if (look.font === 'keycard' && !document.getElementById('ca-fonts')) {
      // Same pairing as the card (card_generator.py): Bebas Neue for big
      // moments, JetBrains Mono for the rest. Only loaded for this look.
      const fontLink = document.createElement('link')
      fontLink.id = 'ca-fonts'; fontLink.rel = 'stylesheet'
      fontLink.href = 'https://fonts.googleapis.com/css2?family=Bebas+Neue&family=JetBrains+Mono:wght@400;500;700&display=swap'
      document.head.appendChild(fontLink)
    }
  }
  applyLook()
  if (look.theme === 'match') {
    // Colors can change after load: a late stylesheet, a dark-mode switch on
    // the page, the visitor's own light/dark setting. Look again when they do.
    let timer = null
    const again = () => { clearTimeout(timer); timer = setTimeout(applyLook, 120) }
    window.addEventListener('load', again)
    try {
      const mo = new MutationObserver(again)
      mo.observe(document.documentElement, { attributes: true })
      if (document.body) mo.observe(document.body, { attributes: true })
      if (window.matchMedia) window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', again)
    } catch (e) {}
  }

  // ── Script loader (used for JSZip and jsQR, both lazy) ──
  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement('script')
      s.src = src
      s.onload = resolve
      s.onerror = () => reject(new Error(`Failed to load ${src}`))
      document.head.appendChild(s)
    })
  }

  // JSZip is lazy-loaded inside processFile(), the first time someone
  // actually drops a .zip — see below. It used to load eagerly here,
  // before the widget even rendered, which meant a single blocked or
  // slow request to cdnjs (ad-blocker, firewall, brief CDN hiccup)
  // took down the ENTIRE widget — banner, drop zone, QR button, token
  // input, all of it. QR scanning already lazy-loads its own library
  // this way; bundle verification now matches that pattern.

  // ── State ──
  let memberData = null

  // ── Check URL token on load ──
  const params = new URLSearchParams(window.location.search)
  const urlId  = params.get('id')
  const urlH   = params.get('h')

  // ── Render widget ──
  container.innerHTML = `

    <!-- BANNER -->
    <div class="ca-banner" id="ca-banner">
      <div class="ca-banner-text">${esc(T.banner)}</div>
    </div>

    <!-- DROP ZONE -->
    <div class="ca-drop-zone" id="ca-drop-zone">
      <input type="file" id="ca-file-input" accept=".zip,.html" style="display:none">
      <div class="ca-drop-title">${esc(T.dropTitle)}</div>
      <div class="ca-drop-sub">${esc(T.dropSub)}</div>
    </div>

    <!-- TOKEN INPUT -->
    <div class="ca-token-row">
      <input type="text" class="ca-token-input" id="ca-token-input"
        placeholder="Or paste your access link...">
      <button class="ca-token-btn" id="ca-token-btn">Verify</button>
    </div>

    <!-- SCAN QR -->
    <div class="ca-scan-row">
      <button class="ca-scan-link" id="ca-scan-link">◈ Or scan your card's QR code</button>
    </div>

    <!-- RESULT -->
    <div class="ca-result" id="ca-result"></div>

    <!-- QR SCAN MODAL -->
    <div class="ca-modal-overlay ca-qr-modal" id="ca-qr-modal">
      <div class="ca-modal">
        <div class="ca-modal-title">Scan your card</div>
        <div class="ca-modal-sub">Point your camera at the QR code on your membership card.</div>
        <div class="ca-qr-video-wrap">
          <video id="ca-qr-video" playsinline muted></video>
          <div class="ca-qr-frame"></div>
        </div>
        <div class="ca-qr-status" id="ca-qr-status"></div>
        <canvas id="ca-qr-canvas" style="display:none;"></canvas>
        <div class="ca-submit-row">
          <button class="ca-close" id="ca-qr-cancel" style="flex:1;">Cancel</button>
        </div>
      </div>
    </div>

    <!-- MEMBER AREA -->
    <div class="ca-member-area" id="ca-member-area">
      <div class="ca-member-header" id="ca-member-header"></div>

      <div class="ca-tabs" id="ca-tabs"></div>
      <div id="ca-panels"></div>
    </div>

    <!-- MODAL -->
    <div class="ca-modal-overlay" id="ca-modal">
      <div class="ca-modal">
        <div class="ca-modal-title">${esc(T.signupT)}</div>
        <div class="ca-modal-sub">${esc(T.signupSub).replace(/\n/g, '<br>')}</div>
        <div class="ca-tier-picker" id="ca-tier-picker"></div>
        <input type="text"  class="ca-field" id="ca-signup-name"  placeholder="Your name">
        <input type="email" class="ca-field" id="ca-signup-email" placeholder="Your email">
        <div class="ca-msg-err" id="ca-signup-err"></div>
        <div class="ca-msg-ok"  id="ca-signup-ok"></div>
        <div class="ca-submit-row">
          <button class="ca-submit" id="ca-submit">${esc(T.send)}</button>
          <button class="ca-close"  id="ca-close">✕</button>
        </div>
      </div>
    </div>
  `

  // ── Render tier picker ──
  function renderTierPicker() {
    const el = document.getElementById('ca-tier-picker')
    el.innerHTML = tiers.map((t, i) => `
      <div class="ca-tier-option${t === selectedTier ? ' selected' : ''}${t.sold_out ? ' sold-out' : ''}" data-i="${i}">
        <span class="ca-tier-name">${esc(t.name)}${t.label ? ' — ' + esc(t.label) : ''}</span>
        <span class="ca-tier-price">${t.sold_out ? 'Sold out' : (t.price ? '$' + esc(t.price) + '/mo' : 'Free') + (typeof t.spots_left === 'number' ? ' · ' + esc(Math.max(0, Math.floor(t.spots_left))) + ' left' : '')}</span>
      </div>`).join('')
    el.querySelectorAll('.ca-tier-option').forEach(opt => {
      opt.onclick = () => {
        const t = tiers[Number(opt.dataset.i)]
        if (t.sold_out) return          // full: can't be picked
        selectedTier = t
        // Picking again after a "Pay with ..." button appeared: back to the normal send button.
        const sb = document.getElementById('ca-submit'), ok = document.getElementById('ca-signup-ok')
        if (sb && sb.onclick !== requestCard) { sb.onclick = requestCard; sb.textContent = T.send; sb.disabled = false; if (ok) ok.style.display = 'none' }
        renderTierPicker()
      }
    })
  }
  renderTierPicker()

  // ── Wire up events ──
  document.getElementById('ca-banner').onclick = () =>
    document.getElementById('ca-modal').classList.add('open')

  document.getElementById('ca-close').onclick = () =>
    document.getElementById('ca-modal').classList.remove('open')

  const dropZone = document.getElementById('ca-drop-zone')
  dropZone.onclick = () => document.getElementById('ca-file-input').click()
  dropZone.ondragover = e => { e.preventDefault(); dropZone.classList.add('drag-over') }
  dropZone.ondragleave = () => dropZone.classList.remove('drag-over')
  dropZone.ondrop = e => {
    e.preventDefault()
    dropZone.classList.remove('drag-over')
    const f = e.dataTransfer.files[0]
    if (f) processFile(f)
  }

  document.getElementById('ca-file-input').onchange = e => {
    if (e.target.files[0]) processFile(e.target.files[0])
  }

  document.getElementById('ca-token-btn').onclick = verifyToken
  document.getElementById('ca-token-input').onkeydown = e => {
    if (e.key === 'Enter') verifyToken()
  }

  document.getElementById('ca-submit').onclick = requestCard

  document.getElementById('ca-scan-link').onclick = startQRScan
  document.getElementById('ca-qr-cancel').onclick = stopQRScan

  // ── Auto-verify from URL ──
  if (urlId) {
    showResult('checking', 'Verifying access link...')
    setTimeout(() => verifyWithAPI(urlId, urlH), 400)
  }

  // ── Session check ──
  // A signed-in member stays signed in for the browser session. What's kept
  // is the verify response plus the access code (`_h`) the content request
  // needs. Records from before content was protected have no code: they're
  // dropped, and the member signs in again from their link or card.
  const sessionKey = 'cp_member_' + name
  let stored = null
  try { stored = sessionStorage.getItem(sessionKey) } catch(e) {}   // blocked storage (private mode, sandboxed preview) just means "not signed in"
  if (stored && !urlId) {
    try {
      const d = JSON.parse(stored)
      if (d && d._h && new Date(d.expires_at) > new Date()) {
        grantAccess(d)
      } else {
        try { sessionStorage.removeItem(sessionKey) } catch(e) {}
      }
    } catch(e) { try { sessionStorage.removeItem(sessionKey) } catch(e2) {} }
  }

  // ── FILE PROCESSING ──
  // Two container formats can be dropped/browsed-to here:
  //   .zip  — the full signed bundle (manifest + signature + PDF cert, etc.)
  //   .html — the visual keycard itself, which now carries the same
  //           manifest embedded in a hidden <script> tag, so the pretty
  //           card someone actually keeps IS a working credential, not
  //           just a picture of one.
  // bundle_type + expiry are checked locally first, just for a fast, friendly
  // error message before touching the network — they do NOT grant anything.
  // The actual access decision always goes through verifyWithAPI(), the same
  // live call the access-link and QR paths use, so revocation is respected
  // here too: dropping a card file can no longer let someone in on the
  // strength of the file alone once that credential's been revoked.
  // `proof` is the access code that goes with the file: for a card it's the
  // code in the card's own QR link; for a .zip it's the SHA-256 of the zip
  // itself (which is exactly what the server stored when it issued it).
  // Members-only content is only handed over for id + code together.
  function applyManifest(manifest, proof) {
    if (manifest.bundle_type !== 'credential') {
      showResult('invalid', '✗ This is not a member credential.')
      return
    }
    if (!manifest.credential_id) {
      showResult('invalid', '✗ Could not read a credential ID from this file.')
      return
    }
    const expiry = new Date(manifest.expires_at)
    if (isNaN(expiry.getTime()) || expiry < new Date()) {
      showResult('invalid', '✗ Credential has expired.')
      return
    }
    verifyWithAPI(manifest.credential_id, proof || null)
  }

  async function sha256Hex(buffer) {
    if (!(window.crypto && window.crypto.subtle)) throw new Error('no-crypto')
    const digest = await window.crypto.subtle.digest('SHA-256', buffer)
    return Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, '0')).join('')
  }

  async function processFile(file) {
    showResult('checking', 'Reading credential...')
    try {
      if (file.name.endsWith('.zip')) {
        if (!window.JSZip) {
          try {
            await loadScript('https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js')
          } catch(e) {
            showResult('invalid', '✗ Could not load the file reader. Try the QR scan or your access link instead.')
            return
          }
        }
        const buf = await file.arrayBuffer()
        const zip = await JSZip.loadAsync(buf)
        if (!zip.file('manifest.json')) {
          showResult('invalid', '✗ Not a valid credential bundle.')
          return
        }
        const manifest = JSON.parse(await zip.file('manifest.json').async('string'))
        let proof = null
        try {
          proof = await sha256Hex(buf)
        } catch(e) {
          showResult('invalid', '✗ This browser can\'t read the bundle securely here. Use your access link or card file instead.')
          return
        }
        applyManifest(manifest, proof)
      } else if (file.name.endsWith('.html') || file.name.endsWith('.htm')) {
        const text = await file.text()
        const match = text.match(/<script[^>]+id=["']cp-manifest["'][^>]*>([\s\S]*?)<\/script>/i)
        if (!match) {
          showResult('invalid', '✗ This card doesn\'t have a credential embedded in it.')
          return
        }
        let manifest
        try {
          manifest = JSON.parse(match[1])
        } catch(e) {
          showResult('invalid', '✗ Could not read the credential in this card.')
          return
        }
        // The card's QR link (?id=…&h=…) carries the access code.
        let proof = null
        try {
          const doc  = new DOMParser().parseFromString(text, 'text/html')
          const link = doc.querySelector('a.card-qr-link')
          const parsed = link ? parseToken(link.getAttribute('href')) : null
          if (parsed && parsed.hash && parsed.id === manifest.credential_id) proof = parsed.hash
        } catch(e) {}
        if (!proof) {
          showResult('invalid', '✗ This card has no access code in it. Use the access link from your email instead.')
          return
        }
        applyManifest(manifest, proof)
      } else {
        showResult('invalid', '✗ Drop your card file — a .zip bundle or the card .html.')
      }
    } catch(e) {
      showResult('invalid', `✗ Error: ${e.message}`)
    }
  }

  // ── PARSE A CREDENTIAL TOKEN ──
  // Accepts: a card's access-link URL (?id=...&h=...) — what new QR codes
  // encode, so a plain phone camera can tap-to-open it directly — plus two
  // legacy shapes still carried by cards issued before this: raw QR JSON
  // ({"id":...,"h":...}) and "id:hash".
  function parseToken(raw) {
    const token = (raw || '').trim()
    if (!token) return null
    if (/^https?:\/\//i.test(token)) {
      try {
        const u  = new URL(token)
        const id = u.searchParams.get('id')
        const h  = u.searchParams.get('h')
        if (id) return { id, hash: h || null }
      } catch(e) { /* fall through */ }
    }
    if (token.startsWith('{')) {
      try {
        const obj = JSON.parse(token)
        if (obj.id) return { id: obj.id, hash: obj.h || null }
      } catch(e) { /* fall through */ }
    }
    const parts = token.split(':')
    return { id: parts[0], hash: parts[1] || null }
  }

  // ── TOKEN VERIFY ──
  function verifyToken() {
    const parsed = parseToken(document.getElementById('ca-token-input').value)
    if (!parsed) return
    verifyWithAPI(parsed.id, parsed.hash)
  }

  // ── QR SCAN ──
  let qrStream = null
  let qrScanning = false

  async function startQRScan() {
    const modal  = document.getElementById('ca-qr-modal')
    const video  = document.getElementById('ca-qr-video')
    const status = document.getElementById('ca-qr-status')

    modal.classList.add('open')
    status.textContent = 'Starting camera...'

    try {
      if (!window.jsQR) {
        await loadScript('https://cdnjs.cloudflare.com/ajax/libs/jsqr/1.4.0/jsQR.js')
      }
    } catch(e) {
      status.textContent = 'Could not load QR scanner. Try the file drop or link instead.'
      return
    }

    try {
      qrStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' }
      })
      video.srcObject = qrStream
      await video.play()
      status.textContent = 'Point your camera at the QR code...'
      qrScanning = true
      requestAnimationFrame(scanFrame)
    } catch(e) {
      status.textContent = 'Camera access denied or unavailable. Try the file drop or link instead.'
    }
  }

  function stopQRScan() {
    qrScanning = false
    if (qrStream) {
      qrStream.getTracks().forEach(t => t.stop())
      qrStream = null
    }
    document.getElementById('ca-qr-modal').classList.remove('open')
  }

  function scanFrame() {
    if (!qrScanning) return
    const video  = document.getElementById('ca-qr-video')
    const canvas = document.getElementById('ca-qr-canvas')

    if (video.readyState === video.HAVE_ENOUGH_DATA) {
      canvas.width  = video.videoWidth
      canvas.height = video.videoHeight
      const ctx = canvas.getContext('2d')
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
      const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
      const code = window.jsQR(imageData.data, imageData.width, imageData.height)

      if (code && code.data) {
        const parsed = parseToken(code.data)
        if (parsed) {
          document.getElementById('ca-qr-status').textContent = '✔ Code found — verifying...'
          stopQRScan()
          verifyWithAPI(parsed.id, parsed.hash)
          return
        }
      }
    }
    requestAnimationFrame(scanFrame)
  }

  // ── API VERIFY ──
  // `bundle_hash` is the access code from the member's link, card or bundle.
  // Without it we can't prove who's asking, so there's nothing to show them.
  async function verifyWithAPI(credential_id, bundle_hash) {
    if (!bundle_hash) {
      showResult('invalid', '✗ This link or code is incomplete. Use the full access link from your email, or drop your card file.')
      return
    }
    showResult('checking', 'Verifying...')
    try {
      const res = await fetch(`${API_BASE}/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credential_id, bundle_hash }),
      })
      const data = await res.json()
      if (data.valid) {
        data._h = String(bundle_hash).toLowerCase()
        data.credential_id = data.credential_id || credential_id
        try { sessionStorage.setItem(sessionKey, JSON.stringify(data)) } catch(e) {}
        grantAccess(data)
      } else {
        showResult('invalid', `✗ ${data.error || 'Invalid credential.'}`)
      }
    } catch(e) {
      showResult('invalid', '✗ Could not reach verification server. Try again in a moment.')
    }
  }

  // ── MEMBER CONTENT ──
  // Asked for only after the member has proved their credential, and asked
  // again on every visit, so revoking a credential cuts off its content at
  // once. Returns the sections this member's tier includes, or null.
  async function loadMemberContent(data) {
    const res = await fetch(`${API_BASE}/member-content`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ credential_id: data.credential_id, bundle_hash: data._h }),
    })
    if (res.status === 403) return null
    const body = await res.json()
    if (!body || !body.success) return null
    return body.sections || []
  }

  // ── GRANT ACCESS ──
  async function grantAccess(data) {
    memberData = data
    const memberName = data.holder_name || data.name || 'Member'
    const expiry = new Date(data.expires_at).toLocaleDateString('en-GB', {
      day: '2-digit', month: 'short', year: 'numeric'
    })

    showResult('valid', `✔ Welcome, ${memberName}. ${data.tier} access · valid until ${expiry}`)

    document.getElementById('ca-member-header').innerHTML = `
      <div class="ca-member-name">${esc(memberName)}</div>
      <div class="ca-member-tier">${esc(data.tier)}</div>
      <div class="ca-member-hr"></div>
      <div class="ca-member-meta">
        <div><b>ACCESS CLASS</b> // <span>${esc(data.tier)}</span></div>
        <div><b>VALID UNTIL</b> // <span>${esc(expiry)}</span></div>
      </div>`

    const area = document.getElementById('ca-member-area')
    area.style.display = 'block'
    document.getElementById('ca-tabs').innerHTML = ''
    document.getElementById('ca-panels').innerHTML =
      '<div class="ca-panel active"><p style="color:#6b6058;font-size:10px;position:relative;">Loading your content…</p></div>'

    let sections = null
    let unreachable = false
    try {
      sections = await loadMemberContent(data)
    } catch(e) {
      unreachable = true
    }

    if (unreachable) {
      document.getElementById('ca-panels').innerHTML =
        '<div class="ca-panel active"><p style="color:#cc0000;font-size:10px;position:relative;">Could not load your content right now. Reload the page to try again.</p></div>'
    } else if (sections === null) {
      // The server no longer accepts this credential (revoked, expired, or
      // the code doesn't match) — don't leave a half-signed-in page behind.
      try { sessionStorage.removeItem(sessionKey) } catch(e) {}
      memberData = null
      area.style.display = 'none'
      showResult('invalid', '✗ This access is no longer valid. Contact ' + name + ' if you think that\'s a mistake.')
      return
    } else {
      buildMemberArea(sections)
    }

    area.scrollIntoView && area.scrollIntoView({ behavior: 'smooth' })
    window.history.replaceState({}, '', window.location.pathname)
  }

  // ── BUILD MEMBER AREA ──
  // `sections` is exactly what the server returned for this member:
  // [{ key, title, type: 'links' | 'merch' | 'chat', … }]
  function buildMemberArea(sections) {
    const tabsEl   = document.getElementById('ca-tabs')
    const panelsEl = document.getElementById('ca-panels')
    tabsEl.innerHTML   = ''
    panelsEl.innerHTML = ''

    // Nothing to show for an empty links list or a blank merch entry.
    const shown = (sections || []).filter(sec => {
      if (sec.type === 'links') return sec.items && sec.items.length
      if (sec.type === 'merch') return sec.label || sec.code || sec.url
      return sec.type === 'chat'
    })

    if (!shown.length) {
      panelsEl.innerHTML = '<div class="ca-panel active"><p style="color:#6b6058;font-size:10px;position:relative;">No content available yet.</p></div>'
      return
    }

    shown.forEach((sec, i) => {
      const btn = document.createElement('button')
      btn.className = 'ca-tab' + (i === 0 ? ' active' : '')
      btn.textContent = '// ' + String(sec.title || sec.key).toUpperCase()
      btn.onclick = () => switchTab(sec.key, btn)
      tabsEl.appendChild(btn)

      const panel = document.createElement('div')
      panel.className = 'ca-panel' + (i === 0 ? ' active' : '')
      panel.id = 'ca-panel-' + sec.key
      panel.innerHTML = buildPanel(sec)
      panelsEl.appendChild(panel)
    })

    if (shown.some(s => s.type === 'chat')) {
      const sendBtn   = document.getElementById('ca-chat-send')
      const chatInput = document.getElementById('ca-chat-input')
      if (sendBtn)   sendBtn.onclick = sendChat
      if (chatInput) chatInput.onkeydown = e => { if (e.key === 'Enter') sendChat() }
    }
  }

  function switchTab(key, btn) {
    document.querySelectorAll('.ca-tab').forEach(b => b.classList.remove('active'))
    document.querySelectorAll('.ca-panel').forEach(p => p.classList.remove('active'))
    btn.classList.add('active')
    document.getElementById('ca-panel-' + key).classList.add('active')
  }

  function buildPanel(sec) {
    const title = `<div class="ca-panel-title">${esc(sec.title || sec.key)}</div>`

    if (sec.type === 'links') {
      const grid = sec.layout === 'grid'
      const items = (sec.items || []).map(it => {
        // An uploaded file arrives as a short-lived download path on the API
        // (/member-file/…); anything else is a plain link the creator added.
        const isFile = typeof it.download === 'string' &&
                       /^\/member-file\/[a-f0-9]{24}\?t=[A-Za-z0-9_.=-]+$/.test(it.download)
        const url = isFile ? API_BASE + it.download : safeUrl(it.url)
        const fileInfo = isFile && it.file ? [it.file.name, fmtSize(it.file.size)].filter(Boolean).join(' · ') : ''
        const meta = [it.note, fileInfo].filter(Boolean).join(' · ')
        // For sale: a Buy button (http/https only, opened in a new tab) replaces the download.
        const buyRaw = safeUrl(it.buy_url)
        const buyUrl = /^https?:\/\//i.test(buyRaw) ? buyRaw : ''
        const price = String(it.price || '').slice(0, 30)
        // The preview picture arrives as a short-lived path on the API (/member-preview/…).
        const hasThumb = typeof it.thumb === 'string' &&
                         /^\/member-preview\/[a-f0-9]{24}\?t=[A-Za-z0-9_.=-]+$/.test(it.thumb)
        const thumb = hasThumb ? `<img class="ca-thumb" src="${esc(API_BASE + it.thumb)}" alt="" loading="lazy">` : ''
        const btn = buyUrl
          ? `<a href="${esc(buyUrl)}" class="ca-dl-btn" target="_blank" rel="noopener noreferrer">${esc('Buy' + (price ? ' · ' + price : ''))}</a>`
          : url
            ? (isFile
                ? `<a href="${esc(url)}" class="ca-dl-btn" rel="noopener">${esc(sec.button || '↓ Download')}</a>`
                : `<a href="${esc(url)}" class="ca-dl-btn" target="_blank" rel="noopener">${esc(sec.button || 'Open →')}</a>`)
            : ''
        const text = `<div>
            <div class="ca-track-title">${esc(it.title)}</div>
            <div class="ca-track-meta">${esc(meta)}</div>
          </div>`
        if (grid) {
          return `
        <div class="ca-card">
          ${thumb}
          ${text}
          ${btn}
        </div>`
        }
        return `
        <div class="ca-track">
          <div class="ca-track-main">${thumb}${text}</div>
          ${btn}
        </div>`
      }).join('')
      return title + (grid ? `<div class="ca-grid">${items}</div>` : items)
    }

    if (sec.type === 'merch') {
      const url = safeUrl(sec.url)
      return `${title}
        <div class="ca-track">
          <div>
            <div class="ca-track-title">${esc(sec.label || 'Member Discount')}</div>
            <div class="ca-track-meta">${sec.code ? 'Code: ' + esc(sec.code) : ''}</div>
          </div>
          ${url ? `<a href="${esc(url)}" class="ca-dl-btn" target="_blank" rel="noopener">Shop →</a>` : ''}
        </div>`
    }

    if (sec.type === 'chat') {
      return `${title}
        <div class="ca-chat-messages" id="ca-chat-messages">
          <div>
            <div class="ca-msg-author">${esc(name)} // system</div>
            <div class="ca-msg-text">Welcome. Demo chat — local only for now.</div>
          </div>
        </div>
        <div class="ca-chat-row">
          <input type="text" class="ca-chat-input" id="ca-chat-input" placeholder="Say something...">
          <button class="ca-chat-send" id="ca-chat-send">Send</button>
        </div>`
    }

    return ''
  }

  // ── CHAT ──
  function sendChat() {
    const input = document.getElementById('ca-chat-input')
    const msg   = input.value.trim()
    if (!msg) return
    const memberName = memberData
      ? (memberData.holder_name || memberData.name || 'Member').toUpperCase()
      : 'MEMBER'
    const msgs = document.getElementById('ca-chat-messages')
    const div  = document.createElement('div')
    div.innerHTML = `
      <div class="ca-msg-author">${esc(memberName)}</div>
      <div class="ca-msg-text" style="color:inherit;">${esc(msg)}</div>`
    msgs.appendChild(div)
    msgs.scrollTop = msgs.scrollHeight
    input.value = ''
  }

  // ── REQUEST CARD ──
  async function requestCard() {
    const nameVal  = document.getElementById('ca-signup-name').value.trim()
    const emailVal = document.getElementById('ca-signup-email').value.trim()
    const errEl    = document.getElementById('ca-signup-err')
    const okEl     = document.getElementById('ca-signup-ok')
    const btn      = document.getElementById('ca-submit')

    errEl.style.display = 'none'
    okEl.style.display  = 'none'

    if (selectedTier.sold_out) { errEl.textContent = 'Sorry, that tier is sold out.'; errEl.style.display = 'block'; return }
    if (!nameVal)  { errEl.textContent = 'Enter your name.';  errEl.style.display = 'block'; return }
    if (!emailVal || !emailVal.includes('@')) {
      errEl.textContent = 'Enter a valid email.'
      errEl.style.display = 'block'
      return
    }

    btn.textContent = 'Sending...'
    btn.disabled    = true

    try {
      // /checkout handles every tier, free or paid: a free tier issues
      // instantly (same as /issue used to, just one endpoint now); a
      // paid tier starts whichever payment_provider the dashboard has
      // configured — see the three response shapes handled below.
      const res = await fetch(`${API_BASE}/checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name:  nameVal,
          email: emailVal,
          tier:  selectedTier.name,
        }),
      })
      const data = await res.json()
      if (data.success) {
        if (data.checkout_url) {
          // Stripe (or any future redirect-based provider) — hand the
          // browser off to the hosted checkout page. Nothing is issued
          // yet; that happens once the provider's webhook confirms payment.
          window.location.href = data.checkout_url
          return
        }
        if (data.pending) {
          // Manual-approval provider — a request is now queued for the
          // creator; nothing is issued until they approve it.
          let msg = esc(data.instructions || 'Request received. Your access will be issued once payment is confirmed.').replace(/\n/g, '<br>')
          // "Custom payment link" provider: a pay link comes with the request.
          // Only plain http(s) links are ever opened, and in a new tab.
          const payUrl = (typeof data.pay_url === 'string' && /^https?:\/\//i.test(data.pay_url)) ? data.pay_url : ''
          if (payUrl) {
            if (data.reference) msg += '<br><br>Your reference: <b>' + esc(String(data.reference)) + '</b>'
            msg += '<br><br>Once your payment is received, your card is sent to you.'
          }
          okEl.innerHTML = msg
          okEl.style.display = 'block'
          if (payUrl) {
            btn.textContent = String(data.pay_label || 'Pay now').slice(0, 60)
            btn.disabled    = false
            btn.onclick     = () => { window.open(payUrl, '_blank', 'noopener,noreferrer') }
          } else {
            btn.textContent = 'Request sent'
          }
          return
        }
        if (data.email_sent === false) {
          // The credential was issued, but the email didn't go out (no email
          // service set up yet, or the send failed) — say so rather than
          // promising an email that isn't coming. The creator can copy this
          // member's link from the admin Members page and send it by hand.
          okEl.innerHTML = `✔ Your access has been created, but we couldn't send the email.<br>Please contact ${esc(name)} and they'll send you your access link.`
          okEl.style.display = 'block'
          btn.textContent = '✔ Created'
        } else {
          okEl.innerHTML = `✔ Card sent to ${esc(emailVal)}.<br>Check your inbox — your card and access link are on their way.`
          okEl.style.display = 'block'
          btn.textContent = '✔ Sent'
        }
      } else {
        errEl.textContent = data.error || 'Something went wrong.'
        errEl.style.display = 'block'
        btn.textContent = 'Send my card'
        btn.disabled = false
      }
    } catch(e) {
      errEl.textContent = 'Could not reach server. Try again shortly.'
      errEl.style.display = 'block'
      btn.textContent = 'Send my card'
      btn.disabled = false
    }
  }

  // ── RESULT ──
  function showResult(type, msg) {
    const el = document.getElementById('ca-result')
    el.className = `ca-result ${type}`
    el.textContent = msg
    el.style.display = 'block'
  }

})()