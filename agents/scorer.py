"""
Lead-Scoring — bewertet jeden gefundenen Betrieb 0-100.
Kein API-Call nötig, reine Heuristik.
"""
from scrapers.regions import HIGH_VALUE, KETTEN_KEYWORDS


def score(lead: dict) -> tuple[int, str]:
    """
    Gibt (punkte: int, typ: str) zurück.
    typ = 'Hot' | 'Warm' | 'Cold'
    """
    pts = 0

    # Kein Website → Hauptsignal
    if not lead.get("has_website"):
        pts += 25

    # Hochwertige Branche
    branche = lead.get("branche", "")
    if any(hv.lower() in branche.lower() for hv in HIGH_VALUE):
        pts += 15

    # Bewertungs-Qualität
    rating = float(lead.get("bewertung", 0) or 0)
    if rating >= 4.5:
        pts += 12
    elif rating >= 4.0:
        pts += 8
    elif rating >= 3.5:
        pts += 4

    # Anzahl Bewertungen → Betrieb ist aktiv
    rev = int(lead.get("anz_bewertungen", 0) or 0)
    if rev >= 50:
        pts += 12
    elif rev >= 20:
        pts += 8
    elif rev >= 5:
        pts += 4

    # Telefon vorhanden → direkt kontaktierbar
    if lead.get("telefon"):
        pts += 10

    # Bilder vorhanden → professionelles Auftreten
    if lead.get("bilder"):
        pts += 6

    # Ketten / Franchises → wertlos
    name_lower = (lead.get("name") or "").lower()
    if any(k in name_lower for k in KETTEN_KEYWORDS):
        pts -= 25

    pts = max(0, min(100, pts))

    if pts >= 72:
        typ = "Hot"
    elif pts >= 48:
        typ = "Warm"
    else:
        typ = "Cold"

    return pts, typ
