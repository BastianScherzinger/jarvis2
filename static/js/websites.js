// ════════════════════════════════════════════════════════════════════════════
//  WEBSEITEN-REITER — Tages-Ordner · Karten (eingeklappt)
//  Standard: alle Ordner UND alle Karten sind zugeklappt.
//  Im eingeklappten Zustand sieht man: Name · Meta · Stufen-Dots · Status · 📨
//  Discord-Versand-Status wird live aktualisiert (2,5s-Poll).
// ════════════════════════════════════════════════════════════════════════════
let _wsTimer       = null;
let _wsData        = [];   // flache Liste aller Seiten
let _wsDays        = [];   // gruppiert [{date, is_today, sites, count, limit, …}]
let _wsOpenDays    = null; // Set<string> — null = noch nicht initialisiert
let _wsCardOpen    = new Set(); // Set<string> — offene Karten-IDs
let _wsTotal       = 0;

function _wse(s){
  return String(s == null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function _wsAgo(ts){
  if(!ts) return '';
  const s = Math.max(0, Math.floor(Date.now()/1000 - ts));
  if(s < 60)    return 'gerade eben';
  if(s < 3600)  return 'vor ' + Math.floor(s/60) + ' Min';
  if(s < 86400) return 'vor ' + Math.floor(s/3600) + ' Std';
  return 'vor ' + Math.floor(s/86400) + ' Tg';
}

const _MONATE = ['Januar','Februar','März','April','Mai','Juni',
                 'Juli','August','September','Oktober','November','Dezember'];

function _wsDayLabel(dateStr, isToday){
  if(isToday) return 'Heute';
  if(!dateStr || dateStr === 'unbekannt') return 'Unbekannt';
  const yd = new Date(); yd.setDate(yd.getDate() - 1);
  if(dateStr === yd.toISOString().slice(0,10)) return 'Gestern';
  try{
    const [y,m,d] = dateStr.split('-').map(Number);
    return `${d}. ${_MONATE[m-1]} ${y}`;
  }catch(e){ return dateStr; }
}

const _WS_STATUS = {
  queued:  {cls:'queued',  lbl:'In Warteschlange'},
  running: {cls:'running', lbl:'Baut…'},
  done:    {cls:'done',    lbl:'● LIVE'},
  error:   {cls:'error',   lbl:'Fehler'},
};

function _wsBadge(w){
  if(w.status === 'done'){
    if(w.live)     return {cls:'done',     lbl:'● LIVE'};
    if(w.live_url) return {cls:'building', lbl:'Build läuft'};
    if(w.repo_url) return {cls:'building', lbl:'Nicht live'};
    return {cls:'queued', lbl:'Nur lokal'};
  }
  return _WS_STATUS[w.status] || {cls:'queued', lbl:w.status || '—'};
}

// ── Initialisierung & Timer ───────────────────────────────────────────────────
// Die komplette Fortschrittsansicht (Tages-Ordner + Karten) läuft doppelt: einmal im
// eigenen "Webseiten"-Tab (Namespace 'ws', Container #ws-list) und einmal kompakter
// eingebettet in "Mein Status" (Namespace 'msws', Container #ms-ws-list) — dieselben
// Daten (_wsDays/_wsData), aber eigene DOM-IDs pro Namespace (sonst doppelte IDs, da
// beide Container gleichzeitig im DOM stehen, nur eine Seite ist per CSS sichtbar).

function initWebsites(){ loadWebsites(); _wsEnsureTimer(); }
function refreshWebsites(){ loadWebsites(true); }

async function wsManualReload(){
  const btn = document.getElementById('ws-reload-btn');
  if(btn){ btn.classList.add('loading'); btn.disabled = true; }
  try{ await loadWebsites(false); }
  finally{
    if(btn){ btn.classList.remove('loading'); btn.disabled = false; }
  }
}

function _wsAnyTargetVisible(){
  const ws = document.querySelector('.websites-page');
  if(ws && ws.classList.contains('active')) return true;
  const ms = document.querySelector('.page[data-page="leads"]');
  return !!(ms && ms.classList.contains('active'));
}

function _wsEnsureTimer(){
  if(_wsTimer) return;
  _wsTimer = setInterval(() => {
    if(!_wsAnyTargetVisible()) return;
    loadWebsites(true);
  }, 7000);   // gedrosselt: 7 s reicht fürs Nachziehen, spart Log-/Server-Last
}

let _wsArchivedOpen = false;
let _wsArchivedDays = [];

// ── Daten laden ───────────────────────────────────────────────────────────────

async function loadWebsites(silent){
  try{
    const d = await(await fetch('/api/websites/grouped')).json();
    if(d && d.ok){
      _wsDays  = Array.isArray(d.days) ? d.days : [];
      _wsData  = _wsDays.flatMap(day => day.sites || []);
      _wsTotal = d.total || 0;
      const arcCnt = d.archived_count || 0;
      const arcSec = document.getElementById('ws-archive-section');
      const arcCount = document.getElementById('ws-archive-count');
      if(arcSec) arcSec.style.display = arcCnt > 0 ? '' : 'none';
      if(arcCount) arcCount.textContent = arcCnt + (arcCnt===1?' Seite':' Seiten');
    }
  }catch(e){ if(!silent){ _wsDays=[]; _wsData=[]; } else return; }

  // Alle Ordner standardmäßig zugeklappt — kein Auto-Öffnen von "Heute"
  if(_wsOpenDays === null){
    _wsOpenDays = new Set();
  }
  _renderWebsites();
}

async function loadArchived(){
  try{
    const d = await(await fetch('/api/websites/archived')).json();
    if(d && d.ok){ _wsArchivedDays = Array.isArray(d.days) ? d.days : []; }
  }catch(e){ _wsArchivedDays = []; }
  _renderArchived();
}

function wsToggleArchive(){
  _wsArchivedOpen = !_wsArchivedOpen;
  const body  = document.getElementById('ws-archive-body');
  const arrow = document.getElementById('ws-archive-arrow');
  if(_wsArchivedOpen){
    if(arrow) arrow.textContent = '▾';
    if(body) body.style.display = '';
    loadArchived();
  } else {
    if(arrow) arrow.textContent = '▸';
    if(body) body.style.display = 'none';
  }
}

function _renderArchived(){
  const body = document.getElementById('ws-archive-body');
  if(!body) return;
  if(!_wsArchivedDays.length){
    body.innerHTML = '<div class="ws-empty" style="padding:16px"><div class="empty-sub">Keine archivierten Seiten.</div></div>';
    return;
  }
  body.innerHTML = _wsArchivedDays.map(day => {
    const label = _wsDayLabel(day.date, false);
    return `<div class="ws-day ws-archived-day">
      <div class="ws-day-head ws-archived-day-head">
        <span class="ws-day-label">${_wse(label)}</span>
        <div class="ws-day-pills">
          <span class="ws-day-pill done">${day.count} Seiten</span>
        </div>
      </div>
      <div class="ws-day-body" style="opacity:0.65">
        ${(day.sites||[]).map(_wsArchivedCard).join('')}
      </div>
    </div>`;
  }).join('');
}

function _wsArchivedCard(w){
  const meta = [w.branche, w.stadt].filter(Boolean).map(_wse).join(' · ');
  const liveLink = w.live_url
    ? `<a class="ws-link live" href="${_wse(w.live_url)}" target="_blank" rel="noopener">🌐 ${_wse(w.live_url)} ↗</a>`
    : '';
  return `<div class="ws-card archived">
    <div class="ws-card-row" style="cursor:default">
      <div class="ws-card-info">
        <span class="ws-card-name">${_wse(w.name||'Unbenannt')}</span>
        ${meta ? `<span class="ws-card-meta">${meta}</span>` : ''}
      </div>
      <span class="ws-badge archived">Archiv</span>
    </div>
    ${liveLink ? `<div class="ws-links" style="padding-top:8px">${liveLink}</div>` : ''}
    <div class="ws-foot">${_wse(_wsAgo(w.updated||w.created))}</div>
  </div>`;
}

// ── Neu starten ───────────────────────────────────────────────────────────────

async function archiveAllAndStart(){
  const ok = confirm(
    '⚡ Neu starten\n\n'
    + 'Das archiviert alle aktuellen Webseiten und startet den Night-Builder neu.\n\n'
    + 'Leads werden nicht doppelt gebaut.\n\nFortfahren?'
  );
  if(!ok) return;
  const btn = document.querySelector('.ws-neu-btn');
  if(btn){ btn.disabled=true; btn.textContent='⏳ Starte…'; }
  try{
    const r = await(await fetch('/api/websites/archive_all', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({start_builder: true})
    })).json();
    if(r && r.ok){
      const msg = `✓ ${r.archived} Seite(n) archiviert.`
        + (r.builder_started ? '\n✓ Night-Builder gestartet.' : '\n(Builder lief bereits)');
      alert(msg);
      loadWebsites(false);
    } else {
      alert('Fehlgeschlagen: ' + ((r&&r.reason)||'unbekannt'));
    }
  }catch(e){ alert('Fehler: ' + e); }
  finally{
    if(btn){ btn.disabled=false; btn.textContent='⚡ Neu starten'; }
  }
}

// ── Render: Tages-Ordner ──────────────────────────────────────────────────────

function _renderWebsites(){
  _renderWebsitesInto('ws-list', 'ws-count', 'ws');
  _renderWebsitesInto('ms-ws-list', 'ms-ws-count', 'msws');
}

function _renderWebsitesInto(listId, countId, ns){
  const list = document.getElementById(listId);
  if(!list) return;   // Container aktuell nicht im DOM (z.B. andere Seite) → überspringen

  const total = _wsTotal || _wsData.length;
  if(countId){
    const cnt = document.getElementById(countId);
    if(cnt) cnt.textContent = total + (total === 1 ? ' Seite' : ' Seiten');
  }

  if(!_wsDays.length){
    list.innerHTML = `<div class="ws-empty">
      <div class="empty-icon">◎</div>
      <div class="empty-title">Noch keine Webseiten gebaut</div>
      <div class="empty-sub">Bei einem Lead auf „Webseite bauen" drücken — die Seite erscheint hier mit Live-Status.</div>
    </div>`;
    return;
  }

  list.innerHTML = _wsDays.map(day => _wsDayFolder(day, ns)).join('');
}

// ── Tages-Ordner ─────────────────────────────────────────────────────────────

function _wsDayFolder(day, ns='ws'){
  const open     = _wsOpenDays && _wsOpenDays.has(day.date);
  const label    = _wsDayLabel(day.date, day.is_today);
  const count    = day.count  || 0;
  const limit    = day.limit  || 10;
  const extra    = day.extra_count || 0;
  const autoCnt  = day.auto_count  || Math.min(count, limit);
  const pct      = Math.min(100, Math.round((autoCnt / limit) * 100));
  const full     = autoCnt >= limit;
  const running  = day.sites && day.sites.some(s => s.status === 'running');
  const liveN    = day.sites ? day.sites.filter(s => s.live).length : 0;
  const sentN    = day.sites ? day.sites.filter(s => s.email_sent).length : 0;

  const progBadge = full
    ? `<span class="ws-day-pill done">✓ ${limit}/${limit}</span>`
    : `<span class="ws-day-pill ${running?'running':'open'}">${autoCnt}/${limit}</span>`;
  const extraBadge = extra > 0
    ? `<span class="ws-day-pill extra">+${extra} Eigene</span>` : '';
  const liveBadge = liveN > 0
    ? `<span class="ws-day-pill live">● ${liveN} live</span>` : '';
  const sentBadge = sentN > 0
    ? `<span class="ws-day-pill sent">📨 ${sentN}</span>` : '';

  const bar = `<div class="ws-day-bar" title="${autoCnt} von ${limit} Auto-Seiten">
    <div class="ws-day-barfill ${full?'full':running?'running':''}" style="width:${pct}%"></div>
  </div>`;

  const bodyStyle = open ? '' : 'style="display:none"';
  const arrow     = open ? '▾' : '▸';

  // Nur der 'ws'-Namespace (dedizierter Webseiten-Tab) darf den ganzen Tag löschen —
  // in Mein Status ist das eine Fortschritts-ANZEIGE, keine Verwaltung, darum dort ohne
  // Lösch-Knopf (verhindert versehentliches Löschen aus der falschen Ansicht heraus).
  const delBtn = ns === 'ws'
    ? `<button class="ws-day-del" title="Ganzen Tag löschen (inkl. Railway)"
        onclick="event.stopPropagation(); wsDeleteDay('${_wse(day.date)}', ${count})">
        <svg viewBox="0 0 18 18" width="15" height="15" fill="none"><path d="M3 5h12M7 5V3.5A1.5 1.5 0 018.5 2h1A1.5 1.5 0 0111 3.5V5M5.5 5l.5 9a1.5 1.5 0 001.5 1.4h3a1.5 1.5 0 001.5-1.4l.5-9" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </button>`
    : '';

  return `<div class="ws-day ${open?'open':''}" id="${ns}-day-${_wse(day.date)}">
    <div class="ws-day-head" onclick="wsDayToggle('${_wse(day.date)}','${ns}')">
      <span class="ws-day-arrow">${arrow}</span>
      <span class="ws-day-label ${day.is_today?'today':''}">${_wse(label)}</span>
      <span class="ws-day-date-sub">${day.is_today ? _wse(day.date) : ''}</span>
      <div class="ws-day-pills">
        ${progBadge}${extraBadge}${liveBadge}${sentBadge}
      </div>
      ${delBtn}
      ${bar}
    </div>
    <div class="ws-day-body" ${bodyStyle}>
      ${(day.sites || []).map(w => _wsCard(w, ns)).join('')}
    </div>
  </div>`;
}

// ── Ordner auf-/zuklappen ─────────────────────────────────────────────────────

function wsDayToggle(date, ns='ws'){
  if(!_wsOpenDays) _wsOpenDays = new Set();
  const el   = document.getElementById(ns + '-day-' + date);
  if(!el) return;
  const body  = el.querySelector('.ws-day-body');
  const arrow = el.querySelector('.ws-day-arrow');
  if(_wsOpenDays.has(date)){
    _wsOpenDays.delete(date);
    el.classList.remove('open');
    if(body)  body.style.display = 'none';
    if(arrow) arrow.textContent = '▸';
  } else {
    _wsOpenDays.add(date);
    el.classList.add('open');
    if(body)  body.style.display = '';
    if(arrow) arrow.textContent = '▾';
  }
}

// ── Karte auf-/zuklappen ──────────────────────────────────────────────────────

function wsCardToggle(id, ns='ws'){
  const sid    = String(id);
  const detail = document.getElementById(ns + '-cd-' + sid);
  const arrow  = document.getElementById(ns + '-ca-' + sid);
  const card   = document.getElementById(ns + '-c-'  + sid);
  if(!detail) return;
  if(_wsCardOpen.has(sid)){
    _wsCardOpen.delete(sid);
    detail.style.display = 'none';
    if(arrow) arrow.textContent = '▸';
    if(card)  card.classList.remove('open');
  } else {
    _wsCardOpen.add(sid);
    detail.style.display = '';
    if(arrow) arrow.textContent = '▾';
    if(card)  card.classList.add('open');
  }
}

// ── Stufen-Stepper (volle Ansicht für Detail-Bereich) ────────────────────────

function _wsStages(w){
  const total = w.stages_total || 0;
  if(!total) return '';
  const done    = Math.max(0, Math.min(total, w.stages_done || 0));
  const labels  = w.stage_labels || [];
  const running = (w.status === 'running' || w.status === 'queued');
  const curIdx  = running ? Math.min(done, total - 1) : -1;
  let segs = '';
  for(let i = 0; i < total; i++){
    const cls = i < done ? 'done' : (i === curIdx ? 'cur' : 'pend');
    const lbl = labels[i] ? ` title="Stufe ${i+1}: ${_wse(labels[i])}"` : '';
    segs += `<span class="ws-seg ${cls}"${lbl}></span>`;
  }
  let txt;
  if(done >= total)        txt = `✓ Alle ${total} Stufen fertig`;
  else if(running && labels[curIdx]) txt = `Stufe ${done+1}/${total} · ${_wse(labels[curIdx])}`;
  else                     txt = `${done}/${total} Stufen`;
  return `<div class="ws-stages ${done>=total?'full':''}">
    <div class="ws-seg-row">${segs}</div>
    <span class="ws-stage-txt">${txt}</span>
  </div>`;
}

// ── Website-Karte (kompakte Zeile + aufklappbares Detail) ─────────────────────

function _wsCard(w, ns='ws'){
  const st   = _wsBadge(w);
  const meta = [w.branche, w.stadt].filter(Boolean).map(_wse).join(' · ');
  const sid  = String(w.id);
  const open = _wsCardOpen.has(sid);

  // Mini-Stufen-Dots für die Zusammenfassungszeile
  let miniDots = '';
  if(w.stages_total){
    const done = Math.min(w.stages_done || 0, w.stages_total);
    miniDots = `<span class="ws-stages-mini" title="${done}/${w.stages_total} Stufen">`;
    for(let i = 0; i < w.stages_total; i++){
      miniDots += `<span class="ws-sm-seg ${i < done ? 'done' : ''}"></span>`;
    }
    miniDots += `</span>`;
  }

  // Discord-Versandstatus-Badge
  const sentBadge = w.email_sent
    ? `<span class="ws-badge sent" title="E-Mail ${_wsAgo(w.email_sent_ts)} versandt">📨</span>`
    : '';

  // ── Zusammenfassungszeile (immer sichtbar) ──────────────────────────────────
  const summaryRow = `<div class="ws-card-row" onclick="wsCardToggle(${w.id},'${ns}')">
    <span class="ws-card-arrow" id="${ns}-ca-${sid}">${open ? '▾' : '▸'}</span>
    <div class="ws-card-info">
      <span class="ws-card-name">${_wse(w.name || 'Unbenannt')}</span>
      ${meta ? `<span class="ws-card-meta">${meta}</span>` : ''}
    </div>
    <div class="ws-card-right">
      ${miniDots}
      <span class="ws-badge ${st.cls}">${_wse(st.lbl)}</span>
      ${sentBadge}
    </div>
  </div>`;

  // ── Detail-Bereich (ein-/ausgeklappt) ───────────────────────────────────────
  const p = Math.max(0, Math.min(100, w.progress || 0));

  let progHtml = '';
  if(w.stages_total){ progHtml += _wsStages(w); }
  if(w.status === 'running' || w.status === 'queued'){
    progHtml += `<div class="ws-prog">
      <div class="ws-bar"><div class="ws-fill" style="width:${p}%"></div></div>
      <div class="ws-step"><span class="jc-spin"></span><span>${_wse(w.step || 'Arbeitet…')}</span><span class="ws-pct">${p}%</span></div>
    </div>`;
  } else if(w.status === 'error'){
    progHtml += `<div class="ws-errline">✕ ${_wse(w.error || w.step || 'Fehlgeschlagen')}</div>`;
  } else if(w.status === 'done' && !w.live && w.live_url){
    progHtml += `<div class="ws-hintline">⏳ ${_wse(w.step || 'Build läuft — in 1-2 Min erneut öffnen.')}</div>`;
  }

  // Links
  const links = [];
  if(w.live_url) links.push(`<a class="ws-link live" href="${_wse(w.live_url)}" target="_blank" rel="noopener">🌐 Live öffnen ↗</a>`);
  if(w.repo_url) links.push(`<a class="ws-link" href="${_wse(w.repo_url)}" target="_blank" rel="noopener">⎇ GitHub ↗</a>`);
  const linkRow = links.length ? `<div class="ws-links">${links.join('')}</div>` : '';

  // E-Mail-Zeile
  const emailRow = `<div class="ws-email">
    <span class="ws-email-ico">✉</span>
    ${w.kontakt_email
      ? `<code>${_wse(w.kontakt_email)}</code>`
      : `<span class="ws-email-none">Keine Kontakt-Mail</span>`}
    ${w.email_sent
      ? `<span class="ws-email-sent-tag">✓ Gesendet ${_wsAgo(w.email_sent_ts)}</span>`
      : ''}
    ${w.live_url
      ? `<button class="ws-copy" onclick="event.stopPropagation();wsPreviewEmail(${w.id})">Vorschau</button>`
      : ''}
  </div>`;

  // Aktionen (nur die wichtigsten)
  const actions = `<div class="ws-actions">
    <button class="ws-act" onclick="event.stopPropagation();wsSendOffer(${w.id},'test')" title="Test-Mail an dich senden">✉ Test-Mail</button>
    ${w.kontakt_email
      ? (w.email_sent
          ? `<button class="ws-act done-act" disabled title="Bereits versandt">📨 Gesendet</button>`
          : `<button class="ws-act mail" onclick="event.stopPropagation();wsSendOffer(${w.id},'real')" title="An Kunden senden">✉ An Kunde</button>`)
      : `<button class="ws-act" onclick="event.stopPropagation();wsFindContact(${w.id}, this)" title="Kontakt suchen">🔎 Kontakt</button>`}
    <button class="ws-act danger" onclick="event.stopPropagation();wsDelete(${w.id}, ${JSON.stringify(w.name||'')})" title="Löschen">🗑</button>
  </div>`;

  const detailHtml = `<div class="ws-card-detail" id="${ns}-cd-${sid}" style="${open ? '' : 'display:none'}">
    ${progHtml}
    ${linkRow}
    ${emailRow}
    ${actions}
    <div class="ws-foot">${_wse(_wsAgo(w.updated || w.created))}</div>
  </div>`;

  return `<div class="ws-card ${st.cls} ${open ? 'open' : ''}" id="${ns}-c-${sid}">
    ${summaryRow}
    ${detailHtml}
  </div>`;
}

// ── Aktionen ──────────────────────────────────────────────────────────────────

async function wsDelete(wid, name){
  const ok = confirm(`Webseite „${name||'?'}" komplett löschen?\n\n`
    + 'Das entfernt den lokalen Ordner, das GitHub-Repo und den Railway-Service.\n\nFortfahren?');
  if(!ok) return;
  try{
    const r = await(await fetch(`/api/websites/${wid}?folder=1&remote=1`, {method:'DELETE'})).json();
    if(r && r.ok){ loadWebsites(true); }
    else alert('Löschen fehlgeschlagen: ' + ((r && r.reason) || 'unbekannt'));
  }catch(e){ alert('Löschen fehlgeschlagen: ' + e); }
}

async function wsDeleteDay(date, count){
  const ok = confirm(`Den ganzen Tag ${date} mit ${count} Webseite(n) löschen?\n\n`
    + 'Das entfernt lokale Ordner, GitHub-Repos UND Railway-Services.\n\nFortfahren?');
  if(!ok) return;
  try{
    const r = await(await fetch(`/api/websites/day/${encodeURIComponent(date)}?folder=1&remote=1`,
      {method:'DELETE'})).json();
    if(r && r.ok){
      loadWebsites(true);
      if(typeof toast === 'function')
        toast(`Tag ${date}: ${r.deleted} Seite(n) gelöscht.`);
    } else {
      alert('Löschen fehlgeschlagen: ' + ((r && r.reason) || 'unbekannt'));
    }
  }catch(e){ alert('Löschen fehlgeschlagen: ' + e); }
}

async function wsPreviewEmail(wid){
  let bg = document.getElementById('ws-mail-bg');
  if(!bg){
    bg = document.createElement('div');
    bg.id = 'ws-mail-bg'; bg.className = 'ws-chat-bg';
    bg.innerHTML = `<div class="ws-chat ws-mail" onclick="event.stopPropagation()">
      <div class="ws-chat-head"><span>Angebots-Mail · Vorschau</span>
        <button class="ws-chat-x" onclick="document.getElementById('ws-mail-bg').classList.remove('open')">✕</button></div>
      <div class="ws-mail-meta" id="ws-mail-meta"></div>
      <iframe id="ws-mail-frame" class="ws-mail-frame" sandbox=""></iframe>
    </div>`;
    bg.onclick = () => bg.classList.remove('open');
    document.body.appendChild(bg);
  }
  const meta  = bg.querySelector('#ws-mail-meta');
  const frame = bg.querySelector('#ws-mail-frame');
  meta.innerHTML = '<span class="jc-spin"></span> lädt…';
  frame.srcdoc = '';
  bg.classList.add('open');
  try{
    const r = await(await fetch(`/api/websites/${wid}/offer-email/preview`)).json();
    if(r && r.ok){
      const linkBadge = r.link
        ? `<a href="${_wse(r.link)}" target="_blank" rel="noopener" class="ws-mail-link ${r.link_ok?'ok':'bad'}">
             ${r.link_ok ? '✓ Link erreichbar' : '⚠ Link nicht erreichbar'} · ${_wse(r.link)} ↗</a>`
        : '<span class="ws-mail-link bad">Kein Live-Link</span>';
      meta.innerHTML = `<div><b>An:</b> ${_wse(r.to||'—')}</div>
        <div><b>Betreff:</b> ${_wse(r.betreff||'')}</div>
        <div class="ws-mail-linkrow">${linkBadge}</div>`;
      frame.srcdoc = r.html || '';
    }else{
      meta.textContent = 'Vorschau fehlgeschlagen.';
    }
  }catch(e){ meta.textContent = 'Fehler: ' + e; }
}

async function wsFindContact(wid, btn){
  const o = btn ? btn.textContent : '';
  if(btn){ btn.disabled = true; btn.textContent = '🔎 sucht…'; }
  try{
    const r = await(await fetch(`/api/websites/${wid}/find-contact`, {method:'POST'})).json();
    if(r && r.ok){
      alert('✓ Kontakt: ' + r.email + (r.ansprechpartner ? '\nAnsprechpartner: ' + r.ansprechpartner : ''));
      loadWebsites(true);
    }else{
      alert('Keine öffentliche Kontaktadresse gefunden.'
        + ((r && r.website) ? '\n\nGefundene Website: ' + r.website : '')
        + '\n\nTipp: manuell ergänzen oder Discord-Freigabe abwarten.');
    }
  }catch(e){ alert('Kontakt-Suche fehlgeschlagen: ' + e); }
  finally{ if(btn){ btn.disabled = false; btn.textContent = o; } }
}

async function wsSendOffer(wid, mode){
  mode = mode || 'test';
  const frage = mode === 'real'
    ? 'Angebots-Mail JETZT an die echte Kontaktadresse senden?\n\nDies geht an einen echten Betrieb.'
    : 'Angebots-Mail als Test an dich senden?';
  if(!confirm(frage)) return;
  try{
    const r = await(await fetch(`/api/websites/${wid}/offer-email`, {method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({mode})})).json();
    if(r && r.ok){
      alert('✓ E-Mail gesendet an ' + r.to);
      if(mode === 'real') loadWebsites(true);
    }
    else if(r && r.status === 'deaktiviert'){
      alert('E-Mail-Versand ist noch aus.\n\n' + (r.hinweis || 'JARVIS_EMAIL_ENABLED=true in .env setzen.'));
    }else{
      alert('E-Mail fehlgeschlagen: ' + ((r && (r.reason || r.status)) || 'unbekannt')
        + (r && r.hinweis ? '\n\n' + r.hinweis : ''));
    }
  }catch(e){ alert('E-Mail fehlgeschlagen: ' + e); }
}

// Behalten für Rückwärtskompatibilität (werden aus dem Menü/Chat aufgerufen)
async function wsImprove(wid){
  if(!confirm('„Top verbessern" lässt 5 Profi-Agenten über die Seite gehen. Fortfahren?')) return;
  try{
    const r = await(await fetch(`/api/websites/${wid}/improve`, {method:'POST'})).json();
    if(r && r.ok){ loadWebsites(true); }
    else alert('Verbessern fehlgeschlagen: ' + ((r&&r.reason)||'unbekannt'));
  }catch(e){ alert('Verbessern fehlgeschlagen: ' + e); }
}

async function wsAdImages(wid){
  const w = _wsData.find(x => String(x.id) === String(wid)); if(!w) return;
  if(!confirm(`5 Werbe-Bilder für „${w.name||'?'}" generieren?`)) return;
  try{
    const r = await(await fetch('/api/media/generate/set', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({betrieb:w.name||'', branche:w.branche||'', stil:'fotorealistisch',
                           stimmung:'professionell', text_platz:true})})).json();
    if(r && r.ok) alert('✓ Werbe-Set wird generiert — im „Bilder"-Tab sichtbar.');
    else alert('Fehlgeschlagen: ' + ((r&&r.reason)||'unbekannt'));
  }catch(e){ alert('Fehlgeschlagen: ' + e); }
}

