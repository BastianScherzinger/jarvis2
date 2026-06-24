"""
ref_images.py — deterministische, akzentgetönte SVG-Referenzbilder als Platzhalter.

Garantiert, dass JEDE gebaute oder verbesserte Seite vollständig & wertig aussieht,
auch wenn gerade keine echte Bildquelle verfügbar ist (Higgsfield ohne Guthaben,
OpenAI-Tageslimit/Billing-Limit, CPU-Render zu langsam). Die Platzhalter sind
branchengetönt, druck-/retinascharf (SVG) und tragen ein dezentes „Referenz"-Label,
damit klar ist, dass hier ein echtes Foto eingesetzt wird. Echte Fotos/KI-Bilder
überschreiben die Platzhalter automatisch, sobald sie vorhanden sind.

Einstieg: ensure_placeholders(folder, content, branche) — füllt nur LEERE Bild-Slots.
"""
from __future__ import annotations

import re
from pathlib import Path

# Schlichte Strich-Icons (24×24 viewBox) je Gewerk — Teilstring der Branche (lower) → path.
_ICONS: dict[str, str] = {
    "dach":      "M3 11l9-7 9 7M5 10v9h14v-9M9 19v-5h6v5",
    "maler":     "M4 3h12v6H4zM16 6h3v5h-7v9a2 2 0 11-4 0v-5",
    "lackier":   "M4 3h12v6H4zM16 6h3v5h-7v4",
    "elektr":    "M13 2L4 14h7l-1 8 9-12h-7z",
    "sanitär":   "M7 3v6a5 5 0 0010 0V6M17 3v3M5 21h14",
    "heizung":   "M8 3v8M12 3v8M16 3v8M6 13h12v6a2 2 0 01-2 2H8a2 2 0 01-2-2z",
    "klima":     "M3 7h18v6H3zM6 16v3M12 16v3M18 16v3",
    "garten":    "M12 21c5-2 7-6 7-11-5 0-9 3-9 8M12 21c-3-1-4-4-4-7-3 0-5 2-5 5",
    "gala":      "M12 21c5-2 7-6 7-11-5 0-9 3-9 8",
    "kfz":       "M3 13l2-6h14l2 6v5h-3v-2H6v2H3zM6 13a1.5 1.5 0 100 3 1.5 1.5 0 000-3zm12 0a1.5 1.5 0 100 3 1.5 1.5 0 000-3z",
    "auto":      "M3 13l2-6h14l2 6v5h-3v-2H6v2H3zM6 13a1.5 1.5 0 100 3 1.5 1.5 0 000-3zm12 0a1.5 1.5 0 100 3 1.5 1.5 0 000-3z",
    "friseur":   "M6 6a3 3 0 106 0 3 3 0 00-6 0zM6 18a3 3 0 106 0 3 3 0 00-6 0zM9 9l11 9M9 15l11-9",
    "kosmetik":  "M12 3l2 5 5 2-5 2-2 5-2-5-5-2 5-2z",
    "bau":       "M3 21h18M5 21V9l7-5 7 5v12M9 21v-6h6v6",
    "tischler":  "M3 7l9 4 9-4-9-4zM3 7v6l9 4 9-4V7M3 13v4l9 4 9-4v-4",
    "schreiner": "M3 7l9 4 9-4-9-4zM3 7v6l9 4 9-4V7",
    "gastro":    "M6 3v7a2 2 0 004 0V3M8 12v9M16 3c-2 0-3 2-3 5s1 4 3 4v9",
    "restaurant":"M6 3v7a2 2 0 004 0V3M8 12v9M16 3c-2 0-3 2-3 5s1 4 3 4v9",
    "bäcker":    "M5 13a7 4 0 0014 0c0-3-3-6-7-6s-7 3-7 6zM5 13v3a3 3 0 003 3h8a3 3 0 003-3v-3",
    "reinigung": "M6 3l2 6M16 3l-1 6M5 9h14l-1 11H6zM10 13v4M14 13v4",
    "fenster":   "M4 4h16v16H4zM12 4v16M4 12h16",
    "fliesen":   "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
    "zimmerei":  "M3 11l9-7 9 7M5 10v9h14v-9",
    "metallbau": "M4 20h16M6 20V8h12v12M9 20v-6h6v6",
    "umzug":     "M3 7h11v8H3zM14 10h4l3 3v2h-7zM7 18a2 2 0 100-4 2 2 0 000 4zm10 0a2 2 0 100-4 2 2 0 000 4z",
    "immobilie": "M3 21h18M5 21V9l7-5 7 5v12M10 21v-6h4v6",
}
_DEFAULT_ICON = "M3 21h18M5 21V9l7-5 7 5v12M9 21v-6h6v6"   # Haus/Gebäude


def _icon(branche: str) -> str:
    low = (branche or "").lower()
    for key, path in _ICONS.items():
        if key in low:
            return path
    return _DEFAULT_ICON


def _accent(akzent: str) -> str:
    return akzent if re.fullmatch(r"#[0-9a-fA-F]{6}", str(akzent or "")) else "#1f6f54"


