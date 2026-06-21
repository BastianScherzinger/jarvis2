'use strict';
/* ── JARVIS LeadHunter · Rangliste (DB2 — KI-bewertete Leads) ──────────────── */

// ── State ─────────────────────────────────────────────────────────────────────
let _rankData        = [];
let _rankSort        = 'score';
let _rankSearch      = '';
let _rankTimer       = null;
let _rankFiltersInit = false;
let _rankSearchTimer = null;
let _rankInit        = false;
let _rankCurrentLead = null;  // zuletzt geöffneter Lead (für Bilder-Aktion)

// ── HTML-Escape (lokal — NICHT die app.js-Version überschreiben) ──────────────
function _re(s){
  return (s==null?'':String(s))
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Sicheres JSON-Parsen (Felder können leer/ungültig sein) ───────────────────
function _rjson(raw, fallback){
  if(raw==null) return fallback;
  if(typeof raw !== 'string') return raw;
  const t = raw.trim();
  if(!t) return fallback;
  try{ return JSON.parse(t); }catch{ return fallback; }
}

// ── Aktiv? (Tab sichtbar) ─────────────────────────────────────────────────────
function _rankActive(){
  const p = document.querySelector('main[data-page="ranking"]');
  return !!(p && p.classList.contains('active'));
}

// ── Init (erster Tab-Wechsel) ─────────────────────────────────────────────────
function initRanking(){
  if(!_rankInit){
    _rankInit = true;
    _initRankFilters();
    _startRankRefresh();
  }
  rankReload();
}

// ── Filter-Dropdowns EINMALIG befüllen (aus /stats) ──────────────────────────
async function _initRankFilters(){
  if(_rankFiltersInit) return;
  _rankFiltersInit = true;
  let s;
  try{ s = await(await fetch('/api/evaluated/stats')).json(); }catch{ return; }
  const blSel = document.getElementById('rank-bl');
  const brSel = document.getElementById('rank-br');
  const fill = (sel, obj) => {
    if(!sel || !obj) return;
    const keys = Object.keys(obj);
    if(!keys.length) return;
    sel.insertAdjacentHTML('beforeend',
      keys.map(k => `<option value="${_re(k)}">${_re(k)}</option>`).join(''));
  };
  fill(blSel, s.top_bundeslaender);
  fill(brSel, s.top_branchen);
}

// ── Auto-Refresh alle 3s (nur wenn Tab aktiv) ────────────────────────────────
function _startRankRefresh(){
  if(_rankTimer) return;
  _rankTimer = setInterval(() => {
    if(_rankActive()) rankReload();
  }, 3000);
}

// ── Reload: Query bauen, fetchen, rendern ────────────────────────────────────
async function rankReload(){
  const sort = document.getElementById('rank-sort')?.value || _rankSort;
  const typ  = document.getElementById('rank-typ')?.value  || '';
  const bl   = document.getElementById('rank-bl')?.value   || '';
  const br   = document.getElementById('rank-br')?.value   || '';
  _rankSort  = sort;

  const q = new URLSearchParams({limit:'200', sort});
  if(typ) q.set('lead_typ', typ);
  if(bl)  q.set('bundesland', bl);
  if(br)  q.set('branche', br);
  if(_rankSearch) q.set('suche', _rankSearch);

  let data;
  try{ data = await(await fetch('/api/evaluated/all?' + q.toString())).json(); }
  catch{ return; }
  _rankData = Array.isArray(data) ? data : (data.leads || data.items || []);
  _renderRank();
  _renderSummary();
}

// ── Kopf-Kacheln (Pipeline-Wert als Hero) ────────────────────────────────────
async function _renderSummary(){
  const el = document.getElementById('rank-summary');
  if(!el) return;
  let s;
  try{ s = await(await fetch('/api/evaluated/stats')).json(); }catch{ return; }

  const eur = n => (Number(n)||0).toLocaleString('de-DE') + ' €';
  el.innerHTML = `
    <div class="rs-hero">
      <div class="rs-hero-lbl">Pipeline-Wert</div>
      <div class="rs-hero-num">${eur(s.summe_potenzial)}</div>
      <div class="rs-hero-sub">${(Number(s.total)||0).toLocaleString('de-DE')} bewertete Leads · Ø ${eur(s.avg_potenzial)}</div>
    </div>
    <div class="rs-cards">
      <div class="rs-card"><div class="rs-c-num">${Number(s.total)||0}</div><div class="rs-c-lbl">Gesamt</div></div>
      <div class="rs-card hot"><div class="rs-c-num">${Number(s.hot)||0}</div><div class="rs-c-lbl">🔴 Hot</div></div>
      <div class="rs-card warm"><div class="rs-c-num">${Number(s.warm)||0}</div><div class="rs-c-lbl">🟡 Warm</div></div>
      <div class="rs-card cold"><div class="rs-c-num">${Number(s.cold)||0}</div><div class="rs-c-lbl">🔵 Cold</div></div>
      <div class="rs-card"><div class="rs-c-num">${Number(s.ohne_website_echt)||0}</div><div class="rs-c-lbl">Ohne Website</div></div>
      <div class="rs-card"><div class="rs-c-num">${Number(s.mit_bildern)||0}</div><div class="rs-c-lbl">Mit Bildern</div></div>
      <div class="rs-card"><div class="rs-c-num">${Number(s.mit_email)||0}</div><div class="rs-c-lbl">Mit E-Mail</div></div>
    </div>`;
}

// ── Liste rendern (DocumentFragment, max 200) ────────────────────────────────
function _renderRank(){
  const list = document.getElementById('rank-list');
  if(!list) return;

  // Scroll-Position der Seite merken (Re-Render darf sie nicht zerstören)
  const page = document.querySelector('main[data-page="ranking"]');
  const sc   = page ? page.scrollTop : 0;

  if(!_rankData.length){
    list.innerHTML = '<div class="rank-empty">Noch keine bewerteten Leads. Scraper + Evaluator starten.</div>';
    return;
  }

  const frag = document.createDocumentFragment();
  _rankData.slice(0, 200).forEach((lead, i) => {
    frag.appendChild(_buildRankRow(lead, i + 1));
  });
  list.innerHTML = '';
  list.appendChild(frag);

  if(page) page.scrollTop = sc;
}

// ── Einzelne Zeile ────────────────────────────────────────────────────────────
function _buildRankRow(lead, rank){
  const row = document.createElement('div');
  const typ = lead.lead_typ || 'Cold';
  row.className = 'rank-row ' + typ;

  // Rang (Medaillen-Glow Top 3)
  const medal = rank<=3 ? ' r'+rank : '';

  // Website-Badge
  let web;
  if(!Number(lead.has_website)){
    web = `<span class="rb web-none">✗ KEINE</span>`;
  }else if(Number(lead.website_veraltet)){
    const a = Number(lead.website_alter_jahre);
    web = `<span class="rb web-old">⚠ ${a>=4?a+'J alt':'veraltet'}</span>`;
  }else{
    const a = Number(lead.website_alter_jahre);
    web = `<span class="rb web-ok">✓ ${a>=1?a+'J':'aktuell'}</span>`;
  }
  if(lead.discovered_website){
    const u = String(lead.discovered_website);
    const href = u.startsWith('http') ? u : 'https://'+u;
    web += `<a class="rb-link" href="${_re(href)}" target="_blank" title="Gefundene Website" onclick="event.stopPropagation()">↗</a>`;
  }

  // Bilder
  const bild = Number(lead.bilder_vorhanden)
    ? `<span class="rb bild-ok">✓</span>`
    : `<span class="rb bild-no">—</span>`;

  // Kontakt
  const kTel  = lead.telefon ? `<span class="rb k-tel" title="${_re(lead.telefon)}">📞</span>` : '';
  const kMail = Number(lead.email_vorhanden) ? `<span class="rb k-mail" title="${_re(lead.email_adresse||'E-Mail')}">✉</span>` : '';
  const kontakt = (kTel + kMail) || `<span class="rb k-none">—</span>`;

  // Sub-Zeile
  const sub = [lead.branche, lead.stadt, lead.bundesland].filter(Boolean).map(_re).join(' · ');
  const hook = lead.pitch_hook ? `<div class="rr-hook">${_re(lead.pitch_hook)}</div>` : '';

  const pot = (Number(lead.potenzial_euro)||0).toLocaleString('de-DE') + ' €';
  const cur = lead.status || 'neu';
  const opt = (v,l)=>`<option value="${v}"${cur===v?' selected':''}>${l}</option>`;

  row.innerHTML = `
    <span class="rt-rank rr-rank${medal}">${rank}</span>
    <span class="rt-score"><span class="rr-score ${typ}">${Number(lead.score)||0}</span></span>
    <span class="rt-name">
      <div class="rr-name">${_re(lead.name)}</div>
      <div class="rr-sub">${sub}</div>
      ${hook}
    </span>
    <span class="rt-web">${web}</span>
    <span class="rt-bild">${bild}</span>
    <span class="rt-kontakt">${kontakt}</span>
    <span class="rt-pot"><span class="rr-pot">${pot}</span></span>
    <span class="rt-status">
      <select class="rr-status" onclick="event.stopPropagation()" onchange="rankSetStatus(event, ${Number(lead.id)||0})">
        ${opt('neu','● Neu')}${opt('kontaktiert','● Kontaktiert')}${opt('termin','● Termin')}${opt('verkauft','● Verkauft')}${opt('tot','● Tot')}
      </select>
    </span>`;

  row.addEventListener('click', () => openRankDetail(lead));
  return row;
}

// ── Status setzen ─────────────────────────────────────────────────────────────
async function rankSetStatus(ev, id){
  ev.stopPropagation();
  const sel = ev.target;
  if(!id) return;
  try{
    await fetch(`/api/evaluated/${id}/status`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({status: sel.value}),
    });
    const l = _rankData.find(x => Number(x.id) === Number(id));
    if(l) l.status = sel.value;
  }catch{}
}

