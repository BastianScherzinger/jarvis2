"""
JARVIS Startup Check
Prueft und richtet alle Abhaengigkeiten ein, bevor der Server startet.
Wird automatisch von app.py ausgefuehrt.
"""
import importlib
import os
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

    results["python"]           = _check_python()
    results["anthropic_key"]    = _check_anthropic_key()
    results["speech_rec"]       = _check_speech_recognition()
    results["ffmpeg"]           = _check_ffmpeg()
    results["edge_tts"]         = _check_edge_tts()
    _check_elevenlabs()
    results["playwright"]       = _check_playwright()
    results["workspace"]        = _check_workspace()
    _check_higgsfield_mcp()

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
