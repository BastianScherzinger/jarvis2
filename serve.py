#!/usr/bin/env python3
"""
serve.py — Produktions-Start von JARVIS über den robusten waitress-WSGI-Server.

  python serve.py                     # 0.0.0.0:5000 (oder JARVIS_PORT)
  JARVIS_PORT=8080 python serve.py    # eigener Port
  JARVIS_THREADS=16 python serve.py   # mehr Worker-Threads

Unterschied zu start.py: kein Boot-Screen, kein Browser-Autostart, kein Flask-
Dev-Server — sondern waitress für Dauerbetrieb (Server/VPS/Container). Hinter einem
Reverse-Proxy (nginx/Caddy) für TLS betreiben; SSE-Routen brauchen Buffering aus
(X-Accel-Buffering: no ist bereits gesetzt).
"""
import os
import subprocess
import sys
from pathlib import Path

# Produktionsmodus erzwingen, bevor app importiert wird.
os.environ.setdefault("JARVIS_SERVER", "1")
os.environ.setdefault("JARVIS_AI_MODE", "local")
os.environ.setdefault("PYTHONUTF8", "1")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).parent


def _ensure_waitress() -> None:
    try:
        import waitress  # noqa: F401
    except ImportError:
        print("[serve] waitress wird installiert …", flush=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "waitress", "-q"], check=False)


if __name__ == "__main__":
    _ensure_waitress()
    sys.path.insert(0, str(HERE))
    import app
    app.run_server()
