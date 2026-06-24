"""
JARVIS Startup Check
Prueft und richtet alle Abhaengigkeiten ein, bevor der Server startet.
Wird automatisch von app.py ausgefuehrt.
"""
import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

# UTF-8 erzwingen damit Sonderzeichen funktionieren
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ANSI (werden von jarvis_log geladen -- hier minimal definiert)
_R  = "\033[0m"
_B  = "\033[1m"
_GR = "\033[92m"
_RD = "\033[91m"
_YL = "\033[93m"
_CY = "\033[96m"
_GY = "\033[90m"

_OK   = "[OK]"
_WARN = "[!] "
_FAIL = "[X] "
_DL   = "[>] "

def _ok(label: str, info: str = "") -> None:
    info_str = f"  {_GY}{info}{_R}" if info else ""
    print(f"  {_GR}{_OK}{_R}  {label:<32}{info_str}", flush=True)

def _warn(label: str, info: str = "") -> None:
    info_str = f"  {_GY}{info}{_R}" if info else ""
    print(f"  {_YL}{_WARN}{_R}  {label:<32}{info_str}", flush=True)

def _fail(label: str, info: str = "") -> None:
    info_str = f"  {_GY}{info}{_R}" if info else ""
    print(f"  {_RD}{_FAIL}{_R}  {label:<32}{info_str}", flush=True)

def _installing(label: str) -> None:
    print(f"  {_CY}{_DL}{_R}  {label:<32}  {_GY}installiere...{_R}", flush=True)

def _pip_install(package: str) -> bool:
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", package, "-q"],
            check=True, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False

def _pkg_version(pkg: str) -> str | None:
    try:
        mod = importlib.import_module(pkg.replace("-", "_"))
        return getattr(mod, "__version__", "✓")
    except ImportError:
        return None

# ── Einzelne Checks ──────────────────────────────────────────────

def _check_python() -> bool:
    v = sys.version_info
    label = "Python"
    info  = f"{v.major}.{v.minor}.{v.micro}"
    if v >= (3, 10):
        _ok(label, info)
        return True
    _warn(label, f"{info}  (empfohlen: 3.10+)")
    return True

def _check_package(import_name: str, pip_name: str, label: str, auto_install: bool = True) -> bool:
    ver = _pkg_version(import_name)
    if ver:
        _ok(label, ver)
        return True
    if auto_install:
        _installing(label)
        if _pip_install(pip_name):
            ver = _pkg_version(import_name) or "installiert"
            _ok(label, ver)
            return True
    _fail(label, f"pip install {pip_name}")
    return False

def _check_anthropic_key() -> bool:
    key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_KEY", "")
    if key:
        _ok("Anthropic API Key", key[:12] + "..." + key[-4:] if len(key) > 16 else "***")
        return True
    _fail("Anthropic API Key", "ANTHROPIC_KEY in .env setzen")
    return False

def _check_playwright() -> bool:
    # 1) Package vorhanden?
    ver = _pkg_version("playwright")
    if not ver:
        _installing("playwright (Browser-Kontrolle)")
        if not _pip_install("playwright"):
            _fail("playwright", "pip install playwright")
            return False
        ver = _pkg_version("playwright") or "installiert"

    # 2) Browser-Executables vorhanden?
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
                browser.close()
                _ok("playwright + Chromium", ver)
                return True
            except Exception:
                pass
    except Exception:
        pass

    # Browser noch nicht installiert → automatisch installieren
    _warn("playwright Browser", "Chromium wird installiert...")
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium", "--with-deps"],
            check=True, capture_output=True, timeout=180,
        )
        _ok("playwright + Chromium", ver)
        return True
    except Exception as e:
        _fail("playwright Chromium", f"manuell: playwright install chromium")
        return False

def _check_edge_tts() -> bool:
    return _check_package("edge_tts", "edge-tts", "TTS (edge-tts)")

def _check_elevenlabs() -> None:
    key = os.environ.get("ELEVENLABS_KEY", "").strip()
    if key:
        _ok("ElevenLabs TTS (premium)", key[:8] + "...")
    else:
        voice = os.environ.get("JARVIS_VOICE", "de-DE-ConradNeural")
        _ok("TTS-Stimme", voice)

