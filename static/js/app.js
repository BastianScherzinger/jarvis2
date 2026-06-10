/* ── JARVIS LeadHunter — Frontend ─────────────────────────────────────────── */

let _running    = false;
let _sse        = null;
let _feedCount  = 0;
let _allLeads   = [];   // lokaler Cache aller gesehenen Leads
let _statsTimer = null;

// ── KI / Modus Toggle ─────────────────────────────────────────────────────────
document.querySelectorAll("#ai-toggle .tgl").forEach(btn => {
  btn.addEventListener("click", () => {
    if (_running) return;
    document.querySelectorAll("#ai-toggle .tgl").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
  });
});
document.querySelectorAll("#mode-toggle .tgl").forEach(btn => {
  btn.addEventListener("click", () => {
    if (btn.classList.contains("disabled")) return;
    document.querySelectorAll("#mode-toggle .tgl").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
  });
});

function _getAiMode() {
  return document.querySelector("#ai-toggle .tgl.active")?.dataset.val || "local";
}

// ── Start / Stop ──────────────────────────────────────────────────────────────
function toggleScraper() {
  if (_running) {
    stopScraper();
  } else {
    startScraper();
  }
}

async function startScraper() {
  const ai_mode = _getAiMode();
  const res = await fetch("/api/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ai_mode }),
  });
  const data = await res.json();
  if (!data.ok && data.reason !== "already_running") {
    console.error("Start fehlgeschlagen:", data);
    return;
  }

  _running = true;
  _updateRunningUI(true);
  _connectSSE();
  _statsTimer = setInterval(_fetchStats, 5000);
}

async function stopScraper() {
  await fetch("/api/stop", { method: "POST" });
  _running = false;
  _updateRunningUI(false);
  if (_sse) { _sse.close(); _sse = null; }
  if (_statsTimer) { clearInterval(_statsTimer); _statsTimer = null; }
}

function _updateRunningUI(on) {
  const btn  = document.getElementById("btn-start");
  const icon = btn.querySelector(".btn-icon");
  const text = btn.querySelector(".btn-text");
  const live = document.getElementById("live-badge");
  const lbl  = document.getElementById("live-text");

  if (on) {
    btn.classList.add("running");
    icon.textContent = "■";
    text.textContent = "STOP";
    live.classList.add("on");
    lbl.textContent = "LIVE";
  } else {
    btn.classList.remove("running");
    icon.textContent = "▶";
    text.textContent = "START";
    live.classList.remove("on");
    lbl.textContent = "OFFLINE";
  }
}

// ── SSE Verbindung ─────────────────────────────────────────────────────────────
function _connectSSE() {
  if (_sse) { _sse.close(); }
  _sse = new EventSource("/api/stream");

  _sse.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type === "lead")  _onLead(msg.data);
      if (msg.type === "error") _onError(msg.msg);
    } catch (err) { /* ignore */ }
  };

  _sse.onerror = () => {
    if (_running) {
      setTimeout(_connectSSE, 3000);   // Reconnect
    }
  };
}

// ── Neuer Lead empfangen ───────────────────────────────────────────────────────
function _onLead(lead) {
  _allLeads.unshift(lead);
  _feedCount++;

  document.getElementById("feed-empty")?.remove();
  document.getElementById("feed-count").textContent = `${_feedCount} Nachrichten`;

  const feed = document.getElementById("chat-feed");
  const msg  = _buildMsg(lead);
  feed.insertBefore(msg, feed.firstChild);

  // Limitiere Chat-Bubble-Anzahl auf 200 (Performance)
  const msgs = feed.querySelectorAll(".msg");
  if (msgs.length > 200) msgs[msgs.length - 1].remove();

  // Hot Leads in der Sidebar
  if (lead.lead_typ === "Hot") {
    _addRecentHot(lead);
  }

  _updateStats();
}

function _onError(msg) {
  const feed = document.getElementById("chat-feed");
  const el   = document.createElement("div");
  el.className   = "msg-error";
  el.textContent = "⚠ " + msg;
  feed.insertBefore(el, feed.firstChild);
}

