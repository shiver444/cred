/**
 * CrithAccess Widget — cp.js
 * Drop two lines on any site. Everything else is handled.
 *
 * Usage:
 * <script src="https://your-api.com/cp.js" data-api="https://your-api.com"></script>
 * <div id="crith-access"></div>
 */

(async function() {
  const script    = document.currentScript
  const API_BASE  = script.getAttribute('data-api') || 'http://localhost:5001'
  const container = document.getElementById('crith-access')
  if (!container) return

  // ── Load config and content ──
  let config  = {}
  let content = {}

  try {
    const [cr, ct] = await Promise.all([
      fetch(`${API_BASE}/config`).then(r => r.json()),
      fetch(`${API_BASE}/content`).then(r => r.json()),
    ])
    config  = cr
    content = ct
  } catch(e) {
    container.innerHTML = '<p style="color:#888;font-family:monospace;font-size:11px;">CrithAccess: could not reach API.</p>'
    return
  }

  const accent  = config.accent_color || '#00e87a'
  const name    = config.creator_name || 'Creator'
  const tiers   = (config.tiers && config.tiers.length) ? config.tiers : [{ name: 'MEMBER', label: 'Free', price: 0 }]
  let selectedTier = tiers[0]

  // ── Load matching fonts ──
  // Same family pairing as the physical/PDF keycard (card_generator.py):
  // Bebas Neue for the big display moments, JetBrains Mono for everything
  // else. Injected here (not just assumed from the host page) so the
  // widget looks right even on a page that doesn't already load these.
  if (!document.getElementById('ca-fonts')) {
    const fontLink = document.createElement('link')
    fontLink.id  = 'ca-fonts'
    fontLink.rel = 'stylesheet'
    fontLink.href = 'https://fonts.googleapis.com/css2?family=Bebas+Neue&family=JetBrains+Mono:wght@400;500;700&display=swap'
    document.head.appendChild(fontLink)
  }

  // ── Inject base styles ──
  const style = document.createElement('style')
  style.textContent = `
    #crith-access * { box-sizing: border-box; }
    #crith-access {
      --ca-panel:    #1a100e;
      --ca-panel-2:  #241512;
      --ca-bone:     #e6dfd2;
      --ca-ash:      #6b6058;
      --ca-line:     #3a1210;
      --ca-glow:     #e8232b;
      font-family: 'JetBrains Mono', monospace;
      color: var(--ca-bone);
    }
    .ca-display {
      font-family: 'Bebas Neue', sans-serif;
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
      color: ${accent};
      text-shadow: 0 0 12px ${accent}55;
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
      font-family: 'Bebas Neue', sans-serif;
      font-size: 26px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--ca-bone);
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
      font-family: 'JetBrains Mono', monospace;
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
      color: #000;
      font-family: monospace;
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
      font-family: 'JetBrains Mono', monospace;
      font-size: 9px;
      letter-spacing: 2px;
      text-transform: uppercase;
      text-decoration: underline;
      cursor: pointer;
      padding: 4px;
    }
    .ca-scan-link:hover { color: ${accent}; }
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
      color: #888;
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
    .ca-result.valid   { border-left: 3px solid ${accent}; color: ${accent}; }
    .ca-result.invalid { border-left: 3px solid #cc0000;   color: #cc0000; }
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
      font-family: 'Bebas Neue', sans-serif;
      font-size: 20px;
      letter-spacing: 0.04em;
      color: var(--ca-bone);
      line-height: 1.2;
    }
    .ca-member-tier {
      position: relative;
      font-size: 9px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: ${accent};
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
    .ca-member-meta span { color: var(--ca-bone); }
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
      font-family: 'JetBrains Mono', monospace;
      font-size: 9px;
      letter-spacing: 2px;
      text-transform: uppercase;
      padding: 11px;
      cursor: pointer;
      transition: all .15s;
    }
    .ca-tab:hover { color: var(--ca-bone); background: var(--ca-panel-2); }
    .ca-tab.active { background: ${accent}; color: #0a0908; }
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
      font-family: 'Bebas Neue', sans-serif;
      font-size: 16px;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      color: ${accent};
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
    .ca-track-title { font-size: 11px; margin-bottom: 3px; color: var(--ca-bone); }
    .ca-track-meta  { font-size: 8px; color: var(--ca-ash); letter-spacing: 1px; }
    .ca-dl-btn {
      font-size: 8px;
      letter-spacing: 2px;
      text-transform: uppercase;
      padding: 7px 14px;
      border: 1px solid ${accent};
      color: ${accent};
      text-decoration: none;
      white-space: nowrap;
      transition: all .15s;
    }
    .ca-dl-btn:hover { background: ${accent}; color: #000; }
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
      color: ${accent};
      margin-bottom: 8px;
    }
    .ca-video-title { font-size: 9px; letter-spacing: 1px; text-transform: uppercase; color: var(--ca-bone); }
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
    .ca-msg-author { font-size: 7px; letter-spacing: 2px; color: ${accent}; text-transform: uppercase; margin-bottom: 3px; }
    .ca-msg-text   { font-size: 10px; color: var(--ca-ash); line-height: 1.5; }
    .ca-chat-row   { display: flex; }
    .ca-chat-input {
      flex: 1;
      background: transparent;
      border: 1px solid var(--ca-line);
      border-right: none;
      color: inherit;
      font-family: 'JetBrains Mono', monospace;
      font-size: 9px;
      padding: 11px 14px;
      outline: none;
    }
    .ca-chat-send {
      background: ${accent};
      border: none;
      color: #0a0908;
      font-family: 'JetBrains Mono', monospace;
      font-size: 9px;
      letter-spacing: 2px;
      padding: 11px 16px;
      cursor: pointer;
    }
    .ca-modal-overlay {
      display: none;
      position: fixed; inset: 0;
      background: rgba(0,0,0,.9);
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
      font-family: 'Bebas Neue', sans-serif;
      font-size: 30px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--ca-bone);
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
    .ca-tier-option.selected {
      border-color: ${accent};
      color: ${accent};
      background: ${accent}14;
    }
    .ca-tier-name { font-weight: bold; }
    .ca-tier-price { color: inherit; opacity: 0.8; }
    .ca-field {
      width: 100%;
      background: transparent;
      border: 1px solid var(--ca-line);
      color: inherit;
      font-family: 'JetBrains Mono', monospace;
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
      color: #0a0908;
      font-family: 'JetBrains Mono', monospace;
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
      font-family: 'JetBrains Mono', monospace;
      font-size: 10px;
      padding: 13px 18px;
      cursor: pointer;
    }
    .ca-msg-ok  { font-size: 9px; color: ${accent}; letter-spacing: 1px; margin-top: 12px; display: none; line-height: 1.8; }
    .ca-msg-err { font-size: 9px; color: #cc0000; letter-spacing: 1px; margin-top: 8px; display: none; }
    @media (max-width: 600px) {
      .ca-video-grid { grid-template-columns: 1fr; }
    }
  `
  document.head.appendChild(style)

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
      <div class="ca-banner-text">◈ Get your free demo card — click here</div>
    </div>

    <!-- DROP ZONE -->
    <div class="ca-drop-zone" id="ca-drop-zone">
      <input type="file" id="ca-file-input" accept=".zip,.html" style="display:none">
      <div class="ca-drop-title">Insert card here</div>
      <div class="ca-drop-sub">drop your card file · or click to browse</div>
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
        <div class="ca-modal-title">Get your card</div>
        <div class="ca-modal-sub">
          Pick a tier, enter your name and email.<br>
          Your card arrives instantly.
        </div>
        <div class="ca-tier-picker" id="ca-tier-picker"></div>
        <input type="text"  class="ca-field" id="ca-signup-name"  placeholder="Your name">
        <input type="email" class="ca-field" id="ca-signup-email" placeholder="Your email">
        <div class="ca-msg-err" id="ca-signup-err"></div>
        <div class="ca-msg-ok"  id="ca-signup-ok"></div>
        <div class="ca-submit-row">
          <button class="ca-submit" id="ca-submit">Send my card</button>
          <button class="ca-close"  id="ca-close">✕</button>
        </div>
      </div>
    </div>
  `

  // ── Render tier picker ──
  function renderTierPicker() {
    const el = document.getElementById('ca-tier-picker')
    el.innerHTML = tiers.map((t, i) => `
      <div class="ca-tier-option${t === selectedTier ? ' selected' : ''}" data-i="${i}">
        <span class="ca-tier-name">${t.name}${t.label ? ' — ' + t.label : ''}</span>
        <span class="ca-tier-price">${t.price ? '$' + t.price + '/mo' : 'Free'}</span>
      </div>`).join('')
    el.querySelectorAll('.ca-tier-option').forEach(opt => {
      opt.onclick = () => {
        selectedTier = tiers[Number(opt.dataset.i)]
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
  const stored = sessionStorage.getItem('crith_member_' + name)
  if (stored) {
    try {
      const d = JSON.parse(stored)
      if (new Date(d.expires_at) > new Date()) {
        grantAccess(d)
      } else {
        sessionStorage.removeItem('crith_member_' + name)
      }
    } catch(e) {}
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
  function applyManifest(manifest) {
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
    verifyWithAPI(manifest.credential_id, null)
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
        const zip = await JSZip.loadAsync(await file.arrayBuffer())
        if (!zip.file('manifest.json')) {
          showResult('invalid', '✗ Not a valid credential bundle.')
          return
        }
        const manifest = JSON.parse(await zip.file('manifest.json').async('string'))
        applyManifest(manifest)
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
        applyManifest(manifest)
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
  async function verifyWithAPI(credential_id, bundle_hash) {
    showResult('checking', 'Verifying...')
    try {
      const res = await fetch(`${API_BASE}/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credential_id, bundle_hash }),
      })
      const data = await res.json()
      if (data.valid) {
        sessionStorage.setItem('crith_member_' + name, JSON.stringify(data))
        grantAccess(data)
      } else {
        showResult('invalid', `✗ ${data.error || 'Invalid credential.'}`)
      }
    } catch(e) {
      showResult('invalid', '✗ Could not reach verification server. Try dropping your .zip bundle instead.')
    }
  }

  // ── GRANT ACCESS ──
  function grantAccess(data) {
    memberData = data
    const memberName = data.holder_name || data.name || 'Member'
    const expiry = new Date(data.expires_at).toLocaleDateString('en-GB', {
      day: '2-digit', month: 'short', year: 'numeric'
    })

    showResult('valid', `✔ Welcome, ${memberName}. ${data.tier} access · valid until ${expiry}`)

    document.getElementById('ca-member-header').innerHTML = `
      <div class="ca-member-name">${memberName}</div>
      <div class="ca-member-tier">${data.tier}</div>
      <div class="ca-member-hr"></div>
      <div class="ca-member-meta">
        <div><b>ACCESS CLASS</b> // <span>${data.tier}</span></div>
        <div><b>VALID UNTIL</b> // <span>${expiry}</span></div>
      </div>`

    buildMemberArea(data.sections || [])
    document.getElementById('ca-member-area').style.display = 'block'
    document.getElementById('ca-member-area').scrollIntoView({ behavior: 'smooth' })

    window.history.replaceState({}, '', window.location.pathname)
  }

  // ── BUILD MEMBER AREA ──
  function buildMemberArea(sections) {
    const tabsEl   = document.getElementById('ca-tabs')
    const panelsEl = document.getElementById('ca-panels')
    tabsEl.innerHTML   = ''
    panelsEl.innerHTML = ''

    const availableSections = []
    if (content.downloads && content.downloads.length && sections.includes('downloads'))
      availableSections.push('downloads')
    if (content.bts && content.bts.length && sections.includes('bts'))
      availableSections.push('bts')
    if (content.chat && sections.includes('chat'))
      availableSections.push('chat')
    if (content.merch && sections.includes('merch'))
      availableSections.push('merch')

    if (!availableSections.length) {
      panelsEl.innerHTML = '<div class="ca-panel active" style="border:1px solid #222;border-top:none;padding:28px;"><p style="color:#555;font-size:10px;">No content available yet.</p></div>'
      return
    }

    availableSections.forEach((sec, i) => {
      // Tab
      const btn = document.createElement('button')
      btn.className = 'ca-tab' + (i === 0 ? ' active' : '')
      btn.textContent = '// ' + sec.toUpperCase()
      btn.onclick = () => switchTab(sec, btn)
      tabsEl.appendChild(btn)

      // Panel
      const panel = document.createElement('div')
      panel.className = 'ca-panel' + (i === 0 ? ' active' : '')
      panel.id = 'ca-panel-' + sec
      panel.innerHTML = buildPanel(sec)
      panelsEl.appendChild(panel)
    })

    // Wire chat
    if (sections.includes('chat')) {
      const sendBtn   = document.getElementById('ca-chat-send')
      const chatInput = document.getElementById('ca-chat-input')
      if (sendBtn)   sendBtn.onclick = sendChat
      if (chatInput) chatInput.onkeydown = e => { if (e.key === 'Enter') sendChat() }
    }
  }

  function switchTab(name, btn) {
    document.querySelectorAll('.ca-tab').forEach(b => b.classList.remove('active'))
    document.querySelectorAll('.ca-panel').forEach(p => p.classList.remove('active'))
    btn.classList.add('active')
    document.getElementById('ca-panel-' + name).classList.add('active')
  }

  function buildPanel(sec) {
    if (sec === 'downloads') {
      const items = (content.downloads || []).map((t, i) => `
        <div class="ca-track">
          <div>
            <div class="ca-track-title">${t.title}</div>
            <div class="ca-track-meta">${t.meta || ''}</div>
          </div>
          <a href="${t.url}" class="ca-dl-btn" ${t.url !== '#' ? 'download' : ''}>↓ Download</a>
        </div>`).join('')
      return `<div class="ca-panel-title">Downloads</div>${items}`
    }

    if (sec === 'bts') {
      const items = (content.bts || []).map(v => `
        <div class="ca-video-card">
          <div class="ca-video-thumb">▶</div>
          <div class="ca-video-title">${v.title}</div>
          <div class="ca-video-meta">${v.meta || ''}</div>
        </div>`).join('')
      return `<div class="ca-panel-title">Behind The Scenes</div><div class="ca-video-grid">${items}</div>`
    }

    if (sec === 'merch') {
      const m = content.merch || {}
      return `
        <div class="ca-panel-title">Merch Discount</div>
        <div class="ca-track">
          <div>
            <div class="ca-track-title">${m.label || 'Member Discount'}</div>
            <div class="ca-track-meta">Code: ${m.code || ''}</div>
          </div>
          <a href="${m.url || '#'}" class="ca-dl-btn" target="_blank" rel="noopener">Shop →</a>
        </div>`
    }

    if (sec === 'chat') {
      return `
        <div class="ca-panel-title">Chat</div>
        <div class="ca-chat-messages" id="ca-chat-messages">
          <div>
            <div class="ca-msg-author">${name} // system</div>
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
      <div class="ca-msg-author">${memberName}</div>
      <div class="ca-msg-text" style="color:inherit;">${msg.replace(/</g,'&lt;')}</div>`
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
          okEl.innerHTML = (data.instructions || 'Request received. Your access will be issued once payment is confirmed.').replace(/\n/g, '<br>')
          okEl.style.display = 'block'
          btn.textContent = 'Request sent'
          return
        }
        okEl.innerHTML = `✔ Card sent to ${emailVal}.<br>Check your inbox — your card and access link are on their way.`
        okEl.style.display = 'block'
        btn.textContent = '✔ Sent'
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