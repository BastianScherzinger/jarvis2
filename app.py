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
import media_queue
from scrapers import controller, _http

app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24)
db.init_db()

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


@app.route("/api/claude", methods=["POST"])
def api_claude():
    """Claude ein- oder ausschalten — auch während der Scraper läuft."""
    body    = request.get_json(silent=True) or {}
    enabled = bool(body.get("enabled", False))
    controller.set_claude_enabled(enabled)
    return jsonify({"ok": True, "claude_enabled": enabled})


@app.route("/api/status")
def api_status():
    return jsonify({
        "running":        controller.is_running(),
        "claude_enabled": controller.is_claude_enabled(),
        "stats":          db.get_stats(),
    })


@app.route("/api/export/csv")
def api_export_csv():
    return Response(
        db.export_csv(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
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

            # Verifier-Events: Lead wurde nachverifiziert
            if lead.get("type") == "verified":
                yield _sse({
                    "type":  "verified",
                    "data":  lead["data"],
                    "stats": db.get_stats(),
                })
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
