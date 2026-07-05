// ════════════════════════════════════════════════════════════════════════════
//  WERBEVIDEO-TAB — Website-URL → automatisches 9:16-TikTok-Werbevideo (10s)
//  Eingaben + laufender Job überleben das Neuladen (localStorage), wie beim
//  Video-Studio/Eigene-Marke-Tab.
// ════════════════════════════════════════════════════════════════════════════
const _AV_FORM_KEY = 'jarvis.av.form';
const _AV_JOB_KEY   = 'jarvis.av.job';
let _avPoll = null;
let _avInited = false;

function _avSaveForm(){
  const data = { url: (document.getElementById('av-url')||{}).value || '',
                 hook: (document.getElementById('av-hook')||{}).value || '',
                 cta:  (document.getElementById('av-cta')||{}).value || '' };
  try{ localStorage.setItem(_AV_FORM_KEY, JSON.stringify(data)); }catch(e){}
}

function _avRestoreForm(){
  try{
    const data = JSON.parse(localStorage.getItem(_AV_FORM_KEY) || 'null');
    if(!data) return;
    if(document.getElementById('av-url'))  document.getElementById('av-url').value  = data.url  || '';
    if(document.getElementById('av-hook')) document.getElementById('av-hook').value = data.hook || '';
    if(document.getElementById('av-cta'))  document.getElementById('av-cta').value  = data.cta  || '';
  }catch(e){}
}

function initAdVideo(){
  if(!_avInited){
    _avInited = true;
    _avRestoreForm();
    ['av-url','av-hook','av-cta'].forEach(id => {
      const el = document.getElementById(id);
      if(el) el.addEventListener('input', _avSaveForm);
    });
  }
  avLoadGallery();
  const jobId = localStorage.getItem(_AV_JOB_KEY);
  if(jobId) _avStartPoll(jobId);
}

async function avSubmit(){
  const urlEl  = document.getElementById('av-url');
  const url    = (urlEl.value || '').trim();
  const hint   = document.getElementById('av-hint');
  if(!url){ hint.textContent = 'Bitte eine Website-URL angeben, Sir.'; hint.classList.add('err'); return; }
  hint.classList.remove('err');
  hint.textContent = 'Auftrag wird eingereiht…';
  document.getElementById('av-submit-btn').disabled = true;

  const body = {
    url,
    hook_text: (document.getElementById('av-hook').value || '').trim(),
    cta_text:  (document.getElementById('av-cta').value  || '').trim(),
  };
  try{
    const res = await fetch('/api/media/generate/website-ad-video', {
      method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body),
    });
    const d = await res.json();
    document.getElementById('av-submit-btn').disabled = false;
    if(!d.ok){ hint.textContent = 'Fehler: ' + (d.reason || 'unbekannt'); hint.classList.add('err'); return; }
    hint.textContent = '';
    localStorage.setItem(_AV_JOB_KEY, d.job_id);
    _avStartPoll(d.job_id);
  }catch(e){
    document.getElementById('av-submit-btn').disabled = false;
    hint.textContent = 'Netzwerkfehler: ' + e;
    hint.classList.add('err');
  }
}

function _avStartPoll(jobId){
  document.getElementById('av-result').style.display = 'none';
  const card = document.getElementById('av-job-card');
  card.style.display = 'block';
  card.classList.remove('err');
  card.classList.add('running');
  if(_avPoll) clearInterval(_avPoll);
  const tick = async () => {
    try{
      const res = await fetch('/api/media/job/' + jobId);
      if(res.status === 404){ clearInterval(_avPoll); localStorage.removeItem(_AV_JOB_KEY); card.style.display='none'; return; }
      const job = await res.json();
      _avRenderJob(job);
      if(job.status === 'done' || job.status === 'error'){
        clearInterval(_avPoll);
        localStorage.removeItem(_AV_JOB_KEY);
        if(job.status === 'done'){ _avShowResult(job); avLoadGallery(); }
      }
    }catch(e){ /* nächster Tick versucht's erneut */ }
  };
  tick();
  _avPoll = setInterval(tick, 1500);
}

function _avRenderJob(job){
  const card = document.getElementById('av-job-card');
  const text = document.getElementById('av-jc-text');
  const fill = document.getElementById('av-jc-fill');
  const spin = document.getElementById('av-jc-spin');
  fill.style.width = (job.progress || 0) + '%';
  if(job.status === 'error'){
    card.classList.remove('running'); card.classList.add('err');
    spin.style.display = 'none';
    text.innerHTML = '<span class="jc-x">✕ Fehler:</span> ' + (job.error || 'unbekannt');
  }else if(job.status === 'done'){
    card.classList.remove('running');
    spin.style.display = 'none';
    text.innerHTML = '<span class="jc-ok">✓ Werbevideo fertig</span> · ' + (job.elapsed || 0) + 's';
  }else{
    spin.style.display = 'inline-block';
    text.textContent = (job.stage || 'Verarbeite…') + '  ·  ' + (job.progress || 0) + '%';
  }
}

function _avQaRow(label, ok){
  return '<div class="av-qa-row ' + (ok ? 'ok' : 'bad') + '">' +
    '<span class="av-qa-ic">' + (ok ? '✓' : '✕') + '</span><span>' + label + '</span></div>';
}

function _avShowResult(job){
  const result = document.getElementById('av-result');
  result.style.display = 'block';
  const vid = document.getElementById('av-preview');
  vid.src = job.result_url;
  document.getElementById('av-download').href = job.result_url;

  const c = job.checks || {};
  const qa = job.qa || {};
  document.getElementById('av-qa-rows').innerHTML = [
    _avQaRow('Dauer ' + (qa.duration ? qa.duration.toFixed(1) : '?') + 's (Ziel 10,0s)', c.duration_ok),
    _avQaRow('Auflösung ' + (qa.width||'?') + '×' + (qa.height||'?') + ' (9:16)', c.resolution_ok),
    _avQaRow('Codec H.264', c.codec_ok),
    _avQaRow('Ton vorhanden', c.audio_ok),
    _avQaRow('Dateigröße ' + (qa.size_mb||'?') + ' MB (≤ 12 MB)', c.size_ok),
  ].join('');

  document.getElementById('av-caption').value = job.caption || '';
  document.getElementById('av-hashtags').innerHTML = (job.hashtags || [])
    .map(h => '<span class="av-tag">' + h + '</span>').join('');
}

function avCopyCaption(){
  const cap = document.getElementById('av-caption').value || '';
  const tags = Array.from(document.querySelectorAll('#av-hashtags .av-tag')).map(e => e.textContent).join(' ');
  const full = cap + (tags ? ('\n\n' + tags) : '');
  navigator.clipboard.writeText(full).then(() => {
    const btn = document.getElementById('av-copy-btn');
    const old = btn.innerHTML;
    btn.innerHTML = '<span class="cb-suggest-ic">✓</span> Kopiert!';
    setTimeout(() => { btn.innerHTML = old; }, 1600);
  }).catch(() => {});
}

async function avLoadGallery(){
  const grid = document.getElementById('av-gallery');
  if(!grid) return;
  try{
    const res = await fetch('/api/media/ads');
    const d = await res.json();
    const ads = d.ads || [];
    if(!ads.length){ grid.innerHTML = '<div class="media-empty">Noch keine Werbevideos gebaut.</div>'; return; }
    grid.innerHTML = ads.map(a =>
      '<div class="media-card"><video src="' + a.url + '" muted preload="metadata" ' +
      'onclick="this.paused ? this.play() : this.pause()"></video></div>'
    ).join('');
  }catch(e){ /* still */ }
}
