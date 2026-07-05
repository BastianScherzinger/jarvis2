'use strict';
/* ════════════════════════════════════════════════════════════════════════════
   JARVIS LeadHunter — LIVE-SYSTEM-PIPELINE  (v3, Mehrfach-Instanz)
   Ein 2D-Canvas-Hologramm des kompletten Lead-Flusses in Echtzeit:

     [ Internet-Scraper × N ] ─▶ [ JARVIS2-Roboter ] ─▶ [ Claude ] ─▶ [ Gmail ]

   • BUBBLES = echte Ereignisse:
       SSE `lead`      → Scraper ▶ Roboter   (grün „Lead")       — Rohlead gefunden
       SSE `evaluated` → Roboter ▶ Claude     (cyan „bewertet")   — KI-Bewertung fertig
       Δ Website live  → Claude ▶ Gmail        (gold „Website")    — Seite gebaut & online
       Δ Mail versandt → Claude ▶ Gmail        (violett „Mail")    — Angebot raus
   • ECHTE LOGS: die Live-Log-Konsole zieht den kompletten Ringpuffer ALLER Module
     (`/api/logs` → logger._buffer) und färbt jede Zeile nach Level. Jeder neue
     Log-Eintrag lässt ausserdem den zugehörigen Pipeline-Knoten aufleuchten
     (Scraper/Roboter/Claude/Gmail), Fehler blitzen rot — so sieht man wirklich,
     welcher Code-Block gerade arbeitet.

   Zwei Instanzen teilen dieselben Poller/Daten:
     initPipeline()         — grosse Ansicht im Graph-Tab (#pipeline-canvas + #pipeline-log)
     initPipelinePreview()  — Live-Mini-Vorschau auf der Startseite (#home-pipeline-canvas)

   Iron-Man-HUD (style.css-Tokens): Cyan #00d4ff, Grün #00e87a, additives Glühen.
   Performance: jede Instanz pausiert ihr Rendering, wenn ihre .page nicht aktiv ist;
   Poller fetchen nur, wenn mindestens eine Instanz sichtbar ist. prefers-reduced-motion
   dämpft die Bewegung.
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

const _PL_BUBBLE = {
  lead:    { color: '#00e87a', label: 'Lead',     seg: 's2r' },
  eval:    { color: '#00d4ff', label: 'bewertet', seg: 'r2c' },
  website: { color: '#ffc93d', label: 'Website',  seg: 'c2g' },
  mail:    { color: '#9b5de5', label: 'Mail',     seg: 'c2g' },
};
const _PL_SEG_DUR = { s2r: 1.15, r2c: 1.0, c2g: 1.15 };
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
  logLastTs: '',
  started: false, pollTimer: null, logTimer: null,
};
const _PL_INST = [];

function _plAnyVisible() { return _PL_INST.some(_plVisible); }
function _plVisible(P) {
  const pg = P.wrap.closest ? P.wrap.closest('.page') : null;
  return !!pg && pg.classList.contains('active') && !document.hidden;
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
        _plBurst('website', Math.min(8, Math.max(0, _D.stats.live - _D.prev.live)));
        _plBurst('mail',    Math.min(8, Math.max(0, _D.stats.sent - _D.prev.sent)));
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
    d.logs.forEach(e => {
      _D.logs.push(e);
      if (fresh) _plReactToLog(e);        // nur echte Neuzugänge lösen Effekte aus
    });
    if (_D.logs.length > 300) _D.logs.splice(0, _D.logs.length - 300);
    _D.logLastTs = d.last_ts || _D.logLastTs;
    _PL_INST.forEach(_plRenderLog);
  } catch (e) { /* still weiter */ }
}

function _plBurst(type, n) {
  if (n <= 0) return;
  for (let i = 0; i < n; i++) {
    setTimeout(() => _PL_INST.forEach(P => { if (_plVisible(P)) _plSpawn(P, type); }), i * 260);
  }
}

