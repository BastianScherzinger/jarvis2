"""
Qualitätsfilter — verhindert Portal-Müll und Fake-Einträge in der DB.
"""
import re

# Marken-/Domain-Begriffe: als Substring sicher (kommen in echten Firmennamen nicht vor).
_PORTAL_SUBSTR = ["wikipedia", "facebook", "instagram", "youtube", "twitter", "yelp",
    "11880", "gelbe seiten", "das örtliche", "branchenbuch", "kleinanzeigen",
    "immobilien scout", "ebay", "amazon", "booking", "tripadvisor", "google maps"]

# Generische deutsche Wörter: NUR als ganzes Wort prüfen — sonst werden echte
# Betriebe verworfen ("Listemann GmbH", "Findeisen", "Vergleichsweise …").
_PORTAL_WORDS = ["suche", "finden", "vergleich", "liste", "verzeichnis", "portal", "anzeigen"]
_PORTAL_RE = re.compile(r"\b(?:" + "|".join(_PORTAL_WORDS) + r")\b")

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

    # 3. Portal / Verzeichnis (Marken als Substring, generische Wörter wort-genau)
    if any(w in name_lower for w in _PORTAL_SUBSTR) or _PORTAL_RE.search(name_lower):
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
