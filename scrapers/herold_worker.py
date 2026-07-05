"""
herold.at-Worker — dünner Adapter für die Haupt-Pipeline um das bereits validierte
leadpackages/sources_herold.py (dort für das separate LeadForge-Produkt gebaut).

Bewusster Architektur-Kompromiss: dieses Modul verbindet scrapers/ (Haupt-Pipeline)
mit leadpackages/ (Lead-Pakete-Produkt) — die beiden waren vorher unabhängig. Für ein
Solo-Repo vertretbar, eine Verschiebung von sources_herold.py nur der Sauberkeit wegen
lohnt sich nicht (sources_herold.py bleibt an Ort und Stelle, LeadForge nutzt es weiter
unverändert).

Nur für Österreich-Kombis gedacht (siehe controller.py: AT_COMBOS gehen an Maps, AI-Worker
UND diesen Worker — die 4 DE-Verzeichnis-Scraper bekommen weiterhin nur DE-Kombis).
"""
import itertools
import time

from agents.scorer import score as calc_score
from agents.quality import is_real_business
from scrapers.website_checker import check_website
from leadpackages.sources_dach import get_region
from leadpackages import sources_herold
import db_raw as _db_raw
import logger


def run_continuous(all_combos: list[tuple], on_lead, stop_event, max_per: int = 20):
    """Läuft als langlebiger Thread durch alle (AT-Stadt, Branche)-Kombis."""
    counter = 0
    for region, branche in itertools.cycle(all_combos):
        if stop_event.is_set():
            break
        counter += 1
        if counter % 10 == 0:
            on_lead({"_activity": f"herold.at scannt {region}/{branche}"})
        try:
            _scrape_query(region, branche, on_lead, stop_event, max_per)
        except Exception as e:
            on_lead({"_error": f"herold.at ({region}/{branche}): {e}"})
        time.sleep(1.0)


def _scrape_query(stadt: str, branche: str, on_lead, stop_event, max_per: int):
    logger.scrape("Herold", f"Scanne: {branche} | {stadt}")
    try:
        treffer = sources_herold.search(branche, stadt, max_results=max_per)
    except Exception as e:
        logger.warn("Herold", f"Fehler bei {branche}/{stadt}: {type(e).__name__}: {str(e)[:120]}")
        return

    found = 0
    for eintrag in treffer:
        if stop_event.is_set() or found >= max_per:
            break

        name = (eintrag.get("name") or "").strip()
        if not name or len(name) < 2:
            continue

        website_url = (eintrag.get("website_url") or "").strip()
        has_web     = bool(website_url)
        web_info    = check_website(website_url) if has_web else {}

        lead = {
            "name":            name[:120],
            "adresse":         (eintrag.get("adresse") or "")[:200],
            "stadt":           stadt,
            "bundesland":      eintrag.get("region") or get_region("AT", stadt) or stadt,
            "branche":         branche,
            "telefon":         (eintrag.get("telefon") or "")[:50],
            "website_url":     website_url[:300] if has_web else "",
            "has_website":     int(has_web),
            "website_alter":   web_info.get("alter_jahre", -1),
            "bewertung":       0.0,
            "anz_bewertungen": 0,
            "bilder":          0,
            "finder":          "herold_at",
            "maps_url":        "",
        }

        ok, _grund = is_real_business(lead)
        if not ok:
            continue

        pts, typ         = calc_score(lead)
        lead["score"]     = pts
        lead["lead_typ"]  = typ

        lead_id = _db_raw.insert_raw(lead)   # Roh-Lead speichern + Feed-ID
        if lead_id:
            lead["id"] = lead_id
            logger.success("Herold", f"Gefunden: {name} ({stadt})")
            try:
                logger.activity("HeroldAT", "Lead gefunden",
                                f"{name} · {branche} · {stadt}",
                                "📡", "scrape")
            except Exception:
                pass
            on_lead(lead)
            found += 1