// ── Log-Klassifikation → welcher Knoten reagiert ─────────────────────────────
function _plClassifyLog(e) {
  const w = (e.worker || '').toLowerCase(), lv = e.level || '';
  for (const [kw, nm] of _PL_LOG_SCRAPER) if (w.includes(kw)) return { stage: 'scraper', scraper: nm };
  if (lv === 'SCRAPE') return { stage: 'scraper', scraper: null };
  if (lv === 'EVAL' || /eval|bewert|score|analyst|social|ollama/.test(w)) return { stage: 'eval' };
  if (/autobuild|makeover|builder|website|railway|deploy|hero|github/.test(w)) return { stage: 'build' };
  if (/mailer|offer|discord|inbox|versand|smtp|mail/.test(w)) return { stage: 'mail' };
  if (/leadcollector|collector|controller/.test(w)) return { stage: 'lead' };
  return { stage: null };
}

function _plReactToLog(e) {
  const c = _plClassifyLog(e);
  const err = e.level === 'ERROR';
  _PL_INST.forEach(P => {
    if (!_plVisible(P)) return;
    const hit = (node) => { if (!node) return; node.pulse = 1; if (err) node.err = 1; };
    if (c.stage === 'scraper') {
      const idx = c.scraper ? _D.scrapers.findIndex(s => s.name === c.scraper) : -1;
      if (idx >= 0 && P.scr[idx]) hit(P.scr[idx]); else hit(P.robot);
    } else if (c.stage === 'eval') { hit(P.robot); hit(P.claude); }
    else if (c.stage === 'build')  { hit(P.claude); }
    else if (c.stage === 'mail')   { hit(P.gmail); }
    else if (c.stage === 'lead')   { hit(P.robot); }
  });
}

// ── Instanz erzeugen ─────────────────────────────────────────────────────────
function _plCreate(wrap, cv, opts) {
  const P = {
    wrap, cv, ctx: cv.getContext('2d'), opts: opts || {},
    mini: !!(opts && opts.mini), logEl: (opts && opts.logEl) || null,
    W: 0, H: 0, dpr: 1, t: 0, last: performance.now(), raf: 0,
    scr: _D.scrapers.map(() => ({ x: 0, y: 0, cx: 0, cy: 0, pulse: 0, err: 0 })),
    robot:  { x: 0, y: 0, pulse: 0, err: 0 },
    claude: { x: 0, y: 0, pulse: 0, err: 0 },
    gmail:  { x: 0, y: 0, pulse: 0, err: 0 },
    bubbles: [], seg: { s2r: 0, r2c: 0, c2g: 0 },
  };
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
}

function _plLayout(P) {
  const W = P.W, H = P.H, cy = H * 0.5;
  const flowW = P.mini ? W : W * 0.67;     // grosse Ansicht: rechts Platz für die Log-Konsole
  const rx = flowW * 0.44, cx = flowW * 0.70, gx = flowW * 0.92;
  P.robot.x = rx; P.robot.y = cy;
  P.claude.x = cx; P.claude.y = cy;
  P.gmail.x = gx; P.gmail.y = cy;
  const sx = flowW * 0.13, n = P.scr.length;
  const top = P.mini ? H * 0.14 : H * 0.11, bot = P.mini ? H * 0.86 : H * 0.82;
  const span = bot - top;
  P.scr.forEach((s, i) => {
    s.x = sx; s.y = n > 1 ? top + span * (i / (n - 1)) : cy;
    s.cx = s.x * 0.30 + rx * 0.70; s.cy = s.y * 0.45 + cy * 0.55;
  });
  P.nodeR = P.mini ? Math.max(7, Math.min(13, H * 0.05))  : Math.max(15, Math.min(24, W * 0.021));
  P.hubR  = P.mini ? Math.max(12, Math.min(20, H * 0.085)) : Math.max(26, Math.min(40, W * 0.034));
}

