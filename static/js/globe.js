// ════════════════════════════════════════════════════════════════════════════
//  3D-ERD-GLOBUS — realistische Erde (Satelliten-Look) mit Lead-Standorten.
//  Three.js r128. Echte Erd-Texturen (CDN), Sonnenlicht, Wolken, Atmosphäre,
//  Sterne. Start-Zoom Deutschland. Marker je Stadt mit Hover-Tooltip.
// ════════════════════════════════════════════════════════════════════════════
let _globeReady = false;
let _gb = null;

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
function _glowTex(color){
  if(_texCache[color]) return _texCache[color];
  const [r,g_,b]=_hexRgb(color);
  const c=document.createElement('canvas'); c.width=c.height=64; const g=c.getContext('2d');
  const grd=g.createRadialGradient(32,32,0,32,32,32);
  grd.addColorStop(0,`rgba(255,255,255,0.55)`);
  grd.addColorStop(0.18,`rgba(${r},${g_},${b},0.85)`);
  grd.addColorStop(1,`rgba(${r},${g_},${b},0)`);
  g.fillStyle=grd; g.beginPath(); g.arc(32,32,32,0,7); g.fill();
  const t=new THREE.CanvasTexture(c); _texCache[color]=t; return t;
}
const _TYP_COL = { hot:'#ff5a4e', warm:'#ffd24d', cold:'#4dc3ff' };
const _TEX = 'https://cdn.jsdelivr.net/gh/mrdoob/three.js@r128/examples/textures/planets/';

function initGlobe(){
  if(_globeReady){ _globeResize(); return; }
  const cv = document.getElementById('globe-canvas');
  if(!cv || typeof THREE === 'undefined') return;
  _globeReady = true;

  const wrap = document.getElementById('globe-wrap');
  const W = wrap.clientWidth || 900, H = wrap.clientHeight || 460;

  const scene = new THREE.Scene();
  const cam = new THREE.PerspectiveCamera(40, W/H, 0.1, 200);
  cam.position.set(0, 0, 4.6);
  const renderer = new THREE.WebGLRenderer({canvas:cv, antialias:true, alpha:true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1, 2));
  renderer.setSize(W, H, false);

  // Sternenhimmel
  const starGeo = new THREE.BufferGeometry();
  const sp = []; for(let i=0;i<1400;i++){ const r=40+Math.random()*40,
    th=Math.random()*Math.PI*2, ph=Math.acos(2*Math.random()-1);
    sp.push(r*Math.sin(ph)*Math.cos(th), r*Math.cos(ph), r*Math.sin(ph)*Math.sin(th)); }
  starGeo.setAttribute('position', new THREE.Float32BufferAttribute(sp,3));
  scene.add(new THREE.Points(starGeo, new THREE.PointsMaterial({color:0x88aacc, size:0.18, sizeAttenuation:true, transparent:true, opacity:0.7})));

  // Licht (Sonne von vorne-rechts-oben → Europa beleuchtet) + Fülllicht
  const sun = new THREE.DirectionalLight(0xffffff, 1.25); sun.position.set(2.5, 1.4, 3.5); scene.add(sun);
  scene.add(new THREE.AmbientLight(0x35506e, 0.5));

  const pivot = new THREE.Group();
  const group = new THREE.Group();
  pivot.add(group); scene.add(pivot);

  const R = 1.35;
  const loader = new THREE.TextureLoader(); loader.setCrossOrigin('anonymous');

  // Erd-Körper (zunächst dunkelblau, Texturen werden asynchron nachgeladen)
  const earthMat = new THREE.MeshPhongMaterial({color:0x143a5a, specular:0x224466, shininess:14});
  const earth = new THREE.Mesh(new THREE.SphereGeometry(R, 64, 64), earthMat); group.add(earth);
  loader.load(_TEX+'earth_atmos_2048.jpg', t=>{ earthMat.map=t; earthMat.color.set(0xffffff); earthMat.needsUpdate=true; });
  loader.load(_TEX+'earth_specular_2048.jpg', t=>{ earthMat.specularMap=t; earthMat.specular.set(0x666666); earthMat.needsUpdate=true; });

  // Wolken
  const cloudMat = new THREE.MeshPhongMaterial({transparent:true, opacity:0.0, depthWrite:false});
  const clouds = new THREE.Mesh(new THREE.SphereGeometry(R*1.012, 48, 48), cloudMat); group.add(clouds);
  loader.load(_TEX+'earth_clouds_1024.png', t=>{ cloudMat.map=t; cloudMat.alphaMap=t; cloudMat.opacity=0.45; cloudMat.needsUpdate=true; });

  // Atmosphäre (Rim-Glow)
  group.add(new THREE.Mesh(new THREE.SphereGeometry(R*1.16, 48, 48),
    new THREE.MeshBasicMaterial({color:0x4aa8ff, transparent:true, opacity:0.12, side:THREE.BackSide})));

  // Deutschland nach vorne
  group.quaternion.setFromUnitVectors(_llv(_DE[0], _DE[1], 1).normalize(), new THREE.Vector3(0,0,1));

  _gb = {scene, cam, renderer, pivot, group, clouds, R, markers:[], wrap, cv,
         userY:0, userX:0.14, dragging:false, lastX:0, lastY:0, introT:0, t:0,
         ray:new THREE.Raycaster(), mouse:new THREE.Vector2(-9,-9)};
  try{ window._gb = _gb; }catch(e){}

  _loadGlobeLocations();
  _wireGlobe(cv);
  _globeLoop();
}

