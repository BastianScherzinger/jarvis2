'use strict';
/* ════════════════════════════════════════════════════════════════════════════
   JARVIS LeadHunter — LIVE-SYSTEM-PIPELINE  (v4, Mehrfach-Instanz, Stationen-Kette)
   Ein 2D-Canvas-Hologramm des kompletten Lead-Flusses in Echtzeit:

     [ Internet-Scraper × N ]
              └─▶ SAMMELN ─▶ BEWERTEN ─▶ WEBSEITE ─▶ MAKEOVER ─▶ FREIGABE ─▶ VERSAND

   • JEDER ECHTE LOG wird zu einem PUNKT in der Pipeline:
       Die Live-Log-Konsole zieht den kompletten Ringpuffer ALLER Module
       (`/api/logs` → logger._buffer). Jede neue Log-Zeile wird nach ihrem Worker/Level
       der richtigen Station zugeordnet und wandert als Bubble durch das Segment DAVOR —
       die Bubble-FARBE = Log-Level (cyan INFO, grün Erfolg, orange Scrape, violett
       Bewertung, gold Warnung, rot FEHLER). Der Ziel-Knoten leuchtet bei Ankunft auf,
       Fehler blitzen rot. So sieht man 1:1, welcher Code-Block gerade arbeitet.
   • Zusätzlich getippte SSE-Ereignisse (heller, mit Label):
       SSE `lead`      → Scraper ▶ SAMMELN   (grün „Lead")
       SSE `evaluated` → SAMMELN ▶ BEWERTEN   (cyan „bewertet")
       Δ Website live  → BEWERTEN ▶ WEBSEITE   (gold „Website")
       Δ Mail versandt → FREIGABE ▶ VERSAND    (violett „Angebot")

   Drei Instanzen teilen dieselben Poller/Daten:
     initPipeline()         — grosse Ansicht im Graph-Tab (#pipeline-canvas + #pipeline-log)
     initPipelinePreview()  — Live-Mini-Vorschau auf der Startseite (#home-pipeline-canvas)
     initPipelineStatus()   — Popup-Mini-Vorschau auf „Mein Status" (#status-pipeline-canvas)

   Iron-Man-HUD (style.css-Tokens): Cyan #00d4ff, Grün #00e87a, additives Glühen.
   Performance: jede Instanz pausiert ihr Rendering, wenn ihre .page nicht aktiv (oder das
   Popup geschlossen) ist; Poller fetchen nur, wenn mindestens eine Instanz sichtbar ist.
   prefers-reduced-motion dämpft die Bewegung.
   ════════════════════════════════════════════════════════════════════════════ */

const _PL_REDUCED = (typeof window !== 'undefined' && window.matchMedia)
  ? window.matchMedia('(prefers-reduced-motion: reduce)').matches : false;

const _PL_SCRAPERS = ['Maps', 'GelbeSeit', 'DasOertliche', 'Elfacht', 'Golocal', 'AI', 'HeroldAT'];
const _PL_SCRAPER_LABEL = {
  Maps: 'Google Maps', GelbeSeit: 'Gelbe Seiten', DasOertliche: 'Das Örtliche',
  Elfacht: '11880', Golocal: 'GoLocal', AI: 'KI-Suche', HeroldAT: 'Herold (AT)',
};
// finder-String (aus scrapers/*.py) → Scraper-Name.
const _PL_FINDER = [
  ['maps', 'Maps'], ['gelbe', 'GelbeSeit'], ['oertlich', 'DasOertliche'],
  ['örtlich', 'DasOertliche'], ['ortlich', 'DasOertliche'], ['elfacht', 'Elfacht'],
  ['11880', 'Elfacht'], ['golocal', 'Golocal'], ['herold', 'HeroldAT'],
  ['ai', 'AI'], ['ki', 'AI'],
];
// Log-worker → Scraper-Name (Namen, mit denen die Module tatsächlich loggen).
const _PL_LOG_SCRAPER = [
  ['maps', 'Maps'], ['gelbe', 'GelbeSeit'], ['oertl', 'DasOertliche'], ['örtl', 'DasOertliche'],
  ['golocal', 'Golocal'], ['11880', 'Elfacht'], ['herold', 'HeroldAT'],
];

// Die Stationen der Kette (nach der Scraper-Spalte). Reihenfolge = Fluss links→rechts.
const _PL_STAGES = [
  { key: 'collect',  label: 'SAMMELN',  sub: 'Rohleads',     color: '#00e87a', icon: 'robot',  lc: '#7fe9b6' },
  { key: 'eval',     label: 'BEWERTEN', sub: 'KI-Scoring',   color: '#00d4ff', icon: 'claude', lc: '#e79a80' },
  { key: 'build',    label: 'WEBSEITE', sub: 'Bau',          color: '#c58bff', icon: 'build',  lc: '#c9a0ff' },
  { key: 'makeover', label: 'MAKEOVER', sub: 'Feinschliff',  color: '#ff9d3d', icon: 'spark',  lc: '#ffb877' },
  { key: 'wait',     label: 'FREIGABE', sub: 'Warten',       color: '#ffc93d', icon: 'clock',  lc: '#ffd873' },
  { key: 'send',     label: 'VERSAND',  sub: 'Angebot raus', color: '#9b5de5', icon: 'mail',   lc: '#c19bf0' },
];

const _PL_SEG_DUR_BASE = 1.0;           // Sekunden pro Segment (× Instanz-Faktor)
const _PL_LV_COLOR = {
  INFO: '#00d4ff', SUCCESS: '#00e87a', WARN: '#ffc93d', ERROR: '#ff3b4e',
  DEBUG: '#6684a8', EVAL: '#c58bff', SCRAPE: '#ff9d3d',
};

