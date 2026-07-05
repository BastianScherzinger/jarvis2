"""
Score-Kalibrierungs-Bericht (Backlog B9) — rein BERATEND, verändert NIE automatisch die
Gewichte in score_writer.py.

Warum kein automatischer Feedback-Loop: `db_evaluated.get_conversion_stats()` liefert reale
Konversionsdaten, aber das System hat Stand der Testphase erst sehr wenige tatsächliche
Verkäufe. Gewichte anhand von n=0/1/2 Verkäufen automatisch nachzujustieren wäre reines
Rauschen und könnte die Lead-Priorisierung aktiv verschlechtern. Dieses Modul macht darum nur
sichtbar, was die Daten NAHELEGEN, sobald genug Fälle vorliegen (Mindeststichprobe) — die
eigentliche Entscheidung, ob/wie score_writer.py angepasst wird, bleibt bei Sir.
"""
from __future__ import annotations

# Branchen-Einstufung wie in score_writer._preis_tier — hier nur zum Abgleich, nicht importiert
# (score_writer bleibt die einzige Quelle der Wahrheit fürs tatsächliche Scoring).
_HIGH_VAL = ["zahnarzt", "physiotherapeut", "rechtsanwalt", "steuerberater",
             "notar", "facharzt", "arzt", "kanzlei"]
_MEDIUM_VAL = ["elektriker", "dachdecker", "heizung", "klempner", "kfz", "sanitär",
               "bauunternehmen", "umzug", "reinigung", "tischler", "maler", "garten"]

MIN_SAMPLES = 20   # unter dieser Stichprobengröße wird eine Branche/Band NIE bewertet


def _tier_fuer_branche(branche: str) -> str:
    b = (branche or "").lower()
    if any(x in b for x in _HIGH_VAL):
        return "hoch"
    if any(x in b for x in _MEDIUM_VAL):
        return "mittel"
    return "standard"


def suggest_branch_calibration(min_samples: int = MIN_SAMPLES) -> dict:
    """Vergleicht die reale Konversionsrate (verkauft/aktiv) je Branche mit ihrer aktuellen
    Zahlkraft-Einstufung (hoch/mittel/standard aus score_writer._preis_tier) und schlägt NUR
    für Branchen mit genug Fällen (>= min_samples aktive Leads) eine Einordnung vor.

    Gibt {"genug_daten": bool, "branchen": [...], "score_bands": [...], "hinweis": str}
    zurück — rein informativ, nichts hiervon wird automatisch angewendet."""
    import db_evaluated

    stats = db_evaluated.get_conversion_stats()

    branchen_result = []
    for row in stats.get("nach_branche", []):
        aktiv = int(row.get("aktiv") or 0)
        if aktiv < min_samples:
            continue
        verkauft = int(row.get("verkauft") or 0)
        rate = round(verkauft / aktiv, 3) if aktiv else 0.0
        aktuelle_einstufung = _tier_fuer_branche(row.get("branche", ""))
        branchen_result.append({
            "branche": row.get("branche", ""),
            "aktive_leads": aktiv,
            "verkauft": verkauft,
            "konversionsrate": rate,
            "aktuelle_einstufung": aktuelle_einstufung,
        })
    branchen_result.sort(key=lambda r: r["konversionsrate"], reverse=True)

    band_result = []
    for row in stats.get("nach_score_band", []):
        aktiv = int(row.get("aktiv") or 0)
        if aktiv < min_samples:
            continue
        verkauft = int(row.get("verkauft") or 0)
        band_result.append({
            "band": row.get("band", ""),
            "aktive_leads": aktiv,
            "verkauft": verkauft,
            "konversionsrate": round(verkauft / aktiv, 3) if aktiv else 0.0,
        })

    genug_daten = bool(branchen_result or band_result)
    hinweis = (
        "Genug Daten für erste Hinweise — score_writer.py NICHT automatisch geändert, "
        "das bleibt eine bewusste manuelle Entscheidung."
        if genug_daten else
        f"Noch keine Branche/kein Score-Band erreicht die Mindeststichprobe "
        f"({min_samples} aktive Leads) — jede Kalibrierung wäre reines Rauschen. "
        "Bericht bleibt leer, bis genug reale Konversionen vorliegen."
    )
    return {
        "genug_daten": genug_daten,
        "branchen": branchen_result,
        "score_bands": band_result,
        "hinweis": hinweis,
    }
