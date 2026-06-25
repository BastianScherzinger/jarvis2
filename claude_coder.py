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
import threading
import time
from pathlib import Path

try:
    import logger
except Exception:                       # Logger ist best-effort — nie ein harter Import-Fehler
    logger = None


def _lg(level: str, msg: str) -> None:
    """Schlanker Logger-Wrapper (Console + Ringpuffer + Frontend-Konsole). Silent, wenn der
    Logger fehlt. Worker-Tag 'Makeover' → taucht im Webseiten-Verbessern-Log auf."""
    try:
        if logger:
            getattr(logger, level, logger.info)("Makeover", msg)
    except Exception:
        pass

# Sicherheitsmodus: erlaubt Datei-Edits ohne interaktive Rückfrage, aber keine
# beliebigen Shell-Kommandos. Per .env überschreibbar.
_PERMISSION = os.environ.get("JARVIS_CLAUDE_PERMISSION", "acceptEdits")
_TIMEOUT    = int(os.environ.get("JARVIS_CLAUDE_TIMEOUT", "1200") or "1200")
# Inaktivitäts-Watchdog: kommt aus dem headless-Lauf so lange KEIN Lebenszeichen (kein
# Stream-Event), gilt er als hängend und wird abgebrochen → die Stufe behält ihr Teil-Ergebnis
# (falls es rendert) bzw. rollt zurück, die Pipeline läuft weiter, statt ewig bei „Stufe 1" zu
# stehen. 300 s (vorher 600): echte Hänger werden doppelt so schnell erkannt — der Balken steht
# nie 10 Min still und es wird kein Token an einem toten Lauf verschwendet. Pro .env justierbar.
_INACTIVITY = int(os.environ.get("JARVIS_CLAUDE_INACTIVITY", "300") or "300")
# Harte Obergrenze an Agenten-Runden je Stufe (verhindert Endlosschleifen + deckelt Tokens). 0 = aus.
# 50 (vorher 80): Inhalte werden vorab lokal (Ollama) befüllt, daher müssen die Stufen nur noch
# einbauen/gestalten — weniger Runden = weniger Tokens = ≥3 Seiten pro Claude-Session.
_MAX_TURNS  = int(os.environ.get("JARVIS_CLAUDE_MAX_TURNS", "50") or "50")

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


def ensure_cli() -> bool:
    """Best-effort: installiert die claude-CLI (npm i -g @anthropic-ai/claude-code), falls sie
    fehlt und npm verfügbar ist. Ohne die CLI läuft das 7-Stufen-Makeover NICHT. Gibt True
    zurück, wenn die CLI danach verfügbar ist. Auth (claude login / ANTHROPIC-Login) bleibt
    Sache des Nutzers — wird nur hingewiesen."""
    if is_available():
        return True
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        try:
            import logger
            logger.warn("Setup", "claude-CLI fehlt & npm/Node nicht gefunden — Makeover deaktiviert. "
                                 "Node.js installieren, dann: npm i -g @anthropic-ai/claude-code")
        except Exception:
            pass
        return False
    try:
        import logger
        logger.info("Setup", "Installiere claude-CLI (npm i -g @anthropic-ai/claude-code)…")
    except Exception:
        pass
    try:
        subprocess.run([npm, "i", "-g", "@anthropic-ai/claude-code"],
                       capture_output=True, text=True, timeout=600)
    except Exception:
        return False
    ok = is_available()
    try:
        import logger
        if ok:
            logger.success("Setup", "claude-CLI installiert. (Einmalig anmelden: `claude` im Terminal starten.)")
        else:
            logger.warn("Setup", "claude-CLI-Installation nicht bestätigt — Terminal neu öffnen / PATH prüfen.")
    except Exception:
        pass
    return ok


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
            # Verbrauch fürs Limit-Lernen buchen (Prozent-Schätzung / „gleich voll"-Warnung).
            try:
                import claude_limit
                claude_limit.record_usage(in_t + out_t)
            except Exception:
                pass
    except Exception:
        pass


