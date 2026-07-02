"""
pricing.py — Faires, transparentes Preissystem für die Webseiten (einmalige Zahlung).

Grundgedanke (Sirs Vorgabe): moderne, individuell programmierte Local-Business-Webseite,
KEIN Baukasten, keine laufenden Entwicklungskosten. Einstieg ab 300 €, je nach Umfang typisch
300–600 €. Alles Einmalzahlung, Rechnung möglich.

Zwei Wege:
  • tiers()  → 3 klar benannte Pakete (Starter/Standard/Premium) für die Anzeige/Angebotsmail.
  • quote(features) → rechnet aus gewünschten Funktionen einen fairen Festpreis (mit Aufschlüsselung).

Alles über .env überschreibbar (JARVIS_PRICE_*), damit Sir die Zahlen jederzeit anpassen kann.
"""
from __future__ import annotations

import os


def _eur(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except Exception:
        return default


# ── Basis + Aufpreise (einmalig, in EUR) ──────────────────────────────────────
BASE = _eur("JARVIS_PRICE_BASE", 300)      # moderne One-Page-Webseite, mobil, Kontakt, Impressum
_MIN = _eur("JARVIS_PRICE_MIN", 300)
_MAX = _eur("JARVIS_PRICE_MAX", 950)

# Aufpreis-Bausteine — bewusst rund & nachvollziehbar.
FEATURES: dict[str, dict] = {
    "unterseiten":   {"label": "Mehrere Unterseiten (Leistungen, Team, Kontakt, Notdienst)", "price": _eur("JARVIS_PRICE_UNTERSEITEN", 120)},
    "terminanfrage": {"label": "Terminanfrage / Kontaktformular",                            "price": _eur("JARVIS_PRICE_TERMIN", 80)},
    "galerie":       {"label": "Bildergalerie / individuelle KI-Bilder",                     "price": _eur("JARVIS_PRICE_GALERIE", 60)},
    "admin":         {"label": "Geschützter Admin-Bereich (Inhalte selbst pflegen)",         "price": _eur("JARVIS_PRICE_ADMIN", 150)},
    "mehrsprachig":  {"label": "Mehrsprachigkeit (z. B. DE/EN)",                             "price": _eur("JARVIS_PRICE_SPRACHE", 90)},
    "blog":          {"label": "Blog / News-Bereich",                                        "price": _eur("JARVIS_PRICE_BLOG", 90)},
    "shop":          {"label": "Kleiner Online-Shop",                                        "price": _eur("JARVIS_PRICE_SHOP", 250)},
}


def range_text() -> str:
    """Typische Preisspanne als Text für Angebots-/Antwortmails."""
    lo = _eur("JARVIS_PRICE_TYP_MIN", 300)
    hi = _eur("JARVIS_PRICE_TYP_MAX", 600)
    return f"{lo} € und {hi} €"


def base_text() -> str:
    return f"ab {BASE} €"


def _clamp(p: int) -> int:
    return max(_MIN, min(_MAX, int(round(p / 10.0)) * 10))     # auf 10 € gerundet, geklemmt


def quote(features: "list | dict | None" = None) -> dict:
    """Fairer Festpreis für eine Auswahl an Funktionen.
    features: Liste von Keys aus FEATURES (oder dict {key: bool}). Gibt
    {price, min, max, positionen:[{label, price}], summary}."""
    keys: list[str] = []
    if isinstance(features, dict):
        keys = [k for k, v in features.items() if v]
    elif isinstance(features, list):
        keys = list(features)
    positionen = [{"label": "Basis: moderne, individuell programmierte Webseite", "price": BASE}]
    total = BASE
    for k in keys:
        f = FEATURES.get(k)
        if f:
            positionen.append({"label": f["label"], "price": f["price"]})
            total += f["price"]
    price = _clamp(total)
    return {
        "price": price,
        "min": _MIN,
        "max": _MAX,
        "positionen": positionen,
        "summary": f"{price} € einmalig",
    }


def tiers() -> list[dict]:
    """Drei klar benannte Pakete für Anzeige & Angebot — reale, faire Festpreise (300/450/600 €),
    passend zur kommunizierten Spanne „ab 300 €, meist 300–600 €". Über .env anpassbar. Für
    individuelle Umfänge (z. B. Shop) rechnet quote() additiv darüber hinaus."""
    return [
        {
            "key": "starter", "name": "Starter", "price": _eur("JARVIS_PRICE_STARTER", BASE),
            "claim": "Moderne One-Page-Webseite",
            "features": ["Individuell programmiert (kein Baukasten)", "Mobil & schnell",
                         "Kontakt & Anfahrt", "Impressum & Datenschutz", "Einmalzahlung"],
        },
        {
            "key": "standard", "name": "Standard", "price": _eur("JARVIS_PRICE_STANDARD", 450),
            "claim": "Mehr Seiten & Terminanfrage", "empfohlen": True,
            "features": ["Alles aus Starter", "Mehrere Unterseiten (Leistungen, Team, Kontakt)",
                         "Terminanfrage / Kontaktformular", "Bildergalerie"],
        },
        {
            "key": "premium", "name": "Premium", "price": _eur("JARVIS_PRICE_PREMIUM", 600),
            "claim": "Rundum-Paket mit Admin-Bereich",
            "features": ["Alles aus Standard", "Geschützter Admin-Bereich (selbst pflegen)",
                         "Individuelle KI-Bilder", "SEO-Feinschliff"],
        },
    ]


def summary() -> dict:
    """Kompakter Überblick fürs Dashboard / API."""
    return {"base": BASE, "min": _MIN, "max": _MAX,
            "range_text": range_text(), "tiers": tiers(), "features": FEATURES}
