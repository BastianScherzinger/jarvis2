"""
Maps-Enrichment — ergänzt Leads aus JEDER Quelle (nicht nur dem Maps-Scraper selbst)
um echte Google-Maps-Fotos, Telefon und Adresse.

Hintergrund: nur scrapers/maps.py (Discovery über viele Städte/Branchen) liest direkt von
Google Maps. Die 4 Verzeichnis-Scraper und der AI-Worker liefern nie Fotos — gerade Leads
OHNE eigene Website (das wertvollste Akquise-Segment) bekommen dadurch oft GAR KEINE echten
Bilder. web_analyst.analyze() ruft enrich() für jeden Lead auf, dessen Fotos noch fehlen,
unabhängig von der Findequelle (siehe dort, Schritt 3b).

Playwright-Sync-API ist NICHT cross-thread-safe für dieselbe Browser-Instanz — deshalb ein
kleiner Pool dedizierter Worker-Threads (analog scrapers/maps.py::run_continuous), jeder mit
EIGENER sync_playwright()-Session, die Anfragen aus einer Queue abarbeiten. Der Evaluator
selbst (bis zu 32 Threads) ruft nur die dünne, blockierende enrich()-Funktion auf — nie
Playwright direkt.
"""
from __future__ import annotations

import os
import queue
import threading

from scrapers import maps_common
import logger

# 20s statt knapper bemessen: gemessen (2026-07-05) brauchte die ERSTE echte Suche eines
# frisch gestarteten Workers (nach dem einmaligen Cookie-Consent-Goto) >12s, obwohl
# nachfolgende Lookups auf derselben warmen Page nur ~6s brauchen — ein zu knapper
# Timeout hätte sonst systematisch genau die ersten Enrichments nach jedem Evaluator-
# Start verloren.
_REQUEST_TIMEOUT_DEFAULT = 20.0

_pool_lock  = threading.Lock()
_started    = False
_request_q: "queue.Queue" = queue.Queue(maxsize=64)
_workers: list = []


def _headless() -> bool:
    return os.environ.get("JARVIS_BROWSER_HEADLESS", "false").lower() == "true"


def _n_threads() -> int:
    try:
        return max(1, int(os.environ.get("JARVIS_MAPS_ENRICH_THREADS", "2") or 2))
    except (ValueError, TypeError):
        return 2


def start_pool() -> None:
    """Startet den Enrichment-Worker-Pool (idempotent, Daemon-Threads)."""
    global _started
    with _pool_lock:
        if _started:
            return
        _started = True
    n = _n_threads()
    for i in range(n):
        t = threading.Thread(target=_worker_loop, name=f"MapsEnrich-{i}", daemon=True)
        t.start()
        _workers.append(t)
    logger.info("MapsEnrich", f"Enrichment-Pool aktiv ({n} Worker).")


def stop_pool() -> None:
    """Signalisiert allen Worker-Threads das Ende (Poison-Pill je Worker)."""
    global _started, _workers
    with _pool_lock:
        if not _started:
            return
        _started = False
    for _ in _workers:
        try:
            _request_q.put_nowait(None)
        except queue.Full:
            pass
    _workers = []


def enrich(lead: dict, timeout: float = _REQUEST_TIMEOUT_DEFAULT) -> dict | None:
    """Sucht EINEN Betrieb auf Google Maps (Name+Stadt) und liefert
    telefon/adresse/foto_url/foto_urls/bewertung/anz_bewertungen — oder None bei
    Timeout/keinem Treffer/gestopptem Pool. Blockiert NIE länger als `timeout`."""
    if not _started:
        return None
    name  = (lead.get("name") or "").strip()
    stadt = (lead.get("stadt") or "").strip()
    if not name:
        return None

    reply: "queue.Queue" = queue.Queue(maxsize=1)
    request = {"name": name, "stadt": stadt,
               "branche": (lead.get("branche") or "").strip(), "reply": reply}
    try:
        _request_q.put_nowait(request)
    except queue.Full:
        return None   # Pool überlastet — lieber kein Enrichment als lange warten

    try:
        return reply.get(timeout=timeout)
    except queue.Empty:
        return None


def _accept_cookies(page) -> None:
    """Einmalig beim Worker-Start: Cookie-Banner wegklicken (analog scrapers/maps.py)."""
    try:
        page.goto("https://www.google.de/maps", timeout=15000)
        page.wait_for_timeout(2000)
        for sel in [
            "button[aria-label*='Alle ablehnen']",
            "button[aria-label*='Accept all']",
            "button[jsname='b3VHJd']",
            "form:last-of-type button",
        ]:
            try:
                page.click(sel, timeout=2000)
                break
            except Exception:
                pass
        page.wait_for_timeout(1000)
    except Exception:
        pass


def _lookup_one(page, name: str, stadt: str, branche: str) -> dict | None:
    query = f"{name} {stadt}".strip()
    url   = f"https://www.google.de/maps/search/{query.replace(' ', '+')}"
    page.goto(url, timeout=15000, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    # Eindeutige Suchen leiten oft DIREKT auf die Detailseite um (keine Ergebnisliste).
    entries = maps_common.find_entries(page)
    if not entries:
        return maps_common.read_detail(page, stadt, branche)

    # Sonst: ersten (relevantesten) Treffer der Liste öffnen.
    return maps_common.extract_entry(page, entries[0], stadt, branche)


def _worker_loop() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warn("MapsEnrich", "Playwright fehlt — Enrichment-Worker beendet sich.")
        return

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=_headless(),
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(
            locale="de-DE",
            viewport={"width": 1366, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        _accept_cookies(page)

        while True:
            request = _request_q.get()
            if request is None:              # Poison-Pill → Worker beenden
                break
            reply = request["reply"]
            try:
                result = _lookup_one(page, request["name"], request["stadt"], request["branche"])
            except Exception as e:
                logger.warn("MapsEnrich", f"Lookup fehlgeschlagen ({request['name']}): "
                                          f"{type(e).__name__}: {str(e)[:120]}")
                result = None
            try:
                reply.put_nowait(result)
            except queue.Full:
                pass   # enrich() hat schon aufgegeben (Timeout) — Ergebnis verwerfen

        try:
            browser.close()
        except Exception:
            pass