// ── Chat-Bubble bauen ─────────────────────────────────────────────────────────
function _buildMsg(lead) {
  const wrap = document.createElement("div");
  wrap.className = "msg";

  const avatarCls = _avatarClass(lead.finder);
  const avatarLbl = _avatarLabel(lead.finder);

  const time = new Date().toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  const webTag    = lead.has_website
    ? `<span class="mc-tag ylw">⚠ Website alt: ${lead.website_alter >= 0 ? lead.website_alter + "j" : "?"}</span>`
    : `<span class="mc-tag red">✗ Kein Website</span>`;
  const telTag    = lead.telefon ? `<span class="mc-tag grn">✓ Telefon</span>` : "";
  const bildTag   = lead.bilder  ? `<span class="mc-tag">📷 Bilder</span>` : "";
  const brancheTag= lead.branche ? `<span class="mc-tag">${lead.branche}</span>` : "";
  const ratingTxt = lead.bewertung ? `⭐ ${lead.bewertung}` + (lead.anz_bewertungen ? ` (${lead.anz_bewertungen})` : "") : "";

  wrap.innerHTML = `
    <div class="msg-avatar ${avatarCls}">${avatarLbl}</div>
    <div class="msg-body">
      <div class="msg-meta">
        <span class="msg-sender">${_senderName(lead.finder)}</span>
        <span class="msg-time">${time}</span>
        <span class="msg-score ${lead.lead_typ}">${lead.lead_typ} · ${lead.score}pt</span>
      </div>
      <div class="msg-card ${lead.lead_typ}" data-id="${lead.id||0}" onclick="openModal(${JSON.stringify(lead).replace(/"/g,'&quot;')})">
        <div class="mc-name">${_esc(lead.name)}</div>
        <div class="mc-tags">
          ${webTag}${telTag}${bildTag}${brancheTag}
        </div>
        <div class="mc-detail">
          ${lead.adresse ? `<div class="mc-row"><span class="mc-icon">📍</span>${_esc(lead.adresse)}</div>` : ""}
          ${lead.telefon ? `<div class="mc-row"><span class="mc-icon">📞</span>${_esc(lead.telefon)}</div>` : ""}
          ${ratingTxt    ? `<div class="mc-row"><span class="mc-icon">★</span>${ratingTxt}</div>` : ""}
        </div>
      </div>
    </div>`;

  return wrap;
}

