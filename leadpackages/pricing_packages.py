"""
Eigene Preisliste für Datenpakete — bewusst getrennt von pricing.py (Website-
Verkaufspreise, anderer Verkaufszweck). Startpreise, im Dashboard später anpassbar.
"""

BUNDLE_SIZES = [50, 200, 1000]

PREIS_EURO = {
    50: 49,
    200: 149,
    1000: 499,
}


def preis_fuer(bundle_size: int) -> int:
    return PREIS_EURO.get(bundle_size, 0)
