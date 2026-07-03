"""
Zusätzliche Fuzzy-Dublettenerkennung für LeadForge (Entscheidung: strenger als
Bestand) — ergänzt die bestehende exakte Dedup (leadkey.py/duplicate_guard.py),
die auf normalisierten Namen+Stadt basiert. rapidfuzz erkennt auch leicht
unterschiedliche Schreibweisen ("Müller GmbH" vs. "Mueller GmbH & Co KG").

Läuft NUR innerhalb von stock_leads (isoliert) — evaluated_leads/raw_leads bleiben
unberührt.
"""
from __future__ import annotations

from itertools import combinations

from rapidfuzz import fuzz

from leadpackages.db_packages import delete_stock, get_all_stock

THRESHOLD = 90   # ab diesem Ähnlichkeitswert (0-100) gilt ein Paar als Dublette


def find_and_remove_duplicates(land: str | None = None, branche: str | None = None) -> dict:
    """Gruppiert stock_leads nach (land, stadt, branche) — Dubletten kommen praktisch
    nur innerhalb derselben Kombination vor — und vergleicht dort paarweise per
    rapidfuzz. Von jedem gefundenen Paar bleibt der Datensatz mit dem höheren
    quality_score, der schwächere wird gelöscht."""
    rows = get_all_stock(land=land, branche=branche)
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        key = (r.get("land"), (r.get("stadt") or "").lower(), (r.get("branche") or "").lower())
        groups.setdefault(key, []).append(r)

    to_delete: set[int] = set()
    for group in groups.values():
        for a, b in combinations(group, 2):
            if a["id"] in to_delete or b["id"] in to_delete:
                continue
            ratio = fuzz.token_sort_ratio((a.get("name") or "").lower(), (b.get("name") or "").lower())
            if ratio >= THRESHOLD:
                worse = a if (a.get("quality_score") or 0) < (b.get("quality_score") or 0) else b
                to_delete.add(worse["id"])

    entfernt = delete_stock(list(to_delete))
    return {"geprueft": len(rows), "gruppen": len(groups), "dubletten_entfernt": entfernt}
