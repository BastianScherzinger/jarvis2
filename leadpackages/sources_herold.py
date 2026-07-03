"""
herold.at-Scraper — erste echte AT-Quelle für LeadForge (Entscheidung: DACH-Scope).

robots.txt von herold.at geprüft (2026-07-03): Branchenverzeichnis/Suche ist NICHT
gesperrt (nur Admin-/interne Pfade wie /servlet/, /data/, /meinherold/ u.ä.).

Extraktion (validiert gegen "Elektriker Wien", 31 Treffer): jede Trefferkarte ist ein
<article itemtype="https://schema.org/LocalBusiness"> mit:
  - Name:    <meta itemprop="name" content="..."> (Text leer, Wert steht im content-Attribut)
  - Adresse: [itemprop="streetAddress"] als Text
  - Telefon/E-Mail/Website: ganz normale <a href="tel:...">/<a href="mailto:...">/
    externe <a href="https://..."> (nicht herold.at) INNERHALB der Karte — kein
    Reverse-Engineering des internen Seiten-States nötig.
Ein Sponsored-Slot dupliziert gelegentlich den ersten organischen Treffer (gleicher
Name+Telefon) — wird über ein (name, telefon)-Set dedupliziert.
"""
from __future__ import annotations

import re
import threading
import time

from leadkey import lead_key

from leadpackages import scrapling_engine as se
from leadpackages import sources_dach

BASE = "https://www.herold.at"

_UMLAUT = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}

_MIN_INTERVAL_SEC = 2.5     # eigenes Rate-Limit gegenüber herold.at (analog Sleeps in scrapers/*)
_rate_lock = threading.Lock()
_last_call = [0.0]


def _slug(text: str) -> str:
    text = text or ""
    for k, v in _UMLAUT.items():
        text = text.replace(k, v)
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _respect_rate_limit() -> None:
    with _rate_lock:
        wait = _last_call[0] + _MIN_INTERVAL_SEC - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()


def _first_text(node, selector: str) -> str:
    matches = node.css(selector)
    return (matches[0].get_all_text() or "").strip() if matches else ""


def _extract_links(card) -> dict:
    tel = mail = web = ""
    for a in card.css("a"):
        href = a.attrib.get("href") or ""
        if href.startswith("tel:") and not tel:
            tel = href[4:].strip()
        elif href.startswith("mailto:") and not mail:
            mail = href[7:].split("?")[0].strip()
        elif href.startswith("http") and "herold.at" not in href and not web:
            web = href.strip()
    return {"telefon": tel, "email_adresse": mail, "website_url": web}


def search(branche: str, stadt: str, max_results: int = 50) -> list[dict]:
    """Eine Suche (branche+stadt) gegen herold.at. Gibt eine Liste von dicts im
    stock_leads-Feldformat zurück (land='AT'). Bei 0 Treffern: leere Liste (kein Fehler) —
    z.B. weil die interne Branchen-Bezeichnung nicht 1:1 auf eine herold.at-Kategorie passt
    (kommt bei manchen BRANCHEN-Einträgen vor, dann liefert herold.at 404/leere Seite)."""
    _respect_rate_limit()
    url = f"{BASE}/gelbe-seiten/{_slug(stadt)}/{_slug(branche)}/"
    page = se.fetch_plain(url)
    status = getattr(page, "status", 200)
    if status and int(status) >= 400:
        return []

    cards = page.css('[itemtype*="LocalBusiness"]')
    region = sources_dach.get_region("AT", stadt) or stadt

    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for card in cards[:max_results]:
        name = _first_text(card, '[itemprop="name"]')
        if not name:
            meta = card.css('[itemprop="name"]')
            name = meta[0].attrib.get("content", "").strip() if meta else ""
        if not name:
            continue

        links = _extract_links(card)
        dedup_key = (name.lower(), links["telefon"])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        adresse = _first_text(card, '[itemprop="streetAddress"]')
        out.append({
            "lead_key": lead_key(name, stadt),
            "name": name,
            "adresse": adresse,
            "stadt": stadt,
            "region": region,
            "land": "AT",
            "branche": branche,
            "telefon": links["telefon"],
            "email_adresse": links["email_adresse"],
            "website_url": links["website_url"],
            "has_website": 1 if links["website_url"] else 0,
            "quelle": "herold_scrapling",
        })
    return out
