'use strict';
/* ── JARVIS LeadHunter ─────────────────────────────────────────────────────── */

// ── State ─────────────────────────────────────────────────────────────────────
let _running        = false;
let _sse            = null;
let _feedCount      = 0;
let _allLeads       = [];   // Session-Cache für Sphere + Filter
let _sessionFinder  = {};   // {finder: count} nur Session
let _evalRankTimer  = null; // Debounce für Ranking-Reload nach evaluated-Event
let _sessionStartTs = 0;    // Start-Zeitpunkt des laufenden Sammel-Laufs (für Funde/h)
let _startMetaTimer = null;

// ── Finder-Registry ───────────────────────────────────────────────────────────
const F = {
  maps_playwright: { cls:'maps',   av:'M',  lbl:'Google Maps',   icon:'🗺',  sub:'Playwright'},
  gelbe_seiten:    { cls:'gelbe',  av:'GS', lbl:'Gelbe Seiten',  icon:'📒',  sub:'HTTP'},
  dasoertliche:    { cls:'oert',   av:'DÖ', lbl:'Das Örtliche',  icon:'📘',  sub:'HTTP'},
  elfacht:         { cls:'elf',    av:'11', lbl:'11880',         icon:'📞',  sub:'HTTP'},
  golocal:         { cls:'glc',    av:'GL', lbl:'golocal',       icon:'⭐',  sub:'HTTP'},
  ollama_ai:       { cls:'ollama', av:'AI', lbl:'Lokale KI',     icon:'🤖',  sub:'Ollama'},
};
function fi(key){ return F[key] || {cls:'maps',av:'?',lbl:key||'?',icon:'?',sub:''}; }

// ── Arc-Reactor Animation (Topbar) ─────────────────────────────────────────
(function initArc(){
  const cv = document.getElementById('arc-canvas');
  if(!cv) return;
  const cx = cv.getContext('2d');
  let angle = 0;
  function draw(){
    cx.clearRect(0,0,32,32);
    const x=16,y=16;
    // Outer ring
    cx.strokeStyle='rgba(0,212,255,.25)';cx.lineWidth=1.5;
    cx.beginPath();cx.arc(x,y,13,0,Math.PI*2);cx.stroke();
    // Middle ring
    cx.strokeStyle='rgba(0,212,255,.5)';cx.lineWidth=1.2;
    cx.beginPath();cx.arc(x,y,8,0,Math.PI*2);cx.stroke();
    // Rotating arc
    cx.strokeStyle='#00d4ff';cx.lineWidth=2;
    cx.beginPath();cx.arc(x,y,11,angle,angle+1.2);cx.stroke();
    // Core
    cx.fillStyle='#00d4ff';cx.beginPath();cx.arc(x,y,3,0,Math.PI*2);cx.fill();
    cx.fillStyle='rgba(0,212,255,.3)';cx.beginPath();cx.arc(x,y,5,0,Math.PI*2);cx.fill();
    angle += 0.05;
    requestAnimationFrame(draw);
  }
  draw();
})();

// ── Start / Stop ──────────────────────────────────────────────────────────────
function toggleScraper(){ _running ? stopScraper() : startScraper(); }

