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


# Discord-Freigabe-Bot (Voting-Gate vor dem Kundenversand) — nur wenn konfiguriert.
def _start_discord():
    try:
        import discord_bot
        if discord_bot.enabled():
            discord_bot.start()
    except Exception:
        pass
_startup_t.Thread(target=_start_discord, daemon=True).start()

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
    return jsonify({
        "running": controller.is_running(),
        "stats":   _stats(),
        "workers": controller.worker_health(),   # echte Pro-Worker-Gesundheit
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
    """Websites gruppiert nach Bautag — für den Tages-Ordner-View."""
    import time as _time
    daily_limit = int(os.environ.get("JARVIS_DAILY_SITES", "10") or "10")
    today = _time.strftime("%Y-%m-%d")
    all_sites = db_websites.get_all()

    # build_date aus created-Timestamp ableiten
    for s in all_sites:
        ts = s.get("created") or 0
        s["build_date"] = _time.strftime("%Y-%m-%d", _time.localtime(ts)) if ts else "unbekannt"

    # Nach Datum gruppieren
    days_dict: dict = {}
    for s in all_sites:
        days_dict.setdefault(s["build_date"], []).append(s)

    days = []
    for d in sorted(days_dict.keys(), reverse=True):
        sites = days_dict[d]
        # Seiten die den Auto-Limit übersteigen sind Custom/Manual-Builds
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

    return jsonify({"ok": True, "days": days, "total": len(all_sites)})


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


@app.route("/api/websites/<int:wid>", methods=["DELETE"])
def api_website_delete(wid):
    """Löscht eine generierte Webseite: DB-Eintrag immer; lokalen Ordner (folder=1)
    und remote GitHub-Repo + Railway-Service (remote=1) best-effort."""
    import shutil
    row = db_websites.get(wid)
    if not row:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    del_folder = request.args.get("folder", "1") not in ("0", "false", "no")
    del_remote = request.args.get("remote", "0") in ("1", "true", "yes")
    report = []

    # 1) Lokalen Ordner löschen (nur sichere web_-Ordner unterhalb der Shop-Basis)
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

    # 2) Remote (GitHub-Repo + Railway-Service) — best-effort
    if del_remote and row.get("repo_url"):
        full = row["repo_url"].split("github.com/", 1)[-1].strip("/").removesuffix(".git")
        if "/" in full:
            try:
                import agent_github
                gr = agent_github.delete_repo(full)
                report.append("GitHub-Repo gelöscht" if gr.get("ok")
                              else f"GitHub: {gr.get('error', '')[:60]}")
            except Exception as e:
                report.append(f"GitHub-Fehler: {type(e).__name__}")
            try:
                import agent_railway
                svc = full.split("/")[-1]            # Service-Name = Repo-Name (web-<slug>)
                rr = agent_railway.service_delete_by_name(svc)
                report.append("Railway-Service gelöscht" if rr.get("ok")
                              else f"Railway: {rr.get('error', '')[:60]}")
            except Exception as e:
                report.append(f"Railway-Fehler: {type(e).__name__}")

    # 3) Cloud-Eintrag entfernen (Cross-PC) + lokalen DB-Eintrag (immer)
    try:
        import cloud_sync_websites
        cloud_sync_websites.delete_remote(row.get("name", ""), row.get("stadt", ""))
    except Exception:
        pass
    db_websites.delete(wid)
    report.append("Eintrag entfernt")
    return jsonify({"ok": True, "report": report})


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
    """'Top verbessern': 5-Agenten-Pipeline + Re-Deploy (Hintergrund-Job)."""
    import website_builder
    row = db_websites.get(wid)
    if not row:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    folder = (row.get("folder") or "").strip()
    if not folder or not os.path.isdir(folder):
        return jsonify({"ok": False, "reason": "Ordner nicht gefunden"}), 409
    job_id = website_builder.improve_existing(folder, row.get("name") or None)
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
    if backend == "higgsfield":
        params = {"prompt": prompt, "width": body.get("width"), "height": body.get("height")}
        job_id = media_queue.submit("higgsfield_image", params)
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

    if backend == "higgsfield":
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
    if backend == "higgsfield":
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