def _check_workspace() -> bool:
    workspace = Path(__file__).parent / "workspace"
    workspace_tasks   = workspace / "tasks"
    workspace_results = workspace / "results"
    for d in [workspace, workspace_tasks, workspace_results]:
        d.mkdir(exist_ok=True)
    _ok("Workspace", str(workspace))
    return True

def _check_ffmpeg() -> bool:
    try:
        r = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0:
            version_line = r.stdout.split("\n")[0]
            ver = version_line.split("version")[1].strip().split()[0] if "version" in version_line else "OK"
            _ok("ffmpeg (Sprachkonvertierung)", ver)
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    _warn("ffmpeg", "nicht gefunden — Stimmerkennung eingeschränkt")
    return False

def _check_speech_recognition() -> bool:
    return _check_package("speech_recognition", "SpeechRecognition", "speech_recognition")

def _check_higgsfield_mcp() -> None:
    """Meldet, ob die Higgsfield-MCP-Anbindung (Abo-Credits) angemeldet ist. Löst KEINEN
    Login aus (das macht der Startup-Cleanup in app.py) — reine Statusanzeige."""
    try:
        import higgsfield_mcp
        if higgsfield_mcp.is_authorized():
            _ok("Higgsfield (Abo via MCP)", "angemeldet")
        else:
            _warn("Higgsfield (Abo via MCP)", "Login beim Start (Browser bestaetigen)")
    except Exception:
        _warn("Higgsfield (Abo via MCP)", "Modul nicht ladbar")


# ── Pipeline-Checks (Webseiten bauen + verbessern + deployen) ────────────────

def _check_node() -> bool:
    """Node.js/npm — Voraussetzung, um die claude-CLI (Makeover) zu installieren."""
    node = shutil.which("node") or shutil.which("node.exe")
    npm  = shutil.which("npm") or shutil.which("npm.cmd")
    if node and npm:
        try:
            r = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=5)
            _ok("Node.js / npm", (r.stdout or "").strip() or "vorhanden")
        except Exception:
            _ok("Node.js / npm", "vorhanden")
        return True
    _warn("Node.js / npm", "fehlt — claude-CLI nicht installierbar (Makeover aus)")
    return False


def _check_claude_cli() -> bool:
    """Claude Code CLI — Herzstueck des 7-Stufen-Makeovers. Ohne sie kann keine Seite
    verbessert werden."""
    cmd = shutil.which("claude.cmd") or shutil.which("claude.exe") or shutil.which("claude")
    if not cmd:
        _fail("Claude Code CLI (Makeover)", "npm i -g @anthropic-ai/claude-code")
        return False
    try:
        r = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=20)
        ver = (r.stdout or "").strip().splitlines()[0][:40] if r.stdout else "installiert"
        _ok("Claude Code CLI (Makeover)", ver or "installiert")
        return True
    except Exception:
        _warn("Claude Code CLI (Makeover)", "vorhanden, Version nicht lesbar")
        return True


def _check_git() -> bool:
    """git — noetig fuer den Webseiten-Deploy (GitHub/Railway)."""
    try:
        r = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            _ok("git (Deploy)", r.stdout.strip().replace("git version ", ""))
            return True
    except Exception:
        pass
    _fail("git (Deploy)", "https://git-scm.com/download/win")
    return False


def _check_ollama() -> bool:
    """Ollama — lokale KI (Lead-Bewertung, Build-Texte, Hero-Prompts). Zeigt Modelle."""
    import json as _json
    import urllib.request
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            data = _json.loads(r.read().decode("utf-8"))
        models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        if models:
            extra = ", ".join(models[:3]) + ("…" if len(models) > 3 else "")
            _ok("Ollama (lokale KI)", f"{len(models)} Modelle: {extra}")
        else:
            _warn("Ollama (lokale KI)", "laeuft, aber keine Modelle (ollama pull qwen2.5:7b)")
        return True
    except Exception:
        _warn("Ollama (lokale KI)", "nicht erreichbar — 'ollama serve' starten")
        return False


