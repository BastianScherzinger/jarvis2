"""
11880.com Scraper — großes deutsches Branchenverzeichnis.
Klon des dasoertliche-Patterns mit robusten Fallback-Selektor-Ketten.
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
from scrapers import _http
import db
import db_raw as _db_raw
import logger

_HEADERS = {
    "User-Agent": _http.UA,
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


def _slug(text: str) -> str:
    """Kleinschreibung, Leerzeichen → '-', URL-encoded."""
    s = text.strip().lower().replace(" ", "-")
    return urllib.parse.quote(s, safe="-")


def run_continuous(all_combos: list[tuple], on_lead, stop_event, max_per: int = 20):
    """Läuft als langlebiger Thread durch alle Kombis."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        on_lead({"_error": "beautifulsoup4 fehlt"})
        return

    # 11880 leicht versetzt starten
    time.sleep(7)

    counter = 0
    for region, branche in itertools.cycle(all_combos):
        if stop_event.is_set():
            break
        counter += 1
        if counter % 10 == 0:
            on_lead({"_activity": f"11880 scannt {region}/{branche}"})
        try:
            _scrape_query(region, branche, on_lead, stop_event, max_per, BeautifulSoup)
        except Exception as e:
            on_lead({"_error": f"11880 ({region}/{branche}): {e}"})
        time.sleep(1.5)


def _scrape_query(region, branche, on_lead, stop_event, max_per, BS4):
    logger.scrape("11880", f"Scanne: {branche} | {region}")
    city = region.replace("Berlin ", "")
    url  = f"https://www.11880.com/suche/{_slug(branche)}/{_slug(city)}"

    html = _get(url)
    if not html:
        return

    soup    = BS4(html, "html.parser")
    entries = (
        soup.select("article") or
        soup.select("div[class*='result-list-entry']") or
        soup.select("li[class*='entry']") or
        soup.select("[class*='result']")
    )
    if not entries:
        logger.warn("11880", f"Keine Ergebnisse: {region}/{branche}")

    found = 0
    for art in entries:
        if stop_event.is_set() or found >= max_per:
            break

        # Name
        name_el = (
            art.select_one("h2") or
            art.select_one("[class*='name']") or
            art.select_one("a[class*='title']") or
            art.select_one("h3")
        )
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        if not name or len(name) < 2:
            continue

        # Adresse
        adr_el  = (
            art.select_one("[class*='address']") or
            art.select_one("address") or
            art.select_one("[class*='adresse']")
        )
        adresse = adr_el.get_text(" ", strip=True) if adr_el else ""

        # Telefon
        telefon = ""
        tel_el  = art.select_one("a[href^='tel:']") or art.select_one("[class*='phone']")
        if tel_el:
            telefon = tel_el.get_text(strip=True) or tel_el.get("href", "").replace("tel:", "")

        # Website
        website_url = ""
        web_el = art.select_one("a[class*='website']")
        if web_el and web_el.get("href", "").startswith("http"):
            website_url = web_el["href"]
        if not website_url:
            for a in art.find_all("a", href=True):
                href = a["href"]
                if href.startswith("http") and "11880" not in href and "google" not in href:
                    website_url = href
                    break

        has_web  = bool(website_url)
        web_info = check_website(website_url) if has_web else {}
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
            "website_alter":  web_info.get("alter_jahre", -1),
            "bewertung":      bewertung,
            "anz_bewertungen": anz_bew,
            "bilder":         0,
            "finder":         "elfacht",
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
            logger.success("11880", f"Gefunden: {name} ({region})")
            on_lead(lead)
            found += 1

    time.sleep(1.0)


def _parse_rating(art) -> tuple[float, int]:
    """Extrahiert (Sterne 0-5, Anzahl Bewertungen) aus einem Listen-Eintrag.
    Robust — gibt (0.0, 0) zurück wenn nichts gefunden, crasht nie."""
    bewertung, anz = 0.0, 0
    try:
        rate_el = (
            art.select_one("[itemprop='ratingValue']") or
            art.select_one("[class*='rating']") or
            art.select_one("[class*='stars']") or
            art.select_one("[class*='bewertung']")
        )
        txt = ""
        if rate_el:
            txt = rate_el.get("content") or rate_el.get("aria-label") or rate_el.get_text(" ", strip=True)
        if txt:
            m = re.search(r"(\d[.,]?\d?)", txt)
            if m:
                val = float(m.group(1).replace(",", "."))
                if 0.0 <= val <= 5.0:
                    bewertung = val
    except Exception:
        bewertung = 0.0
    try:
        cnt_el = (
            art.select_one("[itemprop='reviewCount']") or
            art.select_one("[class*='count']")
        )
        cnt_txt = ""
        if cnt_el:
            cnt_txt = cnt_el.get("content") or cnt_el.get_text(" ", strip=True)
        if not cnt_txt:
            full = art.get_text(" ", strip=True)
            mb = re.search(r"\((\d+)\s*Bewertung", full, re.I) or \
                 re.search(r"(\d+)\s*Bewertung", full, re.I)
            if mb:
                cnt_txt = mb.group(1)
        if cnt_txt:
            mc = re.search(r"\d+", cnt_txt)
            if mc:
                anz = int(mc.group(0))
    except Exception:
        anz = 0
    return bewertung, anz