async function wsAdVideo(wid){
  const w = _wsData.find(x => String(x.id) === String(wid)); if(!w) return;
  const hf = confirm(`Werbevideo für „${w.name||'?'}" generieren?\nOK = Higgsfield · Abbrechen = lokal`);
  try{
    const r = await(await fetch('/api/media/generate/ad-video', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({betrieb:w.name||'', branche:w.branche||'', stil:'cinematisch',
                           stimmung:'professionell', backend: hf ? 'higgsfield':'local'})})).json();
    if(r && r.ok) alert('✓ Werbevideo wird erstellt — im „Video"-Tab sichtbar.');
    else alert('Fehlgeschlagen: ' + ((r&&r.reason)||'unbekannt'));
  }catch(e){ alert('Fehlgeschlagen: ' + e); }
}

function wsOpenChat(wid){
  let bg = document.getElementById('ws-chat-bg');
  if(!bg){
    bg = document.createElement('div');
    bg.id = 'ws-chat-bg'; bg.className = 'ws-chat-bg';
    bg.innerHTML = `<div class="ws-chat" onclick="event.stopPropagation()">
      <div class="ws-chat-head"><span>Mit Claude · verbessern &amp; debuggen</span>
        <button class="ws-chat-x" onclick="wsCloseChat()">✕</button></div>
      <div class="ws-chat-log" id="ws-chat-log"></div>
      <div class="ws-chat-in">
        <textarea id="ws-chat-text" rows="2" placeholder="Änderung beschreiben oder Frage stellen…"></textarea>
        <button class="ws-chat-send" id="ws-chat-send">Senden</button>
      </div></div>`;
    bg.onclick = wsCloseChat;
    document.body.appendChild(bg);
    bg.querySelector('#ws-chat-send').onclick = wsChatSend;
    bg.querySelector('#ws-chat-text').addEventListener('keydown', e=>{
      if(e.key==='Enter' && (e.ctrlKey||e.metaKey)){ e.preventDefault(); wsChatSend(); }
    });
  }
  bg.dataset.wid = wid;
  document.getElementById('ws-chat-log').innerHTML =
    '<div class="ws-chat-hint">Beschreibe eine Änderung oder stelle eine Frage zur Seite.</div>';
  bg.classList.add('open');
}
function wsCloseChat(){ const b=document.getElementById('ws-chat-bg'); if(b) b.classList.remove('open'); }

