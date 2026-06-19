// ════════════════════════════════════════════════════════════════════════════
//  CLAUDE — KI-Chat-Tab (interaktiver 3D-Roboter + Streaming-Chat)
// ════════════════════════════════════════════════════════════════════════════
let _claudeInit    = false;
let _claudeHistory = [];                 // [{role, content}] im Anthropic-Format
let _claudeBusy    = false;
let _claudeFile    = null;               // {media_type, data(base64), preview, name}
const _claudeFlags = { search: false, think: false };
const _CLAUDE_SCENE = 'https://prod.spline.design/kZDDjO5HuC9GJUM2/scene.splinecode';

// Sprache (STT via Whisper-Backend, TTS via edge-tts-Backend)
let _claudeSpeakOn  = false;
let _claudeRecorder = null, _claudeChunks = [], _claudeStream = null;
let _claudeRecording = false, _claudeStarting = false, _claudeAudio = null;

function initClaude(){
  if(_claudeInit) return;
  _claudeInit = true;

  // 3D-Roboter laden (Spline-Web-Component) + Wasserzeichen entfernen
  const wrap = document.getElementById('claude-robot-wrap');
  if(wrap && !wrap.querySelector('spline-viewer')){
    const v = document.createElement('spline-viewer');
    v.setAttribute('url', _CLAUDE_SCENE);
    v.setAttribute('events-target', 'global');
    wrap.appendChild(v);
    _claudeStripWatermark(v);
  }

  // Bereitschaft (API-Key vorhanden?)
  fetch('/api/claude/status').then(r=>r.json()).then(d=>{
    const el = document.getElementById('claude-status');
    if(!el) return;
    el.textContent = d.ready ? ('Online · ' + (d.model||'claude')) : 'API-Key fehlt (.env)';
    el.classList.toggle('off', !d.ready);
  }).catch(()=>{});

  _claudeWire();
}

// Spline-„Made with Spline"-Logo aus dem Shadow-DOM entfernen
function _claudeStripWatermark(v){
  let tries = 0;
  const t = setInterval(()=>{
    tries++;
    const sr = v.shadowRoot;
    if(sr){
      const logo = sr.querySelector('#logo');
      if(logo){ logo.remove(); clearInterval(t); return; }
    }
    if(tries > 60) clearInterval(t);   // nach ~15s aufgeben
  }, 250);
}

function _claudeWire(){
  const inp  = document.getElementById('cc-input');
  const send = document.getElementById('cc-send');
  const mic  = document.getElementById('cc-mic');
  const up   = document.getElementById('cc-upload-btn');
  const file = document.getElementById('cc-file');
  if(!inp) return;

  inp.addEventListener('input', ()=>{
    inp.style.height = 'auto';
    inp.style.height = Math.min(inp.scrollHeight, 160) + 'px';
  });
  inp.addEventListener('keydown', e=>{
    if(e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); claudeSend(); }
  });
  send.addEventListener('click', claudeSend);

  document.querySelectorAll('.cc-toggle').forEach(b=>{
    b.addEventListener('click', ()=>{
      const k = b.dataset.k;
      _claudeFlags[k] = !_claudeFlags[k];
      b.classList.toggle('on', _claudeFlags[k]);
    });
  });

  up.addEventListener('click', ()=>file.click());
  file.addEventListener('change', e=>{
    const f = e.target.files && e.target.files[0];
    if(!f) return;
    if(!f.type.startsWith('image/')){ alert('Nur Bilddateien.'); return; }
    if(f.size > 5*1024*1024){ alert('Bild zu groß (max. 5 MB).'); return; }
    const r = new FileReader();
    r.onload = ev=>{
      const dataUrl = ev.target.result;
      _claudeFile = { media_type:f.type, data:String(dataUrl).split(',')[1],
                      preview:dataUrl, name:f.name };
      _claudeRenderFiles();
    };
    r.readAsDataURL(f);
    file.value = '';
  });

  _claudeWireVoice(mic, inp);

  // Sprachausgabe-Toggle (Antworten vorlesen)
  const voiceBtn = document.getElementById('cc-voice');
  if(voiceBtn){
    voiceBtn.addEventListener('click', ()=>{
      _claudeSpeakOn = !_claudeSpeakOn;
      if(!_claudeSpeakOn) _claudeStopAudio();
      _claudeUpdateVoiceBtn();
    });
    _claudeUpdateVoiceBtn();   // Startzustand (aus)
  }

  const convoBtn = document.getElementById('cc-convo');
  if(convoBtn) convoBtn.addEventListener('click', _claudeToggleConvo);
}

