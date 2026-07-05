// ════════════════════════════════════════════════════════════════════════════
//  3D-ERD-GLOBUS — realistische Erde (Satelliten-Look) mit Lead-Standorten.
//  Three.js r128. Echte Erd-Texturen (CDN), Sonnenlicht, Wolken, Atmosphäre,
//  Fresnel-Glow, Sterne. Cinematischer Intro-Zoom auf Deutschland. Pulsierende
//  Marker je Stadt (skaliert nach Lead-Anzahl), aufsteigende Light-Beams,
//  Stadt-Labels (Top-Städte), Hologramm-Scanline-Overlay. Hover-Tooltip.
//  Öffentliche API bleibt unverändert: initGlobe(), /api/graph/locations,
//  _coordsFor/_llv-Lookups, window._gb (Debug).
// ════════════════════════════════════════════════════════════════════════════
let _globeReady = false;
let _gb = null;

const _REDUCED = (typeof window !== 'undefined' && window.matchMedia)
  ? window.matchMedia('(prefers-reduced-motion: reduce)').matches : false;
// Grobe Leistungseinschätzung → weniger Partikel/Marker auf schwachen Geräten.
const _LOWPWR = (typeof navigator !== 'undefined' &&
  ((navigator.hardwareConcurrency || 8) <= 4 ||
   (navigator.deviceMemory || 8) <= 4));

// Koordinaten gängiger deutscher Städte (lat, lng).
const _CITY = {
  "berlin":[52.52,13.40],"hamburg":[53.55,9.99],"münchen":[48.14,11.58],"munchen":[48.14,11.58],
  "köln":[50.94,6.96],"koln":[50.94,6.96],"frankfurt am main":[50.11,8.68],"frankfurt":[50.11,8.68],
  "stuttgart":[48.78,9.18],"düsseldorf":[51.23,6.78],"dusseldorf":[51.23,6.78],"dortmund":[51.51,7.47],
  "essen":[51.46,7.01],"leipzig":[51.34,12.37],"bremen":[53.08,8.80],"dresden":[51.05,13.74],
  "hannover":[52.37,9.73],"nürnberg":[49.45,11.08],"nurnberg":[49.45,11.08],"duisburg":[51.43,6.76],
  "bochum":[51.48,7.22],"wuppertal":[51.26,7.18],"bielefeld":[52.02,8.53],"bonn":[50.74,7.10],
  "münster":[51.96,7.63],"munster":[51.96,7.63],"karlsruhe":[49.01,8.40],"mannheim":[49.49,8.47],
  "augsburg":[48.37,10.90],"wiesbaden":[50.08,8.24],"mönchengladbach":[51.19,6.44],
  "gelsenkirchen":[51.52,7.10],"braunschweig":[52.27,10.52],"kiel":[54.32,10.14],"aachen":[50.78,6.08],
  "halle":[51.48,11.97],"magdeburg":[52.13,11.63],"freiburg":[47.99,7.85],"krefeld":[51.33,6.56],
  "lübeck":[53.87,10.69],"lubeck":[53.87,10.69],"oberhausen":[51.47,6.85],"erfurt":[50.98,11.03],
  "mainz":[49.99,8.24],"rostock":[54.09,12.14],"kassel":[51.31,9.50],"hagen":[51.36,7.47],
  "saarbrücken":[49.24,6.99],"saarbrucken":[49.24,6.99],"potsdam":[52.40,13.06],"hamm":[51.68,7.82],
  "ludwigshafen":[49.48,8.45],"oldenburg":[53.14,8.21],"osnabrück":[52.28,8.05],"heidelberg":[49.40,8.67],
  "tübingen":[48.52,9.06],"tubingen":[48.52,9.06],"ulm":[48.40,9.99],"regensburg":[49.01,12.10],
  "ingolstadt":[48.77,11.43],"würzburg":[49.79,9.95],"wurzburg":[49.79,9.95],"wolfsburg":[52.42,10.79],
  "göttingen":[51.54,9.93],"pforzheim":[48.89,8.70],"offenbach":[50.10,8.77],"reutlingen":[48.49,9.21],
  "koblenz":[50.36,7.59],"bergisch gladbach":[50.99,7.13],"recklinghausen":[51.61,7.20],"jena":[50.93,11.59],
  "trier":[49.75,6.64],"aichach":[48.46,11.13],"herrenberg":[48.60,8.87],"flensburg":[54.78,9.44],
  "konstanz":[47.66,9.18],"villingen":[48.06,8.46],"esslingen":[48.74,9.31],"ravensburg":[47.78,9.61],
};
const _BL = {
  "baden-württemberg":[48.6,9.0],"baden-wurttemberg":[48.6,9.0],"bayern":[48.8,11.4],
  "berlin":[52.52,13.40],"brandenburg":[52.4,13.0],"bremen":[53.08,8.80],"hamburg":[53.55,9.99],
  "hessen":[50.6,9.0],"mecklenburg-vorpommern":[53.6,12.7],"niedersachsen":[52.8,9.3],
  "nordrhein-westfalen":[51.4,7.5],"rheinland-pfalz":[49.9,7.5],"saarland":[49.4,7.0],
  "sachsen":[51.0,13.4],"sachsen-anhalt":[51.9,11.7],"schleswig-holstein":[54.2,9.8],
  "thüringen":[50.9,11.0],"thuringen":[50.9,11.0],
};
const _DE = [51.1, 10.3];

