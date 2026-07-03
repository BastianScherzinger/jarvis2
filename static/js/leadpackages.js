// LeadForge — Datenpakete-Tab: Bestell-Flow (Branche/Region/Land wählen, Vorschau,
// Paket erstellen, Bestellhistorie). Manueller Verkauf, kein Payment-Provider —
// eine Bestellung erzeugt sofort die Export-Datei zum Download.

let _lpInitDone = false;
let _lpBundleSize = null;

function initLeadpackages(){
  if(_lpInitDone){ _lpLoadStats(); _lpLoadOrders(); return; }
  _lpInitDone = true;

  document.getElementById('lp-land').addEventListener('change', _lpOnLandChange);
  document.querySelectorAll('.lp-bundle-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.lp-bundle-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _lpBundleSize = parseInt(btn.dataset.size, 10);
    });
  });
  document.getElementById('lp-preview-btn').addEventListener('click', _lpLoadPreview);
  document.getElementById('lp-order-btn').addEventListener('click', _lpPlaceOrder);

  _lpLoadBranchen();
  _lpOnLandChange();
  _lpLoadStats();
  _lpLoadOrders();
}

function _lpLoadStats(){
  fetch('/api/leadpackages/stats').then(r => r.json()).then(d => {
    document.getElementById('lp-stat-total').textContent = d.total ?? 0;
    document.getElementById('lp-stat-de').textContent = (d.nach_land || {}).DE ?? 0;
    document.getElementById('lp-stat-at').textContent = (d.nach_land || {}).AT ?? 0;
    const top = Object.keys(d.top_branchen || {})[0];
    document.getElementById('lp-stat-top').textContent = top || '—';
  }).catch(() => {});
}

function _lpLoadBranchen(){
  fetch('/api/leadpackages/branchen').then(r => r.json()).then(d => {
    const sel = document.getElementById('lp-branche');
    sel.innerHTML = '<option value="">Branche wählen…</option>' +
      (d.branchen || []).map(b => `<option value="${b}">${b}</option>`).join('');
  }).catch(() => {});
}

function _lpOnLandChange(){
  const land = document.getElementById('lp-land').value;
  fetch(`/api/leadpackages/regionen?land=${encodeURIComponent(land)}`)
    .then(r => r.json()).then(d => {
      const sel = document.getElementById('lp-region');
      sel.innerHTML = '<option value="">Alle Regionen</option>' +
        (d.staedte || []).map(s => `<option value="${s}">${s}</option>`).join('');
    }).catch(() => {});
}

function _lpLoadPreview(){
  const branche = document.getElementById('lp-branche').value;
  const region = document.getElementById('lp-region').value;
  const land = document.getElementById('lp-land').value;
  if(!branche){ alert('Bitte zuerst eine Branche wählen.'); return; }

  const btn = document.getElementById('lp-preview-btn');
  btn.classList.add('loading');
  const qs = new URLSearchParams({ branche, land });
  if(region) qs.set('region', region);

  fetch(`/api/leadpackages/preview?${qs}`).then(r => r.json()).then(d => {
    btn.classList.remove('loading');
    (d.pakete || []).forEach(p => {
      const el = document.querySelector(`.lp-bundle-btn[data-size="${p.bundle_size}"]`);
      if(!el) return;
      el.querySelector('small').textContent = `${p.preis_euro} € · ${p.verfuegbar} verf.`;
      el.disabled = p.verfuegbar === 0;
    });
    document.getElementById('lp-preview-desc').textContent = d.beschreibung || '';
    document.getElementById('lp-preview-sample').innerHTML = (d.vorschau || []).map(v =>
      `<div class="lp-sample-row"><b>${v.name || ''}</b><span>${v.stadt || ''} · Score ${v.quality_score ?? 0}</span></div>`
    ).join('') || '<div class="lp-sample-row">Keine Vorschau verfügbar.</div>';
    document.getElementById('lp-preview').style.display = 'flex';
    document.getElementById('lp-result').style.display = 'none';
  }).catch(() => { btn.classList.remove('loading'); });
}

function _lpPlaceOrder(){
  const branche = document.getElementById('lp-branche').value;
  const region = document.getElementById('lp-region').value;
  const land = document.getElementById('lp-land').value;
  const kaeufer = document.getElementById('lp-kaeufer').value;
  const format = document.getElementById('lp-format').value;

  if(!_lpBundleSize){ alert('Bitte zuerst eine Paketgröße wählen.'); return; }

  const btn = document.getElementById('lp-order-btn');
  btn.classList.add('loading');
  fetch('/api/leadpackages/order', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ branche, region, land, bundle_size: _lpBundleSize, kaeufer, format }),
  }).then(r => r.json().then(d => ({ ok: r.ok, d }))).then(({ ok, d }) => {
    btn.classList.remove('loading');
    const box = document.getElementById('lp-result');
    box.style.display = 'flex';
    if(!ok){
      box.classList.add('lp-error');
      box.innerHTML = `<span>${d.error || 'Fehler bei der Bestellung.'}</span>`;
      return;
    }
    box.classList.remove('lp-error');
    box.innerHTML = `<span>${d.geliefert} Datensätze · ${d.preis_euro} €</span>` +
      `<a href="${d.download_url}" target="_blank">⬇ Herunterladen</a>`;
    _lpLoadStats();
    _lpLoadOrders();
  }).catch(() => { btn.classList.remove('loading'); });
}

function _lpLoadOrders(){
  fetch('/api/leadpackages/orders').then(r => r.json()).then(d => {
    const wrap = document.getElementById('lp-orders');
    const orders = d.orders || [];
    if(!orders.length){
      wrap.innerHTML = '<div class="ws-empty"><div class="empty-sub">Noch keine Bestellungen.</div></div>';
      return;
    }
    wrap.innerHTML = orders.map(o => `
      <div class="lp-order-row">
        <div class="lp-order-main">${o.branche} · ${o.region || o.land}
          <small>${o.kaeufer} · ${o.bundle_size} Stk · ${(o.erstellt_am || '').replace('T', ' ')}</small>
        </div>
        <div class="lp-order-price">${o.preis_euro} €</div>
        <div class="lp-order-status ${o.status}">${o.status}</div>
      </div>`).join('');
  }).catch(() => {});
}
