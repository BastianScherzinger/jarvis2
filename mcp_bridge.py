"""
mcp_bridge.py — Brücke, die lokalen Ollama-Modellen Werkzeuge gibt (Plan:
workspace/PLAN_MCP_LOCAL_AI.md). Zwei Toolset-Backends:

  (1) builtin  — unsere sandboxed SiteTools (local_tools.py) direkt als Ollama-Tools.
                 Braucht KEIN Node/MCP, läuft sofort (empfohlen, deterministisch).
  (2) mcp      — echte MCP-Server (z.B. Filesystem) per stdio dazuschalten, wenn die
                 'mcp'-Library + Node/npx vorhanden sind (JARVIS_MCP_SERVERS).

Der Agent nutzt natives Ollama-Tool-Calling (ollama.chat(tools=...)). Determinismus
außerhalb des Modells: Snapshot vor dem Edit, Render-Gate nach jedem Zyklus, Rollback
bei Regression. Import-sicher: ohne 'ollama' ist available()=False (No-op), das
restliche System bleibt unberührt.

Aktivierung im Nightly-Builder: JARVIS_NIGHTLY_DEEP=mcp
Voraussetzung: `pip install ollama` und ein tool-fähiges Modell
(JARVIS_MCP_MODEL, Default qwen2.5:7b — qwen2.5-coder trägt KEIN Tools-Badge).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import logger
import local_tools
import feature_backlog
from jsonstate import atomic_write_json

try:
    import ollama as _ollama
    _HAS_OLLAMA = True
except Exception:
    _HAS_OLLAMA = False

_MODEL     = os.environ.get("JARVIS_MCP_MODEL") or os.environ.get("JARVIS_TOOL_MODEL") or "qwen2.5:7b"
_MAX_STEPS = int(os.environ.get("JARVIS_MCP_STEPS", "16") or "16")


def available() -> bool:
    """Die Bridge läuft, wenn die ollama-Library da ist (builtin-Toolset reicht)."""
    return _HAS_OLLAMA


def mcp_available() -> bool:
    """Echte MCP-Server nur, wenn die offizielle 'mcp'-Library installiert ist."""
    try:
        import mcp  # noqa: F401
        return True
    except Exception:
        return False


# ── Tool-Schema-Übersetzung: SiteTools → Ollama function-tools ────────────────

_ARG_TYPE = {"content": "object"}                    # content darf ein Objekt sein


def _ollama_tools() -> list:
    """Übersetzt local_tools.TOOLS_SCHEMA 1:1 ins Ollama-/OpenAI-Tool-Format."""
    tools = []
    for t in local_tools.TOOLS_SCHEMA:
        props, required = {}, []
        for arg, desc in (t.get("args") or {}).items():
            props[arg] = {"type": _ARG_TYPE.get(arg, "string"), "description": desc}
            required.append(arg)
        tools.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["desc"],
                "parameters": {"type": "object", "properties": props,
                               "required": [r for r in required if r != "content" or t["name"] == "write_file"]},
            },
        })
    return tools


_SYSTEM = (
    "Du bist ein Senior-Frontend-Entwickler. Du baust EIN konkretes Feature in eine "
    "bereits live gebaute Landing-Page (Django-Template, gesteuert über content.json) "
    "ein. Arbeite ausschließlich über die bereitgestellten Tools — sieh dir mit "
    "read_content/read_file den Ist-Zustand an, ändere minimal und sauber, und prüfe "
    "danach IMMER mit render_check, dass die Seite fehlerfrei rendert. "
    "Design-Prinzipien: eine Akzentfarbe, klare Hierarchie, großzügiger Weißraum, "
    "echte Inhalte statt Platzhalter, mobiloptimiert, barrierearm. Beschädige keine "
    "bestehende Funktion. Wenn render_check grün ist und das Feature steht, antworte "
    "kurz mit 'FERTIG: <was du gebaut hast>'."
)


def _run_agent(folder: str, task: str, max_steps: int = _MAX_STEPS) -> dict:
    """Native-Tool-Calling-Schleife mit SiteTools + Render-Gate + Rollback."""
    tools_obj = local_tools.SiteTools(folder)
    snap = tools_obj.snapshot()                      # Sicherheitsnetz
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": task},
    ]
    ollama_tools = _ollama_tools()
    summary = ""
    try:
        for _ in range(max_steps):
            resp = _ollama.chat(model=_MODEL, messages=messages, tools=ollama_tools)
            msg = resp.get("message", {}) if isinstance(resp, dict) else resp.message
            calls = (msg.get("tool_calls") if isinstance(msg, dict) else getattr(msg, "tool_calls", None)) or []
            content = (msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")) or ""
            messages.append({"role": "assistant", "content": content,
                             "tool_calls": calls if calls else None})
            if not calls:
                summary = content.strip()
                break
            for call in calls:
                fn = call["function"] if isinstance(call, dict) else call.function
                name = fn["name"] if isinstance(fn, dict) else fn.name
                raw_args = fn["arguments"] if isinstance(fn, dict) else fn.arguments
                args = raw_args if isinstance(raw_args, dict) else _parse_json(raw_args)
                obs = tools_obj.dispatch(name, args)
                messages.append({"role": "tool", "name": name, "content": obs[:4000]})
    except Exception as e:
        tools_obj.restore(snap)
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}

    # Render-Gate: bei Regression vollständig zurückrollen.
    gate = tools_obj.render_check()
    if not gate.startswith("[OK]"):
        tools_obj.restore(snap)
        return {"ok": False, "reason": f"Render-Gate rot, Rollback: {gate[:160]}"}
    return {"ok": True, "summary": summary or "Feature eingebaut"}


def _parse_json(raw) -> dict:
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        return {}


def build_feature(folder: str, branche: str = "", name: str = "") -> dict:
    """Nächstes Backlog-Feature über die lokale KI (MCP-Bridge) einbauen.
    Spiegelt local_coder.build_feature, nutzt aber natives Tool-Calling."""
    if not available():
        return {"ok": False, "reason": "ollama-Library fehlt (pip install ollama)"}
    cj = Path(folder) / "content.json"
    content = {}
    try:
        if cj.is_file():
            content = json.loads(cj.read_text(encoding="utf-8"))
    except Exception:
        pass
    feat = feature_backlog.next_feature(branche, content)
    if not feat:
        return {"ok": False, "reason": "keine offenen Features"}

    task = (f"Baue dieses Feature in die Seite von '{name or content.get('site_name','dem Betrieb')}' "
            f"(Branche: {branche or 'allgemein'}) ein:\n\n{feat['spec']}\n\n"
            f"Nutze read_content zuerst. Prüfe am Ende mit render_check.")
    res = _run_agent(folder, task)
    if not res.get("ok"):
        return {"ok": False, "feature": feat["label"], "reason": res.get("reason", "Bau fehlgeschlagen")}

    # Feature als erledigt markieren + Changelog (wie bei local_coder).
    try:
        content = json.loads(cj.read_text(encoding="utf-8"))
        feature_backlog.mark_done(content, feat["key"])
        atomic_write_json(cj, content, indent=2)
    except Exception:
        pass
    try:
        import local_coder
        local_coder._append_changelog(Path(folder), feat["label"], res.get("summary", ""))
    except Exception:
        pass
    return {"ok": True, "feature": feat["label"], "summary": res.get("summary", "")}


def selftest() -> dict:
    """Schnelle Diagnose ohne echtes Modell: Schema-Übersetzung + Lib-Status."""
    info = {"ollama": _HAS_OLLAMA, "mcp_lib": mcp_available(), "model": _MODEL,
            "tools": [t["function"]["name"] for t in _ollama_tools()],
            "references": local_tools.list_references()}
    return info


if __name__ == "__main__":
    print(json.dumps(selftest(), ensure_ascii=False, indent=2))
