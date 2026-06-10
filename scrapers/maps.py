"""
Google Maps Scraper — persistenter Browser, durchläuft alle Kombis in einer Session.
Ein Browser für alle Suchen = schneller, weniger Detection-Risiko.
"""
import os
import re
import time
import itertools

from agents.scorer import score as calc_score
from scrapers.website_checker import check_website
import db


def _headless() -> bool:
    return os.environ.get("JARVIS_BROWSER_HEADLESS", "false").lower() == "true"


def _text(page, *selectors: str) -> str:
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el:
                t = (el.inner_text() or "").strip()
                if t:
                    return t
        except Exception:
            pass
    return ""


def run_continuous(all_combos: list[tuple], on_lead, stop_event, max_per: int = 25):
    """
    Hält EINEN Browser offen und scannt alle Combis nacheinander.
    Wird vom Controller als einzelner langlebiger Thread gestartet.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as _PwT
    except ImportError:
        on_lead({"_error": "Playwright fehlt — `playwright install chromium`"})
        return

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=_headless(),
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx  = browser.new_context(
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

        # Cookie-Banner einmalig akzeptieren
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

        for region, branche in itertools.cycle(all_combos):
            if stop_event.is_set():
                break
            try:
                _scrape_query(page, region, branche, on_lead, stop_event, max_per)
            except Exception as e:
                on_lead({"_error": f"Maps ({region}/{branche}): {e}"})
                # Browser-Neustart bei schwerem Fehler
                try:
                    page.goto("https://www.google.de/maps", timeout=10000)
                    page.wait_for_timeout(2000)
                except Exception:
                    pass

        try:
            browser.close()
        except Exception:
            pass


def _scrape_query(page, region: str, branche: str, on_lead, stop_event, max_per: int):
    query = f"{branche} {region}"
    url   = f"https://www.google.de/maps/search/{query.replace(' ', '+')}"

    page.goto(url, timeout=20000, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    visited = set()
    found   = 0
    scroll_attempts = 0

    while found < max_per and not stop_event.is_set():
        # Alle Listeneinträge sammeln
        entries = page.query_selector_all(
            "a[href*='/maps/place/'], div[jsaction*='mouseover'] a[href*='/maps/place/']"
        )
        new_this_round = False

        for entry in entries:
            if stop_event.is_set() or found >= max_per:
                break
            href = entry.get_attribute("href") or ""
            if not href or href in visited:
                continue
            visited.add(href)
            new_this_round = True

            lead = _extract_entry(page, entry, region, branche, stop_event)
            if lead:
                pts, typ         = calc_score(lead)
                lead["score"]    = pts
                lead["lead_typ"] = typ
                lead_id          = db.insert(lead)
                if lead_id:
                    lead["id"] = lead_id
                    on_lead(lead)
                    found += 1

        if not new_this_round or found >= max_per:
            scroll_attempts += 1
            if scroll_attempts > 5:
                break
            # Feed scrollen
            feed = page.query_selector("div[role='feed']")
            if feed:
                feed.evaluate("el => el.scrollBy(0, 1200)")
                page.wait_for_timeout(1800)
            else:
                break
        else:
            scroll_attempts = 0


def _extract_entry(page, entry, region: str, branche: str, stop_event) -> dict | None:
    try:
        entry.click()
        page.wait_for_timeout(1800)

        name = _text(page, "h1", "h2[class*='fontHeadlineLarge']")
        if not name or len(name) < 2:
            return None

        # Website-Check (mehrere Selektor-Varianten)
        website_url = ""
        for ws in [
            "a[data-item-id='authority']",
            "a[aria-label*='Website']",
            "a[href^='http'][data-tooltip*='ebsite']",
        ]:
            el = page.query_selector(ws)
            if el:
                website_url = el.get_attribute("href") or ""
                break

        has_web  = bool(website_url and "google" not in website_url)
        web_info = check_website(website_url) if has_web else {}

        bilder = bool(page.query_selector(
            "button[aria-label*='Foto'], button[aria-label*='Bild'], "
            "div[aria-label*='Fotos']"
        ))

        adresse = _text(
            page,
            "button[data-item-id='address']",
            "button[aria-label*='Adresse']",
            "[data-item-id='address'] span",
        )
        telefon = _text(
            page,
            "button[data-item-id*='phone']",
            "button[aria-label*='Telefon']",
            "a[href^='tel:']",
        )
        # Telefon aus href extrahieren falls nötig
        if not telefon:
            tel_el = page.query_selector("a[href^='tel:']")
            if tel_el:
                telefon = (tel_el.get_attribute("href") or "").replace("tel:", "")

        # Rating
        rating = 0.0
        for rs in ["div.fontDisplayLarge", "span[aria-label*='Stern']", "div[aria-label*='Stern']"]:
            rt = _text(page, rs)
            try:
                rating = float(rt.replace(",", "."))
                break
            except Exception:
                pass

        # Anzahl Bewertungen
        anz_rev = 0
        for rs in [
            "button[aria-label*='Rezension']",
            "button[aria-label*='Bewertung']",
            "span[aria-label*='Bewertungen']",
        ]:
            rev_el = page.query_selector(rs)
            if rev_el:
                m = re.search(r"(\d[\d.,]*)", rev_el.inner_text() or "")
                if m:
                    try:
                        anz_rev = int(m.group(1).replace(".", "").replace(",", ""))
                        break
                    except Exception:
                        pass

        return {
            "name":           name,
            "adresse":        adresse,
            "stadt":          region,
            "bundesland":     "Berlin" if "Berlin" in region else "Schleswig-Holstein",
            "branche":        branche,
            "telefon":        telefon,
            "website_url":    website_url if has_web else "",
            "has_website":    int(has_web),
            "website_alter":  web_info.get("alter_jahre", -1),
            "bewertung":      rating,
            "anz_bewertungen": anz_rev,
            "bilder":         int(bilder),
            "finder":         "maps_playwright",
            "maps_url":       page.url,
        }
    except Exception:
        return None