// ── Detail-Ansicht im bestehenden Modal ──────────────────────────────────────
function openRankDetail(lead){
  _rankCurrentLead = lead;
  const typ   = lead.lead_typ || 'Cold';
  const inner = document.getElementById('modal-inner');
  if(!inner) return;

  // Score-Aufschlüsselung
  const breakdown = _rjson(lead.score_breakdown, {});
  let bdHtml = '';
  if(breakdown && typeof breakdown === 'object' && Object.keys(breakdown).length){
    const entries = Object.entries(breakdown);
    const maxAbs = Math.max(1, ...entries.map(([,v]) => Math.abs(Number(v)||0)));
    bdHtml = entries.map(([sig,pts]) => {
      const p = Number(pts)||0;
      const w = Math.round(Math.abs(p)/maxAbs*100);
      const neg = p < 0;
      return `<div class="score-comp${neg?' neg':''}">
        <span class="sc-sig">${_re(sig)}</span>
        <span class="sc-bar-wrap"><span class="sc-bar" style="width:${w}%"></span></span>
        <span class="sc-pts">${p>0?'+':''}${p}</span>
      </div>`;
    }).join('');
  }

  // Prüf-Protokoll
  const vlog = _rjson(lead.verify_log, []);
  let vlogHtml = '';
  if(Array.isArray(vlog) && vlog.length){
    vlogHtml = vlog.map((s,i) =>
      `<div class="verify-step"><span class="vs-n">${i+1}</span><span class="vs-t">${_re(String(s))}</span></div>`
    ).join('');
  }

  // Website-Probleme
  const probleme = _rjson(lead.website_probleme, []);
  let probHtml = '';
  if(Array.isArray(probleme) && probleme.length){
    probHtml = `<ul class="m-issues">${probleme.map(p=>`<li>${_re(String(p))}</li>`).join('')}</ul>`;
  }

  // Social Media
  const social = _rjson(lead.social_media, {});
  let socialHtml = '';
  if(social && typeof social === 'object' && Object.keys(social).length){
    const pills = Object.entries(social).filter(([,v])=>v).map(([k,v]) => {
      const u = String(v);
      const href = u.startsWith('http') ? u : 'https://'+u;
      return `<a class="m-social-pill" href="${_re(href)}" target="_blank">${_re(k)} ↗</a>`;
    }).join('');
    if(pills) socialHtml = `<div class="m-social">${pills}</div>`;
  }

  // Website-Status-Zeile
  let webStatus;
  if(!Number(lead.has_website))      webStatus = `<span class="m-v no">✗ Keine Website</span>`;
  else if(Number(lead.website_veraltet)) webStatus = `<span class="m-v warn">⚠ Veraltet</span>`;
  else                                webStatus = `<span class="m-v ok">✓ Aktuell</span>`;
  const alterTxt = Number(lead.website_alter_jahre)>=0 ? Number(lead.website_alter_jahre)+' Jahre' : 'unbekannt';
  const discHref = lead.discovered_website
    ? (String(lead.discovered_website).startsWith('http') ? lead.discovered_website : 'https://'+lead.discovered_website)
    : '';

  // E-Mail-Entwurf
  const mail = _rjson(lead.email_entwurf, null);
  let mailHtml = '';
  if(mail && (mail.betreff || mail.text)){
    const full = (mail.betreff?('Betreff: '+mail.betreff+'\n\n'):'') + (mail.text||'');
    mailHtml = `<div class="m-sec">
      <div class="m-sec-t">E-Mail-Entwurf</div>
      ${mail.betreff?`<div class="m-email-sub">${_re(mail.betreff)}</div>`:''}
      <textarea class="m-email-txt" readonly>${_re(mail.text||'')}</textarea>
      <button class="m-copy-btn" onclick="_rankCopy(this)" data-full="${_re(full)}">⧉ Kopieren</button>
    </div>`;
  }

  const eur = n => (Number(n)||0).toLocaleString('de-DE') + ' €';

  // Foto-URL validieren (nur http/https)
  const fotoUrl = (lead.foto_url || '').startsWith('http') ? lead.foto_url : '';

  // Bilder-Galerie (öffenbarer Ordner) — alle gefundenen Bilder des Betriebs
  let fotos = _rjson(lead.foto_urls, []);
  if(!Array.isArray(fotos)) fotos = [];
  fotos = fotos.filter(u => typeof u === 'string' && u.startsWith('http'));
  window._rankFotos = fotos;
  let galerieHtml = '';
  if(fotos.length){
    const thumbs = fotos.map((u,i) =>
      `<img class="m-gal-thumb" src="${_re(u)}" loading="lazy" alt="Bild ${i+1}"
            onclick="rankLightbox(${i})" onerror="this.style.display='none'"/>`
    ).join('');
    galerieHtml = `<div class="m-sec">
      <div class="m-sec-t">📷 Bilder des Betriebs · ${fotos.length}</div>
      <div class="m-gallery">${thumbs}</div></div>`;
  }

  // Sicherheits-Aufschlüsselung
  const sBd = _rjson(lead.sicherheit_breakdown, {});
  let sBdHtml = '';
  if(sBd && typeof sBd === 'object' && Object.keys(sBd).length){
    const entries = Object.entries(sBd);
    const maxAbs  = Math.max(1, ...entries.map(([,v]) => Math.abs(Number(v)||0)));
    sBdHtml = entries.map(([sig,pts]) => {
      const p = Number(pts)||0, w = Math.round(Math.abs(p)/maxAbs*100), neg = p<0;
      return `<div class="score-comp${neg?' neg':''}">
        <span class="sc-sig">${_re(sig)}</span>
        <span class="sc-bar-wrap"><span class="sc-bar" style="width:${w}%"></span></span>
        <span class="sc-pts">${p>0?'+':''}${p}</span></div>`;
    }).join('');
  }

  inner.innerHTML = `
    <div class="m-hdr">
      <div class="m-badge ${typ}">${typ}</div>
      <div class="m-title">${_re(lead.name)}</div>
      <button class="m-close" onclick="closeModal()">✕</button>
    </div>
    ${fotoUrl ? `<div class="m-foto-wrap">
      <img class="m-foto" src="${_re(fotoUrl)}" alt="${_re(lead.name)}"
           onerror="this.parentElement.style.display='none'"/>
    </div>` : ''}
    <div class="m-score-row">
      <span style="font-size:10px;color:var(--tx2)">Bedarf</span>
      <div class="m-bar"><div class="m-fill ${typ}" style="width:${Number(lead.score)||0}%"></div></div>
      <span class="m-score-num ${typ}">${Number(lead.score)||0}</span>
    </div>
    <div class="m-score-row">
      <span style="font-size:10px;color:var(--tx2)">Sicherheit</span>
      <div class="m-bar"><div class="m-fill-sec" style="width:${Number(lead.sicherheit)||0}%"></div></div>
      <span class="m-score-num sec">${Number(lead.sicherheit)||0}</span>
    </div>
    <div class="m-ew-row">
      <span class="m-ew-lbl">Erwartungswert (sicheres Geld)</span>
      <span class="m-ew-val">${eur(lead.erwartungswert_euro)}</span>
      <span class="m-ew-sub">von ${eur(lead.potenzial_euro)} Potenzial</span>
    </div>

    ${galerieHtml}

    ${bdHtml ? `<div class="m-sec"><div class="m-sec-t">Bedarf — Aufschlüsselung</div>${bdHtml}</div>` : ''}
    ${sBdHtml ? `<div class="m-sec"><div class="m-sec-t">Sicherheit — Aufschlüsselung</div>${sBdHtml}</div>` : ''}
    ${vlogHtml ? `<div class="m-sec"><div class="m-sec-t">Prüf-Protokoll</div>${vlogHtml}</div>` : ''}

    <div class="m-sec">
      <div class="m-sec-t">Website</div>
      <div class="m-row"><span class="m-k">Status</span>${webStatus}</div>
      <div class="m-row"><span class="m-k">Alter</span><span class="m-v ${Number(lead.website_alter_jahre)>5?'warn':''}">${alterTxt}</span></div>
      ${lead.website_url?`<div class="m-row"><span class="m-k">URL</span><span class="m-v"><a href="${_re(String(lead.website_url).startsWith('http')?lead.website_url:'https://'+lead.website_url)}" target="_blank">${_re(lead.website_url)} ↗</a></span></div>`:''}
      ${discHref?`<div class="m-row"><span class="m-k">Gefunden</span><span class="m-v"><a href="${_re(discHref)}" target="_blank">${_re(lead.discovered_website)} ↗</a></span></div>`:''}
      ${probHtml}
    </div>

    <div class="m-sec">
      <div class="m-sec-t">Online-Präsenz</div>
      <div class="m-row"><span class="m-k">Bilder (Maps)</span><span class="m-v ${Number(lead.fotos_in_maps)?'ok':'no'}">${Number(lead.fotos_in_maps)?'✓ Ja':'✗ Nein'}</span></div>
      <div class="m-row"><span class="m-k">Bilder (Web)</span><span class="m-v ${Number(lead.bilder_vorhanden)?'ok':'no'}">${Number(lead.bilder_vorhanden)?'✓ Ja':'✗ Nein'}</span></div>
      ${Number(lead.hat_nur_social)?`<div class="m-row"><span class="m-k">Nur Social</span><span class="m-v warn">⚠ Ja</span></div>`:''}
      ${socialHtml}
    </div>

    <div class="m-sec">
      <div class="m-sec-t">Kontakt</div>
      ${lead.adresse?`<div class="m-row"><span class="m-k">Adresse</span><span class="m-v">${_re(lead.adresse)}</span></div>`:''}
      <div class="m-row"><span class="m-k">Stadt</span><span class="m-v">${_re(lead.stadt||'')} · ${_re(lead.bundesland||'')}</span></div>
      <div class="m-row"><span class="m-k">Branche</span><span class="m-v">${_re(lead.branche||'—')}</span></div>
      ${lead.ansprechpartner?`<div class="m-row"><span class="m-k">Ansprechpartner</span><span class="m-v ok">${_re(lead.ansprechpartner)}</span></div>`:''}
      ${lead.telefon?`<div class="m-row"><span class="m-k">Telefon</span><span class="m-v ok">${_re(lead.telefon)}${Number(lead.telefon_verifiziert)?' ✓':''}</span></div>`:''}
      ${Number(lead.email_vorhanden)?`<div class="m-row"><span class="m-k">E-Mail</span><span class="m-v ok">${_re(lead.email_adresse||'vorhanden')}</span></div>`:''}
      ${(()=>{const ea=_rjson(lead.email_alle,[]);return (Array.isArray(ea)&&ea.length>1)?`<div class="m-row"><span class="m-k">Weitere E-Mails</span><span class="m-v">${ea.slice(1,5).map(e=>_re(e)).join('<br>')}</span></div>`:'';})()}
    </div>

    <div class="m-sec">
      <div class="m-sec-t">Einschätzung</div>
      ${lead.beschreibung?`<div class="m-row"><span class="m-k">Beschreibung</span><span class="m-v">${_re(lead.beschreibung)}</span></div>`:''}
      ${lead.firmengroesse?`<div class="m-row"><span class="m-k">Firmengröße</span><span class="m-v">${_re(lead.firmengroesse)}</span></div>`:''}
      <div class="m-row"><span class="m-k">Privat-Zahler</span><span class="m-v ${Number(lead.ist_privat_zahler)?'ok':''}">${Number(lead.ist_privat_zahler)?'✓ Ja':'Nein'}</span></div>
      <div class="m-row"><span class="m-k">Potenzial</span><span class="m-v" style="color:var(--y);font-weight:700">${eur(lead.potenzial_euro)}</span></div>
      ${lead.potenzial_begruendung?`<div class="m-row"><span class="m-k">Begründung</span><span class="m-v">${_re(lead.potenzial_begruendung)}</span></div>`:''}
    </div>

    ${lead.pitch_hook?`<div class="m-sec"><div class="m-sec-t">Pitch-Hook</div><div class="m-pitch">${_re(lead.pitch_hook)}</div></div>`:''}
    ${mailHtml}

    ${lead.schluessel?`<div class="rr-key">${_re(lead.schluessel)}</div>`:''}

    <div class="m-sec m-actions" style="margin-top:10px">
      <button class="rank-web-btn" id="rank-web-btn" onclick="rankBuildWebsite(this)" title="prüfe Claude…">
        🌐 Webseite bauen &amp; live stellen
      </button>
      <div class="rank-web-out" id="rank-web-out" style="display:none"></div>
      ${Number(lead.email_vorhanden)?`<button class="rank-mail-btn" onclick="rankSendEmail(${Number(lead.id)||0}, this)">✉ E-Mail an Lead senden</button>`:''}
      <button class="rank-img-btn" onclick="rankCreateImages()">
        🎨 Werbe-Bilder für diesen Lead erstellen
      </button>
    </div>`;

  document.getElementById('modal-bg').classList.add('open');
  document.getElementById('modal').classList.add('open');
  _rankColorWebBtn();   // Button rot (Token fehlt) / grün (Claude bereit)
}

