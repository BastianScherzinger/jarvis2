// ════════════════════════════════════════════════════════════════════════════
//  WEBSEITEN-REITER — Tages-Ordner-Ansicht.
//  Seiten werden nach Bautag gruppiert in aufklappbaren Ordnern gezeigt.
//  Heute ist standardmäßig offen, Vortage zugeklappt.
//  Aufklapp-Zustand überlebt den 2,5s-Live-Poll.
// ════════════════════════════════════════════════════════════════════════════
let _wsTimer       = null;
let _wsData        = [];   // flache Liste aller Seiten (für wsAdImages etc.)
let _wsDays        = [];   // gruppiert [{date, is_today, sites, count, limit, …}]
let _wsOpenDays    = null; // Set<string> — null = noch nicht initialisiert
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

// Deutsches Datumslabel für den Ordner-Header
const _MONATE = ['Januar','Februar','März','April','Mai','Juni',
                 'Juli','August','September','Oktober','November','Dezember'];

function _wsDayLabel(dateStr, isToday){
  if(isToday) return 'Heute';
  if(!dateStr || dateStr === 'unbekannt') return 'Unbekannt';
  // Gestern?
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

function initWebsites(){ loadWebsites(); _wsEnsureTimer(); }
function refreshWebsites(){ loadWebsites(true); }

function _wsEnsureTimer(){
  if(_wsTimer) return;
  _wsTimer = setInterval(() => {
    const pg = document.querySelector('.websites-page');
    if(!pg || !pg.classList.contains('active')) return;
    loadWebsites(true);
  }, 2500);
}

// ── Daten laden ───────────────────────────────────────────────────────────────

async function loadWebsites(silent){
  try{
    const d = await(await fetch('/api/websites/grouped')).json();
    if(d && d.ok){
      _wsDays  = Array.isArray(d.days) ? d.days : [];
      _wsData  = _wsDays.flatMap(day => day.sites || []);
      _wsTotal = d.total || 0;
    }
  }catch(e){ if(!silent){ _wsDays=[]; _wsData=[]; } else return; }

  // Beim allerersten Laden: heute öffnen, alles andere schließen
  if(_wsOpenDays === null){
    _wsOpenDays = new Set();
    const todayDay = _wsDays.find(d => d.is_today);
    if(todayDay) _wsOpenDays.add(todayDay.date);
  }
  _renderWebsites();
}

// ── Render: Tages-Ordner-Ansicht ──────────────────────────────────────────────

function _renderWebsites(){
  const list = document.getElementById('ws-list');
  const cnt  = document.getElementById('ws-count');
  if(!list) return;

  const total = _wsTotal || _wsData.length;
  if(cnt) cnt.textContent = total + (total === 1 ? ' Seite' : ' Seiten');

  if(!_wsDays.length){
    list.innerHTML = `<div class="ws-empty">
      <div class="empty-icon">◎</div>
      <div class="empty-title">Noch keine Webseiten gebaut</div>
      <div class="empty-sub">Bei einem Lead auf „Webseite bauen" drücken — die Seite erscheint hier mit Live-Status.</div>
    </div>`;
    return;
  }

  list.innerHTML = _wsDays.map(_wsDayFolder).join('');
}

// Ein Tages-Ordner
function _wsDayFolder(day){
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

  // Fortschritts-Badge
  const progBadge = full
    ? `<span class="ws-day-pill done">✓ ${limit}/${limit}</span>`
    : `<span class="ws-day-pill ${running?'running':'open'}">${autoCnt}/${limit}</span>`;
  const extraBadge = extra > 0
    ? `<span class="ws-day-pill extra">+${extra} Eigene</span>` : '';
  const liveBadge = liveN > 0
    ? `<span class="ws-day-pill live">● ${liveN} live</span>` : '';

  // Fortschrittsbalken im Header
  const bar = `<div class="ws-day-bar" title="${autoCnt} von ${limit} Auto-Seiten">
    <div class="ws-day-barfill ${full?'full':running?'running':''}" style="width:${pct}%"></div>
  </div>`;

  const bodyStyle = open ? '' : 'style="display:none"';
  const arrow     = open ? '▾' : '▸';

  return `<div class="ws-day ${open?'open':''}" id="ws-day-${_wse(day.date)}">
    <div class="ws-day-head" onclick="wsDayToggle('${_wse(day.date)}')">
      <span class="ws-day-arrow">${arrow}</span>
      <span class="ws-day-label ${day.is_today?'today':''}">${_wse(label)}</span>
      <span class="ws-day-date-sub">${day.is_today ? _wse(day.date) : ''}</span>
      <div class="ws-day-pills">
        ${progBadge}${extraBadge}${liveBadge}
      </div>
      ${bar}
    </div>
    <div class="ws-day-body" ${bodyStyle}>
      ${(day.sites || []).map(_wsCard).join('')}
    </div>
  </div>`;
}

// ── Ordner auf-/zuklappen ─────────────────────────────────────────────────────

function wsDayToggle(date){
  if(!_wsOpenDays) _wsOpenDays = new Set();
  const el   = document.getElementById('ws-day-' + date);
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

// ── Website-Karte (unverändert, nur hierher verschoben) ───────────────────────

function _wsCard(w){
  const st   = _wsBadge(w);
  const meta = [w.branche, w.stadt].filter(Boolean).map(_wse).join(' · ');
  const p    = Math.max(0, Math.min(100, w.progress || 0));

  let prog = '';
  if(w.status === 'running' || w.status === 'queued'){
    prog = `<div class="ws-prog">
      <div class="ws-bar"><div class="ws-fill" style="width:${p}%"></div></div>
      <div class="ws-step"><span class="jc-spin"></span><span>${_wse(w.step || 'Arbeitet…')}</span><span class="ws-pct">${p}%</span></div>
    </div>`;
  }else if(w.status === 'error'){
    prog = `<div class="ws-errline">✕ ${_wse(w.error || w.step || 'Fehlgeschlagen')}</div>`;
  }else if(w.status === 'done' && !w.live && w.live_url){
    prog = `<div class="ws-hintline">⏳ ${_wse(w.step || 'Build läuft — in 1-2 Min erneut öffnen.')}</div>`;
  }else if(w.status === 'done' && !w.live_url){
    prog = `<div class="ws-hintline">${_wse(w.step || 'Lokal gebaut — noch nicht deployt.')}</div>`;
  }

  const links = [];
  if(w.live_url) links.push(`<a class="ws-link live" href="${_wse(w.live_url)}" target="_blank" rel="noopener">🌐 Live öffnen ↗</a>`);
  if(w.repo_url) links.push(`<a class="ws-link" href="${_wse(w.repo_url)}" target="_blank" rel="noopener">⎇ GitHub-Repo ↗</a>`);
  const linkRow = links.length ? `<div class="ws-links">${links.join('')}</div>` : '';

  const folder = w.folder
    ? `<div class="ws-folder" title="Lokaler Projektordner"><span class="ws-folder-ico">📁</span>
         <code>${_wse(w.folder)}</code>
         <button class="ws-copy" onclick="wsCopy('${_wse(w.folder).replace(/'/g,"\\'")}', this)">Kopieren</button></div>`
    : '';

  const emailRow = `<div class="ws-email">
      <span class="ws-email-ico">✉</span>
      ${w.kontakt_email
        ? `<code>${_wse(w.kontakt_email)}</code>`
        : `<span class="ws-email-none">keine Kontakt-E-Mail (über „Kontakt finden")</span>`}
      ${w.live_url ? `<button class="ws-copy" onclick='wsPreviewEmail(${w.id})' title="Angebots-Mail mit Live-Link ansehen">E-Mail ansehen</button>` : ''}
    </div>`;

  const ready  = !!w.folder;
  const thumbs = (w.images || []).map(fn => {
    const src = /^https?:\/\//i.test(fn) ? fn : `/api/websites/${w.id}/asset/${encodeURIComponent(fn)}`;
    return `<a class="ws-thumb" href="${_wse(src)}" target="_blank" rel="noopener" title="${_wse(fn)}">
       <img src="${_wse(src)}" alt="Bild" loading="lazy"></a>`;
  }).join('');
  const addBtn = ready
    ? `<label class="ws-add" title="Bild zur Seite hinzufügen (für späteren Einsatz)">
         <input type="file" accept="image/*" hidden onchange="wsUploadImage(${w.id}, this)">
         <span class="ws-add-plus">＋</span><span>Bild</span>
       </label>`
    : `<span class="ws-add disabled" title="Ordner wird noch erstellt">＋ Bild</span>`;
  const integrate = ready ? `
      <textarea class="ws-textarea" id="ws-txt-${w.id}" rows="2" placeholder="Text einfügen, den Claude sinnvoll einbauen soll (z.B. Über-uns, Leistung, Angebot) …"></textarea>
      <div class="ws-int-row">
        <button class="ws-act mail" onclick='wsIntegrate(${w.id})'>✨ Von Claude einbauen lassen</button>
        <span class="ws-int-out" id="ws-int-${w.id}"></span>
      </div>` : '';
  const media = `<div class="ws-media">
      <div class="ws-media-lbl">Inhalte einbauen — Bilder &amp; Text${(w.images && w.images.length) ? ' · ' + w.images.length + ' Bild(er)' : ''}</div>
      <div class="ws-thumbs">${thumbs}${addBtn}</div>
      ${integrate}
    </div>`;

  return `<div class="ws-card ${st.cls}">
    <div class="ws-card-head">
      <div class="ws-card-titlewrap">
        <div class="ws-card-title">${_wse(w.name || 'Unbenannt')}</div>
        ${meta ? `<div class="ws-card-meta">${meta}</div>` : ''}
      </div>
      <span class="ws-badge ${st.cls}">${_wse(st.lbl)}</span>
    </div>
    ${prog}
    ${linkRow}
    ${folder}
    ${emailRow}
    ${media}
    <div class="ws-actions">
      <button class="ws-act" onclick='wsImprove(${w.id})' title="5 Profi-Agenten verbessern Design, Texte &amp; Bilder">✦ Top verbessern</button>
      <button class="ws-act" onclick='wsAdImages(${w.id})' title="5 Werbe-Bilder für diesen Betrieb generieren">🖼 Werbebilder</button>
      <button class="ws-act" onclick='wsAdVideo(${w.id})' title="Werbevideo für diesen Betrieb generieren">🎬 Werbevideo</button>
      <button class="ws-act" onclick='wsOpenChat(${w.id})' title="Mit Claude debuggen / gezielt verbessern">⌥ Mit Claude</button>
      <button class="ws-act" onclick='wsSendOffer(${w.id}, "test")' title="Angebots-Mail (350 €) zum Test an dich senden">✉ Test an mich</button>
      ${w.kontakt_email
        ? `<button class="ws-act mail" onclick='wsSendOffer(${w.id}, "real")' title="An ${_wse(w.kontakt_email)} senden">✉ An Kunde senden</button>`
        : `<button class="ws-act" onclick='wsFindContact(${w.id}, this)' title="Kontaktadresse des Betriebs aktiv suchen (Impressum / Google)">🔎 Kontakt finden</button>`}
      <button class="ws-act danger" onclick='wsDelete(${w.id}, ${JSON.stringify(w.name||"")})' title="Webseite komplett löschen">🗑 Löschen</button>
    </div>
    <div class="ws-foot">${_wse(_wsAgo(w.updated || w.created))}</div>
  </div>`;
}

// ── Aktionen (unverändert) ────────────────────────────────────────────────────

async function wsDelete(wid, name){
  const ok = confirm(`Webseite „${name||'?'}" komplett löschen?\n\n`
    + 'Das entfernt den lokalen Ordner und (falls möglich) das GitHub-Repo '
    + 'und den Railway-Service.\n\nAbbrechen = nichts löschen.');
  if(!ok) return;
  try{
    const r = await(await fetch(`/api/websites/${wid}?folder=1&remote=1`, {method:'DELETE'})).json();
    if(r && r.ok){ loadWebsites(true); }
    else alert('Löschen fehlgeschlagen: ' + ((r && r.reason) || 'unbekannt'));
  }catch(e){ alert('Löschen fehlgeschlagen: ' + e); }
}

async function wsImprove(wid){
  const ok = confirm('„Top verbessern" lässt 5 Profi-Agenten über die Seite gehen '
    + '(Design, Texte, Referenzbilder, Über-uns, FAQ) und deployt neu.\n\n'
    + 'Das überschreibt das aktuelle Design & die Texte mit verbesserten Versionen. Fortfahren?');
  if(!ok) return;
  try{
    const r = await(await fetch(`/api/websites/${wid}/improve`, {method:'POST'})).json();
    if(r && r.ok){ loadWebsites(true); }
    else alert('Verbessern fehlgeschlagen: ' + ((r&&r.reason)||'unbekannt'));
  }catch(e){ alert('Verbessern fehlgeschlagen: ' + e); }
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
             ${r.link_ok ? '✓ Link funktioniert' : '⚠ Link nicht erreichbar'} · ${_wse(r.link)} ↗</a>`
        : '<span class="ws-mail-link bad">Kein Live-Link vorhanden</span>';
      meta.innerHTML = `<div><b>An:</b> ${_wse(r.to||'—')}</div>
        <div><b>Betreff:</b> ${_wse(r.betreff||'')}</div>
        <div class="ws-mail-linkrow">${linkBadge}</div>`;
      frame.srcdoc = r.html || '';
    }else{
      meta.textContent = 'Vorschau fehlgeschlagen.';
    }
  }catch(e){ meta.textContent = 'Fehler: ' + e; }
}

async function wsAdImages(wid){
  const w = _wsData.find(x => String(x.id) === String(wid)); if(!w) return;
  if(!confirm(`5 Werbe-Bilder für „${w.name||'?'}" generieren?\n\nLäuft im Hintergrund — die Bilder erscheinen im „Bilder"-Tab.`)) return;
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
  const hf = confirm(`Werbevideo für „${w.name||'?'}" generieren?\n\n`
    + 'OK = Higgsfield Cloud (Qualität, braucht Credits)\nAbbrechen = lokal (Wan 2.1).');
  try{
    const r = await(await fetch('/api/media/generate/ad-video', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({betrieb:w.name||'', branche:w.branche||'', stil:'cinematisch',
                           stimmung:'professionell', backend: hf ? 'higgsfield':'local'})})).json();
    if(r && r.ok) alert('✓ Werbevideo wird erstellt — im „Video"-Tab sichtbar.');
    else alert('Fehlgeschlagen: ' + ((r&&r.reason)||'unbekannt'));
  }catch(e){ alert('Fehlgeschlagen: ' + e); }
}