async function startScraper(){
  const res  = await fetch('/api/start',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  const data = await res.json();
  if(!data.ok && data.reason !== 'already_running') return;
  _running = true;
  _setUI(true);
  _connectSSE();
}

async function stopScraper(){
  await fetch('/api/stop',{method:'POST'});
  _running = false;
  _setUI(false);
  if(_sse){_sse.close();_sse=null;}
}

function _setUI(on){
  document.getElementById('start-btn').className = 'start-btn' + (on?' run':'');
  document.getElementById('si').textContent       = on ? '■' : '▶';
  document.getElementById('st').textContent       = on ? 'STOP' : 'START';
  const ind = document.getElementById('live-ind');
  ind.classList.toggle('on', on);
  document.getElementById('live-lbl').textContent = on ? 'LIVE' : 'OFFLINE';

  if(on){
    if(!_sessionStartTs) _sessionStartTs = Date.now();
    if(!_startMetaTimer) _startMetaTimer = setInterval(_updateStartMeta, 5000);
    _updateStartMeta();
  } else {
    _sessionStartTs = 0;
    if(_startMetaTimer){ clearInterval(_startMetaTimer); _startMetaTimer = null; }
  }
  _updateStartMetaVisibility();
  _autoPoll();   // /api/start + /api/stop steuern den Auto-Builder mit — Anzeige sofort nachziehen
}

// start-meta bleibt sichtbar, solange IRGENDEIN Teil der Pipeline läuft (Scraper ODER
// Auto-Builder) — beide werden vom selben Knopf gesteuert, können aber kurz auseinanderlaufen
// (z.B. der Builder braucht noch einen Moment für seinen letzten Schritt beim Stoppen).
function _updateStartMetaVisibility(){
  const meta = document.getElementById('start-meta');
  if(meta) meta.classList.toggle('show', _running || _autoOn);
}

// Funde/h + aktive Worker im Start-Button-Cluster (ergänzt _limitPoll, kein Extra-Fetch).
function _updateStartMeta(){
  const rateEl = document.getElementById('start-rate');
  if(!rateEl) return;
  const minutes = _sessionStartTs ? (Date.now() - _sessionStartTs) / 60000 : 0;
  if(minutes < 2){
    // Anlaufphase: eine Hochrechnung aus <2 Min. Laufzeit wäre stark verrauscht
    // (wenige Funde × 30 hochgerechnet auf 1h) — erst absolute Zahl zeigen.
    rateEl.textContent = `${_feedCount} Funde`;
  } else {
    rateEl.textContent = `${Math.round(_feedCount / (minutes / 60))} Funde/h`;
  }
}

function _updateWorkerMeta(workers){
  const el = document.getElementById('start-workers');
  if(!el || !Array.isArray(workers)) return;
  const alive = workers.filter(w => w.alive).length;
  el.textContent = `${alive}/${workers.length || 6} Worker`;
}

// ── SSE ───────────────────────────────────────────────────────────────────────
function _connectSSE(){
  if(_sse) _sse.close();
  _sse = new EventSource('/api/stream');
  _sse.onmessage = e => {
    try{
      const msg = JSON.parse(e.data);
      if(msg.type==='lead')       { _onLead(msg.data); _applyStats(msg.stats); }
      if(msg.type==='verified')   { _onVerified(msg.data); _applyStats(msg.stats); }
      if(msg.type==='stats')      { _applyStats(msg.stats); }
      if(msg.type==='init_stats') { _applyStats(msg.stats); }
      if(msg.type==='activity')   { _onActivity(msg.msg); }
      if(msg.type==='error')      { _onErr(msg.msg); }
      if(msg.type==='evaluated'){
        // Ranking und Graph sofort aktualisieren (debounced — 600ms)
        clearTimeout(_evalRankTimer);
        _evalRankTimer = setTimeout(() => {
          if(typeof rankReload === 'function') rankReload();
          if(typeof _updateStatBar === 'function') _updateStatBar();
        }, 600);
      }
    }catch{}
  };
  _sse.onerror = () => { if(_running) setTimeout(_connectSSE,3000); };
}

// ── Stats (DB ist einzige Quelle der Wahrheit) ────────────────────────────────
function _applyStats(s){
  if(!s) return;
  _setNum('s-total', s.total);
  _setNum('s-hot',   s.hot);
  _setNum('s-warm',  s.warm);
  _setNum('s-cold',  s.cold);
  const pct = s.total ? Math.round(s.no_web/s.total*100) : 0;
  const noWebEl = document.getElementById('s-noweb');
  if(noWebEl) noWebEl.textContent = pct+'%';
  // Telefon aus Session zählen
  const telEl = document.getElementById('s-tel');
  if(telEl) telEl.textContent = _allLeads.filter(l=>l.telefon).length;
}

function _setNum(id, val){
  const el = document.getElementById(id);
  if(!el) return;
  const old = parseInt(el.textContent)||0;
  if(old !== val) el.textContent = val;
}

// ── Lead empfangen ────────────────────────────────────────────────────────────
// Kein Live-Feed mehr (Mein Status zeigt stattdessen die Top-25-Rangliste +
// eingebettetes Log) — diese Funktion pflegt nur noch die Datengrundlage für
// Stats/Graph/Rate.
function _onLead(lead){
  _allLeads.unshift(lead);
  _feedCount++;
  _sessionFinder[lead.finder] = (_sessionFinder[lead.finder]||0) + 1;

  // Graph Live-Update
  if(typeof graphOnNewLead === 'function') graphOnNewLead(lead);
}

function _onErr(msg){
  if(!msg) return;
  const el = document.getElementById('ticker-text');
  if(!el) return;
  el.textContent = '⚠ ' + msg;
  el.classList.remove('tk-fade');
  void el.offsetWidth;   // Reflow → Animation neu starten
  el.classList.add('tk-fade');
}

// ── Activity-Ticker ────────────────────────────────────────────────────────────
function _onActivity(msg){
  const el = document.getElementById('ticker-text');
  if(!el || !msg) return;
  el.textContent = '▸ ' + msg;
  el.classList.remove('tk-fade');
  void el.offsetWidth;   // Reflow → Animation neu starten
  el.classList.add('tk-fade');
}

function _e(s){ return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

// JSON sicher in ein single-quote-onclick-Attribut einbetten (gescrapte Daten
// können ', ", <, > enthalten — sonst Ausbruch aus dem Attribut = XSS).
function _jattr(o){
  return JSON.stringify(o)
    .replace(/&/g,'&amp;').replace(/'/g,'&#39;').replace(/"/g,'&quot;')
    .replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function _onVerified(lead){
  if(!lead) return;
  const i = _allLeads.findIndex(l => l.id === lead.id);
  if(i >= 0) _allLeads[i] = Object.assign({}, _allLeads[i], lead);
}

// ── Verifier-Modell ─────────────────────────────────────────────────────────
async function loadVerifierModel(){
  let d;
  try{ d = await(await fetch('/api/verifier/model')).json(); }catch{ return; }
  const sel = document.getElementById('verifier-model');
  if(!sel) return;
  const avail = d.available || [];
  const cur   = d.model || '';
  const opts  = avail.length
    ? avail.map(m => `<option value="${_e(m.name)}"${m.name===cur?' selected':''}>${_e(m.name)} (${m.size_gb}G)</option>`).join('')
    : `<option value="${_e(cur)}" selected>${_e(cur||'kein Modell')}</option>`;
  sel.innerHTML = opts;
}

async function setVerifierModel(){
  const sel = document.getElementById('verifier-model');
  if(!sel || !sel.value) return;
  try{
    await fetch('/api/verifier/model',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({model: sel.value}),
    });
  }catch{}
}


// ── Modal ─────────────────────────────────────────────────────────────────────
let _modalLead = null;

function _parseJSON(raw, fallback){
  if(raw==null) return fallback;
  if(typeof raw !== 'string') return raw;
  try{ return JSON.parse(raw); }catch{ return fallback; }
}

function openModal(lead){
  _modalLead = lead;
  const f=fi(lead.finder);
  const webRow=lead.has_website
    ?`<div class="m-row"><span class="m-k">Website</span><span class="m-v warn"><a href="${_e(lead.website_url)}" target="_blank">${_e(lead.website_url||'Link')} ↗</a></span></div>
      <div class="m-row"><span class="m-k">Alter</span><span class="m-v ${lead.website_alter>5?'warn':''}">${lead.website_alter>=0?lead.website_alter+' Jahre':'unbekannt'}</span></div>`
    :`<div class="m-row"><span class="m-k">Website</span><span class="m-v no">❌ Kein Website</span></div>`;

  document.getElementById('modal-inner').innerHTML=`
    <div class="m-hdr">
      <div class="m-badge ${lead.lead_typ}">${lead.lead_typ}</div>
      <div class="m-title">${_e(lead.name)}</div>
      <button class="m-close" onclick="closeModal()">✕</button>
    </div>
    <div class="m-score-row">
      <span style="font-size:10px;color:var(--tx2)">Score</span>
      <div class="m-bar"><div class="m-fill ${lead.lead_typ}" style="width:${lead.score}%"></div></div>
      <span class="m-score-num ${lead.lead_typ}">${lead.score}</span>
    </div>
    <div class="m-sec">
      <div class="m-sec-t">Kontakt</div>
      ${lead.adresse?`<div class="m-row"><span class="m-k">Adresse</span><span class="m-v">${_e(lead.adresse)}</span></div>`:''}
      ${lead.telefon?`<div class="m-row"><span class="m-k">Telefon</span><span class="m-v ok">${_e(lead.telefon)}</span></div>`:''}
      <div class="m-row"><span class="m-k">Stadt</span><span class="m-v">${_e(lead.stadt||'')} · ${_e(lead.bundesland||'')}</span></div>
      <div class="m-row"><span class="m-k">Branche</span><span class="m-v">${_e(lead.branche||'—')}</span></div>
    </div>
    <div class="m-sec">
      <div class="m-sec-t">Online-Präsenz</div>
      ${webRow}
      <div class="m-row"><span class="m-k">Bilder</span><span class="m-v ${lead.bilder?'ok':'no'}">${lead.bilder?'✓ Ja':'✗ Nein'}</span></div>
    </div>
    ${lead.bewertung?`<div class="m-sec">
      <div class="m-sec-t">Bewertung</div>
      <div class="m-row"><span class="m-k">Sterne</span><span class="m-v">⭐ ${lead.bewertung}</span></div>
      ${lead.anz_bewertungen?`<div class="m-row"><span class="m-k">Anzahl</span><span class="m-v">${lead.anz_bewertungen}</span></div>`:''}
      ${lead.maps_url?`<div class="m-row"><span class="m-k">Maps</span><span class="m-v"><a href="${_e(lead.maps_url)}" target="_blank">Öffnen ↗</a></span></div>`:''}
    </div>`:''}
    <div class="m-sec">
      <div class="m-sec-t">Quelle</div>
      <div class="m-finder src-${f.cls}" style="display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:8px;border:1px solid var(--bdr2);background:var(--bg3)">
        <span style="font-size:20px">${f.icon}</span>
        <div>
          <div class="m-finder-name src-${f.cls}" style="font-size:12px;font-weight:600">${f.lbl}</div>
          <div class="m-finder-sub">${f.sub} · ${lead.gefunden_am||'—'}</div>
        </div>
      </div>
    </div>
    ${_modalExtras(lead)}
    ${_modalActions(lead)}`;
  document.getElementById('modal-bg').classList.add('open');
  document.getElementById('modal').classList.add('open');
  _loadCompetition(lead.id);
}

// ── Modal: optionale Sektionen ──────────────────────────────────────────────
function _modalExtras(lead){
  let html = '';

  // Pitch-Hook
  if(lead.pitch_hook){
    html += `<div class="m-sec"><div class="m-sec-t">Pitch-Hook</div>
      <div class="m-pitch">${_e(lead.pitch_hook)}</div></div>`;
  }

  // Website-Probleme
  const issues = _parseJSON(lead.website_issues, []);
  if(Array.isArray(issues) && issues.length){
    html += `<div class="m-sec"><div class="m-sec-t">Website-Probleme</div>
      <ul class="m-issues">${issues.map(i=>`<li>${_e(String(i))}</li>`).join('')}</ul></div>`;
  }

  // Social Media
  const social = _parseJSON(lead.social_media, {});
  if(social && typeof social === 'object' && Object.keys(social).length){
    const pills = Object.entries(social).filter(([,v])=>v).map(([k,v])=>{
      const url = String(v);
      const href = url.startsWith('http') ? url : 'https://'+url;
      return `<a class="m-social-pill" href="${_e(href)}" target="_blank">${_e(k)} ↗</a>`;
    }).join('');
    if(pills) html += `<div class="m-sec"><div class="m-sec-t">Social Media</div>
      <div class="m-social">${pills}</div></div>`;
  }

  return html;
}

// ── Modal: Aktions-Leiste ───────────────────────────────────────────────────
function _modalActions(lead){
  const cur = lead.status || 'neu';
  const opt = (v,l)=>`<option value="${v}"${cur===v?' selected':''}>${l}</option>`;
  return `<div class="m-sec m-actions">
    <div class="m-sec-t">Aktionen</div>
    <div class="m-comp" id="m-comp">…</div>
    <div class="m-act-row">
      <select class="m-status-sel" id="m-status" onchange="setLeadStatus(${lead.id})">
        ${opt('neu','● Neu')}${opt('kontaktiert','● Kontaktiert')}${opt('termin','● Termin')}${opt('verkauft','● Verkauft')}${opt('tot','● Tot')}
      </select>
    </div>
    <div class="m-act-row">
      <button class="m-act-btn" id="m-email-btn" onclick="genEmail(${lead.id})">✉ E-Mail-Entwurf</button>
      <button class="m-act-btn" id="m-mockup-btn" onclick="genMockup(${lead.id})">🎨 Website-Mockup</button>
    </div>
    <div class="m-act-row">
      <button class="m-act-btn m-web-btn" id="m-web-btn" onclick="buildWebsite(${lead.id})">🌐 Webseite bauen &amp; live stellen</button>
    </div>
    <div class="m-email-out" id="m-email-out" style="display:none"></div>
    <div class="m-mockup-out" id="m-mockup-out" style="display:none"></div>
    <div class="m-web-out" id="m-web-out" style="display:none"></div>
  </div>`;
}

async function setLeadStatus(id){
  const sel = document.getElementById('m-status');
  if(!sel) return;
  try{
    await fetch(`/api/lead/${id}/status`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({status: sel.value}),
    });
    const l = _allLeads.find(x=>x.id===id);
    if(l) l.status = sel.value;
  }catch{}
}

async function _loadCompetition(id){
  const el = document.getElementById('m-comp');
  if(!el || !id) return;
  try{
    const d = await(await fetch(`/api/lead/${id}/competition`)).json();
    const l = _modalLead || {};
    if(d.gesamt > 0){
      el.innerHTML = `<span class="m-comp-badge">${d.ohne_website} von ${d.gesamt} ${_e(l.branche||'Betriebe')}-Betrieben in ${_e(l.stadt||'')} ohne Website (${d.prozent_ohne}%)</span>`;
    }else{
      el.style.display = 'none';
    }
  }catch{ el.style.display='none'; }
}

async function genEmail(id){
  const btn = document.getElementById('m-email-btn');
  const out = document.getElementById('m-email-out');
  if(!btn || !out) return;
  btn.disabled = true;
  out.style.display = 'block';
  out.innerHTML = `<div class="m-spin-row"><span class="jc-spin"></span><span>E-Mail wird generiert…</span></div>`;
  try{
    const d = await(await fetch(`/api/lead/${id}/email`, {method:'POST'})).json();
    if(d.error || (!d.betreff && !d.text)){
      out.innerHTML = `<div class="m-err-row">✕ ${_e(d.error||'Fehler')}</div>`;
    }else{
      const full = (d.betreff?('Betreff: '+d.betreff+'\n\n'):'') + (d.text||'');
      out.innerHTML = `
        <div class="m-email-sub">${_e(d.betreff||'')}</div>
        <textarea class="m-email-txt" id="m-email-txt" readonly>${_e(d.text||'')}</textarea>
        <button class="m-copy-btn" onclick="_copyEmail(this)" data-full="${_e(full)}">⧉ Kopieren</button>`;
    }
  }catch(e){ out.innerHTML = `<div class="m-err-row">✕ ${_e(String(e))}</div>`; }
  finally{ btn.disabled = false; }
}

function _copyEmail(btn){
  const txt = btn.getAttribute('data-full') || '';
  navigator.clipboard.writeText(txt).then(()=>{
    btn.textContent = '✓ Kopiert';
    setTimeout(()=>{ btn.textContent = '⧉ Kopieren'; }, 2000);
  }).catch(()=>{});
}

async function genMockup(id){
  const btn = document.getElementById('m-mockup-btn');
  const out = document.getElementById('m-mockup-out');
  if(!btn || !out) return;
  btn.disabled = true;
  out.style.display = 'block';
  out.innerHTML = `<div class="m-spin-row"><span class="jc-spin"></span><span>Mockup wird generiert…</span></div>`;
  try{
    const d = await(await fetch(`/api/lead/${id}/mockup`, {method:'POST'})).json();
    if(d.ok && d.job_id) _pollMockup(d.job_id, out, btn);
    else { out.innerHTML = `<div class="m-err-row">✕ ${_e(d.reason||'Fehler')}</div>`; btn.disabled=false; }
  }catch(e){ out.innerHTML = `<div class="m-err-row">✕ ${_e(String(e))}</div>`; btn.disabled=false; }
}

function _pollMockup(jobId, out, btn){
  let elapsed = 0;
  const iv = setInterval(async ()=>{
    let job;
    try{ job = await(await fetch('/api/media/job/'+jobId)).json(); }
    catch{ return; }
    if(job.status === 'done'){
      clearInterval(iv);
      out.innerHTML = `<img class="m-mockup-img" src="${_e(job.result_url)}" alt="Mockup"/>`;
      btn.disabled = false;
    }else if(job.status === 'error'){
      clearInterval(iv);
      out.innerHTML = `<div class="m-err-row">✕ ${_e(job.error||'Fehler')}</div>`;
      btn.disabled = false;
    }else{
      elapsed += 1.5;
      out.innerHTML = `<div class="m-spin-row"><span class="jc-spin"></span><span>Mockup wird generiert… ${Math.round(elapsed)}s</span></div>`;
    }
  }, 1500);
}
// ── Webseite bauen & live stellen ────────────────────────────────────────────
// Fragt EINMAL (nur wenn Higgsfield konfiguriert ist), ob der Hero über die Cloud
// erzeugt werden soll. Lokal bleibt der bewährte Standard.
let _hfConfigured = null;
let _hfMcpConfigured = null;      // Higgsfield via MCP/Abo angemeldet? (nutzt Abo-Credits)
let _openaiConfigured = null;     // ChatGPT-Bilder verfügbar? (OPENAI_API_KEY gesetzt)
let _mediaMode = 'image';         // aktueller Medien-Modus: 'image' | 'video'

// Medien-Studio: zwischen Bild- und Video-Modus umschalten.
function setMediaMode(mode){
  _mediaMode = (mode === 'video') ? 'video' : 'image';
  const img = document.getElementById('media-mode-image');
  const vid = document.getElementById('media-mode-video');
  if(img) img.style.display = (_mediaMode === 'image') ? '' : 'none';
  if(vid) vid.style.display = (_mediaMode === 'video') ? '' : 'none';
  document.querySelectorAll('.media-mode-switch .mode-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.mode === _mediaMode));
  if(_mediaMode === 'image' && typeof onImgBackend === 'function') onImgBackend();
  if(_mediaMode === 'video' && typeof onVidBackend === 'function') onVidBackend();
}
async function _websiteHiggsfieldChoice(){
  if(_hfConfigured === null){
    try{ const s = await(await fetch('/api/media/status')).json(); _hfConfigured = !!s.higgsfield_api_key; }
    catch{ _hfConfigured = false; }
  }
  if(!_hfConfigured) return false;   // kein Key → keine Frage, immer lokal
  return confirm('Hero-Banner über Higgsfield-Cloud erzeugen?\n\n'
    + 'OK = Higgsfield-Cloud (verbraucht Credits, oft schneller)\n'
    + 'Abbrechen = lokal generieren (bewährt)');
}

// Gemeinsamer Start für Feed- und Rangliste-Button.
async function _startWebsiteBuild(id, lead, btn, out){
  if(!btn || !out) return;
  btn.disabled = true;
  out.style.display = 'block';
  out.innerHTML = `<div class="m-spin-row"><span class="jc-spin"></span><span>Frage Hero-Modus ab…</span></div>`;
  const useHf = await _websiteHiggsfieldChoice();
  out.innerHTML = `<div class="m-spin-row"><span class="jc-spin"></span><span>Website-Bau wird gestartet…</span></div>`;
  try{
    const body = Object.assign({}, lead || {}, {use_higgsfield: useHf});
    const d = await(await fetch(`/api/lead/${id}/website`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body),
    })).json();
    if(d.ok && d.job_id){
      // Die Seite ist ab jetzt persistent — im 'Webseiten'-Reiter sofort sichtbar
      // machen (läuft serverseitig im Hintergrund weiter, auch wenn man wegklickt).
      if(typeof refreshWebsites === 'function') refreshWebsites();
      _pollWebsite(d.job_id, out, btn, d.github_ready, d.railway_ready);
    }else{
      out.innerHTML = `<div class="m-err-row">✕ ${_e(d.reason||'Fehler')}</div>`;
      btn.disabled = false;
    }
  }catch(e){ out.innerHTML = `<div class="m-err-row">✕ ${_e(String(e))}</div>`; btn.disabled=false; }
}

async function buildWebsite(id){
  await _startWebsiteBuild(id, _modalLead || {},
    document.getElementById('m-web-btn'), document.getElementById('m-web-out'));
}

function _pollWebsite(jobId, out, btn, ghReady, rwReady){
  const hint = (!ghReady || !rwReady)
    ? `<div class="m-web-hint">Hinweis: ${!ghReady?'GITHUB_TOKEN':''}${(!ghReady&&!rwReady)?' + ':''}${!rwReady?'RAILWAY_TOKEN':''} fehlt in .env — die Seite wird lokal gebaut, Repo/Deploy aktivieren sich, sobald die Tokens gesetzt sind.</div>`
    : '';
  const iv = setInterval(async ()=>{
    let job;
    try{ job = await(await fetch('/api/website/job/'+jobId)).json(); }
    catch{ return; }
    const log = Array.isArray(job.log) ? job.log : [];
    if(job.status === 'done'){
      clearInterval(iv);
      btn.disabled = false;
      let html = `<div class="m-web-done">✓ ${_e(job.step||'Fertig')}</div>`;
      if(job.live_url) html += `<a class="m-web-link" href="${_e(job.live_url)}" target="_blank">🌐 Live öffnen: ${_e(job.live_url)} ↗</a>`;
      if(job.repo_url) html += `<a class="m-web-link sub" href="${_e(job.repo_url)}" target="_blank">GitHub-Repo ↗</a>`;
      if(job.folder)   html += `<div class="m-web-folder">Ordner: ${_e(job.folder)}</div>`;
      out.innerHTML = html + hint;
      if(typeof refreshWebsites === 'function') refreshWebsites();            // 'Webseiten'-Reiter nachziehen
      if(typeof _claudeRefreshUsage === 'function') _claudeRefreshUsage();   // Token-Anzeige nachziehen
    }else if(job.status === 'error'){
      clearInterval(iv);
      btn.disabled = false;
      out.innerHTML = `<div class="m-err-row">✕ ${_e(job.error||job.step||'Fehler')}</div>` + hint;
    }else{
      const p = job.progress || 0;
      const recent = log.slice(-6);
      const steps = recent.map((s,i)=>{
        const last = i === recent.length-1;
        return `<div class="m-web-step ${last?'cur':'ok'}">`
          + (last ? `<span class="jc-spin"></span>` : `<span class="m-web-tick">✓</span>`)
          + `<span>${_e(s.t||'')}</span></div>`;
      }).join('') || `<div class="m-web-step cur"><span class="jc-spin"></span><span>${_e(job.step||'Arbeitet…')}</span></div>`;
      out.innerHTML = `<div class="m-web-prog">
        <div class="m-web-bar"><div class="m-web-fill" style="width:${p}%"></div></div>
        <div class="m-web-pct">${p}%</div>
        <div class="m-web-steps">${steps}</div></div>` + hint;
    }
  }, 1200);
}

function closeModal(){
  document.getElementById('modal-bg').classList.remove('open');
  document.getElementById('modal').classList.remove('open');
}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();});