// ── Webseite bauen (shop-bauen) aus der Rangliste ─────────────────────────────
let _claudeReadyCache = null;

function _rankColorWebBtn(){
  const btn = document.getElementById('rank-web-btn');
  if(!btn) return;
  const apply = (ready)=>{
    btn.classList.toggle('ready', ready);
    btn.classList.toggle('notready', !ready);
    btn.disabled = !ready;
    btn.title = ready ? 'Claude bereit — Seite wird mit KI-Texten + Hero-Banner gebaut'
                      : 'ANTHROPIC_KEY fehlt in der .env — Claude nicht verfügbar';
  };
  if(_claudeReadyCache !== null){ apply(_claudeReadyCache); return; }
  fetch('/api/claude/status').then(r=>r.json())
    .then(d=>{ _claudeReadyCache = !!d.ready; apply(_claudeReadyCache); })
    .catch(()=>apply(false));
}

async function rankBuildWebsite(btn){
  const lead = _rankCurrentLead;
  if(!lead || !lead.id || btn.disabled) return;
  const out = document.getElementById('rank-web-out');
  btn.disabled = true;
  if(out){ out.style.display = 'block';
    out.innerHTML = `<div class="m-spin-row"><span class="jc-spin"></span><span>Website-Bau wird gestartet…</span></div>`; }
  try{
    const d = await(await fetch(`/api/lead/${Number(lead.id)}/website`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(lead),   // vollständiger Lead inkl. foto_urls
    })).json();
    if(d.ok && d.job_id && typeof _pollWebsite === 'function'){
      _pollWebsite(d.job_id, out, btn, d.github_ready, d.railway_ready);
    } else if(out){
      out.innerHTML = `<div class="m-err-row">✕ ${_re(d.reason||'Fehler')}</div>`; btn.disabled = false;
    }
  }catch(e){
    if(out) out.innerHTML = `<div class="m-err-row">✕ ${_re(String(e))}</div>`;
    btn.disabled = false;
  }
}