async function wsFindContact(wid, btn){
  const o = btn ? btn.textContent : '';
  if(btn){ btn.disabled = true; btn.textContent = '🔎 sucht…'; }
  try{
    const r = await(await fetch(`/api/websites/${wid}/find-contact`, {method:'POST'})).json();
    if(r && r.ok){
      alert('✓ Kontakt gefunden: ' + r.email + (r.ansprechpartner ? '\n\nAnsprechpartner: ' + r.ansprechpartner : ''));
      loadWebsites(true);
    }else{
      alert('Keine öffentliche Kontaktadresse gefunden.'
        + ((r && r.website) ? '\n\nGefundene Website: ' + r.website : '')
        + '\n\nTipp: über „Mit Claude" oder manuell ergänzen.');
    }
  }catch(e){ alert('Kontakt-Suche fehlgeschlagen: ' + e); }
  finally{ if(btn){ btn.disabled = false; btn.textContent = o; } }
}

async function wsSendOffer(wid, mode){
  mode = mode || 'test';
  const frage = mode === 'real'
    ? 'Angebots-Mail (350 €) JETZT an die ECHTE Kontaktadresse des Kunden senden?\n\nDies geht an einen echten Betrieb.'
    : 'Angebots-Mail (350 €) als Test an dich (bastian.scherzinger05@gmail.com) senden?';
  if(!confirm(frage)) return;
  try{
    const r = await(await fetch(`/api/websites/${wid}/offer-email`, {method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({mode})})).json();
    if(r && r.ok){ alert('✓ E-Mail gesendet an ' + r.to); }
    else if(r && r.status === 'deaktiviert'){
      alert('E-Mail-Versand ist noch aus.\n\n' + (r.hinweis || 'JARVIS_EMAIL_ENABLED=true in der .env setzen.'));
    }else{
      alert('E-Mail fehlgeschlagen: ' + ((r && (r.reason || r.status)) || 'unbekannt')
        + (r && r.hinweis ? '\n\n' + r.hinweis : ''));
    }
  }catch(e){ alert('E-Mail fehlgeschlagen: ' + e); }
}

