"""
Branchen-Synonym-Expansion via Ollama — einmalig generiert, gecacht.
43 Branchen → ~150 Suchbegriffe = deutlich mehr Funde.
"""
import json
import re
from pathlib import Path

from scrapers.regions import BRANCHEN
from scrapers import _http

CACHE_FILE = Path(__file__).parent.parent / "data" / "branchen_synonyme.json"


def _parse_array(raw: str) -> list[str]:
    """Extrahiert ein JSON-String-Array aus der Ollama-Antwort."""
    if not raw:
        return []
    try:
        m = re.search(r"\[.*?\]", raw, re.DOTALL)
        if m:
            arr = json.loads(m.group(0))
            return [str(x).strip() for x in arr if isinstance(x, (str, int, float))]
    except Exception:
        pass
    return []


def _fallback() -> dict[str, list[str]]:
    return {b: [b] for b in BRANCHEN}


def get_expanded_branchen() -> dict[str, list[str]]:
    """
    Gibt {branche: [branche, syn1, syn2, ...]} zurück — Original immer enthalten.
    Cache wird genutzt wenn vorhanden, sonst via Ollama generiert + gecacht.
    Bei Ollama-Ausfall: Fallback ohne Crash.
    """
    # 1. Cache lesen
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                # Sicherstellen dass Original immer enthalten ist
                return {b: data.get(b, [b]) or [b] for b in BRANCHEN}
        except Exception:
            pass

    # 2. Ollama erreichbar? (sonst Fallback ohne Crash)
    if not _http.ollama_models():
        return _fallback()

    result: dict[str, list[str]] = {}
    any_ok = False

    for b in BRANCHEN:
        prompt = (
            f"Nenne 2-3 alternative deutsche Bezeichnungen/Suchbegriffe für die Branche '{b}'. "
            f'Nur JSON-Array, z.B. ["Sanitärinstallateur", "Rohrreinigung"]'
        )
        raw  = _http.ask_ollama(prompt)
        syns = _parse_array(raw)

        # 3. Validierung: max 3, Strings 3-40 Zeichen, kein Duplikat von Original
        clean: list[str] = []
        for s in syns:
            s = s.strip()
            if 3 <= len(s) <= 40 and s.lower() != b.lower() and s not in clean:
                clean.append(s)
            if len(clean) >= 3:
                break

        if clean:
            any_ok = True
        result[b] = [b] + clean

    # 4. Cache schreiben (nur wenn mindestens ein Synonym generiert wurde)
    if any_ok:
        try:
            CACHE_FILE.parent.mkdir(exist_ok=True)
            CACHE_FILE.write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    # 5. Rückgabe
    return result or _fallback()


def expand_combos(combos: list[tuple]) -> list[tuple]:
    """
    [(region, branche)] → [(region, suchbegriff)] mit allen Synonymen.
    Hinweis: Wird aktuell NICHT vom Controller genutzt (Synonyme laufen im
    ai_worker, damit branche im Lead-Dict die Original-Branche bleibt).
    """
    expanded = get_expanded_branchen()
    out: list[tuple] = []
    for region, branche in combos:
        for term in expanded.get(branche, [branche]):
            out.append((region, term))
    return out
