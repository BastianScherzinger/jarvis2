"""
qa_security.py — Eigenständiges Qualitäts-, Sicherheits- und Upgrade-Verfahren für JARVIS.

Dieses Modul läuft SEPARAT vom Flask-Dashboard und prüft das gesamte Projekt:
  1. compile_all()      — kompiliert alle .py-Dateien (Syntaxprüfung)
  2. security_scan()    — Regex-Scan auf riskante Code-Muster
  3. dependency_check() — best-effort-Abgleich requirements.txt <-> installierte Versionen
  4. run_all()          — alles zusammen als dict
  5. report_text()      — menschenlesbarer ASCII-Report

Nur Standardbibliothek + optional importlib.metadata. Keine neuen pip-Deps.
Ausführbar als Skript:  python qa_security.py
"""

from __future__ import annotations

import py_compile
import re
import time
import traceback
from pathlib import Path

# Wurzelverzeichnis = Ordner dieser Datei
ROOT = Path(__file__).parent.resolve()

# Ordner die beim Scan/Compile komplett übersprungen werden.
# web_* wird zusätzlich als Präfix behandelt (siehe _is_excluded).
EXCLUDED_DIRS: set[str] = {
    ".git", "__pycache__", "node_modules", "vorlage_landing",
    "shop_vorlage", "reference_sites", "venv", ".venv", "env",
}
# Präfixe (z.B. web_app, web_build) ebenfalls ausschließen
EXCLUDED_PREFIXES: tuple[str, ...] = ("web_",)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
def _is_excluded(path: Path) -> bool:
    """True, wenn irgendein Pfad-Bestandteil ausgeschlossen ist."""
    for part in path.relative_to(ROOT).parts:
        if part in EXCLUDED_DIRS:
            return True
        for pref in EXCLUDED_PREFIXES:
            if part.startswith(pref):
                return True
    return False


def _iter_py_files() -> list[Path]:
    """Alle relevanten .py-Dateien im Projekt (rekursiv, gefiltert)."""
    files: list[Path] = []
    for p in ROOT.rglob("*.py"):
        if p.is_file() and not _is_excluded(p):
            # qa_security.py selbst nicht scannen (würde eigene Regex-Muster matchen)
            if p.resolve() == Path(__file__).resolve():
                continue
            files.append(p)
    return sorted(files)


def _rel(path: Path) -> str:
    """Pfad relativ zur Wurzel als String (für Reports)."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# 1. Kompilierung
# ---------------------------------------------------------------------------
def compile_all() -> dict:
    """
    Kompiliert alle Projekt-.py-Dateien via py_compile (doraise=True).
    Gibt {ok: bool, fehler: [{file, error}]}.
    """
    fehler: list[dict] = []
    for f in _iter_py_files():
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError as exc:
            # Saubere, kurze Fehlermeldung
            fehler.append({"file": _rel(f), "error": str(exc).strip()})
        except Exception as exc:  # robust: jede Datei einzeln absichern
            fehler.append({"file": _rel(f), "error": f"{type(exc).__name__}: {exc}"})
    return {"ok": len(fehler) == 0, "fehler": fehler}


# ---------------------------------------------------------------------------
# 2. Sicherheits-Scan
# ---------------------------------------------------------------------------
# Jede Regel: (regel, schwere, compiled_regex, optional_predicate)
# predicate(line) -> True wenn das Match GÜLTIG ist (False = False-Positive verwerfen)

# eval(/exec( als echter Aufruf (Wortgrenze davor), aber nicht ast.literal_eval o.ä.
_RE_EVAL_EXEC = re.compile(r"(?<![\w.])(eval|exec)\s*\(")
# subprocess ... shell=True
_RE_SHELL_TRUE = re.compile(r"shell\s*=\s*True")
# pickle.load( / pickle.loads(
_RE_PICKLE = re.compile(r"\bpickle\s*\.\s*loads?\s*\(")
# yaml.load( ohne SafeLoader-Hinweis (Loader-Prüfung im Predicate)
_RE_YAML_LOAD = re.compile(r"\byaml\s*\.\s*load\s*\(")
# os.system(
_RE_OS_SYSTEM = re.compile(r"\bos\s*\.\s*system\s*\(")
# verify=False (requests)
_RE_VERIFY_FALSE = re.compile(r"verify\s*=\s*False")
# debug=True in app.run / run(
_RE_DEBUG_TRUE = re.compile(r"\.run\s*\([^)]*debug\s*=\s*True")

# Hardcoded Secrets:
#   - API_KEY / PASSWORD / SECRET / TOKEN = "langes Literal"
_RE_SECRET_ASSIGN = re.compile(
    r"""(?ix)
    \b(api[_-]?key|password|passwd|secret|token|access[_-]?key)\b
    \s*[:=]\s*
    ['"][^'"]{8,}['"]          # String-Literal mit >=8 Zeichen
    """
)
#   - sk-... (Anthropic/OpenAI-Style Key) als Literal
_RE_SK_KEY = re.compile(r"""['"]sk-[A-Za-z0-9_\-]{16,}['"]""")

