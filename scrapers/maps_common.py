"""
Gemeinsame Google-Maps-Extraktionslogik — genutzt vom Haupt-Scraper (scrapers/maps.py,
Discovery über viele Städte/Branchen, klickt sich durch eine Ergebnisliste) UND vom
Maps-Enrichment (agents/evaluator/maps_enrichment.py, gezielter Einzel-Lookup für einen
bereits bekannten Betrieb — landet bei einer eindeutigen Suche oft DIREKT auf der
Detailseite, ohne Ergebnisliste). Reine DOM-Extraktion, kein Playwright-Lifecycle
(Browser/Context/Page-Setup bleibt beim jeweiligen Aufrufer — die beiden haben
unterschiedliche Lebenszyklen: EIN langlebiger Discovery-Browser vs. ein kleiner Pool
dedizierter Enrichment-Worker).
"""
import re
import json

from scrapers.website_checker import check_website
from scrapers.regions import get_bundesland


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


def find_entries(page):
    """Alle Listeneinträge der aktuellen Maps-Suchergebnisseite (leer, wenn die Suche
    eindeutig war und Maps direkt auf die Detailseite umgeleitet hat)."""
    return page.query_selector_all(
        "a[href*='/maps/place/'], div[jsaction*='mouseover'] a[href*='/maps/place/']"
    )


def read_detail(page, region: str, branche: str) -> dict | None:
    """Liest die AKTUELL GEÖFFNETE Maps-Detailansicht aus (kein Klick nötig) — Basis für
    die klickende Discovery-Variante (extract_entry) und den direkten Einzel-Lookup
    (Enrichment landet bei eindeutigen Suchen oft ohne Ergebnisliste direkt hier)."""
    try:
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


def extract_entry(page, entry, region: str, branche: str, stop_event=None) -> dict | None:
    """Klickt einen Listeneintrag der Maps-Suchergebnisse und liest danach die Detailansicht
    (`stop_event` bisher ungenutzt, nur für Signatur-Kompatibilität mit dem Discovery-Aufrufer)."""
    try:
        entry.click()
        page.wait_for_timeout(1800)
    except Exception:
        return None
    return read_detail(page, region, branche)
