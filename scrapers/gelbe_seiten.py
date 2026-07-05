"""
Gelbe Seiten Scraper — robuste Selektor-Hierarchie, mehrere Fallbacks.
"""
import re
import time
import urllib.request
import urllib.parse
import itertools

from agents.scorer import score as calc_score
from agents.quality import is_real_business
from scrapers.regions import get_bundesland
from scrapers import _http
import db_raw as _db_raw
import logger

# Header/Get/Rating-Parser sind gemeinsam mit dasoertliche/elfacht/golocal.py — siehe
# scrapers/_http.py (waren vorher 4x byte-identisch dupliziert).
_HEADERS      = _http.DIRECTORY_HEADERS
_get          = _http.get_directory


def run_continuous(all_combos: list[tuple], on_lead, stop_event, max_per: int = 25):
    """Läuft als einzelner langlebiger Thread durch alle Kombis."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        on_lead({"_error": "beautifulsoup4 fehlt — pip install beautifulsoup4"})
        return

    counter = 0
    for region, branche in itertools.cycle(all_combos):
        if stop_event.is_set():
            break
        counter += 1
        if counter % 10 == 0:
            on_lead({"_activity": f"Gelbe Seiten scannt {region}/{branche}"})
        try:
            _scrape_query(region, branche, on_lead, stop_event, max_per, BeautifulSoup)
        except Exception as e:
            on_lead({"_error": f"GelbeSeit ({region}/{branche}): {e}"})
        time.sleep(1.0)


def _scrape_query(region, branche, on_lead, stop_event, max_per, BS4):
    logger.scrape("GelbeSeit", f"Scanne: {branche} | {region}")
    city_enc   = urllib.parse.quote_plus(region)
    branch_enc = urllib.parse.quote_plus(branche)
    base       = f"https://www.gelbeseiten.de/suche/{branch_enc}/{city_enc}"
    found      = 0
    page_nr    = 1

    while found < max_per and not stop_event.is_set():
        url  = base if page_nr == 1 else f"{base}?page={page_nr}"
        html = _get(url)
        if not html:
            break

        soup    = BS4(html, "html.parser")
        entries = (
            soup.select("article.mod-Treffer") or
            soup.select("li.entry") or
            soup.select("div.result") or
            soup.select("[class*='Treffer']") or
            soup.select("[class*='result']")
        )
        if not entries:
            if page_nr == 1:
                logger.warn("GelbeSeit", f"Keine Ergebnisse: {region}/{branche}")
            break

        new_found = False
        for art in entries:
            if stop_event.is_set() or found >= max_per:
                break

            name = (
                _txt(art, "h2.mod-Treffer__name span", "h2.mod-Treffer__name",
                     "h2[class*='name']", "h3[class*='name']", ".entry-name", "h2")
            )
            if not name or len(name) < 2:
                continue

            adresse = _txt(
                art,
                "address.mod-Treffer__adresse", "address",
                "[class*='adresse']", "[class*='address']",
            )
            # Adresse aus einzelnen Spans zusammensetzen
            if not adresse:
                parts = [s.get_text(" ", strip=True) for s in art.find_all("span") if s.get_text(strip=True)]
                adresse = " ".join(parts[:3])

            telefon = ""
            tel_el  = art.find("a", href=re.compile(r"^tel:"))
            if tel_el:
                telefon = tel_el.get_text(strip=True) or tel_el.get("href", "").replace("tel:", "")

            website_url = ""
            for cls_kw in ["website", "web", "url", "authority"]:
                el = art.find("a", href=re.compile(r"^https?://"),
                              attrs={"class": re.compile(cls_kw, re.I)})
                if el:
                    website_url = el.get("href", "")
                    break
            if not website_url:
                for a in art.find_all("a", href=re.compile(r"^https?://")):
                    href = a.get("href", "")
                    if "gelbeseiten" not in href and "google" not in href:
                        website_url = href
                        break

            has_web  = bool(website_url)
            bilder   = bool(art.find("img", class_=re.compile(r"(bild|logo|foto|img)", re.I)))
            bewertung, anz_bew = _parse_rating(art)

            lead = {
                "name":           name[:120],
                "adresse":        adresse[:200],
                "stadt":          region,
                "bundesland":     get_bundesland(region),
                "branche":        branche,
                "telefon":        telefon[:50],
                "website_url":    website_url[:300] if has_web else "",
                "has_website":    int(has_web),
                "website_alter":  -1,  # Alter wird zentral im Evaluator ermittelt (web_analyst.py)
                "bewertung":      bewertung,
                "anz_bewertungen": anz_bew,
                "bilder":         int(bilder),
                "finder":         "gelbe_seiten",
                "maps_url":       "",
            }

            ok, _grund = is_real_business(lead)
            if not ok:
                continue

            pts, typ         = calc_score(lead)
            lead["score"]    = pts
            lead["lead_typ"] = typ

            lead_id = _db_raw.insert_raw(lead)   # Roh-Lead speichern + Feed-ID
            if lead_id:
                lead["id"] = lead_id
                logger.success("GelbeSeit", f"Gefunden: {name} ({region})")
                try:
                    logger.activity("GelbeSeiten", "Lead gefunden",
                                    f"{name} · {lead.get('branche','')} · {region}",
                                    "📡", "scrape")
                except Exception:
                    pass
                on_lead(lead)
                found += 1
                new_found = True

        if not new_found:
            break
        page_nr += 1
        time.sleep(1.2)


# Rating-Parser ist gemeinsam mit dasoertliche/elfacht/golocal.py — siehe scrapers/_http.py.
_parse_rating = _http.parse_rating


def _txt(tag, *selectors: str) -> str:
    for sel in selectors:
        try:
            el = tag.select_one(sel)
            if el:
                t = el.get_text(" ", strip=True)
                if t:
                    return t
        except Exception:
            pass
    return ""
