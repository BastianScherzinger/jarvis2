"""
JARVIS LeadHunter — Flask Backend.
"""
import json
import os
import queue
from pathlib import Path

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_from_directory,
    stream_with_context,
)

import db_raw
import db_evaluated
import db_websites
import media_queue
import cloud_sync
import logger as _logger
from scrapers import controller, _http

app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24)
db_raw.init_db()
db_evaluated.init_db()
db_websites.init_db()


# ── HTTP-Zugriffslog entrümpeln ───────────────────────────────────────────────
# Der Flask-Dev-Server (Werkzeug) loggt JEDEN Request. Das Dashboard pollt einige
# Status-Endpunkte im Sekundentakt → 95 % des Logs sind identische „GET … 200"-Zeilen,
# die echte Ereignisse (Bau, Deploy, Fehler) zuscrollen. Dieser Filter wirft NUR
# erfolgreiche (200/304) Polling-Requests weg — Fehler (4xx/5xx) und alle anderen
# Endpunkte bleiben vollständig sichtbar. Abschaltbar via JARVIS_QUIET_ACCESS_LOG=0.
if (os.environ.get("JARVIS_QUIET_ACCESS_LOG", "1") or "1").strip().lower() not in ("0", "false", "no", "off"):
    import logging as _logging

    _QUIET_PATHS = (
        "/api/websites/grouped", "/api/auto-build/status", "/api/status", "/api/top",
        "/api/activity/recent", "/api/home/stats", "/api/logs", "/api/limit/status",
        "/api/costs", "/favicon.ico",
    )

    class _AccessLogFilter(_logging.Filter):
        def filter(self, record: "_logging.LogRecord") -> bool:
            try:
                msg = record.getMessage()
            except Exception:
                return True
            # Nur erfolgreiche Poll-Requests schlucken — Fehlerstatus immer durchlassen.
            if ('" 200 ' in msg or '" 304 ' in msg) and any(p in msg for p in _QUIET_PATHS):
                return False
            return True

    _logging.getLogger("werkzeug").addFilter(_AccessLogFilter())


