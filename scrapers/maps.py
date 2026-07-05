"""
Google Maps Scraper — persistenter Browser, durchläuft alle Kombis in einer Session.
Ein Browser für alle Suchen = schneller, weniger Detection-Risiko.
"""
import os
import time
import itertools

from agents.scorer import score as calc_score
from agents.quality import is_real_business
from scrapers import maps_common
import db_raw as _db_raw
import logger


def _headless() -> bool:
    return os.environ.get("JARVIS_BROWSER_HEADLESS", "false").lower() == "true"


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
        logger.scrape("Maps", "Browser gestartet")
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

        counter = 0
        for region, branche in itertools.cycle(all_combos):
            if stop_event.is_set():
                break
            counter += 1
            if counter % 10 == 0:
                on_lead({"_activity": f"Google Maps scannt {region}/{branche}"})
            try:
                _scrape_query(page, region, branche, on_lead, stop_event, max_per)
            except Exception as e:
                logger.error("Maps", f"{region}/{branche}: {e}")
                on_lead({"_error": f"Maps ({region}/{branche}): {e}"})
                # Leichte Erholung; scheitert sie (Browser/Context komplett tot), den Browser
                # VOLLSTÄNDIG neu aufbauen — sonst stirbt der Maps-Worker still für den Rest der Nacht.
                try:
                    page.goto("https://www.google.de/maps", timeout=10000)
                    page.wait_for_timeout(2000)
                except Exception:
                    try:
                        # Alten Context zuerst schließen (sonst kann ein Chromium-Context
                        # verwaisen), dann den Browser komplett neu aufbauen.
                        try:
                            ctx.close()
                        except Exception:
                            pass
                        try:
                            browser.close()
                        except Exception:
                            pass
                        browser = pw.chromium.launch(
                            headless=_headless(),
                            args=["--disable-blink-features=AutomationControlled",
                                  "--no-sandbox", "--disable-dev-shm-usage"])
                        ctx = browser.new_context(
                            locale="de-DE", viewport={"width": 1366, "height": 900},
                            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"))
                        page = ctx.new_page()
                        page.add_init_script(
                            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
                        page.goto("https://www.google.de/maps", timeout=15000)
                        page.wait_for_timeout(1500)
                        logger.scrape("Maps", "Browser nach schwerem Fehler neu aufgebaut.")
                    except Exception as e2:
                        logger.error("Maps", f"Browser-Neuaufbau fehlgeschlagen: {e2}")
                        stop_event.wait(30)          # kurz warten, dann nächste Combo erneut versuchen

        try:
            browser.close()
        except Exception:
            pass


def _scrape_query(page, region: str, branche: str, on_lead, stop_event, max_per: int):
    logger.scrape("Maps", f"Scanne: {branche} | {region}")
    query = f"{branche} {region}"
    url   = f"https://www.google.de/maps/search/{query.replace(' ', '+')}"

    page.goto(url, timeout=20000, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    visited = set()
    found   = 0
    scroll_attempts = 0

    while found < max_per and not stop_event.is_set():
        # Alle Listeneinträge sammeln
        entries = maps_common.find_entries(page)
        new_this_round = False

        for entry in entries:
            if stop_event.is_set() or found >= max_per:
                break
            href = entry.get_attribute("href") or ""
            if not href or href in visited:
                continue
            visited.add(href)
            new_this_round = True

            lead = maps_common.extract_entry(page, entry, region, branche, stop_event)
            if lead:
                ok, _grund = is_real_business(lead)
                if not ok:
                    continue
                pts, typ         = calc_score(lead)
                lead["score"]    = pts
                lead["lead_typ"] = typ
                lead_id          = _db_raw.insert_raw(lead)   # Roh-Lead speichern + Feed-ID
                if lead_id:
                    lead["id"] = lead_id
                    logger.success("Maps", f"Gefunden: {lead['name']} ({lead['stadt']})")
                    try:
                        logger.activity("GoogleMaps", "Lead gefunden",
                                        f"{lead['name']} · {lead.get('branche','')} · {lead['stadt']}",
                                        "📡", "scrape")
                    except Exception:
                        pass
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


# _extract_entry() lebt jetzt in scrapers/maps_common.py (geteilt mit dem
# Maps-Enrichment für Leads aus anderen Quellen, siehe agents/evaluator/maps_enrichment.py).