// ── E-Mail an Lead senden (Trockenlauf solange JARVIS_EMAIL_ENABLED=false) ─────
async function rankSendEmail(id, btn){
  if(!id) return;
  const orig = btn ? btn.textContent : '';
  if(btn){ btn.disabled = true; btn.textContent = '… sende'; }
  try{
    const r = await fetch(`/api/lead/${id}/send-email`, {method:'POST'});
    const d = await r.json();
    if(d.status === 'deaktiviert'){
      alert('Versand ist deaktiviert (JARVIS_EMAIL_ENABLED=false).\nTrockenlauf — es wurde nichts gesendet.');
    } else if(d.ok){
      alert('E-Mail gesendet ✓');
    } else {
      alert('Fehler: ' + (d.fehler || d.reason || 'unbekannt'));
    }
  }catch(e){ alert('Netzwerkfehler beim Senden'); }
  if(btn){ btn.disabled = false; btn.textContent = orig; }
}

// ── Lightbox: einzelnes Lead-Bild groß öffnen ─────────────────────────────────
function rankLightbox(i){
  const fotos = window._rankFotos || [];
  const url   = (typeof i === 'number') ? fotos[i] : i;
  if(!url) return;
  let lb = document.getElementById('rank-lightbox');
  if(!lb){
    lb = document.createElement('div');
    lb.id = 'rank-lightbox';
    lb.className = 'rank-lightbox';
    lb.onclick = () => lb.classList.remove('open');
    document.body.appendChild(lb);
  }
  lb.innerHTML = `<img src="${_re(url)}" alt="Bild"/>`;
  lb.classList.add('open');
}

