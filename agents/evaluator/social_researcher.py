"""Agent 2 — Web-Recherche: Social Media, Firmengröße, Kontext."""
from scrapers._http import ddg_search

# Alle relevanten Social-/Bild-Plattformen
SOCIAL_DOMAINS = {
    "facebook.com":   "facebook",
    "instagram.com":  "instagram",
    "linkedin.com":   "linkedin",
    "xing.com":       "xing",
    "youtube.com":    "youtube",
    "tiktok.com":     "tiktok",
    "twitter.com":    "twitter",
    "x.com":          "twitter",
    "pinterest.com":  "pinterest",
    "business.google.com": "google_business",
}

KETTEN_BRANDS = ["mcdonald", "burger king", "rewe", "edeka", "lidl", "aldi", "dm ", "rossmann"]

# Branchen die fast immer Klein-/Einzelbetriebe sind (Handwerk, Einzelpraxis).
_KLEIN_BRANCHEN = [
    "elektriker", "klempner", "heizung", "maler", "dachdecker", "fliesenleger",
    "schreiner", "schlosser", "sanitär", "gerüstbau", "trockenbau", "glaserei",
    "physiotherapeut", "heilpraktiker", "ergotherapeut", "logopäde", "podologe",
    "friseur", "kosmetik", "fotograf", "rolladenservice", "insektenschutz",
    "sonnenschutz", "gartenbau", "landschaftsgärtner", "autoaufbereitung",
    "schlüsseldienst", "steuerberater", "rechtsanwalt", "tierarzt", "optiker",
]

# Bildpräsenz-Plattformen (visuell → hohe Bild-Wahrscheinlichkeit).
_BILD_SOCIAL = {"instagram", "facebook", "pinterest", "youtube", "tiktok"}


def research(lead: dict, hits: list[dict] | None = None) -> dict:
    """
    Gibt zurück: {social_media: dict, hat_nur_social: int, beschreibung_roh: str,
                  firmengroesse_hinweis: str, hat_bilder_social: int}

    `hits`: vorgefundene Such-Treffer (vom WebAnalyst) — spart eine zweite Suche.
    Nur wenn None wird selbst gesucht.
    """
    result = {
        "social_media": {},
        "hat_nur_social": 0,
        "beschreibung_roh": "",
        "firmengroesse_hinweis": "",
        "hat_bilder_social": 0,
    }

    name    = (lead.get("name") or "").strip()
    stadt   = (lead.get("stadt") or "").strip()
    branche = (lead.get("branche") or "").strip()
    if not name:
        return result

    # Treffer wiederverwenden wenn vorhanden — sonst (nur dann) selbst suchen.
    if hits is None:
        hits = ddg_search(f'"{name}" {stadt}')

    social   = {}
    snippets = []

    for hit in hits[:12]:   # mehr Ergebnisse auswerten
        url     = hit.get("url", "")
        snippet = hit.get("snippet", "") or hit.get("title", "")

        for domain, key in SOCIAL_DOMAINS.items():
            if domain in url and key not in social:
                social[key] = url

        if snippet:
            snippets.append(snippet)

    # Zweite gezielte Suche nach Bildern/visueller Präsenz wenn noch keine Bilder
    if not any(k in social for k in _BILD_SOCIAL):
        img_hits = ddg_search(f'"{name}" {branche} {stadt} bilder fotos')
        for hit in img_hits[:6]:
            url = hit.get("url", "")
            for domain, key in SOCIAL_DOMAINS.items():
                if domain in url and key not in social:
                    social[key] = url
            snippet = hit.get("snippet", "") or hit.get("title", "")
            if snippet:
                snippets.append(snippet)

    result["social_media"]     = social
    result["beschreibung_roh"] = " | ".join(snippets[:5])[:600]

    # Bildpräsenz über Social (visuelle Plattformen = Bilder vorhanden)
    if any(k in social for k in _BILD_SOCIAL):
        result["hat_bilder_social"] = 1

    # Keine eigene Website aber Social vorhanden = hat_nur_social
    if social and not lead.get("has_website"):
        result["hat_nur_social"] = 1

    # Firmengröße-Hinweis aus Bewertungsanzahl + Branche
    rev   = int(lead.get("anz_bewertungen") or 0)
    bl    = branche.lower()
    klein = any(k in bl for k in _KLEIN_BRANCHEN)

    if any(k in name.lower() for k in KETTEN_BRANDS):
        result["firmengroesse_hinweis"] = "Kette"
    elif rev > 200 and not klein:
        result["firmengroesse_hinweis"] = "10-50"
    elif rev > 80:
        result["firmengroesse_hinweis"] = "3-10"
    elif klein:
        result["firmengroesse_hinweis"] = "1-2 Personen"
    elif rev > 50:
        result["firmengroesse_hinweis"] = "3-10"
    else:
        result["firmengroesse_hinweis"] = "1-2 Personen"

    return result