# Globaler Fehler-Handler: jede unbehandelte Exception in einer Route landet mit vollem
# Traceback in der CMD (logger.error) + im Frontend-Konsolen-Ringpuffer — damit Sir
# Fehler wirklich SIEHT, statt dass sie still als 500 verschwinden.
@app.errorhandler(Exception)
def _handle_uncaught(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e                                  # 404/405 etc. normal durchreichen
    import traceback
    try:
        _logger.error("HTTP", f"Unbehandelter Fehler in {request.method} {request.path}: "
                              f"{type(e).__name__}: {str(e)[:200]}")
        _logger.error("HTTP", "Traceback: " + traceback.format_exc().strip().replace("\n", " | ")[-500:])
    except Exception:
        pass
    return jsonify({"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}), 500

# Die Bewertung startet bewusst NICHT automatisch beim Boot — erst wenn Sir den
# Start-Button drückt (/api/start → controller.start()). So bleibt der Programmstart
# leicht und es laufen anfangs keine Scraper/Evaluator/Ollama-Last.
import threading as _startup_t

# Cloud-Sync starten (batch alle 10 Min)
cloud_sync.start()
# Startup-Pull: alle Supabase-Leads in lokalen Cache laden (andere PCs)
_startup_t.Thread(target=cloud_sync.pull_and_cache, daemon=True).start()

# Webseiten-Sync (Cross-PC): gebaute Seiten + Links + Bilder von allen PCs zeigen
import cloud_sync_websites
cloud_sync_websites.start()


def _websites_startup_sync():
    cloud_sync_websites.pull_into_db()      # remote → lokal
    cloud_sync_websites.push_all_local()    # bestehende lokale → cloud
_startup_t.Thread(target=_websites_startup_sync, daemon=True).start()

# Whisper-Modell für die Spracheingabe im Hintergrund vorladen (lädt es beim
# ersten Start automatisch herunter — blockiert den Dashboard-Start nicht).
def _warmup_voice():
    try:
        import voice_web
        voice_web.warmup()
    except Exception:
        pass
_startup_t.Thread(target=_warmup_voice, daemon=True).start()


# Makeover-Voraussetzungen sicherstellen: (1) die mitgelieferten Skills (taste/ui-ux-pro-max)
# nach ~/.claude/skills spiegeln, damit der headless Makeover-Claude sie im Webseiten-Ordner
# laden kann; (2) die claude-CLI nachinstallieren, falls sie fehlt (sonst kein Makeover).
def _ensure_makeover_setup():
    try:
        import claude_skills
        claude_skills.ensure_installed()
    except Exception:
        pass
    try:
        import claude_coder
        claude_coder.ensure_cli()
    except Exception:
        pass
_startup_t.Thread(target=_ensure_makeover_setup, daemon=True).start()


# Discord-Freigabe-Bot (Voting-Gate vor dem Kundenversand) — nur wenn konfiguriert.
def _start_discord():
    try:
        import discord_bot
        if discord_bot.enabled():
            discord_bot.start()
    except Exception:
        pass
_startup_t.Thread(target=_start_discord, daemon=True).start()


# ── Startup-Aufräumen + Auto-Builder Resume ──────────────────────────────────
def _startup_cleanup():
    """Beim App-Start: hängende 'running'-Seiten korrigieren und Night-Builder fortsetzen."""
    import time as _t
    _t.sleep(2)   # kurz warten bis DB-Sync fertig ist
    try:
        import db_websites as _dw
        stuck = [s for s in _dw.get_all() if s.get("status") == "running"]
        for s in stuck:
            job_id = s.get("job_id")
            if not job_id:
                continue
            # Hat bereits eine live_url → war erfolgreich deployed, nur Status hängt
            if s.get("live_url"):
                _dw.update(job_id, status="done", live=1, progress=100, step="Fertig")
                _logger.info("Startup", f"Status korrigiert (done+live): {s.get('name','?')}")
            else:
                # Kein live_url → Bau war unvollständig, als done ohne live markieren
                _dw.update(job_id, status="done", live=0, progress=50, step="Unterbrochen")
                _logger.info("Startup", f"Status korrigiert (done): {s.get('name','?')}")
    except Exception as e:
        _logger.warn("Startup", f"Stuck-Site-Cleanup fehlgeschlagen: {type(e).__name__}")

    # Fremde (von anderen PCs reingesyncte) Webseiten aus dem lokalen Dashboard entfernen —
    # NUR die DB-Zeile (kein Remote-Eingriff): job_id 'remote-…' ODER ein gesetzter Ordner, der
    # auf DIESEM PC nicht existiert. So zeigt das Dashboard nur die eigenen, lokal baubaren
    # Seiten (Sirs Beschwerde „aufeinmal alle alten wieder da"). Mid-Build-Zeilen (running/
    # queued) bleiben unangetastet.
    try:
        import os as _os
        import db_websites as _dw
        entfernt = 0
        for s in _dw.get_all():
            jid = (s.get("job_id") or "")
            folder = (s.get("folder") or "").strip()
            is_remote = jid.startswith("remote-")
            foreign_folder = bool(folder) and not _os.path.isdir(folder) and \
                s.get("status") not in ("running", "queued")
            if is_remote or foreign_folder:
                try:
                    _dw.delete(s["id"])
                    entfernt += 1
                except Exception:
                    pass
        if entfernt:
            _logger.info("Startup", f"{entfernt} fremde/synchronisierte Webseiten aus dem "
                                    "Dashboard entfernt (nur lokale Anzeige, kein Remote-Eingriff).")
    except Exception as e:
        _logger.warn("Startup", f"Fremd-Seiten-Cleanup übersprungen: {type(e).__name__}")

    # Night-Builder fortsetzen wenn er beim letzten Mal lief
    try:
        import auto_builder
        if auto_builder.resume_if_needed():
            _logger.info("Startup", "Night-Builder automatisch fortgesetzt")
        # Live-Watcher IMMER starten (auch wenn der Builder aus ist): prüft regelmäßig, ob die
        # Seiten-Links wirklich antworten (200, kein 404), setzt den Live-Status ehrlich und
        # deployt kaputte LOKALE Seiten automatisch neu → „alle Links live".
        auto_builder.start_live_watch()
    except Exception as e:
        _logger.warn("Startup", f"Builder-Resume fehlgeschlagen: {type(e).__name__}")

    # Higgsfield-MCP bereitmachen: angemeldet → Token still erneuern; sonst (z.B. NEUER PC)
    # den einmaligen Browser-Login anstoßen, damit JARVIS danach die Abo-Credits nutzt.
    try:
        import higgsfield_mcp
        higgsfield_mcp.ensure_ready()
    except Exception as e:
        _logger.warn("Startup", f"Higgsfield-MCP-Setup übersprungen: {type(e).__name__}")

_startup_t.Thread(target=_startup_cleanup, daemon=True).start()

_MEDIA_DIR = Path(__file__).parent / "workspace" / "media"


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# Stats max. 1×/Sek aggregieren (statt bei JEDEM Lead-Event eine volle COUNT-Runde).
import time as _time
_stats_cache = {"t": 0.0, "v": None}


def _stats() -> dict:
    """Dashboard-Zähler: Funde/Quellen/Bundesländer aus db_raw + Hot/Warm/Cold aus db_evaluated.
    (leads.db eliminiert — db_evaluated ist der kanonische Lead-Store.)"""
    now = _time.time()
    if _stats_cache["v"] is None or now - _stats_cache["t"] > 1.0:
        s = db_raw.get_dashboard_stats()
        s.update(db_evaluated.get_typ_counts())
        _stats_cache["v"] = s
        _stats_cache["t"] = now
    return _stats_cache["v"]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    return ("", 204)   # kein Icon nötig — verhindert 404-Spam im Log


@app.route("/api/start", methods=["POST"])
def api_start():
    if not controller.is_running():
        controller.start()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "reason": "already_running"})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    controller.stop()
    return jsonify({"ok": True})


@app.route("/api/status")
def api_status():
    try:
        import claude_limit
        limit = claude_limit.state()
    except Exception:
        limit = {"limited": False}
    return jsonify({
        "running": controller.is_running(),
        "stats":   _stats(),
        "workers": controller.worker_health(),   # echte Pro-Worker-Gesundheit
        "claude_limit": limit,                    # „Limit voll"-Zeichen fürs Dashboard
    })


@app.route("/api/export/csv")
def api_export_csv():
    # Sortierter Export der KI-bewerteten Leads (DB2): Score absteigend,
    # sprechende deutsche Spalten, Semikolon + BOM für deutsches Excel.
    csv_text = db_evaluated.export_csv()
    return Response(
        csv_text.encode("utf-8"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=leads_rangliste.csv"},
    )


@app.route("/api/top")
def api_top():
    # Nutze db_evaluated statt altem Verifier-Status (war immer 'pending')
    return jsonify({"top": db_evaluated.get_top(10)})


# Feed-Modal-IDs sind raw_ids (db_raw). Nach Bewertung liegt der Lead in db_evaluated
# (verknüpft über raw_id); davor nur als Rohdatensatz. Diese Auflösung ist eindeutig
# (die Rangliste nutzt eigene Eval-Routen) — daher kein ID-Namensraum-Konflikt.
def _feed_lead(lead_id: int) -> dict | None:
    return db_evaluated.get_by_raw_id(lead_id) or db_raw.get_by_id(lead_id)


@app.route("/api/lead/<int:lead_id>/status", methods=["POST"])
def api_lead_status(lead_id):
    body   = request.get_json(silent=True) or {}
    status = body.get("status", "")
    allowed = {"neu", "kontaktiert", "termin", "verkauft", "tot"}
    if status not in allowed:
        return jsonify({"ok": False, "reason": "invalid_status"}), 400
    ev = db_evaluated.get_by_raw_id(lead_id)
    if ev:
        db_evaluated.update_status(ev["id"], status)
        return jsonify({"ok": True, "status": status})
    # Lead noch nicht bewertet → Status lässt sich (noch) nicht persistieren.
    return jsonify({"ok": True, "status": status,
                    "hinweis": "Lead wird noch bewertet — Status nach der Bewertung setzbar."})


@app.route("/api/lead/<int:lead_id>/email", methods=["POST"])
def api_lead_email(lead_id):
    """Generiert einen Outreach-E-Mail-Entwurf (synchron via Ollama, ~5-20s)."""
    from agents import outreach
    lead = _feed_lead(lead_id)
    if not lead:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    result = outreach.generate_email(lead)
    # Entwurf am kanonischen (bewerteten) Lead speichern, falls vorhanden.
    ev = db_evaluated.get_by_raw_id(lead_id)
    if ev and (result.get("betreff") or result.get("text")):
        try:
            db_evaluated.set_email_entwurf(ev["id"], json.dumps(result, ensure_ascii=False))
        except Exception:
            pass
    return jsonify(result)


@app.route("/api/lead/<int:lead_id>/mockup", methods=["POST"])
def api_lead_mockup(lead_id):
    """Reiht einen Website-Mockup-Bild-Job für diesen Lead ein."""
    lead = _feed_lead(lead_id)
    if not lead:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    branche = (lead.get("branche") or "business").strip()
    prompt = (
        f"modern professional website hero image for a German {branche} business, "
        f"clean corporate design, high quality, no text"
    )
    # Modell wählt media_queue hardware-abhängig (GPU → SDXL, CPU → SD-Turbo).
    job_id = media_queue.submit("mockup", {
        "prompt":    prompt,
        "lead_id":   lead_id,
    })
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/lead/<int:eval_id>/website", methods=["POST"])
def api_lead_website(eval_id):
    """Startet den Website-Builder für einen Lead (Vorlage → Fotos → Claude → GitHub → Railway)."""
    import website_builder
    if not website_builder.is_available():
        return jsonify({"ok": False, "reason": "vorlage_landing/ fehlt"}), 500

    # Der Body ist die maßgebliche Quelle — das geöffnete Modal (Feed ODER Rangliste)
    # liefert den vollständigen Lead inkl. foto_urls. Fehlende Felder werden aus
    # db_evaluated angereichert: per raw_id (Feed) ODER id (Rangliste), aber nur wenn
    # der Name passt (schützt gegen raw_id/eval_id-Namensraum-Kollision).
    body = request.get_json(silent=True) or {}
    use_hf = bool(body.get("use_higgsfield"))   # Higgsfield-Cloud nur auf ausdrücklichen Wunsch
    lead = dict(body)
    lead.pop("use_higgsfield", None)
    for getter in (db_evaluated.get_by_raw_id, db_evaluated.get_by_id):
        try:
            row = getter(eval_id)
        except Exception:
            row = None
        if not row:
            continue
        bn = (lead.get("name") or "").strip().lower()
        rn = (row.get("name") or "").strip().lower()
        if bn and rn and bn[:12] != rn[:12]:
            continue   # falsche Zeile (ID-Namensraum-Kollision) → überspringen
        for k, v in row.items():
            if v not in (None, "", []) and not lead.get(k):
                lead[k] = v
        break
    if not lead.get("name"):
        return jsonify({"ok": False, "reason": "Kein Lead-Name."}), 400

    job_id = website_builder.build(lead, use_higgsfield=use_hf)
    import agent_github
    import agent_railway
    import media_engine
    return jsonify({"ok": True, "job_id": job_id,
                    "github_ready": agent_github.is_ready(),
                    "railway_ready": agent_railway.is_ready(),
                    "higgsfield_ready": media_engine.higgsfield_available()})


@app.route("/api/website/job/<job_id>")
def api_website_job(job_id):
    import website_builder
    job = website_builder.get(job_id)
    if job is None:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    return jsonify(job)


@app.route("/api/websites")
def api_websites():
    """Alle persistierten Webseiten-Bau-Jobs (für den 'Webseiten'-Reiter)."""
    return jsonify({"ok": True, "websites": db_websites.get_all()})


@app.route("/api/websites/grouped")
def api_websites_grouped():
    """Aktive (nicht archivierte) Websites gruppiert nach Bautag."""
    import time as _time
    daily_limit = int(os.environ.get("JARVIS_DAILY_SITES", "7") or "7")
    today = _time.strftime("%Y-%m-%d")
    all_sites = db_websites.get_all()          # archived=0 (Standard)

    try:
        import overnight_makeover as _om
        import site_meta as _sm
        _stage_total = len(_om.STAGES)
        _stage_labels = [st.get("label", st.get("key", "")) for st in _om.STAGES]
    except Exception:
        _om = None
        _stage_total = 2
        _stage_labels = []

    for s in all_sites:
        ts = s.get("created") or 0
        s["build_date"] = _time.strftime("%Y-%m-%d", _time.localtime(ts)) if ts else "unbekannt"
        # Update-Level (Version) + Makeover-Stufen-Stand je Seite fürs Dashboard-Badge.
        folder = s.get("folder") or ""
        s["stages_total"] = _stage_total
        s["stage_labels"] = _stage_labels
        try:
            if _om and folder:
                c = _om._read_content(folder)
                s["site_version"] = c.get("site_version", "")
                s["stages_done"] = _stage_total - _om.open_stages(folder)
            else:
                s["site_version"] = ""
                s["stages_done"] = 0
        except Exception:
            s["site_version"] = ""
            s["stages_done"] = 0

    days_dict: dict = {}
    for s in all_sites:
        days_dict.setdefault(s["build_date"], []).append(s)

    days = []
    for d in sorted(days_dict.keys(), reverse=True):
        sites = days_dict[d]
        auto_count  = min(len(sites), daily_limit)
        extra_count = max(0, len(sites) - daily_limit)
        days.append({
            "date":        d,
            "is_today":    d == today,
            "sites":       sites,
            "count":       len(sites),
            "limit":       daily_limit,
            "auto_count":  auto_count,
            "extra_count": extra_count,
            "full":        len(sites) >= daily_limit,
        })

    archived_count = len(db_websites.get_archived())
    return jsonify({"ok": True, "days": days, "total": len(all_sites),
                    "archived_count": archived_count})


@app.route("/api/websites/archived")
def api_websites_archived():
    """Archivierte Websites — für den 'Alte Webseiten'-Bereich."""
    import time as _time
    daily_limit = int(os.environ.get("JARVIS_DAILY_SITES", "7") or "7")
    sites = db_websites.get_archived()

    for s in sites:
        ts = s.get("created") or 0
        s["build_date"] = _time.strftime("%Y-%m-%d", _time.localtime(ts)) if ts else "unbekannt"

    # Nach Datum gruppieren
    days_dict: dict = {}
    for s in sites:
        days_dict.setdefault(s["build_date"], []).append(s)

    days = []
    for d in sorted(days_dict.keys(), reverse=True):
        day_sites = days_dict[d]
        days.append({
            "date":       d,
            "sites":      day_sites,
            "count":      len(day_sites),
            "limit":      daily_limit,
        })

    return jsonify({"ok": True, "days": days, "total": len(sites)})


@app.route("/api/websites/archive_all", methods=["POST"])
def api_websites_archive_all():
    """Archiviert alle aktiven Seiten und startet optional den Night-Builder neu."""
    n = db_websites.archive_all()
    _logger.info("Dashboard", f"{n} Webseite(n) archiviert")

    # Night-Builder optional neu starten
    start_builder = request.json.get("start_builder", False) if request.is_json else False
    builder_started = False
    if start_builder:
        try:
            import auto_builder as _ab
            if not _ab.is_running():
                _ab.start()
                builder_started = True
        except Exception:
            pass

    return jsonify({"ok": True, "archived": n, "builder_started": builder_started})


def _website_added_dir(row: dict) -> "Path | None":
    """Sicherer Pfad zum 'added'-Bilderordner einer gebauten Seite (oder None)."""
    folder = (row or {}).get("folder") or ""
    if not folder:
        return None
    base = Path(folder)
    if not base.exists():
        return None
    return base / "static" / "img" / "added"


@app.route("/api/websites/<int:wid>/image", methods=["POST"])
def api_website_add_image(wid):
    """Lädt ein Bild zu einer gebauten Seite hoch (für späteren Einsatz)."""
    from werkzeug.utils import secure_filename
    row = db_websites.get(wid)
    if not row:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    added = _website_added_dir(row)
    if added is None:
        return jsonify({"ok": False, "reason": "Ordner noch nicht bereit"}), 409
    if "image" not in request.files:
        return jsonify({"ok": False, "reason": "Keine Datei (Feld 'image')"}), 400
    f = request.files["image"]
    safe = secure_filename(f.filename or "")
    if not safe:
        return jsonify({"ok": False, "reason": "Ungültiger Dateiname"}), 400
    added.mkdir(parents=True, exist_ok=True)
    ziel = added / safe
    if ziel.exists():                      # Kollision → Zahl anhängen
        stem, suf = ziel.stem, ziel.suffix
        for i in range(2, 9999):
            cand = added / f"{stem}-{i}{suf}"
            if not cand.exists():
                ziel, safe = cand, cand.name
                break
    f.save(str(ziel))
    # In Supabase-Storage laden → öffentliche URL (cross-PC sichtbar); sonst lokaler Name.
    bild_ref = safe
    try:
        import cloud_sync_websites
        url = cloud_sync_websites.upload_image(
            row.get("name", ""), row.get("stadt", ""), safe,
            ziel.read_bytes(), f.mimetype or "image/png")
        if url:
            bild_ref = url
    except Exception:
        pass
    updated = db_websites.add_image(wid, bild_ref)
    try:
        import cloud_sync_websites
        if updated:
            cloud_sync_websites.push(updated)
    except Exception:
        pass
    return jsonify({"ok": True, "website": updated})


def _website_teardown_remote(row: dict) -> list:
    """GitHub-Repo + Railway-Service einer Seite abbauen (best-effort). Gibt report-Liste."""
    report = []
    repo = (row.get("repo_url") or "").strip()
    if not repo:
        return report
    full = repo.split("github.com/", 1)[-1].strip("/").removesuffix(".git")
    if "/" not in full:
        return report
    try:
        import agent_github
        gr = agent_github.delete_repo(full)
        report.append("GitHub-Repo gelöscht" if gr.get("ok")
                      else f"GitHub: {gr.get('error', '')[:60]}")
    except Exception as e:
        report.append(f"GitHub-Fehler: {type(e).__name__}")
    try:
        import agent_railway
        svc = full.split("/")[-1]                 # Service-Name = Repo-Name (web-<slug>)
        rr = agent_railway.service_delete_by_name(svc)
        report.append("Railway-Service gelöscht" if rr.get("ok")
                      else f"Railway: {rr.get('error', '')[:60]}")
    except Exception as e:
        report.append(f"Railway-Fehler: {type(e).__name__}")
    return report


def _mark_lead_done(row: dict) -> bool:
    """Markiert den zur Webseite gehörenden Lead in db_evaluated als erledigt/archiviert,
    damit der Night-Builder ihn NICHT erneut baut (verhindert die wiederkehrenden Doppelten).
    Match: zuerst per lead_id MIT Namensprüfung (lead_id kann eine raw_id sein → sonst falscher
    Lead), sonst per lead_key bzw. Name+Stadt. Best-effort, wirft nie."""
    try:
        import db_evaluated
    except Exception:
        return False
    name  = (row.get("name") or "").strip()
    stadt = (row.get("stadt") or "").strip()
    if not name:
        return False
    target = None
    try:
        lid = row.get("lead_id")
        if lid:
            cand = db_evaluated.get_by_id(int(lid))
            if cand and (cand.get("name") or "").strip().lower() == name.lower():
                target = cand                     # exakter Treffer, Name passt → sicher
    except Exception:
        target = None
    if target is None:
        try:
            from leadkey import lead_key as _lk
            lk = _lk(name, stadt)
            for r in db_evaluated.get_all(limit=2000):
                if (lk and r.get("lead_key") == lk) or (
                        (r.get("name") or "").strip().lower() == name.lower()
                        and (r.get("stadt") or "").strip().lower() == stadt.lower()):
                    target = r
                    break
        except Exception:
            target = None
    if not target:
        return False
    try:
        db_evaluated.archive_lead(int(target["id"]), "Webseite gelöscht — Lead erledigt")
        return True
    except Exception:
        return False


def _website_delete_local(row: dict, del_folder: bool = True) -> list:
    """Lokalen Ordner (nur sichere web_-Ordner) + Cloud-Eintrag + DB-Zeile entfernen. Schnell.
    Markiert zusätzlich den zugehörigen Lead als erledigt (kein Re-Build → keine Doppelten)."""
    import shutil
    report = []
    folder = (row.get("folder") or "").strip()
    if del_folder and folder:
        try:
            p = Path(folder).resolve()
            if p.is_dir() and p.name.lower().startswith("web"):
                shutil.rmtree(p, ignore_errors=True)
                report.append("Ordner gelöscht")
            else:
                report.append("Ordner übersprungen (unsicherer Pfad)")
        except Exception as e:
            report.append(f"Ordner-Fehler: {type(e).__name__}")
    try:
        import cloud_sync_websites
        cloud_sync_websites.delete_remote(row.get("name", ""), row.get("stadt", ""))
    except Exception:
        pass
    db_websites.delete(row["id"])
    report.append("Eintrag entfernt")
    # Lead als erledigt markieren → der Night-Builder baut ihn nicht erneut (keine Doppelten).
    if _mark_lead_done(row):
        report.append("Lead als erledigt markiert")
    return report


@app.route("/api/websites/<int:wid>", methods=["DELETE"])
def api_website_delete(wid):
    """Löscht eine generierte Webseite: DB-Eintrag immer; lokalen Ordner (folder=1)
    und remote GitHub-Repo + Railway-Service (remote=1) best-effort."""
    row = db_websites.get(wid)
    if not row:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    del_folder = request.args.get("folder", "1") not in ("0", "false", "no")
    del_remote = request.args.get("remote", "0") in ("1", "true", "yes")
    report = []
    if del_remote:
        report += _website_teardown_remote(row)
    report += _website_delete_local(row, del_folder)
    return jsonify({"ok": True, "report": report})


@app.route("/api/websites/day/<date>", methods=["DELETE"])
def api_websites_delete_day(date):
    """Löscht ALLE Seiten EINES Bautags in einem Rutsch. Lokale Ordner + DB-Einträge werden
    sofort entfernt (UI aktualisiert sofort); der langsamere GitHub+Railway-Abbau (remote=1,
    Default an) läuft im Hintergrund, damit der Request nicht hängt."""
    import time as _time
    import threading
    del_folder = request.args.get("folder", "1") not in ("0", "false", "no")
    del_remote = request.args.get("remote", "1") not in ("0", "false", "no")   # Default: Railway weg

    targets = []
    for s in db_websites.get_all():                 # aktive (nicht archivierte) Seiten = was angezeigt wird
        ts = s.get("created") or 0
        bd = _time.strftime("%Y-%m-%d", _time.localtime(ts)) if ts else "unbekannt"
        if bd == date:
            targets.append(s)
    if not targets:
        return jsonify({"ok": False, "reason": "no_sites"}), 404

    # Für den Hintergrund-Abbau eine Kopie der Remote-Infos sichern, BEVOR die Zeilen weg sind.
    remote_rows = [dict(s) for s in targets] if del_remote else []
    # Lokal + DB sofort entfernen.
    for s in targets:
        try:
            _website_delete_local(s, del_folder)
        except Exception:
            pass
    # GitHub + Railway im Hintergrund abbauen (kann je Seite 1-3 s dauern).
    if remote_rows:
        def _bg():
            for r in remote_rows:
                try:
                    rep = _website_teardown_remote(r)
                    _logger.info("Websites", f"Tag {date}: {r.get('name','?')} → {', '.join(rep) or 'kein Remote'}")
                except Exception as e:
                    _logger.warn("Websites", f"Remote-Abbau {r.get('name','?')}: {type(e).__name__}")
            _logger.success("Websites", f"Tag {date}: Railway/GitHub-Abbau abgeschlossen ({len(remote_rows)} Seiten).")
        threading.Thread(target=_bg, name="DayTeardown", daemon=True).start()

    return jsonify({"ok": True, "deleted": len(targets),
                    "remote": "im Hintergrund" if remote_rows else "übersprungen"})


@app.route("/api/websites/<int:wid>/asset/<path:fname>")
def api_website_asset(wid, fname):
    """Liefert ein hinzugefügtes Bild einer Seite aus (Thumbnail-Vorschau)."""
    row = db_websites.get(wid)
    added = _website_added_dir(row) if row else None
    if added is None:
        return ("", 404)
    ziel = (added / fname)
    # Path-Traversal verhindern: realer Pfad MUSS im added-Ordner liegen.
    base_real = os.path.realpath(str(added))
    ziel_real = os.path.realpath(str(ziel))
    if not (ziel_real == base_real or ziel_real.startswith(base_real + os.sep)):
        return ("", 404)
    if not os.path.isfile(ziel_real):
        return ("", 404)
    return send_from_directory(base_real, os.path.basename(ziel_real))


@app.route("/api/websites/<int:wid>/improve", methods=["POST"])
def api_website_improve(wid):
    """'Top verbessern': mehrstufiges Skill-Makeover (7 Stufen, design-pro/taste/
    frontend-design) — Commit je Stufe, Deploy am Ende, Discord-Freigabe wenn komplett.
    Läuft als Hintergrund-Job (Fortschritt im Webseiten-Reiter)."""
    import website_builder
    row = db_websites.get(wid)
    if not row:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    folder = (row.get("folder") or "").strip()
    if not folder or not os.path.isdir(folder):
        return jsonify({"ok": False, "reason": "Ordner nicht gefunden"}), 409
    job_id = website_builder.makeover_existing(folder, row.get("name") or None)
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/websites/<int:wid>/chat", methods=["POST"])
def api_website_chat(wid):
    """Mit Claude debuggen/verbessern: freie Anweisung → Antwort und/oder Änderung
    an content.json; bei Änderung wird die Seite neu deployt."""
    import website_improve
    import website_builder
    row = db_websites.get(wid)
    if not row:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    folder = (row.get("folder") or "").strip()
    if not folder or not os.path.isdir(folder):
        return jsonify({"ok": False, "reason": "Ordner nicht gefunden"}), 409
    instruction = ((request.get_json(silent=True) or {}).get("instruction") or "").strip()
    if not instruction:
        return jsonify({"ok": False, "reason": "Keine Anweisung"}), 400
    res = website_improve.chat_edit(folder, instruction)
    job_id = ""
    if res.get("ok") and res.get("changed"):
        job_id = website_builder.deploy_existing(folder, row.get("name") or None)
    return jsonify({"ok": bool(res.get("ok")), "answer": res.get("answer", ""),
                    "changed": bool(res.get("changed")), "job_id": job_id})


@app.route("/api/websites/<int:wid>/integrate", methods=["POST"])
def api_website_integrate(wid):
    """Baut Nutzer-Texte + die hochgeladenen Bilder per Claude sinnvoll in die Seite
    ein und deployt neu. Body {text}."""
    import website_improve
    import website_builder
    row = db_websites.get(wid)
    if not row:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    folder = (row.get("folder") or "").strip()
    if not folder or not os.path.isdir(folder):
        return jsonify({"ok": False, "reason": "Ordner nicht gefunden"}), 409
    text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
    # Hochgeladene Bilder als /static/-Pfade (so referenziert die deployte Seite sie)
    added = Path(folder) / "static" / "img" / "added"
    image_paths = []
    if added.is_dir():
        for f in sorted(added.iterdir()):
            if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                image_paths.append(f"/static/img/added/{f.name}")
    res = website_improve.integrate(folder, text, image_paths)
    job_id = ""
    if res.get("ok") and res.get("changed"):
        job_id = website_builder.deploy_existing(folder, row.get("name") or None)
    return jsonify({"ok": bool(res.get("ok")), "answer": res.get("answer", ""),
                    "changed": bool(res.get("changed")), "job_id": job_id,
                    "images_used": len(image_paths)})


@app.route("/api/websites/<int:wid>/find-contact", methods=["POST"])
def api_website_find_contact(wid):
    """Sucht aktiv die Kontakt-E-Mail des Betriebs (DDG→Impressum / Google Places)
    und speichert sie an der Webseiten-Zeile. Für den 'Kontakt finden'-Button."""
    import contact_finder
    row = db_websites.get(wid)
    if not row:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    res = contact_finder.find(row.get("name", ""), row.get("stadt", ""), row.get("branche", ""))
    if res.get("ok") and res.get("email"):
        db_websites.set_contact(wid, res["email"], res.get("ansprechpartner", ""))
        return jsonify({"ok": True, "email": res["email"],
                        "ansprechpartner": res.get("ansprechpartner", ""),
                        "website": res.get("website", "")})
    return jsonify({"ok": False, "reason": "Keine öffentliche Kontaktadresse gefunden.",
                    "website": res.get("website", "")})


@app.route("/api/websites/<int:wid>/offer-email/preview")
def api_website_offer_email_preview(wid):
    """Vorschau der Angebots-Mail: gerenderte Mail + Empfänger + Live-Link inkl.
    Erreichbarkeits-Check (damit man sieht, dass der Link wirklich funktioniert)."""
    import offer_mail
    row = db_websites.get(wid)
    if not row:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    name    = row.get("name") or "Ihr Betrieb"
    link    = (row.get("live_url") or "").strip()
    betreff, _text, html = offer_mail.build(name, link, row.get("branche", ""),
                                            row.get("stadt", ""), row.get("ansprechpartner", ""))
    norm_link = offer_mail._norm_url(link)
    # Schneller Erreichbarkeits-Check (kurzer Timeout — blockiert die UI nicht lange).
    link_ok = False
    if norm_link:
        try:
            import urllib.request
            req = urllib.request.Request(norm_link, method="GET",
                                         headers={"User-Agent": "JARVIS-LinkCheck"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                link_ok = resp.status < 500
        except Exception as e:
            link_ok = getattr(e, "code", 500) < 500   # 200/301/404 = erreichbar
    return jsonify({"ok": True, "to": row.get("kontakt_email", ""), "betreff": betreff,
                    "html": html, "link": norm_link, "link_ok": bool(link_ok)})


@app.route("/api/websites/<int:wid>/offer-email", methods=["POST"])
def api_website_offer_email(wid):
    """Sendet die designte Angebots-Mail (350 €). Body {mode}:
       'test' → an Bastian (zum Testen);  'real' → an die gefundene Kontaktadresse."""
    import mailer
    row = db_websites.get(wid)
    if not row:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    mode = ((request.get_json(silent=True) or {}).get("mode") or "test").strip().lower()
    name = row.get("name") or "Ihr Betrieb"
    # NUR der echte Live-Link taugt als Webseiten-CTA — ein GitHub-Repo-Link ist
    # keine ansehbare Seite. offer_mail rendert bei leerem Link sauber ohne Button.
    link = (row.get("live_url") or "").strip()
    ansprechpartner = (row.get("ansprechpartner") or "").strip()

    if mode == "real":
        to = (row.get("kontakt_email") or "").strip()
        if "@" not in to:
            # Letzte Chance: jetzt aktiv suchen, statt nur abzulehnen.
            try:
                import contact_finder
                res = contact_finder.find(name, row.get("stadt", ""), row.get("branche", ""))
                if res.get("ok") and res.get("email"):
                    to = res["email"]
                    ansprechpartner = ansprechpartner or res.get("ansprechpartner", "")
                    db_websites.set_contact(wid, to, ansprechpartner)
            except Exception:
                pass
        if "@" not in to:
            return jsonify({"ok": False, "reason": "Keine Kontakt-E-Mail gefunden — "
                            "über 'Kontakt finden' suchen oder manuell ergänzen."}), 400
    else:
        to = "bastian.scherzinger05@gmail.com"        # Testempfänger

    betreff, text, html = _build_offer_email(name, link, row.get("branche", ""),
                                             row.get("stadt", ""), ansprechpartner)
    # Bewusste, vom Nutzer ausgelöste Sendung → Redirect umgehen (echter Empfänger).
    res = mailer.send_email(to, betreff, text, html=html, bypass_redirect=True)
    out = {"ok": bool(res.get("ok")), "status": res.get("status", ""),
           "reason": res.get("fehler", ""), "to": to, "mode": mode}
    if res.get("status") == "deaktiviert":
        out["hinweis"] = "Versand aus: setze JARVIS_EMAIL_ENABLED=true in der .env."
    elif "Auth" in str(res.get("fehler", "")):
        out["hinweis"] = ("Gmail lehnt die Anmeldung ab. App-Passwort gehört zum SMTP_USER? "
                          "Neues unter myaccount.google.com → Sicherheit → App-Passwörter.")
    return jsonify(out)


def _build_offer_email(name: str, link: str, branche: str = "", stadt: str = "",
                       ansprechpartner: str = "") -> tuple:
    """Designte Angebots-Mail (350 €) — Logik in offer_mail.py (geteilt mit auto_builder)."""
    import offer_mail
    return offer_mail.build(name, link, branche, stadt, ansprechpartner)


@app.route("/api/lead/<int:lead_id>/competition")
def api_lead_competition(lead_id):
    lead = _feed_lead(lead_id)
    if not lead:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    return jsonify(db_raw.get_competition(lead.get("stadt", ""), lead.get("branche", "")))


@app.route("/api/verifier/model", methods=["GET", "POST"])
def api_verifier_model():
    if request.method == "POST":
        body  = request.get_json(silent=True) or {}
        model = (body.get("model") or "").strip()
        if not model:
            return jsonify({"ok": False, "reason": "no_model"}), 400
        controller.set_verifier_model(model)
        return jsonify({"ok": True, "model": model})
    return jsonify({
        "model":     controller.get_verifier_model(),
        "available": _http.ollama_models(),
    })


# ── Evaluator-DB (DB2: leads_evaluated) ──────────────────────────────────────

@app.route("/api/evaluated/top")
def api_eval_top():
    return jsonify({"top": db_evaluated.get_top(10)})


@app.route("/api/evaluated/all")
def api_eval_all():
    limit      = int(request.args.get("limit", 200))
    offset     = int(request.args.get("offset", 0))
    branche    = request.args.get("branche")
    bundesland = request.args.get("bundesland")
    lead_typ   = request.args.get("lead_typ")
    sort       = request.args.get("sort", "score")
    suche      = request.args.get("suche", "")
    return jsonify(db_evaluated.get_all(
        limit, offset, branche, bundesland, lead_typ, sort, suche
    ))


@app.route("/api/evaluated/reeval", methods=["POST"])
def api_eval_reeval():
    # Setzt alle Leads auf 'pending' UND startet den Evaluator (auch ohne Scraper).
    n = controller.reevaluate_all()
    return jsonify({"ok": True, "requeued": n})


@app.route("/api/clear", methods=["POST"])
def api_clear():
    """Stoppt die Worker und leert ALLE drei Datenbanken komplett."""
    controller.stop()
    geloescht = {
        "raw":       db_raw.clear_all(),
        "evaluated": db_evaluated.clear_all(),
    }
    return jsonify({"ok": True, "geloescht": geloescht})


@app.route("/api/evaluated/stats")
def api_eval_stats():
    return jsonify(db_evaluated.get_stats())


@app.route("/api/evaluated/<int:eval_id>/status", methods=["POST"])
def api_eval_status(eval_id):
    body   = request.get_json(silent=True) or {}
    status = body.get("status", "")
    VALID  = {"neu", "kontaktiert", "termin", "verkauft", "tot"}
    if status not in VALID:
        return jsonify({"error": f"Ungültig. Erlaubt: {VALID}"}), 400
    db_evaluated.update_status(eval_id, status)
    return jsonify({"ok": True})


@app.route("/api/voice/status")
def api_voice_status():
    import voice_web
    return jsonify(voice_web.status())


@app.route("/api/voice/transcribe", methods=["POST"])
def api_voice_transcribe():
    """Audio (MediaRecorder, webm/opus) → Text via faster-whisper."""
    import voice_web
    if "audio" in request.files:
        data = request.files["audio"].read()
    else:
        data = request.get_data() or b""
    if not data:
        return jsonify({"ok": False, "reason": "no_audio"}), 400
    if len(data) > 5 * 1024 * 1024:   # ~5 Min Opus — schützt vor langer CPU-Blockade
        return jsonify({"ok": False, "reason": "too_large"}), 413
    try:
        text = voice_web.transcribe(data)
        return jsonify({"ok": True, "text": text})
    except Exception as e:
        return jsonify({"ok": False, "reason": f"{type(e).__name__}: {str(e)[:160]}"}), 500


@app.route("/api/voice/speak", methods=["POST"])
def api_voice_speak():
    """Text → gesprochenes Audio (MP3/WAV) via edge-tts."""
    import voice_web
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "reason": "no_text"}), 400
    try:
        audio, mime = voice_web.speak(text)
        return Response(audio, mimetype=mime,
                        headers={"Cache-Control": "no-store"})
    except Exception as e:
        return jsonify({"ok": False, "reason": f"{type(e).__name__}: {str(e)[:160]}"}), 500


@app.route("/api/claude/status")
def api_claude_status():
    """Ist der Claude-Chat einsatzbereit (API-Key vorhanden)? + Token-Budget der Session."""
    import claude_chat
    import metrics
    return jsonify({"ready": claude_chat.is_ready(), "model": claude_chat.MODEL,
                    "usage": metrics.budget_status()})


@app.route("/api/claude/limit")
def api_claude_limit():
    """Claude-Limit-Status (Session/Weekly, Prozent) + Mehrfach-Key-Übersicht fürs Dashboard."""
    try:
        import claude_limit
        return jsonify({"ok": True, **claude_limit.status()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:120]}), 500


@app.route("/api/claude/reset", methods=["POST"])
def api_claude_reset():
    """„Nochmal testen": hebt das Limit-Zeichen auf, startet das Token-Fenster frisch und gibt
    alle erschöpften Keys wieder frei (manueller Retry-Knopf)."""
    out = {}
    try:
        import claude_limit
        claude_limit.reset()
        out["limit"] = "reset"
    except Exception:
        pass
    try:
        import claude_keys
        claude_keys.reset()
        out["keys"] = "reset"
    except Exception:
        pass
    return jsonify({"ok": True, **out})


@app.route("/api/metrics")
def api_metrics():
    """Observability: Claude-Token-Verbrauch + Tool-Latenzen/Fehlerraten."""
    import metrics
    return jsonify(metrics.snapshot())


@app.route("/api/claude/chat", methods=["POST"])
def api_claude_chat():
    """Streamt eine Claude-Antwort als SSE. Body: {messages:[...], think?, search?}."""
    import claude_chat
    body     = request.get_json(silent=True) or {}
    messages = body.get("messages") or []
    if not isinstance(messages, list) or not messages:
        return jsonify({"ok": False, "reason": "no_messages"}), 400
    think  = bool(body.get("think"))
    search = bool(body.get("search"))

    def event_stream():
        try:
            for chunk in claude_chat.stream_chat(messages, think=think, search=search):
                if "_error" in chunk:
                    yield _sse({"type": "error", "msg": chunk["_error"]})
                elif "tool" in chunk:
                    yield _sse({"type": "tool", "name": chunk["tool"], "input": chunk.get("input", {})})
                elif "tool_result" in chunk:
                    yield _sse({"type": "tool_result", "text": chunk["tool_result"]})
                elif "text" in chunk:
                    yield _sse({"type": "token", "text": chunk["text"]})
        except Exception as e:
            yield _sse({"type": "error", "msg": f"{type(e).__name__}"})
        yield _sse({"type": "done"})

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )


