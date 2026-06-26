"""
design_tokens.py — LOKALE „taste"-Stufe (0 Claude-Tokens).

Die Basis-Vorlage (vorlage_landing) rendert bereits alle Blöcke aus content.json und ist
über CSS-Variablen voll token-getrieben. Das einzige, was bisher pro Kunde injiziert wurde,
war `--accent`. Dieses Modul macht daraus eine *vollständige*, harmonische Design-Stufe —
deterministisch, lokal, ohne ein KI-Modell:

  1. Aus der Akzentfarbe wird per HSL-Mathe eine stimmige Farbwelt abgeleitet (getönte
     Neutrals: bg / surface / ink / ink-soft / line), die zur Marke passt (WCAG-AA-sicher).
  2. Aus der Branche wird ein charakterstarkes, passendes Google-Font-Pairing gewählt
     (Display + Body) — kuratiert, nicht zufällig.
  3. Beides wird in `static/css/tokens.css` geschrieben und (idempotent) ins Template
     eingebunden. tokens.css lädt NACH style.css und überschreibt daher sauber Palette
     und Fonts — auch auf bereits gebauten Seiten (deren style.css unverändert bleibt).

Damit ersetzt diese Stufe den teuren Headless-Claude-Design-Durchgang für die Farb-/Font-
Arbeit vollständig. Der optionale dünne Claude-Politur-Pass baut nur noch darauf auf.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# ── Farb-Mathe (Hex ↔ HSL) ─────────────────────────────────────────────────────

def _hex_to_rgb(hex_str: str) -> "tuple[int, int, int]":
    h = (hex_str or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6 or re.fullmatch(r"[0-9a-fA-F]{6}", h) is None:
        h = "1f6f54"                      # ruhiges Grün als Default (wie website_builder)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hsl(r: int, g: int, b: int) -> "tuple[float, float, float]":
    rf, gf, bf = r / 255, g / 255, b / 255
    mx, mn = max(rf, gf, bf), min(rf, gf, bf)
    l = (mx + mn) / 2
    if mx == mn:
        return 0.0, 0.0, l
    d = mx - mn
    s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
    if mx == rf:
        h = (gf - bf) / d + (6 if gf < bf else 0)
    elif mx == gf:
        h = (bf - rf) / d + 2
    else:
        h = (rf - gf) / d + 4
    return h / 6 * 360, s, l


def _hsl_to_hex(h: float, s: float, l: float) -> str:
    h = (h % 360) / 360
    s = max(0.0, min(1.0, s))
    l = max(0.0, min(1.0, l))

    def _hue(p, q, t):
        if t < 0:
            t += 1
        if t > 1:
            t -= 1
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p

    if s == 0:
        r = g = b = l
    else:
        q = l * (1 + s) if l < 0.5 else l + s - l * s
        p = 2 * l - q
        r = _hue(p, q, h + 1 / 3)
        g = _hue(p, q, h)
        b = _hue(p, q, h - 1 / 3)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def _luminance(r: int, g: int, b: int) -> float:
    def _lin(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast(hex_a: str, hex_b: str) -> float:
    la = _luminance(*_hex_to_rgb(hex_a))
    lb = _luminance(*_hex_to_rgb(hex_b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def derive_palette(accent: str) -> dict:
    """Leitet aus EINER Akzentfarbe eine stimmige, getönte Neutral-Palette ab.
    Alle Neutrals tragen einen Hauch der Akzent-Tonalität (kohärent), bleiben aber
    WCAG-AA-tauglich (ink auf bg, accent als Button-BG mit weißem Text)."""
    r, g, b = _hex_to_rgb(accent)
    h, s, l = _rgb_to_hsl(r, g, b)
    accent_hex = "#{:02x}{:02x}{:02x}".format(r, g, b)

    # Akzent leicht normalisieren, falls extrem hell/blass (für Buttons mit weißer Schrift).
    acc_l = l
    if _contrast(accent_hex, "#ffffff") < 3.0:          # zu hell → abdunkeln bis Text lesbar
        acc_l = max(0.30, l - 0.18)
        accent_hex = _hsl_to_hex(h, max(s, 0.45), acc_l)

    # Getönte Neutrals — niedrige Sättigung, Hue der Marke.
    bg       = _hsl_to_hex(h, min(s, 0.22) * 0.5, 0.975)   # fast-weiß, ein Hauch Marke
    surface  = "#ffffff"
    ink      = _hsl_to_hex(h, min(s, 0.30) * 0.6, 0.11)    # near-black, leicht getönt
    ink_soft = _hsl_to_hex(h, min(s, 0.24) * 0.5, 0.38)
    line     = _hsl_to_hex(h, min(s, 0.20) * 0.5, 0.90)
    # Dunkle Akzent-Variante (Hover/Tiefe) und Akzent-Tinte für Bänder.
    accent_dk = _hsl_to_hex(h, min(1.0, s + 0.05), max(0.18, acc_l - 0.12))

    return {
        "accent": accent_hex,
        "accent_dark": accent_dk,
        "bg": bg,
        "surface": surface,
        "ink": ink,
        "ink_soft": ink_soft,
        "line": line,
    }


# ── Font-Pairings (kuratiert, alle Google Fonts) ───────────────────────────────

# css2-Fragment je Familie (kontrollierte Achsen/Gewichte → valider Google-Fonts-Link).
_FAMILY_SPEC = {
    "Fraunces":            "Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700",
    "Inter":               "Inter:wght@400;500;600",
    "Playfair Display":    "Playfair+Display:wght@500;600;700",
    "Source Sans 3":       "Source+Sans+3:wght@400;500;600",
    "Poppins":             "Poppins:wght@400;500;600;700",
    "Cormorant Garamond":  "Cormorant+Garamond:wght@500;600;700",
    "Jost":                "Jost:wght@400;500;600",
    "DM Serif Display":    "DM+Serif+Display",
    "Archivo":             "Archivo:wght@400;500;600;700",
    "Sora":                "Sora:wght@400;500;600;700",
    "Space Grotesk":       "Space+Grotesk:wght@400;500;600;700",
}

_DEFAULT_PAIR = ("Fraunces", "Inter")

# Erster Teilstring-Treffer in der Branche gewinnt → spezifische Schlüssel zuerst.
_PAIRS: "list[tuple[str, tuple[str, str]]]" = [
    # Recht / Beratung / Finanzen — seriös-klassisch
    ("rechtsanwalt", ("Playfair Display", "Source Sans 3")),
    ("anwalt",       ("Playfair Display", "Source Sans 3")),
    ("kanzlei",      ("Playfair Display", "Source Sans 3")),
    ("notar",        ("Playfair Display", "Source Sans 3")),
    ("steuerberat",  ("Playfair Display", "Source Sans 3")),
    ("steuer",       ("Playfair Display", "Source Sans 3")),
    ("buchhalt",     ("Playfair Display", "Source Sans 3")),
    ("versicher",    ("Playfair Display", "Source Sans 3")),
    ("immobil",      ("Cormorant Garamond", "Jost")),
    ("makler",       ("Cormorant Garamond", "Jost")),
    ("architek",     ("Space Grotesk", "Inter")),
    # Gesundheit — freundlich-klar
    ("zahnarzt",     ("Poppins", "Inter")),
    ("zahn",         ("Poppins", "Inter")),
    ("kieferortho",  ("Poppins", "Inter")),
    ("physio",       ("Poppins", "Inter")),
    ("ergotherap",   ("Poppins", "Inter")),
    ("therapie",     ("Poppins", "Inter")),
    ("tierarzt",     ("Poppins", "Inter")),
    ("arzt",         ("Poppins", "Inter")),
    ("ärzt",         ("Poppins", "Inter")),
    ("praxis",       ("Poppins", "Inter")),
    ("heilprakt",    ("Poppins", "Inter")),
    ("apotheke",     ("Poppins", "Inter")),
    # Beauty & Körper — elegant
    ("friseur",      ("Cormorant Garamond", "Jost")),
    ("frisör",       ("Cormorant Garamond", "Jost")),
    ("frisoer",      ("Cormorant Garamond", "Jost")),
    ("barber",       ("Archivo", "Inter")),
    ("kosmetik",     ("Cormorant Garamond", "Jost")),
    ("nagel",        ("Cormorant Garamond", "Jost")),
    ("beauty",       ("Cormorant Garamond", "Jost")),
    ("tattoo",       ("Space Grotesk", "Inter")),
    ("fitness",      ("Sora", "Inter")),
    ("yoga",         ("Cormorant Garamond", "Jost")),
    # Gastro & Lebensmittel — warm
    ("restaurant",   ("DM Serif Display", "Inter")),
    ("gastro",       ("DM Serif Display", "Inter")),
    ("catering",     ("DM Serif Display", "Inter")),
    ("café",         ("DM Serif Display", "Inter")),
    ("cafe",         ("DM Serif Display", "Inter")),
    ("bäcker",       ("DM Serif Display", "Inter")),
    ("baecker",      ("DM Serif Display", "Inter")),
    ("konditor",     ("DM Serif Display", "Inter")),
    ("metzger",      ("DM Serif Display", "Inter")),
    # Fahrzeug & Metall — technisch-stark
    ("autohaus",     ("Archivo", "Inter")),
    ("kfz",          ("Archivo", "Inter")),
    ("auto",         ("Archivo", "Inter")),
    ("werkstatt",    ("Archivo", "Inter")),
    ("reifen",       ("Archivo", "Inter")),
    ("motorrad",     ("Archivo", "Inter")),
    ("metallbau",    ("Space Grotesk", "Inter")),
    ("schlosser",    ("Space Grotesk", "Inter")),
    ("stahl",        ("Space Grotesk", "Inter")),
    ("elektr",       ("Space Grotesk", "Inter")),
    # Dienstleistung / IT
    ("edv",          ("Space Grotesk", "Inter")),
    ("elektronik",   ("Space Grotesk", "Inter")),
    ("logistik",     ("Archivo", "Inter")),
    ("transport",    ("Archivo", "Inter")),
    ("umzug",        ("Archivo", "Inter")),
]


def font_pairing(branche: str) -> "tuple[str, str]":
    """(Display, Body)-Pairing zur Branche; sonst der bewährte Fraunces/Inter-Default."""
    low = (branche or "").lower()
    for key, pair in _PAIRS:
        if key in low:
            return pair
    return _DEFAULT_PAIR


def fonts_href(display: str, body: str) -> str:
    """Google-Fonts-css2-Link für das Pairing (Display + Body)."""
    specs = []
    for fam in (display, body):
        spec = _FAMILY_SPEC.get(fam)
        if spec and spec not in specs:
            specs.append(spec)
    if not specs:
        specs = [_FAMILY_SPEC["Fraunces"], _FAMILY_SPEC["Inter"]]
    return "https://fonts.googleapis.com/css2?" + "&".join(f"family={s}" for s in specs) + "&display=swap"


# ── tokens.css bauen + einbinden ───────────────────────────────────────────────

# Selektoren, die in der Basis-Vorlage die Display-Schrift (früher Fraunces) tragen.
_DISPLAY_SELECTORS = ("h1,h2,h3,.brand,.section-t,.team-t,.band-t,.hr-title,.hr-result-val")

_BODY_FALLBACK = 'system-ui,-apple-system,"Segoe UI",sans-serif'
_DISPLAY_FALLBACK = '"Iowan Old Style",Georgia,serif'


def build_tokens_css(accent: str, branche: str) -> "tuple[str, dict]":
    """Erzeugt den vollständigen tokens.css-Inhalt (Palette + Fonts) für eine Seite.
    Gibt (css_text, info) zurück; info enthält die gewählten Werte fürs Logging/content."""
    pal = derive_palette(accent)
    display, body = font_pairing(branche)
    href = fonts_href(display, body)
    css = f"""/* tokens.css — LOKALE taste-Stufe (design_tokens.py), 0 Claude-Tokens.
   Lädt NACH style.css und überschreibt Palette + Fonts markengerecht. */
