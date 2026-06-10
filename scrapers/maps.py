"""
Google Maps Scraper — findet Unternehmen via Playwright.
Kein API-Key. Läuft sichtbar oder headless je nach .env.
"""
import os
import re
import time

from agents.scorer import score as calc_score
from scrapers.website_checker import check_website
import db


def _headless() -> bool:
    return os.environ.get("JARVIS_BROWSER_HEADLESS", "false").lower() == "true"


def _text(page, selector: str) -> str:
    try:
        el = page.query_selector(selector)
        return (el.inner_text() or "").strip() if el else ""
    except Exception:
        return ""


def run_loop(region: str, branche: str, on_lead, stop_event, max_per=40):
    """
    Scannt Maps für region + branche.
    on_lead(lead_dict) wird bei jedem neuen Fund aufgerufen.
    stop_event: threading.Event — wird gecheckt für sauberes Stoppen.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
    except ImportError:
        on_lead({"_error": "Playwright nicht installiert — `playwright install chromium`"})
        return

    query = f"{branche} {region}"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=_headless())
        ctx  = browser.new_context(locale="de-DE", viewport={"width": 1280, "height": 900})
        page = ctx.new_page()

        try:
            page.goto(
                f"https://www.google.de/maps/search/{query.replace(' ', '+')}",
                timeout=25000,
            )
            page.wait_for_timeout(3000)

            # Cookie-Banner
            for sel in ["button[aria-label*='Alle ablehnen']",
                        "button[aria-label*='Accept all']",
                        "form:last-of-type button"]:
                try:
                    page.click(sel, timeout=2000)
                    break
                except Exception:
                    pass

            visited = set()
            found   = 0

            while found < max_per and not stop_event.is_set():
                entries = page.query_selector_all("a[href*='/maps/place/']")
                if not entries:
                    break

                new_this_round = False
                for entry in entries:
                    if stop_event.is_set() or found >= max_per:
                        break

                    href = entry.get_attribute("href") or ""
                    if href in visited:
                        continue
                    visited.add(href)
                    new_this_round = True

                    try:
                        entry.click()
                        page.wait_for_timeout(2000)

                        name = _text(page, "h1")
                        if not name:
                            continue

                        # Website-Check
                        website_el  = page.query_selector("a[data-item-id='authority']")
                        website_url = ""
                        if website_el:
                            website_url = website_el.get_attribute("href") or ""

                        has_web  = bool(website_url)
                        web_info = check_website(website_url) if has_web else {}

                        # Bilder
                        bilder = bool(page.query_selector("button[aria-label*='Foto']"))

                        # Adresse
                        adresse = _text(page, "button[data-item-id='address']")
                        telefon = ""
                        for sel in ["button[data-item-id*='phone']",
                                    "button[aria-label*='Telefon']"]:
                            telefon = _text(page, sel)
                            if telefon:
                                break

                        # Rating
                        rating_text = _text(page, "div.fontDisplayLarge")
                        rating = 0.0
                        try:
                            rating = float(rating_text.replace(",", "."))
                        except Exception:
                            pass

                        # Anzahl Bewertungen
                        rev_el  = (page.query_selector("button[aria-label*='Rezension']")
                                   or page.query_selector("button[aria-label*='Bewertung']"))
                        rev_txt = rev_el.inner_text() if rev_el else ""
                        anz_rev = 0
                        m       = re.search(r"(\d[\d.,]*)", rev_txt)
                        if m:
                            try:
                                anz_rev = int(m.group(1).replace(".", "").replace(",", ""))
                            except Exception:
                                pass

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
                            "bewertung":      rating,
                            "anz_bewertungen": anz_rev,
                            "bilder":         int(bilder),
                            "finder":         "maps_playwright",
                            "maps_url":       page.url,
                        }

                        pts, typ     = calc_score(lead)
                        lead["score"]    = pts
                        lead["lead_typ"] = typ

                        lead_id = db.insert(lead)
                        if lead_id:
                            lead["id"] = lead_id
                            on_lead(lead)
                            found += 1

                    except Exception:
                        continue

                if not new_this_round:
                    # Mehr Ergebnisse laden
                    feed = page.query_selector("div[role='feed']")
                    if feed:
                        feed.evaluate("el => el.scrollBy(0, 1000)")
                        page.wait_for_timeout(1500)
                    else:
                        break

        except Exception as e:
            on_lead({"_error": f"Maps-Fehler ({region}/{branche}): {e}"})
        finally:
            try:
                browser.close()
            except Exception:
                pass
