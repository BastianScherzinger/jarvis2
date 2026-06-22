// ════════════════════════════════════════════════════════════════════════════
//  WEBSEITEN-REITER — persistente Übersicht aller generierten Lead-Seiten.
//  Zeigt Live-Status (Fortschritt), Live-Link, GitHub-Repo, lokalen Ordner und
//  erlaubt das Hinzufügen von Bildern (für späteren Einsatz). Der Bau läuft
//  serverseitig im Hintergrund weiter — der Reiter pollt nur den Stand.
// ════════════════════════════════════════════════════════════════════════════
let _wsTimer = null;
let _wsData  = [];

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

const _WS_STATUS = {
  queued:  {cls:'queued',  lbl:'In Warteschlange'},
  running: {cls:'running', lbl:'Baut…'},
  done:    {cls:'done',    lbl:'● LIVE'},
  error:   {cls:'error',   lbl:'Fehler'},
};

// Echter Status-Badge: bei 'done' zählt das verifizierte live-Flag, nicht nur
// das Vorhandensein einer Domain (Railway-Domain existiert vor dem Build).
function _wsBadge(w){
  if(w.status === 'done'){
    if(w.live) return {cls:'done', lbl:'● LIVE'};
    if(w.live_url) return {cls:'building', lbl:'Build läuft'};
    if(w.repo_url) return {cls:'building', lbl:'Nicht live'};
    return {cls:'queued', lbl:'Nur lokal'};
  }
  return _WS_STATUS[w.status] || {cls:'queued', lbl:w.status || '—'};
}

function initWebsites(){ loadWebsites(); _wsEnsureTimer(); }

// Von app.js nach Bau-Start / Bau-Ende aufgerufen — Liste sofort nachziehen.
function refreshWebsites(){ loadWebsites(true); }

function _wsEnsureTimer(){
  if(_wsTimer) return;
  _wsTimer = setInterval(() => {
    const pg = document.querySelector('.websites-page');
    if(!pg || !pg.classList.contains('active')) return;     // nur der sichtbare Reiter pollt
    loadWebsites(true);                                      // solange sichtbar: Live-Stand nachziehen
  }, 2500);
}

async function loadWebsites(silent){
  try{
    const d = await(await fetch('/api/websites')).json();
    _wsData = (d && d.ok && Array.isArray(d.websites)) ? d.websites : [];
  }catch(e){ if(!silent) _wsData = []; else return; }
  _renderWebsites();
}

function _renderWebsites(){
  const list = document.getElementById('ws-list');
  const cnt  = document.getElementById('ws-count');
  if(!list) return;
  if(cnt) cnt.textContent = _wsData.length + (_wsData.length === 1 ? ' Seite' : ' Seiten');

  if(!_wsData.length){
    list.innerHTML = `<div class="ws-empty" id="ws-empty">
      <div class="empty-icon">◎</div>
      <div class="empty-title">Noch keine Webseiten gebaut</div>
      <div class="empty-sub">Bei einem Lead auf „Webseite bauen“ drücken — die Seite erscheint hier mit Live-Status.</div>
    </div>`;
    return;
  }
  list.innerHTML = _wsData.map(_wsCard).join('');
}

