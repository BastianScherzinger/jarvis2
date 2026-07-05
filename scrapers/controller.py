"""
Scraper-Controller — 6 unabhängige DE+AT-Worker laufen parallel, plus ein 7. Worker
(herold.at) nur für Österreich, wenn AT-Combos vorhanden sind.
Vollständig lokal: Scraper + lokale KI (Ollama) finden und bewerten alle Leads.
"""
import json
import os
import queue
import random
import threading
import itertools
import time
from pathlib import Path

from scrapers.regions import ALLE_REGIONEN, BRANCHEN, HIGH_VALUE
from scrapers import maps, gelbe_seiten, dasoertliche, elfacht, golocal, herold_worker
from leadpackages.sources_dach import AT_STAEDTE
from agents import ai_worker
from agents.evaluator import pipeline as evaluator_pipeline
import db_raw
import logger

_stop_event        = threading.Event()   # stoppt den EVALUATOR (+ Watchdog) — "Master"-Stop
_scraper_stop_event = threading.Event()  # stoppt NUR die 6 Scraper-Worker
_active            = False
_evaluator_started = False   # läuft der Evaluator (via Scraper ODER standalone)?
_eval_lock         = threading.Lock()   # schützt _evaluator_started gegen Race Condition

# Persistenter An/Aus-Schalter — überlebt Schließen/Absturz/Neustart, analog zu
# auto_builder._persist_running(). Stand "running": true → resume_if_needed() nimmt
# das Sammeln beim nächsten App-Start automatisch wieder auf. Die eigentlichen Daten
# (Leads) liegen ohnehin durchgehend committet in db_raw/db_evaluated (WAL-Modus) —
# dieser Schalter merkt sich nur, OB Sir zuletzt "an" wollte, nicht die Lead-Daten selbst.
_STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "scraper_state.json"