function wsOpenChat(wid){
  let bg = document.getElementById('ws-chat-bg');
  if(!bg){
    bg = document.createElement('div');
    bg.id = 'ws-chat-bg'; bg.className = 'ws-chat-bg';
    bg.innerHTML = `<div class="ws-chat" onclick="event.stopPropagation()">
      <div class="ws-chat-head"><span>Mit Claude · verbessern &amp; debuggen</span>
        <button class="ws-chat-x" onclick="wsCloseChat()" aria-label="Schließen">✕</button></div>
      <div class="ws-chat-log" id="ws-chat-log"></div>
      <div class="ws-chat-in">
        <textarea id="ws-chat-text" rows="2" placeholder="z.B. „Mach die Headline knackiger und die Akzentfarbe dunkelblau" — oder stell eine Frage zur Seite."></textarea>
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
    '<div class="ws-chat-hint">Beschreibe eine Änderung (wird umgesetzt &amp; neu deployt) oder stelle eine Frage zur Seite.</div>';
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
      let m = _wse(r.answer || 'Erledigt, Sir.');
      if(r.changed) m += '<div class="ws-msg-tag">✓ Änderung übernommen — Seite wird neu deployt.</div>';
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

async function wsIntegrate(wid){
  const ta  = document.getElementById('ws-txt-'+wid);
  const out = document.getElementById('ws-int-'+wid);
  const text = (ta && ta.value || '').trim();
  if(!text && !confirm('Kein Text eingegeben — nur die hochgeladenen Bilder einbauen lassen?')) return;
  if(out){ out.textContent = 'Claude baut ein …'; out.className = 'ws-int-out busy'; }
  try{
    const r = await(await fetch(`/api/websites/${wid}/integrate`, {method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({text})})).json();
    if(r && r.ok){
      if(out){ out.textContent = '✓ ' + (r.answer || 'eingebaut') + (r.changed ? ' — wird neu deployt.' : ''); out.className='ws-int-out ok'; }
      if(ta) ta.value='';
      if(r.changed) loadWebsites(true);
    }else{
      if(out){ out.textContent = '✕ ' + ((r && r.reason) || 'Fehler'); out.className='ws-int-out err'; }
    }
  }catch(e){ if(out){ out.textContent = '✕ ' + e; out.className='ws-int-out err'; } }
}

function wsCopy(text, btn){
  try{
    navigator.clipboard.writeText(text);
    if(btn){ const o = btn.textContent; btn.textContent = '✓'; setTimeout(()=>btn.textContent = o, 1200); }
  }catch(e){}
}

// Timer + DOMContentLoaded (wie zuvor)
_wsEnsureTimer();
document.addEventListener('DOMContentLoaded', () => {
  const pg = document.querySelector('.websites-page');
  if(pg && pg.classList.contains('active')) loadWebsites();
});
