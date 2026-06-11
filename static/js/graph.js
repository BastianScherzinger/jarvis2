'use strict';
/* ── JARVIS LeadHunter — Graph-Visualisierungen ─────────────────────────── */

// ── State ──────────────────────────────────────────────────────────────────
let _gNodes      = [];   // Array<{id,name,branche,stadt,bundesland,score,potenzial_euro,lead_typ,has_website}>
let _gGrouping   = 'branche';
let _gSimulation = null;
let _gSvg        = null;

// ── Farben ─────────────────────────────────────────────────────────────────
const TYPE_COLOR = { Hot:'#ff3b50', Warm:'#ffca28', Cold:'#3d82f5' };
const BRANCH_PALETTE = [
  '#00d4ff','#ff6b35','#7b61ff','#00e676','#ff4081',
  '#ffab40','#40c4ff','#ea80fc','#69f0ae','#ff6d00',
  '#b2ff59','#f06292',
];
const _branchColor = new Map();
let   _branchIdx   = 0;
function branchColor(b) {
  if (!_branchColor.has(b)) _branchColor.set(b, BRANCH_PALETTE[_branchIdx++ % BRANCH_PALETTE.length]);
  return _branchColor.get(b);
}

function groupColor(d) {
  if (_gGrouping === 'lead_typ')   return TYPE_COLOR[d.lead_typ] || '#3d82f5';
  if (_gGrouping === 'bundesland') return branchColor(d.bundesland || '?');
  if (_gGrouping === 'potenzial')  {
    const p = d.potenzial_euro || 0;
    return p >= 3000 ? '#ff3b50' : p >= 1500 ? '#ffca28' : '#3d82f5';
  }
  return branchColor(d.branche || '?');
}

// ── Init ──────────────────────────────────────────────────────────────────
async function initGraph() {
  await refreshGraph();
}

async function refreshGraph() {
  // 1. Versuche /api/graph/nodes (DB2)
  let nodes = [];
  try {
    const r = await fetch('/api/graph/nodes?limit=1500');
    const d = await r.json();
    nodes = d.nodes || [];
  } catch(e) {}

  // 2. Fallback: _allLeads aus leads.js (definiert in app.js)
  if (!nodes.length && typeof _allLeads !== 'undefined') {
    nodes = _allLeads.map(l => ({
      id: l.id, name: l.name, branche: l.branche, stadt: l.stadt,
      bundesland: l.bundesland, score: l.score,
      potenzial_euro: l.score >= 72 ? 3000 : l.score >= 48 ? 1500 : 500,
      lead_typ: l.lead_typ, has_website: l.has_website,
      anz_bewertungen: l.anz_bewertungen,
    }));
  }

  _gNodes = nodes;
  document.getElementById('graph-node-count').textContent = nodes.length + ' Leads';

  if (!nodes.length) {
    document.getElementById('graph-svg').innerHTML =
      '<text x="50%" y="50%" text-anchor="middle" fill="#4a6080" font-size="14" dy=".3em">Noch keine bewerteten Leads — Scraper starten</text>';
    return;
  }

  renderForceGraph(nodes);
  renderBubble(nodes);
  await renderTreemap();
}

