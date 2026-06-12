#!/usr/bin/env python3
"""
JARVIS LeadHunter — Launcher
python start.py
"""
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"]       = "1"
os.system("")   # ANSI auf Windows aktivieren

C  = "\033[96m"
B  = "\033[1m"
R  = "\033[0m"
GR = "\033[92m"
YL = "\033[93m"
GY = "\033[90m"
RD = "\033[91m"

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


def _install_deps() -> None:
    """Stellt sicher dass Flask + Playwright + beautifulsoup4 installiert sind."""
    pkgs = ["flask", "playwright", "beautifulsoup4", "requests"]
    for pkg in pkgs:
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            print(f"  {YL}[+]{R}  Installiere {pkg}...")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg, "-q"],
                check=False
            )
    # Playwright Chromium
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.executable_path  # prüft ob Browser da
    except Exception:
        print(f"  {YL}[+]{R}  Installiere Playwright Chromium...")
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium", "--with-deps"],
            check=False
        )


def _boot_screen(cfg: dict) -> str:
    """Zeigt Boot-Banner. System läuft vollständig lokal — keine Modus-Auswahl nötig."""
    local_mdl = cfg.get("JARVIS_TOOL_MODEL") or cfg.get("JARVIS_LOCAL_MODEL", "qwen2.5:7b")

    W = 54
    print()
    print(f"  {C}╔{'═'*W}╗{R}")
    print(f"  {C}║{' '*W}║{R}")
    print(f"  {C}║{R}{B}{'J · A · R · V · I · S':^{W}}{R}{C}║{R}")
    print(f"  {C}║{R}{GY}{'LeadHunter  ·  B2B Lead Generator':^{W}}{R}{C}║{R}")
    print(f"  {C}║{' '*W}║{R}")
    print(f"  {C}╚{'═'*W}╝{R}")
    print()
    print(f"  {GR}⬡ 100% LOKAL{R}   {GY}— alle Leads werden lokal gefunden & bewertet{R}")
    print()
    print(f"  {B}LOKALE KI{R}      ›  {GY}{local_mdl}{R}")
    print(f"  {B}INTERNET{R}       ›  {GR}DuckDuckGo + Google Maps{R}")
    print(f"  {B}PORT{R}           ›  {GY}localhost:5000{R}")
    print()
    print(f"  {GY}{'─'*50}{R}")
    print()

    _set_env("JARVIS_AI_MODE", "local")
    os.environ["JARVIS_AI_MODE"] = "local"
    return "local"


def main():
    cfg     = _read_env()
    ai_mode = _boot_screen(cfg)

    print(f"  {GY}[+]{R}  Prüfe Abhängigkeiten...")
    _install_deps()
    print(f"  {GR}[✓]{R}  Bereit.")
    print()

    # Browser nach kurzer Verzögerung öffnen
    def _open():
        time.sleep(2.5)
        webbrowser.open("http://localhost:5000")
    threading.Thread(target=_open, daemon=True).start()

    print(f"  {C}[JARVIS]{R}  LeadHunter läuft auf {GY}http://localhost:5000{R}")
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