function exportCSV(){ window.location.href='/api/export/csv'; }

// ── Auto-Website-Builder ────────────────────────────────────────────────────
// Start/Stop laufen seit dem EINEN Start-Button über /api/start + /api/stop (siehe
// toggleScraper()/_setUI()) — dieser Poller liefert nur noch die Live-Anzeige im
// start-meta-Cluster ("n/5 Seiten"). Die ausführliche Ansicht bleibt auf der Home-Seite
// (hm-builder-panel), unabhängig von diesem Poller.
let _autoOn = false, _autoTimer = null;
async function _autoPoll(){
  let s;
  try{ s = await(await fetch('/api/auto-build/status')).json(); }catch{ return; }
  _autoOn = !!s.running;
  const el = document.getElementById('start-build');
  if(el){
    const limit = s.daily_limit ?? 5;
    el.textContent = _autoOn
      ? `${s.today_count ?? 0}/${limit} Seiten`
      : (s.done ? `${s.done} Seiten gebaut` : `0/${limit} Seiten`);
  }
  _updateStartMetaVisibility();
  clearTimeout(_autoTimer);
  if(_autoOn) _autoTimer = setTimeout(_autoPoll, 6000);   // gedrosselt von 3 s → 6 s
}

// ── Sidebar Collapse ────────────────────────────────────────────────────────
function toggleSidebar(){
  const on = document.body.classList.toggle('sb-collapsed');
  try{ localStorage.setItem('jarvis_sb_collapsed', on ? '1' : '0'); }catch{}
}
function _initSidebar(){
  try{
    if(localStorage.getItem('jarvis_sb_collapsed') === '1') document.body.classList.add('sb-collapsed');
  }catch{}
}

// ── Init ──────────────────────────────────────────────────────────────────────
(async()=>{
  try{
    const d=await(await fetch('/api/status')).json();
    if(d.stats) _applyStats(d.stats);
    if(d.workers) _updateWorkerMeta(d.workers);
    if(d.running){_running=true;_setUI(true);_connectSSE();}
  }catch{}
  loadVerifierModel();
  loadMediaModels();
  _applyCustomBg();
  _initPageFromHash();
  _initSidebar();
  _autoPoll();
  _limitPoll();
  _usagePoll();
  // 'leads' (Mein Status) ist die statische Default-Seite — ohne passenden URL-Hash
  // ruft _initPageFromHash() showPage() nie auf, darum hier zusätzlich absichern.
  const _activePage = document.querySelector('.page.active');
  if(!_activePage || _activePage.dataset.page === 'leads'){
    loadMyStatus(); _startMyStatusPoll(); _startStatusLogPoll(); _startMsRankPoll();
    if(typeof initWebsites === 'function') initWebsites();
  }
})();

// ── Claude-Limit-Banner: alle 15 s prüfen, bei vollem Limit direkt anzeigen ────
let _claudeLimit = null;
async function _limitPoll(){
  try{
    const d = await(await fetch('/api/status')).json();
    _claudeLimit = (d && d.claude_limit) || null;
    _renderLimitBanner(_claudeLimit);
    if(d && d.workers) _updateWorkerMeta(d.workers);
  }catch{}
  setTimeout(_limitPoll, 15000);
}
function _renderLimitBanner(lim){
  const el = document.getElementById('claude-limit-banner');
  if(!el) return;
  if(lim && lim.limited){
    const txt = document.getElementById('claude-limit-text');
    if(txt){
      const scope = (lim.scope === 'weekly') ? 'Weekly-Limit' : 'Session-Limit';
      const stage = lim.stage ? ` (Stufe „${lim.stage}")` : '';
      // Exakte Reset-Uhrzeit anzeigen, wenn Claude sie gemeldet hat („resets 5am"),
      // sonst Fallback auf die Restminuten des gelernten Retry-Plans.
      let wait = '';
      if(lim.reset_at){
        const t = new Date(lim.reset_at * 1000);
        wait = ` — läuft um ${t.toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'})} Uhr automatisch weiter`;
      } else if(lim.minutes_left){
        wait = ` — nächster Versuch in ~${lim.minutes_left} Min`;
      }
      txt.textContent = `Claude-${scope} erreicht${stage} — pausiert${wait || ', läuft automatisch weiter'}.`;
    }
    // „Nochmal testen"-Button einmalig anhängen (manueller Retry / Limit zurücksetzen).
    if(!document.getElementById('claude-limit-retry')){
      const b = document.createElement('button');
      b.id = 'claude-limit-retry';
      b.className = 'limit-retry-btn';
      b.textContent = '↻ Nochmal testen';
      b.title = 'Limit-Zeichen zurücksetzen, Token-Fenster frisch starten und alle Keys freigeben';
      b.onclick = claudeLimitRetry;
      el.appendChild(b);
    }
    el.style.display = 'flex';
    document.body.classList.add('limit-on');
  }else{
    el.style.display = 'none';
    document.body.classList.remove('limit-on');
  }
}

async function claudeLimitRetry(){
  const b = document.getElementById('claude-limit-retry');
  if(b){ b.disabled = true; b.textContent = '↻ …'; }
  try{ await fetch('/api/claude/reset', {method:'POST'}); }catch{}
  _renderLimitBanner(null);            // optimistisch ausblenden
  try{
    const d = await(await fetch('/api/status')).json();
    _claudeLimit = (d && d.claude_limit) || null;
    _renderLimitBanner(_claudeLimit);
  }catch{}
  if(b){ b.disabled = false; b.textContent = '↻ Nochmal testen'; }
}

// Generiertes Hintergrundbild (static/img/bg_custom.png) anwenden, falls vorhanden.
function _applyCustomBg(){
  const img = new Image();
  img.onload = () => {
    document.body.style.backgroundImage =
      `linear-gradient(rgba(2,6,14,.72),rgba(2,6,14,.82)), url('/static/img/bg_custom.png?v=${Date.now()}')`;
    document.body.style.backgroundSize = 'cover';
    document.body.style.backgroundPosition = 'center';
    document.body.style.backgroundAttachment = 'fixed';
  };
  img.src = '/static/img/bg_custom.png?probe=' + Date.now();
}

// ════════════════════════════════════════════════════════════════════════════
//  PAGE NAVIGATION
// ════════════════════════════════════════════════════════════════════════════
const _PAGES = ['home', 'leads', 'media', 'graph', 'ranking', 'websites', 'custom', 'claude', 'video-studio', 'leadpackages'];