// ── Bubble spawnen ───────────────────────────────────────────────────────────
function _plSpawn(P, type, scraperIdx) {
  const def = _PL_BUBBLE[type]; if (!def) return;
  let from, to, cx, cy;
  if (def.seg === 's2r') {
    let idx = (typeof scraperIdx === 'number') ? scraperIdx : Math.floor(Math.random() * P.scr.length);
    const s = P.scr[idx]; if (!s) return;
    s.pulse = 1;
    from = { x: s.x, y: s.y }; to = { x: P.robot.x, y: P.robot.y }; cx = s.cx; cy = s.cy;
  } else if (def.seg === 'r2c') {
    P.robot.pulse = 1;
    from = { x: P.robot.x, y: P.robot.y }; to = { x: P.claude.x, y: P.claude.y };
    cx = (from.x + to.x) / 2; cy = from.y - P.H * 0.04;
  } else {
    P.claude.pulse = 1;
    from = { x: P.claude.x, y: P.claude.y }; to = { x: P.gmail.x, y: P.gmail.y };
    cx = (from.x + to.x) / 2; cy = from.y - P.H * 0.04;
  }
  P.bubbles.push({
    type, seg: def.seg, color: def.color, label: def.label, from, to, cx, cy,
    t: 0, dur: _PL_SEG_DUR[def.seg] * (0.9 + Math.random() * 0.2),
    r: (def.seg === 's2r' ? 5.5 : 6.5) * (P.mini ? 0.62 : 1),
  });
  if (P.bubbles.length > 140) P.bubbles.splice(0, P.bubbles.length - 140);
}

