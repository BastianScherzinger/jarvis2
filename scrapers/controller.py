"""
Scraper-Controller — 6 unabhängige Worker laufen parallel.
Vollständig lokal: Scraper + lokale KI (Ollama) finden und bewerten alle Leads.
"""
import os
import queue
import random
import threading
import itertools
import time

from scrapers.regions import ALLE_REGIONEN, BRANCHEN, HIGH_VALUE
from scrapers import maps, gelbe_seiten, dasoertliche, elfacht, golocal
from agents import ai_worker
from agents.evaluator import pipeline as evaluator_pipeline
import db_raw
import logger

_stop_event        = threading.Event()
_active            = False
_evaluator_started = False   # läuft der Evaluator (via Scraper ODER standalone)?
_eval_lock         = threading.Lock()   # schützt _evaluator_started gegen Race Condition

# SSE-Fan-out: jeder verbundene Client bekommt seine EIGENE Queue. Eine einzige
# geteilte Queue würde Events bei mehreren Tabs auf die Clients aufteilen
# (jeder verpasst dann Events der anderen).
_subscribers: set = set()
_sub_lock         = threading.Lock()


def subscribe() -> "queue.Queue":
    """Registriert einen neuen SSE-Client und gibt dessen Queue zurück."""
    q: queue.Queue = queue.Queue(maxsize=2000)
    with _sub_lock:
        _subscribers.add(q)
    return q


def unsubscribe(q) -> None:
    with _sub_lock:
        _subscribers.discard(q)


def is_running()       -> bool:        return _active

# Registry aller benannten Worker-Threads → echte Gesundheit statt globalem Flag.
_workers: dict = {}


def _register(name: str, thread) -> None:
    _workers[name] = thread


def worker_health() -> list:
    """Pro Worker: lebt der Thread wirklich? (deckt still gestorbene Worker auf)."""
    return [{"name": n, "alive": bool(t and t.is_alive())} for n, t in _workers.items()]


def _warmup_model() -> None:
    from scrapers import _http
    modell = _http.best_chat_model()
    logger.info("Ollama", f"Lade Bewertungs-Modell '{modell}' in den Speicher…")
    ok = _http.warmup_ollama()
    logger.success("Ollama", f"Modell '{modell}' bereit.") if ok else \
        logger.warn("Ollama", "Modell nicht erreichbar — Heuristik-Fallback aktiv.")


def _spawn_evaluator() -> None:
    """Startet Warmup + Evaluator-Threads. Idempotent (via _evaluator_started)."""
    global _evaluator_started
    with _eval_lock:
        if _evaluator_started:
            return
        _evaluator_started = True
    threading.Thread(target=_warmup_model, name="Ollama-Warmup", daemon=True).start()
    db_raw.init_db()
    db_raw.reset_stale()
    n_eval = int(os.environ.get("JARVIS_EVAL_THREADS", "4"))
    threading.Thread(
        target=evaluator_pipeline.run_continuous,
        args=(_on_lead, _stop_event, n_eval),
        name="Worker-Evaluator", daemon=True,
    ).start()
    threading.Thread(target=_watchdog_loop, name="Evaluator-Watchdog", daemon=True).start()
    logger.info("Controller", f"Evaluator gestartet ({n_eval} Threads)")


def _watchdog_loop() -> None:
    """Setzt periodisch hängengebliebene 'running'-Leads zurück (Crash-Schutz)."""
    while not _stop_event.is_set():
        time.sleep(120)
        try:
            n = db_raw.reset_stale_running(10)
            if n:
                logger.warn("Watchdog", f"{n} hängende 'running'-Leads → zurück auf pending")
        except Exception:
            pass


def ensure_evaluator_running() -> None:
    """Stellt sicher dass der Evaluator läuft — auch wenn die Scraper aus sind."""
    _stop_event.clear()
    _spawn_evaluator()


def reevaluate_all() -> int:
    """Frische Neubewertung: leert die Ergebnis-DB (DB2) — die Rangliste wird
    leer und füllt sich dann LIVE wieder, jeder neu bewertete Lead erscheint
    sofort an seiner sortierten Position. Setzt alle Roh-Leads auf 'pending'
    und startet den Evaluator. Funktioniert auch bei gestopptem Scraper.
    Gibt Anzahl neu einzustufender Leads zurück."""
    db_raw.init_db()
    import db_evaluated
    db_evaluated.clear_all()                # Rangliste leeren → füllt sich live
    n = db_raw.reset_all_for_reeval()
    ensure_evaluator_running()
    logger.info("Controller", f"Neubewertung: Rangliste geleert, {n} Leads → pending, Evaluator aktiv")
    return n


