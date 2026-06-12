"""Agent 2 — Web-Recherche: Social Media, Firmengröße, Kontext."""
from scrapers._http import ddg_search

SOCIAL_DOMAINS = {
    "facebook.com":  "facebook",
    "instagram.com": "instagram",
    "linkedin.com":  "linkedin",
    "xing.com":      "xing",
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

# Bildpräsenz-Plattformen.
_BILD_SOCIAL = {"instagram", "facebook"}


def research(lead: dict) -> dict:
    """
    Gibt zurück: {social_media: dict, hat_nur_social: int, beschreibung_roh: str,
                  firmengroesse_hinweis: str, hat_bilder_social: int}
    """
    result = {
        "social_media": {},
        "hat_nur_social": 0,
        "beschreibung_roh": "",
        "firmengroesse_hinweis": "",
        "hat_bilder_social": 0,
    }

    name  = (lead.get("name") or "").strip()
    stadt = (lead.get("stadt") or "").strip()
    if not name:
        return result

    query = f'"{name}" {stadt}'
    hits  = ddg_search(query)

    social   = {}
    snippets = []

    for hit in hits[:8]:
        url     = hit.get("url", "")
        snippet = hit.get("snippet", "")

        for domain, key in SOCIAL_DOMAINS.items():
            if domain in url and key not in social:
                social[key] = url

        if snippet:
            snippets.append(snippet)

    result["social_media"]     = social
    result["beschreibung_roh"] = " | ".join(snippets[:3])[:500]

    # Bildpräsenz über Social (Instagram/Facebook = visuelle Plattform)
    if any(k in social for k in _BILD_SOCIAL):
        result["hat_bilder_social"] = 1

    # Kein eigene Website aber Social vorhanden = hat_nur_social
    if social and not lead.get("has_website"):
        result["hat_nur_social"] = 1

    # Firmengröße-Hinweis aus Bewertungsanzahl + Branche
    rev     = int(lead.get("anz_bewertungen") or 0)
    branche = (lead.get("branche") or "").lower()
    klein   = any(k in branche for k in _KLEIN_BRANCHEN)

    if any(k in name.lower() for k in KETTEN_BRANDS):
        result["firmengroesse_hinweis"] = "Kette"
    elif rev > 200 and not klein:
        result["firmengroesse_hinweis"] = "10-50"
    elif rev > 80:
        result["firmengroesse_hinweis"] = "3-10"
    elif klein:
        # Handwerk/Einzelpraxis tendenziell klein — unabhängig von Reviews.
        result["firmengroesse_hinweis"] = "1-2 Personen"
    elif rev > 50:
        result["firmengroesse_hinweis"] = "3-10"
    else:
        result["firmengroesse_hinweis"] = "1-2 Personen"

    return result