// ── Zu Bilder-Tab wechseln und Lead vorausfüllen ──────────────────────────────
function rankCreateImages(){
  if(!_rankCurrentLead) return;
  const lead = _rankCurrentLead;
  closeModal();
  if(typeof showPage === 'function') showPage('images');
  // Kurz warten bis Tab aktiv + loadImageLeads fertig (Dropdown befüllt)
  setTimeout(async () => {
    // Lead-Dropdown: passenden Eintrag wählen
    const sel = document.getElementById('af-lead');
    if(sel){
      // Falls noch nicht befüllt: kurz warten
      if(sel.options.length <= 1){
        await new Promise(r => setTimeout(r, 600));
      }
      const opt = [...sel.options].find(o => String(o.value) === String(lead.id));
      if(opt){
        sel.value = String(lead.id);
        if(typeof afLeadPick === 'function') afLeadPick();
      }
    }
    // Direkt setzen falls Dropdown-Treffer fehlt
    const b  = document.getElementById('af-betrieb');
    const br = document.getElementById('af-branche');
    if(b  && !b.value)  b.value  = lead.name    || '';
    if(br && !br.value) br.value = lead.branche || '';
    // Zum Formular scrollen
    document.querySelector('.adform')?.scrollIntoView({behavior:'smooth'});
  }, 300);
}