// ── VIZ 1: Force-Directed Graph ───────────────────────────────────────────
function renderForceGraph(nodes) {
  const wrap = document.getElementById('graph-wrap');
  const W = wrap.clientWidth  || 900;
  const H = wrap.clientHeight || 520;

  d3.select('#graph-svg').selectAll('*').remove();
  const svg = d3.select('#graph-svg')
    .attr('width', W).attr('height', H);
  _gSvg = svg;

  // Zoom + Pan
  const g = svg.append('g').attr('class', 'graph-g');
  svg.call(d3.zoom().scaleExtent([0.2, 4]).on('zoom', e => g.attr('transform', e.transform)));

  // Arbeits-Kopie der Nodes (D3 mutiert sie)
  const simNodes = nodes.map(d => ({...d}));

  // Links zwischen Nodes gleicher Gruppe
  const groupKey = d => {
    if (_gGrouping === 'branche')    return d.branche;
    if (_gGrouping === 'bundesland') return d.bundesland;
    if (_gGrouping === 'lead_typ')   return d.lead_typ;
    if (_gGrouping === 'potenzial')  return d.potenzial_euro >= 1500 ? 'hoch' : 'niedrig';
    return d.branche;
  };

  // Nur Intra-Gruppen-Links (max 3 pro Node um Chaos zu vermeiden)
  const groups = {};
  simNodes.forEach(d => {
    const k = groupKey(d);
    if (!groups[k]) groups[k] = [];
    groups[k].push(d);
  });
  const links = [];
  Object.values(groups).forEach(grp => {
    for (let i = 0; i < Math.min(grp.length, 15); i++) {
      for (let j = i+1; j < Math.min(grp.length, 15); j++) {
        if (Math.random() < 0.25) links.push({source: grp[i], target: grp[j]});
      }
    }
  });

  // Simulation
  if (_gSimulation) _gSimulation.stop();
  _gSimulation = d3.forceSimulation(simNodes)
    .force('link',    d3.forceLink(links).distance(60).strength(0.3))
    .force('charge',  d3.forceManyBody().strength(-80))
    .force('center',  d3.forceCenter(W/2, H/2))
    .force('collide', d3.forceCollide(d => nodeRadius(d) + 3));

  // Kanten
  const link = g.append('g').attr('class', 'links')
    .selectAll('line').data(links).join('line')
    .attr('stroke', d => groupColor(d.source))
    .attr('stroke-opacity', 0.2)
    .attr('stroke-width', 1);

  // Knoten-Gruppe
  const node = g.append('g').attr('class', 'nodes')
    .selectAll('g').data(simNodes).join('g')
    .attr('class', 'node')
    .style('cursor', 'pointer')
    .call(d3.drag()
      .on('start', (e, d) => { if (!e.active) _gSimulation.alphaTarget(0.3).restart(); d.fx=d.x; d.fy=d.y; })
      .on('drag',  (e, d) => { d.fx=e.x; d.fy=e.y; })
      .on('end',   (e, d) => { if (!e.active) _gSimulation.alphaTarget(0); d.fx=null; d.fy=null; })
    )
    .on('mouseover', showTooltip)
    .on('mouseout',  hideTooltip)
    .on('click', (e, d) => { e.stopPropagation(); if (typeof openModal === 'function') openModal(d); });

  // Äußerer Glow-Ring
  node.append('circle')
    .attr('r', d => nodeRadius(d) + 3)
    .attr('fill', 'none')
    .attr('stroke', d => groupColor(d))
    .attr('stroke-width', 1)
    .attr('stroke-opacity', 0.4);

  // Haupt-Kreis
  node.append('circle')
    .attr('r', d => nodeRadius(d))
    .attr('fill', d => groupColor(d))
    .attr('fill-opacity', d => d.lead_typ === 'Hot' ? 0.9 : 0.65)
    .attr('stroke', '#0d1a2e')
    .attr('stroke-width', 0.5);

  // Label (nur bei größeren Nodes sichtbar)
  node.filter(d => nodeRadius(d) >= 6).append('text')
    .attr('dy', '.35em')
    .attr('text-anchor', 'middle')
    .attr('font-size', '7px')
    .attr('fill', '#e0f4ff')
    .attr('pointer-events', 'none')
    .text(d => (d.name || '').substring(0, 12));

  // Tick
  _gSimulation.on('tick', () => {
    link.attr('x1', d=>d.source.x).attr('y1', d=>d.source.y)
        .attr('x2', d=>d.target.x).attr('y2', d=>d.target.y);
    node.attr('transform', d => `translate(${d.x},${d.y})`);
  });
}

function nodeRadius(d) {
  // Größe nach Potenzial: 500→4, 1500→6, 3000→8, 5000→11
  const p = d.potenzial_euro || 500;
  return p >= 5000 ? 11 : p >= 3000 ? 8 : p >= 1500 ? 6 : 4;
}

function showTooltip(e, d) {
  const tip = document.getElementById('graph-tooltip');
  tip.innerHTML = `
    <div class="gt-name">${_esc(d.name)}</div>
    <div class="gt-row"><span class="gt-k">Branche</span><span>${_esc(d.branche||'—')}</span></div>
    <div class="gt-row"><span class="gt-k">Stadt</span><span>${_esc(d.stadt||'—')}</span></div>
    <div class="gt-row"><span class="gt-k">Score</span><span class="gt-score-${d.lead_typ}">${d.score}</span></div>
    <div class="gt-row"><span class="gt-k">Potenzial</span><span>${(d.potenzial_euro||0).toLocaleString('de')} €</span></div>
    <div class="gt-row"><span class="gt-k">Website</span><span>${d.has_website ? '✓ vorhanden' : '✗ fehlt'}</span></div>`;
  tip.style.display = 'block';
  tip.style.left = (e.clientX + 14) + 'px';
  tip.style.top  = (e.clientY - 14) + 'px';
}
function hideTooltip() { document.getElementById('graph-tooltip').style.display='none'; }

