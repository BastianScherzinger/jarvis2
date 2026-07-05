"""
supabase_quota.py — geteilter Kontingent-Schutz für alle Supabase-Push-Pfade
(cloud_sync.py: Leads, cloud_sync_websites.py: Webseiten).

Ein HTTP 402 (Billing-/Egress-Kontingent überschritten) ist ein ACCOUNT-weites Problem,
nicht pro Lead/Webseite — ohne Bremse löst JEDER weitere Push (potenziell hunderte pro
Minute bei 32 parallelen Evaluator-Threads) denselben 402 erneut aus und flutet das Log.
Nach dem ERSTEN 402 pausieren beide Module gemeinsam für _COOLDOWN Sekunden, bevor der
nächste Versuch erlaubt ist (das Kontingent könnte inzwischen zurückgesetzt/erhöht sein).
"""
from __future__ import annotations

import threading
import time

import logger

_COOLDOWN = 600   # 10 Minuten Pause nach einem 402, bevor der nächste Versuch erlaubt ist
_lock = threading.Lock()
_blocked_until: list = [0.0]


def blocked() -> bool:
    with _lock:
        return time.time() < _blocked_until[0]


def mark_blocked(source: str = "") -> None:
    """Meldet einen 402 — setzt/verlängert die gemeinsame Pause. Loggt nur beim ERSTEN
    Übergang in die Pause, nicht bei jedem weiteren 402 während der laufenden Pause."""
    with _lock:
        already_blocked = time.time() < _blocked_until[0]
        _blocked_until[0] = time.time() + _COOLDOWN
    if not already_blocked:
        logger.warn(
            "Supabase",
            f"Kontingent/Billing blockiert (HTTP 402){' — ' + source if source else ''} "
            f"— pausiere Sync für {_COOLDOWN // 60} Min statt jeden Push erneut zu versuchen.",
        )