// ── E-Mail kopieren ───────────────────────────────────────────────────────────
function _rankCopy(btn){
  const txt = btn.getAttribute('data-full') || '';
  navigator.clipboard.writeText(txt).then(() => {
    btn.textContent = '✓ Kopiert';
    setTimeout(() => { btn.textContent = '⧉ Kopieren'; }, 2000);
  }).catch(()=>{});
}

// ── Suche (debounce 350ms) ────────────────────────────────────────────────────
function rankSearch(v){
  if(_rankSearchTimer) clearTimeout(_rankSearchTimer);
  _rankSearchTimer = setTimeout(() => {
    _rankSearch = (v||'').trim();
    rankReload();
  }, 350);
}

// ── Neu bewerten ──────────────────────────────────────────────────────────────
async function rankReeval(){
  if(!confirm('Alle Leads neu bewerten? Die Rangliste wird geleert und füllt sich live wieder, jeder Lead erscheint sortiert an seiner Position.')) return;
  const live = document.getElementById('rank-live');
  // Ansicht SOFORT leeren — die Leads strömen dann live sortiert wieder rein.
  _rankData = [];
  _renderRank();
  try{
    const r = await fetch('/api/evaluated/reeval', {method:'POST'});
    const d = await r.json();
    if(live) live.textContent = `↻ Bewertet live · ${d.requeued||0} Leads`;
    _renderSummary();
  }catch{
    if(live) live.textContent = '✕ Fehler';
  }
  setTimeout(() => { if(live) live.textContent = '● LIVE · 3s'; }, 6000);
}

