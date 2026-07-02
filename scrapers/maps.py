"""
Google Maps Scraper — persistenter Browser, durchläuft alle Kombis in einer Session.
Ein Browser für alle Suchen = schneller, weniger Detection-Risiko.
"""
import os
import re
import json
import time
import itertools

from agents.scorer import score as calc_score
from agents.quality import is_real_business
from scrapers.website_checker import check_website
from scrapers.regions import get_bundesland
import db_raw as _db_raw
import logger


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


def _extract_entry(page, entry, region: str, branche: str, stop_event) -> dict | None:
    try:
        entry.click()
        page.wait_for_timeout(1800)

        name = _text(page, "h1", "h2[class*='fontHeadlineLarge']")
        if not name or len(name) < 2:
            return None
        # Generische Maps-Überschriften ("Ergebnisse" etc.) sind keine Betriebe
        if name.strip().lower() in {"ergebnisse", "suchergebnisse", "results",
                                    "mehr ergebnisse", "weitere ergebnisse"}:
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

        # Bilder / Hero-Foto-URL erfassen (gespeicherte Maps-Bilder)
        foto_url = ""
        for img_sel in [
            "button[jsaction*='heroHeaderImage'] img",
            "div[role='img'] img[src*='googleusercontent']",
            "img[decoding='async'][src*='googleusercontent']",
        ]:
            el = page.query_selector(img_sel)
            if el:
                src = el.get_attribute("src") or ""
                if src and "googleusercontent" in src:
                    foto_url = src
                    break
        # Fallback: Hintergrundbild im Hero-Button
        if not foto_url:
            hero = page.query_selector("button[jsaction*='heroHeaderImage'], div[role='img']")
            if hero:
                style = hero.get_attribute("style") or ""
                m = re.search(r'url\(["\']?(https?://[^"\')]+)', style)
                if m and "googleusercontent" in m.group(1):
                    foto_url = m.group(1)
        bilder = bool(foto_url) or bool(page.query_selector(
            "button[aria-label*='Foto'], button[aria-label*='Bild'], "
            "div[aria-label*='Fotos']"
        ))

        # Mehrere Maps-Bilder sammeln + auf HOHE Auflösung hochrechnen (Google liefert nur
        # Thumbnails mit Größen-Suffix '=w###-h###-…'; den ersetzen wir durch eine große
        # Variante). Dedup über die Basis-URL, damit nicht dasselbe Bild mehrfach (in
        # verschiedenen Größen) landet → brauchbare, scharfe Fotos für die Kundenseite.
        def _hires(u: str) -> str:
            return re.sub(r"=[swh]\d.*$", "=w1280-h960-k-no", u) if re.search(r"=[swh]\d", u) else u

        def _base(u: str) -> str:
            return re.sub(r"=[swh]\d.*$", "", u)

        foto_urls: list[str] = []
        seen_bases: set = set()
        kandidaten = [foto_url] if foto_url else []
        try:
            kandidaten += [(img.get_attribute("src") or "").strip()
                           for img in page.query_selector_all("img[src*='googleusercontent']")]
        except Exception:
            pass
        for src in kandidaten:
            if not src or "googleusercontent" not in src:
                continue
            b = _base(src)
            if b in seen_bases:
                continue
            seen_bases.add(b)
            foto_urls.append(_hires(src))
            if len(foto_urls) >= 8:
                break
        if foto_urls:
            foto_url = foto_urls[0]            # Hero-Kandidat ebenfalls in hoher Auflösung

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
            "bundesland":     get_bundesland(region),
            "branche":        branche,
            "telefon":        telefon,
            "website_url":    website_url if has_web else "",
            "has_website":    int(has_web),
            "website_alter":  web_info.get("alter_jahre", -1),
            "bewertung":      rating,
            "anz_bewertungen": anz_rev,
            "bilder":         int(bilder),
            "foto_url":       foto_url,
            "foto_urls":      json.dumps(foto_urls, ensure_ascii=False),
            "finder":         "maps_playwright",
            "maps_url":       page.url,
        }
    except Exception:
        return None