function showPage(name){
  if(!_PAGES.includes(name)) name = 'leads';
  document.querySelectorAll('.page').forEach(p =>
    p.classList.toggle('active', p.dataset.page === name));
  document.querySelectorAll('.topnav-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.page === name));
  location.hash = name;
  if(name === 'media'){
    loadGallery(); loadImageLeads(); _restoreActiveJob();
    if(typeof loadMediaModels === 'function') loadMediaModels();
    if(typeof onImgBackend === 'function') onImgBackend();
    if(typeof onVidBackend === 'function') onVidBackend();
  }
  if(name === 'graph' && typeof initGraph === 'function') initGraph();
  if(name === 'graph' && typeof initGlobe === 'function') initGlobe();
  if(name === 'ranking' && typeof initRanking === 'function') initRanking();
  if((name === 'websites' || name === 'leads') && typeof initWebsites === 'function') initWebsites();
  if(name === 'custom' && typeof cbInit === 'function') cbInit();
  if(name === 'claude' && typeof initClaude === 'function') initClaude();
  if(name === 'video-studio' && typeof initVideoStudio === 'function') initVideoStudio();
  if(name === 'leadpackages' && typeof initLeadpackages === 'function') initLeadpackages();
  if(name === 'home')  loadHome();
  // Mein-Status-Polling (Sammler/Bau/Kosten + eingebettetes Log + Top-25-Rangliste) nur, solange sichtbar
  if(name !== 'leads') { _stopMyStatusPoll(); _stopStatusLogPoll(); _stopMsRankPoll(); }
  if(name === 'leads')  { loadMyStatus(); _startMyStatusPoll(); _startStatusLogPoll(); _startMsRankPoll(); }
}

function _initPageFromHash(){
  const h = (location.hash || '').slice(1);
  if(_PAGES.includes(h)) showPage(h);
}
window.addEventListener('hashchange', () => {
  const h = (location.hash || '').slice(1);
  if(_PAGES.includes(h)) showPage(h);
});

// ════════════════════════════════════════════════════════════════════════════
//  EIGENE MARKE — Custom-Build (Schritt 1 bauen · Schritt 2 verbessern)
//  Eingaben + aktiver Job überleben das Neuladen (localStorage).
// ════════════════════════════════════════════════════════════════════════════
const _CB_FORM_KEY = 'jarvis.cb.form';
const _CB_JOB_KEY  = 'jarvis.cb.job';
const _CB_FIELDS   = ['cb-name','cb-branche','cb-stadt','cb-beschreibung','cb-telefon',
                      'cb-email','cb-adresse','cb-hero-mode','cb-hero-prompt','cb-recipients'];
let _cbPoll = null;
let _cbInited = false;

function cbHeroMode(){
  const m = (document.getElementById('cb-hero-mode')||{}).value;
  const pw = document.getElementById('cb-hero-prompt-wrap');
  const fw = document.getElementById('cb-hero-file-wrap');
  if(pw) pw.style.display = (m==='generate') ? '' : 'none';
  if(fw) fw.style.display = (m==='upload')   ? '' : 'none';
  _cbSaveForm();
}

// ── Persistenz ────────────────────────────────────────────────────────────────
function _cbSaveForm(){
  const o = {};
  _CB_FIELDS.forEach(id => { const el = document.getElementById(id); if(el) o[id] = el.value; });
  try{ localStorage.setItem(_CB_FORM_KEY, JSON.stringify(o)); }catch(e){}
}
function _cbRestoreForm(){
  let o; try{ o = JSON.parse(localStorage.getItem(_CB_FORM_KEY)||'{}'); }catch(e){ o = {}; }
  _CB_FIELDS.forEach(id => { const el = document.getElementById(id); if(el && o[id]!=null) el.value = o[id]; });
  cbHeroMode();
}
function _cbSaveJob(job){
  try{ job ? localStorage.setItem(_CB_JOB_KEY, JSON.stringify(job))
          : localStorage.removeItem(_CB_JOB_KEY); }catch(e){}
}
function _cbLoadJob(){ try{ return JSON.parse(localStorage.getItem(_CB_JOB_KEY)||'null'); }catch(e){ return null; } }

// ── Init (beim Tab-Öffnen + beim Laden) ─────────────────────────────────────────
function cbInit(){
  if(!document.getElementById('cb-form')) return;
  _cbRestoreForm();
  if(!_cbInited){
    _CB_FIELDS.forEach(id => {
      const el = document.getElementById(id);
      if(el) el.addEventListener('input', _cbSaveForm);
    });
    _cbInited = true;
  }
  const job = _cbLoadJob();
  if(job && job.job_id){
    document.getElementById('cb-status-empty').style.display='none';
    document.getElementById('cb-prog').style.display='';
    document.getElementById('cb-prog-name').textContent = job.name || '—';
    _cbWatch(job.job_id);   // setzt Polling fort, egal ob bauen oder verbessern läuft
  }
}

// ── KI-Vorschläge ───────────────────────────────────────────────────────────────
async function cbSuggest(){
  const g = id => (document.getElementById(id)||{}).value || '';
  const name = g('cb-name').trim();
  const out  = document.getElementById('cb-suggest-out');
  const btn  = document.getElementById('cb-suggest');
  if(!name){ alert('Bitte zuerst einen Firmennamen eingeben, Sir.'); return; }
  btn.disabled = true; btn.querySelector('.cb-suggest-ic').textContent = '…';
  if(out){ out.style.display=''; out.className='cb-suggest-out'; out.textContent='JARVIS denkt nach…'; }
  let r;
  try{ r = await(await fetch('/api/custom-build/suggest',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name, branche:g('cb-branche'), stadt:g('cb-stadt'), beschreibung:g('cb-beschreibung')})})).json(); }
  catch{ r = {ok:false, reason:'Netzwerkfehler'}; }
  btn.disabled = false; btn.querySelector('.cb-suggest-ic').textContent = '✦';
  if(!r.ok){ if(out){ out.className='cb-suggest-out err'; out.textContent='Vorschlag fehlgeschlagen: '+(r.reason||'unbekannt'); } return; }
  const s = r.suggestion || {};
  const set = (id,v) => { const el=document.getElementById(id); if(el && v){ el.value=v; } };
  if(s.branche && !g('cb-branche').trim()) set('cb-branche', s.branche);
  set('cb-beschreibung', s.beschreibung);
  if(s.hero_prompt && (g('cb-hero-mode')==='generate')) set('cb-hero-prompt', s.hero_prompt);
  _cbSaveForm();
  if(out){
    const leist = (s.leistungen||[]).slice(0,6).join(' · ');
    out.className='cb-suggest-out';
    out.textContent = (r.source==='ollama' ? '✓ KI-Vorschlag übernommen' : '✓ Vorschlag übernommen')
      + (s.tagline ? ' — „'+s.tagline+'"' : '') + (leist ? ' · '+leist : '');
  }
}

// ── Schritt 1: Bauen ──────────────────────────────────────────────────────────
async function startCustomBuild(){
  const name = (document.getElementById('cb-name').value||'').trim();
  if(!name){ alert('Bitte einen Firmennamen eingeben, Sir.'); return; }
  const btn = document.getElementById('cb-submit');
  btn.disabled = true; btn.textContent = 'Wird gebaut…';

  const fd = new FormData();
  const g = id => (document.getElementById(id)||{}).value || '';
  fd.append('name', name);
  ['branche','stadt','beschreibung','telefon','email','adresse','recipients'].forEach(k=>fd.append(k, g('cb-'+k)));
  const heroMode = g('cb-hero-mode');
  if(heroMode==='generate') fd.append('hero_prompt', g('cb-hero-prompt'));
  const logo = (document.getElementById('cb-logo')||{}).files?.[0]; if(logo) fd.append('logo', logo);
  if(heroMode==='upload'){ const hf=(document.getElementById('cb-hero-file')||{}).files?.[0]; if(hf) fd.append('hero', hf); }

  let res;
  try{ res = await(await fetch('/api/custom-build',{method:'POST',body:fd})).json(); }
  catch{ res = {ok:false, reason:'Netzwerkfehler'}; }
  if(!res.ok){ alert('Fehler: '+(res.reason||'unbekannt')); btn.disabled=false; btn.textContent='Webseite bauen'; return; }

  _cbSaveJob({job_id:res.job_id, name});
  document.getElementById('cb-status-empty').style.display='none';
  document.getElementById('cb-prog').style.display='';
  document.getElementById('cb-prog-name').textContent = name;
  document.getElementById('cb-actions').style.display='none';
  _cbWatch(res.job_id);
}

// ── Schritt 2: Verbessern (Skill-Makeover, wiederholbar) ────────────────────────
async function cbImprove(){
  const job = _cbLoadJob();
  if(!job || !job.job_id){ alert('Keine gebaute Seite gefunden, Sir.'); return; }
  const ib = document.getElementById('cb-improve');
  ib.disabled = true; ib.querySelector('.cb-improve-ic').textContent='…';
  let r;
  try{ r = await(await fetch('/api/custom-build/improve',{method:'POST',
    headers:{'Content-Type':'application/json'}, body:JSON.stringify({job_id:job.job_id})})).json(); }
  catch{ r = {ok:false, reason:'Netzwerkfehler'}; }
  ib.querySelector('.cb-improve-ic').textContent='✦';
  if(!r.ok){ alert('Verbessern fehlgeschlagen: '+(r.reason||'unbekannt')); ib.disabled=false; return; }
  document.getElementById('cb-actions').style.display='none';
  document.getElementById('cb-stages').style.display='';
  _cbWatch(job.job_id);
}

function cbReset(){
  if(_cbPoll){ clearInterval(_cbPoll); _cbPoll=null; }
  _cbSaveJob(null);
  document.getElementById('cb-prog').style.display='none';
  document.getElementById('cb-status-empty').style.display='';
  document.getElementById('cb-actions').style.display='none';
  document.getElementById('cb-stages').style.display='none';
  const sub = document.getElementById('cb-submit'); if(sub){ sub.disabled=false; sub.textContent='Webseite bauen'; }
}

// ── Live-Status-Polling (bauen ODER verbessern) ─────────────────────────────────
function _cbWatch(jobId){
  if(_cbPoll) clearInterval(_cbPoll);
  const tick = async ()=>{
    let d; try{ d = await(await fetch('/api/custom-build/status/'+jobId)).json(); }catch{ return; }
    const b = d.build||{}, c = d.custom||{};
    // Nach einem Server-Neustart ist der In-Memory-Job weg (custom leer + kein Build-Status):
    // Polling sauber beenden, Panel zurücksetzen, statt ewig „…" anzuzeigen.
    if(!c.job_id && !b.status && !b.step){
      clearInterval(_cbPoll); _cbPoll=null; _cbSaveJob(null);
      const empty=document.getElementById('cb-status-empty'), prog=document.getElementById('cb-prog');
      if(empty) empty.style.display=''; if(prog) prog.style.display='none';
      const sub=document.getElementById('cb-submit'); if(sub){ sub.disabled=false; sub.textContent='Webseite bauen'; }
      return;
    }
    const fill = document.getElementById('cb-prog-fill');
    const step = document.getElementById('cb-prog-step');
    const link = document.getElementById('cb-prog-link');
    const sub  = document.getElementById('cb-submit');
    if(fill) fill.style.width = (b.progress||0)+'%';
    if(step) step.textContent = c.phase || b.step || '…';
    if((b.live_url||c.live_url) && link){ link.style.display=''; link.href = b.live_url||c.live_url; }

    // Makeover-Stufenbalken, sobald verbessert wird oder Stufen vorhanden sind
    const stagesWrap = document.getElementById('cb-stages');
    const sd = c.stages_done||0, stt = c.stages_total||7;
    if(c.improving || sd>0){
      if(stagesWrap) stagesWrap.style.display='';
      const sc = document.getElementById('cb-stages-cnt'); if(sc) sc.textContent = sd+'/'+stt;
      const sf = document.getElementById('cb-stages-fill'); if(sf) sf.style.width = Math.round(sd/stt*100)+'%';
    }

    if(c.improving){ if(sub){ sub.disabled=true; } return; }   // läuft noch

    if(c.done){
      clearInterval(_cbPoll); _cbPoll=null;
      if(step) step.textContent = c.phase || 'Fertig';
      if(sub){ sub.disabled=false; sub.textContent='Webseite bauen'; }
      // Nach erfolgreichem Bau → Verbessern + Neue-Marke anbieten
      if(c.built){
        document.getElementById('cb-actions').style.display='';
        const ib = document.getElementById('cb-improve');
        if(ib){ ib.disabled=false; ib.querySelector('.cb-improve-ic').textContent='✦';
          ib.lastChild.textContent = sd>0 ? ' Weiter verbessern' : ' Mit Skill verbessern'; }
      }
    }
  };
  tick();
  _cbPoll = setInterval(tick, 2500);
}

// ════════════════════════════════════════════════════════════════════════════
//  MEDIA — Bild / Video Generierung
// ════════════════════════════════════════════════════════════════════════════
let _mediaModels = null;
const _activePolls = {};   // {prefix: intervalId}

