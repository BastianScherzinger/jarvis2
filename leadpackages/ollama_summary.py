"""
KI-Paketbeschreibung (Entscheidung: ja, via Ollama — 0 Claude-Tokens).
Fällt auf einen deterministischen Text zurück, wenn Ollama nicht erreichbar ist.
"""
from __future__ import annotations


def _fallback(branche: str, region: str, rows: list[dict]) -> str:
    n = len(rows)
    ohne_web = sum(1 for r in rows if not r.get("has_website"))
    avg_score = round(sum(r.get("quality_score") or 0 for r in rows) / n) if n else 0
    return (
        f"{n} Firmen aus der Branche {branche} in {region}. "
        f"{ohne_web} davon ohne eigene Website. "
        f"Durchschnittliche Datenqualität: {avg_score}/100."
    )


def generate(branche: str, region: str, rows: list[dict]) -> str:
    if not rows:
        return f"Keine Datensätze für {branche} in {region} verfügbar."
    fallback = _fallback(branche, region, rows)

    n = len(rows)
    ohne_web = sum(1 for r in rows if not r.get("has_website"))
    avg_score = round(sum(r.get("quality_score") or 0 for r in rows) / n) if n else 0
    prompt = (
        "Schreibe einen kurzen, sachlich-werblichen Verkaufstext (2-3 Sätze, Deutsch, "
        "keine Übertreibungen) für ein Firmendaten-Paket mit folgenden Eckdaten:\n"
        f"Branche: {branche}\nRegion: {region}\nAnzahl Firmen: {n}\n"
        f"Ohne eigene Website: {ohne_web}\nDurchschnittliche Datenqualität: {avg_score}/100"
    )
    from leadpackages._ollama_bounded import ask_bounded
    text = (ask_bounded(prompt, system="Du bist ein präziser B2B-Marketing-Texter.",
                        hard_timeout=6.0) or "").strip()
    return text or fallback
