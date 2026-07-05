"""
local_coder.py — Variante B des Nightly-Tiefenmodus:
"Claude schreibt die Prompts/Spec, die lokale Mega-KI baut es."

Ablauf je Feature:
  1. plan_feature()  — Claude (klein) liest die Seite und schreibt eine PRÄZISE,
     seitenspezifische Bau-Spec (kostengünstiger Prompt-Autor). Ohne API-Key: die
     generische Backlog-Spec.
  2. build_with_local() — die lokale Ollama-Mega-KI (qwen2.5/qwen2.5-coder) baut die
     Spec in einer ReAct-Schleife mit local_tools (read/write/replace/render_check).
     Snapshot vorher, Render-Gate + Rollback bei Regression.
  3. build_feature() — orchestriert beides + wählt das nächste Feature aus dem Backlog.

Alles best-effort und lokal-first: ohne Ollama bricht es sauber ab, ohne API-Key
nutzt es die generische Spec.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from jsonstate import atomic_write_json

MODEL_CLAUDE = "claude-opus-4-8"
_MAX_STEPS   = int(os.environ.get("JARVIS_CODER_STEPS", "14") or "14")

# Komprimierte Skills im System-Prompt (aus dem Agenten-Werkzeug-/Skill-Katalog).
_SYSTEM = (
    "Du bist CODER — ein lokaler Agent, der eine fertige Django-Landing-Page verbessert. "
    "Du arbeitest in einer Schleife: EIN Gedanke, EINE Action, dann wartest du auf die Observation.\n\n"
    "PROJEKT: content.json (alle Texte/Daten — Struktur NIE brechen), templates/index.html "
    "(rendert content.json), static/css/style.css, static/img/.\n\n"
    "TOOLS (genau EIN Tool pro Schritt): list_dir{path}, read_file{path}, write_file{path,content}, "
    "replace_in_file{path,old,new}, read_content{}, write_content{content}, compile_check{path}, "
    "render_check{}, read_reference{name}.\n"
    "read_reference{name}: liest Skill-Docs. Verfügbare Namen: 'stats_counter', 'testimonials', "
    "'process_steps', 'animations'.\n\n"
    "EISERNE REGELN: 1) IMMER read_content/read_file vor Änderungen. 2) content.json: nur Werte "
    "ändern/ergänzen, NIE Keys löschen/umbenennen. 3) Vor 'fertig' IMMER render_check{} — muss [OK] "
    "sein. 4) Eine kleine Änderung pro Schritt. 5) design-pro: eine Akzentfarbe, klare Hierarchie, EIN "
    "primärer CTA, großzügiger Weißraum, deutsch & konkret, kein KI-Geschwurbel. 6) Bei Unsicherheit "
    "lesen statt raten.\n\n"
    "ANTWORTFORMAT — IMMER genau dieses JSON, nichts davor/danach:\n"
    '{\"thought\":\"kurz\",\"action\":{\"tool\":\"read_content\",\"args\":{}}}\n'
    "Wenn die Aufgabe erledigt und render_check [OK] ist:\n"
    '{\"thought\":\"...\",\"done\":true,\"summary\":\"was geändert wurde\"}'
)


def _extract_json(text: str) -> "dict | None":
    try:
        from website_improve import _extract_json as ej
        return ej(text or "")
    except Exception:
        return None


def _ollama(prompt: str, system: str) -> str:
    """Single-Shot an das lokale Modell (Coder-Modell bevorzugt)."""
    try:
        from scrapers._http import ask_ollama
        model = (os.environ.get("JARVIS_CODER_MODEL")
                 or os.environ.get("JARVIS_TOOL_MODEL", ""))
        return ask_ollama(prompt, system, model=model) or ""
    except Exception:
        return ""


def ollama_available() -> bool:
    try:
        import hardware
        return bool(hardware.installed_models())
    except Exception:
        return False


# ── 1. Claude schreibt die Spec ───────────────────────────────────────────────

def plan_feature(folder: str, feature: dict, branche: str = "") -> str:
    """Claude verfeinert die generische Feature-Spec zu einer präzisen, seiten-
    spezifischen Bau-Anweisung. Ohne API-Key → die generische Spec."""
    generic = (feature or {}).get("spec", "")
    try:
        import anthropic
        import config
        key = config.get_api_key()
        if not key:
            return generic
        content = {}
        cj = Path(folder) / "content.json"
        if cj.is_file():
            content = json.loads(cj.read_text(encoding="utf-8"))
        client = anthropic.Anthropic(api_key=key)
        sys = ("Du bist Tech-Lead. Schreibe eine PRÄZISE, knappe Bau-Anweisung (deutsch) für "
               "eine lokale Coding-KI, die GENAU EIN Feature in eine Django-Landing-Page einbaut. "
               "Konkret: welche content.json-Felder anlegen (mit Beispielwerten passend zum Betrieb), "
               "welche Template-Sektion wo, welche CSS-Klassen. Keine Romane, nur umsetzbare Schritte.")
        prompt = (f"Feature: {feature.get('label','')}\nGeneric-Spec: {generic}\n"
                  f"Branche: {branche}\nAktuelle content.json:\n"
                  f"{json.dumps(content, ensure_ascii=False)[:2500]}\n\n"
                  "Schreibe die seitenspezifische Bau-Anweisung (max ~12 Zeilen).")
        msg = client.messages.create(model=MODEL_CLAUDE, max_tokens=700, system=sys,
                                     messages=[{"role": "user", "content": prompt}])
        try:
            import cost_tracker
            cost_tracker.track_message(MODEL_CLAUDE, msg, "nightly_improve")
        except Exception:
            pass
        txt = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
        return txt.strip() or generic
    except Exception:
        return generic


# ── 2. Lokale KI baut (ReAct-Schleife) ────────────────────────────────────────

def build_with_local(folder: str, spec: str, max_steps: int = 0) -> dict:
    """Lokale Ollama-KI baut die Spec via local_tools. Snapshot + Render-Gate + Rollback.
    Gibt {ok, summary, steps, render_ok, reason}."""
    import local_tools
    try:
        tools = local_tools.SiteTools(folder)
    except Exception as e:
        return {"ok": False, "reason": str(e)}
    if not ollama_available():
        return {"ok": False, "reason": "Ollama nicht erreichbar/keine Modelle — lokal nicht möglich."}

    snap = tools.snapshot()
    transcript = f"AUFGABE (genau dieses eine Feature umsetzen):\n{spec}\n"
    summary = ""
    steps = max_steps or _MAX_STEPS
    fehlerserie = 0
    for i in range(steps):
        raw = _ollama(transcript + "\nNächster Schritt — antworte NUR mit dem JSON:", _SYSTEM)
        obj = _extract_json(raw)
        if not obj:
            fehlerserie += 1
            transcript += "\n[System] Ungültig. Antworte NUR mit dem geforderten JSON-Format."
            if fehlerserie >= 3:
                break
            continue
        fehlerserie = 0
        if obj.get("done"):
            summary = str(obj.get("summary") or "").strip()
            break
        action = obj.get("action") or {}
        tool = action.get("tool", "")
        args = action.get("args") or {}
        obs = tools.dispatch(tool, args)
        transcript += (f"\nAction: {tool} {json.dumps(args, ensure_ascii=False)[:160]}"
                       f"\nObservation: {obs[:700]}\n")

    ok, fehler = website_render_ok(folder)
    if not ok:
        tools.restore(snap)               # Regression → zurückrollen
        return {"ok": False, "render_ok": False, "steps": i + 1,
                "reason": f"Render-Fehler nach lokalem Bau, zurückgerollt: {fehler[:140]}"}
    return {"ok": True, "render_ok": True, "steps": i + 1,
            "summary": summary or "Feature lokal eingebaut."}


def website_render_ok(folder: str) -> tuple:
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


# ── 3. Orchestrierung: nächstes Feature planen + bauen ────────────────────────

def build_feature(folder: str, branche: str = "", name: str = "") -> dict:
    """Wählt das nächste offene Feature, lässt Claude die Spec schreiben und die
    lokale KI bauen, markiert es in content.json und schreibt ins Seiten-Changelog.
    Gibt {ok, feature, summary, reason}."""
    import feature_backlog
    f = Path(folder)
    cj = f / "content.json"
    content = {}
    try:
        if cj.is_file():
            content = json.loads(cj.read_text(encoding="utf-8"))
    except Exception:
        pass
    feat = feature_backlog.next_feature(branche, content)
    if not feat:
        return {"ok": False, "reason": "Alle Backlog-Features bereits eingebaut."}

    spec = plan_feature(folder, feat, branche)
    res = build_with_local(folder, spec)
    if not res.get("ok"):
        return {"ok": False, "feature": feat["label"], "reason": res.get("reason", "Bau fehlgeschlagen")}

    # Feature markieren (frisch lesen — die KI hat content.json geändert)
    try:
        content = json.loads(cj.read_text(encoding="utf-8"))
    except Exception:
        pass
    feature_backlog.mark_done(content, feat["key"])
    try:
        atomic_write_json(cj, content, indent=2)
    except Exception:
        pass
    _append_changelog(f, feat["label"], res.get("summary", ""))
    return {"ok": True, "feature": feat["label"], "summary": res.get("summary", "")}


def _append_changelog(folder: Path, feature: str, summary: str) -> None:
    """Per-Seite-Changelog: was wurde wann nachts eingebaut."""
    try:
        import time
        line = f"- {time.strftime('%Y-%m-%d %H:%M')} · {feature}: {summary}\n"
        p = folder / "JARVIS_CHANGELOG.md"
        head = "" if p.exists() else "# JARVIS — Nightly-Verbesserungen\n\n"
        with p.open("a", encoding="utf-8") as fh:
            fh.write(head + line)
    except Exception:
        pass