def get_combo_count() -> int:
    """Anzahl aller Stadt×Branche-Kombinationen (Deutschland-weit)."""
    return len(ALLE_REGIONEN) * len(BRANCHEN)


def set_verifier_model(model: str) -> None:
    """Setzt das Bewertungs-Modell zur Laufzeit (Dashboard-Dropdown)."""
    os.environ["JARVIS_VERIFIER_MODEL"] = model
    os.environ["JARVIS_EVAL_MODEL"]     = model   # steuert den Evaluator/ScoreWriter
    from scrapers import _http
    _http._BEST_MODEL[0] = None                   # Modell-Cache invalidieren


def get_verifier_model() -> str:
    """Aktuell aktives Bewertungs-Modell."""
    from scrapers import _http
    return _http.best_chat_model()


def start() -> None:
    global _active
    if _active:
        return
    _stop_event.clear()
    _active = True

    logger.info("Controller", f"Starte {6} Scraper-Worker + Evaluator | Combos: {get_combo_count():,}")

    # ~40.000 Combos (1000 Städte × 43 Branchen). Gemischt + in 6 Chunks
    # aufgeteilt — jeder Worker bekommt seinen eigenen Teil, keine Überlappung
    # = kein doppeltes Scrapen, breite Deutschland-Abdeckung von Anfang an.
    combos = list(itertools.product(ALLE_REGIONEN, BRANCHEN))
    random.shuffle(combos)

    n  = len(combos)
    k  = n // 6
    chunks = [
        combos[:k], combos[k:2 * k], combos[2 * k:3 * k],
        combos[3 * k:4 * k], combos[4 * k:5 * k], combos[5 * k:],
    ]

    # Priorisierung: jeder Worker beginnt mit High-Value-Branchen in großen Städten
    # (ALLE_REGIONEN ist groß-zuerst sortiert) → früh viele Hot-Leads, gleichmäßig
    # über alle 6 Worker verteilt, ohne Überlappung.
    _stadt_rang = {stadt: i for i, stadt in enumerate(ALLE_REGIONEN)}
    def _prio(combo):
        stadt, branche = combo
        return (0 if branche in HIGH_VALUE else 1, _stadt_rang.get(stadt, 99999))
    for ch in chunks:
        ch.sort(key=_prio)
    c1, c2, c3, c4, c5, c6 = chunks

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

    # Worker 6: Lokale KI (Ollama, recherchiert via Websuche, versetzt 15s)
    _spawn("AI",           ai_worker.run_continuous,     c6, delay=15, max_per=8)

    # Der frühere Verifier (auf der entfernten leads.db) ist abgeschafft — das
    # Evaluator-Team (db_evaluated) ist die kanonische Bewertungs-Pipeline.
    # Hängende 'running'-Roh-Leads räumt der Evaluator-Watchdog (db_raw) auf.

    # Evaluator-Team: liest aus leads_raw (Queue), schreibt nach leads_evaluated.
    # Enthält Warmup + ist idempotent.
    _spawn_evaluator()


def stop() -> None:
    global _active, _evaluator_started
    logger.info("Controller", "Stop-Signal gesendet — alle Worker beenden")
    _stop_event.set()
    _active = False
    _evaluator_started = False


def _on_lead(lead: dict) -> None:
    """Verteilt ein Event an ALLE verbundenen SSE-Clients (Fan-out)."""
    with _sub_lock:
        subs = list(_subscribers)
    for q in subs:
        try:
            q.put_nowait(lead)
        except queue.Full:
            pass   # langsamer/toter Client → Event verwerfen, nie blockieren


def _spawn(name: str, fn, combos, delay: float = 0, **kwargs):
    logger.info("Controller", f"Worker '{name}' gestartet (Delay: {delay}s)")

    def _run():
        if delay:
            time.sleep(delay)
        fn(combos, _on_lead, _stop_event, **kwargs)

    t = threading.Thread(target=_run, name=f"Worker-{name}", daemon=True)
    t.start()
    _register(name, t)
