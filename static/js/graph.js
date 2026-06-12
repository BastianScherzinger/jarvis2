'use strict';
/* ── JARVIS LeadHunter — Graph-Visualisierungen v2 ──────────────────────── */

// ── Konfiguration ──────────────────────────────────────────────────────────
const G_REFRESH_MS  = 3000;   // Auto-Refresh alle 3 Sekunden
const G_MAX_NODES   = 2000;   // Max Nodes im Graph
const G_LINK_PROB   = 0.18;   // Wahrscheinlichkeit für Intra-Gruppen-Link

// ── State ──────────────────────────────────────────────────────────────────
let _gNodes      = [];        // Alle geladenen Node-Objekte
let _gNodeMap    = new Map(); // id → node (schnelles Dedup)
let _gLinks      = [];
let _gGrouping   = 'branche';
let _gFilter     = '';        // Suchtext
let _gHotOnly    = false;
let _gSim        = null;
let _gNodeSel    = null;      // D3-Selection der Knoten-Gruppen
let _gLinkSel    = null;      // D3-Selection der Kanten
let _gG          = null;      // Container-Group
let _gZoom       = null;
let _gRefreshTimer = null;
let _gLastCount  = 0;         // Zähler für inkrementellen Fetch
let _gInitDone   = false;

// ── Farben ─────────────────────────────────────────────────────────────────
const TYPE_COLOR = { Hot:'#ff3b50', Warm:'#ffca28', Cold:'#3d82f5' };
const PALETTE = [
  '#00d4ff','#ff6b35','#7b61ff','#00e676','#ff4081',
  '#ffab40','#40c4ff','#ea80fc','#69f0ae','#ff6d00',
  '#b2ff59','#f06292','#e040fb','#00bcd4','#ff5722',
];
const _colorMap = new Map();
let   _colorIdx = 0;

function _getColor(key) {
  if (!key) return '#4a6080';
  if (!_colorMap.has(key)) _colorMap.set(key, PALETTE[_colorIdx++ % PALETTE.length]);
  return _colorMap.get(key);
}

function _nodeColor(d) {
  if (_gGrouping === 'lead_typ')   return TYPE_COLOR[d.lead_typ] || '#3d82f5';
  if (_gGrouping === 'bundesland') return _getColor(d.bundesland);
  if (_gGrouping === 'potenzial') {
    const p = d.potenzial_euro || 0;
    return p >= 3000 ? '#ff3b50' : p >= 1500 ? '#ffca28' : '#3d82f5';
  }
  return _getColor(d.branche);
}

function _nodeR(d) {
  const p = d.potenzial_euro || 500;
  return p >= 5000 ? 12 : p >= 3000 ? 9 : p >= 1500 ? 6.5 : 4.5;
}

function _isVisible(d) {
  if (_gHotOnly && d.lead_typ !== 'Hot') return false;
  if (!_gFilter) return true;
  const q = _gFilter.toLowerCase();
  return (d.name||'').toLowerCase().includes(q)
      || (d.branche||'').toLowerCase().includes(q)
      || (d.stadt||'').toLowerCase().includes(q)
      || (d.bundesland||'').toLowerCase().includes(q);
}

// ── Graph-Init (einmalig) ─────────────────────────────────────────────────
function _initSimulation(W, H) {
  if (_gSim) _gSim.stop();

  _gSim = d3.forceSimulation()
    .force('link',    d3.forceLink(_gLinks).id(d => d.id).distance(55).strength(0.25))
    .force('charge',  d3.forceManyBody().strength(-70).distanceMax(200))
    .force('center',  d3.forceCenter(W/2, H/2).strength(0.05))
    .force('collide', d3.forceCollide(d => _nodeR(d) + 4).strength(0.7))
    .alphaDecay(0.015)
    .velocityDecay(0.4);

  _gSim.on('tick', _tick);
}