@app.route("/api/email/status")
def api_email_status():
    """Versand-Bereitschaft fürs Dashboard (ist Auto-Mail scharf?)."""
    import mailer
    return jsonify(mailer.status())


@app.route("/api/lead/<int:eval_id>/send-email", methods=["POST"])
def api_lead_send_email(eval_id):
    """Versendet eine E-Mail an einen bewerteten Lead (DB2). Trockenlauf, solange
    JARVIS_EMAIL_ENABLED != true. Aktualisiert email_status + spiegelt in die Cloud."""
    import mailer
    lead = db_evaluated.get_by_id(eval_id)
    if not lead:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    res = mailer.send_to_lead(lead)
    db_evaluated.set_email_status(eval_id, res.get("status", "fehler"), res.get("fehler", ""))
    try:
        cloud_sync.push_lead(db_evaluated.get_by_id(eval_id))
    except Exception:
        pass
    return jsonify(res), (200 if res.get("ok") else 400)


@app.route("/api/lead/<int:eval_id>/opt-out", methods=["POST"])
def api_lead_opt_out(eval_id):
    """Markiert einen Lead als Opt-out (kein Versand mehr)."""
    db_evaluated.set_opt_out(eval_id, 1)
    db_evaluated.set_email_status(eval_id, "opt_out", "")
    return jsonify({"ok": True})


