"""
mcp_maps_launch.py — Launcher für den Google-Maps-MCP-Server.

PROBLEM: In .mcp.json stand `GOOGLE_MAPS_API_KEY=${GOOGLE_MAPS_API_KEY}` — das expandiert
Claude Code aus der OS-Umgebungsvariable, NICHT aus der Projekt-.env. Auf einem PC, der den
Key nur in der .env-Datei (gitignored) hat, blieb er leer → "Maps MCP nicht verbunden, Key
fehlt".

FIX: Dieser Launcher liest GOOGLE_MAPS_API_KEY aus der OS-Umgebung ODER (Fallback) aus der
.env neben diesem Script und startet damit den eigentlichen MCP-Server
(@modelcontextprotocol/server-google-maps) über npx. stdin/stdout/stderr werden 1:1
durchgereicht (MCP spricht über stdio) — der Server verhält sich exakt wie zuvor, nur dass
der Key jetzt zuverlässig aus der .env kommt. So funktioniert es auf JEDEM PC mit derselben
.env, ohne pro Maschine eine Umgebungsvariable setzen zu müssen. Kein Secret landet im Git.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

_KEY_NAME = "GOOGLE_MAPS_API_KEY"


def _key_from_env_file() -> str:
    """Liest den Key aus der .env neben diesem Script (einfacher KEY=VALUE-Parser)."""
    envf = Path(__file__).resolve().with_name(".env")
    if not envf.is_file():
        return ""
    try:
        for line in envf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == _KEY_NAME:
                return v.strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _npx() -> str:
    """npx-Pfad (Windows: npx.cmd)."""
    for name in ("npx.cmd", "npx", "npx.exe"):
        p = shutil.which(name)
        if p:
            return p
    return "npx"


def main() -> int:
    key = (os.environ.get(_KEY_NAME) or "").strip() or _key_from_env_file()
    env = os.environ.copy()
    if key:
        env[_KEY_NAME] = key
    else:
        # Ohne Key startet der Server zwar, kann aber nicht authentifizieren — klare Meldung
        # nach stderr (taucht im MCP-Log auf), trotzdem starten (Server meldet dann selbst).
        sys.stderr.write(f"[mcp_maps_launch] WARN: {_KEY_NAME} weder in OS-Umgebung noch in "
                         ".env gefunden — Maps-MCP wird sich nicht authentifizieren können.\n")
        sys.stderr.flush()
    args = [_npx(), "-y", "@modelcontextprotocol/server-google-maps"]
    try:
        # stdio 1:1 durchreichen (kein PIPE) → MCP-Protokoll fließt transparent.
        return subprocess.run(args, env=env).returncode
    except FileNotFoundError:
        sys.stderr.write("[mcp_maps_launch] FEHLER: npx nicht gefunden — Node.js installieren.\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
