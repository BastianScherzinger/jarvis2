// ════════════════════════════════════════════════════════════════════════════
//  VIDEO-STUDIO — Filmora-MCP-Tab (Connect, Prompt-Verbesserung, YouTube-Edit, Chat)
// ════════════════════════════════════════════════════════════════════════════
let _vsInit = false;

function initVideoStudio(){
  if(_vsInit) return;
  _vsInit = true;
  vsLoadStatus();
  vsWireChat();
}

// ── Connect ────────────────────────────────────────────────────────────────────

async function vsLoadStatus(){
  let s;
  try{ s = await(await fetch('/api/video-studio/status')).json(); }
  catch{ vsDebugLog('error', 'Status-Abfrage fehlgeschlagen (Netzwerk).'); return; }

  const badge = document.getElementById('vs-badge');
  const count = document.getElementById('vs-tool-count');
  const disc  = document.getElementById('vs-disconnect-btn');
  if(!badge) return;

  if(s.connected){
    badge.className = 'vs-badge ok';
    badge.textContent = '● verbunden';
    if(disc) disc.style.display = '';
  }else if(s.url_set && s.last_error){
    badge.className = 'vs-badge err';
    badge.textContent = '● Fehler';
    if(disc) disc.style.display = '';
  }else{
    badge.className = 'vs-badge off';
    badge.textContent = '● nicht verbunden';
    if(disc) disc.style.display = 'none';
  }
  if(count) count.textContent = s.tool_count ? `${s.tool_count} Tools entdeckt` : '';

  const list = document.getElementById('vs-tools-list');
  if(list){
    list.innerHTML = (s.tools||[]).slice(0,30)
      .map(t => `<span class="vs-tool-chip">${_e(t)}</span>`).join('');
  }
  if(s.last_error) vsDebugLog('error', s.last_error);
}

async function vsConnect(){
  const inp = document.getElementById('vs-url');
  const btn = document.getElementById('vs-connect-btn');
  const url = (inp && inp.value || '').trim();
  if(!url){ vsDebugLog('warn', 'Bitte zuerst die persönliche MCP-URL einfügen.'); return; }
  btn.disabled = true; btn.textContent = 'Verbinde…';
  let r;
  try{
    r = await(await fetch('/api/video-studio/connect', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({url})})).json();
  }catch{ r = {ok:false, reason:'Netzwerkfehler'}; }
  btn.disabled = false; btn.textContent = 'Verbinden';
  if(r.ok){
    vsDebugLog('success', `Verbunden — ${r.tool_count||0} Tools entdeckt.`);
    if(inp) inp.value = '';
  }else{
    vsDebugLog('error', 'Verbindung fehlgeschlagen: ' + (r.reason || 'unbekannt'));
  }
  vsLoadStatus();
}

async function vsDisconnect(){
  try{ await fetch('/api/video-studio/disconnect', {method:'POST'}); }catch{}
  vsDebugLog('info', 'Getrennt.');
  vsLoadStatus();
}

// ── Prompt-Verbesserung ──────────────────────────────────────────────────────────

async function vsImprovePrompt(){
  const ta  = document.getElementById('vs-instruction');
  const out = document.getElementById('vs-improve-diff');
  const btn = document.getElementById('vs-improve-btn');
  const raw = (ta && ta.value || '').trim();
  if(!raw){ vsDebugLog('warn', 'Bitte zuerst eine Anweisung eingeben.'); return; }
  btn.disabled = true; btn.querySelector('.cb-suggest-ic').textContent = '…';
  let r;
  try{
    r = await(await fetch('/api/video-studio/improve-prompt', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({raw})})).json();
  }catch{ r = {ok:false, reason:'Netzwerkfehler'}; }
  btn.disabled = false; btn.querySelector('.cb-suggest-ic').textContent = '✦';
  if(!r.ok){
    vsDebugLog('error', 'Prompt-Verbesserung fehlgeschlagen: ' + (r.reason||'unbekannt'));
    return;
  }
  if(out){
    out.style.display = '';
    out.innerHTML = `<b>Original:</b> ${_e(r.original)}<br><b>Verbessert (${r.source==='ollama'?'KI':'lokal'}):</b> ${_e(r.improved)}`;
  }
  if(ta) ta.value = r.improved;
  vsDebugLog(r.source==='ollama' ? 'success' : 'info',
    r.source==='ollama' ? 'Prompt per Ollama verbessert.' : 'Ollama nicht erreichbar — Text normalisiert.');
}

// ── Video bearbeiten (inkl. Ambiguitäts-Picker) ─────────────────────────────────