@app.route("/abmelden", methods=["GET", "POST"])
def abmelden():
    """Öffentlicher Abmelde-Endpunkt für die Angebots-Mails (UWG/DSGVO + List-Unsubscribe).
    Aufruf per Klick (GET) oder Ein-Klick-POST (RFC 8058). Token verhindert Fremd-Abmeldung."""
    import email_suppress
    email = (request.values.get("e") or "").strip()
    token = (request.values.get("t") or "").strip()
    ok = bool(email) and email_suppress.verify(email, token)
    if ok:
        email_suppress.suppress(email, quelle=("one-click" if request.method == "POST" else "link"))
    if request.method == "POST":
        # List-Unsubscribe-Post erwartet nur einen 200er, keine Seite.
        return ("", 200) if ok else ("", 400)
    msg = ("Sie wurden erfolgreich abgemeldet. Sie erhalten keine weiteren Nachrichten von uns."
           if ok else "Abmeldelink ungültig oder abgelaufen. Bitte antworten Sie der Mail mit \"STOP\".")
    html = (f"<!doctype html><html lang=de><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>Abmeldung</title></head>"
            f"<body style='font-family:system-ui,Segoe UI,sans-serif;background:#f4f6f9;margin:0;"
            f"display:flex;min-height:100vh;align-items:center;justify-content:center'>"
            f"<div style='background:#fff;max-width:460px;padding:36px 32px;border-radius:16px;"
            f"box-shadow:0 12px 40px rgba(0,0,0,.1);text-align:center'>"
            f"<div style='font-size:40px'>{'✓' if ok else '⚠'}</div>"
            f"<h1 style='font-size:20px;margin:12px 0 8px;color:#16314f'>"
            f"{'Abgemeldet' if ok else 'Abmeldung fehlgeschlagen'}</h1>"
            f"<p style='color:#5c6b7a;font-size:15px;line-height:1.6'>{msg}</p></div></body></html>")
    return Response(html, mimetype="text/html"), (200 if ok else 400)




