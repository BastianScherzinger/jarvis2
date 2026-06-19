"""
Schlanke Observability — eine zentrale Stelle für:
  • Tool-Aufrufe des Claude-Agenten: Anzahl, Fehler, Latenz (ms).
  • Claude-Token-Verbrauch: Requests, Input-/Output-Tokens, Tool-Fehler.

In-Memory (Prozess-Laufzeit), thread-sicher. Abrufbar über /api/metrics.
"""
from __future__ import annotations

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
