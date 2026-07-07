"""
Agent 1 — Tiefe, individuelle Website-Verifikation.

Findet AKTIV die echte Website (auch wenn der Scraper has_website=0 lieferte),
analysiert sie technisch, extrahiert E-Mail aus Impressum, prüft Bilder
unabhängig und protokolliert jeden Schritt.
"""
import json
import re
import datetime
from urllib.parse import urljoin, urlparse

from scrapers._http import get as http_get, ddg_search
import email_verify
import logger

_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
_BAD_DOMAINS = ['example', 'test', 'sentry', 'wix', 'google', 'schema', 'domain',
                'email', 'yourname', 'mustermann', 'sample']

# Verzeichnis-, Social-, Portal- und Marktplatz-Domains die NIE die eigene Website sind.
_NICHT_EIGENE = [
    'dasoertliche', 'gelbeseiten', '11880', 'golocal', 'cylex', 'meinestadt',
    'facebook', 'instagram', 'linkedin', 'xing', 'youtube', 'twitter', 'tiktok',
    'yelp', 'wikipedia', 'google.', 'maps.', 'provenexpert', 'trustpilot',
    'das-telefonbuch', 'herold', 'wlw.', 'werliefertwas', 'kununu', 'indeed',
    'ebay', 'amazon', 'booking.', 'tripadvisor', 'jameda', 'branchenbuch',
    # Handwerker-/Auftrags-Marktplätze + amtliche Verzeichnisse (mussten bisher manuell raus)
    'myhammer', 'blauarbeit', 'check24', 'kennstdueinen', 'aroundhome', 'wirmachendruck',
    'handwerkskammer', 'hwk-', 'hwk.', 'innung', 'kammer.', 'ihk-', 'ihk.',
    'meinprospekt', 'goyellow', 'pointoo', 'opendi', 'yalwa', 'hotfrog', 'infobel',
    'northdata', 'companyhouse', 'unternehmensregister', 'firmenabc', 'wer-zu-wem',
    'stepstone', 'stellenanzeigen', 'kleinanzeigen', 'immobilienscout', 'immoscout',
    # Suchmaschinen + Werbe-/Tracking-Redirects (DDG/Bing-Ads liefern keine eigene Seite)
    'duckduckgo', 'bing.com', 'y.js', 'ad_domain', 'ad_provider', '/aclick',
    'msclkid', 'doubleclick', 'googleadservices', 'googlesyndication',
]


def _ist_verzeichnis(url: str) -> bool:
    u = (url or "").lower()
    return any(d in u for d in _NICHT_EIGENE)


def _domain(url: str) -> str:
    try:
        net = urlparse(url if url.startswith("http") else "https://" + url).netloc.lower()
        # NICHT lstrip("www.") — das entfernt jedes führende w/./ (z.B. "wuermtal" → "uermtal").
        return net[4:] if net.startswith("www.") else net
    except Exception:
        return ""


def _real_emails(html: str) -> list[str]:
    emails = _EMAIL_RE.findall(html or "")
    return [e for e in emails
            if not any(b in e.lower() for b in _BAD_DOMAINS)
            and not any(b in e.lower() for b in email_verify.BAD_LOCAL_PARTS)]


def _mail_domain(email: str) -> str:
    """Domain-Teil einer E-Mail (klein, www-bereinigt). "" wenn keine Adresse."""
    e = (email or "").strip().lower()
    if "@" not in e:
        return ""
    d = e.rsplit("@", 1)[1].strip().strip(".")
    return d[4:] if d.startswith("www.") else d