@app.route("/api/sync", methods=["GET", "POST"])
def api_sync():
    """GET: Sync-Status. POST: manueller Sync-Trigger (body: {full: true/false})."""
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        full = bool(body.get("full", False))
        result = cloud_sync.sync_once(full=full)
        return jsonify(result)
    return jsonify({
        "configured": cloud_sync.is_configured(),
        "interval_s": cloud_sync.SYNC_INTERVAL,
        "table":      cloud_sync._TABLE,
    })


@app.route("/api/graph/nodes")
def api_graph_nodes():
    limit  = min(int(request.args.get("limit", 2000)), 5000)
    offset = max(int(request.args.get("offset", 0)), 0)
    min_id = max(int(request.args.get("min_id", 0)), 0)
    return jsonify({"nodes": db_evaluated.get_for_graph(limit, offset, min_id)})


@app.route("/api/graph/stats")
def api_graph_stats():
    return jsonify(db_evaluated.get_graph_stats())


@app.route("/api/graph/locations")
def api_graph_locations():
    """Aggregierte Lead-Standorte (Stadt) für den 3D-Globus."""
    return jsonify({"locations": db_evaluated.get_locations()})


@app.route("/api/graph/leadpoints")
def api_graph_leadpoints():
    """Adressgenaue (geocodete) Lead-Punkte für den 3D-Globus — beim Zoom sitzt jeder
    Marker exakt am Betrieb. Liefert sofort den Cache + füllt fehlende im Hintergrund."""
    try:
        import geo_cache
        return jsonify(geo_cache.points())
    except Exception as e:
        return jsonify({"points": [], "pending": 0, "error": type(e).__name__})