async function loadMediaModels(){
  let d;
  try{ d = await(await fetch('/api/media/models')).json(); }
  catch{ d = {image:{}, video:{}, higgsfield:{}}; }
  _mediaModels = d;

  // Bild-Modelle
  const imgSel = document.getElementById('img-model');
  if(imgSel){
    const keys = Object.keys(d.image || {});
    imgSel.innerHTML = keys.length
      ? keys.map(k => `<option value="${_e(k)}">${_e(d.image[k].name || k)}</option>`).join('')
      : '<option value="">Diffusers nicht installiert</option>';
  }

  // Video-Modelle (lokal)
  const vidSel = document.getElementById('vid-model');
  if(vidSel){
    const keys = Object.keys(d.video || {});
    vidSel.innerHTML = keys.length
      ? keys.map(k => `<option value="${_e(k)}">${_e(d.video[k].name || k)}</option>`).join('')
      : '<option value="">Diffusers nicht installiert</option>';
  }

  // Higgsfield-Modelle
  const hfSel = document.getElementById('vid-hf-model');
  if(hfSel){
    const keys = Object.keys(d.higgsfield || {});
    hfSel.innerHTML = keys.length
      ? keys.map(k => `<option value="${_e(k)}">${_e(d.higgsfield[k].name || k)} · ${d.higgsfield[k].credits||'?'} Cr.</option>`).join('')
      : '<option value="dop-lite">Dop Lite</option>';
  }

  // Hardware-Empfehlung anzeigen + bei reiner CPU den Video-Standard auf Higgsfield
  // setzen (lokales Wan-Video braucht eine GPU).
  try{
    const s = await(await fetch('/api/media/status')).json();
    _hfConfigured = !!s.higgsfield_api_key;
    _hfMcpConfigured = !!s.higgsfield_mcp;
    _openaiConfigured = !!s.openai_image;
    // ChatGPT-Bilder nicht verfügbar → Option im Bild-Backend ausgrauen, Default auf lokal.
    const ib = document.getElementById('img-backend');
    if(ib){
      const oaiOpt = ib.querySelector('option[value="openai"]');
      if(oaiOpt && !_openaiConfigured) oaiOpt.textContent = 'ChatGPT (OpenAI) — Key fehlt';
      if(!_openaiConfigured && ib.value === 'openai') ib.value = 'local';
      const mcpOpt = ib.querySelector('option[value="higgsfield_mcp"]');
      if(mcpOpt && !_hfMcpConfigured) mcpOpt.textContent = 'Higgsfield (Abo) — Login beim Start';
      // Abo angemeldet → das ist die beste (kostendeckende) Quelle: als Standard wählen.
      if(_hfMcpConfigured) ib.value = 'higgsfield_mcp';
      else if(ib.value === 'higgsfield_mcp') ib.value = _openaiConfigured ? 'openai' : 'local';
      if(typeof onImgBackend === 'function') onImgBackend();
    }
    // Gleiches Default fürs Werbe-Video bei angemeldetem Abo.
    const vb0 = document.getElementById('vid-backend');
    if(vb0){
      const vmcp = vb0.querySelector('option[value="higgsfield_mcp"]');
      if(vmcp && !_hfMcpConfigured) vmcp.textContent = 'Higgsfield (Abo) — Login beim Start';
      if(_hfMcpConfigured){ vb0.value = 'higgsfield_mcp'; if(typeof onVidBackend==='function') onVidBackend(); }
      else if(vb0.value === 'higgsfield_mcp'){ vb0.value = 'local'; if(typeof onVidBackend==='function') onVidBackend(); }
    }
    const info = document.getElementById('vid-engine-info');
    if(s.video_local_ok === false){
      if(_hfConfigured){
        if(info) info.textContent = 'Kein GPU erkannt — Videos werden automatisch über Higgsfield Cloud generiert';
      } else {
        if(info) info.textContent = '⚠ Kein GPU + kein Higgsfield-Key → HIGGSFIELD_API_KEY in .env eintragen';
      }
      const vb = document.getElementById('vid-backend');
      if(vb){
        const loOpt = vb.querySelector('option[value="local"]');
        if(loOpt) loOpt.textContent = 'Lokal (Wan 2.1) — nur mit GPU';
        // Ohne GPU: Abo-MCP bevorzugen (nutzt Abo-Credits), sonst API-Key-Higgsfield.
        if(_hfMcpConfigured){ vb.value = 'higgsfield_mcp'; if(typeof onVidBackend==='function') onVidBackend(); }
        else if(_hfConfigured){ vb.value = 'higgsfield'; if(typeof onVidBackend==='function') onVidBackend(); }
      }
    } else {
      if(info && s.empfehlung) info.textContent = s.empfehlung;
    }
  }catch(e){}
}

function onVidBackend(){
  const backend = document.getElementById('vid-backend').value;
  const local   = document.getElementById('vid-model');
  const hf       = document.getElementById('vid-hf-model');
  if(backend === 'higgsfield'){
    local.style.display = 'none';
    hf.style.display    = '';
  }else if(backend === 'higgsfield_mcp'){
    // Abo via MCP: festes Modell (Kling 3 Turbo) → keine Modellwahl nötig.
    local.style.display = 'none';
    hf.style.display    = 'none';
  }else{
    local.style.display = '';
    hf.style.display    = 'none';
  }
}

function onImgBackend(){
  const sel     = document.getElementById('img-backend');
  if(!sel) return;
  const backend = sel.value;
  const model   = document.getElementById('img-model');
  const note    = document.getElementById('img-hf-note');
  // Modell-Dropdown nur beim lokalen Backend zeigen (Higgsfield/OpenAI haben feste Modelle).
  const showModel = (backend === 'local');
  if(model) model.style.display = showModel ? '' : 'none';
  if(note)  note.style.display  = showModel ? 'none' : '';
  if(!note) return;
  if(backend === 'higgsfield_mcp'){
    note.textContent = _hfMcpConfigured ? 'Higgsfield Soul V2 · Abo-Credits'
                                        : '⚠ Higgsfield-Abo nicht angemeldet — Login beim Start';
  } else if(backend === 'higgsfield'){
    note.textContent = _hfConfigured ? 'Higgsfield Soul · 1080p (API-Key)'
                                     : '⚠ Higgsfield-API-Key fehlt in der .env';
  } else if(backend === 'openai'){
    note.textContent = _openaiConfigured ? 'ChatGPT · gpt-image-1 · 1536×1024'
                                          : '⚠ OPENAI_API_KEY fehlt in der .env';
  }
}

async function generateImage(){
  const prompt  = (document.getElementById('img-prompt').value || '').trim();
  if(!prompt){ return; }
  const backend = document.getElementById('img-backend').value || 'local';
  const model   = document.getElementById('img-model').value || '';
  const btn     = document.getElementById('img-free-btn');
  btn.disabled = true;
  try{
    const res = await fetch('/api/media/generate/image', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({prompt, backend, model_key: model}),
    });
    const d = await res.json();
    if(d.ok && d.job_id) pollJob(d.job_id, 'img');
    else _showJob('img', {status:'error', error: d.reason || 'Fehler'});
  }catch(e){ _showJob('img', {status:'error', error:String(e)}); }
  finally{ btn.disabled = false; }
}

// ── Werbe-Foto-Set: Lead-Dropdown + Formular ──────────────────────────────────
let _imgLeads = [];
async function loadImageLeads(){
  const sel = document.getElementById('af-lead');
  if(!sel) return;
  try{
    const d = await(await fetch('/api/evaluated/all?limit=300&sort=score')).json();
    _imgLeads = Array.isArray(d) ? d : (d.leads || []);
  }catch{ return; }
  sel.innerHTML = '<option value="">— Lead wählen —</option>' +
    _imgLeads.map(l => `<option value="${l.id}">${_e(l.name)} · ${_e(l.branche||'')} (${_e(l.stadt||'')})</option>`).join('');
  // Gleiche Liste auch im Video-Tab (Werbevideo für einen Lead).
  const vsel = document.getElementById('vid-lead');
  if(vsel){
    vsel.innerHTML = '<option value="">— Lead für Werbevideo —</option>' +
      _imgLeads.map(l => `<option value="${l.id}">${_e(l.name)} · ${_e(l.branche||'')} (${_e(l.stadt||'')})</option>`).join('');
  }
}

function vidLeadPick(){
  const id = (document.getElementById('vid-lead')||{}).value;
  const l  = _imgLeads.find(x => String(x.id) === String(id));
  if(!l) return;
  const b = document.getElementById('vid-betrieb'); if(b) b.value = l.name || '';
  const br = document.getElementById('vid-branche'); if(br) br.value = l.branche || '';
}

async function generateAdVideo(){
  const betrieb = (document.getElementById('vid-betrieb')||{}).value || '';
  const branche = (document.getElementById('vid-branche')||{}).value || '';
  const motiv   = (document.getElementById('vid-prompt')||{}).value || '';
  if(!betrieb.trim() && !branche.trim() && !motiv.trim()){
    _showJob('vid', {status:'error', error:'Bitte Betrieb, Branche oder eine Beschreibung angeben.'});
    return;
  }
  const backend = document.getElementById('vid-backend').value;
  const payload = {betrieb, branche, motiv: motiv.trim(), backend, stil:'cinematisch'};
  if(backend === 'higgsfield') payload.hf_model = document.getElementById('vid-hf-model').value || 'dop-lite';
  else                         payload.model_key = document.getElementById('vid-model').value || '';
  const btn = document.getElementById('vid-ad-btn');
  if(btn) btn.disabled = true;
  try{
    const res = await fetch('/api/media/generate/ad-video', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload),
    });
    const d = await res.json();
    if(d.ok && d.job_id) pollJob(d.job_id, 'vid');
    else _showJob('vid', {status:'error', error: d.reason || 'Fehler'});
  }catch(e){ _showJob('vid', {status:'error', error:String(e)}); }
  finally{ if(btn) btn.disabled = false; }
}

function afLeadPick(){
  const id = document.getElementById('af-lead').value;
  const l  = _imgLeads.find(x => String(x.id) === String(id));
  if(!l) return;
  document.getElementById('af-betrieb').value = l.name || '';
  document.getElementById('af-branche').value = l.branche || '';
}

async function generateImageSet(){
  const brief = {
    lead_id:    document.getElementById('af-lead').value || null,
    betrieb:    (document.getElementById('af-betrieb').value || '').trim(),
    branche:    (document.getElementById('af-branche').value || '').trim(),
    motiv:      (document.getElementById('af-motiv').value || '').trim(),
    stil:       document.getElementById('af-stil').value,
    stimmung:   document.getElementById('af-stimmung').value,
    text_platz: document.getElementById('af-textplatz').checked,
    backend:    (document.getElementById('set-backend')||{}).value || 'local',
    model_key:  document.getElementById('img-model').value || '',
  };
  if(!brief.betrieb && !brief.branche && !brief.motiv){
    document.getElementById('af-hint').textContent = 'Bitte mindestens Betrieb, Branche oder Motiv angeben.';
    return;
  }
  const btn = document.getElementById('img-gen-btn');
  btn.disabled = true;
  document.getElementById('af-hint').textContent = '';
  try{
    const res = await fetch('/api/media/generate/set', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(brief),
    });
    const d = await res.json();
    if(d.ok && d.job_id){
      document.getElementById('af-hint').textContent = 'Prompt: ' + (d.prompt||'').slice(0,140) + '…';
      // Set-Anzeige vorbereiten
      const sr = document.getElementById('set-result');
      sr.style.display = 'block';
      document.getElementById('set-grid').innerHTML = '';
      _pollSet(d.job_id, d.count || brief.count);
    }else{
      _showJob('img', {status:'error', error: d.reason || 'Fehler'});
    }
  }catch(e){ _showJob('img', {status:'error', error:String(e)}); }
  finally{ btn.disabled = false; }
}

