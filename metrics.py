"""
Schlanke Observability — eine zentrale Stelle für:
  • Tool-Aufrufe des Claude-Agenten: Anzahl, Fehler, Latenz (ms).
  • Claude-Token-Verbrauch: Requests, Input-/Output-Tokens, Tool-Fehler.

In-Memory (Prozess-Laufzeit), thread-sicher. Abrufbar über /api/metrics.
"""
from __future__ import annotations

import os
import threading

_lock = threading.Lock()
_tools: dict[str, dict] = {}
_claude = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "tool_errors": 0}


def record_tool(name: str, ms: float, ok: bool) -> None:
    with _lock:
        t = _tools.setdefault(name, {"calls": 0, "errors": 0, "ms": 0.0, "max_ms": 0.0})
        t["calls"] += 1
        t["ms"]    += ms
        t["max_ms"] = max(t["max_ms"], ms)
        if not ok:
            t["errors"] += 1
            _claude["tool_errors"] += 1


def record_claude(input_tokens: int, output_tokens: int) -> None:
    with _lock:
        _claude["requests"]      += 1
        _claude["input_tokens"]  += int(input_tokens or 0)
        _claude["output_tokens"] += int(output_tokens or 0)


def budget_status() -> dict:
    """Session-Token-Budget für die Claude-Anzeige (alle Claude-Tokens seit App-Start).
    Budget + geschätzte Tokens je Webseite sind via .env konfigurierbar:
      JARVIS_SESSION_TOKENS (Default 2.000.000), JARVIS_TOKENS_PER_WEBSITE (Default 2500).
    """
    try:
        budget = int(os.environ.get("JARVIS_SESSION_TOKENS", "2000000") or "2000000")
    except ValueError:
        budget = 2_000_000
    try:
        per_web = max(1, int(os.environ.get("JARVIS_TOKENS_PER_WEBSITE", "2500") or "2500"))
    except ValueError:
        per_web = 2500
    with _lock:
        inp, outp = _claude["input_tokens"], _claude["output_tokens"]
        reqs = _claude["requests"]
    used = inp + outp
    remaining = max(0, budget - used)
    kosten = round(inp / 1e6 * 5 + outp / 1e6 * 25, 4)
    return {
        "used": used, "input": inp, "output": outp, "requests": reqs,
        "budget": budget, "remaining": remaining,
        "pct_used": round(used / budget * 100, 1) if budget else 0,
        "per_website": per_web,
        "websites_remaining": remaining // per_web,
        "cost_usd": kosten,
    }


def snapshot() -> dict:
    with _lock:
        tools = {
            n: {
                "calls":  v["calls"],
                "errors": v["errors"],
                "avg_ms": round(v["ms"] / v["calls"]) if v["calls"] else 0,
                "max_ms": round(v["max_ms"]),
            }
            for n, v in sorted(_tools.items())
        }
        # grobe Kostenschätzung (Opus 4.8: $5/$25 je 1M Tokens)
        kosten = round(_claude["input_tokens"] / 1e6 * 5 + _claude["output_tokens"] / 1e6 * 25, 4)
        return {"claude": {**_claude, "geschaetzte_kosten_usd": kosten}, "tools": tools}