// ── Geteilte Daten + Poller (instanzübergreifend) ────────────────────────────
const _D = {
  scrapers: _PL_SCRAPERS.map(n => ({ name: n, alive: false, count: 0 })),
  stats: { total: 0, live: 0, sent: 0, building: 0, active: 0, running: false },
  prev:  { live: -1, sent: -1 },
  logs:  [],            // {ts, level, worker, msg}
  errors: _PL_STAGES.map(() => []),   // pro Station: [{ts, worker, msg, level}]  (rote Blase + Panel)
  logLastTs: '',
  started: false, pollTimer: null, logTimer: null,
};
const _PL_INST = [];
let _plErrPanelIdx = -1;

function _plAnyVisible() { return _PL_INST.some(_plVisible); }
function _plVisible(P) {
  const pg = P.wrap.closest ? P.wrap.closest('.page') : null;
  if (!pg || !pg.classList.contains('active') || document.hidden) return false;
  if (P.opts && typeof P.opts.gate === 'function' && !P.opts.gate()) return false;
  return true;
}

function _plStartPollers() {
  if (_D.started) return;
  _D.started = true;
  _plPollStatus(); _plPollLogs();
  _D.pollTimer = setInterval(_plPollStatus, 4000);
  _D.logTimer  = setInterval(_plPollLogs, 1300);
}

async function _plPollStatus() {
  if (!_plAnyVisible()) return;
  try {
    const [st, hs] = await Promise.all([
      fetch('/api/status').then(r => r.json()).catch(() => null),
      fetch('/api/home/stats').then(r => r.json()).catch(() => null),
    ]);
    if (st) {
      _D.stats.running = !!st.running;
      const by = {}; (st.workers || []).forEach(w => { by[w.name] = w.alive; });
      _D.scrapers.forEach(s => { s.alive = !!by[s.name]; });
      _D.stats.active = _D.scrapers.filter(s => s.alive).length;
      if (st.stats) _D.stats.total = st.stats.total || 0;
    }
    if (hs) {
      _D.stats.live = hs.live || 0; _D.stats.sent = hs.sent || 0; _D.stats.building = hs.building || 0;
      if (_D.prev.live >= 0) {
        _plBurstStage(2, '#ffc93d', 'Website', Math.min(8, Math.max(0, _D.stats.live - _D.prev.live)));
        _plBurstStage(5, '#9b5de5', 'Angebot', Math.min(8, Math.max(0, _D.stats.sent - _D.prev.sent)));
      }
      _D.prev.live = _D.stats.live; _D.prev.sent = _D.stats.sent;
    }
    _PL_INST.forEach(_plRenderHud);
  } catch (e) { /* still weiter */ }
}

async function _plPollLogs() {
  if (!_plAnyVisible()) return;
  try {
    const u = _D.logLastTs ? `/api/logs?since=${encodeURIComponent(_D.logLastTs)}&limit=80`
                           : '/api/logs?limit=60';
    const d = await fetch(u).then(r => r.json()).catch(() => null);
    if (!d || !d.logs || !d.logs.length) return;
    const fresh = _D.logLastTs.length > 0;
    d.logs.forEach((e, i) => {
      _D.logs.push(e);
      if (e.level === 'ERROR') _plRecordError(e);   // rote Blase zählt auch Alt-Fehler
      if (fresh) _plReactToLog(e, i);               // nur echte Neuzugänge werden zu Punkten
    });
    if (_D.logs.length > 300) _D.logs.splice(0, _D.logs.length - 300);
    _D.logLastTs = d.last_ts || _D.logLastTs;
    _PL_INST.forEach(_plRenderLog);
    _PL_INST.forEach(_plSyncBadges);
    _plRefreshErrPanel();
  } catch (e) { /* still weiter */ }
}

// Fehler einer Station zuordnen und für Blase/Panel speichern.
function _plRecordError(e) {
  const c = _plClassifyLog(e);
  const idx = (c && typeof c.stageIdx === 'number') ? c.stageIdx : 0;
  if (!_D.errors[idx]) _D.errors[idx] = [];
  _D.errors[idx].push({ ts: e.ts || '', worker: e.worker || '', msg: e.msg || '', level: e.level || 'ERROR' });
  if (_D.errors[idx].length > 200) _D.errors[idx].splice(0, _D.errors[idx].length - 200);
}

// Getippte Sammel-Bursts (Δ live/sent) — leicht gestaffelt.
function _plBurstStage(stageIdx, color, label, n) {
  if (n <= 0) return;
  for (let i = 0; i < n; i++) {
    setTimeout(() => _PL_INST.forEach(P => { if (_plVisible(P)) _plSpawnStage(P, stageIdx, color, label); }), i * 240);
  }
}

// ── Log-Klassifikation → welche Station reagiert ─────────────────────────────
// Rückgabe: { stageIdx, scraperIdx? } oder null.
function _plClassifyLog(e) {
  const w = (e.worker || '').toLowerCase(), lv = e.level || '';
  for (const [kw, nm] of _PL_LOG_SCRAPER) if (w.includes(kw)) {
    return { stageIdx: 0, scraperIdx: _D.scrapers.findIndex(s => s.name === nm) };
  }
  if (lv === 'SCRAPE') return { stageIdx: 0, scraperIdx: -1 };
  if (/makeover|overnight/.test(w))                         return { stageIdx: 3 };
  if (/discord|freigab|vote|approval|gate/.test(w))         return { stageIdx: 4 };
  if (/mailer|offer|versand|smtp|inbox|outreach/.test(w))   return { stageIdx: 5 };
  if (w.includes('mail'))                                   return { stageIdx: 5 };
  if (/autobuild|auto_build|builder|website|railway|deploy|hero|github|build/.test(w)) return { stageIdx: 2 };
  if (lv === 'EVAL' || /eval|bewert|score|analyst|social|ollama/.test(w)) return { stageIdx: 1 };
  if (/leadcollector|collector|controller|scrape/.test(w))  return { stageIdx: 0, scraperIdx: -1 };
  return null;
}