# ── Auto-Website-Builder ─────────────────────────────────────────────────────

@app.route("/api/auto-build/start", methods=["POST"])
def api_autobuild_start():
    import auto_builder
    return jsonify(auto_builder.start())


@app.route("/api/auto-build/stop", methods=["POST"])
def api_autobuild_stop():
    import auto_builder
    return jsonify(auto_builder.stop())


@app.route("/api/auto-build/status")
def api_autobuild_status():
    import auto_builder
    return jsonify(auto_builder.status())


@app.route("/api/auto-build/daily")
def api_autobuild_daily():
    """Tages-Historie: welche Seiten an welchem Tag gebaut wurden."""
    import auto_builder
    return jsonify(auto_builder.daily_log())


@app.route("/api/auto-build/scaling")
def api_autobuild_scaling():
    """Skalierungs-Empfehlung (Hochskalieren): aktive vs. hardware-empfohlene
    Sessions/Seiten/lokale Parallelität."""
    import auto_builder
    return jsonify(auto_builder.scaling_info())


# ── Eigene Marke (Custom-Build) ───────────────────────────────────────────────

@app.route("/api/custom-build", methods=["POST"])
def api_custom_build():
    """Manueller Build: Name/Logo/Hero/Beschreibung von Sir vorgegeben. Akzeptiert
    multipart (mit Datei-Uploads) oder JSON."""
    import custom_build
    f = request.form if request.form else {}
    name = (f.get("name") or "").strip()
    if not name and request.is_json:
        f = request.get_json(silent=True) or {}
        name = (f.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "reason": "Name fehlt"}), 400

    slug = custom_build._slugify(name)
    logo_path = custom_build.save_upload(request.files.get("logo"), "logo", slug)
    hero_path = custom_build.save_upload(request.files.get("hero"), "hero", slug)

    # Empfänger: aus Textarea (eine Adresse pro Zeile/Komma/Semikolon).
    roh = f.get("recipients") or ""
    if isinstance(roh, list):
        recipients = roh
    else:
        recipients = [x for x in __import__("re").split(r"[\n,;]+", str(roh)) if x.strip()]

    data = {
        "name": name, "branche": f.get("branche", ""), "stadt": f.get("stadt", ""),
        "beschreibung": f.get("beschreibung", ""), "telefon": f.get("telefon", ""),
        "email": f.get("email", ""), "adresse": f.get("adresse", ""),
        "hero_prompt": f.get("hero_prompt", ""),
        "logo_path": logo_path, "hero_path": hero_path, "recipients": recipients,
    }
    return jsonify(custom_build.start(data))


@app.route("/api/custom-build/status/<job_id>")
def api_custom_build_status(job_id):
    import custom_build
    return jsonify(custom_build.status(job_id))


@app.route("/api/custom-build/improve", methods=["POST"])
def api_custom_build_improve():
    """Schritt 2: 7-Stufen-Skill-Makeover für die bereits gebaute Eigene-Marke-Seite
    (wiederholbar)."""
    import custom_build
    body = request.get_json(silent=True) or {}
    job_id = (body.get("job_id") or "").strip()
    if not job_id:
        return jsonify({"ok": False, "reason": "job_id fehlt"}), 400
    return jsonify(custom_build.improve(job_id))


@app.route("/api/custom-build/suggest", methods=["POST"])
def api_custom_build_suggest():
    """KI-Vorschläge (Beschreibung, Branche, Tagline, Hero-Prompt, Leistungen) für die
    Marke — lokal via Ollama, mit deterministischem Fallback."""
    import custom_build
    body = request.get_json(silent=True) or {}
    return jsonify(custom_build.suggest({
        "name": body.get("name", ""), "branche": body.get("branche", ""),
        "stadt": body.get("stadt", ""), "beschreibung": body.get("beschreibung", ""),
    }))


# ── Discord-Freigabe (Voting-Gate) ───────────────────────────────────────────

@app.route("/api/discord/status")
def api_discord_status():
    import discord_bot
    return jsonify(discord_bot.status())


@app.route("/api/discord/send-now", methods=["POST"])
def api_discord_send_now():
    """Versendet sofort alle freigegebenen Seiten (sonst automatisch um 12 Uhr)."""
    import discord_bot
    return jsonify(discord_bot.send_approved_now())


@app.route("/api/discord/channels")
def api_discord_channels():
    """Erreichbare Text-Kanäle des Bots (mit Server, ID, Sende-Recht) + der aktuell
    konfigurierte Kanal — Diagnose für „Unknown Channel"/falsche DISCORD_CHANNEL_ID."""
    import discord_bot
    chans = discord_bot.channels()
    cid = discord_bot._channel_id()
    return jsonify({"configured": cid,
                    "configured_ok": any(c["id"] == cid and c["can_send"] for c in chans),
                    "channels": chans})


@app.route("/api/reviews")
def api_reviews():
    """Aktuelle Freigabe-Warteschlange (für das Dashboard)."""
    import review_queue
    return jsonify({"reviews": review_queue.all(), "stats": review_queue.stats()})


@app.route("/api/perf")
def api_perf():
    """Aktuelles Leistungsprofil (Auto-Adapt CPU/GPU)."""
    try:
        import hardware_profile
        return jsonify({"ok": True, "profile": hardware_profile.profile(),
                        "summary": hardware_profile.summary()})
    except Exception as e:
        return jsonify({"ok": False, "reason": str(e)})


