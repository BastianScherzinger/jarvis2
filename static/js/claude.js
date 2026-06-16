// ════════════════════════════════════════════════════════════════════════════
//  CLAUDE — KI-Chat-Tab (interaktiver 3D-Roboter + Streaming-Chat)
// ════════════════════════════════════════════════════════════════════════════
let _claudeInit    = false;
let _claudeHistory = [];                 // [{role, content}] im Anthropic-Format
let _claudeBusy    = false;
let _claudeFile    = null;               // {media_type, data(base64), preview, name}
const _claudeFlags = { search: false, think: false };
const _CLAUDE_SCENE = 'https://prod.spline.design/kZDDjO5HuC9GJUM2/scene.splinecode';

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

  _claudeWireMic(mic, inp);
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

// Spracheingabe via Web-Speech-API (Chrome). Fehlt sie, Mic ausblenden.
function _claudeWireMic(mic, inp){
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if(!SR){ if(mic) mic.style.display = 'none'; return; }
  let rec = null, on = false;
  mic.addEventListener('click', ()=>{
    if(on){ rec && rec.stop(); return; }
    rec = new SR(); rec.lang = 'de-DE'; rec.interimResults = true; rec.continuous = false;
    const base = inp.value;
    rec.onstart  = ()=>{ on = true;  mic.classList.add('rec'); };
    rec.onend    = ()=>{ on = false; mic.classList.remove('rec'); };
    rec.onerror  = ()=>{ on = false; mic.classList.remove('rec'); };
    rec.onresult = e=>{
      let txt = '';
      for(let i=0;i<e.results.length;i++) txt += e.results[i][0].transcript;
      inp.value = (base ? base + ' ' : '') + txt;
      inp.dispatchEvent(new Event('input'));
    };
    rec.start();
  });
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

  let acc = '';
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
        if(ev.type === 'token'){ acc += ev.text; body.innerHTML = _claudeMd(acc); _claudeScroll(); }
        else if(ev.type === 'error'){ acc += (acc?'\n\n':'') + '⚠ ' + ev.msg; body.innerHTML = _claudeMd(acc); }
      }
    }
  }catch(e){
    body.innerHTML = _claudeMd(acc + (acc?'\n\n':'') + '⚠ Verbindungsfehler: ' + e.message);
  }
  if(acc.trim()) _claudeHistory.push({role:'assistant', content:acc});
  _claudeBusy = false; _claudeSetBusy(false); _claudeScroll();
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