// ── Freihändiger Gesprächsmodus (dauerhaft zuhören, VAD-basiert) ──────────────
const _claudeConvo = {active:false, recording:false, processing:false, speaking:false,
  ctx:null, analyser:null, src:null, stream:null, rec:null, chunks:[], buf:null,
  raf:0, speechMs:0, silenceMs:0, lastT:0};
const _VAD_THRESH = 0.030;      // RMS-Schwelle für Sprache
const _VAD_SILENCE_END = 1100;  // ms Stille beendet die Äußerung
const _VAD_MIN_SPEECH = 350;    // ms Mindest-Sprechdauer (gegen Geräusche)

async function _claudeToggleConvo(){
  if(_claudeConvo.active){ _claudeConvoStop(); return; }
  try{
    _claudeConvo.stream = await navigator.mediaDevices.getUserMedia({audio:true});
  }catch(e){ _claudeToast('Mikrofon-Zugriff verweigert.'); return; }
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if(!Ctx || !window.MediaRecorder){ _claudeToast('Browser unterstützt keinen Gesprächsmodus.'); return; }
  const c = _claudeConvo;
  c.ctx = new Ctx();
  c.src = c.ctx.createMediaStreamSource(c.stream);
  c.analyser = c.ctx.createAnalyser();
  c.analyser.fftSize = 1024;
  c.buf = new Uint8Array(c.analyser.fftSize);
  c.src.connect(c.analyser);
  c.active = true; c.lastT = performance.now();
  _claudeSpeakOn = true; _claudeUpdateVoiceBtn();   // im Gespräch wird vorgelesen
  _claudeConvoBtnState();
  _claudeConvoStatus('Höre zu…', 'listen');
  _claudeVadTick();
}

function _claudeConvoStop(){
  const c = _claudeConvo;
  c.active = false;
  if(c.raf) cancelAnimationFrame(c.raf);
  try{ if(c.rec && c.rec.state !== 'inactive') c.rec.stop(); }catch(e){}
  if(c.stream){ c.stream.getTracks().forEach(t=>t.stop()); c.stream = null; }
  try{ if(c.ctx) c.ctx.close(); }catch(e){}
  c.ctx = null; c.analyser = null; c.recording = false; c.processing = false; c.speaking = false;
  _claudeStopAudio();
  _claudeConvoBtnState();
  _claudeConvoStatus('', '');
}

function _claudeVadTick(){
  const c = _claudeConvo;
  if(!c.active) return;
  c.raf = requestAnimationFrame(_claudeVadTick);
  const now = performance.now(); const dt = now - c.lastT; c.lastT = now;
  if(c.processing || c.speaking) return;   // nicht zuhören, während verarbeitet/gesprochen wird
  c.analyser.getByteTimeDomainData(c.buf);
  let sum = 0;
  for(let i=0;i<c.buf.length;i++){ const v = (c.buf[i] - 128) / 128; sum += v*v; }
  const rms = Math.sqrt(sum / c.buf.length);
  if(rms > _VAD_THRESH){
    c.silenceMs = 0;
    if(!c.recording) _claudeConvoStartRec(); else c.speechMs += dt;
  } else if(c.recording){
    c.silenceMs += dt; c.speechMs += dt;
    if(c.silenceMs > _VAD_SILENCE_END) _claudeConvoStopRec();
  }
}

function _claudeConvoStartRec(){
  const c = _claudeConvo;
  c.chunks = []; c.speechMs = 0; c.silenceMs = 0;
  const mime = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : '';
  c.rec = new MediaRecorder(c.stream, mime ? {mimeType:mime} : undefined);
  c.rec.ondataavailable = e=>{ if(e.data && e.data.size) c.chunks.push(e.data); };
  c.rec.onstop = ()=>_claudeConvoOnStop();
  c.rec.start();
  c.recording = true;
  _claudeConvoStatus('Ich höre…', 'rec');
}

function _claudeConvoStopRec(){
  const c = _claudeConvo;
  if(c.rec && c.rec.state !== 'inactive'){ try{ c.rec.stop(); }catch(e){} }
}

