"""
local_tools.py — Werkzeugset für die lokale Coding-KI (Nightly-Improver / local_coder).

Gibt einem Ollama-Agenten ein kleines, atomares, sandboxed Toolset, um eine bereits
gebaute Landing-Page (content.json + Django-Template + CSS) sicher zu bearbeiten:
  read_file, write_file, list_dir, replace_in_file, read_content, write_content,
  compile_check (py_compile), render_check (Django-Template rendern), read_reference.

Alle Pfade sind auf den Seitenordner beschränkt (kein Path-Traversal). read_reference
liest aus reference_sites/ (nur lesen). Jedes Tool gibt einen kurzen String zurück
(Observation für die ReAct-Schleife) und wirft nie — Fehler werden als Text gemeldet.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_BASE = Path(__file__).parent
_REFERENCE_DIR = _BASE / "reference_sites"

# JSON-Tool-Definitionen (für den Agenten-System-Prompt / Tool-Calling).
TOOLS_SCHEMA = [
    {"name": "list_dir", "desc": "Listet Dateien/Ordner relativ zum Seitenordner.",
     "args": {"path": "Unterpfad, '' = Wurzel"}},
    {"name": "read_file", "desc": "Liest eine Textdatei (max 60 KB).",
     "args": {"path": "Pfad relativ zum Seitenordner"}},
    {"name": "write_file", "desc": "Schreibt/überschreibt eine Textdatei.",
     "args": {"path": "Pfad", "content": "kompletter neuer Inhalt"}},
    {"name": "replace_in_file", "desc": "Ersetzt EINE eindeutige Textstelle in einer Datei.",
     "args": {"path": "Pfad", "old": "exakter alter Text", "new": "neuer Text"}},
    {"name": "read_content", "desc": "Liest content.json als JSON-Objekt.", "args": {}},
    {"name": "write_content", "desc": "Schreibt das komplette content.json (JSON-Objekt).",
     "args": {"content": "vollständiges content.json-Objekt"}},
    {"name": "compile_check", "desc": "Prüft eine .py-Datei mit py_compile.", "args": {"path": "Pfad"}},
    {"name": "render_check", "desc": "Rendert das Django-Template mit content.json (Bug-Check).", "args": {}},
    {"name": "read_reference", "desc": "Liest eine Referenz-Beispielseite (content.json/HTML/CSS).",
     "args": {"name": "Ordnername unter reference_sites/, '' = Liste"}},
]


def list_references() -> list[str]:
    if not _REFERENCE_DIR.exists():
        return []
    return sorted(d.name for d in _REFERENCE_DIR.iterdir() if d.is_dir())


class SiteTools:
    """Sandboxed Werkzeuge für GENAU einen Seitenordner."""

    def __init__(self, folder: "str | Path"):
        self.root = Path(folder).resolve()
        if not self.root.is_dir():
            raise ValueError(f"Seitenordner nicht gefunden: {folder}")

    # ── Pfad-Sicherheit ──────────────────────────────────────────────────────
    def _safe(self, rel: str) -> Path:
        p = (self.root / (rel or "").lstrip("/\\")).resolve()
        if p != self.root and self.root not in p.parents:
            raise ValueError("Pfad außerhalb des Seitenordners ist nicht erlaubt.")
        return p

    # ── Tools ────────────────────────────────────────────────────────────────
    def list_dir(self, path: str = "") -> str:
        try:
            d = self._safe(path)
            if not d.is_dir():
                return f"[Fehler] kein Verzeichnis: {path}"
            eintraege = []
            for x in sorted(d.iterdir()):
                eintraege.append(("📁 " if x.is_dir() else "📄 ") + x.name)
            return "\n".join(eintraege) or "(leer)"
        except Exception as e:
            return f"[Fehler] {e}"

    def read_file(self, path: str) -> str:
        try:
            p = self._safe(path)
            if not p.is_file():
                return f"[Fehler] Datei fehlt: {path}"
            data = p.read_text(encoding="utf-8", errors="replace")
            return data[:60_000]
        except Exception as e:
            return f"[Fehler] {e}"

    def write_file(self, path: str, content: str) -> str:
        try:
            p = self._safe(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content if isinstance(content, str) else str(content), encoding="utf-8")
            return f"[OK] geschrieben: {path} ({len(content)} Zeichen)"
        except Exception as e:
            return f"[Fehler] {e}"

    def replace_in_file(self, path: str, old: str, new: str) -> str:
        try:
            p = self._safe(path)
            if not p.is_file():
                return f"[Fehler] Datei fehlt: {path}"
            txt = p.read_text(encoding="utf-8", errors="replace")
            n = txt.count(old)
            if n == 0:
                return "[Fehler] 'old' nicht gefunden — Text exakt kopieren."
            if n > 1:
                return f"[Fehler] 'old' {n}× vorhanden — mehr Kontext für Eindeutigkeit geben."
            p.write_text(txt.replace(old, new, 1), encoding="utf-8")
            return f"[OK] ersetzt in {path}"
        except Exception as e:
            return f"[Fehler] {e}"

    def read_content(self) -> str:
        return self.read_file("content.json")

    def write_content(self, content) -> str:
        try:
            if isinstance(content, str):
                content = json.loads(content)        # Modell gab JSON-Text
            if not isinstance(content, dict) or not content.get("site_name"):
                return "[Fehler] content muss ein JSON-Objekt mit 'site_name' sein."
            self._safe("content.json").write_text(
                json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
            return "[OK] content.json geschrieben"
        except Exception as e:
            return f"[Fehler] {e}"

    def compile_check(self, path: str) -> str:
        try:
            import py_compile
            p = self._safe(path)
            if not p.is_file():
                return f"[Fehler] Datei fehlt: {path}"
            py_compile.compile(str(p), doraise=True)
            return f"[OK] {path} kompiliert fehlerfrei"
        except Exception as e:
            return f"[Compile-Fehler] {e}"

    def render_check(self) -> str:
        """Rendert templates/index.html mit content.json (fängt Template-Bugs)."""
        try:
            import website_improve
            content = {}
            cj = self._safe("content.json")
            if cj.is_file():
                content = json.loads(cj.read_text(encoding="utf-8"))
            ok, fehler = website_improve._render_check(self.root, content)
            return "[OK] Template rendert fehlerfrei" if ok else f"[Render-Fehler] {fehler}"
        except Exception as e:
            return f"[Fehler] {e}"

    def read_reference(self, name: str = "") -> str:
        refs = list_references()
        if not name:
            return "Verfügbare Referenzen: " + (", ".join(refs) or "(keine)")
        if name not in refs:
            return f"[Fehler] unbekannte Referenz. Verfügbar: {', '.join(refs)}"
        d = _REFERENCE_DIR / name
        cj = d / "content.json"
        out = [f"# Referenz {name}"]
        if cj.is_file():
            out.append("content.json:\n" + cj.read_text(encoding="utf-8", errors="replace")[:6000])
        return "\n".join(out)

    # ── Snapshot / Rollback (Sicherheitsnetz vor Tiefen-Edits) ──────────────
    def snapshot(self) -> dict:
        """Sichert content.json + Templates + CSS als {relpfad: inhalt}. Damit kann
        ein fehlgeschlagener Feature-Bau vollständig zurückgerollt werden."""
        snap: dict = {}
        cj = self._safe("content.json")
        if cj.is_file():
            snap["content.json"] = cj.read_text(encoding="utf-8", errors="replace")
        for sub in ("templates", "static/css"):
            d = self._safe(sub)
            if d.is_dir():
                for f in sorted(d.rglob("*")):
                    if f.is_file() and f.suffix.lower() in (".html", ".css"):
                        snap[str(f.relative_to(self.root)).replace("\\", "/")] = \
                            f.read_text(encoding="utf-8", errors="replace")
        return snap

    def restore(self, snap: dict) -> None:
        """Stellt einen Snapshot wieder her (bei Regression)."""
        for rel, content in (snap or {}).items():
            try:
                p = self._safe(rel)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
            except Exception:
                pass

    # ── Dispatcher für die Agenten-Schleife ─────────────────────────────────
    def dispatch(self, name: str, args: dict) -> str:
        args = args or {}
        fn = {
            "list_dir":        lambda: self.list_dir(args.get("path", "")),
            "read_file":       lambda: self.read_file(args.get("path", "")),
            "write_file":      lambda: self.write_file(args.get("path", ""), args.get("content", "")),
            "replace_in_file": lambda: self.replace_in_file(args.get("path", ""), args.get("old", ""), args.get("new", "")),
            "read_content":    lambda: self.read_content(),
            "write_content":   lambda: self.write_content(args.get("content", {})),
            "compile_check":   lambda: self.compile_check(args.get("path", "")),
            "render_check":    lambda: self.render_check(),
            "read_reference":  lambda: self.read_reference(args.get("name", "")),
        }.get(name)
        if fn is None:
            return f"[Fehler] unbekanntes Tool '{name}'. Erlaubt: {', '.join(t['name'] for t in TOOLS_SCHEMA)}"
        return fn()