function _tick() {
  if (_gLinkSel) {
    _gLinkSel
      .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
  }
  if (_gNodeSel) {
    _gNodeSel.attr('transform', d => `translate(${d.x||0},${d.y||0})`);
  }
}

// ── Links neu berechnen ───────────────────────────────────────────────────
function _rebuildLinks() {
  const groups = {};
  const visNodes = _gNodes.filter(_isVisible);
  visNodes.forEach(d => {
    let k;
    if (_gGrouping === 'branche')    k = d.branche;
    else if (_gGrouping === 'bundesland') k = d.bundesland;
    else if (_gGrouping === 'lead_typ')   k = d.lead_typ;
    else k = d.potenzial_euro >= 1500 ? 'hoch' : 'niedrig';
    if (!groups[k]) groups[k] = [];
    groups[k].push(d);
  });

  _gLinks = [];
  Object.values(groups).forEach(grp => {
    const maxN = Math.min(grp.length, 20);
    for (let i = 0; i < maxN; i++) {
      for (let j = i+1; j < maxN; j++) {
        if (Math.random() < G_LINK_PROB) {
          _gLinks.push({source: grp[i].id, target: grp[j].id});
        }
      }
    }
  });
}

// ── DOM-Update (ohne Simulation-Neustart) ─────────────────────────────────
function _updateDOM() {
  if (!_gG) return;

  // Links
  _gLinkSel = _gG.select('.links')
    .selectAll('line')
    .data(_gLinks, d => `${d.source.id||d.source}-${d.target.id||d.target}`)
    .join('line')
      .attr('stroke', d => {
        const s = typeof d.source === 'object' ? d.source : _gNodeMap.get(d.source);
        return s ? _nodeColor(s) : '#4a6080';
      })
      .attr('stroke-opacity', 0.15)
      .attr('stroke-width', 1);

  // Nodes
  _gNodeSel = _gG.select('.nodes')
    .selectAll('g.node')
    .data(_gNodes, d => d.id)
    .join(
      enter => {
        const g = enter.append('g').attr('class', 'node')
          .style('cursor', 'pointer')
          .style('opacity', 0)
          .call(d3.drag()
            .on('start', (e, d) => { if (!e.active) _gSim.alphaTarget(0.3).restart(); d.fx=d.x; d.fy=d.y; })
            .on('drag',  (e, d) => { d.fx=e.x; d.fy=e.y; })
            .on('end',   (e, d) => { if (!e.active) _gSim.alphaTarget(0); d.fx=null; d.fy=null; })
          )
          .on('mouseover', _showTip)
          .on('mousemove', _moveTip)
          .on('mouseout',  _hideTip)
          .on('click', (e, d) => { e.stopPropagation(); if (typeof openModal === 'function') openModal(d); });

        // Glow-Ring
        g.append('circle').attr('class', 'glow-ring');
        // Haupt-Kreis
        g.append('circle').attr('class', 'main-circle');
        // Label
        g.append('text').attr('class', 'node-label');

        // Einflug-Animation
        g.transition().duration(600).style('opacity', 1);
        return g;
      },
      update => update,
      exit  => exit.transition().duration(300).style('opacity',0).remove()
    );

  // Attribute aktualisieren (enter + update)
  _gNodeSel.select('.glow-ring')
    .attr('r', d => _nodeR(d) + 4)
    .attr('fill', 'none')
    .attr('stroke', d => _nodeColor(d))
    .attr('stroke-width', 1.2)
    .attr('stroke-opacity', d => _isVisible(d) ? 0.45 : 0);

  _gNodeSel.select('.main-circle')
    .attr('r', d => _nodeR(d))
    .attr('fill', d => _nodeColor(d))
    .attr('fill-opacity', d => _isVisible(d) ? (d.lead_typ==='Hot' ? 0.92 : 0.65) : 0.08)
    .attr('stroke', '#0a1628')
    .attr('stroke-width', 0.5);

  _gNodeSel.select('.node-label')
    .attr('dy', '.35em')
    .attr('text-anchor', 'middle')
    .attr('font-size', '7px')
    .attr('fill', '#e0f4ff')
    .attr('pointer-events', 'none')
    .attr('opacity', d => (_isVisible(d) && _nodeR(d) >= 7) ? 1 : 0)
    .text(d => (d.name||'').substring(0, 13));

  // Simulation-Nodes + Links updaten
  _gSim.nodes(_gNodes);
  _gSim.force('link').links(_gLinks);
  _gSim.alpha(0.15).restart();
}