@app.route("/api/qa")
def api_qa():
    """Separates QA-/Security-/Upgrade-Verfahren (Bug-Check + Security-Scan + Deps)."""
    try:
        import qa_security
        return jsonify({"ok": True, **qa_security.run_all()})
    except Exception as e:
        return jsonify({"ok": False, "reason": str(e)})


@app.route("/api/media/generate/background", methods=["POST"])
def api_media_generate_background():
    """Generiert ein stimmiges Hintergrund-Bild (Iron-Man-HUD-Szene) lokal oder über
    Higgsfield und legt es als static/img/bg_custom.png ab (Frontend nutzt es dann)."""
    body    = request.get_json(silent=True) or {}
    backend = (body.get("backend") or "local").strip()
    prompt  = (body.get("prompt") or
               "cinematic futuristic high-tech command center, dark control room, holographic "
               "blue data displays, Iron Man JARVIS lab atmosphere, glowing arc-reactor light, "
               "depth of field, ultra detailed, 8k, no text, no people").strip()
    out_dir = Path(__file__).parent / "static" / "img"
    try:
        import media_engine
        if backend == "higgsfield":
            res = media_engine.generate_image_higgsfield(prompt, output_dir=out_dir,
                                                         filename="bg_custom.png", width=1920, height=1080)
        else:
            hp = media_engine.hero_image_params()
            res = media_engine.generate_image(prompt, output_dir=out_dir,
                                              filename="bg_custom.png", **{k: hp[k] for k in ("model_key", "steps") if k in hp})
        return jsonify({"ok": True, "url": "/static/img/bg_custom.png", "model": res.get("model", "")})
    except Exception as e:
        return jsonify({"ok": False, "reason": f"{type(e).__name__}: {str(e)[:160]}"})


@app.route("/api/logs")
def api_logs():
    limit   = int(request.args.get("limit", 150))
    since   = request.args.get("since", "")
    entries = _logger.get_since(since, limit) if since else _logger.get_recent(limit)
    last_ts = entries[-1]["ts"] if entries else ""
    return jsonify({"logs": entries, "last_ts": last_ts})


# ── Media: Bild/Video-Generierung ────────────────────────────────────────────

@app.route("/workspace/media/<path:fn>")
def serve_media(fn):
    # send_from_directory schützt selbst gegen Path-Traversal
    return send_from_directory(_MEDIA_DIR, fn)


@app.route("/api/media/status")
def api_media_status():
    try:
        import media_engine
        return jsonify(media_engine.get_status())
    except ImportError:
        return jsonify({
            "diffusers_ok":       False,
            "image_model":        "",
            "image_model_key":    "",
            "video_model":        "",
            "video_model_key":    "",
            "higgsfield_api_key": False,
        })


@app.route("/api/higgsfield/mcp/status")
def api_hf_mcp_status():
    """Status der Higgsfield-MCP-Anbindung (Abo-Credits via OAuth)."""
    try:
        import higgsfield_mcp
        return jsonify(higgsfield_mcp.login_status())
    except Exception as e:
        return jsonify({"authorized": False, "running": False, "url": "",
                        "error": f"{type(e).__name__}: {e}"})


@app.route("/api/higgsfield/mcp/login", methods=["POST"])
def api_hf_mcp_login():
    """Startet den einmaligen Browser-Login. Gibt sofort die Anmelde-URL zurück;
    der Token-Tausch läuft im Hintergrund. Danach nutzt JARVIS die Abo-Credits."""
    try:
        import higgsfield_mcp
        return jsonify(higgsfield_mcp.login_async())
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"})


@app.route("/api/higgsfield/mcp/logout", methods=["POST"])
def api_hf_mcp_logout():
    try:
        import higgsfield_mcp
        return jsonify(higgsfield_mcp.logout())
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"})


@app.route("/api/media/models")
def api_media_models():
    try:
        import media_engine
        return jsonify({
            "image":      media_engine.IMAGE_MODELS,
            "video":      media_engine.VIDEO_MODELS,
            "higgsfield": media_engine.HIGGSFIELD_MODELS,
        })
    except ImportError:
        return jsonify({"image": {}, "video": {}, "higgsfield": {}})


@app.route("/api/media/generate/image", methods=["POST"])
def api_media_generate_image():
    body    = request.get_json(silent=True) or {}
    prompt  = (body.get("prompt") or "").strip()
    backend = (body.get("backend") or "local").strip()
    if not prompt:
        return jsonify({"ok": False, "reason": "no_prompt"}), 400
    if len(prompt) > 1000:
        return jsonify({"ok": False, "reason": "prompt_too_long"}), 400
    if backend in ("higgsfield_mcp", "higgsfield_abo"):
        params = {"prompt": prompt, "aspect_ratio": (body.get("aspect_ratio") or "16:9").strip(),
                  "model": (body.get("hf_model") or "").strip()}
        job_id = media_queue.submit("higgsfield_mcp_image", params)
    elif backend == "higgsfield":
        params = {"prompt": prompt, "width": body.get("width"), "height": body.get("height")}
        job_id = media_queue.submit("higgsfield_image", params)
    elif backend == "openai":
        params = {"prompt": prompt,
                  "width": body.get("width") or 1536, "height": body.get("height") or 1024}
        job_id = media_queue.submit("openai_image", params)
    else:
        params = {
            "prompt":    prompt,
            "model_key": (body.get("model_key") or "").strip(),
            "steps":     body.get("steps", 25),
            "width":     body.get("width"),
            "height":    body.get("height"),
        }
        job_id = media_queue.submit("image", params)
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/media/generate/set", methods=["POST"])
def api_media_generate_set():
    """Werbe-Asset-Set: generiert pro Erstellung 5 verschiedene Assets —
    Logo, Website-Hero-Banner, Flyer, Werbeanzeige und Social-Media-Post,
    jeweils mit eigenem Prompt + Format."""
    import ad_prompts
    body  = request.get_json(silent=True) or {}
    brief = {
        "betrieb":    (body.get("betrieb") or "").strip(),
        "branche":    (body.get("branche") or "").strip(),
        "motiv":      (body.get("motiv") or "").strip(),
        "stil":       body.get("stil", ""),
        "stimmung":   body.get("stimmung", ""),
        "text_platz": body.get("text_platz", True),
    }
    assets  = ad_prompts.build_asset_set(brief)
    summary = " · ".join(filter(None, [brief["betrieb"] or None, brief["branche"] or None]))
    params  = {
        "assets":    assets,
        "model_key": (body.get("model_key") or "").strip(),
        "backend":   (body.get("backend") or "local").strip(),   # local | higgsfield
        "steps":     int(body.get("steps", 0)),   # 0 = Modell entscheidet (FLUX 4, SDXL 25)
        "summary":   summary,
        "lead_id":   body.get("lead_id"),
    }
    job_id = media_queue.submit("asset_set", params)
    return jsonify({
        "ok": True, "job_id": job_id, "count": len(assets),
        "assets": [a["label"] for a in assets], "summary": summary,
    })


@app.route("/api/media/generate/video", methods=["POST"])
def api_media_generate_video():
    body    = request.get_json(silent=True) or {}
    prompt  = (body.get("prompt") or "").strip()
    backend = (body.get("backend") or "local").strip()
    if not prompt:
        return jsonify({"ok": False, "reason": "no_prompt"}), 400
    if len(prompt) > 1000:
        return jsonify({"ok": False, "reason": "prompt_too_long"}), 400

    if backend in ("higgsfield_mcp", "higgsfield_abo"):
        params = {"prompt": prompt, "aspect_ratio": (body.get("aspect_ratio") or "16:9").strip(),
                  "model": (body.get("hf_model") or "").strip(),
                  "duration": body.get("duration") or 0}
        job_id = media_queue.submit("higgsfield_mcp_video", params)
    elif backend == "higgsfield":
        params = {"prompt": prompt, "hf_model": (body.get("hf_model") or "dop-lite").strip()}
        job_id = media_queue.submit("higgsfield", params)
    else:
        params = {
            "prompt":     prompt,
            "model_key":  (body.get("model_key") or "").strip(),
            "num_frames": body.get("num_frames", 25),
        }
        job_id = media_queue.submit("video", params)
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/media/generate/ad-video", methods=["POST"])
def api_media_generate_ad_video():
    """Werbevideo aus einem Brief (Betrieb/Branche/Motiv/Stil) — für Leads, fertige
    Webseiten oder frei. backend: 'local' (Wan) | 'higgsfield' (Cloud)."""
    import ad_prompts
    body    = request.get_json(silent=True) or {}
    brief = {
        "betrieb":  (body.get("betrieb") or "").strip(),
        "branche":  (body.get("branche") or "").strip(),
        "motiv":    (body.get("motiv") or "").strip(),
        "stil":     body.get("stil", "cinematisch"),
        "stimmung": body.get("stimmung", "professionell"),
    }
    if not (brief["betrieb"] or brief["branche"] or brief["motiv"]):
        return jsonify({"ok": False, "reason": "Bitte Betrieb, Branche oder Motiv angeben."}), 400
    vp = ad_prompts.build_video_prompt(brief)
    backend = (body.get("backend") or "local").strip()
    if backend in ("higgsfield_mcp", "higgsfield_abo"):
        params = {"prompt": vp["prompt"], "aspect_ratio": (body.get("aspect_ratio") or "16:9").strip(),
                  "model": (body.get("hf_model") or "").strip(),
                  "duration": body.get("duration") or 0, "summary": vp["summary"]}
        job_id = media_queue.submit("higgsfield_mcp_video", params)
    elif backend == "higgsfield":
        params = {"prompt": vp["prompt"], "hf_model": (body.get("hf_model") or "dop-lite").strip(),
                  "summary": vp["summary"]}
        job_id = media_queue.submit("higgsfield", params)
    else:
        params = {"prompt": vp["prompt"], "model_key": (body.get("model_key") or "").strip(),
                  "num_frames": int(body.get("num_frames", 25)), "summary": vp["summary"]}
        job_id = media_queue.submit("video", params)
    return jsonify({"ok": True, "job_id": job_id, "prompt": vp["prompt"], "summary": vp["summary"]})