async function _claudeConvoOnStop(){
  const c = _claudeConvo;
  c.recording = false;
  const spoke = c.speechMs;
  const blob = new Blob(c.chunks, {type:'audio/webm'});
  c.chunks = [];
  if(!c.active) return;
  if(spoke < _VAD_MIN_SPEECH || !blob.size){ _claudeConvoStatus('Höre zu…', 'listen'); return; }
  c.processing = true;
  _claudeConvoStatus('Verstehe…', 'think');
  const text = await _transcribeBlob(blob);
  if(!c.active) return;
  if(text){
    const inp = document.getElementById('cc-input');
    if(inp) inp.value = text;
    _claudeSpeakOn = true; _claudeUpdateVoiceBtn();
    c.speaking = true;
    _claudeConvoStatus('JARVIS antwortet…', 'speak');
    try{ await claudeSend(); }catch(e){}
    c.speaking = false;
  } else {
    _claudeToast('Nichts verstanden.');
  }
  c.processing = false;
  if(c.active) _claudeConvoStatus('Höre zu…', 'listen');
}

function _claudeConvoBtnState(){
  const b = document.getElementById('cc-convo');
  if(b) b.classList.toggle('on', _claudeConvo.active);
  if(!_claudeConvo.active){
    const lbl = document.getElementById('cc-convo-lbl');
    if(lbl) lbl.textContent = 'Gespräch';
  }
}

function _claudeConvoStatus(text, cls){
  const lbl = document.getElementById('cc-convo-lbl');
  if(lbl) lbl.textContent = text || 'Gespräch';
  const b = document.getElementById('cc-convo');
  if(b){ b.classList.remove('listen','rec','think','speak'); if(cls) b.classList.add(cls); }
}

function _claudeRenderFiles(){
  const box = document.getElementById('cc-files');
  if(!box) return;
  box.innerHTML = _claudeFile
    ? `<div class="cc-file"><img src="${_claudeFile.preview}" alt=""/>
       <button class="cc-file-x" onclick="claudeRemoveFile()" aria-label="Entfernen">✕</button></div>`
    : '';
}
function claudeRemoveFile(){ _claudeFile = null; _claudeRenderFiles(); }

// ── Spracheingabe: Mikrofon aufnehmen → Whisper-Backend → Auto-Senden ─────────
function _claudeWireVoice(mic, inp){
  if(!mic) return;
  mic.addEventListener('click', ()=>{
    if(_claudeRecording) _claudeStopRecording();
    else _claudeStartRecording(mic, inp);
  });
}

async function _claudeStartRecording(mic, inp){
  if(_claudeStarting || _claudeRecording) return;   // Doppelklick-Schutz (synchron)
  _claudeStarting = true;
  if(!navigator.mediaDevices || !window.MediaRecorder){
    _claudeToast('Mikrofon wird vom Browser nicht unterstützt.'); _claudeStarting = false; return;
  }
  try{
    _claudeStream = await navigator.mediaDevices.getUserMedia({audio:true});
  }catch(e){ _claudeToast('Mikrofon-Zugriff verweigert.'); _claudeStarting = false; return; }

  _claudeChunks = [];
  const mime = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : '';
  _claudeRecorder = new MediaRecorder(_claudeStream, mime ? {mimeType:mime} : undefined);
  _claudeRecorder.ondataavailable = e=>{ if(e.data && e.data.size) _claudeChunks.push(e.data); };
  _claudeRecorder.onstop = ()=>_claudeFinishRecording(inp);
  _claudeRecorder.start();
  _claudeRecording = true;
  _claudeStarting = false;
  mic.classList.add('rec');
  _claudeStopAudio();   // laufende Sprachausgabe stoppen, wenn der Nutzer redet
}

function _claudeStopRecording(){
  if(_claudeRecorder && _claudeRecorder.state !== 'inactive'){
    try{ _claudeRecorder.stop(); }catch(e){}
  }
}

async function _claudeFinishRecording(inp){
  _claudeRecording = false;
  const mic = document.getElementById('cc-mic');
  if(mic) mic.classList.remove('rec');
  if(_claudeStream){ _claudeStream.getTracks().forEach(t=>t.stop()); _claudeStream = null; }

  if(!_claudeChunks.length){ _claudeToast('Keine Aufnahme erkannt.'); return; }
  if(mic) mic.classList.add('busy');
  const blob = new Blob(_claudeChunks, {type:'audio/webm'});
  _claudeChunks = [];
  try{
    const fd = new FormData();
    fd.append('audio', blob, 'speech.webm');
    const r = await fetch('/api/voice/transcribe', {method:'POST', body:fd});
    const d = await r.json();
    if(d.ok && d.text && d.text.trim()){
      inp.value = d.text.trim();
      inp.dispatchEvent(new Event('input'));
      if(_claudeBusy){
        _claudeToast('Antwort läuft noch — Frage steht bereit, Enter zum Senden.');
      } else {
        _claudeSpeakOn = true; _claudeUpdateVoiceBtn();   // gesprochene Frage → gesprochene Antwort
        claudeSend();
      }
    } else if(d.ok){
      _claudeToast('Nichts verstanden — bitte erneut sprechen.');
    } else {
      _claudeToast('Spracherkennung: ' + (d.reason || 'Fehler'));
    }
  }catch(e){
    _claudeToast('Transkription fehlgeschlagen.');
  }
  if(mic) mic.classList.remove('busy');
}

