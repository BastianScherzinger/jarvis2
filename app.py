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
import logger as _logger
from scrapers import controller, _http

app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24)
db.init_db()
db_raw.init_db()
db_evaluated.init_db()

_MEDIA_DIR = Path(__file__).parent / "workspace" / "media"


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.route("/")
def index():
    return render_template("index.html")


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
    return jsonify({"top": db.get_top_opportunities(10)})


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


@app.route("/api/graph/nodes")
def api_graph_nodes():
    limit  = min(int(request.args.get("limit", 2000)), 2000)
    offset = max(int(request.args.get("offset", 0)), 0)
    return jsonify({"nodes": db_evaluated.get_for_graph(limit, offset)})


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
        "steps":     int(body.get("steps", 24)),
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
    q = controller.get_queue()

    def event_stream():
        # Beim Verbinden: aktuelle DB-Stats schicken (verhindert Flickern)
        yield _sse({"type": "init_stats", "stats": db.get_stats()})

        while True:
            try:
                lead = q.get(timeout=20)
            except queue.Empty:
                # Keepalive + aktualisierte Stats alle 20s
                yield _sse({"type": "stats", "stats": db.get_stats()})
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
                    "stats": db.get_stats(),
                })
                continue

            # Evaluator-Events: Roh-Lead wurde KI-bewertet (DB2)
            if lead.get("type") == "evaluated":
                yield _sse({"type": "evaluated", "data": lead["data"]})
                continue

            # Lead senden + gleichzeitig DB-Stats (single source of truth)
            yield _sse({"type": "lead", "data": lead, "stats": db.get_stats()})

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