@app.route("/api/media/job/<job_id>")
def api_media_job(job_id):
    job = media_queue.get(job_id)
    if job is None:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    return jsonify(job)


@app.route("/api/media/jobs")
def api_media_jobs():
    return jsonify({"jobs": media_queue.list_jobs()})


@app.route("/api/media/gallery")
def api_media_gallery():
    return jsonify(media_queue.gallery())


# ── Home-Tab ──────────────────────────────────────────────────────────────────

@app.route("/api/home/stats")
def api_home_stats():
    """Alle Webseiten + Kurzzusammenfassung für den Home-Tab."""
    import db_websites
    import auto_builder as _ab
    sites = db_websites.get_all()
    total    = len(sites)
    live     = sum(1 for s in sites if s.get("live"))
    building = sum(1 for s in sites if s.get("status") in ("queued", "running"))
    errors   = sum(1 for s in sites if s.get("status") == "error")
    sent     = sum(1 for s in sites if s.get("email_sent"))
    # Auto-Builder-Status
    ab = _ab.status()
    # Letzte 6 Seiten für die Home-Kacheln
    cards = []
    for s in sites[:6]:
        imgs = []
        try:
            imgs = json.loads(s.get("images") or "[]") if isinstance(s.get("images"), str) else (s.get("images") or [])
        except Exception:
            imgs = []
        cards.append({
            "id":         s.get("id"),
            "name":       s.get("name") or "–",
            "branche":    s.get("branche") or "",
            "stadt":      s.get("stadt") or "",
            "status":     s.get("status") or "unknown",
            "live":       bool(s.get("live")),
            "email_sent": bool(s.get("email_sent")),
            "live_url":   s.get("live_url") or "",
            "repo_url":   s.get("repo_url") or "",
            "thumbnail":  imgs[0] if imgs else "",
            "created":    s.get("created") or "",
            "updated":    s.get("updated") or "",
            "progress":   s.get("progress") or 0,
            "step":       s.get("step") or "",
        })
    return jsonify({
        "total": total, "live": live, "building": building, "errors": errors,
        "sent": sent, "sites": cards, "builder": ab,
    })


# ── Kosten-Tab ────────────────────────────────────────────────────────────────

@app.route("/api/costs/today")
def api_costs_today():
    """Kostenzusammenfassung für heute + Pro-Site-Aufschlüsselung."""
    try:
        import cost_tracker
        summary   = cost_tracker.today_summary()
        per_site  = cost_tracker.per_site_costs(20)
        events    = cost_tracker.recent_events(40)
        try:
            import claude_limit
            budget = claude_limit.status()
            fix    = claude_limit.costs()
        except Exception:
            budget, fix = {}, {}
        return jsonify({"ok": True, "summary": summary, "per_site": per_site,
                        "events": events, "claude_budget": budget, "fix_costs": fix})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "summary": {}, "per_site": [],
                        "events": [], "claude_budget": {}, "fix_costs": {}})


@app.route("/api/costs/history")
def api_costs_history():
    """Kosten der letzten 14 Tage als Zeitreihe für Chart.js."""
    try:
        import cost_tracker
        days = int(request.args.get("days", 14))
        return jsonify({"ok": True, "history": cost_tracker.history(days)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "history": []})


@app.route("/api/costs/export")
def api_costs_export():
    """Kostenhistorie als CSV-Datei zum Download (Semikolon-getrennt für Excel-DE)."""
    import csv
    import io
    import cost_tracker
    try:
        days = max(1, min(365, int(request.args.get("days", 30))))
    except ValueError:
        days = 30
    rows = cost_tracker.history(days)
    buf = io.StringIO()
    w   = csv.writer(buf, delimiter=";")
    w.writerow(["Datum", "Gesamt_EUR", "API_EUR", "Strom_EUR", "Higgsfield_EUR",
                "Tokens_Ein", "Tokens_Aus", "HF_Credits", "Seiten_gebaut", "Leads_bewertet"])
    for r in rows:
        w.writerow([r["date"], r["total_eur"], r["api_eur"], r["power_eur"], r["hf_eur"],
                    r["tokens_in"], r["tokens_out"], r["hf_credits"], r["sites"], r["leads"]])
    return Response(
        "﻿" + buf.getvalue(),   # BOM → Umlaute korrekt in Excel
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="jarvis_kosten_{days}d.csv"'},
    )


@app.route("/api/activity/recent")
def api_activity_recent():
    """Letzte Aktivitäten für den Live-Feed (Home + Kosten)."""
    try:
        limit = int(request.args.get("limit", 60))
        acts  = _logger.get_activities(limit)
        return jsonify({"ok": True, "activities": acts})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "activities": []})


@app.route("/api/stream")
def api_stream():
    q = controller.subscribe()   # eigene Queue pro Client (Fan-out)

    def event_stream():
      try:
        # Beim Verbinden: aktuelle DB-Stats schicken (verhindert Flickern)
        yield _sse({"type": "init_stats", "stats": _stats()})

        while True:
            try:
                lead = q.get(timeout=20)
            except queue.Empty:
                # Keepalive + aktualisierte Stats alle 20s
                yield _sse({"type": "stats", "stats": _stats()})
                continue

            if "_error" in lead:
                yield _sse({"type": "error", "msg": lead["_error"]})
                continue

            if "_activity" in lead:
                yield _sse({"type": "activity", "msg": lead["_activity"]})
                continue

            # Verifier-Events: Lead wurde nachverifiziert
            if lead.get("type") == "verified":
                yield _sse({
                    "type":  "verified",
                    "data":  lead["data"],
                    "stats": _stats(),
                })
                continue

            # Evaluator-Events: Roh-Lead wurde KI-bewertet (DB2)
            if lead.get("type") == "evaluated":
                yield _sse({"type": "evaluated", "data": lead["data"]})
                continue

            # Lead senden + gleichzeitig DB-Stats (single source of truth)
            yield _sse({"type": "lead", "data": lead, "stats": _stats()})
      finally:
        controller.unsubscribe(q)   # beim Trennen Client-Queue abmelden

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


def server_config() -> dict:
    """Server-Konfiguration aus der Umgebung (.env via config.load_dotenv).
      JARVIS_HOST   (Default 0.0.0.0)
      JARVIS_PORT / PORT  (Default 5000)
      JARVIS_THREADS  (Default = 2× CPU-Kerne, 8–32)
      JARVIS_SERVER / JARVIS_PROD  → Produktionsmodus (waitress statt Dev-Server)."""
    host = os.environ.get("JARVIS_HOST", "0.0.0.0")
    try:
        port = int(os.environ.get("JARVIS_PORT") or os.environ.get("PORT") or 5000)
    except ValueError:
        port = 5000
    try:
        threads = int(os.environ.get("JARVIS_THREADS") or 0)
    except ValueError:
        threads = 0
    if threads <= 0:
        threads = min(32, max(8, (os.cpu_count() or 4) * 2))
    prod = (os.environ.get("JARVIS_SERVER") or os.environ.get("JARVIS_PROD") or "").strip().lower() \
        in ("1", "true", "yes", "on", "prod", "production")
    return {"host": host, "port": port, "threads": threads, "prod": prod}


def run_server() -> None:
    """Startet den Server: im Produktionsmodus (JARVIS_SERVER=1) über waitress
    (robuster WSGI-Server, Windows-tauglich), sonst der Flask-Dev-Server.
    Fällt ohne waitress sauber auf den Dev-Server zurück."""
    cfg = server_config()
    if cfg["prod"]:
        try:
            from waitress import serve as _serve
            print(f"[JARVIS] Produktionsserver (waitress) auf http://{cfg['host']}:{cfg['port']} "
                  f"· {cfg['threads']} Threads", flush=True)
            _serve(app, host=cfg["host"], port=cfg["port"], threads=cfg["threads"],
                   channel_timeout=300, ident="JARVIS")
            return
        except ImportError:
            print("[JARVIS] waitress nicht installiert — Fallback auf Dev-Server "
                  "(pip install waitress für Produktion).", flush=True)
    app.run(host=cfg["host"], port=cfg["port"], debug=False, threaded=True)


if __name__ == "__main__":
    run_server()