// ── Sprachausgabe: Antwort vom edge-tts-Backend abspielen ─────────────────────
function _claudeUpdateVoiceBtn(){
  const b = document.getElementById('cc-voice');
  if(!b) return;
  b.classList.toggle('on', _claudeSpeakOn);
  const on = b.querySelector('.ic-on'), off = b.querySelector('.ic-off');
  if(on)  on.style.display  = _claudeSpeakOn ? '' : 'none';
  if(off) off.style.display = _claudeSpeakOn ? 'none' : '';
}

function _claudeStopAudio(){
  if(_claudeAudio){
    try{ _claudeAudio.pause(); }catch(e){}
    if(_claudeAudio._url){ try{ URL.revokeObjectURL(_claudeAudio._url); }catch(e){} }
    _claudeAudio = null;
  }
}

function _claudeSpeak(text){
  // Promise löst auf, wenn die Wiedergabe endet (Gesprächsmodus wartet darauf).
  return new Promise((resolve)=>{
    _claudeStopAudio();
    (async ()=>{
      try{
        const r = await fetch('/api/voice/speak', {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({text}),
        });
        if(!r.ok){ resolve(); return; }
        const blob = await r.blob();
        const url  = URL.createObjectURL(blob);
        const a = new Audio(url); a._url = url;
        const fin = ()=>{ try{ URL.revokeObjectURL(url); }catch(e){} resolve(); };
        a.onended = fin; a.onerror = fin;
        _claudeAudio = a;
        a.play().catch(fin);
      }catch(e){ resolve(); }
    })();
  });
}

// Audio-Blob → Transkript (gemeinsam für Push-to-Talk + Gesprächsmodus)
async function _transcribeBlob(blob){
  try{
    const fd = new FormData();
    fd.append('audio', blob, 'speech.webm');
    const r = await fetch('/api/voice/transcribe', {method:'POST', body:fd});
    const d = await r.json();
    return d.ok ? (d.text || '').trim() : null;
  }catch(e){ return null; }
}

function _claudeToast(msg){
  let t = document.getElementById('claude-toast');
  if(!t){
    t = document.createElement('div');
    t.id = 'claude-toast'; t.className = 'claude-toast';
    document.body.appendChild(t);
  }
  t.textContent = msg; t.classList.add('show');
  clearTimeout(t._h);
  t._h = setTimeout(()=>t.classList.remove('show'), 2800);
}

async function claudeSend(){
  if(_claudeBusy) return;
  const inp  = document.getElementById('cc-input');
  const text = (inp.value || '').trim();
  if(!text && !_claudeFile) return;

  // User-Nachricht im Anthropic-Format (Text oder Bild+Text)
  let content;
  if(_claudeFile){
    content = [{type:'image', source:{type:'base64',
               media_type:_claudeFile.media_type, data:_claudeFile.data}}];
    if(text) content.push({type:'text', text});
  } else {
    content = text;
  }
  _claudeHistory.push({role:'user', content});
  _claudeAppendBubble('user', text, _claudeFile ? _claudeFile.preview : null);
  inp.value = ''; inp.style.height = 'auto';
  _claudeFile = null; _claudeRenderFiles();

  // History begrenzen (Kontext + Kosten), erste Nachricht muss 'user' sein
  let msgs = _claudeHistory.slice(-24);
  while(msgs.length && msgs[0].role !== 'user') msgs = msgs.slice(1);

  const bubble = _claudeAppendBubble('assistant', '');
  const body   = bubble.querySelector('.cb-body');
  _claudeBusy = true; _claudeSetBusy(true);

  let acc = '', toolHtml = '', hadToken = false, hadError = false;
  const _render = () => {
    body.innerHTML = toolHtml +
      (acc ? _claudeMd(acc) : (toolHtml ? '' : '<span class="cb-cursor">▌</span>'));
    _claudeScroll();
  };
  try{
    const resp = await fetch('/api/claude/chat', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ messages:msgs, think:_claudeFlags.think, search:_claudeFlags.search }),
    });
    if(!resp.ok || !resp.body) throw new Error('HTTP ' + resp.status);
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    while(true){
      const {value, done} = await reader.read();
      if(done) break;
      buf += dec.decode(value, {stream:true});
      let idx;
      while((idx = buf.indexOf('\n\n')) >= 0){
        const raw = buf.slice(0, idx); buf = buf.slice(idx + 2);
        const line = raw.split('\n').find(l=>l.startsWith('data:'));
        if(!line) continue;
        let ev; try{ ev = JSON.parse(line.slice(5).trim()); }catch{ continue; }
        if(ev.type === 'token'){ hadToken = true; acc += ev.text; _render(); }
        else if(ev.type === 'tool'){ toolHtml += _claudeToolLine(ev.name, ev.input); _render(); }
        else if(ev.type === 'tool_result'){ /* Tool-Zeile genügt als Aktivitäts-Anzeige */ }
        else if(ev.type === 'error'){ hadError = true; acc += (acc?'\n\n':'') + '⚠ ' + ev.msg; _render(); }
      }
    }
  }catch(e){
    body.innerHTML = _claudeMd(acc + (acc?'\n\n':'') + '⚠ Verbindungsfehler: ' + e.message);
  }
  if(hadToken && acc.trim()) _claudeHistory.push({role:'assistant', content:acc});
  _claudeBusy = false; _claudeSetBusy(false); _claudeScroll();
  if(hadToken && !hadError && _claudeSpeakOn) await _claudeSpeak(acc);   // Fehlertexte nicht vorlesen
}

