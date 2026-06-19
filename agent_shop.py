"""
Shop-Bau-Tool für den Claude-Dashboard-Agenten.

Kopiert die mitgelieferte Vorlage shop_vorlage/ (Railway-ready Django) zu einem neuen
Projekt und erlaubt das gezielte Anpassen einzelner Dateien. Alle Dateioperationen
sind auf SHOP_BASE (Standard: Desktop) beschränkt — Schutz gegen Path-Traversal.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

HERE      = Path(__file__).parent
VORLAGE   = HERE / "shop_vorlage"
SHOP_BASE = Path(os.environ.get("JARVIS_SHOP_DIR", str(Path.home() / "Desktop")))

_INVALID = set('<>:"|?*')


def is_available() -> bool:
    return VORLAGE.exists()


def _safe(rel: str) -> "Path | None":
    """Löst einen Pfad relativ zu SHOP_BASE auf und stellt sicher, dass er INNERHALB
    von SHOP_BASE bleibt (kein Ausbruch via ../). Gibt None bei Verstoß zurück."""
    try:
        base = SHOP_BASE.resolve()
        p = (base / (rel or "")).resolve()
        if p == base or str(p).startswith(str(base) + os.sep):
            return p
    except Exception:
        pass
    return None


def skill() -> str:
    doc = HERE / "skills" / "shop_bauen.md"
    try:
        return doc.read_text(encoding="utf-8")
    except Exception:
        return "Skill-Doku (skills/shop_bauen.md) nicht gefunden."


def shop_new(name: str) -> str:
    name = (name or "").strip().strip("/\\ ")
    if not name or any(c in name for c in _INVALID) or name in (".", ".."):
        return "Ungültiger Projektname."
    if not VORLAGE.exists():
        return "Vorlage shop_vorlage/ fehlt im Projekt."
    target = _safe(name)
    if target is None:
        return "Pfad außerhalb des erlaubten Shop-Bereichs."
    if target.exists():
        return (f"Ordner '{name}' existiert bereits unter {SHOP_BASE}. "
                f"Anderen Namen wählen oder die Dateien direkt mit shop_write bearbeiten.")
    try:
        shutil.copytree(VORLAGE, target)
    except Exception as e:
        return f"Kopieren fehlgeschlagen: {type(e).__name__}: {e}"
    n = sum(1 for _ in target.rglob("*") if _.is_file())
    return (f"Shop-Projekt '{name}' aus der Vorlage erstellt: {target} ({n} Dateien).\n"
            f"Jetzt anpassen (Pfade relativ, z.B. '{name}/config/settings.py'):\n"
            f"- config/settings.py → SITE_NAME, SITE_URL\n"
            f"- static/css/variables.css → Theme/Akzentfarbe\n"
            f"- templates/base.html + templates/components/navbar.html → Branding\n"
            f"- templates/home.html → Inhalte/Hero\n"
            f"Danach lokal: python manage.py check")


def fs_list(rel: str = "") -> str:
    p = _safe(rel or ".")
    if p is None or not p.exists():
        return "Pfad nicht gefunden oder außerhalb des Shop-Bereichs."
    if p.is_file():
        return f"(Datei) {rel}"
    rows = []
    for c in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        rows.append(("[D] " if c.is_dir() else "    ") + c.name)
    return "\n".join(rows[:300]) or "(leer)"


def fs_read(rel: str) -> str:
    p = _safe(rel)
    if p is None or not p.is_file():
        return "Datei nicht gefunden oder außerhalb des Shop-Bereichs."
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:20000]
    except Exception as e:
        return f"Lesefehler: {type(e).__name__}"


def git_push(name: str, repo_url: str, message: str = "Initiales Shop-Projekt") -> str:
    """git init → commit → push für ein Shop-Projekt. repo_url muss vom Nutzer kommen."""
    target = _safe((name or "").strip().strip("/\\ "))
    if target is None or not target.is_dir():
        return "Projekt nicht gefunden — erst shop_new(name) ausführen."
    repo_url = (repo_url or "").strip()
    if not (repo_url.startswith("https://github.com/") or repo_url.startswith("git@")):
        return "Bitte eine gültige GitHub-Repo-URL angeben (https://github.com/<user>/<repo>.git)."

    # LF-Zeilenenden für .sh erzwingen (Railway-Container)
    try:
        (target / ".gitattributes").write_text("*.sh text eol=lf\n", encoding="utf-8")
    except Exception:
        pass

    def _run(args: list) -> "subprocess.CompletedProcess":
        return subprocess.run(["git", *args], cwd=str(target),
                              capture_output=True, text=True, timeout=180)
    try:
        if not (target / ".git").exists():
            _run(["init"])
            _run(["branch", "-M", "main"])
        _run(["add", "-A"])
        _run(["commit", "-m", message or "Initiales Shop-Projekt"])
        if _run(["remote", "add", "origin", repo_url]).returncode != 0:
            _run(["remote", "set-url", "origin", repo_url])
        push = _run(["push", "-u", "origin", "main"])
        if push.returncode == 0:
            return f"✓ Nach {repo_url} gepusht (Branch main). Jetzt auf Railway 'Deploy from GitHub'."
        return ("Push fehlgeschlagen: " + (push.stderr or push.stdout or "")[:300]
                + "\n(Existiert das Repo auf GitHub? Sind die Zugangsdaten gesetzt?)")
    except Exception as e:
        return f"Git-Fehler: {type(e).__name__}: {str(e)[:200]}"


def fs_write(rel: str, content: str) -> str:
    p = _safe(rel)
    if p is None:
        return "Pfad außerhalb des erlaubten Shop-Bereichs."
    if p.exists() and p.is_dir():
        return "Pfad ist ein Ordner, keine Datei."
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # .sh-Skripte IMMER mit LF speichern (sonst bricht der Linux-Container).
        newline = "\n" if p.name.endswith(".sh") else None
        with open(p, "w", encoding="utf-8", newline=newline) as f:
            f.write(content or "")
        return f"Gespeichert: {rel} ({len(content or '')} Zeichen)."
    except Exception as e:
        return f"Schreibfehler: {type(e).__name__}: {e}"