function _pollSet(jobId, total){
  if(_activePolls['img']){ clearInterval(_activePolls['img']); }
  const statusEl = document.getElementById('img-job-status');
  statusEl.style.display = 'block';
  statusEl.classList.add('running');

  _activePolls['img'] = setInterval(async () => {
    let job;
    try{ job = await(await fetch('/api/media/job/' + jobId)).json(); }
    catch{ return; }

    const done  = job.done_count || 0;
    const tot   = job.total  || total || 5;
    const pct   = job.progress != null ? Number(job.progress) : Math.round(done / tot * 100);
    const secs  = job.elapsed ? `${job.elapsed}s` : '';

    // Fertige Assets live ins Grid
    const items = job.result_items || (job.result_urls || []).map(u => ({label:'', url:u}));
    const grid  = document.getElementById('set-grid');
    if(grid && items.length){
      grid.innerHTML = items.map(it => `<div class="media-card asset-card" onclick="openMediaFull('${_e(it.url)}','image')">
          <img src="${_e(it.url)}" loading="lazy"/>
          ${it.label ? `<div class="asset-label">${_e(it.label)}</div>` : ''}
        </div>`).join('');
    }

    if(job.status === 'running' || job.status === 'queued'){
      statusEl.classList.add('running'); statusEl.classList.remove('err');
      statusEl.innerHTML = `
        <div class="jc-row">
          <span class="jc-spin"></span>
          <span>Generiere Assets… <b>${done}/${tot}</b>${secs ? ' · ' + secs : ''}</span>
          <span style="margin-left:auto;font-weight:700;color:var(--c)">${pct}%</span>
        </div>
        <div class="jc-bar"><div class="jc-fill" style="width:${pct}%"></div></div>`;
    }else if(job.status === 'done'){
      clearInterval(_activePolls['img']); _activePolls['img'] = null;
      statusEl.classList.remove('running');
      statusEl.innerHTML = `<div class="jc-row"><span class="jc-ok">✓</span>
        <span>Asset-Set fertig — ${items.length} Bilder in ${job.elapsed||0}s</span>
        <span style="margin-left:auto;font-weight:700;color:var(--g)">100%</span></div>`;
      loadGallery();
      setTimeout(() => { statusEl.style.display = 'none'; }, 6000);
    }else if(job.status === 'error'){
      clearInterval(_activePolls['img']); _activePolls['img'] = null;
      statusEl.classList.add('err'); statusEl.classList.remove('running');
      statusEl.innerHTML = `<div class="jc-row"><span class="jc-x">✕</span><span>Fehler: ${_e(job.error||'unbekannt')}</span></div>`;
    }
  }, 2000);
}

async function generateVideo(){
  const prompt  = (document.getElementById('vid-prompt').value || '').trim();
  if(!prompt){ return; }
  const backend = document.getElementById('vid-backend').value;
  const btn     = document.getElementById('vid-gen-btn');
  btn.disabled  = true;
  const payload = {prompt, backend};
  if(backend === 'higgsfield') payload.hf_model  = document.getElementById('vid-hf-model').value || 'dop-lite';
  else                         payload.model_key = document.getElementById('vid-model').value || '';
  try{
    const res = await fetch('/api/media/generate/video', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload),
    });
    const d = await res.json();
    if(d.ok && d.job_id) pollJob(d.job_id, 'vid');
    else _showJob('vid', {status:'error', error: d.reason || 'Fehler'});
  }catch(e){ _showJob('vid', {status:'error', error:String(e)}); }
  finally{ btn.disabled = false; }
}

function _showJob(prefix, job){
  const el = document.getElementById(prefix + '-job-status');
  if(!el) return;
  el.style.display = 'block';
  el.classList.toggle('running', job.status === 'running' || job.status === 'queued');
  el.classList.toggle('err',     job.status === 'error');

  let body = '';
  if(job.status === 'queued'){
    body = `<div class="jc-row"><span class="jc-spin"></span><span>In Warteschlange…</span></div>`;
  }else if(job.status === 'running'){
    const el2 = (job.elapsed || 0);
    body = `<div class="jc-row"><span class="jc-spin"></span><span>Generierung läuft… <b id="${prefix}-jc-elapsed">${el2}s</b></span></div>
            <div class="jc-scan"></div>`;
  }else if(job.status === 'done'){
    body = `<div class="jc-row"><span class="jc-ok">✓</span><span>Fertig in ${job.elapsed||0}s</span></div>`;
  }else if(job.status === 'error'){
    body = `<div class="jc-row"><span class="jc-x">✕</span><span>Fehler: ${_e(job.error||'unbekannt')}</span></div>`;
  }
  el.innerHTML = body;
}

function pollJob(jobId, prefix){
  if(_activePolls[prefix]){ clearInterval(_activePolls[prefix]); }
  _showJob(prefix, {status:'queued'});
  let elapsed = 0;
  _activePolls[prefix] = setInterval(async () => {
    let job;
    try{ job = await(await fetch('/api/media/job/' + jobId)).json(); }
    catch{ return; }

    if(job.status === 'running'){
      _showJob(prefix, job);
      // Lokaler Elapsed-Zähler (Backend liefert elapsed erst am Ende)
      elapsed += 1.5;
      const e = document.getElementById(prefix + '-jc-elapsed');
      if(e) e.textContent = Math.round(elapsed) + 's';
    }else if(job.status === 'done'){
      clearInterval(_activePolls[prefix]); _activePolls[prefix] = null;
      _showJob(prefix, job);
      loadGallery();
      setTimeout(() => {
        const el = document.getElementById(prefix + '-job-status');
        if(el) el.style.display = 'none';
      }, 4000);
    }else if(job.status === 'error'){
      clearInterval(_activePolls[prefix]); _activePolls[prefix] = null;
      _showJob(prefix, job);
    }else{
      _showJob(prefix, job);
    }
  }, 1500);
}

async function loadGallery(){
  let g;
  try{ g = await(await fetch('/api/media/gallery')).json(); }
  catch{ return; }

  // ── Bild-Galerie: erst Sets als Gruppen, dann Einzelbilder ──────────────
  const imgEl = document.getElementById('img-gallery');
  if(imgEl){
    const sets   = g.sets   || [];
    const singles = g.images || [];
    let html = '';

    // Sets als Gruppen
    for(const s of sets){
      const head  = _e(s.summary || `Set ${s.set_id}`);
      const items = (s.items || []).map(it =>
        `<div class="media-card asset-card" onclick="openMediaFull('${_e(it.url)}','image')">
          <img src="${_e(it.url)}" loading="lazy"/>
          ${it.label ? `<div class="asset-label">${_e(it.label)}</div>` : ''}
        </div>`
      ).join('');
      html += `<div class="gallery-set">
        <div class="gallery-set-head">
          <span class="gsh-title">${head}</span>
          <span class="gsh-sub">${_e(s.ts ? s.ts.slice(0,10) : '')} · ${(s.items||[]).length} Assets</span>
        </div>
        <div class="gallery-set-grid">${items}</div>
      </div>`;
    }

    // Einzelbilder (falls vorhanden)
    if(singles.length){
      html += `<div class="gallery-set-head" style="margin-top:24px"><span class="gsh-title">Einzelbilder</span></div>`;
      html += `<div class="media-grid">` + singles.map(it =>
        `<div class="media-card" onclick="openMediaFull('${_e(it.url)}','image')">
          <img src="${_e(it.url)}" loading="lazy" alt="${_e(it.name)}"/>
        </div>`
      ).join('') + `</div>`;
    }

    imgEl.innerHTML = html || '<div class="media-empty">Noch keine Bilder generiert</div>';
  }

  const vidEl = document.getElementById('vid-gallery');
  if(vidEl){
    const vids = g.videos || [];
    vidEl.innerHTML = vids.length
      ? vids.map(it => `<div class="media-card">
          <video src="${_e(it.url)}" controls preload="metadata"></video>
        </div>`).join('')
      : '<div class="media-empty">Noch keine Videos generiert</div>';
  }
}

// ── Aktiven Job nach Seitenreload wiederherstellen ────────────────────────
async function _restoreActiveJob(){
  let jobs;
  try{ jobs = (await(await fetch('/api/media/jobs')).json()).jobs || []; }
  catch{ return; }
  // Ersten laufenden oder wartenden Asset-Set-Job suchen
  const active = jobs.find(j => j.kind === 'asset_set' && (j.status === 'running' || j.status === 'queued'));
  if(!active) return;
  // Fortschrittsanzeige und bereits fertige Bilder wiederherstellen
  const sr = document.getElementById('set-result');
  if(sr) sr.style.display = 'block';
  const grid = document.getElementById('set-grid');
  if(grid){
    const items = active.result_items || (active.result_urls||[]).map(u=>({label:'',url:u}));
    grid.innerHTML = items.map(it =>
      `<div class="media-card asset-card" onclick="openMediaFull('${_e(it.url)}','image')">
        <img src="${_e(it.url)}" loading="lazy"/>
        ${it.label ? `<div class="asset-label">${_e(it.label)}</div>` : ''}
      </div>`
    ).join('');
  }
  _pollSet(active.id, active.total || 5);
}

function openMediaFull(url, kind){
  document.getElementById('modal-inner').innerHTML = `
    <div class="m-hdr">
      <div class="m-title" style="font-size:13px">Vorschau</div>
      <button class="m-close" onclick="closeModal()">✕</button>
    </div>
    <div style="text-align:center">
      ${kind === 'image'
        ? `<img src="${_e(url)}" style="max-width:100%;border-radius:10px"/>`
        : `<video src="${_e(url)}" controls autoplay style="max-width:100%;border-radius:10px"></video>`}
    </div>
    <div style="text-align:center;margin-top:10px">
      <a href="${_e(url)}" download class="export-btn" style="text-decoration:none">↓ Download</a>
    </div>`;
  document.getElementById('modal-bg').classList.add('open');
  document.getElementById('modal').classList.add('open');
}

// ── Log-Konsole ───────────────────────────────────────────────────────────
let _logLastTs  = '';
let _logFilter  = '';
let _logOpen    = false;
let _logTimer   = null;
const LOG_COLORS = {
  SUCCESS: '#00e676', ERROR: '#ff3b50', WARN: '#ffca28',
  INFO: '#00d4ff', EVAL: '#ea80fc', SCRAPE: '#ffab40', DEBUG: '#4a6080',
};

function toggleLogDrawer() {
  _logOpen = !_logOpen;
  document.getElementById('log-drawer').classList.toggle('open', _logOpen);
  document.getElementById('log-toggle-btn').textContent = _logOpen ? '▼ Schließen' : '▲ Öffnen';
  if (_logOpen && !_logTimer) _startLogPoll();
  if (!_logOpen && _logTimer) { clearInterval(_logTimer); _logTimer = null; }
}

function _startLogPoll() {
  _pollLogs();
  _logTimer = setInterval(_pollLogs, 5000);   // gedrosselt von 2 s → 5 s (nur wenn Konsole offen)
}

async function _pollLogs() {
  try {
    const url = '/api/logs?limit=100' + (_logLastTs ? '&since=' + encodeURIComponent(_logLastTs) : '');
    const r = await fetch(url);
    const d = await r.json();
    if (d.logs && d.logs.length) {
      _logLastTs = d.last_ts || _logLastTs;
      _appendLogs(d.logs);
    }
  } catch(e) {}
}

function _appendLogs(entries) {
  const el = document.getElementById('log-entries');
  if (!el) return;
  const wasBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  entries.forEach(e => {
    if (_logFilter && e.level !== _logFilter) return;
    const div = document.createElement('div');
    div.className = 'log-line';
    div.dataset.lvl = e.level;
    const col = LOG_COLORS[e.level] || '#4a6080';
    div.innerHTML = `<span class="ll-ts">${e.ts}</span>`
      + `<span class="ll-lvl" style="color:${col}">${e.level.padEnd(7)}</span>`
      + `<span class="ll-worker">[${e.worker}]</span>`
      + `<span class="ll-msg">${_e(e.msg)}</span>`;
    el.appendChild(div);
  });
  // Max 400 Zeilen im DOM
  while (el.children.length > 400) el.removeChild(el.firstChild);
  if (wasBottom) el.scrollTop = el.scrollHeight;

  // Stats
  const total = el.querySelectorAll('.log-line').length;
  const errs  = el.querySelectorAll('[data-lvl="ERROR"]').length;
  const stats = document.getElementById('log-stats');
  if (stats) stats.textContent = `${total} Zeilen${errs ? ' · ' + errs + ' Fehler' : ''}`;
}

