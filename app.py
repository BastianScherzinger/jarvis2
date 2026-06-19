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

import db
import db_raw
import db_evaluated
import media_queue
import cloud_sync
import logger as _logger
from scrapers import controller, _http

app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24)
db.init_db()
db_raw.init_db()
db_evaluated.init_db()

# Auto-Start Evaluator wenn ausstehende Roh-Leads aus vorherigen Sessions vorhanden.
def _auto_start_evaluator():
    try:
        if db_raw.get_pending_count() > 0:
            from scrapers import controller
            controller.ensure_evaluator_running()
    except Exception:
        pass

import threading as _startup_t
_startup_t.Thread(target=_auto_start_evaluator, daemon=True).start()

# Cloud-Sync starten (batch alle 10 Min)
cloud_sync.start()
# Startup-Pull: alle Supabase-Leads in lokalen Cache laden (andere PCs)
_startup_t.Thread(target=cloud_sync.pull_and_cache, daemon=True).start()

# Whisper-Modell für die Spracheingabe im Hintergrund vorladen (lädt es beim
# ersten Start automatisch herunter — blockiert den Dashboard-Start nicht).
def _warmup_voice():
    try:
        import voice_web
        voice_web.warmup()
    except Exception:
        pass
_startup_t.Thread(target=_warmup_voice, daemon=True).start()

_MEDIA_DIR = Path(__file__).parent / "workspace" / "media"


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# Stats max. 1×/Sek aggregieren (statt bei JEDEM Lead-Event eine volle COUNT-Runde).
import time as _time
_stats_cache = {"t": 0.0, "v": None}


def _stats() -> dict:
    now = _time.time()
    if _stats_cache["v"] is None or now - _stats_cache["t"] > 1.0:
        _stats_cache["v"] = db.get_stats()
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
        "stats":   db.get_stats(),
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


@app.route("/api/lead/<int:lead_id>/status", methods=["POST"])
def api_lead_status(lead_id):
    body   = request.get_json(silent=True) or {}
    status = body.get("status", "")
    allowed = {"neu", "kontaktiert", "termin", "verkauft", "tot"}
    if status not in allowed:
        return jsonify({"ok": False, "reason": "invalid_status"}), 400
    db.update_lead_status(lead_id, status)
    return jsonify({"ok": True, "status": status})


@app.route("/api/lead/<int:lead_id>/email", methods=["POST"])
def api_lead_email(lead_id):
    """Generiert einen Outreach-E-Mail-Entwurf (synchron via Ollama, ~5-20s)."""
    from agents import outreach
    lead = db.get_lead(lead_id)
    if not lead:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    result = outreach.generate_email(lead)
    return jsonify(result)


@app.route("/api/lead/<int:lead_id>/mockup", methods=["POST"])
def api_lead_mockup(lead_id):
    """Reiht einen Website-Mockup-Bild-Job für diesen Lead ein."""
    lead = db.get_lead(lead_id)
    if not lead:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    branche = (lead.get("branche") or "business").strip()
    prompt = (
        f"modern professional website hero image for a German {branche} business, "
        f"clean corporate design, high quality, no text"
    )
    job_id = media_queue.submit("mockup", {
        "prompt":    prompt,
        "model_key": None,
        "lead_id":   lead_id,
    })
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/lead/<int:eval_id>/website", methods=["POST"])
def api_lead_website(eval_id):
    """Startet den Website-Builder für einen Lead (Vorlage → Fotos → Claude → GitHub → Railway)."""
    import website_builder
    if not website_builder.is_available():
        return jsonify({"ok": False, "reason": "vorlage_landing/ fehlt"}), 500

    # Beste Datenquelle: bewerteter Lead (hat foto_urls, email_alle). Body füllt Lücken.
    lead = {}
    try:
        import db_evaluated
        lead = db_evaluated.get_by_id(eval_id) or {}
    except Exception:
        lead = {}
    body = request.get_json(silent=True) or {}
    for k, v in body.items():
        if v not in (None, "", []) and not lead.get(k):
            lead[k] = v
    if not lead.get("name"):
        return jsonify({"ok": False, "reason": "Kein Lead-Name."}), 400

    job_id = website_builder.build(lead)
    import agent_github
    import agent_railway
    return jsonify({"ok": True, "job_id": job_id,
                    "github_ready": agent_github.is_ready(),
                    "railway_ready": agent_railway.is_ready()})


@app.route("/api/website/job/<job_id>")
def api_website_job(job_id):
    import website_builder
    job = website_builder.get(job_id)
    if job is None:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    return jsonify(job)


@app.route("/api/lead/<int:lead_id>/competition")
def api_lead_competition(lead_id):
    lead = db.get_lead(lead_id)
    if not lead:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    return jsonify(db.get_competition(lead.get("stadt", ""), lead.get("branche", "")))


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
        "leads":     db.clear_all(),
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
    """Ist der Claude-Chat einsatzbereit (API-Key vorhanden)?"""
    import claude_chat
    return jsonify({"ready": claude_chat.is_ready(), "model": claude_chat.MODEL})


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
    body   = request.get_json(silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"ok": False, "reason": "no_prompt"}), 400
    if len(prompt) > 1000:
        return jsonify({"ok": False, "reason": "prompt_too_long"}), 400
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