function _plReactToLog(e, order) {
  const c = _plClassifyLog(e); if (!c) return;
  const err = e.level === 'ERROR';
  const color = err ? '#ff3b4e'
              : (_PL_LV_COLOR[e.level] || (_PL_STAGES[c.stageIdx] || {}).color || '#00d4ff');
  // Mehrere Logs pro Poll leicht versetzen, damit sie als Kette laufen statt zu klumpen.
  const delay = Math.min(900, (order || 0) * 70);
  setTimeout(() => {
    _PL_INST.forEach(P => { if (_plVisible(P)) _plSpawnStage(P, c.stageIdx, color, '', c.scraperIdx, err); });
  }, delay);
}

// ── Instanz erzeugen ─────────────────────────────────────────────────────────
function _plCreate(wrap, cv, opts) {
  const P = {
    wrap, cv, ctx: cv.getContext('2d'), opts: opts || {},
    mini: !!(opts && opts.mini), logEl: (opts && opts.logEl) || null,
    W: 0, H: 0, dpr: 1, t: 0, last: performance.now(), raf: 0,
    scr: _D.scrapers.map(() => ({ x: 0, y: 0, cx: 0, cy: 0, pulse: 0, err: 0 })),
    st: _PL_STAGES.map(() => ({ x: 0, y: 0, pulse: 0, err: 0 })),
    bubbles: [], energy: {}, badges: _PL_STAGES.map(() => null), badgeLayer: null,
  };
  // Overlay-Ebene für klickbare Fehler-Blasen (HTML über dem Canvas)
  P.badgeLayer = document.createElement('div');
  P.badgeLayer.className = 'pl-badge-layer';
  wrap.appendChild(P.badgeLayer);
  _PL_INST.push(P);
  const ro = () => _plResize(P);
  _plResize(P);
  window.addEventListener('resize', ro);
  if (window.ResizeObserver) new ResizeObserver(ro).observe(wrap);
  _plRenderHud(P); _plRenderLog(P);
  _plStartPollers();
  P.raf = requestAnimationFrame(() => _plLoop(P));
  return P;
}

function _plResize(P) {
  const r = P.wrap.getBoundingClientRect();
  if (r.width < 2 || r.height < 2) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  P.W = r.width; P.H = r.height; P.dpr = dpr;
  P.cv.width = Math.round(r.width * dpr); P.cv.height = Math.round(r.height * dpr);
  P.cv.style.width = r.width + 'px'; P.cv.style.height = r.height + 'px';
  P.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  _plLayout(P);
  _plSyncBadges(P);
}

// ── Fehler-Blasen (HTML-Overlay über den Stationen) ──────────────────────────
function _plSyncBadges(P) {
  if (!P.badgeLayer) return;
  P.st.forEach((nd, i) => {
    const n = (_D.errors[i] || []).length;
    let b = P.badges[i];
    if (n > 0 && !b) {
      b = document.createElement('button');
      b.className = 'pl-errbadge' + (P.mini ? ' mini' : '');
      b.addEventListener('click', (ev) => { ev.stopPropagation(); ev.preventDefault(); _plOpenErrPanel(i); });
      P.badgeLayer.appendChild(b); P.badges[i] = b;
    }
    if (!b) return;
    if (n > 0) {
      b.style.display = 'flex';
      b.textContent = n > 99 ? '99+' : String(n);
      b.title = `${n} Fehler in ${_PL_STAGES[i].label} — klicken zum Ansehen & Kopieren`;
      b.style.left = nd.x + 'px';
      b.style.top  = (nd.y - P.hubR - (P.mini ? 9 : 15)) + 'px';
    } else {
      b.style.display = 'none';
    }
  });
}

function _plLayout(P) {
  const W = P.W, H = P.H, cy = H * 0.5;
  const flowW = P.mini ? W : W * 0.70;      // grosse Ansicht: rechts Platz für die Log-Konsole
  const n = P.st.length;
  const x0 = flowW * 0.205, x1 = flowW * 0.955;
  P.st.forEach((nd, i) => { nd.x = x0 + (x1 - x0) * (i / (n - 1)); nd.y = cy; });
  const sx = flowW * 0.055, m = P.scr.length;
  const top = P.mini ? H * 0.15 : H * 0.10, bot = P.mini ? H * 0.85 : H * 0.86;
  const span = bot - top;
  P.scr.forEach((s, i) => {
    s.x = sx; s.y = m > 1 ? top + span * (i / (m - 1)) : cy;
    s.cx = s.x * 0.35 + P.st[0].x * 0.65; s.cy = s.y * 0.5 + cy * 0.5;
  });
  P.nodeR = P.mini ? Math.max(6, Math.min(11, H * 0.045)) : Math.max(11, Math.min(18, W * 0.016));
  P.hubR  = P.mini ? Math.max(9, Math.min(15, H * 0.062)) : Math.max(15, Math.min(24, W * 0.020));
}