// ── Statistik-Bar updaten ─────────────────────────────────────────────────
function _updateStatBar() {
  const vis = _gNodes.filter(_isVisible);
  const hot  = vis.filter(d => d.lead_typ==='Hot').length;
  const warm = vis.filter(d => d.lead_typ==='Warm').length;
  const cold = vis.filter(d => d.lead_typ==='Cold').length;
  const el = document.getElementById('graph-stat-bar');
  if (el) el.innerHTML =
    `<span class="gsb-total">${vis.length} Leads</span>` +
    `<span class="gsb-hot">● ${hot} Hot</span>` +
    `<span class="gsb-warm">● ${warm} Warm</span>` +
    `<span class="gsb-cold">● ${cold} Cold</span>`;
  const cnt = document.getElementById('graph-node-count');
  if (cnt) cnt.textContent = vis.length + ' angezeigt / ' + _gNodes.length + ' gesamt';
}

// ── Legende ───────────────────────────────────────────────────────────────
function _updateLegend() {
  const el = document.getElementById('graph-legend');
  if (!el) return;
  const counts = {};
  _gNodes.forEach(d => {
    let k;
    if (_gGrouping === 'lead_typ')   k = d.lead_typ;
    else if (_gGrouping === 'bundesland') k = d.bundesland;
    else if (_gGrouping === 'potenzial') k = d.potenzial_euro >= 1500 ? '≥1500€' : '<1500€';
    else k = d.branche;
    counts[k] = (counts[k]||0) + 1;
  });
  const sorted = Object.entries(counts).sort((a,b) => b[1]-a[1]).slice(0, 12);
  el.innerHTML = sorted.map(([k, n]) =>
    `<span class="gl-item"><span class="gl-dot" style="background:${_getColor2(k)}"></span>${_esc(k)} <span class="gl-n">${n}</span></span>`
  ).join('');
}

function _getColor2(k) {
  if (_gGrouping === 'lead_typ') return TYPE_COLOR[k] || '#4a6080';
  if (_gGrouping === 'potenzial') return k.startsWith('≥') ? '#ffca28' : '#3d82f5';
  return _getColor(k);
}

// ── Tooltip ───────────────────────────────────────────────────────────────
function _showTip(e, d) {
  const tip = document.getElementById('graph-tooltip');
  if (!tip) return;
  tip.innerHTML = `
    <div class="gt-name">${_esc(d.name)}</div>
    <div class="gt-row"><span class="gt-k">Branche</span><span>${_esc(d.branche||'—')}</span></div>
    <div class="gt-row"><span class="gt-k">Stadt</span><span>${_esc(d.stadt||'—')}</span></div>
    <div class="gt-row"><span class="gt-k">Score</span><span class="gt-score-${d.lead_typ}">${d.score||0}</span></div>
    <div class="gt-row"><span class="gt-k">Potenzial</span><span style="color:#ffca28">${(d.potenzial_euro||0).toLocaleString('de-DE')} €</span></div>
    <div class="gt-row"><span class="gt-k">Website</span><span style="color:${d.has_website?'#00e676':'#ff3b50'}">${d.has_website?'✓ vorhanden':'✗ fehlt'}</span></div>
    ${d.pitch_hook ? `<div class="gt-pitch">"${_esc(d.pitch_hook)}"</div>` : ''}
    <div class="gt-hint">Klick für Details</div>`;
  tip.style.display = 'block';
  _moveTip(e);
}
function _moveTip(e) {
  const tip = document.getElementById('graph-tooltip');
  if (!tip || tip.style.display === 'none') return;
  const vw = window.innerWidth, vh = window.innerHeight;
  const tw = tip.offsetWidth + 20, th = tip.offsetHeight + 20;
  let lx = e.clientX + 16, ly = e.clientY - 10;
  if (lx + tw > vw) lx = e.clientX - tw;
  if (ly + th > vh) ly = e.clientY - th;
  tip.style.left = lx + 'px';
  tip.style.top  = ly + 'px';
}
function _hideTip() {
  const tip = document.getElementById('graph-tooltip');
  if (tip) tip.style.display = 'none';
}

