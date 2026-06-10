"""
Scraper-Controller — 4 unabhängige Worker laufen parallel.
Claude kann jederzeit per set_claude_enabled() an/abgeschaltet werden.
"""
import os
import queue
import random
import threading
import itertools
import time

from scrapers.regions import ALLE_REGIONEN, BRANCHEN
from scrapers import maps, gelbe_seiten, dasoertliche
from agents import ai_worker

_lead_queue     = queue.Queue()
_stop_event     = threading.Event()
_active         = False
_claude_enabled = False   # aus/an per API-Aufruf


def get_queue()        -> queue.Queue: return _lead_queue
def is_running()       -> bool:        return _active
def is_claude_enabled()-> bool:        return _claude_enabled

def get_ai_mode() -> str:
    return "both" if _claude_enabled else "local"


def set_claude_enabled(enabled: bool) -> None:
    global _claude_enabled
    _claude_enabled = enabled
    # Umgebungsvariable setzen — ai_worker liest diese dynamisch
    os.environ["JARVIS_CLAUDE_ENABLED"] = "1" if enabled else "0"


def start() -> None:
    global _active
    if _active:
        return
    _stop_event.clear()
    _active = True

    combos = list(itertools.product(ALLE_REGIONEN, BRANCHEN))

    # Worker 1: Google Maps (persistenter Browser)
    c1 = combos[:]
    random.shuffle(c1)
    _spawn("Maps",        maps.run_continuous,           c1, max_per=25)

    # Worker 2: Gelbe Seiten (versetzt 3s)
    c2 = combos[:]
    random.shuffle(c2)
    _spawn("GelbeSeit",   gelbe_seiten.run_continuous,   c2, delay=3, max_per=25)

    # Worker 3: Das Örtliche (versetzt 6s)
    c3 = combos[:]
    random.shuffle(c3)
    _spawn("DasOertliche",dasoertliche.run_continuous,   c3, delay=6, max_per=20)

    # Worker 4: AI (Ollama + optional Claude, versetzt 12s)
    c4 = combos[:]
    random.shuffle(c4)
    _spawn("AI",          ai_worker.run_continuous,       c4, delay=12, max_per=10)


def stop() -> None:
    global _active
    _stop_event.set()
    _active = False


def _on_lead(lead: dict) -> None:
    _lead_queue.put(lead)


def _spawn(name: str, fn, combos, delay: float = 0, **kwargs):
    def _run():
        if delay:
            time.sleep(delay)
        fn(combos, _on_lead, _stop_event, **kwargs)

    t = threading.Thread(target=_run, name=f"Worker-{name}", daemon=True)
    t.start()
