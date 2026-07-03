"""
KI-gestützte Potenzial-Einschätzung ("klein"/"mittel"/"groß") pro Firma — zusätzliche
Verkaufsspalte (Entscheidung: KI-Qualifizierung ja). Nutzt lokales Ollama (kein
Claude-Tokenverbrauch), wie der Rest von Jarvis2 (scrapers/_http.ask_ollama).

Heuristik-Fallback (kein Ollama erreichbar): grobe Regel-Einschätzung, damit das
System auch offline nie ohne Wert bleibt.
"""
from __future__ import annotations

import json
import re

from leadpackages.db_packages import get_all_stock, update_scoring
from leadpackages.quality_score import compute as compute_quality

_LABELS = {"klein", "mittel", "groß"}

_GROSS_HINWEISE = re.compile(
    r"\bgmbh\b|\bag\b|\bkg\b|\bgesmbh\b|filiale|zentrale|international", re.IGNORECASE
)


def _heuristik(row: dict) -> str:
    name = row.get("name") or ""
    if _GROSS_HINWEISE.search(name):
        return "mittel"
    if (row.get("anz_bewertungen") or 0) >= 20:
        return "mittel"
    return "klein"


def _via_ollama(row: dict) -> str | None:
    from leadpackages._ollama_bounded import ask_bounded
    prompt = (
        f"Firma: {row.get('name')}\n"
        f"Branche: {row.get('branche')}\n"
        f"Ort: {row.get('stadt')}\n"
        f"Hat Website: {'ja' if row.get('has_website') else 'nein'}\n"
        f"Bewertungen: {row.get('anz_bewertungen') or 0}\n\n"
        "Schätze die ungefähre Unternehmensgröße/das Geschäftspotenzial ein. "
        'Antworte NUR mit JSON: {"potenzial": "klein"|"mittel"|"groß"}'
    )
    # Kurze Deadline (6s) — läuft ggf. im Web-Request-Kontext (Bestell-Flow), darf
    # die Antwort nicht durch den 180s-Ollama-Default blockieren.
    raw = ask_bounded(prompt, system="Du bist ein präziser B2B-Datenanalyst.", hard_timeout=6.0)
    if not raw:
        return None
    match = re.search(r'"potenzial"\s*:\s*"([^"]+)"', raw)
    if match and match.group(1).lower() in _LABELS:
        return match.group(1).lower()
    return None


def compute(row: dict) -> str:
    return _via_ollama(row) or _heuristik(row)


def apply_all(land: str | None = None, branche: str | None = None, use_ollama: bool = True) -> dict:
    """Berechnet Potenzial-Label (+ Datenqualitäts-Score in einem Rutsch). Mit
    use_ollama=True kann das je Zeile bis zu ~6s dauern (siehe _ollama_bounded) —
    für synchrone Web-Requests use_ollama=False verwenden (nur Heuristik, sofort)."""
    rows = get_all_stock(land=land, branche=branche)
    for row in rows:
        label = (_via_ollama(row) if use_ollama else None) or _heuristik(row)
        update_scoring(row["id"], compute_quality(row), label)
    return {"aktualisiert": len(rows)}