// Öffentlicher Hook aus app.js (_connectSSE) — an ALLE sichtbaren Instanzen
function pipelineOnEvent(kind, data) {
  _PL_INST.forEach(P => {
    if (!_plVisible(P)) return;
    if (kind === 'lead') {
      const idx = _plScraperIdxFor(data && data.finder);
      _plSpawn(P, 'lead', idx);
      if (idx >= 0) _D.scrapers[idx].count++;
    } else if (kind === 'evaluated') {
      _plSpawn(P, 'eval');
    }
  });
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
function _plRenderHud(P) {
  if (P.mini) { const l = P.wrap.parentElement && P.wrap.parentElement.querySelector('.hpp-live-count');
    if (l) l.textContent = `${_D.stats.active}/${_D.scrapers.length} aktiv · ${_D.stats.live} live`; return; }
  const el = document.getElementById('pipeline-hud'); if (!el) return;
  const s = _D.stats;
  const dot = (c) => `<span class="ph-dot" style="background:${c};box-shadow:0 0 7px ${c}"></span>`;
  el.innerHTML =
    `<span class="ph-chip">${dot(s.running ? '#00e87a' : '#ff3b4e')}Scraper <b>${s.active}/${_D.scrapers.length}</b></span>` +
    `<span class="ph-chip">${dot('#00e87a')}Leads <b>${(s.total).toLocaleString('de-DE')}</b></span>` +
    `<span class="ph-chip">${dot('#ffc93d')}Websites live <b>${s.live}</b></span>` +
    (s.building ? `<span class="ph-chip">${dot('#00d4ff')}im Bau <b>${s.building}</b></span>` : '') +
    `<span class="ph-chip">${dot('#9b5de5')}Mails raus <b>${s.sent}</b></span>`;
  const lg = document.getElementById('pipeline-legend');
  if (lg && !lg.dataset.done) {
    const item = (c, t) => `<span class="plg"><span class="plg-dot" style="background:${c};box-shadow:0 0 7px ${c}"></span>${t}</span>`;
    lg.innerHTML = item('#00e87a', 'Lead') + item('#00d4ff', 'bewertet') +
                   item('#ffc93d', 'Website') + item('#9b5de5', 'Angebot');
    lg.dataset.done = '1';
  }
}

function _plEsc(s) { return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

function _plRenderLog(P) {
  const el = P.logEl || (P.mini ? null : document.getElementById('pipeline-log'));
  if (!el) return;
  const nMax = P.mini ? 6 : 26;
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
    P.seg[b.seg] = Math.min(1, P.seg[b.seg] + dt * 1.6);
    if (b.t >= 1) {
      if (b.seg === 's2r') P.robot.pulse = 1;
      else if (b.seg === 'r2c') P.claude.pulse = 1;
      else P.gmail.pulse = 1;
      P.bubbles.splice(i, 1);
    }
  }
  const dec = dt * 1.7, decE = dt * 1.2;
  [P.robot, P.claude, P.gmail, ...P.scr].forEach(nd => {
    nd.pulse = Math.max(0, nd.pulse - dec);
    nd.err = Math.max(0, (nd.err || 0) - decE);
  });
  P.seg.s2r = Math.max(0, P.seg.s2r - dt * 0.5);
  P.seg.r2c = Math.max(0, P.seg.r2c - dt * 0.5);
  P.seg.c2g = Math.max(0, P.seg.c2g - dt * 0.5);
}

function _plPos(b) {
  const t = b.t, u = 1 - t;
  return { x: u * u * b.from.x + 2 * u * t * b.cx + t * t * b.to.x,
           y: u * u * b.from.y + 2 * u * t * b.cy + t * t * b.to.y };
}

function _plDraw(P) {
  const ctx = P.ctx, W = P.W, H = P.H;
  ctx.clearRect(0, 0, W, H);

  P.scr.forEach((s, i) => {
    const alive = _D.scrapers[i].alive;
    const energy = P.seg.s2r * (alive ? 1 : 0.35);
    _plPipe(P, s.x, s.y, P.robot.x, P.robot.y, s.cx, s.cy,
            alive ? '#00e87a' : '#2a4058', 0.10 + energy * 0.5, P.nodeR * 0.5);
  });
  _plPipe(P, P.robot.x, P.robot.y, P.claude.x, P.claude.y,
          (P.robot.x + P.claude.x) / 2, P.robot.y - H * 0.04, '#00d4ff', 0.16 + P.seg.r2c * 0.5, P.hubR * 0.42);
  _plPipe(P, P.claude.x, P.claude.y, P.gmail.x, P.gmail.y,
          (P.claude.x + P.gmail.x) / 2, P.claude.y - H * 0.04, '#9b5de5', 0.16 + P.seg.c2g * 0.5, P.hubR * 0.42);

  ctx.globalCompositeOperation = 'lighter';
  for (const b of P.bubbles) { const p = _plPos(b); _plGlowDot(P, p.x, p.y, b.r, b.color); }
  ctx.globalCompositeOperation = 'source-over';

  if (!P.mini) {
    ctx.font = '600 9px JetBrains Mono, monospace'; ctx.textAlign = 'center';
    for (const b of P.bubbles) {
      if (b.t < 0.18 || b.t > 0.9) continue;
      const p = _plPos(b);
      ctx.globalAlpha = 0.7; ctx.fillStyle = b.color;
      ctx.fillText(b.label, p.x, p.y - b.r - 5); ctx.globalAlpha = 1;
    }
  }

  P.scr.forEach((s, i) => _plDrawScraper(P, s, _D.scrapers[i]));
  _plDrawRobot(P, P.robot);
  _plDrawClaude(P, P.claude);
  _plDrawGmail(P, P.gmail);
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
  if (P.mini && !text) return;
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

function _plDrawRobot(P, node) {
  const ctx = P.ctx, R = P.hubR;
  _plPulseRing(P, node, R, '#00d4ff');
  const g = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, R * 2.1);
  g.addColorStop(0, _plAlpha('#00d4ff', 0.28 + node.pulse * 0.25)); g.addColorStop(1, _plAlpha('#00d4ff', 0));
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(node.x, node.y, R * 2.1, 0, Math.PI * 2); ctx.fill();
  ctx.save(); ctx.translate(node.x, node.y);
  const hw = R * 0.92, hh = R * 0.8, rad = R * 0.18;
  _plRoundRect(P, -hw, -hh, hw * 2, hh * 2, rad);
  ctx.fillStyle = 'rgba(8,20,30,.95)'; ctx.fill();
  ctx.lineWidth = 2; ctx.strokeStyle = '#00d4ff'; ctx.globalAlpha = 0.95; ctx.stroke(); ctx.globalAlpha = 1;
  ctx.beginPath(); ctx.moveTo(0, -hh); ctx.lineTo(0, -hh - R * 0.35); ctx.stroke();
  ctx.beginPath(); ctx.arc(0, -hh - R * 0.35, R * 0.07 + 1.4, 0, Math.PI * 2);
  ctx.fillStyle = '#00e87a'; ctx.shadowColor = '#00e87a'; ctx.shadowBlur = 8; ctx.fill(); ctx.shadowBlur = 0;
  const blink = 0.6 + 0.4 * Math.abs(Math.sin(P.t * 1.5));
  ctx.fillStyle = _plAlpha('#00d4ff', blink);
  const ew = R * 0.26, eh = R * 0.2, eo = R * 0.34;
  _plRoundRect(P, -eo - ew / 2, -eh / 2, ew, eh, 3); ctx.fill();
  _plRoundRect(P, eo - ew / 2, -eh / 2, ew, eh, 3); ctx.fill();
  ctx.strokeStyle = _plAlpha('#00d4ff', 0.5); ctx.lineWidth = 1;
  for (let i = -2; i <= 2; i++) { ctx.beginPath(); ctx.moveTo(i * R * 0.1, hh * 0.42); ctx.lineTo(i * R * 0.1, hh * 0.62); ctx.stroke(); }
  ctx.restore();
  _plNodeLabel(P, node.x, node.y + R + 15, 'JARVIS2', '#33e0ff', 'Kern');
}

function _plDrawClaude(P, node) {
  const ctx = P.ctx, R = P.hubR, CL = '#d97757';
  _plPulseRing(P, node, R, CL);
  const g = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, R * 2.1);
  g.addColorStop(0, _plAlpha(CL, 0.26 + node.pulse * 0.25)); g.addColorStop(1, _plAlpha(CL, 0));
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(node.x, node.y, R * 2.1, 0, Math.PI * 2); ctx.fill();
  ctx.save(); ctx.translate(node.x, node.y);
  ctx.beginPath(); ctx.arc(0, 0, R * 0.92, 0, Math.PI * 2);
  ctx.fillStyle = 'rgba(24,14,10,.95)'; ctx.fill();
  ctx.lineWidth = 2; ctx.strokeStyle = CL; ctx.globalAlpha = 0.9; ctx.stroke(); ctx.globalAlpha = 1;
  const rays = 12, rot = _PL_REDUCED ? 0 : P.t * 0.35;
  ctx.strokeStyle = CL; ctx.lineCap = 'round';
  for (let i = 0; i < rays; i++) {
    const a = rot + (i / rays) * Math.PI * 2, inner = R * 0.2, outer = R * (0.62 + 0.12 * (i % 2));
    ctx.globalAlpha = 0.85; ctx.lineWidth = P.mini ? 1.4 : 2.1;
    ctx.beginPath(); ctx.moveTo(Math.cos(a) * inner, Math.sin(a) * inner); ctx.lineTo(Math.cos(a) * outer, Math.sin(a) * outer); ctx.stroke();
  }
  ctx.globalAlpha = 1;
  ctx.beginPath(); ctx.arc(0, 0, R * 0.17, 0, Math.PI * 2);
  ctx.fillStyle = '#ffece3'; ctx.shadowColor = CL; ctx.shadowBlur = 10; ctx.fill(); ctx.shadowBlur = 0;
  ctx.restore();
  _plNodeLabel(P, node.x, node.y + R + 15, 'CLAUDE', '#e79a80', 'Bewertung + Bau');
}

