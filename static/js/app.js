'use strict';
/* ── JARVIS LeadHunter ─────────────────────────────────────────────────────── */

// ── State ─────────────────────────────────────────────────────────────────────
let _running       = false;
let _claudeOn      = false;
let _sse           = null;
let _feedCount     = 0;
let _allLeads      = [];   // Session-Cache für Sphere + Filter
let _sessionFinder = {};   // {finder: count} nur Session

// ── Finder-Registry ───────────────────────────────────────────────────────────
const F = {
  maps_playwright: { cls:'maps',   av:'M',  lbl:'Google Maps',   icon:'🗺',  sub:'Playwright'},
  gelbe_seiten:    { cls:'gelbe',  av:'GS', lbl:'Gelbe Seiten',  icon:'📒',  sub:'HTTP'},
  dasoertliche:    { cls:'oert',   av:'DÖ', lbl:'Das Örtliche',  icon:'📘',  sub:'HTTP'},
  ollama_ai:       { cls:'ollama', av:'AI', lbl:'Ollama KI',     icon:'🤖',  sub:'Lokal'},
  claude_ai:       { cls:'claude', av:'✦',  lbl:'Claude KI',     icon:'✦',   sub:'Anthropic'},
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

// ── Claude Toggle ─────────────────────────────────────────────────────────────
async function toggleClaude(){
  _claudeOn = !_claudeOn;
  const tog = document.getElementById('claude-toggle');
  const sw  = document.getElementById('ct-state');
  tog.classList.toggle('on', _claudeOn);
  sw.textContent = _claudeOn ? 'ON' : 'OFF';
  await fetch('/api/claude',{
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({enabled: _claudeOn}),
  });
}

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
      if(msg.type==='stats')      { _applyStats(msg.stats); }
      if(msg.type==='init_stats') { _applyStats(msg.stats); }
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
  const ORDER = ['maps_playwright','gelbe_seiten','dasoertliche','ollama_ai','claude_ai'];
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
}

function _onErr(msg){
  document.getElementById('empty-state')?.remove();
  const el = document.createElement('div');
  el.className='msg-err';el.textContent='⚠ '+msg;
  document.getElementById('chat-feed').insertBefore(el,document.getElementById('chat-feed').firstChild);
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
function openModal(lead){
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
    </div>`;
  document.getElementById('modal-bg').classList.add('open');
  document.getElementById('modal').classList.add('open');
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
    if(d.claude_enabled){
      _claudeOn=true;
      document.getElementById('claude-toggle').classList.add('on');
      document.getElementById('ct-state').textContent='ON';
    }
  }catch{}
})();