def _check_skills() -> None:
    """Makeover-Skills (design-pro/taste) im user-globalen ~/.claude/skills/-Ordner —
    der headless Makeover-Claude laeuft im Seiten-Ordner und sieht nur diese."""
    base = Path.home() / ".claude" / "skills"
    want = ["design-pro", "design-taste-frontend"]
    have = [w for w in want if (base / w).is_dir()]
    if len(have) == len(want):
        _ok("Makeover-Skills", ", ".join(have))
    elif have:
        _warn("Makeover-Skills", f"{len(have)}/{len(want)} da — fehlt: {', '.join(set(want) - set(have))}")
    else:
        _warn("Makeover-Skills", "nicht installiert (wird beim Start gespiegelt)")


def _check_deploy() -> None:
    """Deploy-Bereitschaft: GitHub + Railway + git zusammen (best-effort, kann kurz dauern)."""
    try:
        import website_builder
        s = website_builder.deploy_status()
        if s.get("ready"):
            _ok("Deploy (GitHub + Railway)", "bereit")
        else:
            offen = []
            if not (s.get("github") or {}).get("ok"):  offen.append("GitHub")
            if not (s.get("railway") or {}).get("ok"): offen.append("Railway")
            if not s.get("git"):                        offen.append("git")
            _warn("Deploy-Bereitschaft", "offen: " + (", ".join(offen) or "unklar"))
    except Exception as e:
        _warn("Deploy-Bereitschaft", f"nicht pruefbar: {type(e).__name__}")


def _check_data_writable() -> bool:
    """data/ muss beschreibbar sein (Kosten, Budget, Limit-State, Logs)."""
    d = Path(__file__).parent / "data"
    try:
        d.mkdir(exist_ok=True)
        t = d / ".write_test"
        t.write_text("ok", encoding="utf-8")
        t.unlink()
        _ok("Daten-Verzeichnis schreibbar", str(d))
        return True
    except Exception as e:
        _fail("Daten-Verzeichnis", f"nicht schreibbar: {type(e).__name__}")
        return False


def _check_databases() -> bool:
    """Kern-Datenbanken initialisierbar (Leads roh/bewertet, Webseiten)."""
    try:
        import db_raw, db_evaluated, db_websites
        db_raw.init_db(); db_evaluated.init_db(); db_websites.init_db()
        _ok("Datenbanken", "raw · evaluated · websites")
        return True
    except Exception as e:
        _fail("Datenbanken", f"{type(e).__name__}: {str(e)[:40]}")
        return False

# ── Haupt-Check ──────────────────────────────────────────────────

def run() -> dict[str, bool]:
    """
    Führt alle Checks aus. Gibt Status-Dict zurück.
    Gibt bei Fehler eine Warning aus, stoppt den Server aber nicht.
    """
    print()
    print(f"  {_CY}{'=' * 52}{_R}")
    print(f"  {_CY}  {_B}JARVIS  Startup Check{_R}")
    print(f"  {_CY}{'=' * 52}{_R}")
    print()

    results = {}

    print(f"  {_GY}— Grundsystem —{_R}")
    results["python"]           = _check_python()
    results["data_writable"]    = _check_data_writable()
    results["databases"]        = _check_databases()

    print()
    print(f"  {_GY}— Webseiten-Pipeline (bauen · verbessern · deployen) —{_R}")
    results["node"]             = _check_node()
    results["claude_cli"]       = _check_claude_cli()
    _check_skills()
    results["git"]              = _check_git()
    results["ollama"]           = _check_ollama()
    _check_deploy()
    _check_higgsfield_mcp()

    print()
    print(f"  {_GY}— KI-Schluessel & Medien —{_R}")
    results["anthropic_key"]    = _check_anthropic_key()

    print()
    print(f"  {_GY}— Sprache & Browser —{_R}")
    results["speech_rec"]       = _check_speech_recognition()
    results["ffmpeg"]           = _check_ffmpeg()
    results["edge_tts"]         = _check_edge_tts()
    _check_elevenlabs()
    results["playwright"]       = _check_playwright()
    results["workspace"]        = _check_workspace()

    # Zusammenfassung
    ok    = sum(1 for v in results.values() if v)
    total = len(results)
    print()
    if ok == total:
        print(f"  {_GR}{_B}Alle {total} Checks OK -- JARVIS voll einsatzbereit.{_R}")
    else:
        failed = total - ok
        print(f"  {_YL}{ok}/{total} OK{_R}  {_GY}({failed} Warnung(en)){_R}")
    print()
    print(f"  {_CY}{'=' * 52}{_R}")
    print()

    return results