// ── Bubble spawnen (auf dem Segment VOR stageIdx) ────────────────────────────
function _plSpawnStage(P, stageIdx, color, label, scraperIdx, err) {
  const stage = _PL_STAGES[stageIdx]; if (!stage) return;
  color = color || stage.color;
  let from, to, cx, cy, seg;
  if (stageIdx === 0) {
    let idx = (typeof scraperIdx === 'number' && scraperIdx >= 0)
      ? scraperIdx : Math.floor(Math.random() * P.scr.length);
    const s = P.scr[idx]; if (!s) return;
    s.pulse = Math.max(s.pulse, 0.7);
    from = { x: s.x, y: s.y }; to = { x: P.st[0].x, y: P.st[0].y };
    cx = s.cx; cy = s.cy; seg = 'f' + idx;
  } else {
    const a = P.st[stageIdx - 1], b = P.st[stageIdx];
    a.pulse = Math.max(a.pulse, 0.5);
    from = { x: a.x, y: a.y }; to = { x: b.x, y: b.y };
    cx = (a.x + b.x) / 2; cy = a.y - P.H * (P.mini ? 0.10 : 0.06); seg = 'c' + (stageIdx - 1);
  }
  P.energy[seg] = 1;
  P.bubbles.push({
    seg, stageIdx, color, label: label || '', err: !!err, from, to, cx, cy,
    t: 0, dur: _PL_SEG_DUR_BASE * (P.mini ? 0.8 : 1.0) * (0.85 + Math.random() * 0.3),
    r: (P.mini ? 4.2 : 6) * (label ? 1.1 : 0.92),
  });
  if (P.bubbles.length > 180) P.bubbles.splice(0, P.bubbles.length - 180);
}

// Öffentlicher Hook aus app.js (_connectSSE) — an ALLE sichtbaren Instanzen
function pipelineOnEvent(kind, data) {
  if (kind === 'lead') {
    const idx = _plScraperIdxFor(data && data.finder);
    if (idx >= 0) _D.scrapers[idx].count++;
    _PL_INST.forEach(P => { if (_plVisible(P)) _plSpawnStage(P, 0, '#00e87a', 'Lead', idx); });
  } else if (kind === 'evaluated') {
    _PL_INST.forEach(P => { if (_plVisible(P)) _plSpawnStage(P, 1, '#00d4ff', 'bewertet'); });
  }
}

function _plScraperIdxFor(finder) {
  const f = (finder || '').toLowerCase();
  for (const [kw, nm] of _PL_FINDER) if (f.includes(kw)) {
    const i = _D.scrapers.findIndex(x => x.name === nm); if (i >= 0) return i;
  }
  if (!_D.scrapers.length) return -1;
  let h = 0; for (let i = 0; i < f.length; i++) h = (h * 31 + f.charCodeAt(i)) | 0;
  return Math.abs(h) % _D.scrapers.length;
}

// ── HUD + Konsole + Legende ──────────────────────────────────────────────────
function _plMiniCountEl(P) {
  const card = P.wrap.closest ? P.wrap.closest('.home-pipe-preview, .status-pipe-pop') : null;
  return card ? card.querySelector('.hpp-live-count') : null;
}

function _plRenderHud(P) {
  if (P.mini) {
    const l = _plMiniCountEl(P);
    if (l) l.textContent = `${_D.stats.active}/${_D.scrapers.length} aktiv · ${_D.stats.live} live · ${_D.stats.sent} raus`;
    return;
  }
  const el = document.getElementById('pipeline-hud'); if (!el) return;
  const s = _D.stats;
  const dot = (c) => `<span class="ph-dot" style="background:${c};box-shadow:0 0 7px ${c}"></span>`;
  el.innerHTML =
    `<span class="ph-chip">${dot(s.running ? '#00e87a' : '#ff3b4e')}Scraper <b>${s.active}/${_D.scrapers.length}</b></span>` +
    `<span class="ph-chip">${dot('#00e87a')}Leads <b>${(s.total).toLocaleString('de-DE')}</b></span>` +
    (s.building ? `<span class="ph-chip">${dot('#c58bff')}im Bau <b>${s.building}</b></span>` : '') +
    `<span class="ph-chip">${dot('#ffc93d')}Websites live <b>${s.live}</b></span>` +
    `<span class="ph-chip">${dot('#9b5de5')}Angebote raus <b>${s.sent}</b></span>`;
  const lg = document.getElementById('pipeline-legend');
  if (lg && !lg.dataset.done) {
    const item = (c, t) => `<span class="plg"><span class="plg-dot" style="background:${c};box-shadow:0 0 7px ${c}"></span>${t}</span>`;
    lg.innerHTML =
      `<span class="plg-hd">Punkte = echte Logs:</span>` +
      item('#00d4ff', 'Info') + item('#00e87a', 'Erfolg') + item('#ff9d3d', 'Scrape') +
      item('#c58bff', 'Bewertung') + item('#ffc93d', 'Warnung') + item('#ff3b4e', 'Fehler');
    lg.dataset.done = '1';
  }
}