def _shade(hex_color: str, amount: int) -> str:
    try:
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        f = lambda v: max(0, min(255, v + amount))
        return f"#{f(r):02x}{f(g):02x}{f(b):02x}"
    except Exception:
        return hex_color


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _svg(w: int, h: int, akzent: str, branche: str, label: str = "",
         dark: bool = False, idkey: str = "p") -> str:
    """Ein wertiger Platzhalter: Verlauf in der Akzentfarbe + feines Punktraster +
    großes Strich-Icon mittig + dezentes Label. `dark` = stärker abgedunkelt (Hero)."""
    acc  = _accent(akzent)
    a1   = _shade(acc, -18 if not dark else -50)
    a2   = _shade(acc, -70 if not dark else -110)
    icon = _icon(branche)
    cx, cy = w / 2, h / 2 - (18 if label else 0)
    isc = min(w, h) / 9        # Icon-Skalierung
    lab = (f'<text x="{cx:.0f}" y="{cy + isc * 1.9:.0f}" text-anchor="middle" '
           f'font-family="Inter,Segoe UI,sans-serif" font-size="{max(12, w/46):.0f}" '
           f'letter-spacing="2" fill="#ffffff" fill-opacity="0.62">{_esc(label.upper())}</text>'
           if label else "")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{_esc(label or branche or 'Referenzbild')}">
  <defs>
    <linearGradient id="g{idkey}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{a1}"/><stop offset="1" stop-color="{a2}"/>
    </linearGradient>
    <pattern id="d{idkey}" width="22" height="22" patternUnits="userSpaceOnUse">
      <circle cx="2" cy="2" r="1.3" fill="#ffffff" fill-opacity="0.06"/>
    </pattern>
  </defs>
  <rect width="{w}" height="{h}" fill="url(#g{idkey})"/>
  <rect width="{w}" height="{h}" fill="url(#d{idkey})"/>
  <g transform="translate({cx:.1f} {cy:.1f}) scale({isc/12:.3f}) translate(-12 -12)"
     fill="none" stroke="#ffffff" stroke-opacity="0.82" stroke-width="1.4"
     stroke-linecap="round" stroke-linejoin="round"><path d="{icon}"/></g>
  {lab}
</svg>'''


def _write(img_dir: Path, fn: str, svg: str) -> str:
    img_dir.mkdir(parents=True, exist_ok=True)
    (img_dir / fn).write_text(svg, encoding="utf-8")
    return f"/static/img/{fn}"


def _has_image(folder: Path, web_path: str) -> bool:
    """True, wenn der /static/-Pfad auf eine real existierende Bilddatei im Ordner zeigt."""
    p = (web_path or "").strip()
    if not p.startswith("/static/"):
        return False
    f = folder / p.lstrip("/")
    return f.is_file()


def ensure_placeholders(folder: "str | Path", content: dict, branche: str = "",
                        n_gallery: int = 3) -> dict:
    """Füllt LEERE Bild-Slots (hero, about, Galerie) mit branchengetönten SVG-Referenzbildern,
    damit die Seite vollständig wirkt. Lässt echte Bilder (Foto/KI) unangetastet. Idempotent —
    setzt zusätzlich content['placeholder_images']=True, wenn mind. ein Platzhalter genutzt wird.
    Gibt das aktualisierte content-dict zurück (Aufrufer schreibt content.json)."""
    folder = Path(folder)
    img_dir = folder / "static" / "img"
    akzent = content.get("akzent") or "#1f6f54"
    branche = branche or content.get("branche") or ""
    used = False

    # 1) Hero — nur wenn weder ein echtes hero_image noch echte Galerie-Fotos existieren.
    hero = (content.get("hero_image") or "").strip()
    real_fotos = [f for f in (content.get("fotos") or []) if _has_image(folder, f)]
    if not _has_image(folder, hero) and not real_fotos:
        content["hero_image"] = _write(img_dir, "hero_ph.svg",
                                       _svg(1600, 900, akzent, branche, "Referenzbild",
                                            dark=True, idkey="h"))
        content.pop("hero_source", None)     # Platzhalter ist KEIN Cloud-Hero → darf ersetzt werden
        used = True

    # 2) Über-uns-Bild
    if not _has_image(folder, (content.get("about_image") or "").strip()):
        content["about_image"] = _write(img_dir, "about_ph.svg",
                                         _svg(900, 680, akzent, branche, "", idkey="a"))
        used = True

    # 3) Galerie — auf mind. n_gallery Kacheln auffüllen (echte Fotos zuerst).
    fotos = list(real_fotos)
    i = 1
    while len(fotos) < max(2, n_gallery):
        fn = f"gal_ph{i}.svg"
        # leichte Tönungs-Variation je Kachel, damit es nicht eintönig wirkt
        tint = _shade(akzent, -10 * (i - 1))
        fotos.append(_write(img_dir, fn, _svg(800, 600, tint, branche, "", idkey=f"g{i}")))
        i += 1
    if fotos != content.get("fotos"):
        content["fotos"] = fotos
        used = True

    if used:
        content["placeholder_images"] = True
    return content