def _telefon_plausibel(tel: str) -> bool:
    """Plausibilitätsprüfung einer Telefonnummer — zählt die TATSÄCHLICHEN Ziffern statt nur
    (wie bisher) eine Zeichenklasse zu matchen. Verhindert, dass Deko/Platzhalter wie
    '------', '00000' oder ' / ' als 'telefon_verifiziert' zählen und den Sicherheits-Score
    (20 Punkte) fälschlich anheben. Kalibriert auf deutsche und österreichische
    Rufnummern (DACH-Pipeline): Länder-/Amtsvorwahl abgezogen bleiben grob
    6–13 Teilnehmer-Ziffern."""
    t = (tel or "").strip()
    if not t:
        return False
    digits = re.sub(r"\D", "", t)
    # +49/0049 (DE) bzw. +43/0043 (AT) / führende Amts-0 entfernen → reine Teilnehmer-Ziffernzahl
    if digits.startswith("0049"):
        digits = digits[4:]
    elif digits.startswith("0043"):
        digits = digits[4:]
    elif digits.startswith("49") and len(digits) >= 11:
        digits = digits[2:]
    elif digits.startswith("43") and len(digits) >= 11:
        digits = digits[2:]
    digits = digits.lstrip("0")
    if not (6 <= len(digits) <= 13):
        return False
    if len(set(digits)) <= 1:                 # 000000 / 111111 ist keine echte Nummer
        return False
    return True


# Inhaber/Geschäftsführer aus Impressum (für persönliche Mail-Anrede).
_AP_PATTERNS = [
    r'(?:Gesch[äa]ftsf[üu]hrer(?:in)?)\s*[:\-]?\s*'
    r'([A-ZÄÖÜ][\wäöüß.\-]+(?:\s+[A-ZÄÖÜ][\wäöüß.\-]+){1,2})',
    r'(?:Inhaber(?:in)?)\s*[:\-]?\s*'
    r'([A-ZÄÖÜ][\wäöüß.\-]+(?:\s+[A-ZÄÖÜ][\wäöüß.\-]+){1,2})',
    r'(?:vertreten durch)\s*[:\-]?\s*'
    r'([A-ZÄÖÜ][\wäöüß.\-]+(?:\s+[A-ZÄÖÜ][\wäöüß.\-]+){1,2})',
]