function _plEsc(s) { return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

function _plRenderLog(P) {
  const el = P.logEl || (P.mini ? null : document.getElementById('pipeline-log'));
  if (!el) return;
  const nMax = P.mini ? 7 : 26;
  const lines = _D.logs.slice(-nMax);
  const stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 24;   // Auto-Scroll wenn unten
  el.innerHTML = lines.map(e => {
    const c = _PL_LV_COLOR[e.level] || '#8fa8c4';
    return `<div class="pl-line"><span class="pl-ts">${_plEsc(e.ts)}</span>` +
           `<span class="pl-lv" style="color:${c}">${_plEsc((e.level || '').slice(0, 4))}</span>` +
           `<span class="pl-wk">${_plEsc((e.worker || '').slice(0, 11))}</span>` +
           `<span class="pl-msg">${_plEsc(e.msg || '')}</span></div>`;
  }).join('');
  if (stick) el.scrollTop = el.scrollHeight;
}

// ── Render-Loop ──────────────────────────────────────────────────────────────
function _plLoop(P) {
  P.raf = requestAnimationFrame(() => _plLoop(P));
  if (!_plVisible(P)) { P.last = performance.now(); return; }
  const now = performance.now();
  let dt = (now - P.last) / 1000; P.last = now;
  if (dt > 0.1) dt = 0.1;
  const mo = _PL_REDUCED ? 0.15 : 1;
  P.t += dt * mo;
  _plUpdate(P, dt * mo);
  _plDraw(P);
}

function _plUpdate(P, dt) {
  for (let i = P.bubbles.length - 1; i >= 0; i--) {
    const b = P.bubbles[i];
    b.t += dt / b.dur;
    P.energy[b.seg] = 1;
    if (b.t >= 1) {
      const dest = P.st[b.stageIdx];
      if (dest) { dest.pulse = 1; if (b.err) dest.err = 1; }
      P.bubbles.splice(i, 1);
    }
  }
  const dec = dt * 1.7, decE = dt * 1.2;
  [...P.st, ...P.scr].forEach(nd => {
    nd.pulse = Math.max(0, nd.pulse - dec);
    nd.err = Math.max(0, (nd.err || 0) - decE);
  });
  for (const k in P.energy) { P.energy[k] = Math.max(0, P.energy[k] - dt * 0.55); }
}

function _plPos(b) {
  const t = b.t, u = 1 - t;
  return { x: u * u * b.from.x + 2 * u * t * b.cx + t * t * b.to.x,
           y: u * u * b.from.y + 2 * u * t * b.cy + t * t * b.to.y };
}

function _plDraw(P) {
  const ctx = P.ctx, W = P.W, H = P.H;
  ctx.clearRect(0, 0, W, H);

  // Scraper → SAMMELN
  P.scr.forEach((s, i) => {
    const alive = _D.scrapers[i].alive;
    const e = P.energy['f' + i] || 0;
    _plPipe(P, s.x, s.y, P.st[0].x, P.st[0].y, s.cx, s.cy,
            alive ? '#00e87a' : '#2a4058', 0.09 + e * 0.5 + (alive ? 0.05 : 0), P.nodeR * 0.5);
  });
  // Stationen-Kette
  for (let k = 0; k < P.st.length - 1; k++) {
    const a = P.st[k], b = P.st[k + 1], e = P.energy['c' + k] || 0;
    _plPipe(P, a.x, a.y, b.x, b.y, (a.x + b.x) / 2, a.y - H * (P.mini ? 0.10 : 0.06),
            _PL_STAGES[k + 1].color, 0.14 + e * 0.5, P.hubR * 0.4);
  }

  // Bubbles (additiv)
  ctx.globalCompositeOperation = 'lighter';
  for (const b of P.bubbles) { const p = _plPos(b); _plGlowDot(P, p.x, p.y, b.r, b.color); }
  ctx.globalCompositeOperation = 'source-over';

  // Labels nur für getippte Ereignisse (grosse Ansicht)
  if (!P.mini) {
    ctx.font = '600 9px JetBrains Mono, monospace'; ctx.textAlign = 'center';
    for (const b of P.bubbles) {
      if (!b.label || b.t < 0.18 || b.t > 0.9) continue;
      const p = _plPos(b);
      ctx.globalAlpha = 0.75; ctx.fillStyle = b.color;
      ctx.fillText(b.label, p.x, p.y - b.r - 5); ctx.globalAlpha = 1;
    }
  }

  P.scr.forEach((s, i) => _plDrawScraper(P, s, _D.scrapers[i]));
  P.st.forEach((nd, i) => _plDrawStation(P, nd, _PL_STAGES[i], i));
}

function _plPipe(P, x0, y0, x1, y1, cx, cy, color, alpha, width) {
  const ctx = P.ctx; ctx.save(); ctx.lineCap = 'round';
  ctx.beginPath(); ctx.moveTo(x0, y0); ctx.quadraticCurveTo(cx, cy, x1, y1);
  ctx.strokeStyle = color; ctx.globalAlpha = Math.min(0.5, alpha * 0.6); ctx.lineWidth = width; ctx.stroke();
  ctx.globalAlpha = Math.min(1, alpha); ctx.lineWidth = Math.max(1.4, width * 0.4); ctx.stroke();
  if (!_PL_REDUCED) {
    ctx.globalAlpha = Math.min(0.9, 0.25 + alpha);
    ctx.setLineDash([2, 16]); ctx.lineDashOffset = -(P.t * 60) % 18;
    ctx.lineWidth = Math.max(1.6, width * 0.5); ctx.strokeStyle = color; ctx.stroke();
    ctx.setLineDash([]);
  }
  ctx.restore();
}

function _plGlowDot(P, x, y, r, color) {
  const ctx = P.ctx;
  const g = ctx.createRadialGradient(x, y, 0, x, y, r * 3.4);
  g.addColorStop(0, color); g.addColorStop(0.35, _plAlpha(color, 0.55)); g.addColorStop(1, _plAlpha(color, 0));
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r * 3.4, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = '#ffffff'; ctx.beginPath(); ctx.arc(x, y, r * 0.55, 0, Math.PI * 2); ctx.fill();
}

function _plPulseRing(P, node, r, color) {
  const ctx = P.ctx;
  if (node.err > 0) {   // Fehler-Blitz (rot)
    ctx.beginPath(); ctx.arc(node.x, node.y, r + 3, 0, Math.PI * 2);
    ctx.strokeStyle = '#ff3b4e'; ctx.globalAlpha = node.err * 0.9; ctx.lineWidth = 2.4; ctx.stroke(); ctx.globalAlpha = 1;
  }
  if (node.pulse <= 0) return;
  const p = node.pulse;
  ctx.beginPath(); ctx.arc(node.x, node.y, r + (1 - p) * r * 1.1, 0, Math.PI * 2);
  ctx.strokeStyle = color; ctx.globalAlpha = p * 0.6; ctx.lineWidth = 2; ctx.stroke(); ctx.globalAlpha = 1;
}

function _plNodeLabel(P, x, y, text, color, sub) {
  const ctx = P.ctx; ctx.textAlign = 'center';
  ctx.font = `700 ${P.mini ? 7 : 10}px Orbitron, sans-serif`; ctx.fillStyle = color;
  ctx.fillText(text, x, y);
  if (sub && !P.mini) {
    ctx.font = '400 8.5px Inter, sans-serif'; ctx.fillStyle = 'rgba(150,175,205,.85)';
    ctx.fillText(sub, x, y + 12);
  }
}

function _plDrawScraper(P, s, data) {
  const ctx = P.ctx, r = P.nodeR, alive = data.alive;
  const col = alive ? '#00e87a' : '#3a5573';
  const breathe = alive ? (0.5 + 0.5 * Math.sin(P.t * 2 + s.y)) : 0;
  _plPulseRing(P, s, r, '#00e87a');
  if (alive) {
    const g = ctx.createRadialGradient(s.x, s.y, 0, s.x, s.y, r * 2);
    g.addColorStop(0, _plAlpha('#00e87a', 0.18 + breathe * 0.12)); g.addColorStop(1, _plAlpha('#00e87a', 0));
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(s.x, s.y, r * 2, 0, Math.PI * 2); ctx.fill();
  }
  ctx.save(); ctx.translate(s.x, s.y);
  ctx.beginPath(); ctx.arc(0, 0, r, 0, Math.PI * 2);
  ctx.fillStyle = 'rgba(6,14,20,.92)'; ctx.fill();
  ctx.lineWidth = 1.6; ctx.strokeStyle = col;
  if (!alive) ctx.setLineDash([3, 3]);
  ctx.globalAlpha = alive ? 0.95 : 0.6; ctx.stroke(); ctx.setLineDash([]);
  ctx.globalAlpha = alive ? 0.8 : 0.45; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(-r, 0); ctx.lineTo(r, 0); ctx.stroke();
  for (const kk of [0.5, 1]) { ctx.beginPath(); ctx.ellipse(0, 0, r * kk, r, 0, 0, Math.PI * 2); ctx.stroke(); }
  ctx.beginPath(); ctx.ellipse(0, 0, r, r * 0.5, 0, 0, Math.PI * 2); ctx.stroke();
  ctx.restore();
  ctx.beginPath(); ctx.arc(s.x + r * 0.82, s.y - r * 0.82, P.mini ? 2.2 : 3.2, 0, Math.PI * 2);
  ctx.fillStyle = alive ? '#00e87a' : '#ff3b4e';
  ctx.shadowColor = ctx.fillStyle; ctx.shadowBlur = alive ? 8 : 0; ctx.fill(); ctx.shadowBlur = 0;
  if (!P.mini) _plNodeLabel(P, s.x, s.y + r + 13, (_PL_SCRAPER_LABEL[data.name] || data.name).toUpperCase(),
    alive ? '#7fe9b6' : '#4a6a86', data.count ? data.count + ' Leads' : '');
}

// ── Stationen-Knoten (Basis-Disc + Glühen + Icon) ────────────────────────────
function _plDrawStation(P, node, stage, idx) {
  const ctx = P.ctx, R = P.hubR;
  const nErr = (_D.errors[idx] || []).length;
  const hasErr = nErr > 0;
  const col = hasErr ? '#ff3b4e' : stage.color;   // Fehler → Symbol wird rot
  _plPulseRing(P, node, R, col);
  if (hasErr) {   // zusätzlicher, dauerhaft pulsierender roter Alarm-Ring
    const pr = 0.5 + 0.5 * Math.sin(P.t * 3.2);
    ctx.beginPath(); ctx.arc(node.x, node.y, R * (1.18 + pr * 0.18), 0, Math.PI * 2);
    ctx.strokeStyle = _plAlpha('#ff3b4e', 0.35 + pr * 0.4); ctx.lineWidth = 2; ctx.stroke();
  }
  const glowBoost = hasErr ? 0.32 : 0;
  const g = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, R * 2.1);
  g.addColorStop(0, _plAlpha(col, 0.24 + node.pulse * 0.26 + glowBoost)); g.addColorStop(1, _plAlpha(col, 0));
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(node.x, node.y, R * 2.1, 0, Math.PI * 2); ctx.fill();

  ctx.save(); ctx.translate(node.x, node.y);
  ctx.beginPath(); ctx.arc(0, 0, R * 0.92, 0, Math.PI * 2);
  ctx.fillStyle = hasErr ? 'rgba(26,8,11,.92)' : 'rgba(8,14,22,.9)'; ctx.fill();
  ctx.lineWidth = 1.6; ctx.strokeStyle = _plAlpha(col, hasErr ? 0.7 : 0.4); ctx.stroke();
  _plStationIcon(P, stage.icon, R, col);
  ctx.restore();

  if (!P.mini) _plNodeLabel(P, node.x, node.y + R + 15, stage.label,
    hasErr ? '#ff6b7c' : (stage.lc || col), hasErr ? nErr + ' Fehler' : stage.sub);
}

