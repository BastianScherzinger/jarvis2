"""
Hybrid-Scheduler für LeadForge (Entscheidung: Vorrat + On-Demand).

Hintergrund-Loop (Daemon-Thread, analog lead_collector.py): füllt den AT-Vorrat
(herold.at/Wien — bisher einzige validierte Kategorie-Stadt, siehe MASTER_PLAN.md)
fortlaufend auf und übernimmt neue qualifizierte DE-Bestandsleads aus
evaluated_leads (liest dort nur, verändert nichts). Nach jedem Batch: Scoring +
Fuzzy-Dedup. Discord-Alert bei Totalausfall der Quelle oder knappem Vorrat
(Entscheidung: Monitoring via bestehenden Discord-Bot).

On-Demand: ensure_stock() wird vom Bestell-Flow (Phase 7) synchron aufgerufen,
falls der Vorrat für eine Bestellung nicht reicht.
"""
from __future__ import annotations

import os
import threading
import time

import logger
from scrapers.regions import BRANCHEN

from leadpackages import db_packages as dbp
from leadpackages import dedup_fuzzy, potential_score, quality_score, sources_herold

_lock = threading.Lock()
_started = False

_AT_STADT = "Wien"          # bisher einzige validierte herold.at-Kategorie-Stadt
_MIN_VORRAT_ALERT = 10      # unter dieser Menge gilt eine Kombination als knapp


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)) or default)
    except (ValueError, TypeError):
        return default


def enabled() -> bool:
    return os.environ.get("JARVIS_LEADPACKAGES_SCHEDULER", "1").strip().lower() \
        not in ("0", "false", "no", "off", "")


def _interval() -> int:
    return max(600, _int_env("JARVIS_LEADPACKAGES_INTERVAL", 3600))


def _rescan_after_batch(land: str | None = None, branche: str | None = None,
                          use_ollama: bool = True) -> None:
    """Scoped (land/branche) + use_ollama=False: schnell, ohne Ollama-Aufrufe — sicher
    synchron aus einem Web-Request (ensure_stock) aufrufbar. Unscoped + use_ollama=True:
    voller Rescan, nur aus dem Hintergrund-Loop (kann je nach Vorratsgröße Minuten dauern)."""
    quality_score.apply_all(land=land, branche=branche)
    potential_score.apply_all(land=land, branche=branche, use_ollama=use_ollama)
    dedup_fuzzy.find_and_remove_duplicates(land=land, branche=branche)


def _alert_blockiert() -> None:
    try:
        import discord_bot
        discord_bot.notify(
            "⚠️ LeadForge: herold.at liefert keine Treffer mehr",
            "Alle Branchen in diesem Durchlauf fehlgeschlagen — möglicherweise blockiert "
            "oder das URL-Schema hat sich geändert. Bitte prüfen.",
            0xff5555,
        )
    except Exception:
        pass


def _alert_knapper_vorrat(kombis: list[tuple[str, int]]) -> None:
    if not kombis:
        return
    try:
        import discord_bot
        lines = "\n".join(f"• {b}: nur {n} Datensätze" for b, n in kombis[:10])
        discord_bot.notify("📉 LeadForge: knapper Datenvorrat",
                            f"Folgende Branchen haben wenig Vorrat:\n{lines}", 0xffaa00)
    except Exception:
        pass


def refill_at_wien(branchen: list[str] | None = None) -> dict:
    """Ein Durchlauf: alle (oder ausgewählte) Branchen für Wien nachscrapen."""
    branchen = branchen or BRANCHEN
    neu = 0
    fehlgeschlagen: list[str] = []
    for branche in branchen:
        try:
            leads = sources_herold.search(branche, _AT_STADT)
        except Exception as e:
            fehlgeschlagen.append(branche)
            logger.warn("LeadForge", f"herold.at-Fehler bei {branche}: {type(e).__name__}: {str(e)[:120]}")
            continue
        for lead in leads:
            if dbp.upsert_stock_lead(lead) is not None:
                neu += 1
    if branchen and len(fehlgeschlagen) == len(branchen):
        _alert_blockiert()
    return {"neu": neu, "fehlgeschlagen": fehlgeschlagen}


def refill_de_from_evaluated() -> dict:
    return dbp.migrate_from_evaluated()


def check_vorrat(branchen: list[str] | None = None) -> list[tuple[str, int]]:
    knapp = []
    for branche in (branchen or BRANCHEN[:15]):    # Kern-Branchen, nicht alle 43 jeden Zyklus
        n = dbp.count_stock(branche=branche)
        if n < _MIN_VORRAT_ALERT:
            knapp.append((branche, n))
    _alert_knapper_vorrat(knapp)
    return knapp


def ensure_stock(branche: str, land: str, region: str | None = None, min_needed: int = 50) -> int:
    """On-Demand-Nachscrapen: reicht der Vorrat nicht, wird sofort synchron nachgelegt.
    Bisher nur für land='AT' (Wien) implementiert — DE läuft über die bestehende Pipeline
    und wird nur re-migriert, nicht selbst gescraped."""
    current = dbp.count_stock(branche=branche, land=land)
    if current >= min_needed:
        return current
    if land == "AT":
        for lead in sources_herold.search(branche, region or _AT_STADT):
            dbp.upsert_stock_lead(lead)
    elif land == "DE":
        dbp.migrate_from_evaluated()
    # Scoped + ohne Ollama: schnell genug für einen synchronen Web-Request (Bestell-Flow).
    # Der volle Rescan (inkl. Ollama-Potenzial) läuft separat im Hintergrund-Loop.
    _rescan_after_batch(land=land, branche=branche, use_ollama=False)
    return dbp.count_stock(branche=branche, land=land)


def _loop() -> None:
    time.sleep(120)     # Boot-Puffer, analog lead_collector.py
    while True:
        try:
            if enabled():
                refill_de_from_evaluated()
                result = refill_at_wien()
                _rescan_after_batch()
                check_vorrat()
                logger.success("LeadForge",
                                f"Scheduler-Durchlauf fertig: {result['neu']} neue AT-Leads.")
        except Exception as e:
            logger.warn("LeadForge", f"Scheduler-Zyklus-Fehler: {type(e).__name__}: {str(e)[:120]}")
        time.sleep(_interval())


def start() -> None:
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, name="LeadForgeScheduler", daemon=True).start()
    logger.info("LeadForge", f"Hybrid-Scheduler aktiv (Intervall {_interval()}s).")
