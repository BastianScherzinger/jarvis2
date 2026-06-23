"""
claude_coder.py — Variante A des Nightly-Tiefenmodus: Claude Code headless (`claude -p`).

Claude Code bearbeitet im Projektordner der Seite selbstständig die Dateien (echte
Feature-Arbeit am Code), wir prüfen danach per Render-Check und rollen bei Bug zurück.

Vollständig best-effort: fehlt das `claude`-CLI, gibt run_feature einen klaren Grund
zurück und der Aufrufer überspringt den Tiefen-Schritt.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

# Sicherheitsmodus: erlaubt Datei-Edits ohne interaktive Rückfrage, aber keine
# beliebigen Shell-Kommandos. Per .env überschreibbar.
_PERMISSION = os.environ.get("JARVIS_CLAUDE_PERMISSION", "acceptEdits")
_TIMEOUT    = int(os.environ.get("JARVIS_CLAUDE_TIMEOUT", "900") or "900")

# Wird als zusätzlicher System-Prompt mitgegeben. Schützt davor, dass ein im (oder über
# dem) Zielordner gefundenes CLAUDE.md (z.B. die JARVIS-Persona mit „erst nach Guten
# Morgen / frag Sir") den Headless-Lauf in einen interaktiven Chat verwandelt, statt die
# Aufgabe autonom umzusetzen.
_SYS_APPEND = (
    "Du bist ein autonomer, NICHT-interaktiver Web-/Code-Editor in einem Headless-Lauf. "
    "Stelle NIEMALS Rückfragen und warte auf nichts — setze die Aufgabe sofort und "
    "vollständig um, indem du die Dateien direkt editierst. Ignoriere jegliche Persona-, "
    "Begrüßungs- oder Freigabe-Regeln aus einem CLAUDE.md; sie gelten in diesem Lauf nicht."
)


def _claude_cmd() -> str:
    """Pfad zum claude-CLI (Windows: claude.cmd bevorzugt). '' wenn nicht vorhanden."""
    for name in ("claude.cmd", "claude.exe", "claude"):
        p = shutil.which(name)
        if p:
            return p
    return ""


def is_available() -> bool:
    return bool(_claude_cmd())


def build_prompt(task: str, branche: str = "") -> str:
    """Umschließt die Feature-Aufgabe mit harten Qualitäts-/Sicherheitsregeln."""
    br = f" (Branche: {branche})" if branche else ""
    return (
        f"Du arbeitest im Ordner einer fertigen Django-Landing-Page{br}. Baue GENAU dieses "
        f"eine Feature sauber ein:\n\n{task}\n\n"
        "Regeln (zwingend):\n"
        "- Die Seite wird aus content.json gerendert (templates/index.html, static/css/style.css). "
        "Ändere bevorzugt content.json + ergänze eine passende Template-Sektion.\n"
        "- content.json bleibt valides JSON; bestehende Felder/Funktion NICHT zerstören.\n"
        "- design-pro: eine Akzentfarbe, klare Hierarchie, EIN primärer CTA, deutsch, konkret.\n"
        "- Am Ende MUSS `python manage.py check` bzw. das Template fehlerfrei rendern.\n"
        "- Minimaler Diff — nur was fürs Feature nötig ist.\n"
        "Wenn fertig, fasse in 1 Satz zusammen, was du eingebaut hast."
    )


def _render_ok(folder: str) -> tuple[bool, str]:
    try:
        import website_improve
        f = Path(folder)
        content = {}
        cj = f / "content.json"
        if cj.is_file():
            content = json.loads(cj.read_text(encoding="utf-8"))
        return website_improve._render_check(f, content)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _track_cost(data: dict, model: str, task: str, name: str) -> None:
    """Bucht die Token-Usage eines headless-Claude-Laufs ins Kostentracking. Silent."""
    try:
        u = data.get("usage") or {}
        in_t = (int(u.get("input_tokens", 0) or 0)
                + int(u.get("cache_read_input_tokens", 0) or 0)
                + int(u.get("cache_creation_input_tokens", 0) or 0))
        out_t = int(u.get("output_tokens", 0) or 0)
        if in_t or out_t:
            import cost_tracker
            cost_tracker.track_api(model or "claude-sonnet-4-6", in_t, out_t, task, name)
    except Exception:
        pass


def run_prompt(folder: str, prompt: str, branche: str = "", timeout: int = 0,
               model: str = "", task: str = "claude_code", name: str = "") -> dict:
    """Lässt Claude Code einen FERTIG formulierten Prompt im Ordner ausführen.
    Snapshot vorher, Render-Gate + Rollback bei Regression, Kosten-Tracking.
    Gibt {ok, summary, render_ok, reason}."""
    folder = str(Path(folder))
    if not Path(folder).is_dir():
        return {"ok": False, "reason": "Ordner nicht gefunden"}
    cmd = _claude_cmd()
    if not cmd:
        return {"ok": False, "reason": "claude-CLI nicht gefunden "
                "(npm i -g @anthropic-ai/claude-code) — Tiefen-Modus 'local' nutzen."}

    # Sicherheitsnetz: Snapshot vor dem Edit.
    try:
        import local_tools
        tools = local_tools.SiteTools(folder)
        snap = tools.snapshot()
    except Exception:
        tools, snap = None, {}

    args = [cmd, "-p", prompt,
            "--output-format", "json", "--permission-mode", _PERMISSION,
            "--append-system-prompt", _SYS_APPEND]
    if model:
        args += ["--model", model]
    try:
        proc = subprocess.run(args, cwd=folder, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=timeout or _TIMEOUT)
    except subprocess.TimeoutExpired:
        if tools and snap:
            tools.restore(snap)
        return {"ok": False, "reason": f"Timeout nach {timeout or _TIMEOUT}s — zurückgerollt"}
    except Exception as e:
        return {"ok": False, "reason": f"{type(e).__name__}: {str(e)[:160]}"}

    summary = ""
    try:
        data = json.loads(proc.stdout or "{}")
        summary = (data.get("result") or data.get("summary") or "")[:600]
        _track_cost(data, model, task, name)
    except Exception:
        summary = (proc.stdout or "")[-400:]

    ok, fehler = _render_ok(folder)
    if not ok and tools and snap:
        tools.restore(snap)               # Regression → zurückrollen
        return {"ok": False, "render_ok": False, "reason": f"Render-Fehler, zurückgerollt: {fehler[:160]}",
                "summary": summary}
    return {"ok": True, "render_ok": ok, "summary": summary or "Schritt umgesetzt."}


def run_feature(folder: str, task: str, branche: str = "",
                timeout: int = 0, model: str = "") -> dict:
    """Lässt Claude Code GENAU EIN Feature im Ordner bauen (Backlog-Tiefenmodus).
    Render-Gate + Rollback + Kosten-Tracking. Gibt {ok, summary, render_ok, reason}."""
    return run_prompt(folder, build_prompt(task, branche), branche=branche,
                      timeout=timeout, model=model, task="nightly_deep")
