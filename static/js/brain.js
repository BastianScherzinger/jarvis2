/* ═══════════════════════════════════════════════════════════════════
   JARVIS brain.js  v4 — Knowledge Sphere
   (Background-Scene entfernt — wird von index.html initNexusScene gerendert)
   ═══════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  /* ══════════════════════════════════════════════════════════════════
     KNOWLEDGE SPHERE
  ══════════════════════════════════════════════════════════════════ */
  let kScene, kCam, kRenderer, kGroup;
  let kNodes     = [];    // { mesh, hitbox, label, type }
  let kTooltip   = null;
  let isDragging = false;
  let dragPrev   = { x: 0, y: 0 };
  let kVel       = { x: 0, y: 0 };
  let autoRotate = true;
  let hoveredNode  = null;
  let pinnedNode   = null;
  let kPinLabel    = null;
  let _dragMoved   = false;
  let ptA, ptB, ptC;
  const RC     = new THREE.Raycaster();
  const mouse2 = new THREE.Vector2(-99, -99);

  function initKnowledge(canvas) {
    if (!canvas || !window.THREE) return;

    /* ── Canvas sizing — override CSS completely ───────────────── */
    const wrap = canvas.parentElement;
    const SIZE = (wrap && wrap.clientWidth > 0) ? wrap.clientWidth : 252;
    canvas.width  = SIZE * window.devicePixelRatio;
    canvas.height = SIZE * window.devicePixelRatio;
    canvas.style.width  = SIZE + 'px';
    canvas.style.height = SIZE + 'px';

    /* ── Three.js scene ─────────────────────────────────────────── */
    kScene = new THREE.Scene();
    kCam   = new THREE.PerspectiveCamera(54, 1, 0.01, 100);
    kCam.position.z = 3.2;

    kRenderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    kRenderer.setSize(SIZE, SIZE, false);   // false = don't override style
    kRenderer.setPixelRatio(window.devicePixelRatio);
    kRenderer.setClearColor(0x000000, 0);

    /* ── Lights ─────────────────────────────────────────────────── */
    kScene.add(new THREE.AmbientLight(0x001133, 3));
    ptA = new THREE.PointLight(0x00d4ff, 6, 12);  ptA.position.set(2.5, 2, 3);  kScene.add(ptA);
    ptB = new THREE.PointLight(0x00ff88, 4, 12);  ptB.position.set(-2, -1, 2);  kScene.add(ptB);
    ptC = new THREE.PointLight(0xffffff, 2, 8);   ptC.position.set(0, 0, 3.5);  kScene.add(ptC);

    /* ── Group ──────────────────────────────────────────────────── */
    kGroup = new THREE.Group();
    kScene.add(kGroup);

    /* ── Wireframe shells ───────────────────────────────────────── */
    [
      { r: 1.46, op: 0.05 },
      { r: 1.12, op: 0.03 },
      { r: 0.78, op: 0.02 },
    ].forEach(({ r, op }) => {
      const m = new THREE.Mesh(
        new THREE.IcosahedronGeometry(r, 2),
        new THREE.MeshBasicMaterial({ color: 0x00d4ff, wireframe: true, transparent: true, opacity: op })
      );
      kGroup.add(m);
    });

    /* ── Central arc-reactor core ───────────────────────────────── */
    const coreGeo = new THREE.SphereGeometry(0.14, 16, 16);
    const coreMat = new THREE.MeshPhongMaterial({
      color: 0x00e5ff, emissive: 0x00e5ff, emissiveIntensity: 1.2,
      transparent: true, opacity: 0.95,
    });
    const core = new THREE.Mesh(coreGeo, coreMat);
    kGroup.add(core);
    const coreHalo = new THREE.Mesh(
      new THREE.SphereGeometry(0.32, 12, 12),
      new THREE.MeshBasicMaterial({ color: 0x00d4ff, transparent: true, opacity: 0.15, blending: THREE.AdditiveBlending, depthWrite: false })
    );
    kGroup.add(coreHalo);

    /* ── Equator orbit ring ─────────────────────────────────────── */
    const orbitRing = new THREE.Mesh(
      new THREE.TorusGeometry(1.0, 0.006, 8, 80),
      new THREE.MeshBasicMaterial({ color: 0x00d4ff, transparent: true, opacity: 0.35 })
    );
    kGroup.add(orbitRing);

    /* ── Tooltip ────────────────────────────────────────────────── */
    kTooltip = document.createElement('div');
    Object.assign(kTooltip.style, {
      position:        'fixed',
      background:      'rgba(0,10,22,0.95)',
      color:           '#00e5a0',
      border:          '1px solid rgba(0,212,255,0.4)',
      padding:         '4px 13px 5px',
      borderRadius:    '3px',
      fontSize:        '10px',
      fontFamily:      '"Share Tech Mono",monospace',
      letterSpacing:   '0.1em',
      textTransform:   'uppercase',
      pointerEvents:   'none',
      opacity:         '0',
      transition:      'opacity 0.12s',
      whiteSpace:      'nowrap',
      zIndex:          '9999',
      boxShadow:       '0 0 14px rgba(0,212,255,0.25)',
    });
    document.body.appendChild(kTooltip);

    /* Pin-Label — nach Klick stehen bleiben */
    kPinLabel = document.createElement('div');
    Object.assign(kPinLabel.style, {
      position:      'fixed',
      background:    'rgba(0,4,14,0.97)',
      color:         '#00e5a0',
      border:        '1px solid rgba(0,212,255,0.65)',
      padding:       '5px 16px 7px',
      borderRadius:  '3px',
      fontSize:      '11px',
      fontFamily:    '"Share Tech Mono",monospace',
      letterSpacing: '0.12em',
      textTransform: 'uppercase',
      pointerEvents: 'none',
      opacity:       '0',
      transition:    'opacity 0.15s',
      whiteSpace:    'nowrap',
      zIndex:        '10000',
      boxShadow:     '0 0 20px rgba(0,212,255,0.35), 0 0 4px rgba(0,229,160,0.2)',
    });
    document.body.appendChild(kPinLabel);

    /* ── Fetch real files ─────────────────────────────────────────*/
    fetch('/api/knowledge')
      .then(r => r.json())
      .then(data => buildSphere(data))
      .catch(() => buildSphere([]));

    /* ── Drag rotation ──────────────────────────────────────────── */
    canvas.addEventListener('mousedown', e => {
      isDragging = true; autoRotate = false; _dragMoved = false;
      dragPrev = { x: e.clientX, y: e.clientY };
      kVel = { x: 0, y: 0 };
      canvas.style.cursor = 'grabbing';
    });
    window.addEventListener('mouseup', () => {
      if (!isDragging) return;
      isDragging = false;
      canvas.style.cursor = 'grab';
      setTimeout(() => { autoRotate = true; }, 8000);
    });
    canvas.style.cursor = 'grab';

    canvas.addEventListener('mousemove', e => {
      const rect = canvas.getBoundingClientRect();
      mouse2.x =  ((e.clientX - rect.left) / rect.width)  * 2 - 1;
      mouse2.y = -((e.clientY - rect.top)  / rect.height) * 2 + 1;
      if (isDragging) {
        _dragMoved = true;
        kVel.y = (e.clientX - dragPrev.x) * 0.011;
        kVel.x = (e.clientY - dragPrev.y) * 0.011;
        kGroup.rotation.y += kVel.y;
        kGroup.rotation.x += kVel.x;
        dragPrev = { x: e.clientX, y: e.clientY };
      }
    });
    canvas.addEventListener('mouseleave', () => {
      mouse2.set(-99, -99);
      kTooltip.style.opacity = '0';
      if (hoveredNode) { hoveredNode.mesh.scale.setScalar(1); hoveredNode = null; }
    });

    /* Klick → Node-Name pinnen / lösen */
    canvas.addEventListener('click', e => {
      if (_dragMoved) return;
      const rect = canvas.getBoundingClientRect();
      const cv = new THREE.Vector2(
        ((e.clientX - rect.left) / rect.width)  * 2 - 1,
        -((e.clientY - rect.top)  / rect.height) * 2 + 1,
      );
      RC.setFromCamera(cv, kCam);
      const hits = RC.intersectObjects(kNodes.map(n => n.hitbox), false);
      if (hits.length) {
        const clicked = kNodes.find(n => n.hitbox === hits[0].object);
        if (clicked) {
          if (pinnedNode === clicked) {
            pinnedNode = null;
            kPinLabel.style.opacity = '0';
          } else {
            pinnedNode = clicked;
            kPinLabel.textContent       = clicked.label;
            kPinLabel.style.color       = clicked.type === 'memory' ? '#fbbf24'
                                        : clicked.type === 'h2' || clicked.type === 'section' ? '#60a5fa'
                                        : '#00e5a0';
            kPinLabel.style.borderColor = clicked.type === 'memory'
              ? 'rgba(251,191,36,0.65)' : 'rgba(0,212,255,0.65)';
            kPinLabel.style.opacity = '1';
          }
          return;
        }
      }
      pinnedNode = null;
      kPinLabel.style.opacity = '0';
    });

    /* ── Animation ──────────────────────────────────────────────── */
    let t = 0;
    const tmpVec = new THREE.Vector3();
    (function animK() {
      requestAnimationFrame(animK);
      if (canvas.offsetParent === null) return; // Panel ausgeblendet (anderer Reiter) — Frame ueberspringen
      t += 0.006;

      if (autoRotate) {
        kGroup.rotation.y += 0.004;
        kGroup.rotation.x = Math.sin(t * 0.11) * 0.08;
      } else if (!isDragging) {
        kVel.x *= 0.88; kVel.y *= 0.88;
        kGroup.rotation.x += kVel.x; kGroup.rotation.y += kVel.y;
      }

      /* Core pulse */
      if (core) {
        const s = 1 + 0.12 * Math.sin(t * 3.5);
        core.scale.setScalar(s);
        coreHalo.scale.setScalar(s * 1.4);
      }

      /* Orbit ring tilts */
      orbitRing.rotation.x = t * 0.3;
      orbitRing.rotation.y = t * 0.2;

      /* Hover raycasting */
      if (kNodes.length && !isDragging) {
        RC.setFromCamera(mouse2, kCam);
        const hitboxes = kNodes.map(n => n.hitbox);
        const hits = RC.intersectObjects(hitboxes, false);
        const hNode = hits.length ? kNodes.find(n => n.hitbox === hits[0].object) : null;

        if (hNode) {
          if (hoveredNode !== hNode) {
            if (hoveredNode) hoveredNode.mesh.scale.setScalar(1);
            hoveredNode = hNode;
            hoveredNode.mesh.scale.setScalar(2.8);
          }
          hNode.hitbox.getWorldPosition(tmpVec);
          tmpVec.project(kCam);
          const rect = canvas.getBoundingClientRect();
          const sx = rect.left + (tmpVec.x + 1) / 2 * rect.width;
          const sy = rect.top  + (1 - tmpVec.y) / 2 * rect.height;
          kTooltip.style.left    = (sx + 14) + 'px';
          kTooltip.style.top     = (sy - 10) + 'px';
          kTooltip.style.opacity = '1';
          kTooltip.textContent   = hNode.label;
          kTooltip.style.color   = hNode.type === 'memory' ? '#fbbf24'
                                 : hNode.type === 'section' ? '#60a5fa' : '#00e5a0';
          kTooltip.style.borderColor = hNode.type === 'memory'
            ? 'rgba(251,191,36,0.4)' : 'rgba(0,212,255,0.4)';
        } else {
          if (hoveredNode) { hoveredNode.mesh.scale.setScalar(1); hoveredNode = null; }
          kTooltip.style.opacity = '0';
        }
      }

      /* Pin-Label position mitführen während Sphere dreht */
      if (pinnedNode && kPinLabel) {
        pinnedNode.hitbox.getWorldPosition(tmpVec);
        tmpVec.project(kCam);
        const rectP = canvas.getBoundingClientRect();
        const sx = rectP.left + (tmpVec.x + 1) / 2 * rectP.width;
        const sy = rectP.top  + (1 - tmpVec.y) / 2 * rectP.height;
        kPinLabel.style.left = (sx + 14) + 'px';
        kPinLabel.style.top  = (sy - 24) + 'px';
      }

      /* Pulse non-hovered nodes */
      kNodes.forEach((n, i) => {
        if (n !== hoveredNode) {
          n.mesh.scale.setScalar(1 + (n.type === 'section' ? 0.08 : 0.13) * Math.sin(t * 2.2 + i));
        }
      });

      /* Animate lights */
      if (ptA) { ptA.intensity = 5.5 + 2 * Math.sin(t * 2.4); ptA.position.x = 2.5 * Math.cos(t * 0.5); }
      if (ptB) { ptB.intensity = 3.5 + 1.5 * Math.sin(t * 1.8 + 1.2); }

      kRenderer.render(kScene, kCam);
    })();

    window.addEventListener('resize', () => {
      if (!kRenderer || !canvas.parentElement) return;
      const s = canvas.parentElement.clientWidth || 252;
      canvas.style.width = s + 'px'; canvas.style.height = s + 'px';
      kRenderer.setSize(s, s, false);
    });
  }

  /* ── Build sphere from file data ───────────────────────────────── */
  /* Node-Config je Typ:  radius, color (hex), emissive, haloMult, layer-R */
  const NODE_CFG = {
    file:   { r: 0.092, col: 0x00e5a0, em: 0x009955, halo: 3.8, R: 1.05, seg: 12, lineOp: 0.18 },
    brain:  { r: 0.082, col: 0xa78bfa, em: 0x5522aa, halo: 3.5, R: 1.02, seg: 10, lineOp: 0.16 },
    memory: { r: 0.082, col: 0xfbbf24, em: 0xaa7700, halo: 3.5, R: 1.02, seg: 10, lineOp: 0.16 },
    h2:     { r: 0.048, col: 0x60a5fa, em: 0x1a3a8a, halo: 3.2, R: 0.88, seg: 8,  lineOp: 0 },
    h3:     { r: 0.033, col: 0x8b5cf6, em: 0x3a1a7a, halo: 2.8, R: 0.80, seg: 7,  lineOp: 0 },
    item:   { r: 0.020, col: 0x0088cc, em: 0x003366, halo: 2.5, R: 0.72, seg: 6,  lineOp: 0 },
  };

  function buildSphere(allNodes) {
    if (!kGroup) return;

    /* Keep only first 3 wireframe shells, rebuild everything else */
    while (kGroup.children.length > 3)
      kGroup.remove(kGroup.children[kGroup.children.length - 1]);

    /* Central arc-reactor core */
    const core = new THREE.Mesh(
      new THREE.SphereGeometry(0.13, 16, 16),
      new THREE.MeshPhongMaterial({ color: 0x00e5ff, emissive: 0x00e5ff, emissiveIntensity: 1.3, transparent: true, opacity: 0.95 })
    );
    kGroup.add(core);
    const coreHalo = new THREE.Mesh(
      new THREE.SphereGeometry(0.30, 12, 12),
      new THREE.MeshBasicMaterial({ color: 0x00d4ff, transparent: true, opacity: 0.14, blending: THREE.AdditiveBlending, depthWrite: false })
    );
    kGroup.add(coreHalo);
    kGroup.add(new THREE.Mesh(
      new THREE.TorusGeometry(1.0, 0.005, 8, 80),
      new THREE.MeshBasicMaterial({ color: 0x00d4ff, transparent: true, opacity: 0.30 })
    ));

    kNodes = [];

    if (!allNodes || !allNodes.length) {
      allNodes = [
        { name: 'CLAUDE.md', type: 'file' },
        { name: 'Wer du bist', type: 'h2' },
        { name: 'Immer auf Deutsch', type: 'item' },
        { name: 'Werkzeuge', type: 'h2' },
        { name: 'User Bastian', type: 'memory' },
      ];
    }

    /* Separate by layer (render outermost first for better depth) */
    const order = ['file', 'brain', 'memory', 'h2', 'h3', 'item'];
    const byType = {};
    order.forEach(t => { byType[t] = []; });
    allNodes.forEach(n => {
      const t = n.type in byType ? n.type : 'item';
      byType[t].push(n);
    });

    const goldenAngle = Math.PI * (3 - Math.sqrt(5));

    order.forEach(type => {
      const group = byType[type];
      if (!group.length) return;
      const cfg = NODE_CFG[type];
      const N = group.length;

      group.forEach((node, i) => {
        /* Golden ratio on type-specific shell radius */
        const yN  = 1 - (i / Math.max(N - 1, 1)) * 2;
        const rad = Math.sqrt(Math.max(0, 1 - yN * yN));
        const phi = goldenAngle * i;
        const pos = new THREE.Vector3(
          rad * Math.cos(phi) * cfg.R,
          yN * cfg.R,
          rad * Math.sin(phi) * cfg.R
        );

        /* Visual node */
        const mesh = new THREE.Mesh(
          new THREE.SphereGeometry(cfg.r, cfg.seg, cfg.seg),
          new THREE.MeshPhongMaterial({ color: cfg.col, emissive: cfg.em, emissiveIntensity: 0.85, shininess: 100 })
        );
        mesh.position.copy(pos);
        kGroup.add(mesh);

        /* Glow halo */
        const halo = new THREE.Mesh(
          new THREE.SphereGeometry(cfg.r * cfg.halo, 6, 6),
          new THREE.MeshBasicMaterial({ color: cfg.col, transparent: true, opacity: 0.10, blending: THREE.AdditiveBlending, depthWrite: false })
        );
        halo.position.copy(pos);
        kGroup.add(halo);

        /* Invisible hitbox — 3× radius for easy hover */
        const hitbox = new THREE.Mesh(
          new THREE.SphereGeometry(Math.max(cfg.r * 3, 0.055), 5, 5),
          new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false })
        );
        hitbox.position.copy(pos);
        kGroup.add(hitbox);

        kNodes.push({ mesh, hitbox, label: node.name, type });

        /* Spoke line for large nodes only */
        if (cfg.lineOp > 0) {
          const lg = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0,0,0), pos]);
          kGroup.add(new THREE.LineSegments(lg,
            new THREE.LineBasicMaterial({ color: cfg.col, transparent: true, opacity: cfg.lineOp })));
        }
      });
    });

    /* Stats */
    const bigCount  = kNodes.filter(n => ['file','brain','memory'].includes(n.type)).length;
    const secCount  = kNodes.filter(n => ['h2','h3'].includes(n.type)).length;
    const itemCount = kNodes.filter(n => n.type === 'item').length;
    const ne = document.getElementById('brain-nodes');
    const ce = document.getElementById('brain-conn');
    const me = document.getElementById('brain-mem');
    if (ne) ne.textContent = bigCount;
    if (ce) ce.textContent = secCount;
    if (me) me.textContent = kNodes.length;
  }

  /* ══════════════════════════════════════════════════════════════════
     PUBLIC
  ══════════════════════════════════════════════════════════════════ */
  window.brainGrow = function () {
    if (kGroup) { kGroup.scale.setScalar(1.07); setTimeout(() => kGroup.scale.setScalar(1), 350); }
    const wrap = document.querySelector('.brain-wrap');
    if (wrap) { wrap.classList.add('pulse'); setTimeout(() => wrap.classList.remove('pulse'), 800); }
  };

  window.brainFlashAgent = function (color) {
    if (!kScene) return;
    const fl = new THREE.PointLight(color, 12, 8);
    fl.position.set(0, 0, 2.5);
    kScene.add(fl);
    setTimeout(() => kScene.remove(fl), 500);
  };

  /* ══════════════════════════════════════════════════════════════════
     AGENT CONSTELLATION
  ══════════════════════════════════════════════════════════════════ */
  const AGENT_META_B = {
    library:       { name: 'Library',  color: '#a78bfa' },
    research:      { name: 'Research', color: '#38bdf8' },
    senior_dev:    { name: 'SeniorPy', color: '#34d399' },
    ux:            { name: 'UXCraft',  color: '#fbbf24' },
    code_reviewer: { name: 'Review',   color: '#60a5fa' },
    debugger:      { name: 'Debug',    color: '#f87171' },
    bug_fixer:     { name: 'BugFix',   color: '#fb923c' },
    bug_expert:    { name: 'BugWiz',   color: '#c084fc' },
    performance:   { name: 'Speed',    color: '#22d3ee' },
    security:      { name: 'Secure',   color: '#f43f5e' },
  };

  /* ── Session Stats Panel ─────────────────────────────────────────── */
  const _ssStart = Date.now();
  const CTX_MAX_B   = 200000;
  const CTX_COMPACT_B = 160000;

  function _fmtNum(n) {
    if (!n || n === 0) return '—';
    if (n >= 1000000) return (n / 1000000).toFixed(2) + 'M';
    if (n >= 1000)    return (n / 1000).toFixed(1) + 'K';
    return String(n);
  }
  function _fmtDuration(ms) {
    const s = Math.floor(ms / 1000);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    return String(h).padStart(2,'0') + ':' + String(m).padStart(2,'0') + ':' + String(sec).padStart(2,'0');
  }

  function _ssSet(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  function updateSessionStats(usage) {
    if (!usage) return;
    const inTok   = usage.input    || 0;
    const outTok  = usage.output   || 0;
    const lastCtx = usage.last_ctx || 0;
    const reqs    = usage.requests || 0;
    const ctxPct  = lastCtx > 0 ? Math.min(100, lastCtx / CTX_MAX_B * 100)    : 0;
    const cmpPct  = lastCtx > 0 ? Math.min(100, lastCtx / CTX_COMPACT_B * 100) : 0;

    _ssSet('ss-req',      reqs || '0');
    _ssSet('ss-in',       _fmtNum(inTok));
    _ssSet('ss-out',      _fmtNum(outTok));
    _ssSet('ss-total',    _fmtNum(inTok + outTok));
    _ssSet('ss-last-ctx', lastCtx > 0 ? lastCtx.toLocaleString('de-DE') : '—');
    _ssSet('ss-ctx-pct',  ctxPct.toFixed(0) + '%');
    _ssSet('ss-cmp-pct',  cmpPct.toFixed(0) + '%');

    const ctxFill = document.getElementById('ss-ctx-fill');
    const cmpFill = document.getElementById('ss-cmp-fill');
    if (ctxFill) ctxFill.style.width = ctxPct.toFixed(1) + '%';
    if (cmpFill) cmpFill.style.width = cmpPct.toFixed(1) + '%';

    // Farbe wechseln bei hohem Verbrauch
    const pctEl = document.getElementById('ss-ctx-pct');
    if (pctEl) pctEl.style.color = ctxPct > 80 ? '#ff2244' : ctxPct > 60 ? '#fbbf24' : '#00d4ff';
    const cmpEl = document.getElementById('ss-cmp-pct');
    if (cmpEl) cmpEl.style.color = cmpPct > 80 ? '#ff2244' : cmpPct > 60 ? '#fbbf24' : '#00e5a0';
  }
  window.updateSessionStats = updateSessionStats;

  // Session-Uhr läuft jede Sekunde
  function _tickSessionClock() {
    _ssSet('ss-duration', _fmtDuration(Date.now() - _ssStart));
  }

  // agentOrb-Stubs (app.js ruft diese noch auf)
  window.activateAgentOrb   = function (key) { window.brainFlashAgent && window.brainFlashAgent(0x00d4ff); };
  window.deactivateAgentOrb = function (key) {};

  /* ══════════════════════════════════════════════════════════════════
     CLOCK + INIT
  ══════════════════════════════════════════════════════════════════ */
  function startClock() {
    const tick = () => { const el = document.getElementById('m-time'); if (el) el.textContent = new Date().toLocaleTimeString('de-DE'); };
    tick(); setInterval(tick, 1000);
  }

  window.addEventListener('DOMContentLoaded', () => {
    startClock();
    setInterval(_tickSessionClock, 1000);
    _tickSessionClock();
    /* Wait for layout to complete before sizing canvas */
    function tryInit(attempt) {
      const c = document.getElementById('brain-canvas');
      const w = c && c.parentElement ? c.parentElement.clientWidth : 0;
      if (w > 0 || attempt >= 8) {
        initKnowledge(c);
      } else {
        setTimeout(() => tryInit(attempt + 1), 80);
      }
    }
    requestAnimationFrame(() => requestAnimationFrame(() => tryInit(0)));
  });

})();
