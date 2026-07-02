"""
extra_usage_watch.py — Ab App-Start alle 5 Minuten prüfen, ob bezahlte Extra-Nutzung
("Extra-Modus"/Paid-Boost) erkannt wird, und diese SOFORT wirksam machen + melden.

"Extra Usage bei Claude" ist technisch nur über cost_tracker.paid_tokens_detected()
prüfbar (echte Anthropic-API-Tokens gebucht ODER mehrere ANTHROPIC-Keys konfiguriert =
Builder läuft über einen bezahlten API-Key statt reinem Abo-Kontingent). Anthropics
eigenes Account-Feature "Extra usage" für Claude-Abos ist NICHT per API abfragbar — es
gibt keinen Hook dafür. auto_builder._daily_limit() nutzt cost_tracker.paid_boost_active()
bereits inline bei jedem Aufruf (dashboard-Poll, Builder-Loop) — der Tageslimit-Boost
wirkt also schon sofort, nicht erst am nächsten Tages-Reset. Dieses Modul ergänzt einen
EIGENEN, vom Builder-Loop unabhängigen Herzschlag (läuft auch wenn der Builder steht) und
eine sichtbare Meldung GENAU beim Übergang aus->an, statt eines stillen internen Flags.

.env
  JARVIS_EXTRA_USAGE_POLL=300   # Sekunden zwischen zwei Checks (min. 60, Default 5 Min)
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import logger

_BASE  = Path(__file__).parent
_LATCH = _BASE / "data" / "extra_usage_state.json"
_lock  = threading.Lock()
_started = False


def _interval() -> int:
    try:
        return max(60, int(os.environ.get("JARVIS_EXTRA_USAGE_POLL", "300") or 300))
    except (ValueError, TypeError):
        return 300


def _read_state() -> dict:
    try:
        return json.loads(_LATCH.read_text(encoding="utf-8"))
    except Exception:
        return {"active": False}


def _write_state(d: dict) -> None:
    try:
        _LATCH.parent.mkdir(parents=True, exist_ok=True)
        _LATCH.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def status() -> dict:
    """Letzter bekannter Zustand fürs Dashboard. Wirft nie."""
    s = _read_state()
    return {"active": bool(s.get("active")), "since": s.get("ts", 0),
            "poll": _interval()}


def check_once() -> dict:
    """Ein Check: fragt cost_tracker.paid_boost_active() ab (60s intern gecacht) und
    meldet NUR beim Übergang (aus->an oder an->aus) — kein Spam bei jedem Poll.
    Gibt {active, changed} zurück. Wirft nie."""
    was = bool(_read_state().get("active"))
    now = False
    try:
        import cost_tracker
        now = bool(cost_tracker.paid_boost_active())
    except Exception:
        now = False
    changed = now != was
    if changed:
        _write_state({"active": now, "ts": time.time()})
        if now:
            reason = ""
            try:
                import cost_tracker
                reason = cost_tracker.paid_tokens_detected().get("reason", "")
            except Exception:
                pass
            logger.success("ExtraUsage",
                           f"Extra-Nutzung erkannt — Extra-Modus aktiv (Tageslimit verdoppelt)."
                           + (f" [{reason}]" if reason else ""))
            try:
                import discord_bot
                discord_bot.notify(
                    "⚡ Extra-Modus aktiv",
                    "Bezahlte Extra-Nutzung erkannt — das Tageslimit für Webseiten-Builds ist "
                    "ab sofort verdoppelt, kein Warten auf den nächsten Tages-Reset."
                    + (f"\n\n{reason}" if reason else ""),
                    color=0xffc93d,
                )
            except Exception:
                pass
        else:
            logger.info("ExtraUsage", "Extra-Modus wieder inaktiv (keine bezahlte Extra-Nutzung mehr erkannt).")
    return {"active": now, "changed": changed}


def _loop() -> None:
    time.sleep(20)                          # kurzer Boot-Puffer -- soll wirklich "ab Start" greifen
    logger.info("ExtraUsage", f"Extra-Nutzungs-Check aktiv (alle {_interval()}s).")
    while True:
        try:
            check_once()
        except Exception as e:
            logger.warn("ExtraUsage", f"Check-Fehler: {type(e).__name__}")
        time.sleep(_interval())


def start() -> dict:
    """Startet den Extra-Nutzungs-Check EINMAL (idempotent, Daemon-Thread)."""
    global _started
    with _lock:
        if _started:
            return {"ok": True, "already": True}
        _started = True
    threading.Thread(target=_loop, name="ExtraUsageWatch", daemon=True).start()
    return {"ok": True}
