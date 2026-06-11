"""Agent 2 — Web-Recherche: Social Media, Firmengröße, Kontext."""
from scrapers._http import ddg_search

SOCIAL_DOMAINS = {
    "facebook.com":  "facebook",
    "instagram.com": "instagram",
    "linkedin.com":  "linkedin",
    "xing.com":      "xing",
}

KETTEN_BRANDS = ["mcdonald", "burger king", "rewe", "edeka", "lidl", "aldi", "dm ", "rossmann"]


def research(lead: dict) -> dict:
    """
    Gibt zurück: {social_media: dict, hat_nur_social: int, beschreibung_roh: str,
                  firmengroesse_hinweis: str}
    """
    result = {
        "social_media": {},
        "hat_nur_social": 0,
        "beschreibung_roh": "",
        "firmengroesse_hinweis": "",
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

    result["social_media"]    = social
    result["beschreibung_roh"] = " | ".join(snippets[:3])[:500]

    # Kein eigene Website aber Social vorhanden = hat_nur_social
    if social and not lead.get("has_website"):
        result["hat_nur_social"] = 1

    # Firmengröße-Hinweis aus Bewertungsanzahl + Branche
    rev = int(lead.get("anz_bewertungen") or 0)

    if any(k in name.lower() for k in KETTEN_BRANDS):
        result["firmengroesse_hinweis"] = "Kette"
    elif rev > 200:
        result["firmengroesse_hinweis"] = "10-50"
    elif rev > 50:
        result["firmengroesse_hinweis"] = "3-10"
    else:
        result["firmengroesse_hinweis"] = "1-2 Personen"

    return result