function _esc(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;'); }

// ── Grouping wechseln ──────────────────────────────────────────────────────
function setGrouping(g) {
  _gGrouping = g;
  document.querySelectorAll('.gc-btn[data-group]').forEach(b =>
    b.classList.toggle('active', b.dataset.group === g));
  if (_gNodes.length) {
    renderForceGraph(_gNodes);
    renderBubble(_gNodes);
  }
}

// ── VIZ 2: Bubble-Chart ────────────────────────────────────────────────────
function renderBubble(nodes) {
  const wrap = document.getElementById('bubble-wrap');
  const W = wrap.clientWidth  || 900;
  const H = 420;
  const M = {top:30, right:30, bottom:50, left:60};
  const iW = W - M.left - M.right;
  const iH = H - M.top  - M.bottom;

  d3.select('#bubble-svg').selectAll('*').remove();
  const svg = d3.select('#bubble-svg').attr('width', W).attr('height', H);
  const g   = svg.append('g').attr('transform', `translate(${M.left},${M.top})`);

  // Skalen
  const xMax = Math.max(500, d3.max(nodes, d => d.potenzial_euro || 500));
  const x = d3.scaleLinear().domain([0, xMax]).range([0, iW]);
  const y = d3.scaleLinear().domain([0, 100]).range([iH, 0]);
  const r = d3.scaleSqrt().domain([0, d3.max(nodes, d => d.anz_bewertungen || 10) || 10]).range([4, 22]);

  // Gitter
  g.append('g').attr('class', 'grid')
    .attr('transform', `translate(0,${iH})`)
    .call(d3.axisBottom(x).tickSize(-iH).tickFormat(v => v >= 1000 ? (v/1000)+'k€' : v+'€'))
    .call(gg => gg.selectAll('line').attr('stroke','rgba(255,255,255,.06)').attr('stroke-dasharray','3'))
    .call(gg => gg.select('.domain').remove())
    .call(gg => gg.selectAll('text').attr('fill','#4a6080').attr('font-size','10'));

  g.append('g').attr('class', 'grid')
    .call(d3.axisLeft(y).tickSize(-iW).ticks(5))
    .call(gg => gg.selectAll('line').attr('stroke','rgba(255,255,255,.06)').attr('stroke-dasharray','3'))
    .call(gg => gg.select('.domain').remove())
    .call(gg => gg.selectAll('text').attr('fill','#4a6080').attr('font-size','10'));

  // Achsen-Labels
  g.append('text').attr('x', iW/2).attr('y', iH+42).attr('text-anchor','middle')
    .attr('fill','#4a6080').attr('font-size','11').text('Potenzial (€)');
  g.append('text').attr('transform','rotate(-90)').attr('x', -iH/2).attr('y', -45)
    .attr('text-anchor','middle').attr('fill','#4a6080').attr('font-size','11').text('Score');

  // Dots
  const tip = document.getElementById('graph-tooltip');
  g.selectAll('circle').data(nodes).join('circle')
    .attr('cx', d => x(d.potenzial_euro || 500))
    .attr('cy', d => y(d.score || 0))
    .attr('r',  d => r(d.anz_bewertungen || 1))
    .attr('fill',  d => groupColor(d))
    .attr('fill-opacity', 0.65)
    .attr('stroke', d => groupColor(d))
    .attr('stroke-width', 0.8)
    .attr('cursor', 'pointer')
    .on('mouseover', (e, d) => {
      tip.innerHTML = `<div class="gt-name">${_esc(d.name)}</div>
        <div class="gt-row"><span class="gt-k">Potenzial</span><span>${(d.potenzial_euro||0).toLocaleString('de')} €</span></div>
        <div class="gt-row"><span class="gt-k">Score</span><span class="gt-score-${d.lead_typ}">${d.score}</span></div>
        <div class="gt-row"><span class="gt-k">Branche</span><span>${_esc(d.branche||'—')}</span></div>`;
      tip.style.display='block'; tip.style.left=(e.clientX+14)+'px'; tip.style.top=(e.clientY-14)+'px';
    })
    .on('mouseout', hideTooltip)
    .on('click', (e, d) => { if (typeof openModal === 'function') openModal(d); });
}

// ── VIZ 3: Treemap ────────────────────────────────────────────────────────
async function renderTreemap() {
  const wrap = document.getElementById('treemap-wrap');
  const W = wrap.clientWidth  || 900;
  const H = 460;

  // Versuche /api/graph/stats
  let statsData = null;
  try {
    const r = await fetch('/api/graph/stats');
    statsData = await r.json();
  } catch(e) {}

  // Fallback: aus _gNodes aggregieren
  if (!statsData || !Object.keys(statsData).length) {
    statsData = {};
    _gNodes.forEach(d => {
      const bl = d.bundesland || 'Unbekannt';
      const br = d.branche    || 'Sonstiges';
      const lt = d.lead_typ   || 'Cold';
      if (!statsData[bl]) statsData[bl] = {};
      if (!statsData[bl][br]) statsData[bl][br] = {Hot:0, Warm:0, Cold:0};
      statsData[bl][br][lt] = (statsData[bl][br][lt]||0) + 1;
    });
  }

  // Hierarchie aufbauen
  const root_data = {name:"DE", children: []};
  for (const [bl, branchen] of Object.entries(statsData)) {
    const bl_node = {name: bl, children: []};
    for (const [br, types] of Object.entries(branchen)) {
      const total = (types.Hot||0) + (types.Warm||0) + (types.Cold||0);
      if (total > 0) {
        bl_node.children.push({name: br, value: total, hot: types.Hot||0, warm: types.Warm||0, cold: types.Cold||0});
      }
    }
    if (bl_node.children.length) root_data.children.push(bl_node);
  }

  d3.select('#treemap-svg').selectAll('*').remove();
  if (!root_data.children.length) return;

  const svg = d3.select('#treemap-svg').attr('width', W).attr('height', H);

  const hier = d3.hierarchy(root_data)
    .sum(d => d.value || 0)
    .sort((a,b) => b.value - a.value);

  d3.treemap().size([W, H]).paddingOuter(4).paddingInner(2).round(true)(hier);

  // Nur Leaf-Nodes rendern
  const tip = document.getElementById('graph-tooltip');
  const leaf = svg.selectAll('g').data(hier.leaves()).join('g')
    .attr('transform', d => `translate(${d.x0},${d.y0})`);

  leaf.append('rect')
    .attr('width',  d => Math.max(0, d.x1 - d.x0))
    .attr('height', d => Math.max(0, d.y1 - d.y0))
    .attr('fill',   d => {
      const r = d.data.hot / (d.data.value||1);
      return r > 0.4 ? '#ff3b50' : r > 0.15 ? '#ffca28' : branchColor(d.data.name);
    })
    .attr('fill-opacity', 0.72)
    .attr('stroke', '#0d1a2e')
    .attr('stroke-width', 0.5)
    .attr('cursor', 'pointer')
    .on('mouseover', (e, d) => {
      tip.innerHTML = `<div class="gt-name">${_esc(d.data.name)}</div>
        <div class="gt-row"><span class="gt-k">BL</span><span>${_esc(d.parent?.data?.name||'')}</span></div>
        <div class="gt-row"><span class="gt-k">Gesamt</span><span>${d.data.value}</span></div>
        <div class="gt-row" style="color:#ff3b50"><span class="gt-k">Hot</span><span>${d.data.hot}</span></div>
        <div class="gt-row" style="color:#ffca28"><span class="gt-k">Warm</span><span>${d.data.warm}</span></div>`;
      tip.style.display='block'; tip.style.left=(e.clientX+14)+'px'; tip.style.top=(e.clientY-14)+'px';
    })
    .on('mouseout', hideTooltip);

  // Labels (nur wenn Kachel groß genug)
  leaf.filter(d => (d.x1-d.x0) > 55 && (d.y1-d.y0) > 25).append('text')
    .attr('x', 5).attr('y', 14)
    .attr('font-size', '9px').attr('fill', '#e0f4ff').attr('font-family', 'Inter, sans-serif')
    .text(d => d.data.name.substring(0, 14));

  leaf.filter(d => (d.x1-d.x0) > 40 && (d.y1-d.y0) > 36).append('text')
    .attr('x', 5).attr('y', 25)
    .attr('font-size', '8px').attr('fill', 'rgba(224,244,255,.6)').attr('font-family', 'Inter, sans-serif')
    .text(d => d.data.value + ' Leads');
}

// ── Live-Update (SSE-Integration) ─────────────────────────────────────────
function graphOnNewLead(lead) {
  // Neuen Node in Sphäre einfügen wenn Graph aktiv
  if (document.querySelector('[data-page="graph"]')?.classList.contains('active')) {
    const node = {
      id: lead.id, name: lead.name, branche: lead.branche, stadt: lead.stadt,
      bundesland: lead.bundesland, score: lead.score,
      potenzial_euro: lead.score >= 72 ? 3000 : lead.score >= 48 ? 1500 : 500,
      lead_typ: lead.lead_typ, has_website: lead.has_website,
      anz_bewertungen: lead.anz_bewertungen,
    };
    _gNodes.push(node);
    document.getElementById('graph-node-count').textContent = _gNodes.length + ' Leads';
    // Kein vollständiges Re-Render bei jedem Lead — nur bei Tab-Aktivierung oder manuell
  }
}
