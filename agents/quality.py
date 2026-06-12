"""
Qualitätsfilter — verhindert Portal-Müll und Fake-Einträge in der DB.
"""

PORTAL_WORDS = ["suche", "finden", "vergleich", "liste", "wikipedia", "facebook",
    "instagram", "youtube", "twitter", "yelp", "google", "11880", "gelbe seiten",
    "das örtliche", "branchenbuch", "verzeichnis", "portal", "anzeigen", "kleinanzeigen",
    "immobilien scout", "ebay", "amazon", "booking", "tripadvisor"]

# Generische UI-/Seiten-Texte die KEIN Betrieb sind (exakte Treffer, normalisiert).
# Fängt z.B. den Maps-Bug ab, bei dem die Überschrift "Ergebnisse" als Lead landet.
GENERIC_NAMES = {
    "ergebnisse", "suchergebnisse", "mehr ergebnisse", "keine ergebnisse",
    "results", "search results", "google maps", "maps", "anmelden", "login",
    "mehr anzeigen", "alle anzeigen", "weitere ergebnisse", "übersicht",
    "startseite", "home", "impressum", "kontakt", "menü", "menu",
}


def is_real_business(lead: dict) -> tuple[bool, str]:
    """
    Prüft ob ein Lead ein echter Betrieb ist (kein Portal/Fake).
    Gibt (ok, grund) zurück — grund leer wenn ok.
    """
    name = (lead.get("name") or "").strip()

    # 1. Name zu kurz
    if len(name) < 3:
        return (False, "Name zu kurz")

    name_lower = name.lower()

    # 2. Generischer UI-/Seiten-Text (exakter Treffer)
    if name_lower in GENERIC_NAMES:
        return (False, "Generischer Seiten-Text")

    # 3. Portal / Verzeichnis
    if any(w in name_lower for w in PORTAL_WORDS):
        return (False, "Portal/Verzeichnis")

    # 3. Nur Großbuchstaben + sehr lang → Werbe-Header
    letters = [c for c in name if c.isalpha()]
    if letters and len(name) > 30 and all(c.isupper() for c in letters):
        return (False, "Werbe-Header (nur Großbuchstaben)")

    # 4. Keine Kontaktdaten
    has_contact = bool(
        (lead.get("adresse") or "").strip()
        or (lead.get("telefon") or "").strip()
        or (lead.get("website_url") or "").strip()
    )
    if not has_contact:
        return (False, "Keine Kontaktdaten")

    return (True, "")
