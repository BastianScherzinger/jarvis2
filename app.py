"""
JARVIS LeadHunter — Flask Backend.
SSE-Stream sendet jeden neuen Lead als Chat-Nachricht ans Dashboard.
"""
import json
import os
import queue
import time
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

import db
from scrapers import controller

app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24)

# ── Init DB beim Start ────────────────────────────────────────────────────────
db.init_db()


# ── SSE Helper ────────────────────────────────────────────────────────────────
def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def api_start():
    body    = request.get_json(silent=True) or {}
    ai_mode = body.get("ai_mode", "local")   # local | cloud | both
    if not controller.is_running():
        controller.start(ai_mode=ai_mode)
        return jsonify({"ok": True, "ai_mode": ai_mode})
    return jsonify({"ok": False, "reason": "already_running"})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    controller.stop()
    return jsonify({"ok": True})


@app.route("/api/status")
def api_status():
    return jsonify({
        "running": controller.is_running(),
        "ai_mode": controller.get_ai_mode(),
        "stats":   db.get_stats(),
    })


@app.route("/api/leads")
def api_leads():
    limit  = int(request.args.get("limit", 200))
    offset = int(request.args.get("offset", 0))
    return jsonify(db.get_all(limit=limit, offset=offset))


@app.route("/api/export/csv")
def api_export_csv():
    csv_text = db.export_csv()
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


@app.route("/api/stream")
def api_stream():
    """SSE-Endpoint — schickt neue Leads als Chat-Nachrichten."""
    q = controller.get_queue()

    def event_stream():
        yield _sse({"type": "connected", "msg": "LeadHunter verbunden."})

        while True:
            try:
                lead = q.get(timeout=20)
            except queue.Empty:
                yield _sse({"type": "ping"})
                continue

            if "_error" in lead:
                yield _sse({"type": "error", "msg": lead["_error"]})
                continue

            yield _sse({"type": "lead", "data": lead})

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
