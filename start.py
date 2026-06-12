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


def _ensure_model(model: str) -> None:
    """Lädt das Modell per 'ollama pull' falls noch nicht installiert (mit Nachfrage)."""
    try:
        import hardware
        if model in hardware.installed_models():
            return
    except Exception:
        return
    print()
    print(f"  {YL}[!]{R}  Modell '{model}' ist noch nicht installiert.")
    try:
        ans = input(f"  {C}›{R}  Jetzt herunterladen? (j/N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = ""
    if ans in ("j", "ja", "y", "yes"):
        print(f"  {CY}[>]{R}  Lade {model} … (kann je nach Größe einige Minuten dauern)")
        subprocess.run(["ollama", "pull", model], check=False)
    else:
        print(f"  {GY}     Übersprungen — bestehendes Modell wird genutzt.{R}")


def _boot_screen(cfg: dict) -> str:
    """Boot-Banner mit Hardware-Erkennung + Auswahl des lokalen KI-Profils."""
    try:
        import hardware
        hw  = hardware.detect()
        rec = hardware.recommend(hw)
        profs = hardware.PROFILES
        installed = hardware.installed_models()
    except Exception:
        hw, rec, profs, installed = {}, None, [], []

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

    if hw:
        gpu = f"{hw['gpu_name']} ({hw['vram_gb']:.0f} GB)" if hw["has_gpu"] else "keine dedizierte GPU"
        print(f"  {B}HARDWARE{R}   ›  {GY}{hw['ram_gb']:.0f} GB RAM  ·  {gpu}{R}")
    if rec:
        print(f"  {B}EMPFOHLEN{R}  ›  {GR}{rec['name']}{R} {GY}({rec['model']}){R}")
    print()

    # ── Profil-Auswahl ──────────────────────────────────────────────────────
    cap    = hw.get("kapazitaet_gb", 0) if hw else 0
    chosen = rec
    if profs:
        print(f"  {GY}Wähle das lokale KI-Profil:{R}")
        print()
        for i, p in enumerate(profs, 1):
            mark = f"{GR}● installiert{R}" if p["model"] in installed else f"{GY}↓ Download{R}"
            star = f" {C}◄ empfohlen{R}" if rec and p["key"] == rec["key"] else ""
            # Profil größer als der (V)RAM → würde auslagern und ausbremsen
            if cap and p["size_gb"] > cap * 1.05:
                star = f" {RD}✗ zu groß für deine Hardware{R}"
            print(f"    [{C}{i}{R}]  {B}{p['name']:<12}{R} {GY}{p['model']:<18}{R} {mark}{star}")
            print(f"          {GY}{p['desc']}{R}")
        print()
        try:
            ch = input(f"  {C}›{R}  Auswahl (1-{len(profs)}, Enter = empfohlen): ").strip()
        except (EOFError, KeyboardInterrupt):
            ch = ""
        if ch.isdigit() and 1 <= int(ch) <= len(profs):
            chosen = profs[int(ch) - 1]

    if chosen:
        _set_env("JARVIS_EVAL_MODEL", chosen["model"])
        os.environ["JARVIS_EVAL_MODEL"] = chosen["model"]
        print()
        print(f"  {B}KI-PROFIL{R}  ›  {GR}{chosen['name']}{R} {GY}({chosen['model']}){R}")
        _ensure_model(chosen["model"])

    print(f"  {B}INTERNET{R}   ›  {GR}DuckDuckGo + Google Maps{R}")
    print(f"  {B}PORT{R}       ›  {GY}localhost:5000{R}")
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