# Marker, die anzeigen dass eine "Secret"-Zeile nur aus der Umgebung/.env liest
_ENV_READ_MARKERS = (
    "os.environ", "os.getenv", "getenv(", "environ.get",
    "load_dotenv", "dotenv", ".env", "config.", "settings.",
    "getpass", "input(",
)
# Platzhalter-Werte, die keine echten Secrets sind
_SECRET_PLACEHOLDERS = (
    "sk-ant-...", "sk-...", "your", "xxx", "changeme", "placeholder",
    "example", "dummy", "<", "...", "todo", "none", "null", "test",
)


def _looks_like_env_read(line: str) -> bool:
    """True, wenn die Zeile ein Secret nur aus der Umgebung/.env bezieht."""
    low = line.lower()
    return any(marker in low for marker in _ENV_READ_MARKERS)


def _looks_like_placeholder(line: str) -> bool:
    """True, wenn das Literal ein offensichtlicher Platzhalter ist."""
    low = line.lower()
    return any(ph in low for ph in _SECRET_PLACEHOLDERS)


def _yaml_is_safe(line: str) -> bool:
    """True, wenn yaml.load erkennbar mit SafeLoader/safe_load benutzt wird."""
    low = line.lower()
    return "safeloader" in low or "loader=yaml.safe" in low or "safe_load" in low


def _scan_line(line: str) -> list[tuple[str, str]]:
    """
    Prüft eine einzelne Zeile gegen alle Regeln.
    Gibt Liste von (schwere, regel)-Tupeln zurück (kann mehrere sein).
    Kommentar-Zeilen werden ignoriert (reduziert False-Positives).
    """
    findings: list[tuple[str, str]] = []
    stripped = line.lstrip()

    # Reine Kommentar- ODER Prosa-/Listen-Zeilen überspringen (z.B. Sicherheits-
    # Hinweise INNERHALB von Agenten-Prompts in team.py — das ist kein Code).
    # Markdown-/Aufzählungs-Marker: '#', '-', '*', '>', Backtick oder '1.'/'2)' …
    if (stripped.startswith(("#", "- ", "* ", "> ", "`"))
            or re.match(r"^\d+[.)]\s", stripped)):
        return findings

    # eval(/exec(
    if _RE_EVAL_EXEC.search(line):
        findings.append(("HIGH", "eval/exec mit dynamischem Input"))

    # subprocess shell=True — nur bei echtem Aufruf-Kontext (kein Prosa-Treffer)
    if _RE_SHELL_TRUE.search(line) and re.search(r"(subprocess\.\w+|Popen|check_output|check_call)\s*\(", line):
        findings.append(("HIGH", "subprocess mit shell=True"))

    # pickle.load(s)
    if _RE_PICKLE.search(line):
        findings.append(("HIGH", "pickle.load ohne sichere Quelle"))

    # yaml.load ohne SafeLoader
    if _RE_YAML_LOAD.search(line) and not _yaml_is_safe(line):
        findings.append(("HIGH", "yaml.load ohne SafeLoader"))

    # os.system( — der leere Windows-ANSI-Idiom os.system("") ist harmlos
    if _RE_OS_SYSTEM.search(line) and not re.search(r"os\.system\(\s*['\"]\s*['\"]\s*\)", line):
        findings.append(("MEDIUM", "os.system Aufruf"))

    # verify=False
    if _RE_VERIFY_FALSE.search(line):
        findings.append(("MEDIUM", "requests verify=False (TLS deaktiviert)"))

    # debug=True
    if _RE_DEBUG_TRUE.search(line):
        findings.append(("LOW", "Flask debug=True in app.run"))

    # Hardcoded Secrets — nur wenn KEIN env-read und KEIN Platzhalter
    if not _looks_like_env_read(line) and not _looks_like_placeholder(line):
        if _RE_SECRET_ASSIGN.search(line) or _RE_SK_KEY.search(line):
            findings.append(("MEDIUM", "Möglicherweise hardcoded Secret"))

    return findings