function _plDrawGmail(P, node) {
  const ctx = P.ctx, R = P.hubR, EC = '#ffc93d';
  _plPulseRing(P, node, R, EC);
  const g = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, R * 2.1);
  g.addColorStop(0, _plAlpha(EC, 0.24 + node.pulse * 0.28)); g.addColorStop(1, _plAlpha(EC, 0));
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(node.x, node.y, R * 2.1, 0, Math.PI * 2); ctx.fill();
  ctx.save(); ctx.translate(node.x, node.y);
  const w = R * 1.25, h = R * 0.86;
  _plRoundRect(P, -w / 2, -h / 2, w, h, R * 0.14);
  ctx.fillStyle = 'rgba(26,20,6,.95)'; ctx.fill();
  ctx.lineWidth = 2; ctx.strokeStyle = EC; ctx.globalAlpha = 0.95; ctx.stroke();
  ctx.globalAlpha = 0.9; ctx.lineWidth = 1.6;
  ctx.beginPath(); ctx.moveTo(-w / 2, -h / 2); ctx.lineTo(0, h * 0.12); ctx.lineTo(w / 2, -h / 2); ctx.stroke();
  ctx.globalAlpha = 1; ctx.restore();
  _plNodeLabel(P, node.x, node.y + R + 15, 'VERSAND', '#ffd873', 'Gmail');
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