function _claudeSetBusy(b){
  const s = document.getElementById('cc-send');
  if(s){ s.disabled = b; s.classList.toggle('busy', b); }
}

function _claudeAppendBubble(role, text, img){
  const log = document.getElementById('claude-log');
  const empty = document.getElementById('claude-empty');
  if(empty) empty.remove();
  const row = document.createElement('div');
  row.className = 'cb cb-' + role;
  const imgHtml = img ? `<img class="cb-img" src="${img}" alt=""/>` : '';
  const inner   = (role === 'assistant' && !text)
    ? '<span class="cb-cursor">▌</span>'
    : _claudeMd(text);
  row.innerHTML = `<div class="cb-av">${role==='user'?'S':'J'}</div>
                   <div class="cb-body">${imgHtml}${inner}</div>`;
  log.appendChild(row); _claudeScroll();
  return row;
}

function _claudeScroll(){
  const l = document.getElementById('claude-log');
  if(l) l.scrollTop = l.scrollHeight;
}

// Tool-Aktivität als Chip im Chat anzeigen
const _CLAUDE_TOOL_LABELS = {
  maps_search:'Maps-Suche', maps_geocode:'Geocoding', maps_place_details:'Ort-Details',
  maps_directions:'Route', browser_open:'Browser öffnen', browser_click:'Klicken',
  browser_type:'Tippen', browser_scroll:'Scrollen', browser_read:'Seite lesen',
  browser_links:'Links', browser_back:'Zurück', browser_screenshot:'Screenshot',
  generate_image:'Bild erzeugen', generate_video:'Video erzeugen', media_job_status:'Job-Status',
  leads_top:'Top-Leads', leads_search:'Lead-Suche', web_search:'Websuche',
  leads_update:'Lead aktualisieren', enrich_business:'Akquise-Analyse',
  leads_conversion_stats:'Konversions-Statistik',
  shop_skill:'Shop-Anleitung', shop_new:'Shop erstellen', shop_list:'Projekt-Dateien',
  shop_read:'Datei lesen', shop_write:'Datei schreiben', shop_git:'Nach GitHub pushen',
};
function _claudeToolLine(name, input){
  const label = _CLAUDE_TOOL_LABELS[name] || name;
  let arg = '';
  if(input && typeof input === 'object'){
    const v = input.query || input.url || input.address || input.target ||
              input.prompt || input.origin || input.name || input.path || '';
    if(v) arg = ' · ' + String(v).slice(0, 60);
  }
  return `<div class="cb-tool"><span class="cb-tool-i">⚙</span><b>${_e(label)}</b>${_e(arg)}</div>`;
}

// Minimaler, SICHERER Markdown-Renderer: erst escapen, dann formatieren.
function _claudeMd(t){
  if(!t) return '';
  let s = String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  s = s.replace(/```(\w*)\n?([\s\S]*?)```/g,
        (m,lang,code)=>`<pre class="cb-pre"><code>${code.replace(/\n$/,'')}</code></pre>`);
  s = s.replace(/`([^`]+)`/g, '<code class="cb-code">$1</code>');
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/\n/g, '<br>');
  s = s.replace(/(<pre[\s\S]*?<\/pre>)/g, m=>m.replace(/<br>/g, '\n'));
  return s;
}