function _esc(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

// ── Haupt-SVG setup ───────────────────────────────────────────────────────
function _setupSVG() {
  const wrap = document.getElementById('graph-wrap');
  if (!wrap) return;
  const W = wrap.clientWidth  || 900;
  const H = wrap.clientHeight || 540;

  const svg = d3.select('#graph-svg')
    .attr('width', W).attr('height', H);

  _gZoom = d3.zoom()
    .scaleExtent([0.15, 5])
    .on('zoom', e => _gG && _gG.attr('transform', e.transform));

  svg.call(_gZoom);

  // Hintergrund-Klick = Zoom-Reset
  svg.on('dblclick.zoom', null);

  _gG = svg.select('g.graph-root');
  if (_gG.empty()) {
    _gG = svg.append('g').attr('class', 'graph-root');
    _gG.append('g').attr('class', 'links');
    _gG.append('g').attr('class', 'nodes');
  }

  _initSimulation(W, H);

  // ResizeObserver
  if (window.ResizeObserver) {
    new ResizeObserver(() => {
      const nW = wrap.clientWidth, nH = wrap.clientHeight;
      svg.attr('width', nW).attr('height', nH);
      if (_gSim) {
        _gSim.force('center', d3.forceCenter(nW/2, nH/2).strength(0.05));
        _gSim.alpha(0.05).restart();
      }
    }).observe(wrap);
  }
}

// ── Daten laden (inkrementell!) ───────────────────────────────────────────
async function _fetchNew() {
  let nodes = [];
  try {
    // Nur neue Nodes holen (offset = aktuelle Anzahl)
    const r = await fetch(`/api/graph/nodes?limit=${G_MAX_NODES}&offset=${_gLastCount}`);
    const d = await r.json();
    nodes = d.nodes || [];
  } catch(e) {}

  if (!nodes.length) return false;

  // Neue Nodes in Map einfügen
  let added = false;
  nodes.forEach(n => {
    if (!_gNodeMap.has(n.id)) {
      _gNodeMap.set(n.id, n);
      _gNodes.push(n);
      added = true;
    }
  });
  _gLastCount = _gNodes.length;
  return added;
}

// ── Vollständiger erster Fetch ────────────────────────────────────────────
async function _fetchAll() {
  let nodes = [];
  try {
    const r = await fetch(`/api/graph/nodes?limit=${G_MAX_NODES}`);
    const d = await r.json();
    nodes = d.nodes || [];
  } catch(e) {}

  // Fallback: _allLeads aus app.js
  if (!nodes.length && typeof _allLeads !== 'undefined' && _allLeads.length) {
    nodes = _allLeads.map(l => ({
      id: l.id, name: l.name, branche: l.branche, stadt: l.stadt,
      bundesland: l.bundesland, score: l.score,
      potenzial_euro: l.score >= 72 ? 3000 : l.score >= 48 ? 1500 : 500,
      lead_typ: l.lead_typ, has_website: l.has_website,
      anz_bewertungen: l.anz_bewertungen,
    }));
  }

  _gNodes = [];
  _gNodeMap.clear();
  nodes.forEach(n => { _gNodeMap.set(n.id, n); _gNodes.push(n); });
  _gLastCount = _gNodes.length;
}

// ── Auto-Refresh ──────────────────────────────────────────────────────────
function _startAutoRefresh() {
  if (_gRefreshTimer) clearInterval(_gRefreshTimer);
  _gRefreshTimer = setInterval(async () => {
    if (!document.querySelector('[data-page="graph"]')?.classList.contains('active')) return;
    const hasNew = await _fetchNew();
    if (hasNew) {
      _rebuildLinks();
      _updateDOM();
      _updateStatBar();
      _updateLegend();
      // Bubble + Treemap alle 15s updaten (nicht bei jedem 3s-Tick)
      if (_gNodes.length % 5 === 0) {
        renderBubble(_gNodes);
        renderTreemap();
      }
    }
  }, G_REFRESH_MS);
}

function _stopAutoRefresh() {
  if (_gRefreshTimer) { clearInterval(_gRefreshTimer); _gRefreshTimer = null; }
}

// ── Öffentliche API ───────────────────────────────────────────────────────
async function initGraph() {
  if (_gInitDone) {
    // Beim erneuten Tab-Wechsel: nur refresh
    await refreshGraph();
    return;
  }
  _gInitDone = true;
  _setupSVG();
  await _fetchAll();
  _rebuildLinks();
  _updateDOM();
  _updateStatBar();
  _updateLegend();
  renderBubble(_gNodes);
  await renderTreemap();
  _startAutoRefresh();
}

async function refreshGraph() {
  await _fetchAll();
  _rebuildLinks();
  _updateDOM();
  _updateStatBar();
  _updateLegend();
  renderBubble(_gNodes);
  await renderTreemap();
}

function setGrouping(g) {
  _gGrouping = g;
  document.querySelectorAll('.gc-btn[data-group]').forEach(b =>
    b.classList.toggle('active', b.dataset.group === g));
  _colorIdx = 0; _colorMap.clear(); // Farben für neue Gruppierung zurücksetzen
  _rebuildLinks();
  _updateDOM();
  _updateStatBar();
  _updateLegend();
}

function setGraphSearch(val) {
  _gFilter = val.trim();
  _updateDOM();
  _updateStatBar();
}

function toggleHotOnly() {
  _gHotOnly = !_gHotOnly;
  document.getElementById('hot-only-btn')?.classList.toggle('active', _gHotOnly);
  _updateDOM();
  _updateStatBar();
}

function zoomReset() {
  const wrap = document.getElementById('graph-wrap');
  const svg = d3.select('#graph-svg');
  if (!wrap || !_gZoom) return;
  svg.transition().duration(500)
    .call(_gZoom.transform, d3.zoomIdentity.translate(wrap.clientWidth/2, wrap.clientHeight/2).scale(0.85).translate(-wrap.clientWidth/2, -wrap.clientHeight/2));
}

function graphOnNewLead(lead) {
  // Direktes Einfügen bei SSE-Event (für sub-3s-Reaktion wenn Tab aktiv)
  if (!document.querySelector('[data-page="graph"]')?.classList.contains('active')) return;
  if (_gNodeMap.has(lead.id)) return;
  const node = {
    id: lead.id, name: lead.name, branche: lead.branche, stadt: lead.stadt,
    bundesland: lead.bundesland, score: lead.score,
    potenzial_euro: lead.score >= 72 ? 3000 : lead.score >= 48 ? 1500 : 500,
    lead_typ: lead.lead_typ, has_website: lead.has_website,
    anz_bewertungen: lead.anz_bewertungen,
  };
  _gNodeMap.set(lead.id, node);
  _gNodes.push(node);
  _gLastCount = _gNodes.length;
  // Kein Link-Rebuild bei jedem Lead — passiert beim nächsten 3s-Tick
  _updateDOM();
  _updateStatBar();
}

// ── VIZ 2: Bubble-Chart (wie vorher, minimal überarbeitet) ────────────────
function renderBubble(nodes) {
  const wrap = document.getElementById('bubble-wrap');
  if (!wrap) return;
  const W = wrap.clientWidth || 900;
  const H = 400;
  const M = {top:24, right:28, bottom:48, left:58};
  const iW = W-M.left-M.right, iH = H-M.top-M.bottom;

  d3.select('#bubble-svg').selectAll('*').remove();
  const svg = d3.select('#bubble-svg').attr('width',W).attr('height',H);
  const g   = svg.append('g').attr('transform',`translate(${M.left},${M.top})`);

  const vis = nodes.filter(_isVisible);
  if (!vis.length) return;

  const xMax = Math.max(1000, d3.max(vis, d => d.potenzial_euro||500));
  const x = d3.scaleLinear().domain([0,xMax]).range([0,iW]);
  const y = d3.scaleLinear().domain([0,100]).range([iH,0]);
  const rS = d3.scaleSqrt().domain([0, d3.max(vis, d => d.anz_bewertungen||5)||5]).range([4,20]);

  g.append('g').attr('transform',`translate(0,${iH})`).call(d3.axisBottom(x).tickSize(-iH).ticks(5).tickFormat(v => v>=1000?(v/1000)+'k€':v+'€')).call(gg=>{
    gg.selectAll('line').attr('stroke','rgba(0,212,255,.06)').attr('stroke-dasharray','2');
    gg.select('.domain').remove();
    gg.selectAll('text').attr('fill','#4a6080').attr('font-size','10');
  });
  g.append('g').call(d3.axisLeft(y).tickSize(-iW).ticks(5)).call(gg=>{
    gg.selectAll('line').attr('stroke','rgba(0,212,255,.06)').attr('stroke-dasharray','2');
    gg.select('.domain').remove();
    gg.selectAll('text').attr('fill','#4a6080').attr('font-size','10');
  });

  g.append('text').attr('x',iW/2).attr('y',iH+40).attr('text-anchor','middle').attr('fill','#4a6080').attr('font-size','11').text('Potenzial (€)');
  g.append('text').attr('transform','rotate(-90)').attr('x',-iH/2).attr('y',-42).attr('text-anchor','middle').attr('fill','#4a6080').attr('font-size','11').text('Score');

  const tip = document.getElementById('graph-tooltip');
  g.selectAll('circle').data(vis).join('circle')
    .attr('cx', d => x(d.potenzial_euro||500))
    .attr('cy', d => y(d.score||0))
    .attr('r',  d => rS(d.anz_bewertungen||1))
    .attr('fill', d => _nodeColor(d))
    .attr('fill-opacity', 0.6)
    .attr('stroke', d => _nodeColor(d))
    .attr('stroke-width', 0.8)
    .attr('cursor','pointer')
    .on('mouseover', (e,d) => {
      tip.innerHTML = `<div class="gt-name">${_esc(d.name)}</div>
        <div class="gt-row"><span class="gt-k">Potenzial</span><span style="color:#ffca28">${(d.potenzial_euro||0).toLocaleString('de-DE')} €</span></div>
        <div class="gt-row"><span class="gt-k">Score</span><span class="gt-score-${d.lead_typ}">${d.score}</span></div>
        <div class="gt-row"><span class="gt-k">${_gGrouping.charAt(0).toUpperCase()+_gGrouping.slice(1)}</span><span>${_esc(d[_gGrouping]||'—')}</span></div>`;
      tip.style.display='block'; _moveTip(e);
    })
    .on('mousemove', _moveTip)
    .on('mouseout', _hideTip)
    .on('click', (e,d)=>{ if(typeof openModal==='function') openModal(d); });
}

// ── VIZ 3: Treemap (wie vorher, minimal überarbeitet) ─────────────────────
async function renderTreemap() {
  const wrap = document.getElementById('treemap-wrap');
  if (!wrap) return;
  const W = wrap.clientWidth||900, H = 440;

  let stats = null;
  try {
    const r = await fetch('/api/graph/stats');
    stats = await r.json();
  } catch(e) {}

  if (!stats || !Object.keys(stats).length) {
    stats = {};
    _gNodes.forEach(d => {
      const bl=d.bundesland||'Unbekannt', br=d.branche||'Sonstiges', lt=d.lead_typ||'Cold';
      if(!stats[bl]) stats[bl]={};
      if(!stats[bl][br]) stats[bl][br]={Hot:0,Warm:0,Cold:0};
      stats[bl][br][lt]++;
    });
  }

  const root_data = {name:'DE', children:[]};
  for(const [bl,brs] of Object.entries(stats)) {
    const bl_n = {name:bl, children:[]};
    for(const [br,types] of Object.entries(brs)) {
      const total=(types.Hot||0)+(types.Warm||0)+(types.Cold||0);
      if(total>0) bl_n.children.push({name:br, value:total, hot:types.Hot||0, warm:types.Warm||0, cold:types.Cold||0});
    }
    if(bl_n.children.length) root_data.children.push(bl_n);
  }

  d3.select('#treemap-svg').selectAll('*').remove();
  if(!root_data.children.length) return;

  const svg = d3.select('#treemap-svg').attr('width',W).attr('height',H);
  const hier = d3.hierarchy(root_data).sum(d=>d.value||0).sort((a,b)=>b.value-a.value);
  d3.treemap().size([W,H]).paddingOuter(3).paddingInner(2).round(true)(hier);

  const tip = document.getElementById('graph-tooltip');
  const leaf = svg.selectAll('g').data(hier.leaves()).join('g')
    .attr('transform', d=>`translate(${d.x0},${d.y0})`);

  leaf.append('rect')
    .attr('width',  d=>Math.max(0,d.x1-d.x0))
    .attr('height', d=>Math.max(0,d.y1-d.y0))
    .attr('fill',   d=>{ const r=d.data.hot/(d.data.value||1); return r>0.4?'#ff3b50':r>0.15?'#ffca28':_getColor(d.data.name); })
    .attr('fill-opacity', 0.7)
    .attr('stroke','#0a1628').attr('stroke-width',0.5).attr('cursor','pointer')
    .on('mouseover',(e,d)=>{
      tip.innerHTML=`<div class="gt-name">${_esc(d.data.name)}</div>
        <div class="gt-row"><span class="gt-k">Bundesland</span><span>${_esc(d.parent?.data?.name||'')}</span></div>
        <div class="gt-row"><span class="gt-k">Gesamt</span><span>${d.data.value}</span></div>
        <div class="gt-row" style="color:#ff3b50"><span class="gt-k">Hot</span><span>${d.data.hot}</span></div>
        <div class="gt-row" style="color:#ffca28"><span class="gt-k">Warm</span><span>${d.data.warm}</span></div>
        <div class="gt-row" style="color:#3d82f5"><span class="gt-k">Cold</span><span>${d.data.cold}</span></div>`;
      tip.style.display='block'; _moveTip(e);
    })
    .on('mousemove',_moveTip).on('mouseout',_hideTip);

  leaf.filter(d=>(d.x1-d.x0)>50&&(d.y1-d.y0)>22).append('text')
    .attr('x',5).attr('y',14).attr('font-size','9px').attr('fill','#e0f4ff')
    .text(d=>d.data.name.substring(0,15));
  leaf.filter(d=>(d.x1-d.x0)>36&&(d.y1-d.y0)>34).append('text')
    .attr('x',5).attr('y',25).attr('font-size','8px').attr('fill','rgba(224,244,255,.55)')
    .text(d=>d.data.value+' Leads');
}
