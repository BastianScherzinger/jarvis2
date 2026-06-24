"""
claude_limit.py — zentraler Status des Claude-Code-Session-/Usage-Limits.

Single Source of Truth für „das Limit ist voll": das Makeover (overnight_makeover)
meldet hier ein erkanntes Session-Limit (`mark`) bzw. das Weiterlaufen (`clear`); das
Dashboard liest den Status (`state`) und zeigt direkt ein sichtbares Zeichen
(Banner über den Webseiten) — so sieht Sir sofort, dass nicht der Code hängt,
sondern Claudes Kontingent erschöpft ist.

State liegt in data/claude_limit.json (gitignored, maschinenlokal).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

_FILE = Path(__file__).resolve().parent / "data" / "claude_limit.json"


def _read() -> dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(d: dict) -> None:
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def mark(stage: str = "", wait_seconds: int = 0, site: str = "") -> None:
    """Markiert das Claude-Limit als erschöpft. `stage` = welche Makeover-Stufe blockiert,
    `wait_seconds` = geplante Wartezeit bis zum nächsten Versuch (0 = unbekannt),
    `site` = Name der gerade verbesserten Webseite (für ein Zeichen direkt auf der Karte)."""
    now = time.time()
    cur = _read()
    d = {
        "limited": True,
        "since": cur.get("since") or now,     # ersten Zeitpunkt behalten
        "stage": stage or cur.get("stage", ""),
        "site": site or cur.get("site", ""),
        "until": (now + wait_seconds) if wait_seconds else 0,
        "updated": now,
    }
    _write(d)


def clear() -> None:
    """Hebt die Limit-Markierung auf (eine Stufe lief wieder durch / Makeover fertig)."""
    if _read().get("limited"):
        _write({"limited": False, "updated": time.time()})


def state() -> dict:
    """Aktueller Limit-Status fürs Dashboard.
    {limited, since, stage, until, minutes_left}. `minutes_left` = grobe Restwartezeit."""
    d = _read()
    if not d.get("limited"):
        return {"limited": False}
    until = float(d.get("until") or 0)
    mins = 0
    if until:
        mins = max(0, int((until - time.time()) // 60))
    return {
        "limited": True,
        "since": d.get("since", 0),
        "stage": d.get("stage", ""),
        "site": d.get("site", ""),
        "until": until,
        "minutes_left": mins,
    }