function setLogFilter(lvl) {
  _logFilter = lvl;
  document.querySelectorAll('.lf-btn').forEach(b => b.classList.toggle('active', b.dataset.lvl === lvl));
  // Bestehende Zeilen filtern
  document.querySelectorAll('.log-line').forEach(l => {
    l.style.display = (!lvl || l.dataset.lvl === lvl) ? '' : 'none';
  });
}

function clearLogView() {
  const el = document.getElementById('log-entries');
  if (el) el.innerHTML = '';
  _logLastTs = '';
}


/* ════════════════════════════════════════════════════════════════════════════
   MEIN STATUS — Status-Leiste, Website-Bau-Card, Versand-Queue (Leads-Tab)
   ════════════════════════════════════════════════════════════════════════════ */
let _myStatusPollId = null;

async function loadMyStatus(){
  let d;
  try{ d = await(await fetch('/api/mystatus')).json(); }catch{ return; }
  _renderMyStatus(d);
}

function _startMyStatusPoll(){
  if(_myStatusPollId) clearInterval(_myStatusPollId);
  _myStatusPollId = setInterval(loadMyStatus, 8000);
}
function _stopMyStatusPoll(){
  if(_myStatusPollId){ clearInterval(_myStatusPollId); _myStatusPollId = null; }
}

// ── Mein-Status: kompakte Top-25-Rangliste (links, alle 10s) ─────────────────
// Nutzt dieselbe Route wie die volle Rangliste-Seite (ranking.js) — kein neuer
// Endpoint nötig, nur ein schmalerer Render für die linke Spalte.
let _msRankData    = [];
let _msRankTimer    = null;

function _startMsRankPoll(){
  _loadMsRank();
  if(_msRankTimer) clearInterval(_msRankTimer);
  _msRankTimer = setInterval(_loadMsRank, 10000);
}
function _stopMsRankPoll(){
  if(_msRankTimer){ clearInterval(_msRankTimer); _msRankTimer = null; }
}

async function _loadMsRank(){
  let data;
  try{ data = await(await fetch('/api/evaluated/all?limit=25&sort=erwartungswert')).json(); }
  catch{ return; }
  _msRankData = Array.isArray(data) ? data : (data.leads || data.items || []);
  _renderMsRank();
}

function _renderMsRank(){
  const list = document.getElementById('ms-rank-list');
  if(!list) return;
  if(!_msRankData.length){
    list.innerHTML = '<div class="ms-rank-empty">Noch keine bewerteten Leads</div>';
    return;
  }
  list.innerHTML = _msRankData.slice(0, 25).map((l, i) => {
    const typ = l.lead_typ || 'Cold';
    const sub = [l.branche, l.stadt].filter(Boolean).map(_e).join(' · ');
    const wert = Number(l.erwartungswert_euro ?? l.potenzial_euro) || 0;
    return `<div class="ms-rank-row ${typ}" onclick="_msRankOpen(${i})">
      <span class="mr-rank">${i+1}</span>
      <span class="mr-body">
        <div class="mr-name">${_e(l.name)}</div>
        <div class="mr-sub">${sub}</div>
      </span>
      <span class="mr-val">${wert.toLocaleString('de-DE')} €</span>
    </div>`;
  }).join('');
}

function _msRankOpen(i){
  const lead = _msRankData[i];
  if(lead && typeof openRankDetail === 'function') openRankDetail(lead);
}

function _fmtEta(seconds){
  seconds = Math.max(0, Math.round(seconds||0));
  if(seconds <= 0) return 'jetzt';
  const m = Math.floor(seconds/60);
  return m > 0 ? `${m} Min` : `${seconds}s`;
}

function _renderMyStatus(d){
  if(!d) return;
  const col  = d.collector || {};
  const scr  = d.scraper   || {};
  const bld  = d.builder   || {};
  const web  = d.websites  || {};
  const rev  = d.review    || {};
  const cl   = d.claude_limit || {};
  const paid = d.paid      || {};

  // Sammler-Chip (10-Min-Sammel-Zyklus)
  const cDot = document.getElementById('ms-collector-dot');
  const cTxt = document.getElementById('ms-collector-txt');
  if(cDot && cTxt){
    if(!col.enabled){
      cDot.className = 'ms-dot';
      cTxt.textContent = 'Lead-Sammler deaktiviert';
    } else if(col.in_window){
      cDot.className = 'ms-dot on';
      const left = Math.max(0, (col.run_seconds || 600) - (col.window_elapsed || 0));
      cTxt.textContent = `Sammelt gerade — noch ${_fmtEta(left)}`;
    } else if(scr.running){
      cDot.className = 'ms-dot on';
      cTxt.textContent = 'Läuft (manuell gestartet)';
    } else {
      cDot.className = 'ms-dot';
      cTxt.textContent = `Nächster Lauf in ${_fmtEta(col.seconds_to_next)}`;
    }
  }
  const wTxt = document.getElementById('ms-worker-txt');
  if(wTxt){
    const workers = scr.workers || [];
    const alive = workers.filter(w => w.alive).length;
    wTxt.textContent = `${alive}/${workers.length || 6} Worker`;
  }

  // Token-/Kosten-Leiste (Claude-Session-Limit für den Webseiten-Bau)
  const tTxt  = document.getElementById('ms-token-txt');
  const tFill = document.getElementById('ms-token-fill');
  if(tTxt && tFill){
    const pct = Math.min(100, Math.max(0, cl.percent || 0));
    tTxt.textContent = `Session-Limit: ${pct}%`;
    tFill.style.width = pct + '%';
    tFill.className = 'ms-token-fill' + (pct >= 95 ? ' full' : pct >= 75 ? ' near' : '');
  }
  const costEl  = document.getElementById('ms-cost');
  const costTxt = document.getElementById('ms-cost-txt');
  if(costEl && costTxt){
    const eur = Number(paid.api_eur_today || 0);
    // Schwelle 1 Cent statt "> 0": Mini-Bruchteile (z.B. 0.0005 €) rundeten sonst sichtbar
    // auf "+0.00 €" — technisch korrekt, aber irrefuehrend als hervorgehobener Hinweis.
    if(paid.paid && eur >= 0.01){
      costEl.classList.add('show');
      costTxt.textContent = `+${eur.toFixed(2)} € Extra-Tokens heute`;
    } else {
      costEl.classList.remove('show');
    }
  }

  // Website-Bau-Card
  const bDot   = document.getElementById('ms-build-dot');
  const bPhase = document.getElementById('ms-build-phase');
  const bFill  = document.getElementById('ms-build-fill');
  const bCnt   = document.getElementById('ms-build-cnt');
  if(bDot) bDot.className = 'ms-build-dot' + (bld.running ? ' on' : '');
  if(bPhase) bPhase.textContent = bld.running ? (bld.phase || 'läuft…') : 'Bereit (nicht aktiv)';
  const limit = bld.daily_limit || 5, today = bld.today_count || 0;
  if(bFill) bFill.style.width = Math.min(100, Math.round(today / limit * 100)) + '%';
  if(bCnt) bCnt.textContent = `${today}/${limit} Seiten heute`;
  _setNum('mbs-live',   web.live   || 0);
  _setNum('mbs-dead',   web.dead   || 0);
  _setNum('mbs-errors', web.errors || 0);

  // Versand-Queue
  _setNum('ms-send-approved', rev.approved || 0);
  _setNum('ms-send-sent',     rev.sent     || 0);
  _setNum('ms-send-pending',  rev.pending  || 0);
}

// ── Eingebettetes Live-Log (eigener Poller — unabhängig vom Log-Drawer unten) ──
let _msLogLastTs = '';
let _msLogFilter = '';
let _msLogTimer  = null;

