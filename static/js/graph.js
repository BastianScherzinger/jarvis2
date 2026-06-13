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
let _gRefreshTimer = null;
let _gLastMaxId  = 0;         // Höchste bekannte ID für inkrementellen Fetch
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
    .force('link',    d3.forceLink(_gLinks).id(d => d.id).distance(60).strength(0.3))
    .force('charge',  d3.forceManyBody().strength(-90).distanceMax(250))
    .force('center',  d3.forceCenter(W/2, H/2).strength(0.12))
    .force('collide', d3.forceCollide(d => _nodeR(d) + 6).strength(0.85))
    .alphaDecay(0.03)
    .velocityDecay(0.55);

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

  // Nodes — kein Drag (alles fest nach Simulation)
  _gNodeSel = _gG.select('.nodes')
    .selectAll('g.node')
    .data(_gNodes, d => d.id)
    .join(
      enter => {
        const g = enter.append('g').attr('class', 'node')
          .style('cursor', 'pointer')
          .style('opacity', 0)
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

  // Simulation-Nodes + Links updaten — sanfter Neustart (wenig Bewegung)
  _gSim.nodes(_gNodes);
  _gSim.force('link').links(_gLinks);
  _gSim.alpha(0.08).restart();
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
    .attr('width', W).attr('height', H)
    .style('touch-action', 'none');  // kein Pinch-Zoom auf Touch

  // Zoom/Pan DEAKTIVIERT — Karte ist fest
  svg.on('.zoom', null);
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
        _gSim.force('center', d3.forceCenter(nW/2, nH/2).strength(0.12));
        _gSim.alpha(0.05).restart();
      }
    }).observe(wrap);
  }
}

// ── Daten laden (inkrementell — nur neue IDs) ─────────────────────────────
async function _fetchNew() {
  if (_gLastMaxId === 0) return false;
  let nodes = [];
  try {
    const r = await fetch(`/api/graph/nodes?limit=${G_MAX_NODES}&min_id=${_gLastMaxId}`);
    const d = await r.json();
    nodes = d.nodes || [];
  } catch(e) {}

  if (!nodes.length) return false;

  let added = false;
  nodes.forEach(n => {
    if (!_gNodeMap.has(n.id)) {
      _gNodeMap.set(n.id, n);
      _gNodes.push(n);
      if (n.id > _gLastMaxId) _gLastMaxId = n.id;
      added = true;
    }
  });
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
  _gLastMaxId = 0;
  nodes.forEach(n => {
    _gNodeMap.set(n.id, n);
    _gNodes.push(n);
    if (n.id > _gLastMaxId) _gLastMaxId = n.id;
  });
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
      renderBarChart();
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
  renderBarChart();
  _startAutoRefresh();
}

async function refreshGraph() {
  await _fetchAll();
  _rebuildLinks();
  _updateDOM();
  _updateStatBar();
  _updateLegend();
  renderBarChart();
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
  // Neu-Layout: Simulation kurz aufwärmen damit Knoten sich neu positionieren
  if (_gSim) _gSim.alpha(0.4).restart();
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
  if (lead.id > _gLastMaxId) _gLastMaxId = lead.id;
  // Kein Link-Rebuild bei jedem Lead — passiert beim nächsten 3s-Tick
  _updateDOM();
  _updateStatBar();
}

// ── VIZ 2: Balken-Diagramm (umschaltbare Kategorie) ───────────────────────
let _barCat = 'branche';   // branche | bundesland | stadt | lead_typ