@import url('{href}');
:root{{
  --accent:{pal['accent']};
  --accent-dark:{pal['accent_dark']};
  --bg:{pal['bg']};
  --surface:{pal['surface']};
  --ink:{pal['ink']};
  --ink-soft:{pal['ink_soft']};
  --line:{pal['line']};
}}
body{{font-family:"{body}",{_BODY_FALLBACK}}}
{_DISPLAY_SELECTORS}{{font-family:"{display}",{_DISPLAY_FALLBACK}}}
.btn{{background:var(--accent)}}
.btn:hover{{background:var(--accent-dark)}}
"""
    info = {"palette": pal, "font_display": display, "font_body": body, "fonts_href": href}
    return css, info


_LINK_TAG = '<link rel="stylesheet" href="{% static \'css/tokens.css\' %}">'


def _ensure_link_in_template(folder: Path) -> None:
    """Fügt den tokens.css-Link idempotent NACH dem style.css-Link ins Template ein
    (auch bei bereits gebauten Seiten). Ändert sonst nichts am Template."""
    tpl = folder / "templates" / "index.html"
    try:
        html = tpl.read_text(encoding="utf-8")
    except Exception:
        return
    if "css/tokens.css" in html:
        return
    # Nach dem style.css-Link einsetzen (robust gegen Whitespace).
    m = re.search(r"<link[^>]+css/style\.css[^>]*>", html)
    if not m:
        return
    insert_at = m.end()
    html = html[:insert_at] + "\n  " + _LINK_TAG + html[insert_at:]
    try:
        tpl.write_text(html, encoding="utf-8")
    except Exception:
        pass


def apply(folder: "str | Path", content: dict, branche: str = "") -> dict:
    """Schreibt static/css/tokens.css aus Akzent+Branche und bindet sie ins Template ein.
    Aktualisiert `content` (font_*, taste_applied) und gibt es zurück. Best-effort, lokal.
    `content` wird vom Aufrufer gespeichert (hier NICHT geschrieben, um atomar zu bleiben)."""
    folder = Path(folder)
    accent = (content.get("akzent") or "").strip() or "#1f6f54"
    branche = (branche or content.get("branche") or "").strip()
    css, info = build_tokens_css(accent, branche)
    try:
        dst = folder / "static" / "css" / "tokens.css"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(css, encoding="utf-8")
    except Exception:
        return content
    _ensure_link_in_template(folder)
    content["font_display"] = info["font_display"]
    content["font_body"] = info["font_body"]
    content["taste_applied"] = True
    return content


if __name__ == "__main__":                      # Mini-Selbsttest (keine Abhängigkeiten)
    for acc, br in [("#c8102e", "dachdecker"), ("#1571a8", "zahnarzt"),
                    ("#243b66", "rechtsanwalt"), ("#a83279", "friseur"),
                    ("#37474f", "autohaus")]:
        css, info = build_tokens_css(acc, br)
        pal = info["palette"]
        print(f"{br:14s} accent={pal['accent']} bg={pal['bg']} ink={pal['ink']} "
              f"contrast(ink/bg)={_contrast(pal['ink'], pal['bg']):.1f} "
              f"fonts={info['font_display']}/{info['font_body']}")