function _startStatusLogPoll(){
  _pollStatusLogs();
  if(_msLogTimer) clearInterval(_msLogTimer);
  _msLogTimer = setInterval(_pollStatusLogs, 5000);
}
function _stopStatusLogPoll(){
  if(_msLogTimer){ clearInterval(_msLogTimer); _msLogTimer = null; }
}
async function _pollStatusLogs(){
  try{
    const url = '/api/logs?limit=100' + (_msLogLastTs ? '&since=' + encodeURIComponent(_msLogLastTs) : '');
    const d = await(await fetch(url)).json();
    if(d.logs && d.logs.length){
      _msLogLastTs = d.last_ts || _msLogLastTs;
      _appendStatusLogs(d.logs);
    }
  }catch{}
}
function _appendStatusLogs(entries){
  const el = document.getElementById('ms-log-entries');
  if(!el) return;
  const wasBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  entries.forEach(e => {
    if(_msLogFilter && e.level !== _msLogFilter) return;
    const div = document.createElement('div');
    div.className = 'log-line';
    div.dataset.lvl = e.level;
    const col = LOG_COLORS[e.level] || '#4a6080';
    div.innerHTML = `<span class="ll-ts">${e.ts}</span>`
      + `<span class="ll-lvl" style="color:${col}">${e.level.padEnd(7)}</span>`
      + `<span class="ll-worker">[${e.worker}]</span>`
      + `<span class="ll-msg">${_e(e.msg)}</span>`;
    el.appendChild(div);
  });
  while(el.children.length > 200) el.removeChild(el.firstChild);
  if(wasBottom) el.scrollTop = el.scrollHeight;
}
function setStatusLogFilter(lvl){
  _msLogFilter = lvl;
  document.querySelectorAll('.ms-log-filters .lf-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.lvl === lvl));
  document.querySelectorAll('#ms-log-entries .log-line').forEach(l => {
    l.style.display = (!lvl || l.dataset.lvl === lvl) ? '' : 'none';
  });
}


/* ════════════════════════════════════════════════════════════════════════════
   HOME TAB
   ════════════════════════════════════════════════════════════════════════════ */

async function loadHome() {
  try {
    const [statsRes, actRes] = await Promise.all([
      fetch('/api/home/stats').then(r => r.json()),
      fetch('/api/activity/recent?limit=20').then(r => r.json()),
    ]);
    _renderHomeStats(statsRes);
    _renderHomeBuilderPanel(statsRes.builder || {});
    _renderHomeProgress(statsRes);
    _renderHomeGrid(statsRes.sites || []);
    _renderHomeActivity(actRes.activities || []);
  } catch(e) {
    console.warn('[Home] Ladefehler:', e);
  }
}

function _set(id, v){ const el = document.getElementById(id); if(el) el.textContent = v; }
function _setHtml(id, v){ const el = document.getElementById(id); if(el) el.innerHTML = v; }

function _renderHomeStats(d) {
  _set('hstat-total',  d.total    ?? 0);
  _set('hstat-live',   d.live     ?? 0);
  _set('hstat-sent',   d.sent     ?? 0);
  _set('hstat-build',  d.building ?? 0);
}

function _renderHomeBuilderPanel(ab) {
  const dot  = document.getElementById('hm-dot');
  const lbl  = document.getElementById('hm-builder-lbl');
  const fill = document.getElementById('hm-session-fill');
  const cnt  = document.getElementById('hm-session-cnt');
  const sess = document.getElementById('hm-session-lbl');
  if(!dot) return;

  if(ab.running) {
    dot.className  = 'hm-dot running';
    const phase    = ab.phase   || 'läuft';
    const today    = ab.today_count ?? 0;
    const limit    = ab.daily_limit ?? 5;
    const pct      = Math.min(100, Math.round(today / Math.max(1, limit) * 100));
    lbl.textContent  = `Auto-Builder aktiv · ${phase}`;
    if(fill) fill.style.width = pct + '%';
    if(cnt)  cnt.textContent  = `${today} / ${limit}`;
    if(sess) {
      // Session-Key '{datum}_s{n}' → "Session n/3"; Fallback aus der Uhrzeit.
      const m = /_s(\d+)$/.exec(ab.session || '');
      sess.textContent = m ? `Session ${m[1]}` : 'Session';
    }
  } else {
    dot.className    = 'hm-dot idle';
    lbl.textContent  = 'Auto-Builder · bereit (nicht aktiv)';
    if(fill) fill.style.width = '0%';
    if(cnt)  cnt.textContent  = '';
    if(sess) sess.textContent = '';
  }
}

function _renderHomeProgress(d) {
  const total  = d.total    || 0;
  const live   = d.live     || 0;
  const sent   = d.sent     || 0;
  const build  = d.building || 0;

  // Technik: Schritt 1–5 vollständig implementiert = Basis 88 %
  // +4 % wenn Seiten live sind, +4 % wenn Mails versendet wurden
  const techPct = Math.min(100, 88 + (live > 0 ? 4 : 0) + (sent > 0 ? 4 : 0) + (build > 0 ? 2 : 0));

  // Umsatz: nach Angeboten versandt hochskalieren
  // Basis 35 % (System bereit) + je versandter Mail +5 % bis max. 70 %
  const moneyPct = Math.min(70, 35 + Math.min(sent * 5, 35));
  const moneyWarn = moneyPct < 50;

  const techEl  = document.getElementById('ov-tech-fill');
  const moneyEl = document.getElementById('ov-money-fill');
  if(techEl)  techEl.style.width  = techPct  + '%';
  if(moneyEl) moneyEl.style.width = moneyPct + '%';

  const techPctEl  = document.getElementById('ov-tech-pct');
  const moneyPctEl = document.getElementById('ov-money-pct');
  if(techPctEl)  techPctEl.textContent  = techPct  + ' %';
  if(moneyPctEl){
    moneyPctEl.textContent = moneyPct + ' %';
    moneyPctEl.className   = 'ov-meter-pct' + (moneyWarn ? ' warn' : '');
  }

  // Technik-Note dynamisch
  const techNote = document.getElementById('ov-tech-note');
  if(techNote){
    const parts = ['Schritt 1–5 fertig'];
    if(live > 0)  parts.push(`${live} Seite${live>1?'n':''} live`);
    if(sent > 0)  parts.push(`${sent} Angebot${sent>1?'e':''} versandt`);
    if(build > 0) parts.push(`${build} in Bearbeitung`);
    techNote.textContent = parts.join(' · ');
  }

  // Money-Note dynamisch
  const moneyNote = document.getElementById('ov-money-note');
  if(moneyNote){
    if(sent === 0)
      moneyNote.textContent = 'Nächster Schritt: SMTP einrichten + erstes Angebot senden';
    else if(sent < 5)
      moneyNote.textContent = `${sent} Angebot${sent>1?'e':''} versandt — mehr Volumen für Konversion nötig`;
    else
      moneyNote.textContent = `${sent} Angebote versandt — Conversion beobachten, Volumen weiter hochfahren`;
  }

  // Pipeline-Knoten für Schritt 6 dynamisch färben
  const pn6    = document.getElementById('hpn-6');
  const arr6   = document.getElementById('hpn-arr-6');
  if(pn6){
    if(sent > 0){
      pn6.className  = 'ofn done';
      if(arr6) arr6.className = 'ofn-arr done';
      const badge6 = document.getElementById('step6-badge');
      if(badge6){ badge6.className = 'ov-badge done'; badge6.textContent = 'Aktiv'; }
    } else {
      pn6.className  = 'ofn partial';
      if(arr6) arr6.className = 'ofn-arr partial';
    }
  }

  // Step 6 sent-info
  const si = document.getElementById('step6-sent-info');
  if(si) si.textContent = sent > 0 ? `✓ ${sent} Angebot${sent>1?'e':''} bereits versandt.` : '';

  // Goal-Title dynamisch
  const gt = document.getElementById('goal-dynamic-title');
  if(gt){
    if(sent > 0)
      gt.textContent = `${sent} Angebot${sent>1?'e':''} versandt — jetzt auf Antwort warten & Volumen erhöhen.`;
    else if(live > 0)
      gt.textContent = `${live} Seite${live>1?'n':''} live — SMTP einrichten und erstes Angebot rausschicken.`;
    else
      gt.textContent = 'Technik läuft — SMTP einrichten und ersten Testlauf starten.';
  }

  // Testphasen-Reifegrad (Banner): alle Module gebaut (Basis 80) + live (+10) + Echtversand (+10)
  const tpFill = document.getElementById('tp-progress-fill');
  const tpLbl  = document.getElementById('tp-progress-lbl');
  if(tpFill){
    const maturity = Math.min(100, 80 + (live > 0 ? 10 : 0) + (sent > 0 ? 10 : 0));
    tpFill.style.width = maturity + '%';
    if(tpLbl){
      let s = `Reifegrad ${maturity} % · alle Module gebaut & getestet`;
      if(sent > 0)      s += ` · ${sent} Angebot${sent>1?'e':''} live versandt`;
      else if(live > 0) s += ` · ${live} Seite${live>1?'n':''} live · nur noch SMTP scharf schalten`;
      else              s += ` · SMTP scharf schalten für den Echtversand`;
      tpLbl.textContent = s;
    }
  }
}

function _renderHomeGrid(sites) {
  const grid  = document.getElementById('home-grid');
  const empty = document.getElementById('home-empty');
  if (!grid) return;

  if (!sites.length) {
    if (empty) empty.style.display = '';
    return;
  }
  if (empty) empty.style.display = 'none';

  const statusLabels = {live:'Online',building:'Wird gebaut',error:'Fehler',pending:'Ausstehend',done:'Fertig'};
  const brancheIcons = {'Dachdecker':'🏠','Maler':'🎨','Elektriker':'⚡','Klempner':'🔧','Zahnarzt':'🦷','Friseur':'✂️','Restaurant':'🍽️','default':'🌐'};

  const cards = sites.map(s => {
    const icon = brancheIcons[s.branche] || brancheIcons.default;
    const statusCls = s.live ? 'live' : (s.status || 'unknown').toLowerCase();
    const statusLbl = s.live ? 'Online' : (statusLabels[s.status] || s.status || 'Unbekannt');
    const prog      = Math.min(100, Math.max(0, s.progress || 0));
    const thumb     = s.thumbnail
      ? `<img class="site-thumb" src="${_e(s.thumbnail)}" alt="${_e(s.name)}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">`
        + `<div class="site-thumb-placeholder" style="display:none">${icon}</div>`
      : `<div class="site-thumb-placeholder">${icon}</div>`;
    const liveBtnAttr = s.live_url ? `href="${_e(s.live_url)}" target="_blank"` : 'disabled';
    const gitBtnAttr  = s.repo_url ? `href="${_e(s.repo_url)}" target="_blank"` : 'disabled';
    const created = s.created ? new Date(s.created).toLocaleDateString('de-DE') : '';
    return `<div class="site-card">
      ${thumb}
      <div class="site-body">
        <div class="site-name">${_e(s.name)}</div>
        <div class="site-meta">
          ${s.branche ? `<span class="site-branche">${_e(s.branche)}</span>` : ''}
          ${s.stadt   ? `<span class="site-stadt">📍 ${_e(s.stadt)}</span>` : ''}
        </div>
        <div class="site-status ${statusCls}">${statusLbl}</div>
        ${(_claudeLimit && _claudeLimit.limited && _claudeLimit.site && s.name === _claudeLimit.site)
          ? `<div class="site-limit-badge">⏳ Limit voll · pausiert</div>` : ''}
        ${s.status === 'building' ? `<div class="site-progress-bar"><div class="site-progress-fill" style="width:${prog}%"></div></div>` : ''}
        ${created ? `<div style="font-size:10px;color:var(--tx3)">${created}</div>` : ''}
        <div class="site-actions">
          <a class="site-btn live-btn" ${liveBtnAttr}>🌐 Live</a>
          <a class="site-btn" ${gitBtnAttr}>⎔ GitHub</a>
        </div>
      </div>
    </div>`;
  });
  grid.innerHTML = cards.join('');
}

function _renderHomeActivity(acts) {
  const el = document.getElementById('home-act-list');
  if (!el) return;
  if (!acts.length) { el.innerHTML = '<div class="home-act-empty">Noch keine Aktivitäten.</div>'; return; }
  el.innerHTML = [...acts].reverse().map(a =>
    `<div class="act-item">
      <span class="act-icon">${_e(a.icon||'⚡')}</span>
      <div class="act-body">
        <div class="act-action">${_e(a.action)}</div>
        ${a.detail ? `<div class="act-detail">${_e(a.detail)}</div>` : ''}
      </div>
      <div class="act-meta">
        <span class="act-agent">${_e(a.agent)}</span>
        <span class="act-ts">${_e(a.ts)}</span>
      </div>
    </div>`
  ).join('');
}


/* ════════════════════════════════════════════════════════════════════════════
   VERBRAUCH — Badge im Topbar (Extra-Nutzung Claude + Higgsfield), auf JEDER
   Seite sichtbar. Ersetzt die frühere eigene Kosten-Seite.
   ════════════════════════════════════════════════════════════════════════════ */

function _fmt_eur(v) {
  return (parseFloat(v) || 0).toLocaleString('de-DE', {minimumFractionDigits:2,maximumFractionDigits:4}) + ' €';
}
function _fmt_k(v) {
  const n = parseInt(v) || 0;
  return n >= 1000 ? (n/1000).toFixed(1) + ' k' : String(n);
}

const _MONTH_NAMES = ['Januar','Februar','März','April','Mai','Juni','Juli',
                      'August','September','Oktober','November','Dezember'];

async function loadUsageBadge() {
  try {
    const r = await (await fetch('/api/usage/summary')).json();
    _renderUsageBadge(r.extra_usage || {}, r.higgsfield || {}, !!r.paid_active);
  } catch(e) {
    console.warn('[Usage] Ladefehler:', e);
  }
}

function _renderUsageBadge(extra, hf, paidActive) {
  const eur = parseFloat(extra.eur || 0);
  const hasExtra = paidActive && eur >= 0.01;   // < 1 Cent gilt als "inklusive" (Rundungsrauschen)

  const txt = document.getElementById('usage-badge-txt');
  if (txt) txt.textContent = hasExtra ? _fmt_eur(eur) : 'Inklusive';
  const badge = document.getElementById('usage-badge');
  if (badge) badge.classList.toggle('extra', hasExtra);

  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  set('up-extra', _fmt_eur(eur));
  set('up-extra-sub', hasExtra
    ? `${_fmt_k((extra.tokens_in||0) + (extra.tokens_out||0))} Tokens über das Abo-Limit hinaus abgerechnet.`
    : 'Abo-Session ist inklusive, keine Zusatzkosten.');
  set('up-hf', `${hf.credits || 0} Credits` + (hf.eur ? ` · ${_fmt_eur(hf.eur)}` : ''));

  const month = extra.month || hf.month || '';
  if (month) {
    const [y, m] = month.split('-');
    set('up-month', `${_MONTH_NAMES[parseInt(m, 10) - 1] || month} ${y}`);
  }
}

function toggleUsagePopover(ev) {
  if (ev) ev.stopPropagation();
  const pop = document.getElementById('usage-popover');
  if (!pop) return;
  const show = !pop.classList.contains('show');
  pop.classList.toggle('show', show);
  if (show) loadUsageBadge();
}
document.addEventListener('click', (ev) => {
  const pop   = document.getElementById('usage-popover');
  const badge = document.getElementById('usage-badge');
  if (!pop || !pop.classList.contains('show')) return;
  if (!pop.contains(ev.target) && ev.target !== badge && !(badge && badge.contains(ev.target))) {
    pop.classList.remove('show');
  }
});

function _usagePoll() {
  loadUsageBadge();
  setTimeout(_usagePoll, 60000);   // 60s reicht — Verbrauch ändert sich nicht sekündlich
}