async function wsChatSend(){
  const bg = document.getElementById('ws-chat-bg');
  if(!bg) return;
  const wid = bg.dataset.wid;
  const ta  = document.getElementById('ws-chat-text');
  const log = document.getElementById('ws-chat-log');
  const q   = (ta.value || '').trim();
  if(!q) return;
  ta.value = '';
  log.insertAdjacentHTML('beforeend', `<div class="ws-msg user">${_wse(q)}</div>`);
  const wait = document.createElement('div');
  wait.className = 'ws-msg bot';
  wait.innerHTML = '<span class="jc-spin"></span> denkt nach…';
  log.appendChild(wait); log.scrollTop = log.scrollHeight;
  try{
    const r = await(await fetch(`/api/websites/${wid}/chat`, {method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({instruction:q})})).json();
    wait.remove();
    if(r && r.ok){
      let m = _wse(r.answer || 'Erledigt.');
      if(r.changed) m += '<div class="ws-msg-tag">✓ Änderung übernommen — wird neu deployt.</div>';
      log.insertAdjacentHTML('beforeend', `<div class="ws-msg bot">${m}</div>`);
      if(r.changed) loadWebsites(true);
    }else{
      log.insertAdjacentHTML('beforeend', `<div class="ws-msg bot err">✕ ${_wse((r&&r.reason)||'Fehler')}</div>`);
    }
  }catch(e){
    wait.remove();
    log.insertAdjacentHTML('beforeend', `<div class="ws-msg bot err">✕ ${_wse(String(e))}</div>`);
  }
  log.scrollTop = log.scrollHeight;
}

async function wsUploadImage(wid, input){
  const file = input && input.files && input.files[0];
  if(!file) return;
  const fd = new FormData();
  fd.append('image', file);
  try{
    const r = await(await fetch(`/api/websites/${wid}/image`, {method:'POST', body:fd})).json();
    if(r && r.ok){ loadWebsites(true); }
    else alert('Bild-Upload fehlgeschlagen: ' + ((r && r.reason) || 'unbekannt'));
  }catch(e){ alert('Bild-Upload fehlgeschlagen: ' + e); }
  finally{ if(input) input.value = ''; }
}

function wsCopy(text, btn){
  try{
    navigator.clipboard.writeText(text);
    if(btn){ const o = btn.textContent; btn.textContent = '✓'; setTimeout(()=>btn.textContent = o, 1200); }
  }catch(e){}
}

_wsEnsureTimer();
document.addEventListener('DOMContentLoaded', () => {
  // 'leads' (Mein Status) ist die Default-Seite beim kalten Laden — dort steckt jetzt
  // auch die eingebettete Webseiten-Fortschrittsliste, darum hier zusätzlich prüfen.
  if(_wsAnyTargetVisible()) loadWebsites();
});