function _hash(s){ let h=0; for(let i=0;i<s.length;i++){ h=(h*31+s.charCodeAt(i))|0; } return h; }
function _coordsFor(stadt, bundesland){
  const s = (stadt||"").toLowerCase().trim();
  if(_CITY[s]) return _CITY[s];
  const first = s.split(/[ ,/(]/)[0];
  if(_CITY[first]) return _CITY[first];
  const base = _BL[(bundesland||"").toLowerCase().trim()] || _DE;
  const h = _hash(s);
  return [base[0] + ((h%1000)/1000-0.5)*1.1, base[1] + (((h>>10)%1000)/1000-0.5)*1.6];
}
function _llv(lat, lng, r){
  const phi=(90-lat)*Math.PI/180, theta=(lng+180)*Math.PI/180;
  return new THREE.Vector3(-r*Math.sin(phi)*Math.cos(theta), r*Math.cos(phi), r*Math.sin(phi)*Math.sin(theta));
}
function _hexRgb(h){ h=h.replace('#',''); return [parseInt(h.slice(0,2),16),parseInt(h.slice(2,4),16),parseInt(h.slice(4,6),16)]; }

const _texCache = {};
// Weicher, leicht ringförmiger Glow — kräftiger Kern, sanfter Halo (kein weißer Blob).
function _glowTex(color){
  if(_texCache[color]) return _texCache[color];
  const [r,g_,b]=_hexRgb(color);
  const c=document.createElement('canvas'); c.width=c.height=128; const g=c.getContext('2d');
  const grd=g.createRadialGradient(64,64,0,64,64,64);
  grd.addColorStop(0.00,`rgba(255,255,255,0.95)`);
  grd.addColorStop(0.12,`rgba(${Math.min(255,r+60)},${Math.min(255,g_+60)},${Math.min(255,b+60)},0.92)`);
  grd.addColorStop(0.34,`rgba(${r},${g_},${b},0.62)`);
  grd.addColorStop(0.70,`rgba(${r},${g_},${b},0.12)`);
  grd.addColorStop(1.00,`rgba(${r},${g_},${b},0)`);
  g.fillStyle=grd; g.beginPath(); g.arc(64,64,64,0,7); g.fill();
  const t=new THREE.CanvasTexture(c); t.minFilter=THREE.LinearFilter; _texCache[color]=t; return t;
}
// Stern-Sprite (kleiner heller Punkt mit Halo) für hübschere Sterne.
let _starTex = null;
function _starSprite(){
  if(_starTex) return _starTex;
  const c=document.createElement('canvas'); c.width=c.height=64; const g=c.getContext('2d');
  const grd=g.createRadialGradient(32,32,0,32,32,32);
  grd.addColorStop(0,'rgba(255,255,255,1)'); grd.addColorStop(0.3,'rgba(200,225,255,0.7)');
  grd.addColorStop(1,'rgba(120,160,220,0)');
  g.fillStyle=grd; g.beginPath(); g.arc(32,32,32,0,7); g.fill();
  _starTex=new THREE.CanvasTexture(c); return _starTex;
}
// Stadt-Label als Sprite-Textur.
function _labelTex(text){
  const pad=10, fs=34;
  const c=document.createElement('canvas'); const g=c.getContext('2d');
  g.font=`600 ${fs}px Inter, "Segoe UI", system-ui, sans-serif`;
  const w=Math.ceil(g.measureText(text).width)+pad*2, h=fs+pad*2;
  c.width=w; c.height=h; const x=c.getContext('2d');
  x.font=`600 ${fs}px Inter, "Segoe UI", system-ui, sans-serif`;
  x.textBaseline='middle';
  x.shadowColor='rgba(0,180,255,0.9)'; x.shadowBlur=10;
  x.fillStyle='rgba(8,18,30,0.55)';
  _roundRect(x,1,1,w-2,h-2,8); x.fill();
  x.shadowBlur=0;
  x.fillStyle='rgba(190,235,255,0.96)';
  x.fillText(text, pad, h/2+1);
  const t=new THREE.CanvasTexture(c); t.minFilter=THREE.LinearFilter;
  return {tex:t, w, h};
}
function _roundRect(ctx,x,y,w,h,r){
  ctx.beginPath(); ctx.moveTo(x+r,y);
  ctx.arcTo(x+w,y,x+w,y+h,r); ctx.arcTo(x+w,y+h,x,y+h,r);
  ctx.arcTo(x,y+h,x,y,r); ctx.arcTo(x,y,x+w,y,r); ctx.closePath();
}

const _TYP_COL = { hot:'#ff5a4e', warm:'#ffd24d', cold:'#4dc3ff' };
// 2K-Fallback (three.js, versionsgepinnt @r128) + hochauflösende Texturen von three-globe
// (npm-Paket, versionsgepinnt @2.31.0 — jsDelivr garantiert Uptime fuer /npm/-Pakete, anders
// als /gh/-Links auf einzelne, unversionierte GitHub-Repos wie das fruehere turban/webgl-earth,
// dessen @master-Branch zwischenzeitlich verschwunden ist und nur noch 404 lieferte).
const _TEX     = 'https://cdn.jsdelivr.net/gh/mrdoob/three.js@r128/examples/textures/planets/';
const _TEX_HI  = 'https://cdn.jsdelivr.net/npm/three-globe@2.31.0/example/img/';
// Texturen je Slot als Fallback-Kette: erst hochauflösend (scharf beim Zoom), sonst 2K. Schwache
// Hardware (_LOWPWR) lädt nur die 2K-Variante (Bandbreite/Speicher schonen).
const _EARTH_TEX = {
  day:      _LOWPWR ? [_TEX+'earth_atmos_2048.jpg']
                    : [_TEX_HI+'earth-blue-marble.jpg', _TEX+'earth_atmos_2048.jpg'],
  specular: _LOWPWR ? [_TEX+'earth_specular_2048.jpg']
                    : [_TEX_HI+'earth-water.png', _TEX+'earth_specular_2048.jpg'],
  bump:     _LOWPWR ? [_TEX+'earth_normal_2048.jpg']
                    : [_TEX_HI+'earth-topology.png', _TEX+'earth_normal_2048.jpg'],
  night:    _LOWPWR ? [_TEX+'earth_lights_2048.png']
                    : [_TEX_HI+'earth-night.jpg', _TEX+'earth_lights_2048.png'],
  clouds:   [_TEX+'earth_clouds_1024.png'],
};
// Lädt die erste ladbare URL aus der Kette (8K→2K). onLoad bekommt die Textur; scheitert eine
// URL (404/CORS), wird automatisch die nächste versucht — der Globus rendert nie ohne Erde.
function _loadTexFallback(loader, urls, onLoad){
  let i=0;
  const tryNext=()=>{
    if(i>=urls.length) return;
    const u=urls[i++];
    loader.load(u, t=>{ try{ onLoad(t); }catch(e){} }, undefined, ()=>tryNext());
  };
  tryNext();
}
// GLTFLoader liegt in r128 nicht im Core → bei Bedarf dynamisch nachladen.
const _GLTF_LOADER_URL = 'https://cdn.jsdelivr.net/gh/mrdoob/three.js@r128/examples/js/loaders/GLTFLoader.js';

// ── Fresnel-Atmosphäre (Shader) ────────────────────────────────────────────
function _atmosphereMaterial(color, power, intensity){
  return new THREE.ShaderMaterial({
    uniforms:{
      uColor:{value:new THREE.Color(color)},
      uPower:{value:power},
      uIntensity:{value:intensity},
    },
    vertexShader:`
      varying vec3 vN; varying vec3 vP;
      void main(){
        vN = normalize(normalMatrix * normal);
        vec4 mv = modelViewMatrix * vec4(position,1.0);
        vP = -normalize(mv.xyz);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader:`
      uniform vec3 uColor; uniform float uPower; uniform float uIntensity;
      varying vec3 vN; varying vec3 vP;
      void main(){
        float f = pow(1.0 - max(dot(vN, vP), 0.0), uPower);
        gl_FragColor = vec4(uColor, f * uIntensity);
      }`,
    transparent:true, blending:THREE.AdditiveBlending,
    side:THREE.BackSide, depthWrite:false,
  });
}

// ── Hologramm-Scanline-Overlay (DOM, leichtgewichtig) ──────────────────────
function _ensureScanline(wrap){
  if(_REDUCED) return; // Bewegte Scanlines bei reduzierter Bewegung weglassen.
  if(wrap.querySelector('.globe-scan')) return;
  if(getComputedStyle(wrap).position === 'static') wrap.style.position='relative';
  const el=document.createElement('div');
  el.className='globe-scan';
  el.style.cssText='position:absolute;inset:0;pointer-events:none;z-index:3;'+
    'mix-blend-mode:screen;opacity:0.5;'+
    'background:repeating-linear-gradient(0deg,rgba(90,200,255,0.06) 0px,'+
    'rgba(90,200,255,0.06) 1px,transparent 2px,transparent 4px);'+
    'animation:globeScan 7s linear infinite;';
  wrap.appendChild(el);
  const vig=document.createElement('div');
  vig.className='globe-vignette';
  vig.style.cssText='position:absolute;inset:0;pointer-events:none;z-index:2;'+
    'background:radial-gradient(ellipse at 50% 48%,transparent 52%,rgba(2,8,18,0.55) 100%);';
  wrap.appendChild(vig);
  if(!document.getElementById('globe-scan-style')){
    const st=document.createElement('style'); st.id='globe-scan-style';
    st.textContent='@keyframes globeScan{0%{background-position:0 0}100%{background-position:0 80px}}';
    document.head.appendChild(st);
  }
}

// ── Higgsfield-Weltraum-Hintergrund (DOM-Bild hinter dem transparenten Canvas) ──
// Der WebGL-Canvas rendert mit alpha:true → ein ultrarealistisches, von Higgsfield erzeugtes
// Weltraum/Nebel-Bild als CSS-Hintergrund des Wraps scheint durch. Fehlt das Bild, bleibt der
// dunkle Verlauf + die prozeduralen Sterne (kein Bruch). URL via window.JARVIS_SPACE_BG
// überschreibbar; Default static/img/space_bg.jpg.
function _ensureSpaceBg(wrap){
  let url = '/static/img/space_bg.jpg';
  try{ if(window.JARVIS_SPACE_BG) url = String(window.JARVIS_SPACE_BG); }catch(e){}
  const img = new Image();
  img.onload = ()=>{
    wrap.style.backgroundImage =
      `radial-gradient(ellipse at 50% 42%, rgba(4,10,22,0.18) 0%, rgba(2,6,16,0.82) 100%), url('${url}')`;
    wrap.style.backgroundSize = 'cover';
    wrap.style.backgroundPosition = 'center';
    wrap.style.backgroundRepeat = 'no-repeat';
  };
  img.onerror = ()=>{ /* kein Higgsfield-Bild → Sterne/Verlauf bleiben */ };
  img.src = url;
}

// ── Adressgenaue Lead-Pins (geocodet) ─────────────────────────────────────────
// Holt /api/graph/leadpoints (exakte lat/lng pro Betrieb) und setzt scharfe, perspektivisch
// skalierende Glow-Pins direkt auf die Erde — beim Reinzoomen nach Deutschland sieht man genau,
// wo jeder Lead sitzt. Solange das Geocoding im Hintergrund läuft (pending>0), wird nachgeladen.
function _disposeLeadPoints(){
  const g=_gb; if(!g||!g.leadMarkers) return;
  g.leadMarkers.forEach(s=>{
    g.group.remove(s);
    if(s.material){ if(s.material.map && s.material.map.dispose) s.material.map.dispose(); s.material.dispose(); }
  });
  g.leadMarkers=[];
}
async function _loadLeadPoints(){
  if(!_gb) return;
  let data;
  try{ data = await(await fetch('/api/graph/leadpoints')).json(); }catch(e){ return; }
  if(!_gb) return;
  const pts = (data && data.points) || [];
  _disposeLeadPoints();
  const R=_gb.R, cap=_LOWPWR?300:900;
  pts.slice(0,cap).forEach(p=>{
    if(typeof p.lat!=='number' || typeof p.lng!=='number') return;
    const typ=(p.typ==='hot'||p.typ==='warm'||p.typ==='cold')?p.typ:'cold';
    const col=_TYP_COL[typ];
    const dir=_llv(p.lat,p.lng,1).normalize();
    const mat=new THREE.SpriteMaterial({map:_glowTex(col), transparent:true,
      blending:THREE.AdditiveBlending, depthWrite:false, depthTest:false, opacity:0.9});
    const spr=new THREE.Sprite(mat);
    spr.position.copy(dir.clone().multiplyScalar(R*1.012));
    const base=0.015;
    spr.scale.set(base,base,1);
    spr.userData={info:p, base, lead:true};
    _gb.group.add(spr);
    _gb.leadMarkers.push(spr);
  });
  const cnt=document.getElementById('globe-count');
  if(cnt){
    const baseTxt = cnt.dataset.base || cnt.textContent || '';
    cnt.dataset.base = baseTxt;
    cnt.textContent = baseTxt + (pts.length ? ` · ${pts.length} adressgenau` : '');
  }
  if(data && data.pending>0){
    clearTimeout(_gb._leadPoll);
    _gb._leadPoll=setTimeout(_loadLeadPoints, 4500);   // Geocoding läuft → nachladen
  }
}

function initGlobe(){
  if(_globeReady){ _globeResize(); return; }
  const cv = document.getElementById('globe-canvas');
  if(!cv || typeof THREE === 'undefined') return;

  const wrap = document.getElementById('globe-wrap');
  if(!wrap) return;
  const W = wrap.clientWidth || 900, H = wrap.clientHeight || 460;

  // WebGL-Verfügbarkeit defensiv prüfen → sauberer Abbruch ohne Crash.
  let renderer;
  try{
    renderer = new THREE.WebGLRenderer({canvas:cv, antialias:!_LOWPWR, alpha:true, powerPreference:'high-performance'});
  }catch(e){
    const cnt=document.getElementById('globe-count');
    if(cnt) cnt.textContent='WebGL nicht verfügbar';
    return;
  }
  if(!renderer || !renderer.getContext || !renderer.getContext()){
    const cnt=document.getElementById('globe-count');
    if(cnt) cnt.textContent='WebGL nicht verfügbar';
    return;
  }

  _globeReady = true;
  _ensureScanline(wrap);
  _ensureSpaceBg(wrap);     // ultrarealistischer Higgsfield-Weltraum hinter dem (transparenten) Canvas

  const scene = new THREE.Scene();
  const cam = new THREE.PerspectiveCamera(40, W/H, 0.1, 400);
  cam.position.set(0, 0, 6.6);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1, _LOWPWR?1.25:2));
  renderer.setSize(W, H, false);
  if(THREE.sRGBEncoding) renderer.outputEncoding = THREE.sRGBEncoding;

  // ── Sternenhimmel (Sprite-Sterne, schimmernd) ──
  const starCount = _LOWPWR ? 700 : 1900;
  const starGeo = new THREE.BufferGeometry();
  const sp = []; for(let i=0;i<starCount;i++){ const r=60+Math.random()*120,
    th=Math.random()*Math.PI*2, ph=Math.acos(2*Math.random()-1);
    sp.push(r*Math.sin(ph)*Math.cos(th), r*Math.cos(ph), r*Math.sin(ph)*Math.sin(th)); }
  starGeo.setAttribute('position', new THREE.Float32BufferAttribute(sp,3));
  const stars = new THREE.Points(starGeo, new THREE.PointsMaterial({
    map:_starSprite(), color:0x9fc4ff, size:0.9, sizeAttenuation:true,
    transparent:true, opacity:0.85, depthWrite:false, blending:THREE.AdditiveBlending}));
  scene.add(stars);

  // ── Licht: Sonne von vorne-rechts-oben (Europa beleuchtet) + Fülllicht + Rim ──
  const sun = new THREE.DirectionalLight(0xfff4e0, 1.55); sun.position.set(2.8, 1.6, 3.8); scene.add(sun);
  scene.add(new THREE.AmbientLight(0x2a3f5c, 0.55));
  const rim = new THREE.DirectionalLight(0x3a7bd5, 0.6); rim.position.set(-3, -1, -2.5); scene.add(rim);

  const pivot = new THREE.Group();
  const group = new THREE.Group();
  pivot.add(group); scene.add(pivot);

  const R = 1.35;
  const segs = _LOWPWR ? 96 : 160;
  const loader = new THREE.TextureLoader(); loader.setCrossOrigin('anonymous');
  // Anisotrope Filterung: hält Kontinente/Küsten am Globusrand gestochen scharf,
  // sodass die Standort-Marker klar auf ihren Ländern sitzen (kein extra Asset).
  const _ANISO = (renderer.capabilities && renderer.capabilities.getMaxAnisotropy)
    ? renderer.capabilities.getMaxAnisotropy() : 8;
  const _sharp = t => { t.anisotropy=_ANISO; if(THREE.LinearMipmapLinearFilter)t.minFilter=THREE.LinearMipmapLinearFilter; t.generateMipmaps=true; return t; };

  // ── Erd-Körper mit Relief (Bump) + Glanz ──
  const earthMat = new THREE.MeshPhongMaterial({color:0x0f2a44, specular:0x2a4a6e, shininess:18});
  const earth = new THREE.Mesh(new THREE.SphereGeometry(R, segs, segs), earthMat); group.add(earth);
  _loadTexFallback(loader, _EARTH_TEX.day, t=>{ _sharp(t); if(t.encoding!==undefined&&THREE.sRGBEncoding)t.encoding=THREE.sRGBEncoding; earthMat.map=t; earthMat.color.set(0xffffff); earthMat.needsUpdate=true; });
  _loadTexFallback(loader, _EARTH_TEX.specular, t=>{ _sharp(t); earthMat.specularMap=t; earthMat.specular.set(0x6688aa); earthMat.shininess=26; earthMat.needsUpdate=true; });
  _loadTexFallback(loader, _EARTH_TEX.bump, t=>{ _sharp(t); earthMat.bumpMap=t; earthMat.bumpScale=0.06; earthMat.needsUpdate=true; });

  // ── Nachtlichter (Schattenseite leuchtet) — additive Overlay-Kugel ──
  const nightMat = new THREE.MeshBasicMaterial({color:0xfff2c0, transparent:true, opacity:0.0,
    blending:THREE.AdditiveBlending, depthWrite:false});
  const night = new THREE.Mesh(new THREE.SphereGeometry(R*1.002, segs, segs), nightMat); group.add(night);
  _loadTexFallback(loader, _EARTH_TEX.night, t=>{ _sharp(t); nightMat.map=t; nightMat.opacity=0.85; nightMat.needsUpdate=true; });

  // ── Wolken ──
  const cloudMat = new THREE.MeshPhongMaterial({transparent:true, opacity:0.0, depthWrite:false});
  const clouds = new THREE.Mesh(new THREE.SphereGeometry(R*1.015, _LOWPWR?48:96, _LOWPWR?48:96), cloudMat); group.add(clouds);
  _loadTexFallback(loader, _EARTH_TEX.clouds, t=>{ _sharp(t); cloudMat.map=t; cloudMat.alphaMap=t; cloudMat.opacity=0.45; cloudMat.needsUpdate=true; });

  // ── Atmosphäre: weicher innerer Fresnel-Rand + äußerer Glow ──
  const atmIn = new THREE.Mesh(new THREE.SphereGeometry(R*1.06, 96, 96),
    _atmosphereMaterial(0x4ab0ff, 3.2, 1.05));
  group.add(atmIn);
  const atmOut = new THREE.Mesh(new THREE.SphereGeometry(R*1.30, 64, 64),
    _atmosphereMaterial(0x1e7bff, 5.0, 0.55));
  group.add(atmOut);

  // ── Optional: echte Erd-GLB nachladen, sonst Textur-Sphere behalten (Fallback) ──
  _tryLoadEarthGLB(group, R);

  // Deutschland nach vorne (Quaternion-Ziel).
  group.quaternion.setFromUnitVectors(_llv(_DE[0], _DE[1], 1).normalize(), new THREE.Vector3(0,0,1));

  _gb = {scene, cam, renderer, pivot, group, earth, clouds, night, stars, R,
         markers:[], beams:[], labels:[], rings:[], leadMarkers:[], arcs:[], arcPulses:[], wrap, cv,
         userY:0, userX:0.14, dragging:false, lastX:0, lastY:0,
         introT:0, t:0, introY:0, targetZ:3.4, zoom:6.6, raf:0, _leadPoll:0,
         ray:new THREE.Raycaster(), mouse:new THREE.Vector2(-9,-9)};
  try{ window._gb = _gb; }catch(e){}

  _loadGlobeLocations();
  _loadLeadPoints();       // adressgenaue Lead-Pins (geocodet) — exakt beim Reinzoomen
  _wireGlobe(cv);
  _globeLoop();
}

// Lädt eine ECHTE Erd-GLB, wenn eine URL hinterlegt ist (window.JARVIS_EARTH_GLB
// oder <meta name="earth-glb" content="...">), und überlagert sie der Textur-Erde.
// Ohne URL bleibt die (jetzt anisotrop geschärfte) Textur-Erde das Primär-Asset —
// es gibt keine garantiert frei lizenzierte, fotoreale Earth-GLB auf stabiler CDN.
function _earthGlbUrl(){
  try{
    if(window.JARVIS_EARTH_GLB) return String(window.JARVIS_EARTH_GLB);
    const m=document.querySelector('meta[name="earth-glb"]');
    if(m && m.content) return m.content;
  }catch(e){}
  return '';
}
function _tryLoadEarthGLB(group, R){
  if(_LOWPWR) return;                       // schwache Hardware: Textur-Erde reicht
  const url = _earthGlbUrl();
  if(!url) return;                          // keine GLB hinterlegt → Textur bleibt primär
  const start = (GLTFLoaderCtor)=>{
    try{
      const gl = new GLTFLoaderCtor();
      gl.setCrossOrigin && gl.setCrossOrigin('anonymous');
      gl.load(url, (gltf)=>{
        try{
          const obj = gltf.scene || gltf.scenes && gltf.scenes[0];
          if(!obj) return;
          // GLB auf den Globusradius normieren.
          const box = new THREE.Box3().setFromObject(obj);
          const size = new THREE.Vector3(); box.getSize(size);
          const max = Math.max(size.x, size.y, size.z) || 1;
          const s = (R*2)/max; obj.scale.setScalar(s);
          const c = new THREE.Vector3(); box.getCenter(c);
          obj.position.sub(c.multiplyScalar(s));
          group.add(obj);
          if(_gb) _gb.earthGlb = obj;
          // Textur-Erde leicht zurücknehmen (GLB ist jetzt primär sichtbar).
          if(_gb && _gb.earth) _gb.earth.visible = false;
        }catch(e){ /* Überlagerung fehlgeschlagen → Textur-Erde bleibt. */ }
      }, undefined, ()=>{ /* Ladefehler → Textur-Erde bleibt. */ });
    }catch(e){ /* Fallback: Textur-Sphere, bereits aktiv. */ }
  };
  if(typeof THREE.GLTFLoader === 'function'){ start(THREE.GLTFLoader); return; }
  try{
    const sc=document.createElement('script');
    sc.src=_GLTF_LOADER_URL; sc.async=true;
    sc.onload=()=>{ if(typeof THREE.GLTFLoader === 'function') start(THREE.GLTFLoader); };
    sc.onerror=()=>{ /* Loader nicht verfügbar → Textur-Sphere bleibt. */ };
    document.head.appendChild(sc);
  }catch(e){ /* Textur-Sphere bleibt aktiv. */ }
}

async function _loadGlobeLocations(){
  let locs = [];
  try{ const d = await(await fetch('/api/graph/locations')).json(); locs = d.locations||[]; }catch{ locs=[]; }
  if(!_gb) return;
  // Alte Objekte sauber entfernen + Speicher freigeben (kein Leak bei Re-Init).
  _disposeMarkerLayer();

  const total = locs.length, leads = locs.reduce((a,b)=>a+(b.n||0),0);
  const cap = _LOWPWR ? 90 : 170;
  const top = locs.slice(0, cap);
  let maxN=1; top.forEach(l=> maxN=Math.max(maxN,l.n||1));
  const up = new THREE.Vector3(0,1,0);

  // Top-Städte für Labels bestimmen (nach n).
  const labelCap = _LOWPWR ? 6 : 12;
  const byN = [...top].map((l,idx)=>({l,idx})).sort((a,b)=>(b.l.n||0)-(a.l.n||0));
  const labelIdx = new Set(byN.slice(0, labelCap).map(o=>o.idx));

  const beamCap = _LOWPWR ? 24 : 50;

  top.forEach((l,i)=>{
    const [lat,lng] = _coordsFor(l.stadt, l.bundesland);
    const dom = (l.hot>=l.warm && l.hot>=l.cold) ? 'hot' : (l.warm>=l.cold ? 'warm' : 'cold');
    const col = _TYP_COL[dom];
    const dir = _llv(lat, lng, 1).normalize();
    const nFrac = Math.log2(1+(l.n||1))/Math.log2(1+maxN);

    // Marker-Glow-Sprite.
    const mat = new THREE.SpriteMaterial({map:_glowTex(col), transparent:true,
      blending:THREE.AdditiveBlending, depthWrite:false, depthTest:false, opacity:0.95});
    const spr = new THREE.Sprite(mat);
    spr.position.copy(dir.clone().multiplyScalar(_gb.R*1.015));
    const base = 0.022 + nFrac * 0.05;
    spr.userData = {base, phase:(i*0.37)%6.283, info:l, dom};
    spr.scale.set(base, base, 1);
    _gb.group.add(spr); _gb.markers.push({sprite:spr});

    // Pulsierender Bodenring (expandiert + verblasst).
    const ringMat = new THREE.MeshBasicMaterial({color:col, transparent:true, opacity:0.0,
      blending:THREE.AdditiveBlending, depthWrite:false, side:THREE.DoubleSide});
    const ring = new THREE.Mesh(new THREE.RingGeometry(base*0.9, base*1.1, 24), ringMat);
    ring.position.copy(dir.clone().multiplyScalar(_gb.R*1.004));
    ring.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1), dir);
    ring.userData = {base, phase:(i*0.61)%6.283};
    _gb.group.add(ring); _gb.rings.push(ring);

    // Aufsteigende Lichtsäule für die stärksten Lead-Städte.
    if(i < beamCap){
      const h = 0.05 + nFrac*0.26;
      const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.016, h, 6, 1, true),
        new THREE.MeshBasicMaterial({color:col, transparent:true, opacity:0.5,
          blending:THREE.AdditiveBlending, depthWrite:false, side:THREE.DoubleSide}));
      beam.position.copy(dir.clone().multiplyScalar(_gb.R + h/2));
      beam.quaternion.setFromUnitVectors(up, dir);
      beam.userData = {phase:(i*0.43)%6.283};
      _gb.group.add(beam); _gb.beams.push(beam);
    }

    // Stadt-Label für die größten Städte.
    if(labelIdx.has(i) && l.stadt){
      const {tex,w,h} = _labelTex(l.stadt);
      const lmat = new THREE.SpriteMaterial({map:tex, transparent:true, depthWrite:false, depthTest:false, opacity:0.92});
      const lab = new THREE.Sprite(lmat);
      const aspect = w/h, lh = 0.075;
      lab.scale.set(lh*aspect, lh, 1);
      lab.position.copy(dir.clone().multiplyScalar(_gb.R*1.06 + 0.05));
      lab.userData = {dir, base:lh, aspect};
      _gb.group.add(lab); _gb.labels.push(lab);
    }
  });

  // ── Netzwerk-Bögen: leuchtende Verbindungen von der stärksten zu den nächststärksten
  // Lead-Städten — macht das "Lead-Netzwerk" direkt auf dem Globus sichtbar, mit
  // wanderndem Lichtpuls je Bogen (Sternform: 1 Hub → mehrere Ziele, kostet nur N-1 Bögen).
  const hubCap = _LOWPWR ? 0 : 7;
  if(hubCap > 0 && byN.length > 1){
    const hub = byN[0].l;
    const [hLat,hLng] = _coordsFor(hub.stadt, hub.bundesland);
    const hDir = _llv(hLat, hLng, 1).normalize();
    byN.slice(1, hubCap).forEach((o,ai)=>{
      const [lat,lng] = _coordsFor(o.l.stadt, o.l.bundesland);
      const dir = _llv(lat, lng, 1).normalize();
      if(dir.distanceTo(hDir) < 0.0008) return; // exakt identische Koordinate wie Hub → kein Bogen
      const dom = (o.l.hot>=o.l.warm && o.l.hot>=o.l.cold) ? 'hot' : (o.l.warm>=o.l.cold ? 'warm' : 'cold');
      const col = _TYP_COL[dom];
      const mid = hDir.clone().add(dir).normalize().multiplyScalar(_gb.R*(1.2 + 0.08*ai));
      const p0 = hDir.clone().multiplyScalar(_gb.R*1.01);
      const p1 = dir.clone().multiplyScalar(_gb.R*1.01);
      const curve = new THREE.QuadraticBezierCurve3(p0, mid, p1);

      const tubeMat = new THREE.MeshBasicMaterial({color:col, transparent:true, opacity:0.22,
        blending:THREE.AdditiveBlending, depthWrite:false});
      const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, 48, 0.0026, 6, false), tubeMat);
      tube.userData = {phase:(ai*0.8)%6.283};
      _gb.group.add(tube); _gb.arcs.push(tube);

      const pulseMat = new THREE.SpriteMaterial({map:_glowTex(col), transparent:true,
        blending:THREE.AdditiveBlending, depthWrite:false, depthTest:false, opacity:0.95});
      const pulse = new THREE.Sprite(pulseMat);
      pulse.scale.set(0.032,0.032,1);
      pulse.userData = {curve, phase:(ai*0.31)%1, speed:0.11+ai*0.012};
      _gb.group.add(pulse); _gb.arcPulses.push(pulse);
    });
  }

  const cnt = document.getElementById('globe-count');
  if(cnt){
    cnt.dataset.base = `${total} Standorte · ${leads} Leads`;
    const ex = (_gb && _gb.leadMarkers) ? _gb.leadMarkers.length : 0;
    cnt.textContent = cnt.dataset.base + (ex ? ` · ${ex} adressgenau` : '');
  }
}

// Entfernt + disposed alle Marker/Beams/Ringe/Labels.
function _disposeMarkerLayer(){
  const g=_gb; if(!g) return;
  const kill=(obj)=>{
    g.group.remove(obj);
    if(obj.geometry) obj.geometry.dispose();
    if(obj.material){
      if(obj.material.map && obj.material.map.dispose) obj.material.map.dispose();
      obj.material.dispose();
    }
  };
  g.markers.forEach(m=>kill(m.sprite)); g.markers=[];
  g.beams.forEach(kill);  g.beams=[];
  g.rings.forEach(kill);  g.rings=[];
  g.labels.forEach(kill); g.labels=[];
  (g.arcs||[]).forEach(kill); g.arcs=[];
  (g.arcPulses||[]).forEach(kill); g.arcPulses=[];
}

function _wireGlobe(cv){
  const g=_gb; cv.style.cursor='grab';
  const down=e=>{ g.dragging=true; cv.style.cursor='grabbing'; const p=e.touches?e.touches[0]:e; g.lastX=p.clientX; g.lastY=p.clientY; };
  const move=e=>{
    const rect=cv.getBoundingClientRect(); const p=e.touches?e.touches[0]:e;
    g.mouse.x=((p.clientX-rect.left)/rect.width)*2-1; g.mouse.y=-((p.clientY-rect.top)/rect.height)*2+1;
    if(g.dragging){ g.userY+=(p.clientX-g.lastX)*0.005; g.userX=Math.max(-1.1,Math.min(1.1,g.userX+(p.clientY-g.lastY)*0.005)); g.lastX=p.clientX; g.lastY=p.clientY; }
  };
  const up=()=>{ g.dragging=false; cv.style.cursor='grab'; };
  cv.addEventListener('mousedown',down); window.addEventListener('mousemove',move); window.addEventListener('mouseup',up);
  cv.addEventListener('touchstart',down,{passive:true}); cv.addEventListener('touchmove',move,{passive:true}); cv.addEventListener('touchend',up);
  cv.addEventListener('wheel',e=>{ e.preventDefault();
    // Während des Intros lassen wir Zoom zu, danach ist targetZ frei steuerbar.
    g.targetZ=Math.max(1.9,Math.min(8.0, g.targetZ+(e.deltaY>0?0.32:-0.32))); },{passive:false});
  window.addEventListener('resize', _globeResize);
}

function _globeResize(){
  if(!_gb) return;
  const W=_gb.wrap.clientWidth||900, H=_gb.wrap.clientHeight||460;
  _gb.cam.aspect=W/H; _gb.cam.updateProjectionMatrix(); _gb.renderer.setSize(W,H,false);
}

function _globeTip(){
  const g=_gb, tip=document.getElementById('globe-tip'); if(!tip) return;
  g.ray.setFromCamera(g.mouse, g.cam);
  // Exakte Lead-Pins nur beim Reinzoomen mit-raycasten (Performance; weit weg zählt die Stadt).
  const objs = g.markers.map(m=>m.sprite);
  if(g.zoom < 4.2 && g.leadMarkers && g.leadMarkers.length) objs.push(...g.leadMarkers);
  const hit = g.ray.intersectObjects(objs, false)[0];
  if(hit && !g.dragging){
    const u=hit.object.userData, l=u.info;
    // Lead-Daten kommen aus Scraping (fremde Webseiten) — vor innerHTML immer escapen.
    const esc = s => String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    if(u.lead){
      tip.innerHTML = `<b>${esc(l.name)||'?'}</b><br>${esc(l.branche)}`
        + `${(l.branche&&l.stadt)?' · ':''}${esc(l.stadt)}`;
    } else {
    tip.innerHTML = `<b>${esc(l.stadt)||'?'}</b><br>${l.n} Lead${l.n===1?'':'s'} · `
      + `<span style="color:#ff5a4e">${l.hot} Hot</span> · <span style="color:#ffd24d">${l.warm} Warm</span> · <span style="color:#4dc3ff">${l.cold} Cold</span>`;
    }
    const rect=g.cv.getBoundingClientRect();
    tip.style.left=((g.mouse.x*0.5+0.5)*rect.width+14)+'px';
    tip.style.top=((-g.mouse.y*0.5+0.5)*rect.height+10)+'px';
    tip.style.display='block';
  } else { tip.style.display='none'; }
}

function _globeLoop(){
  if(!_gb) return;
  _gb.raf=requestAnimationFrame(_globeLoop);
  const g=_gb, pg=document.querySelector('.graph-page');
  if(pg && !pg.classList.contains('active')) return;

  const dt = _REDUCED ? 0.0 : 0.016;
  g.t += 0.016; // Zeit läuft immer (für Hover/Render), Animationsamplitude wird gedämpft.

  // ── Cinematischer Intro-Zoom: aus dem All → Deutschland ──
  if(g.introT<1){
    g.introT=Math.min(1, g.introT + (_REDUCED?0.05:0.011));
    const e=1-Math.pow(1-g.introT,3);            // easeOutCubic
    g.zoom = 6.6 - (6.6 - g.targetZ)*e;           // sanfter Anflug
    g.introY = (1-e) * (_REDUCED?0.4:2.2);        // Erde dreht sich beim Anflug ein
  } else {
    g.introY = 0;
    // Nach Intro: Kamera folgt targetZ (Wheel-Zoom) weich.
    g.zoom += (g.targetZ - g.zoom)*0.12;
  }
  g.cam.position.z = g.zoom;

  const sway = _REDUCED ? 0 : Math.sin(g.t*0.3)*0.03;
  g.pivot.rotation.y = g.userY + g.introY + sway;
  g.pivot.rotation.x = g.userX;

  if(g.clouds) g.clouds.rotation.y += (_REDUCED?0:0.0006);   // Wolken-Drift
  if(g.stars)  g.stars.rotation.y  += (_REDUCED?0:0.00012);  // Sterne langsam drehen

  const amp = _REDUCED ? 0.4 : 1.0;

  // Marker pulsieren.
  for(const m of g.markers){
    const u=m.sprite.userData;
    const s=u.base*(1 + 0.22*amp*Math.sin(g.t*2 + u.phase));
    m.sprite.scale.set(s,s,1);
  }
  // Bodenringe expandieren + verblassen (Ping-Effekt).
  for(const r of g.rings){
    const u=r.userData;
    const cyc=(g.t*0.9 + u.phase) % 6.283 / 6.283;  // 0..1
    const sc=1 + cyc*3.2;
    r.scale.set(sc,sc,1);
    r.material.opacity = (1-cyc)*0.5*amp;
  }
  // Beams pulsieren in Helligkeit.
  for(const b of g.beams){
    b.material.opacity = (0.3 + 0.25*amp*Math.abs(Math.sin(g.t*1.6 + b.userData.phase)));
  }
  // Netzwerk-Bögen: sanftes Atmen der Glow-Linie.
  for(const a of g.arcs){
    a.material.opacity = 0.14 + 0.14*amp*Math.abs(Math.sin(g.t*0.7 + (a.userData.phase||0)));
  }
  // Lichtpulse wandern entlang ihres Bogens, verblassen an Start/Ziel (Sinus-Fade).
  for(const p of g.arcPulses){
    const u=p.userData;
    const tt = (g.t*u.speed + u.phase) % 1;
    p.position.copy(u.curve.getPoint(tt));
    p.material.opacity = 0.9*amp*Math.sin(tt*Math.PI);
  }
  // Labels immer zur Kamera + nur sichtbar wenn auf der Vorderseite (nicht hinter dem Globus).
  if(g.labels.length){
    const camDir = g.cam.position.clone().normalize();
    for(const lab of g.labels){
      const wdir = lab.userData.dir.clone().applyQuaternion(g.group.quaternion).applyQuaternion(g.pivot.quaternion);
      const facing = wdir.dot(camDir);              // >0 ≈ zur Kamera gewandt
      const vis = Math.max(0, Math.min(1, (facing-0.15)/0.5));
      lab.material.opacity = 0.92*vis;
      lab.visible = vis > 0.02;
    }
  }

  // Exakte Lead-Pins: nur die zur Kamera gewandten zeigen (kein Durchscheinen von der Rückseite).
  if(g.leadMarkers && g.leadMarkers.length){
    const camDir = g.cam.position.clone().normalize();
    for(const s of g.leadMarkers){
      const wdir = s.position.clone().normalize()
        .applyQuaternion(g.group.quaternion).applyQuaternion(g.pivot.quaternion);
      s.visible = wdir.dot(camDir) > 0.12;
    }
  }

  _globeTip();
  g.renderer.render(g.scene, g.cam);
}

// Direktaufruf von #graph: initialisieren, sobald der Reiter aktiv ist.
document.addEventListener('DOMContentLoaded', ()=>{
  const pg=document.querySelector('.graph-page');
  if(pg && pg.classList.contains('active')) setTimeout(initGlobe, 60);
});
