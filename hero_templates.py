"""
hero_templates.py — vorgenerierte, branchengenaue Hero-Vorlagen (Stufe 1, 0 Cloud-Tokens).

Statt für JEDE Seite ein frisches Higgsfield-Hero zu erzeugen (kostet Abo-Credits + dauert),
liegen für die Top-Branchen fertige, ultrarealistische Hero-Bilder OHNE Text in `hero_templates/`
(16:9, Motiv mittig-rechts, ruhiger Raum links für die Headline, rechts Platz für die Rechner-
Karte). Dieses Modul wählt per Branche die passende Vorlage und KOPIERT sie als Hero in den Build.

So ist Stufe 1 (Hero) sofort, deterministisch und kostenlos. Echte gute Lead-Fotos schlagen die
Vorlage weiterhin (sie werden vorher gesetzt); ohne Treffer fällt die Pipeline auf die bisherige
Hero-Logik zurück (Higgsfield/lokal/Platzhalter).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

_DIR = Path(__file__).resolve().parent / "hero_templates"
_MANIFEST = _DIR / "manifest.json"


def _rules() -> list:
    try:
        data = json.loads(_MANIFEST.read_text(encoding="utf-8"))
        return data.get("rules") or []
    except Exception:
        return []


def available() -> bool:
    return _DIR.is_dir() and any(_DIR.glob("*.jpg"))


def pick(branche: str) -> "Path | None":
    """Pfad zur passenden Hero-Vorlage für die Branche (erster Keyword-Treffer in Reihenfolge),
    oder None, wenn keine Vorlage passt."""
    low = (branche or "").lower().strip()
    if not low:
        return None
    for rule in _rules():
        for key in rule.get("keys", []):
            if key and key in low:
                p = _DIR / rule.get("file", "")
                if p.is_file():
                    return p
                return None
    return None


def apply(folder: "str | Path", branche: str, content: dict,
          force: bool = False) -> bool:
    """Kopiert die zur Branche passende Hero-Vorlage als static/img/hero.png in den Build und
    setzt content['hero_image'] + content['hero_source']='template'. Gibt True bei Erfolg.

    Respektiert vorhandene Heros: ein vom Inhaber hochgeladenes (hero_custom) oder ein als Hero
    gewähltes echtes Lead-Foto (hero_source='lead_foto') wird NICHT überschrieben — außer force.
    `content` wird nur im Speicher aktualisiert; der Aufrufer schreibt content.json."""
    folder = Path(folder)
    if not force:
        if content.get("hero_custom"):
            return False
        if content.get("hero_source") in ("lead_foto",):
            return False
    src = pick(branche or content.get("branche", ""))
    if not src:
        return False
    try:
        dst = folder / "static" / "img" / "hero.png"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    except Exception:
        return False
    content["hero_image"] = "/static/img/hero.png"
    content["hero_source"] = "template"
    content["hero_template"] = src.name
    return True


if __name__ == "__main__":                      # Mini-Selbsttest
    for b in ["Zahnarzt", "KFZ Werkstatt", "Physiotherapeut", "Umzugsunternehmen",
              "Sanitär", "Heizungsbauer", "Elektriker", "Schreiner", "Rechtsanwalt"]:
        p = pick(b)
        print(f"{b:22s} -> {p.name if p else '— (keine Vorlage, Fallback)'}")
