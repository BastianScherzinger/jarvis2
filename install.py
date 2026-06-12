"""
JARVIS Auto-Installer
Wird von start.py und update.py automatisch aufgerufen.
Installiert alle Abhaengigkeiten und richtet Playwright ein.
"""
import subprocess
import sys
import os
from pathlib import Path

os.system("")   # Windows ANSI aktivieren

R  = "\033[0m";  B  = "\033[1m"
GR = "\033[92m"; RD = "\033[91m"
YL = "\033[93m"; CY = "\033[96m"
GY = "\033[90m"

HERE   = Path(__file__).parent
_QUIET = False   # wird von run(quiet=True) gesetzt


def _pip(*args) -> bool:
    return subprocess.run(
        [sys.executable, "-m", "pip", "install", *args, "--quiet"],
        capture_output=True,
    ).returncode == 0


def _can_import(module: str) -> bool:
    return subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
    ).returncode == 0


def _ok(label: str, detail: str = "") -> None:
    if _QUIET:
        return
    extra = f"  {GY}{detail}{R}" if detail else ""
    print(f"  {GR}OK{R}  {label}{extra}")


def _warn(label: str, detail: str = "") -> None:
    extra = f"  {GY}{detail}{R}" if detail else ""
    print(f"  {YL}!{R}   {label}{extra}")


def _err(label: str, detail: str = "") -> None:
    extra = f"  {GY}{detail}{R}" if detail else ""
    print(f"  {RD}X{R}   {label}{extra}")


def _installing(label: str) -> None:
    print(f"  {CY}>{R}   {label} ...", end="", flush=True)


def _section(title: str, sub: str = "") -> None:
    """Sektionstitel — nur bei vollständigem Setup (nicht quiet)."""
    if _QUIET:
        return
    print()
    print(f"  {CY}{'─' * 56}{R}")
    print(f"  {CY}{B}  {title}{R}" + (f"  {GY}{sub}{R}" if sub else ""))
    print(f"  {CY}{'─' * 56}{R}")


def _header() -> None:
    if _QUIET:
        return
    print()
    print(f"  {CY}{'─' * 50}{R}")
    print(f"  {CY}{B}  JARVIS  Setup{R}")
    print(f"  {CY}{'─' * 50}{R}")
    print()