function _wsCard(w){
  const st   = _wsBadge(w);
  const meta = [w.branche, w.stadt].filter(Boolean).map(_wse).join(' · ');
  const p    = Math.max(0, Math.min(100, w.progress || 0));

  // Fortschritt / Statushinweis
  let prog = '';
  if(w.status === 'running' || w.status === 'queued'){
    prog = `<div class="ws-prog">
      <div class="ws-bar"><div class="ws-fill" style="width:${p}%"></div></div>
      <div class="ws-step"><span class="jc-spin"></span><span>${_wse(w.step || 'Arbeitet…')}</span><span class="ws-pct">${p}%</span></div>
    </div>`;
  }else if(w.status === 'error'){
    prog = `<div class="ws-errline">✕ ${_wse(w.error || w.step || 'Fehlgeschlagen')}</div>`;
  }else if(w.status === 'done' && !w.live && w.live_url){
    // Domain steht, Build evtl. noch nicht erreichbar — ehrlich anzeigen.
    prog = `<div class="ws-hintline">⏳ ${_wse(w.step || 'Build läuft — in 1-2 Min erneut öffnen.')}</div>`;
  }else if(w.status === 'done' && !w.live_url){
    prog = `<div class="ws-hintline">${_wse(w.step || 'Lokal gebaut — noch nicht deployt.')}</div>`;
  }

  // Links + Ordner
  const links = [];
  if(w.live_url) links.push(`<a class="ws-link live" href="${_wse(w.live_url)}" target="_blank" rel="noopener">🌐 Live öffnen ↗</a>`);
  if(w.repo_url) links.push(`<a class="ws-link" href="${_wse(w.repo_url)}" target="_blank" rel="noopener">⎇ GitHub-Repo ↗</a>`);
  const linkRow = links.length ? `<div class="ws-links">${links.join('')}</div>` : '';
  const folder  = w.folder
    ? `<div class="ws-folder" title="Lokaler Projektordner"><span class="ws-folder-ico">📁</span>
         <code>${_wse(w.folder)}</code>
         <button class="ws-copy" onclick="wsCopy('${_wse(w.folder).replace(/'/g,"\\'")}', this)">Kopieren</button></div>`
    : '';

  // Bilder (für später) + Hinzufügen
  const ready = !!w.folder;
  const thumbs = (w.images || []).map(fn => {
    // Cloud-URL (http…) direkt anzeigen, lokalen Dateinamen über die Asset-Route.
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
    ${media}
    <div class="ws-actions">
      <button class="ws-act" onclick='wsImprove(${w.id})' title="5 Profi-Agenten verbessern Design, Texte & Bilder">✦ Top verbessern</button>
      <button class="ws-act" onclick='wsOpenChat(${w.id})' title="Mit Claude debuggen / gezielt verbessern">⌥ Mit Claude</button>
      <button class="ws-act" onclick='wsSendOffer(${w.id}, "test")' title="Angebots-Mail (350 €) zum Test an dich senden">✉ Test an mich</button>
      <button class="ws-act mail" onclick='wsSendOffer(${w.id}, "real")' title="${w.kontakt_email ? 'An '+_wse(w.kontakt_email)+' senden' : 'Keine Kontakt-E-Mail gefunden'}"${w.kontakt_email ? '' : ' disabled'}>✉ An Kunde senden</button>
      <button class="ws-act danger" onclick='wsDelete(${w.id}, ${JSON.stringify(w.name||"")})' title="Webseite komplett löschen">🗑 Löschen</button>
    </div>
    <div class="ws-foot">${_wse(_wsAgo(w.updated || w.created))}</div>
  </div>`;
}

async function wsDelete(wid, name){
  const ok = confirm(`Webseite „${name||'?'}" komplett löschen?\n\n`
    + 'Das entfernt den lokalen Ordner und (falls möglich) das GitHub-Repo '
    + 'und den Railway-Service.\n\nAbbrechen = nichts löschen.');
  if(!ok) return;
  try{
    const r = await(await fetch(`/api/websites/${wid}?folder=1&remote=1`, {method:'DELETE'})).json();
    if(r && r.ok){
      loadWebsites(true);
    }else{
      alert('Löschen fehlgeschlagen: ' + ((r && r.reason) || 'unbekannt'));
    }
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

// ── Mit-Claude-Modal (verbessern / debuggen) ────────────────────────────────
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
    if(r && r.ok){
      loadWebsites(true);
    }else{
      alert('Bild-Upload fehlgeschlagen: ' + ((r && r.reason) || 'unbekannt'));
    }
  }catch(e){ alert('Bild-Upload fehlgeschlagen: ' + e); }
  finally{ if(input) input.value = ''; }
}

async function wsIntegrate(wid){
  const ta = document.getElementById('ws-txt-'+wid);
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

// Timer sofort starten (deckt auch Hard-Reload direkt auf #websites ab — app.js'
// showPage kann laufen, bevor diese Datei geladen ist). Gefetcht wird nur, wenn
// der Reiter sichtbar ist.
_wsEnsureTimer();
document.addEventListener('DOMContentLoaded', () => {
  const pg = document.querySelector('.websites-page');
  if(pg && pg.classList.contains('active')) loadWebsites();
});