def _ansprechpartner(html: str) -> str:
    """Versucht Inhaber/GF-Namen aus (Impressum-)HTML zu ziehen. "" wenn unklar."""
    text = re.sub(r'<[^>]+>', ' ', html or "")
    text = re.sub(r'\s+', ' ', text)
    for pat in _AP_PATTERNS:
        m = re.search(pat, text)
        if m:
            name = m.group(1).strip(' .-')
            woerter = name.split()
            if 2 <= len(woerter) <= 3 and not any(
                w.lower() in _RECHTSFORMEN for w in woerter
            ):
                return name[:80]
    return ""


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
    dann Treffer deren Titel/Snippet den Firmennamen nennt (generische Domain, z.B.
    Homepage-Baukasten-Subdomain). KEIN Blind-Fallback mehr auf den ersten beliebigen
    Nicht-Verzeichnis-Treffer: eine falsch zugeordnete Fremd-Website (Nachbar-Betrieb im
    selben Suchergebnis) würde E-Mail, Alter und Pitch-Text auf Basis einer komplett
    falschen Seite erzeugen — "keine Website gefunden" ist dann die ehrlichere,
    fürs Lead-Scoring sicherere Einordnung als eine geratene Zuordnung."""
    # Schritt 0 — bereits gesetzte URL SOFORT nehmen, wenn keine Verzeichnis-/Social-Domain.
    vorhanden = (lead.get("website_url") or "").strip()
    if vorhanden and not _ist_verzeichnis(vorhanden):
        return vorhanden

    eigene = [(hit.get("url") or "").strip() for hit in hits
              if (hit.get("url") or "").strip() and _ist_eigene_domain((hit.get("url") or "").strip())]
    if not eigene:
        return ""

    tokens = _name_tokens(lead.get("name", ""))
    if not tokens:
        return ""   # Name liefert keine auswertbaren Wort-Bestandteile → nicht raten

    # 1. Wahl: Domain enthält einen Namens-Bestandteil → sehr wahrscheinlich die echte Seite.
    for url in eigene:
        if any(t in _domain(url) for t in tokens):
            return url

    # 2. Wahl: Titel/Snippet des Treffers nennt den Firmennamen, auch wenn die Domain
    # selbst generisch ist (Homepage-Baukasten, Subdomain eines Anbieters etc.).
    by_url = {(hit.get("url") or "").strip(): hit for hit in hits}
    for url in eigene:
        hit  = by_url.get(url, {})
        text = f"{hit.get('title', '')} {hit.get('snippet', '')}".lower()
        if any(t in text for t in tokens):
            return url

    return ""   # keine belastbare Übereinstimmung → lieber "keine Website" als eine geratene


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
        "email_geprueft": 0,     # 1 = mind. eine Adresse per DNS/MX als zustellbar bestätigt
        "email_alle": [],        # alle gefundenen echten E-Mails
        "ansprechpartner": "",   # Inhaber/GF aus Impressum (für persönliche Anrede)
        "telefon_verifiziert": 0,
        "website_veraltet": 0, "website_alter_jahre": -1,
        "website_probleme": [],
        "bilder_vorhanden": 0,
        "foto_url": "",
        "foto_urls": [],         # mehrere Bild-URLs → öffenbarer Bilder-Ordner
        "verify_steps": [],
        "search_hits": [],     # für social_researcher wiederverwendbar (spart 2. Suche)
    }
    steps = result["verify_steps"]

    # ── Schritt 4 vorab: Telefon-Format-Check ───────────────────────────────
    tel = (lead.get("telefon") or "").strip()
    if _telefon_plausibel(tel):
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
            # Ein Timeout/Fehler kann ein langsamer, aber intakter Server sein — EIN
            # Retry mit mehr Zeit, bevor der Lead fälschlich als "veraltet" markiert wird
            # (Qualität > Tempo hier, nur dieser eine Fetch pro Lead, kein Scraper-Durchsatz).
            html = http_get(url, timeout=14)
        if not html:
            issues.append("Website nicht erreichbar")
            result["website_veraltet"] = 1
            steps.append("Website: nicht erreichbar")
        else:
            # E-Mail aus HTML — ALLE echten Adressen sammeln (dedupliziert)
            alle = list(dict.fromkeys(_real_emails(html)))

            # Impressum laden — weitere E-Mails + Ansprechpartner (Inhaber/GF)
            imp = re.search(r'href=["\']([^"\']*impressum[^"\']*)["\']', html, re.I)
            if imp:
                imp_url = imp.group(1)
                if not imp_url.startswith("http"):
                    imp_url = urljoin(url, imp_url)
                imp_html = http_get(imp_url, timeout=6)
                if imp_html:
                    for e in _real_emails(imp_html):
                        if e not in alle:
                            alle.append(e)
                    ap = _ansprechpartner(imp_html)
                    if ap:
                        result["ansprechpartner"] = ap

            # Ansprechpartner-Fallback aus der Startseite
            if not result["ansprechpartner"]:
                ap = _ansprechpartner(html)
                if ap:
                    result["ansprechpartner"] = ap

            if alle:
                # (a) DNS/MX-Zustellbarkeit: Adressen mit definitiv toter Domain rauswerfen —
                #     eine Mail dorthin bounct garantiert zurück. Unklare (DNS-Ausfall) bleiben
                #     drin (best-effort), zählen aber nicht als "geprüft".
                zustellbar: list[str] = []
                geprueft = False
                for e in alle:
                    mx = email_verify.is_deliverable(e)
                    if mx is False:
                        steps.append(f"E-Mail verworfen (Domain ohne Mailserver): {e}")
                        continue
                    zustellbar.append(e)
                    if mx is True:
                        geprueft = True

                # (b) Passgenauigkeit: E-Mails deren Domain zur gefundenen Website-Domain passt
                #     nach vorne — eine Seite listet oft auch Fremd-Adressen (Web-Designer, Portal),
                #     die eigene Betriebs-Adresse trägt die Website-Domain. Verhindert, dass die
                #     Akquise-Mail an den Dienstleister statt an den Betrieb geht.
                web_dom = _domain(url)
                if web_dom:
                    zustellbar.sort(key=lambda e: 0 if _mail_domain(e) == web_dom else 1)
                    # Passt mindestens eine Adresse zur Website-Domain, sind Fremd-Domain-
                    # Adressen (Web-Designer/Portal/Drittanbieter im selben HTML) eher
                    # Störgeräusch als echte Alternative — raus aus email_alle, damit sie
                    # nicht als falsche Kontaktoption im Dashboard/Pitch-Text auftauchen.
                    if any(_mail_domain(e) == web_dom for e in zustellbar):
                        zustellbar = [e for e in zustellbar if _mail_domain(e) == web_dom]

                # (c) Optionale SMTP-RCPT-Probe (Default AUS, JARVIS_SMTP_RCPT_CHECK): prüft
                # das konkrete Postfach, nicht nur die Domain. Wie bei der DNS/MX-Prüfung oben
                # werden nur DEFINITIV abgelehnte Adressen (550/551/553) verworfen — unklare
                # (Catch-All/Timeout/Greylisting) bleiben best-effort drin. Bleibt am Ende
                # NICHTS übrig, wird lieber die Ursprungsliste behalten als "keine E-Mail" zu
                # melden — eine False-Positive-Ablehnung darf einen validen Lead nicht entwerten.
                if zustellbar and email_verify.rcpt_check_enabled():
                    ungeprueft = zustellbar
                    zustellbar = []
                    for e in ungeprueft:
                        if email_verify.probe_mailbox(e) is False:
                            steps.append(f"E-Mail-Postfach abgelehnt (SMTP-RCPT): {e}")
                            continue
                        zustellbar.append(e)
                    if not zustellbar:
                        zustellbar = ungeprueft

                if zustellbar:
                    result["email_vorhanden"] = 1
                    result["email_geprueft"]  = 1 if geprueft else 0
                    result["email_adresse"]   = zustellbar[0][:100]
                    result["email_alle"]      = [e[:100] for e in zustellbar[:8]]

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
            # Impressum / Datenschutz (Mängel, aber KEIN Alters-Signal)
            if 'impressum' not in low and 'imprint' not in low:
                issues.append("Kein Impressum erkennbar")
            if 'datenschutz' not in low and 'privacy' not in low:
                issues.append("Keine Datenschutzerklärung")

            # 'veraltet' wird NUR durch echte Alt-Signale gesetzt (Copyright-Alter
            # >=4 oder Legacy-Technik oben) — NICHT durch fehlendes Mobile/Impressum/
            # Datenschutz. Sonst werden brandneue Seiten faelschlich als 'alt' markiert.

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
        # Foto-URL: og:image / twitter:image / Schema.org image
        try:
            og = (
                re.search(
                    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
                    html, re.I,
                ) or re.search(
                    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                    html, re.I,
                ) or re.search(
                    r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
                    html, re.I,
                ) or re.search(
                    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
                    html, re.I,
                )
            )
            if og:
                og_url = og.group(1).strip()
                if og_url and not og_url.startswith("http"):
                    og_url = urljoin(url, og_url)
                if og_url:
                    result["foto_url"] = og_url[:300]
        except Exception:
            pass

        # Mehrere Bild-URLs sammeln (öffenbarer Bilder-Ordner im Modal)
        srcs  = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.I)
        srcs += re.findall(r'<source[^>]+srcset=["\']([^"\']+)["\']', html, re.I)
        bild_urls: list[str] = []
        if result["foto_url"]:
            bild_urls.append(result["foto_url"])
        for s in srcs:
            s = (s or "").split(",")[0].split()[0].strip()   # srcset → erste URL
            if not s or s.startswith("data:"):
                continue
            if not s.startswith("http"):
                s = urljoin(url, s)
            low_s = s.lower()
            if any(b in low_s for b in
                   ("logo", "icon", "sprite", "pixel", "tracking", "favicon", ".svg")):
                continue
            if s not in bild_urls:
                bild_urls.append(s)
            if len(bild_urls) >= 8:
                break
        result["foto_urls"] = bild_urls[:8]

        # Bild-Heuristik: mehrere Signale zusammenzählen
        low = html.lower()
        img_count  = low.count("<img")
        pic_count  = low.count("<picture")
        srcset_cnt = low.count("srcset=")
        # Schema.org ImageObject
        schema_img = '"image"' in low or '"imageobject"' in low
        # Galerie/Portfolio-Hinweise
        gallery    = any(k in low for k in ("gallery", "galerie", "portfolio", "slider", "carousel", "bildergalerie"))

        has_bilder = (
            bool(result["foto_url"])
            or img_count > 1
            or pic_count > 0
            or srcset_cnt > 0
            or schema_img
            or gallery
            or maps_fotos > 0
        )
        result["bilder_vorhanden"] = 1 if has_bilder else 0
    else:
        result["bilder_vorhanden"] = 1 if maps_fotos else 0

    # ── Schritt 3b: Maps-Enrichment — echte Fotos/Telefon/Adresse für Leads aus JEDER
    # Quelle, nicht nur dem Maps-Scraper selbst. Additiv: füllt nur Lücken, überschreibt
    # nie bereits von der eigenen Website gefundene Daten. Best-effort — ein Timeout/
    # kein Treffer darf die Bewertung nie verzögern oder verschlechtern.
    if (lead.get("finder") or "").strip() != "maps_playwright" or not result["foto_urls"]:
        try:
            from agents.evaluator import maps_enrichment
            zusatz = maps_enrichment.enrich(lead)
        except Exception:
            zusatz = None
        if zusatz:
            if not result["foto_urls"] and zusatz.get("foto_urls"):
                # maps_common liefert foto_urls als JSON-STRING (DB-Speicherformat, siehe
                # db_raw/lead_key) — hier zu einer echten Liste parsen, sonst würde
                # list(json_string) den String zeichenweise zerlegen.
                try:
                    maps_fotos_liste = json.loads(zusatz["foto_urls"]) \
                        if isinstance(zusatz["foto_urls"], str) else list(zusatz["foto_urls"])
                except Exception:
                    maps_fotos_liste = []
                if maps_fotos_liste:
                    result["foto_url"]  = zusatz.get("foto_url", "")
                    result["foto_urls"] = maps_fotos_liste
                    result["bilder_vorhanden"] = 1
                    steps.append("Maps-Enrichment: Fotos ergänzt")
            if not result["telefon_verifiziert"] and zusatz.get("telefon") \
                    and _telefon_plausibel(zusatz["telefon"]):
                lead["telefon"] = zusatz["telefon"]
                result["telefon_verifiziert"] = 1
                steps.append("Maps-Enrichment: Telefon ergänzt")
            if not (lead.get("adresse") or "").strip() and zusatz.get("adresse"):
                lead["adresse"] = zusatz["adresse"]
                steps.append("Maps-Enrichment: Adresse ergänzt")
            if not (lead.get("anz_bewertungen") or 0) and zusatz.get("anz_bewertungen"):
                lead["anz_bewertungen"] = zusatz["anz_bewertungen"]
                lead["bewertung"]       = zusatz.get("bewertung", 0.0)
                steps.append("Maps-Enrichment: Bewertungen ergänzt")

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

    # Geladene Start-HTML für den ContentAnalyst durchreichen (kein zweiter Fetch).
    # Nur in-memory, wird NICHT in DB2 geschrieben — die Pipeline pickt gezielte Felder.
    result["html"] = (html or "")[:200_000]

    return result
