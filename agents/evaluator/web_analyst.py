"""
Agent 1 — Tiefe, individuelle Website-Verifikation.

Findet AKTIV die echte Website (auch wenn der Scraper has_website=0 lieferte),
analysiert sie technisch, extrahiert E-Mail aus Impressum, prüft Bilder
unabhängig und protokolliert jeden Schritt.
"""
import re
import datetime
from urllib.parse import urljoin, urlparse

from scrapers._http import get as http_get, ddg_search
import logger

_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
_BAD_DOMAINS = ['example', 'test', 'sentry', 'wix', 'google', 'schema', 'domain',
                'email', 'yourname', 'mustermann', 'sample']

# Verzeichnis-, Social- und Portal-Domains die NIE die eigene Website sind.
_NICHT_EIGENE = [
    'dasoertliche', 'gelbeseiten', '11880', 'golocal', 'cylex', 'meinestadt',
    'facebook', 'instagram', 'linkedin', 'xing', 'youtube', 'twitter', 'tiktok',
    'yelp', 'wikipedia', 'google.', 'maps.', 'provenexpert', 'trustpilot',
    'das-telefonbuch', 'herold', 'wlw.', 'werliefertwas', 'kununu', 'indeed',
    'ebay', 'amazon', 'booking.', 'tripadvisor', 'jameda', 'branchenbuch',
]


def _ist_verzeichnis(url: str) -> bool:
    u = (url or "").lower()
    return any(d in u for d in _NICHT_EIGENE)


def _domain(url: str) -> str:
    try:
        net = urlparse(url if url.startswith("http") else "https://" + url).netloc
        return net.lower().lstrip("www.")
    except Exception:
        return ""


def _real_emails(html: str) -> list[str]:
    emails = _EMAIL_RE.findall(html or "")
    return [e for e in emails if not any(b in e.lower() for b in _BAD_DOMAINS)]


def _ist_eigene_domain(url: str) -> bool:
    """True wenn die URL eine eigene Website sein könnte: kein Verzeichnis/Social
    und eine gängige TLD. RELAXED — keine strenge Namens-Plausibilitätsprüfung."""
    if _ist_verzeichnis(url):
        return False
    dom = _domain(url)
    if not dom:
        return False
    return dom.endswith((".de", ".com", ".net", ".eu", ".org", ".info", ".biz", ".io"))


_RECHTSFORMEN = {"gmbh", "co", "kg", "ohg", "ag", "ek", "ug", "mbh", "und", "the",
                 "inh", "fa", "firma", "betrieb", "meister", "gbr"}


def _name_tokens(name: str) -> list[str]:
    """Aussagekräftige Wort-Bestandteile eines Firmennamens (für Domain-Abgleich)."""
    roh = re.split(r'[^a-zäöüß0-9]+', (name or "").lower())
    return [t for t in roh if len(t) >= 4 and t not in _RECHTSFORMEN]


def _pick_website(lead: dict, hits: list[dict]) -> str:
    """Wählt aus den Such-Treffern die wahrscheinliche eigene Website. URL oder "".
    Bevorzugt Treffer deren Domain einen Namens-Bestandteil enthält (passgenauer),
    fällt sonst auf den ersten Nicht-Verzeichnis-Treffer zurück (findet trotzdem was)."""
    # Schritt 0 — bereits gesetzte URL SOFORT nehmen, wenn keine Verzeichnis-/Social-Domain.
    vorhanden = (lead.get("website_url") or "").strip()
    if vorhanden and not _ist_verzeichnis(vorhanden):
        return vorhanden

    eigene = [(hit.get("url") or "").strip() for hit in hits
              if (hit.get("url") or "").strip() and _ist_eigene_domain((hit.get("url") or "").strip())]
    if not eigene:
        return ""

    # 1. Wahl: Domain enthält einen Namens-Bestandteil → sehr wahrscheinlich die echte Seite.
    tokens = _name_tokens(lead.get("name", ""))
    if tokens:
        for url in eigene:
            dom = _domain(url)
            if any(t in dom for t in tokens):
                return url

    # 2. Wahl: erster plausibler Nicht-Verzeichnis-Treffer.
    return eigene[0]