// ── Manueller Cloud-Sync ──────────────────────────────────────────────────────
async function rankCloudSync(){
  const btn = document.getElementById('sync-btn');
  const st  = document.getElementById('sync-status');
  if(btn) btn.disabled = true;
  if(st)  st.textContent = '↑ Synchronisiere…';
  try{
    const r = await(await fetch('/api/sync', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({full: false}),
    })).json();
    if(r.ok){
      if(st) st.textContent = `✓ ${r.uploaded} hochgeladen, ${r.skipped} synchron (${r.total} gesamt)`;
    }else{
      if(st) st.textContent = `✕ ${r.reason || 'Fehler — SUPABASE_SERVICE_KEY in .env?'}`;
    }
  }catch(e){
    if(st) st.textContent = '✕ Netzwerkfehler';
  }finally{
    if(btn) btn.disabled = false;
    setTimeout(() => { if(st) st.textContent = ''; }, 8000);
  }
}

// ── Gesamte Datenbank leeren ────────────────────────────────────────────────────
async function rankClearDb(){
  if(!confirm('WIRKLICH die GESAMTE Datenbank leeren? Alle gefundenen und bewerteten Leads werden gelöscht — das kann NICHT rückgängig gemacht werden.')) return;
  if(!confirm('Letzte Warnung: Alles unwiderruflich löschen?')) return;
  const live = document.getElementById('rank-live');
  try{
    const r = await fetch('/api/clear', {method:'POST'});
    const d = await r.json();
    const g = d.geloescht || {};
    if(live) live.textContent = `🗑 Geleert: ${(g.evaluated||0)} bewertet, ${(g.raw||0)} roh`;
    _rankData = [];
    _renderRank();
    _renderSummary();
  }catch{
    if(live) live.textContent = '✕ Fehler beim Leeren';
  }
  setTimeout(() => { if(live) live.textContent = '● LIVE · 3s'; }, 6000);
}
