"""
data_retention.py — DSGVO-Speicherbegrenzung (Art. 5 Abs. 1 lit. e).

Löscht automatisch personenbezogene Lead-Daten, die nach `JARVIS_RETENTION_DAYS` (Default 180)
NICHT zu einem Kontakt/Vertrag geführt haben:
  • DB2 (leads_evaluated): nur nicht-kontaktierte, nicht-verkaufte, nicht-archivierte Leads.
  • DB1 (leads_raw):       nur bereits abgearbeitete Rohleads (done/failed).

Kontaktierte/verkaufte Leads bleiben (Vertragsanbahnung, Art. 6 Abs. 1 lit. b). Läuft als
täglicher Daemon-Thread (in app.py gestartet), Default AN — `JARVIS_RETENTION=0` schaltet ab.
Manueller Aufruf: `python -c "import data_retention; print(data_retention.purge_now())"`.
"""
from __future__ import annotations

import datetime
import os
import threading
import time

import logger


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except (ValueError, TypeError):
        return default


def retention_days() -> int:
    """Aufbewahrungsfrist in Tagen (min. 30, damit ein Fehlwert nichts frisch Erhobenes löscht)."""
    return max(30, _int_env("JARVIS_RETENTION_DAYS", 180))


def _cutoff_iso(days: int) -> str:
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    return cutoff.isoformat(timespec="seconds")


def purge_now() -> dict:
    """Führt EINEN Löschlauf aus und gibt die Anzahl gelöschter Zeilen je DB zurück."""
    days   = retention_days()
    cutoff = _cutoff_iso(days)
    out = {"cutoff": cutoff, "days": days, "evaluated": 0, "raw": 0}
    try:
        import db_evaluated
        out["evaluated"] = db_evaluated.purge_stale(cutoff)
    except Exception as e:
        logger.warn("Retention", f"DB2-Purge fehlgeschlagen: {type(e).__name__}: {e}")
    try:
        import db_raw
        out["raw"] = db_raw.purge_older_than(cutoff)
    except Exception as e:
        logger.warn("Retention", f"DB1-Purge fehlgeschlagen: {type(e).__name__}: {e}")
    total = out["evaluated"] + out["raw"]
    if total:
        logger.info("Retention",
                    f"DSGVO-Löschung: {out['evaluated']} Bewertungen + {out['raw']} Rohleads "
                    f"älter als {days} Tage entfernt.")
        try:   # kurze Discord-Meldung (best-effort, nie blockierend)
            import discord_bot
            if hasattr(discord_bot, "notify"):
                discord_bot.notify(f"🗑️ DSGVO-Löschung: {total} alte, nicht kontaktierte "
                                   f"Datensätze (> {days} Tage) automatisch entfernt.")
        except Exception:
            pass
    return out


def _loop(stop_event: "threading.Event | None") -> None:
    # Erster Lauf nach kurzer Boot-Ruhe, danach täglich.
    time.sleep(120)
    while not (stop_event and stop_event.is_set()):
        try:
            purge_now()
        except Exception as e:
            logger.warn("Retention", f"Lauf-Fehler: {type(e).__name__}: {e}")
        # 24h schlafen, aber in kleinen Schritten, damit ein Stop schnell greift.
        for _ in range(24 * 60):
            if stop_event and stop_event.is_set():
                return
            time.sleep(60)


def start(stop_event: "threading.Event | None" = None) -> "threading.Thread | None":
    """Startet den täglichen Retention-Daemon (Default AN). Gibt den Thread zurück (oder None,
    wenn per JARVIS_RETENTION=0 abgeschaltet)."""
    val = (os.environ.get("JARVIS_RETENTION", "") or "1").strip().lower()
    if val in ("0", "false", "no", "off"):
        logger.info("Retention", "Auto-Löschung deaktiviert (JARVIS_RETENTION=0).")
        return None
    t = threading.Thread(target=_loop, args=(stop_event,), name="Retention", daemon=True)
    t.start()
    logger.info("Retention", f"DSGVO-Auto-Löschung aktiv (Frist {retention_days()} Tage).")
    return t