def security_scan() -> list[dict]:
    """
    Durchsucht alle Projekt-.py-Dateien zeilenweise auf riskante Muster.
    Gibt Liste von Findings [{file, line, schwere, regel, code}].
    """
    findings: list[dict] = []
    for f in _iter_py_files():
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            # Datei nicht lesbar -> überspringen (robust)
            continue
        for nr, line in enumerate(text.splitlines(), start=1):
            for schwere, regel in _scan_line(line):
                findings.append({
                    "file": _rel(f),
                    "line": nr,
                    "schwere": schwere,
                    "regel": regel,
                    "code": line.strip()[:160],
                })
    return findings


# ---------------------------------------------------------------------------
# 3. Dependency-Check (best effort, KEIN Netzwerk)
# ---------------------------------------------------------------------------
# Trennzeichen für Versions-Constraints in requirements.txt
_REQ_SPLIT = re.compile(r"(==|>=|<=|~=|!=|>|<)")


def _parse_requirement(raw: str) -> tuple[str, str] | None:
    """
    Zerlegt eine requirements-Zeile in (paket, gefordert).
    Gibt None für Kommentare/leere/Optionen-Zeilen (-r, -e, --hash, etc.).
    """
    line = raw.strip()
    if not line or line.startswith("#") or line.startswith("-"):
        return None
    # Inline-Kommentar und Umgebungs-Marker abschneiden
    line = line.split("#", 1)[0].split(";", 1)[0].strip()
    if not line:
        return None
    # Extras entfernen: paket[extra]==1.0 -> paket
    name_part = line
    constraint = ""
    m = _REQ_SPLIT.search(line)
    if m:
        name_part = line[:m.start()].strip()
        constraint = line[m.start():].strip()
    name = re.split(r"[\[<>=!~ ]", name_part, maxsplit=1)[0].strip()
    if not name:
        return None
    return name, (constraint or "(beliebig)")


def dependency_check() -> list[dict]:
    """
    Liest requirements.txt und prüft installierte Versionen via importlib.metadata.
    KEIN Netzwerkzugriff. Gibt [{paket, gefordert, installiert, status}].
    """
    ergebnis: list[dict] = []
    req_file = ROOT / "requirements.txt"
    if not req_file.exists():
        return ergebnis

    # importlib.metadata ist seit Python 3.8 in der Standardbibliothek
    try:
        from importlib import metadata as ilm
    except Exception:
        return ergebnis

    try:
        lines = req_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ergebnis

    for raw in lines:
        parsed = _parse_requirement(raw)
        if not parsed:
            continue
        paket, gefordert = parsed
        try:
            installiert = ilm.version(paket)
            status = "installiert"
            # Bei exakter ==-Anforderung Mismatch erkennen
            if gefordert.startswith("=="):
                soll = gefordert[2:].strip()
                if soll and soll != installiert:
                    status = "version-abweichung"
        except ilm.PackageNotFoundError:
            installiert = "-"
            status = "fehlt"
        except Exception:
            installiert = "?"
            status = "unbekannt"
        ergebnis.append({
            "paket": paket,
            "gefordert": gefordert,
            "installiert": installiert,
            "status": status,
        })
    return ergebnis


