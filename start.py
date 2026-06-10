#!/usr/bin/env python3
"""
JARVIS Launcher
Starten:  python start.py
"""

import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

# UTF-8 + ANSI aktivieren
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"]       = "1"
os.system("")


# ── Farben ────────────────────────────────────────────────────────────────────
C  = "\033[96m"   # cyan
B  = "\033[1m"    # bold
R  = "\033[0m"    # reset
GR = "\033[92m"   # green
YL = "\033[93m"   # yellow
GY = "\033[90m"   # gray


HERE = Path(__file__).parent


def _read_env() -> dict:
    p = HERE / ".env"
    if not p.exists():
        return {}
    cfg: dict = {}
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        l = line.strip()
        if not l or l.startswith("#") or "=" not in l:
            continue
        k, _, v = l.partition("=")
        cfg[k.strip()] = v.strip()
    return cfg


def _set_env(key: str, value: str) -> None:
    """Setzt einen Wert in .env (überschreibt falls vorhanden, hängt sonst an)."""
    p = HERE / ".env"
    if not p.exists():
        p.write_text(f"{key}={value}\n", encoding="utf-8")
        return
    txt = p.read_text(encoding="utf-8")
    if re.search(rf"^{re.escape(key)}=", txt, re.MULTILINE):
        txt = re.sub(rf"^{re.escape(key)}=.*$", f"{key}={value}", txt, flags=re.MULTILINE)
    else:
        txt = txt.rstrip() + f"\n{key}={value}\n"
    p.write_text(txt, encoding="utf-8")


def _is_first_run(cfg: dict) -> bool:
    """True wenn Setup noch unvollständig ist."""
    if not (HERE / ".env").exists():
        return True
    mode = cfg.get("JARVIS_MODE", "cloud").lower()
    if mode == "local":
        return not (cfg.get("JARVIS_TOOL_MODEL") or cfg.get("JARVIS_LOCAL_MODEL"))
    key = cfg.get("ANTHROPIC_KEY") or cfg.get("ANTHROPIC_API_KEY", "")
    return not key or "sk-ant-..." in key or "dein_api_key" in key


def _boot_screen() -> None:
    """Zeigt JARVIS-Banner und fragt nach dem KI-Modus."""
    cfg   = _read_env()
    mode  = cfg.get("JARVIS_MODE", "cloud").lower()
    model = cfg.get("JARVIS_TOOL_MODEL") or cfg.get("JARVIS_LOCAL_MODEL") or "qwen2.5:7b"
    key   = cfg.get("ANTHROPIC_KEY") or cfg.get("ANTHROPIC_API_KEY", "")
    has_k = bool(key) and "sk-ant-..." not in key and "dein_api_key" not in key

    W      = 54
    border = "═" * W
    title  = "J · A · R · V · I · S"
    sub    = "Just A Rather Very Intelligent System"

    print()
    print(f"  {C}╔{border}╗{R}")
    print(f"  {C}║{' ' * W}║{R}")
    print(f"  {C}║{R}{B}{title:^{W}}{R}{C}║{R}")
    print(f"  {C}║{R}{GY}{sub:^{W}}{R}{C}║{R}")
    print(f"  {C}║{' ' * W}║{R}")
    print(f"  {C}╚{border}╝{R}")
    print()

    # Status
    if mode == "local":
        mode_str = f"  {B}MODUS{R}    ›  {YL}LOCAL{R}   {GY}{model}{R}"
    else:
        warn = f"   {YL}⚠ kein API-Key{R}" if not has_k else ""
        mode_str = f"  {B}MODUS{R}    ›  {GR}CLOUD{R}   {GY}claude-sonnet-4-6{R}{warn}"

    print(mode_str)
    if mode == "cloud" and model:
        print(f"  {B}FALLBACK{R} ›  {GY}{model} (Ollama){R}")
    print(f"  {B}PORT{R}     ›  {GY}localhost:5000{R}")
    print()

    # Modus-Auswahl
    if mode == "local":
        opt_c = f"{C}[c]{R} Cloud (Claude)"
        opt_l = f"{GY}[l]{R} Lokal  ← aktiv"
    else:
        opt_c = f"{GY}[c]{R} Cloud  ← aktiv"
        opt_l = f"{C}[l]{R} Lokal (Ollama)"

    line = "─" * 50
    print(f"  {GY}{line}{R}")
    print(f"    {opt_c}    {opt_l}    {C}[Enter]{R} Weiter")
    print(f"  {GY}{line}{R}")
    print()

    try:
        ch = input(f"  {C}›{R}  ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        ch = ""

    if ch == "c" and mode != "cloud":
        _set_env("JARVIS_MODE", "cloud")
        os.environ["JARVIS_MODE"] = "cloud"
        print(f"\n  {GR}Cloud-Modus aktiviert.{R}")
        print()
    elif ch == "l" and mode != "local":
        _set_env("JARVIS_MODE", "local")
        os.environ["JARVIS_MODE"] = "local"
        print(f"\n  {YL}Local-Modus aktiviert.{R}  {GY}({model}){R}")
        print()

    return cfg


def main():
    if "--list" in sys.argv:
        subprocess.run([sys.executable, "voice_agent.py", "--list"])
        return

    if not (HERE / "app.py").exists():
        print(f"  {YL}[!]{R}  app.py nicht gefunden — bitte aus dem jarvis-Ordner starten.")
        sys.exit(1)

    # ── Boot-Screen & Modus-Auswahl ──────────────────────────────────
    cfg       = _boot_screen()
    first_run = _is_first_run(_read_env())   # nach möglichem Mode-Write neu lesen

    # ── Setup (quiet wenn bereits konfiguriert) ──────────────────────
    import install
    all_ok = install.run(quiet=not first_run)

    if not all_ok:
        print(f"  {YL}[!]{R}  Setup unvollständig — JARVIS startet trotzdem.")
        print()

    # ── Browser öffnen ───────────────────────────────────────────────
    def _open():
        time.sleep(2.2)
        webbrowser.open("http://localhost:5000")
    threading.Thread(target=_open, daemon=True).start()

    # ── Flask starten ────────────────────────────────────────────────
    print(f"  {C}[JARVIS]{R}  Starte Server auf {GY}http://localhost:5000{R} ...")
    print()

    flask = subprocess.Popen(
        [sys.executable, "-u", "app.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        cwd=str(HERE),
    )

    try:
        for line in iter(flask.stdout.readline, ""):
            sys.stdout.write(line)
            sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            flask.terminate()
            flask.wait(timeout=3)
        except Exception:
            try:
                flask.kill()
            except Exception:
                pass
        print(f"\n  {YL}[JARVIS]{R}  Beendet.")


if __name__ == "__main__":
    main()
