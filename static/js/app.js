'use strict';
/* ── JARVIS LeadHunter ─────────────────────────────────────────────────────── */

// ── State ─────────────────────────────────────────────────────────────────────
let _running       = false;
let _sse           = null;
let _feedCount     = 0;
let _allLeads      = [];   // Session-Cache für Sphere + Filter
let _sessionFinder = {};   // {finder: count} nur Session

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

// ── Three.js Lead-Sphäre ──────────────────────────────────────────────────────
let _sphere = null;
(function initSphere(){
  const cv = document.getElementById('sphere-canvas');
  if(!cv || typeof THREE === 'undefined') return;

  const wrap = cv.parentElement;
  const W = wrap.clientWidth  || 196;
  const H = wrap.clientHeight || 196;

  const scene    = new THREE.Scene();
  const camera   = new THREE.PerspectiveCamera(55, W/H, 0.1, 100);
  camera.position.z = 5.5;

  const renderer = new THREE.WebGLRenderer({canvas:cv, alpha:true, antialias:true});
  renderer.setSize(W, H);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  // Sphere wireframe
  const wfGeo = new THREE.SphereGeometry(3, 18, 14);
  const wfMat = new THREE.MeshBasicMaterial({color:0x1a2d40,wireframe:true,transparent:true,opacity:.12});
  scene.add(new THREE.Mesh(wfGeo, wfMat));

  // Points
  const posArr = [], colArr = [];
  const geo = new THREE.BufferGeometry();
  const mat = new THREE.PointsMaterial({size:.1, vertexColors:true, transparent:true, opacity:.95});
  const pts = new THREE.Points(geo, mat);
  scene.add(pts);

  let n = 0;
  const PHI = Math.PI * (1 + Math.sqrt(5));

  function addPoint(type){
    const i   = n++;
    // Fibonacci sphere distribution
    const phi   = Math.acos(1 - 2*(i+0.5)/2000);
    const theta = PHI * i;
    const R     = 2.8 + (Math.random()-.5)*.2;
    posArr.push(R*Math.sin(phi)*Math.cos(theta), R*Math.cos(phi), R*Math.sin(phi)*Math.sin(theta));
    const C = type==='Hot'  ? [1,.23,.31]
             : type==='Warm' ? [1,.79,.24]
             :                 [.23,.51,.96];
    colArr.push(...C);
    geo.setAttribute('position', new THREE.Float32BufferAttribute([...posArr],3));
    geo.setAttribute('color',    new THREE.Float32BufferAttribute([...colArr],3));
    geo.attributes.position.needsUpdate = true;
    geo.attributes.color.needsUpdate    = true;
    document.getElementById('sphere-count').textContent = n;
  }

  let rx=0, ry=0;
  function animate(){
    requestAnimationFrame(animate);
    pts.rotation.y += .004;
    pts.rotation.x += .001;
    renderer.render(scene, camera);
  }
  animate();

  _sphere = { addPoint };
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
  document.getElementById('s-noweb').textContent = pct+'%';
  // Telefon aus Session zählen
  document.getElementById('s-tel').textContent = _allLeads.filter(l=>l.telefon).length;
  // Source Chart aus DB-Finder-Daten
  _renderChart(s.finders || {});
  // Bundesland-Chart aus DB
  if(s.bundeslaender) _renderBL(s.bundeslaender);
}

function _setNum(id, val){
  const el = document.getElementById(id);
  if(!el) return;
  const old = parseInt(el.textContent)||0;
  if(old !== val) el.textContent = val;
}

// ── Source Chart ──────────────────────────────────────────────────────────────
function _renderChart(finders){
  const el  = document.getElementById('source-chart');
  if(!el) return;
  const max = Math.max(1, ...Object.values(finders));
  const ORDER = ['maps_playwright','gelbe_seiten','dasoertliche','elfacht','golocal','ollama_ai'];
  const rows  = ORDER.filter(k => finders[k] > 0).map(k => {
    const f   = fi(k);
    const cnt = finders[k] || 0;
    const pct = Math.round(cnt/max*100);
    return `<div class="src-row src-${f.cls}">
      <div class="src-head">
        <div class="src-av">${f.av}</div>
        <span class="src-name">${f.lbl}</span>
        <span class="src-cnt">${cnt}</span>
      </div>
      <div class="src-bar-wrap">
        <div class="src-bar" style="width:${pct}%"></div>
      </div>
    </div>`;
  }).join('');
  el.innerHTML = rows || '<div style="color:var(--tx3);font-size:11px;padding:8px 0">Noch keine Daten</div>';
}

// ── Bundesland-Chart ────────────────────────────────────────────────────────────
function _renderBL(bl){
  const el = document.getElementById('bl-chart');
  if(!el) return;
  const max = Math.max(1, ...Object.values(bl));
  const rows = Object.entries(bl).slice(0, 10).map(([name, cnt]) => {
    const pct = Math.round(cnt/max*100);
    return `<div class="bl-row">
      <span class="bl-name">${_e(name.substring(0,16))}</span>
      <div class="bl-bar-wrap"><div class="bl-bar" style="width:${pct}%"></div></div>
      <span class="bl-cnt">${cnt}</span>
    </div>`;
  }).join('');
  el.innerHTML = rows || '';
}

// ── Lead empfangen ────────────────────────────────────────────────────────────
function _onLead(lead){
  _allLeads.unshift(lead);
  _feedCount++;
  _sessionFinder[lead.finder] = (_sessionFinder[lead.finder]||0) + 1;

  document.getElementById('empty-state')?.remove();
  document.getElementById('feed-cnt').textContent = _feedCount;

  const feed = document.getElementById('chat-feed');
  feed.insertBefore(_buildMsg(lead), feed.firstChild);
  if(feed.children.length > 300) feed.lastChild?.remove();

  // Sphere Punkt
  _sphere?.addPoint(lead.lead_typ);

  // Hot Sidebar
  if(lead.lead_typ==='Hot') _addHotCard(lead);

  // Graph Live-Update
  if(typeof graphOnNewLead === 'function') graphOnNewLead(lead);
}

function _onErr(msg){
  document.getElementById('empty-state')?.remove();
  const el = document.createElement('div');
  el.className='msg-err';el.textContent='⚠ '+msg;
  document.getElementById('chat-feed').insertBefore(el,document.getElementById('chat-feed').firstChild);
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

// ── Message bauen ─────────────────────────────────────────────────────────────
function _buildMsg(lead){
  const f    = fi(lead.finder);
  const t    = new Date().toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
  const wrap = document.createElement('div');
  wrap.className = 'msg';

  const webTag = !lead.has_website
    ? `<span class="tag no-web">✗ Kein Website</span>`
    : lead.website_alter >= 0
      ? `<span class="tag">${lead.website_alter}j alt</span>` : '';
  const telTag = lead.telefon ? `<span class="tag tel">✓ Tel</span>` : '';
  const brTag  = lead.branche ? `<span class="tag br">${_e(lead.branche)}</span>` : '';

  const foot = [
    lead.adresse ? `<div class="lc-ft"><span class="lc-ft-i">📍</span>${_e(lead.adresse.substring(0,30))}${lead.adresse.length>30?'…':''}</div>` : '',
    lead.telefon ? `<div class="lc-ft"><span class="lc-ft-i">📞</span>${_e(lead.telefon)}</div>` : '',
    lead.bewertung ? `<div class="lc-ft"><span class="lc-ft-i">⭐</span>${lead.bewertung}${lead.anz_bewertungen?' ('+lead.anz_bewertungen+')':''}</div>` : '',
  ].filter(Boolean).join('');

  const jl = JSON.stringify(lead).replace(/"/g,'&quot;');

  wrap.innerHTML = `
    <div class="msg-av av-${f.cls}">${f.av}</div>
    <div class="msg-body">
      <div class="msg-meta">
        <span class="msg-from from-${f.cls}">${f.lbl}</span>
        <span class="msg-badge badge-${lead.lead_typ}">${lead.lead_typ}</span>
        <span class="msg-time">${t}</span>
      </div>
      <div class="lead-card ${lead.lead_typ}" data-id="${lead.id||0}" onclick='openModal(${jl})'>
        <div class="lc-main">
          <div class="lc-name">${_e(lead.name)}</div>
          <div class="lc-score ${lead.lead_typ}">${lead.score}</div>
        </div>
        <div class="lc-tags">${webTag}${telTag}${brTag}</div>
        ${foot ? `<div class="lc-foot">${foot}</div>` : ''}
      </div>
    </div>`;
  return wrap;
}

function _e(s){ return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

// ── Hot Sidebar ───────────────────────────────────────────────────────────────
function _addHotCard(lead){
  const list = document.getElementById('hot-list');
  list.querySelector('.hot-empty')?.remove();
  const card = document.createElement('div');
  card.className='hot-card';
  card.innerHTML=`<div class="hc-name">${_e(lead.name)}</div>
    <div class="hc-meta">
      ${lead.branche?`<span class="hc-tag">${_e(lead.branche)}</span>`:''}
      ${lead.stadt?`<span class="hc-tag">${_e(lead.stadt)}</span>`:''}
      <span class="hc-score">${lead.score}pt</span>
    </div>`;
  card.onclick=()=>openModal(lead);
  list.insertBefore(card,list.firstChild);
  if(list.querySelectorAll('.hot-card').length>40) list.lastChild?.remove();
}

// ── Top 10 Opportunities ────────────────────────────────────────────────────
async function loadTop(){
  let top = [];
  try{ top = (await(await fetch('/api/top')).json()).top || []; }catch{ return; }
  const el = document.getElementById('top-list');
  if(!el) return;
  if(!top.length){ el.innerHTML = '<div style="color:var(--tx3);font-size:11px;padding:8px 0">Noch keine Daten</div>'; return; }
  el.innerHTML = top.map((l,i) => {
    const verified = l.verify_status === 'verified';
    const sc   = (verified && l.end_score >= 0) ? l.end_score : l.score;
    const badge = verified
      ? '<span class="v-badge verified">✓ verified</span>'
      : '<span class="v-badge pending">⏳ pending</span>';
    const hook = l.pitch_hook ? `<div class="tc-hook">${_e(l.pitch_hook)}</div>` : '';
    const jl   = JSON.stringify(l).replace(/"/g,'&quot;');
    return `<div class="top-card ${l.lead_typ||''}" onclick='openModal(${jl})'>
      <div class="tc-rank">${i+1}</div>
      <div class="tc-body">
        <div class="tc-top"><span class="tc-name">${_e(l.name)}</span><span class="tc-score">${sc}</span></div>
        <div class="tc-meta">${badge}${l.branche?`<span class="tc-br">${_e(l.branche)}</span>`:''}</div>
        ${hook}
      </div>
    </div>`;
  }).join('');
}

function _onVerified(lead){
  if(!lead) return;
  const i = _allLeads.findIndex(l => l.id === lead.id);
  if(i >= 0) _allLeads[i] = Object.assign({}, _allLeads[i], lead);
  loadTop();
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

// ── Filter ────────────────────────────────────────────────────────────────────
function applyFilter(){
  const fT=document.getElementById('flt-typ').value;
  const fW=document.getElementById('flt-web').value;
  const fB=document.getElementById('flt-bl').value;
  document.querySelectorAll('.msg').forEach(g=>{
    const card=g.querySelector('.lead-card');
    if(!card){g.style.display='';return;}
    const id  =parseInt(card.dataset.id||'0');
    const lead=_allLeads.find(l=>l.id===id);
    if(!lead){g.style.display='';return;}
    const ok=((!fT||lead.lead_typ===fT)&&(!fW||String(lead.has_website)===fW)&&(!fB||lead.bundesland===fB));
    g.style.display=ok?'':'none';
  });
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
    <div class="m-email-out" id="m-email-out" style="display:none"></div>
    <div class="m-mockup-out" id="m-mockup-out" style="display:none"></div>
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
function closeModal(){
  document.getElementById('modal-bg').classList.remove('open');
  document.getElementById('modal').classList.remove('open');
}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();});

// ── Utilities ─────────────────────────────────────────────────────────────────
function clearFeed(){
  const feed=document.getElementById('chat-feed');
  feed.innerHTML=`<div class="empty-state" id="empty-state">
    <div class="empty-icon">◎</div>
    <div class="empty-title">Feed geleert</div>
    <div class="empty-sub">Scraper läuft weiter im Hintergrund</div>
  </div>`;
  _allLeads=[];_feedCount=0;_sessionFinder={};
  document.getElementById('feed-cnt').textContent='0';
  document.getElementById('hot-list').innerHTML='<div class="hot-empty">Noch keine Hot Leads</div>';
  document.getElementById('s-tel').textContent='0';
}

function exportCSV(){ window.location.href='/api/export/csv'; }

// ── Init ──────────────────────────────────────────────────────────────────────
(async()=>{
  try{
    const d=await(await fetch('/api/status')).json();
    if(d.stats) _applyStats(d.stats);
    if(d.running){_running=true;_setUI(true);_connectSSE();}
  }catch{}
  loadTop();
  loadVerifierModel();
  loadMediaModels();
  setInterval(loadTop, 30000);
  _initPageFromHash();
})();

// ════════════════════════════════════════════════════════════════════════════
//  PAGE NAVIGATION
// ════════════════════════════════════════════════════════════════════════════
const _PAGES = ['leads', 'images', 'videos', 'graph'];

function showPage(name){
  if(!_PAGES.includes(name)) name = 'leads';
  document.querySelectorAll('.page').forEach(p =>
    p.classList.toggle('active', p.dataset.page === name));
  document.querySelectorAll('.topnav-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.page === name));
  location.hash = name;
  if(name === 'images' || name === 'videos') loadGallery();
  if(name === 'graph' && typeof initGraph === 'function') initGraph();
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
}

function onVidBackend(){
  const backend = document.getElementById('vid-backend').value;
  const local   = document.getElementById('vid-model');
  const hf       = document.getElementById('vid-hf-model');
  if(backend === 'higgsfield'){
    local.style.display = 'none';
    hf.style.display    = '';
  }else{
    local.style.display = '';
    hf.style.display    = 'none';
  }
}

async function generateImage(){
  const prompt = (document.getElementById('img-prompt').value || '').trim();
  if(!prompt){ return; }
  const model = document.getElementById('img-model').value || '';
  const btn   = document.getElementById('img-gen-btn');
  btn.disabled = true;
  try{
    const res = await fetch('/api/media/generate/image', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({prompt, model_key: model}),
    });
    const d = await res.json();
    if(d.ok && d.job_id) pollJob(d.job_id, 'img');
    else _showJob('img', {status:'error', error: d.reason || 'Fehler'});
  }catch(e){ _showJob('img', {status:'error', error:String(e)}); }
  finally{ btn.disabled = false; }
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

  const imgEl = document.getElementById('img-gallery');
  if(imgEl){
    const imgs = g.images || [];
    imgEl.innerHTML = imgs.length
      ? imgs.map(it => `<div class="media-card" onclick="openMediaFull('${_e(it.url)}','image')">
          <img src="${_e(it.url)}" loading="lazy" alt="${_e(it.name)}"/>
        </div>`).join('')
      : '<div class="media-empty">Noch keine Bilder generiert</div>';
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
  _logTimer = setInterval(_pollLogs, 2000);
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