async function _loadGlobeLocations(){
  let locs = [];
  try{ const d = await(await fetch('/api/graph/locations')).json(); locs = d.locations||[]; }catch{ locs=[]; }
  if(!_gb) return;
  _gb.markers.forEach(m=>_gb.group.remove(m.sprite)); _gb.markers=[];
  const total = locs.length, leads = locs.reduce((a,b)=>a+(b.n||0),0);
  const top = locs.slice(0, 160);
  let maxN=1; top.forEach(l=> maxN=Math.max(maxN,l.n||1));
  top.forEach((l,i)=>{
    const [lat,lng] = _coordsFor(l.stadt, l.bundesland);
    const dom = (l.hot>=l.warm && l.hot>=l.cold) ? 'hot' : (l.warm>=l.cold ? 'warm' : 'cold');
    const col = _TYP_COL[dom];
    const mat = new THREE.SpriteMaterial({map:_glowTex(col), transparent:true,
      blending:THREE.AdditiveBlending, depthWrite:false, depthTest:false});
    const sp = new THREE.Sprite(mat);
    sp.position.copy(_llv(lat, lng, _gb.R*1.015));
    const base = 0.02 + Math.log2(1+(l.n||1))/Math.log2(1+maxN) * 0.035;
    sp.userData = {base, phase:(i%20)/20*6.283, info:l, dom};
    sp.scale.set(base, base, 1);
    _gb.group.add(sp); _gb.markers.push({sprite:sp});
  });
  const cnt = document.getElementById('globe-count');
  if(cnt) cnt.textContent = `${total} Standorte · ${leads} Leads`;
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
  cv.addEventListener('wheel',e=>{ e.preventDefault(); g.cam.position.z=Math.max(1.7,Math.min(7,g.cam.position.z+(e.deltaY>0?0.25:-0.25))); },{passive:false});
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
  const hit = g.ray.intersectObjects(g.markers.map(m=>m.sprite), false)[0];
  if(hit && !g.dragging){
    const l=hit.object.userData.info;
    tip.innerHTML = `<b>${(l.stadt||'?')}</b><br>${l.n} Lead${l.n===1?'':'s'} · `
      + `<span style="color:#ff5a4e">${l.hot} Hot</span> · <span style="color:#ffd24d">${l.warm} Warm</span> · <span style="color:#4dc3ff">${l.cold} Cold</span>`;
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
  g.t+=0.016;
  if(g.introT<1){ g.introT=Math.min(1,g.introT+0.012); const e=1-Math.pow(1-g.introT,3);
    g.cam.position.z=4.6-2.0*e; g.introY=(1-e)*2.0; } else { g.introY=0; }
  const sway=Math.sin(g.t*0.3)*0.03;
  g.pivot.rotation.y=g.userY+g.introY+sway; g.pivot.rotation.x=g.userX;
  if(g.clouds) g.clouds.rotation.y += 0.0006;            // Wolken driften
  for(const m of g.markers){ const s=m.sprite.userData.base*(1+0.2*Math.sin(g.t*2+m.sprite.userData.phase)); m.sprite.scale.set(s,s,1); }
  _globeTip();
  g.renderer.render(g.scene, g.cam);
}

// Direktaufruf von #graph: initialisieren, sobald der Reiter aktiv ist.
document.addEventListener('DOMContentLoaded', ()=>{
  const pg=document.querySelector('.graph-page');
  if(pg && pg.classList.contains('active')) setTimeout(initGlobe, 60);
});