function _avatarClass(finder) {
  if (!finder) return "maps";
  if (finder.includes("maps"))   return "maps";
  if (finder.includes("gelbe"))  return "gelbe";
  if (finder.includes("ollama")) return "ollama";
  if (finder.includes("claude")) return "claude";
  return "maps";
}
function _avatarLabel(finder) {
  if (!finder) return "M";
  if (finder.includes("maps"))   return "M";
  if (finder.includes("gelbe"))  return "G";
  if (finder.includes("ollama")) return "AI";
  if (finder.includes("claude")) return "CL";
  return "?";
}
function _senderName(finder) {
  const map = {
    maps_playwright: "Google Maps",
    gelbe_seiten:    "Gelbe Seiten",
    ollama_ai:       "Ollama KI",
    claude_ai:       "Claude KI",
  };
  return map[finder] || finder || "Unbekannt";
}
function _esc(s) {
  return (s || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

// ── Sidebar: letzte Hot Leads ─────────────────────────────────────────────────
function _addRecentHot(lead) {
  const list = document.getElementById("recent-hot");
  const card = document.createElement("div");
  card.className = "recent-card";
  card.innerHTML = `
    <div class="rc-name">${_esc(lead.name)}</div>
    <div class="rc-info">${_esc(lead.stadt)} · ${lead.score}pt</div>`;
  card.onclick = () => openModal(lead);
  list.insertBefore(card, list.firstChild);
  // Max 30 Recent
  const cards = list.querySelectorAll(".recent-card");
  if (cards.length > 30) cards[cards.length - 1].remove();
}

// ── Stats aktualisieren ───────────────────────────────────────────────────────
function _updateStats() {
  const leads  = _allLeads;
  const total  = leads.length;
  const hot    = leads.filter(l => l.lead_typ === "Hot").length;
  const warm   = leads.filter(l => l.lead_typ === "Warm").length;
  const cold   = total - hot - warm;
  const noWeb  = leads.filter(l => !l.has_website).length;
  const noWebP = total ? Math.round(noWeb / total * 100) : 0;

  document.getElementById("s-total").textContent = total;
  document.getElementById("s-hot").textContent   = hot;
  document.getElementById("s-warm").textContent  = warm;
  document.getElementById("s-cold").textContent  = cold;
  document.getElementById("s-noweb").textContent = noWebP + "%";

  // Finder-Liste
  const finders = {};
  leads.forEach(l => { if (l.finder) finders[l.finder] = (finders[l.finder] || 0) + 1; });
  const fl = document.getElementById("finder-list");
  const rows = Object.entries(finders).sort((a,b) => b[1]-a[1]).map(([k,v]) =>
    `<div class="finder-row"><span class="finder-name">${_senderName(k)}</span><span class="finder-count">${v}</span></div>`
  ).join("");
  fl.innerHTML = `<div class="finder-title">Quellen</div>${rows}`;
}

async function _fetchStats() {
  try {
    const res  = await fetch("/api/status");
    const data = await res.json();
    const s    = data.stats;
    document.getElementById("s-total").textContent = s.total;
    document.getElementById("s-hot").textContent   = s.hot;
    document.getElementById("s-warm").textContent  = s.warm;
    document.getElementById("s-cold").textContent  = s.cold;
    const p = s.total ? Math.round(s.no_web / s.total * 100) : 0;
    document.getElementById("s-noweb").textContent = p + "%";
  } catch (e) { /* ignore */ }
}

// ── Filter ────────────────────────────────────────────────────────────────────
function applyFilter() {
  const fTyp = document.getElementById("flt-typ").value;
  const fWeb = document.getElementById("flt-web").value;
  const fBl  = document.getElementById("flt-bl").value;

  document.querySelectorAll(".msg").forEach(msg => {
    const card = msg.querySelector(".msg-card");
    if (!card) return;

    // Typ
    const typ     = card.classList.contains("Hot") ? "Hot" : card.classList.contains("Warm") ? "Warm" : "Cold";
    const typOk   = !fTyp || typ === fTyp;

    // Website — aus gespeichertem Datensatz (data-id attr)
    const id      = parseInt(card.dataset.id || "0");
    const lead    = _allLeads.find(l => l.id === id);
    const webOk   = !fWeb  || (lead && String(lead.has_website) === fWeb);
    const blOk    = !fBl   || (lead && lead.bundesland === fBl);

    msg.style.display = (typOk && webOk && blOk) ? "" : "none";
  });
}

// ── Modal ──────────────────────────────────────────────────────────────────────
function openModal(lead) {
  if (typeof lead === "string") {
    try { lead = JSON.parse(lead); } catch { return; }
  }
  const c = document.getElementById("modal-content");
  const webRow = lead.has_website
    ? `<div class="modal-row"><span class="modal-row-key">Website</span><span class="modal-row-val"><a href="${_esc(lead.website_url)}" target="_blank">${_esc(lead.website_url)}</a></span></div>
       <div class="modal-row"><span class="modal-row-key">Website-Alter</span><span class="modal-row-val">${lead.website_alter >= 0 ? lead.website_alter + " Jahre" : "unbekannt"}</span></div>`
    : `<div class="modal-row"><span class="modal-row-key">Website</span><span class="modal-row-val" style="color:var(--red)">❌ Kein Website</span></div>`;

  const mapsLink = lead.maps_url
    ? `<div class="modal-row"><span class="modal-row-key">Google Maps</span><span class="modal-row-val"><a href="${_esc(lead.maps_url)}" target="_blank">Öffnen ↗</a></span></div>`
    : "";

  c.innerHTML = `
    <div class="modal-name">${_esc(lead.name)}</div>
    <div class="modal-tags">
      <span class="mc-tag ${lead.lead_typ === 'Hot' ? 'red' : lead.lead_typ === 'Warm' ? 'ylw' : ''}">${lead.lead_typ} Lead · ${lead.score}pt</span>
      ${lead.branche ? `<span class="mc-tag">${_esc(lead.branche)}</span>` : ""}
      ${lead.bundesland ? `<span class="mc-tag">${_esc(lead.bundesland)}</span>` : ""}
    </div>
    <div class="score-bar"><div class="score-fill ${lead.lead_typ}" style="width:${lead.score}%"></div></div>

    <div class="modal-section" style="margin-top:16px">
      <div class="modal-section-title">Kontakt</div>
      <div class="modal-row"><span class="modal-row-key">Name</span><span class="modal-row-val">${_esc(lead.name)}</span></div>
      ${lead.adresse  ? `<div class="modal-row"><span class="modal-row-key">Adresse</span><span class="modal-row-val">${_esc(lead.adresse)}</span></div>` : ""}
      ${lead.telefon  ? `<div class="modal-row"><span class="modal-row-key">Telefon</span><span class="modal-row-val">${_esc(lead.telefon)}</span></div>` : ""}
      ${lead.stadt    ? `<div class="modal-row"><span class="modal-row-key">Stadt</span><span class="modal-row-val">${_esc(lead.stadt)}</span></div>` : ""}
    </div>

    <div class="modal-section">
      <div class="modal-section-title">Online-Präsenz</div>
      ${webRow}
      ${lead.bilder ? `<div class="modal-row"><span class="modal-row-key">Bilder</span><span class="modal-row-val" style="color:var(--green)">✓ vorhanden</span></div>` : ""}
    </div>

    <div class="modal-section">
      <div class="modal-section-title">Bewertung & Quelle</div>
      ${lead.bewertung ? `<div class="modal-row"><span class="modal-row-key">Bewertung</span><span class="modal-row-val">⭐ ${lead.bewertung} (${lead.anz_bewertungen} Bewertungen)</span></div>` : ""}
      <div class="modal-row"><span class="modal-row-key">Gefunden von</span><span class="modal-row-val">${_senderName(lead.finder)}</span></div>
      <div class="modal-row"><span class="modal-row-key">Gefunden am</span><span class="modal-row-val">${lead.gefunden_am || "—"}</span></div>
      ${mapsLink}
    </div>`;

  document.getElementById("modal-bg").classList.add("open");
  document.getElementById("modal").classList.add("open");
}

function closeModal() {
  document.getElementById("modal-bg").classList.remove("open");
  document.getElementById("modal").classList.remove("open");
}

document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });

// ── Feed leeren ────────────────────────────────────────────────────────────────
function clearFeed() {
  const feed = document.getElementById("chat-feed");
  feed.innerHTML = "";
  _allLeads   = [];
  _feedCount  = 0;
  document.getElementById("feed-count").textContent = "0 Nachrichten";
  _updateStats();
}

// ── CSV Export ────────────────────────────────────────────────────────────────
function exportCSV() {
  window.location.href = "/api/export/csv";
}

// ── Init: Status beim Laden prüfen ────────────────────────────────────────────
(async function init() {
  try {
    const res  = await fetch("/api/status");
    const data = await res.json();
    if (data.running) {
      _running = true;
      _updateRunningUI(true);
      _connectSSE();
      _statsTimer = setInterval(_fetchStats, 5000);
    }
    if (data.stats) {
      const s = data.stats;
      document.getElementById("s-total").textContent = s.total;
      document.getElementById("s-hot").textContent   = s.hot;
      document.getElementById("s-warm").textContent  = s.warm;
      document.getElementById("s-cold").textContent  = s.cold;
    }
  } catch (e) { /* Server noch nicht bereit */ }
})();