# ---------------------------------------------------------------------------
# 4. Gesamtlauf
# ---------------------------------------------------------------------------
def run_all() -> dict:
    """Führt alle drei Prüfungen aus und liefert ein zusammengefasstes dict."""
    compile_res = compile_all()
    security_res = security_scan()
    deps_res = dependency_check()

    high = sum(1 for f in security_res if f["schwere"] == "HIGH")
    medium = sum(1 for f in security_res if f["schwere"] == "MEDIUM")
    low = sum(1 for f in security_res if f["schwere"] == "LOW")

    return {
        "compile": compile_res,
        "security": security_res,
        "dependencies": deps_res,
        "summary": {
            "compile_ok": compile_res["ok"],
            "high": high,
            "medium": medium,
            "low": low,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    }


# ---------------------------------------------------------------------------
# 5. Report
# ---------------------------------------------------------------------------
def _ampel(ok: bool) -> str:
    """Ampel-Marker [OK]/[!!]."""
    return "[OK]" if ok else "[!!]"


def _schwere_marker(schwere: str) -> str:
    """Marker je Schweregrad."""
    return {"HIGH": "[!!]", "MEDIUM": "[!]", "LOW": "[i]"}.get(schwere, "[?]")


def report_text() -> str:
    """Erzeugt einen menschenlesbaren ASCII-Report."""
    try:
        data = run_all()
    except Exception:
        # Absolute Sicherheit: niemals crashen
        return "QA/Security-Lauf fehlgeschlagen:\n" + traceback.format_exc()

    s = data["summary"]
    out: list[str] = []
    line = "=" * 70

    out.append(line)
    out.append("  JARVIS — QA / SECURITY / UPGRADE REPORT")
    out.append(f"  Zeitstempel: {s['ts']}")
    out.append(f"  Wurzel: {ROOT}")
    out.append(line)
    out.append("")

    # --- Übersicht ---
    out.append("UEBERSICHT")
    out.append("-" * 70)
    out.append(f"  {_ampel(s['compile_ok'])} Kompilierung: "
               f"{'alle Dateien OK' if s['compile_ok'] else 'FEHLER vorhanden'}")
    out.append(f"  {_ampel(s['high'] == 0)} Sicherheit HIGH   : {s['high']}")
    out.append(f"  {_ampel(s['medium'] == 0)} Sicherheit MEDIUM : {s['medium']}")
    out.append(f"  {'[OK]' if s['low'] == 0 else '[i]'} Sicherheit LOW    : {s['low']}")
    out.append("")

    # --- Kompilierung ---
    out.append("1) KOMPILIERUNG")
    out.append("-" * 70)
    comp = data["compile"]
    if comp["ok"]:
        out.append("  [OK] Alle Python-Dateien kompilieren fehlerfrei.")
    else:
        out.append(f"  [!!] {len(comp['fehler'])} Datei(en) mit Syntaxfehlern:")
        for fehler in comp["fehler"]:
            out.append(f"       - {fehler['file']}")
            for zeile in str(fehler["error"]).splitlines():
                out.append(f"           {zeile}")
    out.append("")

    # --- Sicherheit ---
    out.append("2) SICHERHEITS-SCAN")
    out.append("-" * 70)
    sec = data["security"]
    if not sec:
        out.append("  [OK] Keine riskanten Muster gefunden.")
    else:
        # Nach Schwere sortiert ausgeben (HIGH zuerst)
        rang = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        for fnd in sorted(sec, key=lambda x: (rang.get(x["schwere"], 9), x["file"], x["line"])):
            out.append(f"  {_schwere_marker(fnd['schwere'])} "
                       f"[{fnd['schwere']}] {fnd['file']}:{fnd['line']} — {fnd['regel']}")
            out.append(f"        > {fnd['code']}")
    out.append("")

    # --- Dependencies ---
    out.append("3) DEPENDENCY-CHECK")
    out.append("-" * 70)
    deps = data["dependencies"]
    if not deps:
        out.append("  [i] Keine requirements.txt gefunden oder keine prüfbaren Pakete.")
    else:
        out.append(f"  {'PAKET':<28} {'GEFORDERT':<14} {'INSTALLIERT':<14} STATUS")
        out.append("  " + "-" * 66)
        for d in deps:
            marker = {
                "installiert": "[OK]",
                "version-abweichung": "[!]",
                "fehlt": "[!!]",
            }.get(d["status"], "[?]")
            out.append(f"  {marker} {d['paket']:<24} {d['gefordert']:<14} "
                       f"{d['installiert']:<14} {d['status']}")
    out.append("")

    out.append(line)
    out.append("  Ende des Reports.")
    out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 6. Skript-Einstieg
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(report_text())
