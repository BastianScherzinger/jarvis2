"""
Package Builder — stellt aus stock_leads ein verkaufsfertiges Datenpaket zusammen
(Entscheidung: feste Bundle-Größen 50/200/1000, bestes Material zuerst).
"""
from __future__ import annotations

from leadpackages.db_packages import get_all_stock
from leadpackages.pricing_packages import BUNDLE_SIZES, preis_fuer


def _filtered(branche: str, region: str | None, land: str | None) -> list[dict]:
    rows = get_all_stock(land=land, branche=branche)
    if region:
        rows = [r for r in rows if (r.get("region") or "").lower() == region.lower()]
    rows.sort(key=lambda r: r.get("quality_score") or 0, reverse=True)
    return rows


def available_count(branche: str, region: str | None = None, land: str | None = None) -> int:
    return len(_filtered(branche, region, land))


def build(branche: str, bundle_size: int, region: str | None = None,
          land: str | None = None) -> dict:
    """Stellt bis zu bundle_size Zeilen zusammen (beste Datenqualität zuerst).
    Liefert weniger, wenn der Vorrat kleiner ist — kein Fehler, nur eine Info im Ergebnis."""
    rows = _filtered(branche, region, land)
    gewaehlt = rows[:bundle_size]
    return {
        "branche": branche,
        "region": region or "",
        "land": land or "",
        "bundle_size": bundle_size,
        "geliefert": len(gewaehlt),
        "vorrat_gesamt": len(rows),
        "preis_euro": preis_fuer(bundle_size),
        "rows": gewaehlt,
    }


def verfuegbare_pakete(branche: str, region: str | None = None, land: str | None = None) -> list[dict]:
    """Für die Bestell-Vorschau im Dashboard: welche Bundle-Größen sind mit wie viel
    Vorrat aktuell realistisch befüllbar."""
    total = available_count(branche, region, land)
    return [
        {"bundle_size": size, "preis_euro": preis_fuer(size),
         "verfuegbar": min(size, total), "voll_befuellbar": total >= size}
        for size in BUNDLE_SIZES
    ]
