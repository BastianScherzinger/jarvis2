/* ── JARVIS LeadHunter — Frontend ─────────────────────────────────────────── */
'use strict';

let _running   = false;
let _sse       = null;
let _msgCount  = 0;
let _allLeads  = [];
let _hotCount  = 0;
let _statsTimer= null;

// ── Finder-Metadaten ──────────────────────────────────────────────────────────
const FINDER = {
  maps_playwright: { cls:'maps',   icon:'🗺',  label:'M',   name:'Google Maps',  sub:'Playwright Scraper' },
  gelbe_seiten:    { cls:'gelbe',  icon:'📒',  label:'GS',  name:'Gelbe Seiten', sub:'HTTP Scraper' },
  ollama_ai:       { cls:'ollama', icon:'🤖',  label:'AI',  name:'Ollama KI',    sub:'Lokales Modell' },
  claude_ai:       { cls:'claude', icon:'✦',   label:'CL',  name:'Claude KI',    sub:'Anthropic API' },
};
function _finder(key) {
  return FINDER[key] || { cls:'maps', icon:'?', label:'?', name: key || 'Unbekannt', sub:'' };
}

// ── Toggle ────────────────────────────────────────────────────────────────────
document.querySelectorAll('#ai-toggle .pill').forEach(btn => {
  btn.addEventListener('click', () => {
    if (_running) return;
    document.querySelectorAll('#ai-toggle .pill').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  });
});
document.querySelectorAll('#mode-toggle .pill').forEach(btn => {
  btn.addEventListener('click', () => {
    if (btn.classList.contains('off')) return;
    document.querySelectorAll('#mode-toggle .pill').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  });
});
function _getAiMode() {
  return document.querySelector('#ai-toggle .pill.active')?.dataset.val || 'local';
}

// ── Start / Stop ──────────────────────────────────────────────────────────────
function toggleScraper() {
  _running ? stopScraper() : startScraper();
}

async function startScraper() {
  const ai_mode = _getAiMode();
  const res  = await fetch('/api/start', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ ai_mode }),
  });
  const data = await res.json();
  if (!data.ok && data.reason !== 'already_running') return;

  _running = true;
  _setRunningUI(true);
  _connectSSE();
  _statsTimer = setInterval(_fetchStats, 6000);
}

async function stopScraper() {
  await fetch('/api/stop', { method:'POST' });
  _running = false;
  _setRunningUI(false);
  if (_sse) { _sse.close(); _sse = null; }
  clearInterval(_statsTimer);
}

function _setRunningUI(on) {
  const btn  = document.getElementById('start-btn');
  const icon = document.getElementById('start-icon');
  const text = document.getElementById('start-text');
  const ind  = document.getElementById('live-indicator');
  const lbl  = document.getElementById('live-label');

  btn.classList.toggle('running', on);
  icon.textContent = on ? '■' : '▶';
  text.textContent = on ? 'STOP' : 'START';
  ind.classList.toggle('on', on);
  lbl.textContent  = on ? 'LIVE' : 'OFFLINE';
}

// ── SSE ───────────────────────────────────────────────────────────────────────
function _connectSSE() {
  if (_sse) _sse.close();
  _sse = new EventSource('/api/stream');
  _sse.onmessage = e => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type === 'lead')  _onLead(msg.data);
      if (msg.type === 'error') _onError(msg.msg);
    } catch {}
  };
  _sse.onerror = () => { if (_running) setTimeout(_connectSSE, 3000); };
}

// ── Lead ──────────────────────────────────────────────────────────────────────
function _onLead(lead) {
  _allLeads.unshift(lead);
  _msgCount++;

  // Empty State entfernen
  document.getElementById('empty-state')?.remove();

  // Feed-Zähler
  document.getElementById('fb-count').textContent = _msgCount;

  // Hot-Badge
  if (lead.lead_typ === 'Hot') {
    _hotCount++;
    const hb = document.getElementById('feed-badge-hot');
    hb.style.display = 'flex';
    document.getElementById('fb-hot').textContent = _hotCount;
    _addHotCard(lead);
  }

  // Message in Feed
  const feed = document.getElementById('chat-feed');
  const el   = _buildMessage(lead);
  feed.insertBefore(el, feed.firstChild);

  // Max 300 Bubbles
  const msgs = feed.querySelectorAll('.msg-group');
  if (msgs.length > 300) msgs[msgs.length - 1].remove();

  _updateStats();
}