function _plStationIcon(P, icon, R, col) {
  const ctx = P.ctx;
  if (icon === 'robot') {
    const hw = R * 0.82, hh = R * 0.7, rad = R * 0.18;
    _plRoundRect(P, -hw, -hh, hw * 2, hh * 2, rad);
    ctx.fillStyle = 'rgba(8,20,30,.95)'; ctx.fill();
    ctx.lineWidth = 2; ctx.strokeStyle = col; ctx.globalAlpha = 0.95; ctx.stroke(); ctx.globalAlpha = 1;
    ctx.beginPath(); ctx.moveTo(0, -hh); ctx.lineTo(0, -hh - R * 0.3); ctx.stroke();
    ctx.beginPath(); ctx.arc(0, -hh - R * 0.3, 2.4, 0, Math.PI * 2);
    ctx.fillStyle = '#00e87a'; ctx.shadowColor = '#00e87a'; ctx.shadowBlur = 8; ctx.fill(); ctx.shadowBlur = 0;
    const blink = 0.6 + 0.4 * Math.abs(Math.sin(P.t * 1.5));
    ctx.fillStyle = _plAlpha(col, blink);
    const ew = R * 0.24, eh = R * 0.18, eo = R * 0.32;
    _plRoundRect(P, -eo - ew / 2, -eh / 2, ew, eh, 3); ctx.fill();
    _plRoundRect(P, eo - ew / 2, -eh / 2, ew, eh, 3); ctx.fill();
    ctx.strokeStyle = _plAlpha(col, 0.5); ctx.lineWidth = 1;
    for (let i = -2; i <= 2; i++) { ctx.beginPath(); ctx.moveTo(i * R * 0.09, hh * 0.42); ctx.lineTo(i * R * 0.09, hh * 0.6); ctx.stroke(); }
  } else if (icon === 'claude') {
    const rays = 12, rot = _PL_REDUCED ? 0 : P.t * 0.35;
    ctx.strokeStyle = col; ctx.lineCap = 'round';
    for (let i = 0; i < rays; i++) {
      const a = rot + (i / rays) * Math.PI * 2, inner = R * 0.18, outer = R * (0.55 + 0.12 * (i % 2));
      ctx.globalAlpha = 0.85; ctx.lineWidth = P.mini ? 1.2 : 2;
      ctx.beginPath(); ctx.moveTo(Math.cos(a) * inner, Math.sin(a) * inner); ctx.lineTo(Math.cos(a) * outer, Math.sin(a) * outer); ctx.stroke();
    }
    ctx.globalAlpha = 1;
    ctx.beginPath(); ctx.arc(0, 0, R * 0.15, 0, Math.PI * 2);
    ctx.fillStyle = '#ffece3'; ctx.shadowColor = col; ctx.shadowBlur = 10; ctx.fill(); ctx.shadowBlur = 0;
  } else if (icon === 'build') {
    const w = R * 1.12, h = R * 0.82;
    _plRoundRect(P, -w / 2, -h / 2, w, h, R * 0.14);
    ctx.fillStyle = 'rgba(18,10,28,.95)'; ctx.fill();
    ctx.lineWidth = 2; ctx.strokeStyle = col; ctx.globalAlpha = 0.9; ctx.stroke(); ctx.globalAlpha = 1;
    ctx.strokeStyle = _plAlpha(col, 0.6); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(-w / 2, -h / 2 + h * 0.3); ctx.lineTo(w / 2, -h / 2 + h * 0.3); ctx.stroke();
    // </>
    ctx.strokeStyle = col; ctx.lineWidth = 1.8; ctx.lineCap = 'round';
    const bx = R * 0.36, by = h * 0.08, sp = R * 0.2;
    ctx.beginPath(); ctx.moveTo(-bx * 0.2, by - sp); ctx.lineTo(-bx * 0.55, by); ctx.lineTo(-bx * 0.2, by + sp); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(bx * 0.2, by - sp); ctx.lineTo(bx * 0.55, by); ctx.lineTo(bx * 0.2, by + sp); ctx.stroke();
  } else if (icon === 'spark') {
    ctx.strokeStyle = col; ctx.lineCap = 'round';
    ctx.save(); ctx.rotate(_PL_REDUCED ? 0 : P.t * 0.6);
    for (let i = 0; i < 4; i++) { const a = i * Math.PI / 2; ctx.globalAlpha = 0.9; ctx.lineWidth = 2.2;
      ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(Math.cos(a) * R * 0.6, Math.sin(a) * R * 0.6); ctx.stroke(); }
    ctx.rotate(Math.PI / 4);
    for (let i = 0; i < 4; i++) { const a = i * Math.PI / 2; ctx.globalAlpha = 0.55; ctx.lineWidth = 1.4;
      ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(Math.cos(a) * R * 0.34, Math.sin(a) * R * 0.34); ctx.stroke(); }
    ctx.restore(); ctx.globalAlpha = 1;
    ctx.beginPath(); ctx.arc(0, 0, R * 0.12, 0, Math.PI * 2);
    ctx.fillStyle = '#fff'; ctx.shadowColor = col; ctx.shadowBlur = 8; ctx.fill(); ctx.shadowBlur = 0;
  } else if (icon === 'clock') {
    ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.globalAlpha = 0.95;
    ctx.beginPath(); ctx.arc(0, 0, R * 0.6, 0, Math.PI * 2); ctx.stroke();
    ctx.lineCap = 'round';
    ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(0, -R * 0.34); ctx.stroke();
    const a = (_PL_REDUCED ? 0 : P.t * 0.9) - Math.PI / 2;
    ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(Math.cos(a) * R * 0.46, Math.sin(a) * R * 0.46); ctx.stroke();
    ctx.globalAlpha = 1;
  } else if (icon === 'mail') {
    const w = R * 1.22, h = R * 0.84;
    _plRoundRect(P, -w / 2, -h / 2, w, h, R * 0.14);
    ctx.fillStyle = 'rgba(22,16,30,.95)'; ctx.fill();
    ctx.lineWidth = 2; ctx.strokeStyle = col; ctx.globalAlpha = 0.95; ctx.stroke();
    ctx.globalAlpha = 0.9; ctx.lineWidth = 1.6;
    ctx.beginPath(); ctx.moveTo(-w / 2, -h / 2); ctx.lineTo(0, h * 0.12); ctx.lineTo(w / 2, -h / 2); ctx.stroke();
    ctx.globalAlpha = 1;
  }
}

