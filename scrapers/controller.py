"""
Scraper-Controller — 4 unabhängige Worker laufen parallel.

Worker 1: Google Maps (1 persistenter Browser, durchläuft alle Kombis)
Worker 2: Gelbe Seiten (HTTP, leicht)
Worker 3: Das Örtliche (HTTP, leicht)
Worker 4: AI Worker (Ollama/Claude)

Jeder Worker läuft endlos in seinem eigenen Thread.
Kein sequentielles Warten mehr — alle 4 finden gleichzeitig.
"""
import queue
import threading
import itertools
import random
import time

from scrapers.regions import ALLE_REGIONEN, BRANCHEN
from scrapers import maps, gelbe_seiten, dasoertliche
from agents import ai_worker

_lead_queue = queue.Queue()
_stop_event = threading.Event()
_active     = False
_ai_mode    = "local"
_workers: list[threading.Thread] = []


def get_queue()  -> queue.Queue:   return _lead_queue
def is_running() -> bool:          return _active
def get_ai_mode() -> str:          return _ai_mode


def start(ai_mode: str = "local") -> None:
    global _active, _ai_mode, _workers
    if _active:
        return
    _ai_mode = ai_mode
    _stop_event.clear()
    _active   = True
    _workers  = []

    # Alle Combis einmal mischen — verschiedene Einstiegspunkte pro Worker
    combos = list(itertools.product(ALLE_REGIONEN, BRANCHEN))

    # Worker 1: Google Maps — persistenter Browser
    combos_maps = combos[:]
    random.shuffle(combos_maps)
    t1 = threading.Thread(
        target=maps.run_continuous,
        args=(combos_maps, _on_lead, _stop_event),
        kwargs={"max_per": 25},
        name="Worker-Maps",
        daemon=True,
    )
    _workers.append(t1)

    # Worker 2: Gelbe Seiten — versetzt starten
    combos_gs = combos[:]
    random.shuffle(combos_gs)
    t2 = threading.Thread(
        target=_delayed(gelbe_seiten.run_continuous, delay=3),
        args=(combos_gs, _on_lead, _stop_event),
        kwargs={"max_per": 25},
        name="Worker-GelbeSeit",
        daemon=True,
    )
    _workers.append(t2)

    # Worker 3: Das Örtliche
    combos_do = combos[:]
    random.shuffle(combos_do)
    t3 = threading.Thread(
        target=_delayed(dasoertliche.run_continuous, delay=6),
        args=(combos_do, _on_lead, _stop_event),
        kwargs={"max_per": 20},
        name="Worker-DasOertliche",
        daemon=True,
    )
    _workers.append(t3)

    # Worker 4: AI-Worker (Ollama/Claude)
    combos_ai = combos[:]
    random.shuffle(combos_ai)
    t4 = threading.Thread(
        target=_delayed(ai_worker.run_continuous, delay=12),
        args=(combos_ai, _on_lead, _stop_event),
        kwargs={"ai_mode": ai_mode, "max_per": 10},
        name="Worker-AI",
        daemon=True,
    )
    _workers.append(t4)

    for t in _workers:
        t.start()


def stop() -> None:
    global _active
    _stop_event.set()
    _active = False


def _on_lead(lead: dict) -> None:
    _lead_queue.put(lead)


def _delayed(fn, delay: float):
    """Wrapper der eine Funktion erst nach `delay` Sekunden startet."""
    def wrapper(*args, **kwargs):
        time.sleep(delay)
        fn(*args, **kwargs)
    return wrapper