function setBarCategory(cat) {
  _barCat = cat;
  document.querySelectorAll('.bar-cat-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.cat === cat));
  renderBarChart();
}

function _barKey(d) {
  if (_barCat === 'bundesland') return d.bundesland || 'Unbekannt';
  if (_barCat === 'stadt')      return d.stadt || 'Unbekannt';
  if (_barCat === 'lead_typ')   return d.lead_typ || 'Cold';
  return d.branche || 'Sonstiges';
}

function renderBarChart() {
  const wrap = document.getElementById('bar-wrap');
  if (!wrap) return;
  const W = wrap.clientWidth || 900;

  const vis = _gNodes.filter(_isVisible);

  // Aggregieren nach gewählter Kategorie, gestapelt nach Lead-Typ
  const agg = {};
  vis.forEach(d => {
    const k = _barKey(d);
    if (!agg[k]) agg[k] = { key: k, total: 0, Hot: 0, Warm: 0, Cold: 0 };
    agg[k].total++;
    agg[k][d.lead_typ || 'Cold']++;
  });

  const rows = Object.values(agg).sort((a, b) => b.total - a.total).slice(0, 15);

  const M = { top: 8, right: 56, bottom: 26, left: 140 };
  const rowH = 28;
  const innerH = Math.max(rowH, rows.length * rowH);
  const H = innerH + M.top + M.bottom;
  const iW = Math.max(120, W - M.left - M.right);

  d3.select('#bar-svg').selectAll('*').remove();
  const svg = d3.select('#bar-svg').attr('width', W).attr('height', H);

  if (!rows.length) {
    svg.append('text').attr('x', W / 2).attr('y', 60).attr('text-anchor', 'middle')
      .attr('fill', '#4a6080').attr('font-size', '13').text('Noch keine Daten — Scraper starten');
    return;
  }

  const g = svg.append('g').attr('transform', `translate(${M.left},${M.top})`);
  const maxV = d3.max(rows, d => d.total) || 1;
  const x = d3.scaleLinear().domain([0, maxV]).range([0, iW]);
  const y = d3.scaleBand().domain(rows.map(d => d.key)).range([0, innerH]).padding(0.22);

  // X-Gitter
  g.append('g').attr('transform', `translate(0,${innerH})`)
    .call(d3.axisBottom(x).ticks(5).tickSize(-innerH))
    .call(gg => {
      gg.selectAll('line').attr('stroke', 'rgba(0,212,255,.06)').attr('stroke-dasharray', '2');
      gg.select('.domain').remove();
      gg.selectAll('text').attr('fill', '#4a6080').attr('font-size', '10');
    });

  // Kategorie-Labels (links)
  g.append('g').call(d3.axisLeft(y).tickSize(0))
    .call(gg => {
      gg.select('.domain').remove();
      gg.selectAll('text').attr('fill', '#c0d0e0').attr('font-size', '11')
        .text(t => t.length > 19 ? t.slice(0, 18) + '…' : t);
    });

  const tip = document.getElementById('graph-tooltip');
  const TYPES = ['Hot', 'Warm', 'Cold'];

  rows.forEach(row => {
    let xOff = 0;
    TYPES.forEach(t => {
      const v = row[t] || 0;
      if (v <= 0) return;
      g.append('rect')
        .attr('x', x(xOff))
        .attr('y', y(row.key))
        .attr('height', y.bandwidth())
        .attr('width', 0)
        .attr('fill', TYPE_COLOR[t])
        .attr('fill-opacity', 0.85)
        .attr('rx', 2)
        .style('cursor', 'pointer')
        .on('mouseover', (e) => {
          tip.innerHTML = `<div class="gt-name">${_esc(row.key)}</div>
            <div class="gt-row"><span class="gt-k">Gesamt</span><span>${row.total}</span></div>
            <div class="gt-row" style="color:#ff3b50"><span class="gt-k">Hot</span><span>${row.Hot}</span></div>
            <div class="gt-row" style="color:#ffca28"><span class="gt-k">Warm</span><span>${row.Warm}</span></div>
            <div class="gt-row" style="color:#3d82f5"><span class="gt-k">Cold</span><span>${row.Cold}</span></div>`;
          tip.style.display = 'block'; _moveTip(e);
        })
        .on('mousemove', _moveTip)
        .on('mouseout', _hideTip)
        .transition().duration(450)
        .attr('width', Math.max(0, x(v)));
      xOff += v;
    });

    // Gesamt-Zahl am Balken-Ende
    g.append('text')
      .attr('x', x(row.total) + 6)
      .attr('y', y(row.key) + y.bandwidth() / 2)
      .attr('dy', '.35em')
      .attr('font-size', '11px')
      .attr('fill', '#e0f4ff')
      .attr('font-family', 'JetBrains Mono, monospace')
      .text(row.total);
  });
}
