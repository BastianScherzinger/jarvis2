"""
Scrapling-Wrapper für LeadForge — bewusst dünn gehalten: ergänzt die bestehenden
urllib/BeautifulSoup-Scraper (scrapers/*.py), ersetzt sie nicht. Einsatzfälle:

  1. AT/CH-Quellen, für die es noch keinen bestehenden Scraper gibt.
  2. Quellen, die die bestehenden urllib-Scraper aktuell blockieren (Anti-Bot).

Drei Stufen wie bei Scrapling selbst — von leicht zu schwer, damit nie mehr
Aufwand (Browser, Stealth) betrieben wird als für die jeweilige Quelle nötig:

  fetch_plain()    → Fetcher            (schnell, kein Browser)
  fetch_stealth()  → StealthyFetcher    (Anti-Bot-Bypass, Browser headless)
  fetch_dynamic()  → DynamicFetcher     (volle Browser-Interaktion, z.B. Klicks/Scroll)
"""
from __future__ import annotations

import logging

log = logging.getLogger("leadpackages.scrapling_engine")


def fetch_plain(url: str, **kwargs):
    """Schnelle HTTP-Abfrage mit Browser-Impersonation, ohne echten Browser."""
    from scrapling.fetchers import Fetcher
    return Fetcher.get(url, **kwargs)


def fetch_stealth(url: str, headless: bool = True, **kwargs):
    """Stealth-Fetch mit Anti-Bot-Bypass (Cloudflare Turnstile u.a.), headless Browser."""
    from scrapling.fetchers import StealthyFetcher
    return StealthyFetcher.fetch(url, headless=headless, **kwargs)


def fetch_dynamic(url: str, headless: bool = True, **kwargs):
    """Voller Browser (Playwright) für Seiten, die Klicks/Scroll/JS-Rendering brauchen."""
    from scrapling.fetchers import DynamicFetcher
    return DynamicFetcher.fetch(url, headless=headless, **kwargs)


def probe(url: str) -> dict:
    """Testet eine URL nacheinander mit steigender Eskalationsstufe und meldet,
    welche Stufe zuerst durchkam — Diagnose-Helfer für neue Quellen, kein
    Produktions-Pfad (der ruft die passende fetch_*-Funktion direkt gezielt auf)."""
    for stufe, fn in (("plain", fetch_plain), ("stealth", fetch_stealth)):
        try:
            page = fn(url)
            status = getattr(page, "status", None)
            ok = status is None or 200 <= int(status) < 400
            if ok:
                return {"stufe": stufe, "status": status, "ok": True, "len": len(page.body or "")}
            log.info("probe(%s): Stufe %s -> Status %s, eskaliere", url, stufe, status)
        except Exception as e:
            log.info("probe(%s): Stufe %s fehlgeschlagen (%s), eskaliere", url, stufe, e)
    return {"stufe": None, "ok": False}