def _terminate(proc: "subprocess.Popen") -> None:
    """Beendet den headless-Lauf samt Kind-Prozessen (claude.cmd → node)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=15)
        else:
            proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_prompt(folder: str, prompt: str, branche: str = "", timeout: int = 0,
               model: str = "", task: str = "claude_code", name: str = "",
               on_progress=None, max_turns: int = 0) -> dict:
    """Lässt Claude Code einen FERTIG formulierten Prompt im Ordner ausführen.
    Snapshot vorher, Render-Gate + Rollback bei Regression, Kosten-Tracking.

    STREAMING (seit 24.06.2026): Der Lauf wird mit `--output-format stream-json` gestartet
    und Event-für-Event gelesen. on_progress(text) bekommt Live-Schritte (Tool-Nutzung /
    Zwischentexte) → das Dashboard zeigt echten Fortschritt statt einer eingefrorenen
    „Stufe 1". Ein Inaktivitäts-Watchdog bricht ab, wenn KEIN Event mehr kommt (Hänger),
    eine harte Obergrenze deckelt die Gesamtdauer. So kommt die Pipeline zuverlässig bis Stufe 7.
    Gibt {ok, summary, render_ok, reason}."""
    folder = str(Path(folder))
    fname  = Path(folder).name
    if not Path(folder).is_dir():
        _lg("error", f"Ordner nicht gefunden: {folder}")
        return {"ok": False, "reason": "Ordner nicht gefunden"}
    cmd = _claude_cmd()
    if not cmd:
        _lg("error", "claude-CLI nicht gefunden — Makeover nicht möglich "
                     "(npm i -g @anthropic-ai/claude-code).")
        return {"ok": False, "reason": "claude-CLI nicht gefunden "
                "(npm i -g @anthropic-ai/claude-code) — Tiefen-Modus 'local' nutzen."}
    _lg("info", f"▶ Claude-Code startet · {task} · Modell {model or 'default'} · "
                f"{fname} · Prompt {len(prompt)} Zeichen")

    # Sicherheitsnetz: Snapshot vor dem Edit.
    try:
        import local_tools
        tools = local_tools.SiteTools(folder)
        snap = tools.snapshot()
    except Exception:
        tools, snap = None, {}

    # WICHTIG: Den Prompt über STDIN übergeben, NICHT als argv. claude.cmd ist ein
    # Batch-Wrapper → der lange Prompt (mit Sonderzeichen) würde via cmd.exe verstümmelt.
    # stream-json + --verbose: zeilenweise JSON-Events (Liveness + Fortschritt + Abbruch).
    args = [cmd, "-p", "--output-format", "stream-json", "--verbose",
            "--permission-mode", _PERMISSION, "--append-system-prompt", _SYS_APPEND]
    _mt = max_turns if max_turns and max_turns > 0 else _MAX_TURNS
    if _mt > 0:
        args += ["--max-turns", str(_mt)]
    if model:
        args += ["--model", model]

    hard_to = timeout or _TIMEOUT
    # Mehrere Keys konfiguriert → den AKTIVEN (nicht-erschöpften) Key für diesen Lauf setzen,
    # damit das headless-CLI den nächsten „Claude" nutzt, sobald einer am Limit ist. Bei nur
    # EINEM Key bleibt alles unverändert (CLI nutzt die normale Abo-Anmeldung).
    run_env = None
    try:
        import claude_keys
        if claude_keys.count() > 1:
            ak = claude_keys.active_key()
            if ak:
                run_env = os.environ.copy()
                run_env["ANTHROPIC_API_KEY"] = ak
    except Exception:
        run_env = None
    try:
        proc = subprocess.Popen(args, cwd=folder, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace", bufsize=1,
                                env=run_env)
    except Exception as e:
        if tools and snap:
            tools.restore(snap)
        _lg("error", f"Claude-Code-Start fehlgeschlagen: {type(e).__name__}: {str(e)[:160]}")
        return {"ok": False, "reason": f"{type(e).__name__}: {str(e)[:160]}"}

    st = {"last": time.time(), "killed": "", "tools": 0, "edits": 0}
    start = time.time()
    err_buf: list[str] = []

    def _drain_err():
        try:
            for ln in proc.stderr:
                err_buf.append(ln)
        except Exception:
            pass

    def _watch():
        while proc.poll() is None:
            now = time.time()
            if now - start > hard_to:
                st["killed"] = "hard"; _terminate(proc); return
            if now - st["last"] > _INACTIVITY:
                st["killed"] = "inactivity"; _terminate(proc); return
            time.sleep(2)

    threading.Thread(target=_drain_err, name="cc-err", daemon=True).start()
    threading.Thread(target=_watch, name="cc-watch", daemon=True).start()

    # Prompt über stdin reinschreiben und schließen (signalisiert „Eingabe fertig").
    try:
        if proc.stdin:
            proc.stdin.write(prompt)
            proc.stdin.close()
    except Exception:
        pass

    data: "dict | None" = None
    summary = ""
    last_text = ""
    try:
        for line in proc.stdout:                  # blockiert je Event; Watchdog killt bei Stille
            if st["killed"]:                      # Watchdog hat abgebrochen → Leseschleife sofort verlassen
                break
            line = line.strip()
            if not line:
                continue
            st["last"] = time.time()
            try:
                ev = json.loads(line)
            except Exception:
                continue
            etype = ev.get("type")
            if etype == "assistant":
                for blk in (ev.get("message", {}) or {}).get("content", []) or []:
                    if blk.get("type") == "text" and (blk.get("text") or "").strip():
                        last_text = blk["text"].strip()
                        if on_progress:
                            try: on_progress(last_text[:90])
                            except Exception: pass
                    elif blk.get("type") == "tool_use":
                        tname = blk.get("name", "tool")
                        st["tools"] += 1
                        if tname in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                            st["edits"] += 1
                        # Jeden Tool-Einsatz in die CMD loggen → Sir sieht live, was Claude tut.
                        _lg("debug", f"  {fname} · {tname}")
                        if on_progress:
                            try: on_progress(f"{tname} …")
                            except Exception: pass
            elif etype == "result":
                data = ev
                summary = (ev.get("result") or "")[:600]
                if ev.get("is_error") or ev.get("subtype") not in (None, "success"):
                    _lg("warn", f"{fname} · Claude meldet: "
                                f"{ev.get('subtype', '')} {str(ev.get('result',''))[:120]}")
    except Exception as e:
        _lg("warn", f"{fname} · Stream-Lesefehler: {type(e).__name__}: {str(e)[:120]}")
    try:
        proc.wait(timeout=15)
    except Exception:
        _terminate(proc)

    dur = round(time.time() - start, 1)

    if st["killed"]:
        grund = ("Hänger (kein Lebenszeichen > %ds)" % _INACTIVITY if st["killed"] == "inactivity"
                 else f"Zeitlimit {hard_to}s erreicht")
        tail = ("".join(err_buf))[-300:].strip()
        # Abgebrochen, ABER Claude hat schon echte Edits gemacht und die Seite rendert sauber →
        # die Arbeit NICHT wegwerfen. Sonst sind die verbrauchten Tokens verbrannt und die Stufe
        # käme nie über „1/7" hinaus (genau der Hänger-Fall). Nur bei kaputtem Render zurückrollen.
        if st["edits"] > 0:
            ok_r, _fehler_r = _render_ok(folder)
            if ok_r:
                if data is not None:
                    _track_cost(data, model, task, name)
                _lg("warn", f"⚠ {fname} · {grund} nach {dur}s — aber {st['edits']} Edits rendern "
                            f"sauber → Teil-Ergebnis behalten ({st['tools']} Tools).")
                return {"ok": True, "render_ok": True, "partial": True,
                        "summary": (summary or last_text[:200]
                                    or "Teil-Ergebnis behalten (Lauf abgebrochen, Seite rendert).")}
        if tools and snap:
            tools.restore(snap)
        _lg("error", f"✕ {fname} · {grund} nach {dur}s — abgebrochen & zurückgerollt "
                     f"({st['tools']} Tools, {st['edits']} Edits)"
                     + (f" · stderr: {tail[-160:]}" if tail else ""))
        return {"ok": False, "reason": f"{grund} — abgebrochen & zurückgerollt", "summary": summary}

    if data is not None:
        _track_cost(data, model, task, name)
    elif not summary:
        summary = last_text[:600] or (("".join(err_buf))[-300:])
        tail = ("".join(err_buf))[-300:].strip()
        if tail:
            _lg("warn", f"{fname} · kein Result-Event — stderr: {tail[-200:]}")

    ok, fehler = _render_ok(folder)
    if not ok and tools and snap:
        tools.restore(snap)               # Regression → zurückrollen
        _lg("error", f"✕ {fname} · Render-Fehler nach {dur}s → zurückgerollt: {fehler[:160]}")
        return {"ok": False, "render_ok": False,
                "reason": f"Render-Fehler, zurückgerollt: {fehler[:160]}", "summary": summary}
    _lg("success", f"✓ {fname} · fertig in {dur}s · {st['tools']} Tools, {st['edits']} Edits · "
                   f"{(summary or 'Schritt umgesetzt.')[:80]}")
    return {"ok": True, "render_ok": ok, "summary": summary or "Schritt umgesetzt."}


def run_feature(folder: str, task: str, branche: str = "",
                timeout: int = 0, model: str = "") -> dict:
    """Lässt Claude Code GENAU EIN Feature im Ordner bauen (Backlog-Tiefenmodus).
    Render-Gate + Rollback + Kosten-Tracking. Gibt {ok, summary, render_ok, reason}."""
    return run_prompt(folder, build_prompt(task, branche), branche=branche,
                      timeout=timeout, model=model, task="nightly_deep")