function _onError(msg) {
  const feed = document.getElementById('chat-feed');
  document.getElementById('empty-state')?.remove();
  const el = document.createElement('div');
  el.className   = 'msg-error';
  el.textContent = '⚠ ' + msg;
  feed.insertBefore(el, feed.firstChild);
}

// ── Message bauen ─────────────────────────────────────────────────────────────
function _buildMessage(lead) {
  const f     = _finder(lead.finder);
  const time  = new Date().toLocaleTimeString('de-DE', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
  const group = document.createElement('div');
  group.className = 'msg-group';

  // Web-Tag
  let webTag = '';
  if (!lead.has_website) {
    webTag = `<span class="lc-tag web-no">✗ Kein Website</span>`;
  } else if (lead.website_alter >= 0 && lead.website_alter < 3) {
    webTag = `<span class="lc-tag web-old">⚠ Website ${lead.website_alter}j alt</span>`;
  } else if (lead.website_alter >= 3) {
    webTag = `<span class="lc-tag web-old">⚠ Website ${lead.website_alter}j alt</span>`;
  }

  const telTag    = lead.telefon ? `<span class="lc-tag tel">✓ Telefon</span>` : '';
  const branchTag = lead.branche ? `<span class="lc-tag branch">${_esc(lead.branche)}</span>` : '';
  const bildTag   = lead.bilder  ? `<span class="lc-tag">📷 Bilder</span>` : '';

  const adrDetail = lead.adresse
    ? `<div class="lc-detail"><span class="lc-detail-icon">📍</span>${_esc(lead.adresse.substring(0,35))}${lead.adresse.length>35?'…':''}</div>`
    : '';
  const telDetail = lead.telefon
    ? `<div class="lc-detail"><span class="lc-detail-icon">📞</span>${_esc(lead.telefon)}</div>`
    : '';
  const ratDetail = lead.bewertung
    ? `<div class="lc-detail"><span class="lc-detail-icon">⭐</span>${lead.bewertung}${lead.anz_bewertungen ? ` (${lead.anz_bewertungen})`:''}</div>`
    : '';

  const leadJson = JSON.stringify(lead).replace(/"/g,'&quot;');

  group.innerHTML = `
    <div class="msg-header">
      <div class="sender-badge ${f.cls}">
        <div class="sender-avatar ${f.cls}">${f.label}</div>
        <span class="sender-name ${f.cls}">${f.name}</span>
      </div>
      <span class="msg-time">${time}</span>
    </div>
    <div class="lead-card ${lead.lead_typ}" data-id="${lead.id||0}" onclick='openModal(${leadJson})'>
      <div class="lc-top">
        <div class="lc-name">${_esc(lead.name)}</div>
        <div class="lc-score-block">
          <div class="lc-score-num ${lead.lead_typ}">${lead.score}</div>
          <div class="lc-score-lbl">${lead.lead_typ.toUpperCase()} LEAD</div>
        </div>
      </div>
      <div class="lc-tags">
        ${webTag}${telTag}${branchTag}${bildTag}
      </div>
      <div class="lc-bottom">
        ${adrDetail}${telDetail}${ratDetail}
      </div>
    </div>`;

  return group;
}

function _esc(s) {
  return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Hot Sidebar ───────────────────────────────────────────────────────────────
function _addHotCard(lead) {
  const list = document.getElementById('hot-list');
  list.querySelector('.hot-empty')?.remove();

  const card = document.createElement('div');
  card.className = 'hot-card';
  card.innerHTML = `
    <div class="hot-card-name">${_esc(lead.name)}</div>
    <div class="hot-card-meta">
      ${lead.branche ? `<span class="hot-tag">${_esc(lead.branche)}</span>` : ''}
      ${lead.stadt   ? `<span class="hot-tag">${_esc(lead.stadt)}</span>` : ''}
      <span class="hot-score">${lead.score}pt</span>
    </div>`;
  card.onclick = () => openModal(lead);
  list.insertBefore(card, list.firstChild);

  const cards = list.querySelectorAll('.hot-card');
  if (cards.length > 40) cards[cards.length - 1].remove();
}

// ── Stats ─────────────────────────────────────────────────────────────────────
function _updateStats() {
  const leads  = _allLeads;
  const total  = leads.length;
  const hot    = leads.filter(l => l.lead_typ === 'Hot').length;
  const warm   = leads.filter(l => l.lead_typ === 'Warm').length;
  const cold   = total - hot - warm;
  const noWeb  = leads.filter(l => !l.has_website).length;
  const hasTel = leads.filter(l => l.telefon).length;
  const pct    = total ? Math.round(noWeb / total * 100) : 0;

  document.getElementById('s-total').textContent = total;
  document.getElementById('s-hot').textContent   = hot;
  document.getElementById('s-warm').textContent  = warm;
  document.getElementById('s-cold').textContent  = cold;
  document.getElementById('s-noweb').textContent = pct + '%';
  document.getElementById('s-tel').textContent   = hasTel;

  // Fortschrittsbalken (visualisiert bis 500)
  document.getElementById('bar-total').style.width = Math.min(100, total / 5) + '%';

  // Finder-Liste
  const finders = {};
  leads.forEach(l => { if (l.finder) finders[l.finder] = (finders[l.finder]||0)+1; });
  const sl = document.getElementById('source-list');
  sl.innerHTML = Object.entries(finders).sort((a,b)=>b[1]-a[1]).map(([k,v]) => {
    const f = _finder(k);
    return `<div class="source-item">
      <div class="source-icon ${f.cls}">${f.label}</div>
      <div class="source-info">
        <div class="source-name">${f.name}</div>
        <div class="source-cnt">${v} Leads</div>
      </div>
    </div>`;
  }).join('');
}

async function _fetchStats() {
  try {
    const s = (await (await fetch('/api/status')).json()).stats;
    document.getElementById('s-total').textContent = s.total;
    document.getElementById('s-hot').textContent   = s.hot;
    document.getElementById('s-warm').textContent  = s.warm;
    document.getElementById('s-cold').textContent  = s.cold;
    document.getElementById('bar-total').style.width = Math.min(100, s.total / 5) + '%';
    const pct = s.total ? Math.round(s.no_web / s.total * 100) : 0;
    document.getElementById('s-noweb').textContent = pct + '%';
  } catch {}
}

// ── Filter ────────────────────────────────────────────────────────────────────
function applyFilter() {
  const fTyp = document.getElementById('flt-typ').value;
  const fWeb = document.getElementById('flt-web').value;
  const fBl  = document.getElementById('flt-bl').value;

  document.querySelectorAll('.msg-group').forEach(grp => {
    const card = grp.querySelector('.lead-card');
    if (!card) return;
    const id   = parseInt(card.dataset.id || '0');
    const lead = _allLeads.find(l => l.id === id);
    if (!lead) { grp.style.display = ''; return; }

    const typOk = !fTyp || lead.lead_typ === fTyp;
    const webOk = !fWeb || String(lead.has_website) === fWeb;
    const blOk  = !fBl  || lead.bundesland === fBl;
    grp.style.display = (typOk && webOk && blOk) ? '' : 'none';
  });
}

// ── Modal ──────────────────────────────────────────────────────────────────────
function openModal(lead) {
  const f  = _finder(lead.finder);
  const el = document.getElementById('modal-inner');

  const webRow = lead.has_website
    ? `<div class="modal-row"><span class="mrow-key">Website</span><span class="mrow-val warn"><a href="${_esc(lead.website_url)}" target="_blank">${_esc(lead.website_url||'Link öffnen')} ↗</a></span></div>
       <div class="modal-row"><span class="mrow-key">Website-Alter</span><span class="mrow-val ${lead.website_alter>4?'warn':''}">${lead.website_alter>=0 ? lead.website_alter+' Jahre' : 'unbekannt'}</span></div>`
    : `<div class="modal-row"><span class="mrow-key">Website</span><span class="mrow-val no">❌ Kein Website vorhanden</span></div>`;

  el.innerHTML = `
    <div class="modal-header">
      <div class="modal-type-badge ${lead.lead_typ}">${lead.lead_typ} Lead</div>
      <div class="modal-title">${_esc(lead.name)}</div>
      <button class="modal-close-btn" onclick="closeModal()">✕</button>
    </div>

    <div class="score-row">
      <span class="score-label">Score</span>
      <div class="score-bar"><div class="score-fill ${lead.lead_typ}" style="width:${lead.score}%"></div></div>
      <span class="score-num ${lead.lead_typ}">${lead.score}/100</span>
    </div>

    <div class="modal-section">
      <div class="modal-sec-title">Kontakt</div>
      ${lead.adresse  ? `<div class="modal-row"><span class="mrow-key">Adresse</span><span class="mrow-val">${_esc(lead.adresse)}</span></div>` : ''}
      ${lead.telefon  ? `<div class="modal-row"><span class="mrow-key">Telefon</span><span class="mrow-val ok">${_esc(lead.telefon)}</span></div>` : ''}
      <div class="modal-row"><span class="mrow-key">Stadt</span><span class="mrow-val">${_esc(lead.stadt||'')} · ${_esc(lead.bundesland||'')}</span></div>
      <div class="modal-row"><span class="mrow-key">Branche</span><span class="mrow-val">${_esc(lead.branche||'—')}</span></div>
    </div>

    <div class="modal-section">
      <div class="modal-sec-title">Online-Präsenz</div>
      ${webRow}
      <div class="modal-row"><span class="mrow-key">Bilder vorhanden</span><span class="mrow-val ${lead.bilder?'ok':'no'}">${lead.bilder?'✓ Ja':'✗ Nein'}</span></div>
    </div>

    ${lead.bewertung ? `<div class="modal-section">
      <div class="modal-sec-title">Bewertung</div>
      <div class="modal-row"><span class="mrow-key">Sterne</span><span class="mrow-val">⭐ ${lead.bewertung}</span></div>
      ${lead.anz_bewertungen ? `<div class="modal-row"><span class="mrow-key">Anzahl</span><span class="mrow-val">${lead.anz_bewertungen} Bewertungen</span></div>` : ''}
      ${lead.maps_url ? `<div class="modal-row"><span class="mrow-key">Google Maps</span><span class="mrow-val"><a href="${_esc(lead.maps_url)}" target="_blank">Öffnen ↗</a></span></div>` : ''}
    </div>` : ''}

    <div class="modal-section">
      <div class="modal-sec-title">Gefunden von</div>
      <div class="modal-finder ${f.cls}">
        <span class="modal-finder-icon">${f.icon}</span>
        <div class="modal-finder-info">
          <span class="modal-finder-name">${f.name}</span>
          <span class="modal-finder-sub">${f.sub} · ${lead.gefunden_am||'—'}</span>
        </div>
      </div>
    </div>`;

  document.getElementById('modal-bg').classList.add('open');
  document.getElementById('modal').classList.add('open');
}

function closeModal() {
  document.getElementById('modal-bg').classList.remove('open');
  document.getElementById('modal').classList.remove('open');
}
document.addEventListener('keydown', e => { if (e.key==='Escape') closeModal(); });

// ── Utilities ─────────────────────────────────────────────────────────────────
function clearFeed() {
  document.getElementById('chat-feed').innerHTML = `
    <div class="empty-state" id="empty-state">
      <div class="empty-arc"><svg width="60" height="60" viewBox="0 0 60 60"><circle cx="30" cy="30" r="26" fill="none" stroke="#182234" stroke-width="2"/><circle cx="30" cy="30" r="16" fill="none" stroke="#182234" stroke-width="2"/><circle cx="30" cy="30" r="6" fill="#182234"/></svg></div>
      <p class="empty-title">Feed geleert</p>
      <p class="empty-sub">Scraper läuft weiter im Hintergrund</p>
    </div>`;
  _allLeads = []; _msgCount = 0; _hotCount = 0;
  document.getElementById('fb-count').textContent = '0';
  document.getElementById('fb-hot').textContent   = '0';
  document.getElementById('feed-badge-hot').style.display = 'none';
  document.getElementById('hot-list').innerHTML = '<div class="hot-empty">Noch keine Hot Leads</div>';
  _updateStats();
}

function exportCSV() { window.location.href = '/api/export/csv'; }

// ── Init ──────────────────────────────────────────────────────────────────────
(async () => {
  try {
    const data = await (await fetch('/api/status')).json();
    if (data.running) {
      _running = true;
      _setRunningUI(true);
      _connectSSE();
      _statsTimer = setInterval(_fetchStats, 6000);
    }
    if (data.stats) {
      const s = data.stats;
      document.getElementById('s-total').textContent = s.total;
      document.getElementById('s-hot').textContent   = s.hot;
      document.getElementById('s-warm').textContent  = s.warm;
      document.getElementById('s-cold').textContent  = s.cold;
    }
  } catch {}
})();