async function vsSubmitEdit(toolName){
  const yt   = (document.getElementById('vs-yt-url')?.value || '').trim();
  const inst = (document.getElementById('vs-instruction')?.value || '').trim();
  const btn  = document.getElementById('vs-submit-btn');
  const picker = document.getElementById('vs-picker');
  if(!yt){ vsDebugLog('warn', 'Bitte einen YouTube-Link eingeben.'); return; }
  if(!inst){ vsDebugLog('warn', 'Bitte eine Bearbeitungsanweisung eingeben.'); return; }

  btn.disabled = true; btn.textContent = 'Sende…';
  let r;
  try{
    r = await(await fetch('/api/video-studio/submit-edit', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({youtube_url: yt, instruction: inst, tool_name: toolName || ''})})).json();
  }catch{ r = {ok:false, reason:'Netzwerkfehler'}; }
  btn.disabled = false; btn.textContent = 'Video bearbeiten';

  if(r.ok){
    if(picker) picker.style.display = 'none';
    vsDebugLog('success', `Job gestartet (Tool: ${r.tool}).`);
    pollJob(r.job_id, 'vs');
    return;
  }

  if(r.reason === 'tool_unclear'){
    vsDebugLog('warn', 'Mehrere/keine passenden Filmora-Tools — bitte manuell wählen.');
    if(picker){
      picker.style.display = '';
      picker.innerHTML = '';
      const lbl = document.createElement('div');
      lbl.className = 'af-lbl';
      lbl.textContent = 'Welches Filmora-Tool soll genutzt werden?';
      picker.appendChild(lbl);
      const tools = r.tools || [];
      if(!tools.length){
        const empty = document.createElement('span');
        empty.className = 'vs-tool-chip';
        empty.textContent = 'Keine passenden Tools gefunden — Debug-Panel prüfen.';
        picker.appendChild(empty);
      }
      // DOM-Elemente + Closure statt onclick-String-Interpolation — Tool-Namen kommen
      // vom externen MCP-Server und dürfen NIE als ausführbarer JS-String eingebettet werden.
      tools.forEach(t => {
        const chip = document.createElement('span');
        chip.className = 'vs-tool-chip vs-pick';
        chip.textContent = t.name;
        chip.addEventListener('click', () => vsSubmitEdit(t.name));
        picker.appendChild(chip);
      });
    }
  }else if(r.reason === 'not_connected'){
    vsDebugLog('error', 'Nicht verbunden — bitte zuerst die Filmora-MCP-URL einfügen.');
  }else{
    vsDebugLog('error', 'Fehlgeschlagen: ' + (r.reason || 'unbekannt'));
  }
}

// ── Chat unten ────────────────────────────────────────────────────────────────

function vsWireChat(){
  const inp  = document.getElementById('vs-chat-input');
  const send = document.getElementById('vs-chat-send');
  if(!inp) return;
  inp.addEventListener('input', ()=>{
    inp.style.height = 'auto';
    inp.style.height = Math.min(inp.scrollHeight, 160) + 'px';
  });
  inp.addEventListener('keydown', e=>{
    if(e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); vsChatSend(); }
  });
  if(send) send.addEventListener('click', vsChatSend);
}

function vsAppendBubble(role, text){
  const log = document.getElementById('vs-chat-log');
  const empty = document.getElementById('vs-chat-empty');
  if(empty) empty.remove();
  const row = document.createElement('div');
  row.className = 'cb cb-' + role;
  row.innerHTML = `<div class="cb-av">${role==='user'?'S':'J'}</div>
                   <div class="cb-body">${_e(text)}</div>`;
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
  return row;
}

async function vsChatSend(){
  const inp = document.getElementById('vs-chat-input');
  const msg = (inp && inp.value || '').trim();
  if(!msg) return;
  inp.value = ''; inp.style.height = 'auto';
  vsAppendBubble('user', msg);
  const thinking = vsAppendBubble('assistant', '…');
  let r;
  try{
    r = await(await fetch('/api/video-studio/chat', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({message: msg})})).json();
  }catch{ r = {ok:false, reply:'Netzwerkfehler, Sir.'}; }
  thinking.querySelector('.cb-body').textContent = r.reply || 'Keine Antwort erhalten.';
  if(r.looks_like_edit){
    const btn = document.createElement('button');
    btn.className = 'export-btn';
    btn.style.marginTop = '8px';
    btn.textContent = 'In Anweisungsfeld übernehmen';
    btn.onclick = ()=>{
      const ta = document.getElementById('vs-instruction');
      if(ta) ta.value = msg;
    };
    thinking.querySelector('.cb-body').appendChild(document.createElement('br'));
    thinking.querySelector('.cb-body').appendChild(btn);
  }
}

// ── Debug-Panel ───────────────────────────────────────────────────────────────

function vsDebugLog(level, msg){
  const el = document.getElementById('vs-debug-log');
  if(!el) return;
  const row = document.createElement('div');
  row.className = 'vs-debug-row vs-' + level;
  const ts = new Date().toLocaleTimeString('de-DE');
  row.textContent = `[${ts}] ${msg}`;
  el.appendChild(row);
  el.scrollTop = el.scrollHeight;
  while(el.children.length > 200) el.removeChild(el.firstChild);
}