def analyze(lead: dict) -> dict:
    """
    Prüft IMMER tief — auch bei has_website=0.

    Rückgabe:
      discovered_website, has_website (überschreibt Scraper), website_url,
      email_vorhanden, email_adresse, telefon_verifiziert,
      website_veraltet, website_alter_jahre, website_probleme(list),
      bilder_vorhanden, foto_url, verify_steps(list).
    """
    name    = (lead.get("name") or "").strip()
    stadt   = (lead.get("stadt") or "").strip()
    branche = (lead.get("branche") or "").strip()

    result = {
        "discovered_website": "",
        "has_website": 0,
        "website_url": "",
        "email_vorhanden": 0, "email_adresse": "",
        "telefon_verifiziert": 0,
        "website_veraltet": 0, "website_alter_jahre": -1,
        "website_probleme": [],
        "bilder_vorhanden": 0,
        "foto_url": "",
        "verify_steps": [],
        "search_hits": [],     # für social_researcher wiederverwendbar (spart 2. Suche)
    }
    steps = result["verify_steps"]

    # ── Schritt 4 vorab: Telefon-Format-Check ───────────────────────────────
    tel = (lead.get("telefon") or "").strip()
    if tel and len(tel) >= 6 and re.search(r'[\d\s\-\+\(\)]{6,}', tel):
        result["telefon_verifiziert"] = 1

    # ── Schritt 1: Website aktiv finden (EINE Suche, geteilt mit SocialRes) ──
    logger.debug("WebAnalyst", f"→ Suche Website für {name}…")
    vorhanden = (lead.get("website_url") or "").strip()
    if vorhanden and not _ist_verzeichnis(vorhanden):
        hits = []                      # URL schon bekannt — keine Suche nötig
    else:
        hits = ddg_search(f"{name} {stadt}".strip())
    result["search_hits"] = hits
    url = _pick_website(lead, hits)

    if url:
        result["discovered_website"] = url
        result["website_url"]        = url
        result["has_website"]        = 1
        logger.debug("WebAnalyst", f"→ Website gefunden: {url}")
        steps.append(f"Website-Suche: gefunden {_domain(url)}")
    else:
        logger.debug("WebAnalyst", "→ Keine eigene Website (starkes Signal)")
        steps.append("Website-Suche: KEINE eigene Website gefunden")

    issues = result["website_probleme"]

    # ── Schritt 2: Website analysieren (nur wenn gefunden) ──────────────────
    html = ""
    if url:
        html = http_get(url, timeout=8)
        if not html:
            issues.append("Website nicht erreichbar")
            result["website_veraltet"] = 1
            steps.append("Website: nicht erreichbar")
        else:
            # E-Mail aus HTML
            real = _real_emails(html)
            if real:
                result["email_vorhanden"] = 1
                result["email_adresse"]   = real[0][:100]

            # Impressum-Fallback für E-Mail
            if not result["email_vorhanden"]:
                imp = re.search(r'href=["\']([^"\']*impressum[^"\']*)["\']', html, re.I)
                if imp:
                    imp_url = imp.group(1)
                    if not imp_url.startswith("http"):
                        imp_url = urljoin(url, imp_url)
                    imp_html = http_get(imp_url, timeout=6)
                    real_imp = _real_emails(imp_html)
                    if real_imp:
                        result["email_vorhanden"] = 1
                        result["email_adresse"]   = real_imp[0][:100]

            low = html.lower()

            # HTTPS
            if not url.startswith("https://"):
                issues.append("Kein HTTPS")
            # Mobile-Viewport
            if 'viewport' not in low:
                issues.append("Kein Mobile-Viewport (nicht mobil-freundlich)")
            # Copyright-Jahr → Alter
            years = re.findall(
                r'(?:©|copyright|Copyright)\s*(?:\d{4}\s*[-–]\s*)?(20\d{2})', html
            )
            if years:
                max_year = max(int(y) for y in years)
                age = datetime.date.today().year - max_year
                result["website_alter_jahre"] = age
                if age >= 4:
                    issues.append(f"Copyright {max_year} — {age} Jahre alt")
                    result["website_veraltet"] = 1
            # Veraltete Technik
            for pattern, label in (
                (r'<table[^>]+(?:width|cellpadding|cellspacing)', "Tabellen-Layout (veraltet)"),
                (r'<font\s', "Font-Tags (veraltet)"),
                (r'\.swf["\']', "Flash-Inhalte"),
                (r'<marquee', "Marquee-Tag"),
                (r'<frameset', "Frames-Layout"),
            ):
                if re.search(pattern, html, re.I):
                    issues.append(label)
                    result["website_veraltet"] = 1
            # Impressum / Datenschutz
            if 'impressum' not in low and 'imprint' not in low:
                issues.append("Kein Impressum erkennbar")
            if 'datenschutz' not in low and 'privacy' not in low:
                issues.append("Keine Datenschutzerklärung")

            if issues:
                result["website_veraltet"] = 1

            # WHOIS-Fallback fürs Alter
            if result["website_alter_jahre"] == -1:
                try:
                    from scrapers.website_checker import _whois_age
                    result["website_alter_jahre"] = _whois_age(url)
                except Exception:
                    pass

        result["website_probleme"] = issues[:6]

    # ── Schritt 3: Bilder + Foto-URL erfassen ───────────────────────────────
    maps_fotos = int(lead.get("bilder_maps") or 0)
    if html:
        # og:image extrahieren → Foto-URL für die Vorschau.
        try:
            og = re.search(
                r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
                html, re.I,
            ) or re.search(
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                html, re.I,
            )
            if og:
                og_url = og.group(1).strip()
                if og_url and not og_url.startswith("http"):
                    og_url = urljoin(url, og_url)
                result["foto_url"] = og_url[:300]
        except Exception:
            pass

        img_count = html.lower().count("<img")
        if result["foto_url"] or img_count > 3 or maps_fotos:
            result["bilder_vorhanden"] = 1
    else:
        result["bilder_vorhanden"] = 1 if maps_fotos else 0

    if result["foto_url"]:
        logger.debug("WebAnalyst", f"→ Foto-URL: {result['foto_url']}")

    bilder_txt = "ja" if result["bilder_vorhanden"] else "nein"
    alter = result["website_alter_jahre"]
    logger.debug(
        "WebAnalyst",
        f"→ Alter: {alter}J | Probleme: {len(result['website_probleme'])} | "
        f"Bilder: {bilder_txt}",
    )
    if url:
        steps.append(f"Alter: {alter if alter >= 0 else 'unbekannt'} Jahre")
    steps.append(f"Bilder: {bilder_txt}")

    return result
