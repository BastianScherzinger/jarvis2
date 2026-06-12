"""
AI-gestützter Scraper — lokale KI (Ollama) sucht selbstständig im Internet nach Leads.
Ollama generiert Suchanfragen, recherchiert via DuckDuckGo + extrahiert Daten aus Webseiten-Text.
Vollständig lokal — kein externer API-Dienst nötig.
"""
import json
import os
import re
import time
import itertools

from agents.scorer import score as calc_score
from agents.quality import is_real_business
from scrapers.website_checker import check_website
from scrapers.regions import get_bundesland
from scrapers import _http
from scrapers import synonyme
import db
import db_raw as _db_raw
import logger

# Synonym-Cache lazy laden (gecacht → kein Ollama-Spam pro Combo).
# Erst beim ersten run_continuous-Aufruf, damit der Import (→ Flask-Start)
# nicht durch eine evtl. Ollama-Generierung blockiert wird.
_SYNONYME: dict[str, list[str]] = {}


def _load_synonyme() -> None:
    global _SYNONYME
    if _SYNONYME:
        return
    try:
        _SYNONYME = synonyme.get_expanded_branchen() or {}
    except Exception:
        _SYNONYME = {}


# ── HTTP- & KI-Helfer (aus scrapers._http) ─────────────────────────────────────

_get        = _http.get
_ddg_search = _http.ddg_search
_extract_json = _http.extract_json


def _ask_ollama(prompt: str, system: str = "") -> str:
    # Worker nutzt JARVIS_TOOL_MODEL falls gesetzt, sonst Standard-Modellwahl
    return _http.ask_ollama(prompt, system, model=os.environ.get("JARVIS_TOOL_MODEL", ""))


# ── Hauptschleife ─────────────────────────────────────────────────────────────

def run_continuous(all_combos: list[tuple], on_lead, stop_event,
                   max_per: int = 12):
    """
    Langlebiger Thread — lokale KI (Ollama) recherchiert eigenständig im Internet
    (DuckDuckGo) nach Betrieben und extrahiert deren Daten. Vollständig lokal.
    """
    _load_synonyme()
    for region, branche in itertools.cycle(all_combos):
        if stop_event.is_set():
            break

        try:
            _run_one_combo(region, branche, on_lead, stop_event,
                           _ask_ollama, "ollama_ai", max_per)
        except Exception as e:
            on_lead({"_error": f"AI ({region}/{branche}): {e}"})

        time.sleep(2.0)


def _run_one_combo(region, branche, on_lead, stop_event, ask, finder_key, max_per):
    logger.scrape("AI-Worker", f"Recherchiere: {branche} | {region}")
    # Schritt 1: EINE Suchanfrage pro Combo (bester Synonym-Begriff). Mehr Suchen
    # würden nur das globale Such-Budget verbrauchen, das der Evaluator (Website-
    # Findung) dringender braucht. Die HTTP-/Maps-Scraper finden die meisten Leads.
    synonyme_liste = _SYNONYME.get(branche) or []
    bester = synonyme_liste[0] if synonyme_liste else branche
    queries: list[str] = [f"{bester} {region}"]

    found = 0
    for query in queries:
        if stop_event.is_set() or found >= max_per:
            break

        results = _ddg_search(query)
        logger.debug("AI-Worker", f"{len(results)} URLs gefunden für '{query}'")

        for res in results:
            if stop_event.is_set() or found >= max_per:
                break

            url   = res.get("url", "")
            title = res.get("title", "")
            if not title or not url.startswith("http"):
                continue

            # Seite laden + Text extrahieren
            html    = _get(url)
            content = re.sub(r"<[^>]+>", " ", html)
            content = re.sub(r"\s{2,}", " ", content)[:2000]

            # KI extrahiert Firmendaten
            extract_prompt = (
                f"Extrahiere Firmendaten aus diesem Text. "
                f"Antworte NUR mit einem JSON-Objekt (kein Markdown, keine Erklärung).\n\n"
                f"Text: {content[:1200]}\n\n"
                f'{{"name":"Firmenname","adresse":"Str. Nr, PLZ Stadt","telefon":"+49...","website_url":"https://...oder leer","branche":"{branche}"}}'
            )

            raw  = ask(extract_prompt) if ask else ""
            data = _extract_json(raw)
            if not raw:
                logger.warn("AI-Worker", "Ollama nicht erreichbar — Fallback")

            name = (data.get("name") or title)[:120]
            if not name or len(name.strip()) < 3:
                continue

            website_url = (data.get("website_url") or "").strip()
            if not website_url or website_url == url:
                website_url = ""
            has_web  = bool(website_url and website_url.startswith("http"))
            web_info = check_website(website_url) if has_web else {}

            lead = {
                "name":           name,
                "adresse":        (data.get("adresse") or "")[:200],
                "stadt":          region,
                "bundesland":     get_bundesland(region),
                "branche":        branche,
                "telefon":        (data.get("telefon") or "")[:50],
                "website_url":    website_url[:300] if has_web else "",
                "has_website":    int(has_web),
                "website_alter":  web_info.get("alter_jahre", -1),
                "bewertung":      0.0,
                "anz_bewertungen": 0,
                "bilder":         0,
                "finder":         finder_key,
                "maps_url":       "",
            }

            ok, _grund = is_real_business(lead)
            if not ok:
                continue

            pts, typ         = calc_score(lead)
            lead["score"]    = pts
            lead["lead_typ"] = typ

            lead_id = db.insert(lead)
            _db_raw.insert_raw(lead)   # auch in DB1 (Rohdaten) schreiben
            if lead_id:
                lead["id"] = lead_id
                logger.success("AI-Worker", f"Extrahiert: {name} ({region})")
                on_lead(lead)
                found += 1

            time.sleep(0.5)