// ── Utils ────────────────────────────────────────────────────────────────────
function _plRoundRect(P, x, y, w, h, r) {
  const ctx = P.ctx; ctx.beginPath(); ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}
function _plAlpha(hex, a) {
  const h = hex.replace('#', '');
  const n = parseInt(h.length === 3 ? h.replace(/(.)/g, '$1$1') : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

// ── Fehler-Panel (scroll- + kopierbar) ───────────────────────────────────────
function _plOpenErrPanel(idx) {
  _plErrPanelIdx = idx;
  const p = document.getElementById('pl-errpanel'); if (!p) return;
  _plRenderErrPanel();
  p.classList.add('show');
  const list = document.getElementById('pl-errlist'); if (list) list.scrollTop = list.scrollHeight;
}
function _plCloseErrPanel() {
  const p = document.getElementById('pl-errpanel'); if (p) p.classList.remove('show');
  _plErrPanelIdx = -1;
}
function _plRenderErrPanel() {
  if (_plErrPanelIdx < 0) return;
  const idx = _plErrPanelIdx, stage = _PL_STAGES[idx], errs = _D.errors[idx] || [];
  const t = document.getElementById('ple-title');
  if (t) t.textContent = `Fehler · ${stage ? stage.label : ''} (${errs.length})`;
  const list = document.getElementById('pl-errlist'); if (!list) return;
  const stick = list.scrollTop + list.clientHeight >= list.scrollHeight - 20;
  list.innerHTML = errs.length
    ? errs.map(e =>
        `<div class="ple-row"><div class="ple-meta">` +
        `<span class="ple-ts">${_plEsc(e.ts)}</span>` +
        `<span class="ple-wk">${_plEsc(e.worker)}</span></div>` +
        `<div class="ple-msg">${_plEsc(e.msg)}</div></div>`).join('')
    : '<div class="ple-empty">Keine Fehler in dieser Station.</div>';
  if (stick) list.scrollTop = list.scrollHeight;
}
function _plRefreshErrPanel() {
  const p = document.getElementById('pl-errpanel');
  if (p && p.classList.contains('show')) _plRenderErrPanel();
}
function _plCopyErrors() {
  if (_plErrPanelIdx < 0) return;
  const errs = _D.errors[_plErrPanelIdx] || [];
  const text = errs.map(e => `[${e.ts}] ${e.worker}: ${e.msg}`).join('\n');
  _plCopyText(text);
  const btn = document.getElementById('ple-copy');
  if (btn) { const o = btn.textContent; btn.textContent = 'Kopiert ✓'; setTimeout(() => { btn.textContent = o; }, 1400); }
}
function _plClearErrors() {
  if (_plErrPanelIdx < 0) return;
  _D.errors[_plErrPanelIdx] = [];
  _plRenderErrPanel();
  _PL_INST.forEach(_plSyncBadges);
}
function _plCopyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).catch(() => _plCopyFallback(text));
  } else { _plCopyFallback(text); }
}
function _plCopyFallback(text) {
  const ta = document.createElement('textarea');
  ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.select();
  try { document.execCommand('copy'); } catch (e) { /* egal */ }
  document.body.removeChild(ta);
}