def run(quiet: bool = False) -> bool:
    global _QUIET
    _QUIET = quiet

    _header()
    all_ok = True

    # ── System-Analyse ──────────────────────────────────────────────
    _profile = None
    _recommended_model = "qwen2.5:7b"
    try:
        import system_profile as _sp
        _profile = _sp.analyze()
        if not quiet:
            _sp.print_banner(_profile)
        _recommended_model = _profile.get("local_model", "qwen2.5:7b")
    except Exception as _e:
        _warn("System-Analyse fehlgeschlagen", str(_e)[:60])

    # ── Git Update ───────────────────────────────────────────────────
    import shutil
    if shutil.which("git") and (HERE / ".git").exists():
        if not quiet:
            print(f"  {CY}>{R}   Git update ...", end="", flush=True)
        try:
            res = subprocess.run(
                ["git", "pull", "--ff-only"],
                capture_output=True, text=True, cwd=HERE, timeout=12,
                encoding="utf-8", errors="replace",
            )
            out = (res.stdout + res.stderr).strip().split("\n")[0][:60]
            if res.returncode == 0:
                already = "already up" in out.lower() or "bereits" in out.lower()
                if not quiet:
                    label = "bereits aktuell" if already else out
                    print(f"\r  {GR}OK{R}  Git  {GY}{label}{R}          ")
                elif not already:
                    print(f"  {GR}Git{R}  {GY}{out}{R}")
            else:
                if not quiet:
                    print(f"\r  {YL}!{R}   Git pull  {GY}{out}{R}          ")
                else:
                    _warn("Git pull", out)
        except Exception as e:
            if not quiet:
                print(f"\r  {YL}!{R}   Git  {GY}({e}){R}          ")

    # ── Python-Version ───────────────────────────────────────────────
    v = sys.version_info
    if v >= (3, 10):
        _ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        _warn(f"Python {v.major}.{v.minor}.{v.micro}", "empfohlen: 3.10+")

    # ── Pakete installieren ──────────────────────────────────────────
    req_file = HERE / "requirements.txt"
    packages = [
        ("anthropic",          "anthropic"),
        ("flask",              "flask"),
        ("dotenv",             "python-dotenv"),
        ("speech_recognition", "SpeechRecognition"),
        ("edge_tts",           "edge-tts"),
        ("playwright",         "playwright"),
        ("faster_whisper",     "faster-whisper"),
        ("imageio_ffmpeg",     "imageio-ffmpeg"),
        ("pyttsx3",            "pyttsx3"),
    ]

    if req_file.exists():
        _installing("Pakete")
        bulk_ok = _pip("-r", str(req_file))
        if bulk_ok:
            print(f"\r  {GR}OK{R}  Alle Pakete aktuell              ")
        else:
            print(f"\r  {YL}!{R}   Bulk-Install fehlgeschlagen — pruefe einzeln:")
            for module, pip_name in packages:
                if _can_import(module):
                    _ok(pip_name, "bereits vorhanden")
                else:
                    _installing(pip_name)
                    if _pip(pip_name):
                        print(f"\r  {GR}OK{R}  {pip_name:<28}")
                    else:
                        print(f"\r  {RD}X{R}   {pip_name:<28}  {GY}pip install {pip_name}{R}")
                        all_ok = False
    else:
        _warn("requirements.txt nicht gefunden", "manuell: pip install anthropic flask python-dotenv SpeechRecognition edge-tts playwright")

    # ── Playwright Chromium ──────────────────────────────────────────
    if _can_import("playwright"):
        check = subprocess.run(
            [sys.executable, "-c",
             "from playwright.sync_api import sync_playwright;"
             " p=sync_playwright().start(); b=p.chromium.launch(headless=True); b.close(); p.stop()"],
            capture_output=True, timeout=20,
        )
        if check.returncode == 0:
            _ok("Playwright Chromium")
        else:
            _installing("Playwright Chromium  (einmalig ~120 MB)")
            ok = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium", "--with-deps"],
                capture_output=True, timeout=240,
            ).returncode == 0
            if ok:
                print(f"\r  {GR}OK{R}  Playwright Chromium installiert      ")
            else:
                print(f"\r  {YL}!{R}   Playwright Chromium  {GY}manuell: playwright install chromium{R}")

    # ── .env erstellen / pruefen ─────────────────────────────────────
    env_file     = HERE / ".env"
    env_example  = HERE / ".env.example"

    if not env_file.exists():
        if env_example.exists():
            env_file.write_text(env_example.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            env_file.write_text(
                "ANTHROPIC_KEY=dein_api_key_hier\n"
                "# ELEVENLABS_KEY=optional\n"
                "# JARVIS_VOICE=de-DE-ConradNeural\n"
                "# JARVIS_RATE=+18%\n",
                encoding="utf-8",
            )
        _warn(".env erstellt", "ANTHROPIC_KEY eintragen!")
        all_ok = False
    else:
        content = env_file.read_text(encoding="utf-8")
        has_key = "ANTHROPIC_KEY" in content
        is_placeholder = "dein_api_key" in content or "sk-ant-..." in content or "your_key" in content
        if has_key and not is_placeholder:
            _ok(".env  (API-Key gesetzt)")
        else:
            _err(".env", "ANTHROPIC_KEY fehlt oder ist noch Platzhalter")
            all_ok = False

    # ── Ollama — lokale KI-Worker ───────────────────────────────────
    ollama_exe = shutil.which("ollama")
    if not ollama_exe:
        print(f"  {CY}>{R}   Ollama installieren ...", end="", flush=True)
        wg = shutil.which("winget")
        installed = False
        if wg:
            res = subprocess.run(
                ["winget", "install", "--id", "Ollama.Ollama", "-e", "--silent", "--accept-package-agreements"],
                capture_output=True, timeout=120,
            )
            installed = res.returncode == 0
            ollama_exe = shutil.which("ollama")
        if installed and ollama_exe:
            print(f"\r  {GR}OK{R}  Ollama installiert                    ")
        else:
            print(f"\r  {YL}!{R}   Ollama nicht gefunden  {GY}https://ollama.com/download{R}")

    if ollama_exe:
        # Prüfe ob Modell schon in .env gesetzt ist
        env_content = (HERE / ".env").read_text(encoding="utf-8") if (HERE / ".env").exists() else ""
        has_model   = "JARVIS_LOCAL_MODEL=" in env_content and "JARVIS_LOCAL_MODEL=\n" not in env_content

        MODELS = {
            "1": {
                "key":  "tiny",
                "name": "llama3.2:1b",
                "desc": "Jede Hardware    (~600 MB, 1 GB RAM)  — schnell, einfache Aufgaben",
            },
            "2": {
                "key":  "small",
                "name": "qwen2.5:3b",
                "desc": "Schwache PC      (~2 GB,  4 GB RAM)  — besser als tiny",
            },
            "3": {
                "key":  "laptop",
                "name": "qwen2.5:7b",
                "desc": "HP-Laptop        (~4.7 GB, 8 GB RAM) — empfohlen fuer Laptops",
            },
            "4": {
                "key":  "medium",
                "name": "qwen2.5:14b",
                "desc": "Desktop 16 GB    (~9 GB,  16 GB VRAM) — solide Qualitaet",
            },
            "5": {
                "key":  "large",
                "name": "qwen2.5:32b",
                "desc": "Desktop 32 GB    (~20 GB, 32 GB VRAM) — starke Qualitaet",
            },
            "6": {
                "key":  "allware",
                "name": "llama3.3:70b",
                "desc": "High-End Server  (~43 GB, 48 GB VRAM) — bestes lokales Modell",
            },
        }

        if not has_model:
            _section("Lokales KI-Modell", "Empfehlung basiert auf Ihrer Hardware")
            for k, m in MODELS.items():
                marker = f"  {GR}← empfohlen{R}" if m["name"] == _recommended_model else ""
                print(f"  [{k}]  {B}{m['key'].upper():<10}{R}  {m['name']:<20}  {GY}{m['desc']}{R}{marker}")
            print(f"  [0]  Ueberspringen  {GY}(kein lokales Modell){R}")
            print()
            _auto_key = next((k for k, v in MODELS.items() if v["name"] == _recommended_model), None)
            if _auto_key:
                print(f"  {CY}Empfehlung:{R} {B}{_recommended_model}{R}  {GY}(Enter = uebernehmen){R}")
            keys = "/".join(["0"] + list(MODELS.keys()))
            try:
                choice = input(f"  {CY}Auswahl ({keys}) [Enter = empfohlen]:{R} ").strip()
            except (EOFError, KeyboardInterrupt):
                choice = _auto_key or "0"
            if choice == "" and _auto_key:
                choice = _auto_key

            if choice in MODELS:
                chosen = MODELS[choice]
                model_name = chosen["name"]
                # In .env eintragen
                with open(HERE / ".env", "a", encoding="utf-8") as ef:
                    ef.write(f"\nJARVIS_LOCAL_MODEL={model_name}\n")
                print()
                _installing(f"Modell '{model_name}' herunterladen  (kann einige Minuten dauern)")
                pull = subprocess.run(
                    ["ollama", "pull", model_name],
                    timeout=3600,
                )
                if pull.returncode == 0:
                    print(f"\r  {GR}OK{R}  Modell '{model_name}' bereit                   ")
                    _ok(f"JARVIS_LOCAL_MODEL={model_name}")
                else:
                    print(f"\r  {YL}!{R}   Download fehlgeschlagen — manuell: ollama pull {model_name}")
            else:
                _warn("Kein lokales Modell gewählt", "local_ai_worker Tool nicht verfügbar")
        else:
            # Modell schon gesetzt — prüfe ob es lokal vorhanden ist
            import re as _re
            m = _re.search(r"JARVIS_LOCAL_MODEL=(.+)", env_content)
            if m:
                model_name = m.group(1).strip()
                list_res = subprocess.run(
                    ["ollama", "list"], capture_output=True, text=True, timeout=10,
                    encoding="utf-8", errors="replace",
                )
                if model_name.split(":")[0] in list_res.stdout:
                    _ok(f"Ollama  {model_name}", "bereit")
                else:
                    _warn(f"Modell '{model_name}' nicht gefunden", f"manuell: ollama pull {model_name}")

    # ── Node.js / npx — für MCP-Server ─────────────────────────────
    node_ok = shutil.which("node") is not None
    npx_ok  = shutil.which("npx")  is not None
    if node_ok and npx_ok:
        try:
            ver = subprocess.run(["node", "--version"], capture_output=True,
                                 text=True, timeout=5).stdout.strip()
            _ok(f"Node.js  {ver}  + npx")
        except Exception:
            _ok("Node.js + npx")
    else:
        _warn("Node.js nicht gefunden", "MCP-Server brauchen Node.js — https://nodejs.org")

    # ── MCP-Server aus .mcp.json prüfen ─────────────────────────────
    mcp_file = HERE / ".mcp.json"
    if mcp_file.exists() and npx_ok:
        import json as _json
        try:
            mcp_cfg = _json.loads(mcp_file.read_text(encoding="utf-8"))
            servers = mcp_cfg.get("mcpServers", {})
            for name, cfg in servers.items():
                cmd  = cfg.get("command", "")
                args = cfg.get("args", [])
                env_needed = cfg.get("env", {})

                # Prüfe ob benötigte Env-Vars gesetzt sind
                missing_env = []
                if env_needed:
                    import os as _os
                    for k, v in env_needed.items():
                        real_val = _os.environ.get(k, "")
                        placeholder = "${" in str(v)
                        if not real_val and placeholder:
                            missing_env.append(k)

                if missing_env:
                    _warn(f"MCP  {name}", f"Key fehlt: {', '.join(missing_env)}")
                else:
                    _ok(f"MCP  {name}", f"{cmd} {' '.join(str(a) for a in args[:2])}")
        except Exception as e:
            _warn(".mcp.json", f"Parse-Fehler: {e}")
    elif mcp_file.exists() and not npx_ok:
        _warn("MCP-Server", "npx fehlt — Node.js installieren")

    # ── Google Maps Key → ~/.claude/.env synchen (für MCP-Server) ──
    import pathlib as _pl, re as _re2
    _jarvis_env = HERE / ".env"
    _claude_env = _pl.Path.home() / ".claude" / ".env"
    if _jarvis_env.exists():
        _m = _re2.search(r"GOOGLE_MAPS_API_KEY=(.+)", _jarvis_env.read_text(encoding="utf-8"))
        if _m:
            _key = _m.group(1).strip()
            _ce = _claude_env.read_text(encoding="utf-8") if _claude_env.exists() else ""
            if "GOOGLE_MAPS_API_KEY" not in _ce:
                _claude_env.parent.mkdir(parents=True, exist_ok=True)
                with open(_claude_env, "a", encoding="utf-8") as _cf:
                    _cf.write(f"\nGOOGLE_MAPS_API_KEY={_key}\n")
                _ok("~/.claude/.env", "GOOGLE_MAPS_API_KEY gesetzt")
            else:
                _ok("~/.claude/.env", "GOOGLE_MAPS_API_KEY bereits vorhanden")

    # ── obsidian_brain Ordner anlegen ───────────────────────────────
    (HERE / "obsidian_brain").mkdir(exist_ok=True)

    # ── workspace-Ordner anlegen ────────────────────────────────────
    for d in ["workspace/tasks", "workspace/results"]:
        (HERE / d).mkdir(parents=True, exist_ok=True)

    # ── System-Profil ins Brain schreiben ───────────────────────────
    if _profile is not None:
        try:
            _sp.write_profile(_profile, str(HERE))
            _ok("System-Profil", f"obsidian_brain/system_profile.md")
        except Exception:
            pass

    # ── Media KI — Bild & Video Generierung ─────────────────────────
    _section("Media KI", "Hugging Face Diffusers — Bild & Video lokal")

    _diffusers_ok = _can_import("diffusers") and _can_import("torch")

    if not _diffusers_ok:
        print(f"  {GY}diffusers + torch nicht installiert  (~3-5 GB Pakete){R}")
        try:
            _media_install = input(f"  {CY}Jetzt installieren? [j/N]:{R} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            _media_install = "n"
        if _media_install in ("j", "ja", "y", "yes"):
            _installing("torch + torchvision + diffusers + transformers + accelerate")
            _t_ok = _pip("torch", "torchvision")
            _d_ok = _pip("diffusers", "transformers", "accelerate", "sentencepiece")
            if _t_ok and _d_ok:
                print(f"\r  {GR}OK{R}  Media-KI-Pakete installiert            ")
                _diffusers_ok = True
            else:
                print(f"\r  {YL}!{R}   Install fehlgeschlagen — manuell: pip install torch torchvision diffusers transformers accelerate")
        else:
            _warn("Media-KI übersprungen", "manuell: pip install torch torchvision diffusers transformers accelerate")

    # torchvision automatisch nachinstallieren, sobald torch vorhanden ist:
    # transformers nutzt es für die Bild-Prozessoren (CLIP/Siglip). Fehlt es,
    # kommen nur Warnungen + PIL-Fallback. Läuft auch über update.py automatisch.
    if _can_import("torch") and not _can_import("torchvision"):
        print(f"  {GY}torchvision fehlt — installiere automatisch (behebt CLIP/Siglip-Warnungen)…{R}")
        if _pip("torchvision"):
            _ok("torchvision installiert")
            _diffusers_ok = _can_import("diffusers") and _can_import("torch")
        else:
            _warn("torchvision-Install fehlgeschlagen", "manuell: pip install torchvision")

    if _diffusers_ok:
        import re as _re_m
        _env_m = (HERE / ".env").read_text(encoding="utf-8") if (HERE / ".env").exists() else ""
        _has_img = "JARVIS_IMAGE_MODEL=" in _env_m and "JARVIS_IMAGE_MODEL=\n" not in _env_m
        _has_vid = "JARVIS_VIDEO_MODEL=" in _env_m and "JARVIS_VIDEO_MODEL=\n" not in _env_m

        _IMG_MODELS = {
            "1": {"key": "sd21",         "name": "Stable Diffusion 2.1", "size": "~2.5 GB", "vram": 4,
                  "desc": "Schnell, stabil — ab 4 GB VRAM, auch CPU (langsam)"},
            "2": {"key": "sdxl",         "name": "Stable Diffusion XL",  "size": "~6.5 GB", "vram": 8,
                  "desc": "Höhere Qualität, 1024px — ab 8 GB VRAM"},
            "3": {"key": "flux-schnell", "name": "FLUX.1 Schnell",        "size": "~15 GB",  "vram": 8,
                  "desc": "Bestes lokales Bildmodell, Apache 2.0 — ab 8 GB VRAM"},
        }
        _VID_MODELS = {
            "1": {"key": "wan-1.3b", "name": "Wan 2.1 T2V 1.3B", "size": "~2.7 GB", "vram": 8,
                  "desc": "Text-to-Video 480p — ab 8 GB VRAM"},
        }

        # Empfehlung basierend auf System-Profil
        _img_rec = "sd21"
        if _profile:
            _ram = _profile.get("ram_gb", 8)
            if _ram >= 16:
                _img_rec = "sdxl"
            if _ram >= 32:
                _img_rec = "flux-schnell"

        if not _has_img:
            print()
            print(f"  {CY}  Bildmodell wählen:{R}  {GY}(wird beim ersten Aufruf heruntergeladen){R}")
            for k, m in _IMG_MODELS.items():
                _marker = f"  {GR}← empfohlen{R}" if m["key"] == _img_rec else ""
                print(f"  [{k}]  {B}{m['name']:<28}{R}  {GY}{m['size']}, {m['vram']} GB VRAM — {m['desc']}{R}{_marker}")
            print(f"  [0]  Kein Bildmodell")
            try:
                _ic = input(f"  {CY}Bildmodell (0-3) [Enter = {_img_rec}]:{R} ").strip()
            except (EOFError, KeyboardInterrupt):
                _ic = ""
            if _ic == "":
                _ic = next((k for k, v in _IMG_MODELS.items() if v["key"] == _img_rec), "0")
            if _ic in _IMG_MODELS:
                _chosen_img = _IMG_MODELS[_ic]
                with open(HERE / ".env", "a", encoding="utf-8") as _ef:
                    _ef.write(f"\nJARVIS_IMAGE_MODEL={_chosen_img['key']}\n")
                _ok(f"Bildmodell: {_chosen_img['name']}", f"Download beim ersten 'Bild generieren' ({_chosen_img['size']})")
            else:
                _warn("Kein Bildmodell konfiguriert", "JARVIS_IMAGE_MODEL in .env setzen")
        else:
            _mi = _re_m.search(r"JARVIS_IMAGE_MODEL=(.+)", _env_m)
            if _mi:
                _ok(f"Bildmodell: {_mi.group(1).strip()}", "bereits konfiguriert")

        if not _has_vid:
            print()
            print(f"  {CY}  Lokales Videomodell:{R}  {GY}(wird beim ersten Aufruf heruntergeladen){R}")
            for k, m in _VID_MODELS.items():
                print(f"  [{k}]  {B}{m['name']:<28}{R}  {GY}{m['size']}, {m['vram']} GB VRAM — {m['desc']}{R}")
            print(f"  [0]  Kein lokales Videomodell  {GY}(Higgsfield-API reicht){R}")
            try:
                _vc = input(f"  {CY}Videomodell (0/1) [Enter = überspringen]:{R} ").strip()
            except (EOFError, KeyboardInterrupt):
                _vc = "0"
            if _vc in _VID_MODELS:
                _chosen_vid = _VID_MODELS[_vc]
                with open(HERE / ".env", "a", encoding="utf-8") as _ef:
                    _ef.write(f"\nJARVIS_VIDEO_MODEL={_chosen_vid['key']}\n")
                _ok(f"Videomodell: {_chosen_vid['name']}", f"Download beim ersten 'Video generieren' ({_chosen_vid['size']})")
            else:
                _warn("Kein lokales Videomodell", "JARVIS_VIDEO_MODEL in .env setzen")
        else:
            _vi = _re_m.search(r"JARVIS_VIDEO_MODEL=(.+)", _env_m)
            if _vi:
                _ok(f"Videomodell: {_vi.group(1).strip()}", "bereits konfiguriert")

    # ── Higgsfield.ai API — Cloud Video-Generierung ──────────────────
    _section("Higgsfield.ai", "Cloud Video-KI — cinematische Qualität")
    _env_hf = (HERE / ".env").read_text(encoding="utf-8") if (HERE / ".env").exists() else ""
    _has_hf_key = "HIGGSFIELD_API_KEY=" in _env_hf and "HIGGSFIELD_API_KEY=\n" not in _env_hf
    _hf_placeholder = "dein_api_key" in _env_hf or "YOUR_KEY" in _env_hf.upper()

    if _has_hf_key and not _hf_placeholder:
        _ok("Higgsfield API-Key", "gesetzt — Tool 'higgsfield_video' verfügbar")
    else:
        print(f"  {GY}https://cloud.higgsfield.ai/api-keys  — 10 Credits/Tag gratis{R}")
        print(f"  {GY}Modelle: dop-lite (3 Credits), dop-preview (6), dop-turbo (9){R}")
        try:
            _hf_input = input(f"  {CY}Higgsfield API-Key (Enter = überspringen):{R} ").strip()
        except (EOFError, KeyboardInterrupt):
            _hf_input = ""
        if _hf_input and len(_hf_input) > 8:
            with open(HERE / ".env", "a", encoding="utf-8") as _ef:
                _ef.write(f"\nHIGGSFIELD_API_KEY={_hf_input}\n")
            _ok("Higgsfield API-Key", "gesetzt — 'higgsfield_video' Tool aktiv")
        else:
            _warn("Higgsfield übersprungen", "HIGGSFIELD_API_KEY in .env eintragen um Cloud-Videos zu nutzen")

    # ── Abschluss ───────────────────────────────────────────────────
    if quiet:
        if all_ok:
            print(f"  {GR}✓{R}  Alle Systeme bereit.")
        else:
            print(f"  {YL}!{R}  Setup-Probleme — siehe Hinweise oben.")
        print()
    else:
        print()
        if all_ok:
            print(f"  {GR}{B}Alles bereit.{R}")
        else:
            print(f"  {YL}Setup unvollstaendig — pruefe die Eintraege oben.{R}")
        print(f"  {CY}{'─' * 50}{R}")
        print()

    return all_ok


if __name__ == "__main__":
    run()
