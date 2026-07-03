"""
Eigener Datenqualitäts-Score (0-100) für LeadForge — getrennt vom bestehenden
Website-Verkaufs-Score in agents/scorer.py (Entscheidung: getrennter Zweck).

Bewertet, wie GUT ein Datensatz für den Weiterverkauf ist (Vollständigkeit,
Kontaktwege, Frische) — nicht, wie kaufinteressiert die Firma für eine Website ist.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from leadpackages.db_packages import FRISCHE_TAGE, get_all_stock, update_scoring


def compute(row: dict) -> int:
    score = 0

    # Kontaktwege — wichtigster Faktor (max 40)
    n_kontakt = int(row.get("kontaktwege_anzahl") or 0)
    score += {0: 0, 1: 0, 2: 25}.get(n_kontakt, 40)

    # Website vorhanden (15)
    if row.get("has_website"):
        score += 15

    # Adresse vorhanden (15)
    if (row.get("adresse") or "").strip():
        score += 15

    # Bewertungen (max 15)
    if (row.get("anz_bewertungen") or 0) > 0:
        score += 10
        if (row.get("bewertung") or 0) >= 4.0:
            score += 5

    # Frische (15) — voll innerhalb FRISCHE_TAGE, sonst 0
    last_checked = row.get("last_checked_at")
    if last_checked:
        try:
            dt = datetime.fromisoformat(last_checked)
            if datetime.now() - dt <= timedelta(days=FRISCHE_TAGE):
                score += 15
        except ValueError:
            pass

    return max(0, min(100, score))


def apply_all(land: str | None = None, branche: str | None = None) -> dict:
    """Berechnet den Score für alle (oder gefilterte) stock_leads neu und schreibt ihn zurück.
    Reine Arithmetik, kein Ollama — darf synchron in einem Web-Request laufen."""
    rows = get_all_stock(land=land, branche=branche)
    for row in rows:
        update_scoring(row["id"], compute(row))
    return {"aktualisiert": len(rows)}
