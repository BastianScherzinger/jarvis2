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
  const st   = _WS_STATUS[w.status] || {cls:'queued', lbl:w.status || '—'};
  const meta = [w.branche, w.stadt].filter(Boolean).map(_wse).join(' · ');
  const p    = Math.max(0, Math.min(100, w.progress || 0));

  // Fortschritt (nur während des Baus)
  let prog = '';
  if(w.status === 'running' || w.status === 'queued'){
    prog = `<div class="ws-prog">
      <div class="ws-bar"><div class="ws-fill" style="width:${p}%"></div></div>
      <div class="ws-step"><span class="jc-spin"></span><span>${_wse(w.step || 'Arbeitet…')}</span><span class="ws-pct">${p}%</span></div>
    </div>`;
  }else if(w.status === 'error'){
    prog = `<div class="ws-errline">✕ ${_wse(w.error || w.step || 'Fehlgeschlagen')}</div>`;
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
  const thumbs = (w.images || []).map(fn =>
    `<a class="ws-thumb" href="/api/websites/${w.id}/asset/${encodeURIComponent(fn)}" target="_blank" rel="noopener" title="${_wse(fn)}">
       <img src="/api/websites/${w.id}/asset/${encodeURIComponent(fn)}" alt="${_wse(fn)}" loading="lazy">
     </a>`).join('');
  const addBtn = ready
    ? `<label class="ws-add" title="Bild zur Seite hinzufügen (für späteren Einsatz)">
         <input type="file" accept="image/*" hidden onchange="wsUploadImage(${w.id}, this)">
         <span class="ws-add-plus">＋</span><span>Bild</span>
       </label>`
    : `<span class="ws-add disabled" title="Ordner wird noch erstellt">＋ Bild</span>`;
  const media = `<div class="ws-media">
      <div class="ws-media-lbl">Bilder${(w.images && w.images.length) ? ' · ' + w.images.length : ''}</div>
      <div class="ws-thumbs">${thumbs}${addBtn}</div>
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
    <div class="ws-foot">${_wse(_wsAgo(w.updated || w.created))}</div>
  </div>`;
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
