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
from scrapers import maps, gelbe_seiten, dasoertliche, elfacht, golocal, verifier
from agents import ai_worker
from agents.evaluator import pipeline as evaluator_pipeline
import db
import db_raw

_lead_queue     = queue.Queue()
_stop_event     = threading.Event()
_active         = False
_claude_enabled = False   # aus/an per API-Aufruf


def get_queue()        -> queue.Queue: return _lead_queue
def is_running()       -> bool:        return _active
def is_claude_enabled()-> bool:        return _claude_enabled

def get_ai_mode() -> str:
    return "both" if _claude_enabled else "local"


def get_combo_count() -> int:
    """Anzahl aller Stadt×Branche-Kombinationen (Deutschland-weit)."""
    return len(ALLE_REGIONEN) * len(BRANCHEN)


def set_claude_enabled(enabled: bool) -> None:
    global _claude_enabled
    _claude_enabled = enabled
    # Umgebungsvariable setzen — ai_worker liest diese dynamisch
    os.environ["JARVIS_CLAUDE_ENABLED"] = "1" if enabled else "0"


def set_verifier_model(model: str) -> None:
    os.environ["JARVIS_VERIFIER_MODEL"] = model


def get_verifier_model() -> str:
    return os.environ.get("JARVIS_VERIFIER_MODEL", "") or \
        os.environ.get("JARVIS_LOCAL_MODEL", "qwen2.5:7b")


def start() -> None:
    global _active
    if _active:
        return
    _stop_event.clear()
    _active = True

    # ~40.000 Combos (1000 Städte × 43 Branchen). Gemischt + in 6 Chunks
    # aufgeteilt — jeder Worker bekommt seinen eigenen Teil, keine Überlappung
    # = kein doppeltes Scrapen, breite Deutschland-Abdeckung von Anfang an.
    combos = list(itertools.product(ALLE_REGIONEN, BRANCHEN))
    random.shuffle(combos)

    n  = len(combos)
    k  = n // 6
    c1 = combos[:k]
    c2 = combos[k:2 * k]
    c3 = combos[2 * k:3 * k]
    c4 = combos[3 * k:4 * k]
    c5 = combos[4 * k:5 * k]
    c6 = combos[5 * k:]

    # Worker 1: Google Maps (persistenter Browser)
    _spawn("Maps",         maps.run_continuous,          c1, max_per=20)

    # Worker 2: Gelbe Seiten (versetzt 3s)
    _spawn("GelbeSeit",    gelbe_seiten.run_continuous,  c2, delay=3,  max_per=20)

    # Worker 3: Das Örtliche (versetzt 6s)
    _spawn("DasOertliche", dasoertliche.run_continuous,  c3, delay=6,  max_per=15)

    # Worker 4: 11880 (versetzt 9s)
    _spawn("Elfacht",      elfacht.run_continuous,       c4, delay=9,  max_per=20)

    # Worker 5: golocal (versetzt 12s)
    _spawn("Golocal",      golocal.run_continuous,       c5, delay=12, max_per=20)

    # Worker 6: AI (Ollama + optional Claude, versetzt 15s)
    _spawn("AI",           ai_worker.run_continuous,     c6, delay=15, max_per=8)

    # Verifier: prüft gefundene Leads per lokaler KI nach (eigene Thread-Gruppe)
    db.reset_stale_running()
    n_verifier = int(os.environ.get("JARVIS_VERIFIER_THREADS", "3"))
    threading.Thread(
        target=verifier.run_continuous, args=(_on_lead, _stop_event, n_verifier),
        name="Worker-Verifier", daemon=True,
    ).start()

    # Evaluator-Team: liest aus DB1 (leads_raw), schreibt nach DB2 (leads_evaluated)
    db_raw.init_db()
    db_raw.reset_stale()
    n_eval = int(os.environ.get("JARVIS_EVAL_THREADS", "3"))
    threading.Thread(
        target=evaluator_pipeline.run_continuous,
        args=(_on_lead, _stop_event, n_eval),
        name="Worker-Evaluator",
        daemon=True,
    ).start()


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