def _persist_running(running: bool) -> None:
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(
            json.dumps({"running": bool(running), "ts": time.time()}, ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        pass


def _persisted_running() -> bool:
    try:
        return bool(json.loads(_STATE_PATH.read_text(encoding="utf-8")).get("running"))
    except Exception:
        return False


def resume_if_needed() -> bool:
    """Beim App-Start aufrufen: war der Sammler beim letzten Mal an (Sir hat nicht
    aktiv gestoppt), nimmt er automatisch wieder auf — Sir muss nach einem Schließen/
    Absturz nicht erneut auf Start drücken."""
    if _persisted_running() and not is_running():
        logger.info("Controller", "Vorheriger Sammel-Lauf war aktiv → automatische Fortsetzung")
        start()
        return True
    return False

# Beide Events werden NIE wiederverwendet/geclearet — jeder start()/_spawn_evaluator()
# erzeugt ein FRISCHES Event-Objekt für seine Generation und reicht es den Threads dieser
# Generation explizit als Parameter durch (nicht per Modul-Global-Lookup zur Laufzeit).
# Damit kann ein spätes Clear() einer neuen Generation nie ein Alt-Worker "wiederbeleben",
# der das Stop-Signal seiner eigenen (weiterhin gesetzten) Generation noch nicht gesehen hat —
# das frühere Event-Race (siehe stop()) ist damit strukturell ausgeschlossen, nicht nur verzögert.

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
    """Startet Warmup + Evaluator-Threads. Idempotent (via _evaluator_started).
    Erzeugt pro Generation ein frisches _stop_event (siehe Modul-Kopf) — reicht es
    explizit an Evaluator- und Watchdog-Threads weiter, damit ein späteres stop()/
    _spawn_evaluator() dieser Generation nichts an bereits laufenden Alt-Threads ändert."""
    global _evaluator_started, _stop_event
    with _eval_lock:
        if _evaluator_started:
            return
        _evaluator_started = True
        my_stop_event = threading.Event()
        _stop_event = my_stop_event
    threading.Thread(target=_warmup_model, name="Ollama-Warmup", daemon=True).start()
    db_raw.init_db()
    db_raw.reset_stale()
    from agents.evaluator import maps_enrichment
    maps_enrichment.start_pool()
    # Max Threads = CPU-Kerne des PCs (so parallelisiert die Bewertung maximal; die
    # eigentlichen Ollama-Calls bleiben durch JARVIS_OLLAMA_PARALLEL geschützt).
    _default_eval = min(32, max(4, (os.cpu_count() or 4)))
    try:
        n_eval = int(os.environ.get("JARVIS_EVAL_THREADS", str(_default_eval)) or _default_eval)
    except (ValueError, TypeError):
        n_eval = _default_eval
    threading.Thread(
        target=evaluator_pipeline.run_continuous,
        args=(_on_lead, my_stop_event, n_eval),
        name="Worker-Evaluator", daemon=True,
    ).start()
    threading.Thread(target=_watchdog_loop, args=(my_stop_event,),
                      name="Evaluator-Watchdog", daemon=True).start()
    logger.info("Controller", f"Evaluator gestartet ({n_eval} Threads)")


def _watchdog_loop(stop_event: threading.Event) -> None:
    """Setzt periodisch hängengebliebene 'running'-Leads zurück (Crash-Schutz).
    Bekommt das Event seiner eigenen Generation explizit übergeben (siehe Kommentar
    oben bei den Modul-Events) statt es aus dem Modul-Global neu aufzulösen."""
    while not stop_event.is_set():
        time.sleep(120)
        try:
            n = db_raw.reset_stale_running(10)
            if n:
                logger.warn("Watchdog", f"{n} hängende 'running'-Leads → zurück auf pending")
        except Exception:
            pass


def ensure_evaluator_running() -> None:
    """Stellt sicher dass der Evaluator läuft — auch wenn die Scraper aus sind."""
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
    """Anzahl aller Stadt×Branche-Kombinationen (DACH: Deutschland + Österreich)."""
    return (len(ALLE_REGIONEN) + len(AT_STAEDTE)) * len(BRANCHEN)


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
    global _active, _scraper_stop_event
    if _active:
        return
    # Frisches Event für diese Scraper-Generation (siehe Modul-Kopf-Kommentar) — kein
    # Clear() eines evtl. noch von Alt-Workern beobachteten Events mehr.
    _scraper_stop_event = threading.Event()
    _active = True
    _persist_running(True)

    logger.info("Controller", "Starte Scraper-Worker (Maps, GelbeSeit, DasOertliche, Elfacht, "
                "Golocal, AI + herold.at bei AT-Combos) + Evaluator | "
                f"Combos: {get_combo_count():,}")

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

    # Österreich: eigener Combo-Pool, NUR an Quellen verteilt die AT tatsächlich abdecken
    # (Maps + AI-Worker sind global, herold.at ist AT-spezifisch). Die 4 DE-Verzeichnis-
    # Scraper (gelbeseiten.de/dasoertliche.de/11880.com/golocal.de) bekommen weiterhin
    # AUSSCHLIESSLICH combos_de — für AT-Städte lägen dort nur 0-Treffer-Anfragen vor.
    combos_at = list(itertools.product(AT_STAEDTE, BRANCHEN))
    random.shuffle(combos_at)
    k_at = max(1, len(combos_at) // 3)
    at_maps, at_ai, at_herold = (
        combos_at[:k_at], combos_at[k_at:2 * k_at], combos_at[2 * k_at:]
    )
    c1 = c1 + at_maps
    c6 = c6 + at_ai
    c1.sort(key=_prio)   # AT-Städte fehlen in _stadt_rang → rutschen ans Ende ihrer Branchen-Stufe
    c6.sort(key=_prio)

    # Worker 1: Google Maps (persistenter Browser) — DE + AT
    _spawn("Maps",         maps.run_continuous,          c1, max_per=20)

    # Worker 2: Gelbe Seiten (versetzt 3s) — DE
    _spawn("GelbeSeit",    gelbe_seiten.run_continuous,  c2, delay=3,  max_per=20)

    # Worker 3: Das Örtliche (versetzt 6s) — DE
    _spawn("DasOertliche", dasoertliche.run_continuous,  c3, delay=6,  max_per=15)

    # Worker 4: 11880 (versetzt 9s) — DE
    _spawn("Elfacht",      elfacht.run_continuous,       c4, delay=9,  max_per=20)

    # Worker 5: golocal (versetzt 12s) — DE
    _spawn("Golocal",      golocal.run_continuous,       c5, delay=12, max_per=20)

    # Worker 6: Lokale KI (Ollama, recherchiert via Websuche, versetzt 15s) — DE + AT
    _spawn("AI",           ai_worker.run_continuous,     c6, delay=15, max_per=8)

    # Worker 7: herold.at (österreichisches Branchenverzeichnis, versetzt 18s) — nur AT
    if at_herold:
        _spawn("HeroldAT", herold_worker.run_continuous, at_herold, delay=18, max_per=15)

    # Der frühere Verifier (auf der entfernten leads.db) ist abgeschafft — das
    # Evaluator-Team (db_evaluated) ist die kanonische Bewertungs-Pipeline.
    # Hängende 'running'-Roh-Leads räumt der Evaluator-Watchdog (db_raw) auf.

    # Evaluator-Team: liest aus leads_raw (Queue), schreibt nach leads_evaluated.
    # Enthält Warmup + ist idempotent.
    _spawn_evaluator()


def stop() -> None:
    """Voller Stop: Scraper UND Evaluator sofort beenden (Dashboard-Stop-Button)."""
    global _active, _evaluator_started
    logger.info("Controller", "Stop-Signal gesendet — alle Worker beenden")
    _scraper_stop_event.set()
    _stop_event.set()
    _active = False
    _persist_running(False)   # echter Nutzer-Stop — resume_if_needed() lässt es beim nächsten Start aus
    # Reset unter demselben Lock, unter dem _spawn_evaluator ihn prüft/setzt (Flag-Race).
    # Ein unmittelbar folgendes start()/_spawn_evaluator() erzeugt für die NÄCHSTE Generation
    # ein frisches Event-Objekt (siehe Modul-Kopf) statt dieses hier zu clearen — Alt-Worker,
    # die noch auf dieses (jetzt dauerhaft gesetzte) Event warten, sehen das Stop-Signal
    # garantiert. JARVIS_LEAD_STOP_BUFFER bleibt trotzdem sinnvoll: er gibt einem gerade
    # IN-FLIGHT befindlichen Lead (z.B. mitten in einem Ollama-Call) Zeit, fertig zu werden
    # und noch in DB2 zu landen, bevor der Lead-Collector die Trefferzahl zählt.
    with _eval_lock:
        _evaluator_started = False
    from agents.evaluator import maps_enrichment
    maps_enrichment.stop_pool()


def stop_scrapers() -> None:
    """Stoppt NUR die 6 Scraper-Worker, der Evaluator läuft weiter und arbeitet den
    Rest-Backlog (bereits gesammelte, noch nicht bewertete Leads) ab. Für den
    Lead-Collector: Sammel-Fenster ist um, aber frisch gesammelte Leads sollen noch
    bewertet werden, bevor auch der Evaluator gestoppt wird (siehe stop_evaluator)."""
    global _active
    logger.info("Controller", "Stop-Signal an Scraper — Evaluator arbeitet Rest-Backlog ab")
    _scraper_stop_event.set()
    _active = False


def stop_evaluator() -> None:
    """Stoppt den Evaluator (+ Watchdog) separat, NACHDEM der Rest-Backlog leer ist
    (oder die Wartezeit dafür abgelaufen ist). Gegenstück zu stop_scrapers()."""
    global _evaluator_started
    logger.info("Controller", "Stop-Signal an Evaluator")
    _stop_event.set()
    with _eval_lock:
        _evaluator_started = False
    from agents.evaluator import maps_enrichment
    maps_enrichment.stop_pool()


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
        fn(combos, _on_lead, _scraper_stop_event, **kwargs)

    t = threading.Thread(target=_run, name=f"Worker-{name}", daemon=True)
    t.start()
    _register(name, t)
