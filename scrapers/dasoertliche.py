"""
Das Örtliche Scraper — einfaches deutsches Branchenbuch, sehr stabil.
Gute Ergänzung zu Maps + Gelbe Seiten.
"""
import re
import time
import urllib.request
import urllib.parse
import itertools

from agents.scorer import score as calc_score
from agents.quality import is_real_business
from scrapers.website_checker import check_website
from scrapers.regions import get_bundesland
import db
import db_raw as _db_raw
import logger

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
}


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=14) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def run_continuous(all_combos: list[tuple], on_lead, stop_event, max_per: int = 20):
    """Läuft als langlebiger Thread durch alle Kombis."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        on_lead({"_error": "beautifulsoup4 fehlt"})
        return

    # Das Örtliche ist langsamer → leicht versetzt starten
    time.sleep(5)

    counter = 0
    for region, branche in itertools.cycle(all_combos):
        if stop_event.is_set():
            break
        counter += 1
        if counter % 10 == 0:
            on_lead({"_activity": f"Das Örtliche scannt {region}/{branche}"})
        try:
            _scrape_query(region, branche, on_lead, stop_event, max_per, BeautifulSoup)
        except Exception as e:
            on_lead({"_error": f"DasÖrtliche ({region}/{branche}): {e}"})
        time.sleep(1.5)


def _scrape_query(region, branche, on_lead, stop_event, max_per, BS4):
    logger.scrape("DasOertl", f"Scanne: {branche} | {region}")
    kw   = urllib.parse.quote_plus(branche)
    city = urllib.parse.quote_plus(region.replace("Berlin ", ""))
    url  = f"https://www.dasoertliche.de/suche/?kw={kw}&ci={city}"

    html = _get(url)
    if not html:
        return

    soup    = BS4(html, "html.parser")
    entries = (
        soup.select("article.hit") or
        soup.select("li.entry") or
        soup.select("[class*='result']") or
        soup.select("div.hit")
    )
    if not entries:
        logger.warn("DasOertl", f"Keine Ergebnisse: {region}/{branche}")

    found = 0
    for art in entries:
        if stop_event.is_set() or found >= max_per:
            break

        # Name
        name_el = (
            art.select_one("span.hit-name") or
            art.select_one("a.hit-link") or
            art.select_one("[class*='name']") or
            art.select_one("h2") or
            art.select_one("h3")
        )
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        if not name or len(name) < 2:
            continue

        # Adresse
        adr_el  = (
            art.select_one("address") or
            art.select_one("[class*='address']") or
            art.select_one("[class*='adresse']")
        )
        adresse = adr_el.get_text(" ", strip=True) if adr_el else ""

        # Telefon
        telefon = ""
        tel_el  = art.find("a", href=re.compile(r"^tel:"))
        if tel_el:
            telefon = tel_el.get_text(strip=True) or tel_el.get("href", "").replace("tel:", "")

        # Website
        website_url = ""
        for a in art.find_all("a", href=True):
            href = a["href"]
            if href.startswith("http") and "dasoertliche" not in href and "google" not in href:
                website_url = href
                break

        has_web  = bool(website_url)
        web_info = check_website(website_url) if has_web else {}

        lead = {
            "name":           name[:120],
            "adresse":        adresse[:200],
            "stadt":          region,
            "bundesland":     get_bundesland(region),
            "branche":        branche,
            "telefon":        telefon[:50],
            "website_url":    website_url[:300] if has_web else "",
            "has_website":    int(has_web),
            "website_alter":  web_info.get("alter_jahre", -1),
            "bewertung":      0.0,
            "anz_bewertungen": 0,
            "bilder":         0,
            "finder":         "dasoertliche",
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
            logger.success("DasOertl", f"Gefunden: {name} ({region})")
            on_lead(lead)
            found += 1

    time.sleep(1.0)
