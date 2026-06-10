"""
Gelbe Seiten Scraper — Python requests + BeautifulSoup.
Kein Playwright nötig — schneller als Maps, andere Datenbasis.
"""
import re
import time
import urllib.request
import urllib.parse

from agents.scorer import score as calc_score
from scrapers.website_checker import check_website
import db

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _find_all(pattern: str, html: str) -> list[str]:
    return re.findall(pattern, html, re.DOTALL | re.IGNORECASE)


def run_loop(region: str, branche: str, on_lead, stop_event, max_per=30):
    """Scannt Gelbe Seiten für region + branche."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        on_lead({"_error": "beautifulsoup4 fehlt — `pip install beautifulsoup4`"})
        return

    city_enc    = urllib.parse.quote_plus(region)
    branch_enc  = urllib.parse.quote_plus(branche)
    base        = f"https://www.gelbeseiten.de/suche/{branch_enc}/{city_enc}"
    found       = 0
    page_nr     = 1

    while found < max_per and not stop_event.is_set():
        url  = base if page_nr == 1 else f"{base}?page={page_nr}"
        html = _get(url)
        if not html:
            break

        soup    = BeautifulSoup(html, "html.parser")
        entries = soup.select("article.mod-Treffer")
        if not entries:
            break

        for art in entries:
            if stop_event.is_set() or found >= max_per:
                break

            name_el = art.select_one("h2.mod-Treffer__name")
            if not name_el:
                continue
            name = name_el.get_text(strip=True)

            adresse = ""
            adr_el  = art.select_one("address")
            if adr_el:
                adresse = " ".join(adr_el.get_text(separator=" ", strip=True).split())

            telefon = ""
            tel_el  = art.select_one("[href^='tel:']")
            if tel_el:
                telefon = tel_el.get_text(strip=True)

            website_url = ""
            web_el      = art.select_one("a[href*='http'][class*='web'], a[title*='ebsite']")
            if web_el:
                website_url = web_el.get("href", "")

            has_web  = bool(website_url)
            web_info = check_website(website_url) if has_web else {}

            # Bilder
            bilder = bool(art.select_one("img.mod-Treffer__bild"))

            lead = {
                "name":           name,
                "adresse":        adresse,
                "stadt":          region,
                "bundesland":     "Berlin" if "Berlin" in region else "Schleswig-Holstein",
                "branche":        branche,
                "telefon":        telefon,
                "website_url":    website_url,
                "has_website":    int(has_web),
                "website_alter":  web_info.get("alter_jahre", -1),
                "bewertung":      0.0,
                "anz_bewertungen": 0,
                "bilder":         int(bilder),
                "finder":         "gelbe_seiten",
                "maps_url":       "",
            }

            pts, typ     = calc_score(lead)
            lead["score"]    = pts
            lead["lead_typ"] = typ

            lead_id = db.insert(lead)
            if lead_id:
                lead["id"] = lead_id
                on_lead(lead)
                found += 1

        page_nr += 1
        time.sleep(1.5)   # höfliche Pause
