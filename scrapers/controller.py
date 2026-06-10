"""
Scraper-Controller — orchestriert alle 3 Scraper parallel in Threads.
Läuft als Endlos-Loop bis stop_event gesetzt wird.
"""
import queue
import threading
import itertools
import time

from scrapers.regions import ALLE_REGIONEN, BRANCHEN
from scrapers import maps, gelbe_seiten
from agents import ai_worker

# Globale Queues / Events
_lead_queue  = queue.Queue()
_stop_event  = threading.Event()
_active      = False
_ai_mode     = "local"   # 'local' | 'cloud' | 'both'


def get_queue()  -> queue.Queue:
    return _lead_queue

def is_running() -> bool:
    return _active

def get_ai_mode() -> str:
    return _ai_mode


def start(ai_mode: str = "local") -> None:
    global _active, _ai_mode
    if _active:
        return
    _ai_mode = ai_mode
    _stop_event.clear()
    _active = True

    t = threading.Thread(target=_main_loop, daemon=True)
    t.start()


def stop() -> None:
    global _active
    _stop_event.set()
    _active = False


def _main_loop():
    """
    Iteriert endlos über alle Region+Branche-Kombinationen.
    Jede Kombination: Maps + GelbeSeit + AI parallel.
    """
    combos = list(itertools.product(ALLE_REGIONEN, BRANCHEN))

    while not _stop_event.is_set():
        for region, branche in combos:
            if _stop_event.is_set():
                break

            threads = []

            # Scraper 1: Google Maps (Playwright)
            t1 = threading.Thread(
                target=maps.run_loop,
                args=(region, branche, _on_lead, _stop_event),
                kwargs={"max_per": 30},
                daemon=True,
            )
            threads.append(t1)

            # Scraper 2: Gelbe Seiten
            t2 = threading.Thread(
                target=gelbe_seiten.run_loop,
                args=(region, branche, _on_lead, _stop_event),
                kwargs={"max_per": 20},
                daemon=True,
            )
            threads.append(t2)

            # Scraper 3: AI-Worker
            t3 = threading.Thread(
                target=ai_worker.run_loop,
                args=(region, branche, _on_lead, _stop_event),
                kwargs={"ai_mode": _ai_mode, "max_per": 15},
                daemon=True,
            )
            threads.append(t3)

            for t in threads:
                t.start()

            # Warten bis alle fertig oder Stop
            for t in threads:
                while t.is_alive() and not _stop_event.is_set():
                    t.join(timeout=2.0)

            if not _stop_event.is_set():
                time.sleep(2)   # kurze Pause zwischen Regionen


def _on_lead(lead: dict) -> None:
    """Wird von jedem Scraper aufgerufen — legt Lead in die Queue."""
    _lead_queue.put(lead)
