// ════════════════════════════════════════════════════════════════════════════
//  CHAT-DOCK — JARVIS-Chat als ausklappbares Popup auf ALLEN Seiten.
//  Nutzt dasselbe Backend wie der Claude-Reiter (/api/claude/chat, SSE-Streaming),
//  inkl. aller Werkzeuge (Webseiten bauen, Auto-Builder, Leads …).
// ════════════════════════════════════════════════════════════════════════════
let _dockHist = [], _dockBusy = false, _dockOpen = false;

function _dEsc(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function _dMd(t){
  let h = _dEsc(t);
  h = h.replace(/```([\s\S]*?)```/g, (m,c)=>`<pre>${c.replace(/^\n/,'')}</pre>`);
  h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
  h = h.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  h = h.replace(/\n/g, '<br>');
  return h;
}

function dockToggle(){
  _dockOpen = !_dockOpen;
  const p = document.getElementById('dock-panel'), f = document.getElementById('dock-fab');
  if(p) p.classList.toggle('open', _dockOpen);
  if(f) f.classList.toggle('hidden', _dockOpen);
  if(_dockOpen) setTimeout(()=>{ const i=document.getElementById('dock-input'); if(i) i.focus(); }, 120);
}

function _dockBubble(role, text){
  const log = document.getElementById('dock-log');
  const hint = document.getElementById('dock-hint'); if(hint) hint.remove();
  const row = document.createElement('div');
  row.className = 'dock-msg ' + role;
  row.innerHTML = (role==='assistant' && !text) ? '<span class="dock-cur">▌</span>' : _dMd(text);
  log.appendChild(row); log.scrollTop = log.scrollHeight;
  return row;
}

async function dockSend(){
  if(_dockBusy) return;
  const inp = document.getElementById('dock-input');
  const text = (inp.value||'').trim();
  if(!text) return;
  _dockHist.push({role:'user', content:text});
  _dockBubble('user', text);
  inp.value=''; inp.style.height='auto';

  let msgs = _dockHist.slice(-20);
  while(msgs.length && msgs[0].role !== 'user') msgs = msgs.slice(1);

  const bubble = _dockBubble('assistant', '');
  _dockBusy = true;
  const sendBtn = document.getElementById('dock-send'); if(sendBtn) sendBtn.disabled = true;
  let acc='', toolHtml='', hadToken=false;
  const _render = ()=>{ bubble.innerHTML = toolHtml + (acc ? _dMd(acc) : (toolHtml ? '' : '<span class="dock-cur">▌</span>'));
    const log=document.getElementById('dock-log'); log.scrollTop=log.scrollHeight; };
  try{
    const resp = await fetch('/api/claude/chat', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({messages:msgs})});
    if(!resp.ok || !resp.body) throw new Error('HTTP '+resp.status);
    const reader = resp.body.getReader(), dec = new TextDecoder(); let buf='';
    while(true){
      const {value, done} = await reader.read(); if(done) break;
      buf += dec.decode(value, {stream:true});
      let idx;
      while((idx = buf.indexOf('\n\n')) >= 0){
        const raw = buf.slice(0,idx); buf = buf.slice(idx+2);
        const line = raw.split('\n').find(l=>l.startsWith('data:')); if(!line) continue;
        let ev; try{ ev = JSON.parse(line.slice(5).trim()); }catch{ continue; }
        if(ev.type==='token'){ hadToken=true; acc+=ev.text; _render(); }
        else if(ev.type==='tool'){ toolHtml += `<div class="dock-tool">⚙ ${_dEsc(ev.name)}</div>`; _render(); }
        else if(ev.type==='error'){ acc += (acc?'\n\n':'')+'⚠ '+ev.msg; _render(); }
      }
    }
  }catch(e){ bubble.innerHTML = _dMd(acc + (acc?'\n\n':'') + '⚠ Verbindungsfehler: '+e.message); }
  if(hadToken && acc.trim()) _dockHist.push({role:'assistant', content:acc});
  if(_dockHist.length > 36) _dockHist = _dockHist.slice(-36);
  _dockBusy = false; if(sendBtn) sendBtn.disabled = false;
}

document.addEventListener('DOMContentLoaded', ()=>{
  const inp = document.getElementById('dock-input');
  if(inp){
    inp.addEventListener('keydown', e=>{ if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); dockSend(); } });
    inp.addEventListener('input', ()=>{ inp.style.height='auto'; inp.style.height=Math.min(inp.scrollHeight,110)+'px'; });
  }
});