// ── Öffentliche Einstiegspunkte ──────────────────────────────────────────────
function initPipeline() {
  const wrap = document.getElementById('pipeline-wrap');
  const cv   = document.getElementById('pipeline-canvas');
  if (!wrap || !cv) return;
  if (!wrap._plInst) { wrap._plInst = _plCreate(wrap, cv, { logEl: document.getElementById('pipeline-log') }); }
  else { wrap._plInst.last = performance.now(); _plPollStatus(); _plPollLogs(); }
}

function initPipelinePreview() {
  const wrap = document.getElementById('home-pipeline-wrap');
  const cv   = document.getElementById('home-pipeline-canvas');
  if (!wrap || !cv) return;
  if (!wrap._plInst) { wrap._plInst = _plCreate(wrap, cv, { mini: true, logEl: document.getElementById('home-pipeline-log') }); }
  else { wrap._plInst.last = performance.now(); _plResize(wrap._plInst); _plPollStatus(); _plPollLogs(); }
}

function initPipelineStatus() {
  const wrap = document.getElementById('status-pipeline-wrap');
  const cv   = document.getElementById('status-pipeline-canvas');
  if (!wrap || !cv) return;
  const gate = () => { const p = document.getElementById('status-pipe-pop'); return !!p && p.classList.contains('show'); };
  if (!wrap._plInst) { wrap._plInst = _plCreate(wrap, cv, { mini: true, gate, logEl: document.getElementById('status-pipeline-log') }); }
  else { wrap._plInst.last = performance.now(); _plResize(wrap._plInst); _plPollStatus(); _plPollLogs(); }
}
