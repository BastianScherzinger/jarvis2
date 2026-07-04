"""
overnight_makeover.py — Mehrstufiges Skill-Makeover für gebaute Landing-Pages.

Statt nur content.json-Texte zu ändern (das alte website_improve.enrich), fährt diese
Pipeline eine Seite durch 7 aufeinanderfolgende, ABSCHNITTS-orientierte Stufen — Hero,
Beschreibung & Dienstleistungen, Über uns, Kontakt-Bereich, Kontakt-Formular, Komplett-
Design (taste) und QA + Recht (Datenschutz/AGB/Impressum) — jede mit dem passenden echten
Skill (ui-ux-pro-max / design-taste-frontend / design-pro). Der HEADLESS Claude Code
(`claude_coder`) baut dabei wirklich templates/index.html + static/css/style.css um.

WICHTIG (Fix 24.06.2026): Der Stufen-Prompt wird claude_coder über STDIN übergeben, nicht
als argv — sonst verstümmelt cmd.exe den langen Prompt (content.json-Dump mit " & < > |),
Claude sieht nur einen Torso und fragt konversationell zurück statt zu editieren (das war
die Ursache, warum jede Seite bei „Stufe 1" hing und nichts verbessert wurde).

Pro Stufe:
  1. Standard-Kontextblock (Fakten zu genau diesem Lead/dieser Seite) + Master-Prompt + Skill
  2. claude_coder.run_prompt(...)  → Snapshot + Render-Gate + Rollback (in claude_coder)
  3. Erfolg → Stufe in content.json["makeover_stages"] markieren (resume-fähig)
  4. Git-Commit (sauberer Rollback-Punkt + Verlauf)
  5. Activity-Feed + Kosten-Tracking (in claude_coder)

Der eigentliche Deploy (einmal, am Ende) und die Discord-Freigabe laufen im
Aufrufer (website_builder._run_makeover) bzw. über finalize_review().
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import claude_coder
import claude_limit
import logger

# Modell für die Stufen — headless-Claude-Alias ('sonnet'/'opus') oder volle ID.
# Sonnet = starkes Design bei moderaten Kosten; per .env auf 'opus' anhebbar.
_MODEL = os.environ.get("JARVIS_MAKEOVER_MODEL", "sonnet").strip()
# Günstigeres Modell für rein MECHANISCHE Stufen ohne kreative Design-Tiefe (Token-Sparen
# ohne Qualitätsverlust): die qa_recht-Stufe rendert nur bereits fertige Rechtstexte +
# macht Responsive-/Link-QA. Haiku reicht dafür. Per .env auf '' = wie _MODEL setzbar.
_MODEL_LITE = (os.environ.get("JARVIS_MAKEOVER_MODEL_LITE", "haiku").strip() or _MODEL)

# Bei erschöpftem Claude-Session-Limit meldet der Makeover das Limit jetzt SCHNELL zurück
# (Default 0 interne Wartezyklen) — der Auto-Builder orchestriert dann: erst ein bisschen
# ChatGPT (Hero-Bilder), und sind BEIDE leer, schaltet er ab und startet nach einer Wartezeit
# automatisch neu (auto_builder._handle_exhaustion). Wer den alten Weg will (Makeover wartet
# selbst), setzt JARVIS_MAKEOVER_LIMIT_RETRIES>0.
_LIMIT_RETRIES = int(os.environ.get("JARVIS_MAKEOVER_LIMIT_RETRIES", "0") or "0")
_LIMIT_WAIT    = int(os.environ.get("JARVIS_MAKEOVER_LIMIT_WAIT", "3600") or "3600")

# Interner CLI-Fehler (claude_coder meldet cli_error=True, z.B. 'error_during_execution' — der
# headless-Prozess bricht mitten im Lauf ab, meist ein kurzer API-Aussetzer, KEIN Session-Limit).
# Kurze, schnelle Retries statt der stundenlangen Limit-Pause: 2× nach je 20s, dann aufgeben und
# zur nächsten Stufe weiterziehen (die Stufe bleibt offen und wird beim nächsten Makeover-Lauf
# der Seite erneut versucht — s. _pick_improve_target/_makeover_stuck in auto_builder.py).
_CLI_ERROR_RETRIES = int(os.environ.get("JARVIS_MAKEOVER_CLI_RETRIES", "2") or "2")
_CLI_ERROR_WAIT    = int(os.environ.get("JARVIS_MAKEOVER_CLI_WAIT", "20") or "20")


# ── Die 3 Makeover-Stufen ───────────────────────────────────────────────────────
# TOKEN-DISZIPLIN (seit 26.06.2026): Jede Stufe ist EIN eigener headless-Claude-Lauf, der den
# referenzierten Skill + System-Prompt + Kontext NEU lädt. 7 Stufen = 7× dieser Fix-Overhead.
# Zusammengelegt auf 3 Stufen → nur noch 3× Overhead, und DURCHGEHEND der eine kompakte Skill
# «premium-landing» (~12 KB) statt zusätzlich «design-taste-frontend» (88 KB). Da die Basis-
# Vorlage bereits alle Sektionen rendert und die Inhalte VOR dem Makeover lokal (Ollama) in
# content.json stehen, arrangiert/gestaltet Claude nur noch — das spart massiv Tokens (Ziel:
# ≥5 Seiten pro Claude-Session). taste-Tiefe ist in «premium-landing» destilliert; wer den
# vollen 88-KB-taste-Pass zurück will, setzt JARVIS_MAKEOVER_DESIGN_SKILL=design-taste-frontend.
_TASTE   = "design-taste-frontend"
_LANDING = "premium-landing"
_DESIGN_SKILL = (os.environ.get("JARVIS_MAKEOVER_DESIGN_SKILL") or _LANDING).strip() or _LANDING
# Die EINE Claude-Politur nutzt standardmäßig das VOLLE taste-Skill (Sirs Wunsch „mehr /taste");
# es ist der einzige Claude-Schritt → die zusätzliche Token-Last fällt nur einmal je Seite an.
# Per JARVIS_POLITUR_SKILL auf 'premium-landing' (token-ärmer) umschaltbar.
_POLITUR_SKILL = (os.environ.get("JARVIS_POLITUR_SKILL") or _TASTE).strip() or _TASTE

# ── Makeover-Engine (Token-Disziplin, Stand 26.06.2026) ─────────────────────────
# Die Basis-Vorlage rendert alle Blöcke bereits aus content.json (Templates = 0 Tokens) und
# `design_tokens.py` leitet Farbwelt + Font-Pairing LOKAL ab (taste = 0 Tokens). Der teure
# Headless-Claude-Voll-Pass ist damit für Struktur+Design überflüssig. Engine wählt, wie viel
# Claude noch mitmacht:
#   lokal   — NUR die lokale Stufe (Templates + Farben/Fonts + Bilder). 0 Claude-Tokens.
#   hybrid  — lokal + EINE dünne, eng begrenzte Claude-Politur (Feinschliff). Standard.
#   claude  — der alte Voll-Pass (STAGES_ONEPASS/STAGES_MULTI). Teuer, nur per .env.
_ENGINE = (os.environ.get("JARVIS_MAKEOVER_ENGINE") or "hybrid").strip().lower()
if _ENGINE not in ("lokal", "local", "hybrid", "claude"):
    _ENGINE = "hybrid"

# Makeover-Struktur-Version. Wird sie erhöht (neue/umgebaute STAGES), behandelt der Builder
# bereits „fertige" Seiten als komplett offen und makeovert sie mit dem neuen Bauplan neu.
# 3 = Umstellung von 7 auf 3 Stufen (heute gebaute Seiten laufen einmal neu durch).
# 5 = bessere Branchenfarben + Hero-Szenen + Lead-Foto-Bewertung → heutige Seiten laufen neu durch.
# 6 = Hero: Headline LINKS + Kostenrechner-Karte rechts + Bild ohne Text + frisches Higgsfield-Hero.
# 7 = LOKALE Taste-Stufe (design_tokens: Palette+Fonts) + dünne Claude-Politur statt Voll-Pass.
_MAKEOVER_VERSION = 7

STAGES_MULTI: list[dict] = [
    {
        "key": "aufbau", "label": "Aufbau: Hero, Sektionen, Kontakt & Formular", "skill": _LANDING,
        "max_turns": 75,             # ganze Struktur in EINEM Lauf → etwas mehr Runden erlaubt
        "task": (
            "Baue die GESAMTE Seitenstruktur in EINEM Durchgang aus dem bereits in content.json "
            "vorbefüllten Inhalt (leistungen/ueber_text/faq/trust + Lead-Daten). Die Basis-Vorlage "
            "rendert die Sektionen schon — deine Aufgabe ist sie betriebsgenau, vollständig und "
            "premium zu machen. NICHT Texte neu erfinden, vorhandene 1:1 übernehmen.\n"
            "1) HERO (Above-the-fold): Hero-Bild (content.hero_image, von Higgsfield) als Hintergrund "
            "— es enthält NIEMALS Text/Logos, alle Texte sind HTML-Overlay über einem Scrim/Gradient. "
            "Eyebrow (Branche·Stadt), kraftvolle Headline + Subline, Button-Reihe: primärer CTA, "
            "WhatsApp (https://wa.me/<Tel nur Ziffern, 49 statt führender 0>), E-Mail (mailto:), "
            "Anruf (tel:); darunter dezente Vertrauenssignale.\n"
            "2) LEISTUNGEN: content.leistungen als sauberes Karten-Grid (Titel, Nutzen-Text, "
            "konsistentes Inline-SVG-Icon, KEINE Emojis) + FAQ-Sektion aus content.faq.\n"
            "3) KONTAKT-BAND zwischen Leistungen und Über uns: Akzent-Streifen mit WhatsApp- + "
            "Anruf-Button (zweiter Conversion-Punkt).\n"
            "4) ÜBER UNS: content.ueber_text + content.trust übernehmen; links Platzhalter für das "
            "Inhaber-Foto (Label 'Inhaber'), darunter Team-Grid mit GENAU 4 Mitarbeiter-Platzhaltern "
            "(rundes Avatar + '[Name]'/'[Position]'), daneben Trust-/USP-Liste.\n"
            "5) KONTAKT: echte Telefonnummer (tel:), WhatsApp (wa.me), E-Mail (mailto:), Adresse; für "
            "die Karte content.maps_url verlinken (kein leeres OSM-iframe).\n"
            "6) KONTAKT-FORMULAR: Name/E-Mail/Telefon/Nachricht + Einwilligungs-Checkbox → Datenschutz; "
            "method=\"post\", {% csrf_token %}, korrekte input-Typen, required, sichtbare Labels, "
            "focus-visible, Touch-Ziele ≥ 44 px.\n"
            "Bearbeite templates/index.html + static/css/style.css wirklich; alle Bild-Slots als "
            "saubere Platzhalter, nie ein gebrochenes <img>."
        ),
    },
    {
        "key": "design", "label": "Komplett-Design (Farben, Fonts, Feinschliff)", "skill": _DESIGN_SKILL,
        "task": (
            "Großer DESIGN-DURCHGANG über die GESAMTE Seite. Ziel: sieht aus wie von einer "
            "preisgekrönten Agentur, seriös aber farbig-schlicht, nicht templated/KI-generiert. "
            "Wähle eine stimmige Farbwelt um die Akzentfarbe + leicht getönte Neutrals als CSS-Tokens "
            "(--accent --bg --surface --ink --muted --line --ring), WCAG-AA-Kontraste. Wähle ein "
            "charakterstarkes, passendes Display-/Body-Font-Pairing (Google Fonts) und eine fluide "
            "Typo-Skala mit clamp(). Feste Spacing-Skala (4/8/12/16/24/32/48/72), rhythmischer "
            "Weißraum, konsistente Radien/Stroke-Breiten, WEICHE mehrschichtige Schatten (kein harter "
            "Glow), ein Icon-Set (Inline-SVG). Dezente, performante Motion (nur transform/opacity, "
            "150–400 ms, ease-out; prefers-reduced-motion respektieren). Alle Zustände vollständig "
            "(hover, focus-visible, active, disabled). Weniger, aber besser — entferne alles Billige/"
            "KI-haft Wirkende. Bearbeite static/css/style.css + templates/index.html durchgreifend."
        ),
    },
    {
        "key": "qa_recht", "label": "QA, Datenschutz, AGB & Impressum", "skill": _LANDING,
        "model": _MODEL_LITE,        # mechanisch (Rechtstexte rendern + QA) → günstiges Modell
        "task": (
            "ABSCHLUSS-DURCHGANG in zwei Teilen.\n"
            "1) RECHTLICHES: In content.json stehen bereits FERTIGE Texte in den Feldern "
            "`impressum`, `datenschutz` und `agb`. Erfinde KEINE neuen Texte und kürze sie nicht — "
            "RENDERE genau diese Texte als drei eigene, sauber gestaltete Unterseiten bzw. "
            "ausklappbare Abschnitte (Absätze/Zeilenumbrüche erhalten) und verlinke sie gut sichtbar "
            "UNTEN LINKS im Footer (Datenschutz · Impressum · AGB). Das Kontaktformular verweist auf "
            "die Datenschutzerklärung. (Falls die Felder ausnahmsweise fehlen: knappe DSGVO/DDG-"
            "konforme Standardtexte, fehlende Daten als «[bitte ergänzen]».) Der gesamte UNTERE "
            "BEREICH (Footer + Rechtsabschnitte) zeigt ECHTE Texte und echte Betriebsdaten — KEINE "
            "Blindtexte/Platzhalter. Behalte ausserdem den dezenten Credit «Erstellt von WVM-IT» "
            "(Felder wvm_url/wvm_name) + den Shop-Link (wvm_shop) im Footer sauber erhalten.\n"
            "2) QA / RESPONSIVE: Perfekte Mobil-Darstellung (echte Breakpoints), ein mobiler "
            "Sticky-Anruf/WhatsApp-Balken, Touch-Ziele ≥ 44 px, keine horizontalen Überläufe, kein "
            "CLS, alle Links/Buttons/Anker funktionieren, SEO-Grundstruktur (title, meta description, "
            "Überschriften-Hierarchie, alt-Texte) intakt. Es MUSS `python manage.py check` "
            "fehlerfrei sein und das Template ohne Fehler rendern."
        ),
    },
]

# ── EIN-PASS-Makeover (Standard) ─────────────────────────────────────────────────
# Der gesamte Makeover in EINEM headless-Claude-Lauf: Skill + System-Prompt + Kontext werden
# nur EINMAL geladen (statt 3×). Mit lokal vorgefülltem content.json + fertiger Basis-Vorlage
# ist das der mit Abstand günstigste Weg (Ziel: ≥5 Seiten/Session). Per JARVIS_MAKEOVER_ONEPASS=0
# zurück auf die 3 getrennten Stufen (mehr Kontrolle/Qualität, mehr Tokens).
STAGES_ONEPASS: list[dict] = [
    {
        "key": "makeover", "label": "Komplett-Makeover (ein Durchgang)", "skill": _DESIGN_SKILL,
        "max_turns": 130, "timeout": 1800,
        "task": (
            "Mach die GESAMTE Seite in EINEM Durchgang fertig — Struktur, Inhalt, Design und Recht. "
            "Inhalte stehen BEREITS in content.json (leistungen/ueber_text/faq/trust + Lead-Daten + "
            "Rechtstexte); übernimm sie 1:1, schreibe sie NICHT neu, dein Fokus ist Layout + Design. "
            "Die Basis-Vorlage rendert die Sektionen schon — mach sie betriebsgenau und premium.\n\n"
            "A) AUFBAU/SEKTIONEN:\n"
            "1) HERO — ZWEI Spalten: content.hero_image als Hintergrund (enthält NIE Text/Logos; alle "
            "Texte sind HTML-Overlay über Scrim/Gradient).\n"
            "   • LINKE Spalte (Text), strikt LINKSBÜNDIG — NIEMALS zentriert: Eyebrow (Branche·Stadt), "
            "Headline + Subline, Button-Reihe (primärer CTA, WhatsApp https://wa.me/<Tel nur Ziffern, 49 "
            "statt führender 0>, E-Mail mailto:, Anruf tel:), dezente Vertrauenssignale.\n"
            "   • RECHTE Spalte: eine KOSTENRECHNER-Karte (helle Karte über dem Bild). Sie MUSS gebaut "
            "werden und funktionieren: <select> der Posten aus content.rechner.posten, ein Umfang-"
            "Schieber (klein/mittel/groß) und ein Ergebnisfeld 'ca. AB – BIS €' + CTA-Button zu #kontakt. "
            "Daten via Django {{ c.rechner|json_script:'rechner-data' }} ausgeben und die mitgelieferte "
            "Datei static/js/kostenrechner.js per <script src defer> einbinden (NICHT neu erfinden — sie "
            "liest #rechner-data und rechnet). Auf Mobil stapeln (Text oben, Rechner darunter, Touch ≥ 44 px).\n"
            "2) LEISTUNGEN: content.leistungen als Karten-Grid (Inline-SVG-Icons, KEINE Emojis) + "
            "FAQ-Sektion aus content.faq.\n"
            "3) KONTAKT-BAND (Akzent-Streifen, WhatsApp + Anruf) zwischen Leistungen und Über uns.\n"
            "4) ÜBER UNS: content.ueber_text + content.trust; Platzhalter fürs Inhaber-Foto + Team-"
            "Grid mit GENAU 4 Mitarbeiter-Platzhaltern.\n"
            "5) KONTAKT: Telefon (tel:), WhatsApp (wa.me), E-Mail (mailto:), Adresse; echte Karte "
            "über content.map_embed (OSM-iframe mit Koordinaten) bzw. content.maps_url-Link.\n"
            "6) KONTAKT-FORMULAR: Name/E-Mail/Telefon/Nachricht + Einwilligungs-Checkbox → Datenschutz; "
            "method=\"post\", {% csrf_token %}, required, sichtbare Labels, focus-visible, Touch ≥ 44 px.\n\n"
            "B) DESIGN (durchgreifend): eine stimmige Farbwelt um die Akzentfarbe + getönte Neutrals "
            "als CSS-Tokens (--accent --bg --surface --ink --muted --line --ring), WCAG-AA. "
            "Charakterstarkes Display-/Body-Font-Pairing (Google Fonts), fluide Typo mit clamp(), "
            "feste Spacing-Skala, weiche mehrschichtige Schatten, ein Inline-SVG-Icon-Set, dezente "
            "Motion (transform/opacity, prefers-reduced-motion), alle Zustände (hover/focus-visible/"
            "active/disabled). Seriös, farbig-schlicht, NICHT templated/KI-haft.\n\n"
            "C) RECHT + QA: Rechtstexte aus content.json (impressum/datenschutz/agb) 1:1 rendern + "
            "UNTEN LINKS im Footer verlinken; Credit «Erstellt von WVM-IT» (wvm_url/wvm_name) + Shop-"
            "Link (wvm_shop) erhalten. Perfekt mobil (echte Breakpoints, Sticky-Anruf/WhatsApp, Touch "
            "≥ 44 px, keine Überläufe), SEO-Grundgerüst intakt. Am Ende MUSS das Template fehlerfrei "
            "rendern. KEINE Blindtexte/Platzhalter im sichtbaren Text.\n\n"
            "BILDER: Echte Lead-Fotos stehen in content.fotos (bereits nach Qualität sortiert — die "
            "ersten sind die besten) und ggf. content.about_image; baue sie sinnvoll ein (Galerie/"
            "Über-uns), KEINE Doppelung des Hero-Bilds. Sind nur SVG-Platzhalter vorhanden, lass sie.\n\n"
            "Arbeite EFFIZIENT (knappes Token-Budget): surgische Edits über eindeutige Anker/Selektoren, "
            "lies große Dateien NUR im betroffenen Ausschnitt (nie komplett für eine Kleinigkeit), bündle "
            "Änderungen je Datei in EINEM MultiEdit statt vieler Einzel-Edits, KEINE Probe-Renders, kein "
            "endloses Polishing — fertig, sobald es sauber rendert."
        ),
    },
]

# ── LOKALE Stufe + dünne Claude-Politur (Engine lokal/hybrid) ────────────────────
# Die lokale Stufe macht ALLES ohne Claude: Templates rendern bereits (Vorlage), Farben/Fonts
# kommen aus design_tokens.py, Bilder werden lokal bewertet/platziert (in der Vorbereitung).
# `local: True` → run_makeover führt sie über _run_local_stage aus statt über claude_coder.
_STAGE_LOKAL: dict = {
    "key": "lokal", "local": True,
    "label": "Templates, Farben & Bilder (lokal, 0 Tokens)",
}

# Die EINE dünne Claude-Politur: Die Seite ist bereits vollständig gebaut UND markengerecht
# gestaltet (Palette/Fonts via tokens.css). Claude darf NUR noch surgisch feinschleifen —
# knappes Budget (15 Runden, 10 Min), kein Neuaufbau, keine Farb-/Font-Umschreibung.
_STAGE_POLITUR: dict = {
    "key": "politur", "skill": _POLITUR_SKILL, "max_turns": 22, "timeout": 720,
    "label": "Feinschliff & Anordnung (Claude · taste)",
    "optional": True,        # Politur ist Kür — sie darf die Discord-Freigabe NIE blockieren.
    "task": (
        "Die Seite ist BEREITS vollständig gebaut und markengerecht gestaltet: alle Sektionen "
        "rendern aus content.json, und die Farbwelt + das Font-Pairing stehen schon FERTIG in "
        "static/css/tokens.css (lokal erzeugt, lädt nach style.css). Behalte diese Farb-/Font-"
        "Tokens (schreibe Palette/Fonts NICHT um). Wende jetzt das DESIGN-/taste-Skill an und hebe "
        "die Seite mit gezielten Edits auf Premium-Agentur-Niveau — Schwerpunkt KOMPOSITION & "
        "ANORDNUNG (kein Neuaufbau, keine inhaltliche Neutextung):\n\n"
        "1) HERO besser sortieren (Above-the-fold ist das Wichtigste):\n"
        "   • Zwei klar getrennte Spalten: LINKS der Text-Block (Eyebrow → kraftvolle Headline → "
        "Subline → Button-Reihe → dezente Trust-Signale), strikt LINKSBÜNDIG, mit ruhiger "
        "vertikaler Rhythmik (klare Abstände zwischen Eyebrow/H1/Subline/CTAs).\n"
        "   • RECHTS die Kostenrechner-Karte sauber ausgerichtet (gleiche optische Höhe/Mitte wie "
        "der Textblock), klare Felder, gut sichtbarer CTA. Karte hebt sich mit weichem Schatten "
        "vom Hero-Bild ab (lesbarer Scrim/Gradient hinter dem Text).\n"
        "   • Hero-Höhe, Innenabstände und max-Breite so, dass nichts gedrängt wirkt; auf Mobil "
        "sauber stapeln (Text oben, Rechner darunter, Touch-Ziele ≥ 44 px).\n\n"
        "2) GESAMTE SEITEN-ANORDNUNG & Rhythmus:\n"
        "   • Einheitliche, großzügige Sektions-Abstände (konsistente vertikale Skala), klare "
        "visuelle Hierarchie (Section-Titel → Lead → Inhalt), abwechselnde Hintergründe/Bänder "
        "für angenehmen Lesefluss.\n"
        "   • Karten-/Grid-Ausrichtung sauber (gleiche Höhen, gleichmäßige Gaps), Galerie & Team "
        "ordentlich gerastert, Kontakt + Formular nebeneinander ausbalanciert, Footer aufgeräumt.\n"
        "   • Mehr 'taste': feinere Typo-Skala (clamp), bessere Weißraum-Verteilung, konsistente "
        "Radien/Schatten, ruhige Mikro-Interaktionen (hover/focus-visible) — weniger, aber besser.\n\n"
        "3) Offensichtliche Fehler beheben: Überläufe, gebrochene <img>, schiefe Buttons, doppelte/"
        "leere Blöcke, Kontraste (WCAG-AA).\n\n"
        "Arbeite gezielt an static/css/style.css + templates/index.html (surgische Edits über klare "
        "Anker, je Datei in wenigen MultiEdits). KEINE neuen Sektionen erfinden, KEINE Probe-Renders, "
        "kein endloses Polishing. Am Ende MUSS das Template fehlerfrei rendern. Schließe mit genau "
        "einem Satz, was du verbessert hast."
    ),
}

# Standard: Ein-Pass. JARVIS_MAKEOVER_ONEPASS=0 → die 3 getrennten Stufen (nur Engine 'claude').
_ONEPASS = (os.environ.get("JARVIS_MAKEOVER_ONEPASS", "1") or "1").strip().lower() not in (
    "0", "false", "no", "nein", "off")

# Engine-abhängige Stufenliste.
if _ENGINE in ("lokal", "local"):
    STAGES: list[dict] = [_STAGE_LOKAL]
elif _ENGINE == "claude":
    STAGES = STAGES_ONEPASS if _ONEPASS else STAGES_MULTI
else:                                        # hybrid (Standard)
    STAGES = [_STAGE_LOKAL, _STAGE_POLITUR]

_ALL_KEYS = {s["key"] for s in STAGES}


# ── content.json Helfer ─────────────────────────────────────────────────────────

def _read_content(folder: Path) -> dict:
    p = Path(folder) / "content.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        # Korruptes JSON sichtbar machen (statt still 0 → Datenverlust). Defektes File sichern.
        try:
            logger.error("Makeover", f"content.json defekt ({folder.name}): {e} — wird neu aufgebaut.")
            p.replace(p.with_suffix(".json.broken"))
        except Exception:
            pass
        return {}
    except Exception:
        return {}


def _write_content(folder: Path, content: dict) -> None:
    """Atomar schreiben: erst in .tmp, dann os.replace — ein Crash mitten im Schreiben kann
    content.json so nie korrumpieren (Datenverlust-Schutz im Dauerbetrieb)."""
    try:
        p = Path(folder) / "content.json"
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass


def _done_keys(folder: Path) -> set:
    """Erledigte Stufen einer Seite — UNTER Berücksichtigung der Struktur-Version. Wurde die
    Seite mit einer älteren _MAKEOVER_VERSION makeovert, gilt sie als KOMPLETT offen (leere
    Menge), damit der neue Bauplan voll durchläuft (Neu-Makeover heute gebauter Seiten)."""
    c = _read_content(Path(folder))
    if int(c.get("makeover_version") or 0) < _MAKEOVER_VERSION:
        return set()
    return set(c.get("makeover_stages") or [])


def _mark_done(folder: Path, key: str) -> None:
    """Markiert eine Stufe als erledigt (frisch lesen — die KI hat content.json verändert) und
    schreibt die aktuelle Struktur-Version fest."""
    content = _read_content(folder)
    done = list(content.get("makeover_stages") or [])
    # Alte Version → vorherige (zum alten Bauplan gehörende) Markierungen verwerfen.
    if int(content.get("makeover_version") or 0) < _MAKEOVER_VERSION:
        done = []
    if key not in done:
        done.append(key)
    content["makeover_stages"] = done
    content["makeover_version"] = _MAKEOVER_VERSION
    try:
        import site_meta
        content["site_version"] = site_meta.SITE_VERSION
    except Exception:
        pass
    _write_content(folder, content)


def _fingerprint(folder: Path) -> str:
    """Hash der gestaltungsrelevanten Dateien — um zu erkennen, ob eine Stufe WIRKLICH
    etwas geändert hat (Schutz vor 'ok' ohne Änderung, z.B. bei Session-Limit/Rückfrage)."""
    import hashlib
    h = hashlib.md5()
    for rel in ("templates/index.html", "static/css/style.css", "content.json"):
        p = Path(folder) / rel
        if p.is_file():
            h.update(p.read_bytes())
    jsdir = Path(folder) / "static" / "js"
    if jsdir.is_dir():
        for f in sorted(jsdir.glob("*.js")):
            try:
                h.update(f.read_bytes())
            except Exception:
                pass
    return h.hexdigest()


def _looks_limited(text: str) -> bool:
    """Erkennt eine Claude-Code-Limit-/Abbruch-Meldung im Ergebnis-Text (Session ODER Weekly)."""
    t = (text or "").lower()
    return any(s in t for s in (
        "session limit", "usage limit", "rate limit", "hit your limit", "weekly limit",
        "weekly usage", "reached your limit", "resets", "quota", "try again later"))


def _limit_scope(text: str) -> str:
    """'weekly' wenn die Limit-Meldung nach Wochenlimit aussieht, sonst 'session'."""
    return "weekly" if "weekly" in (text or "").lower() else "session"


def open_stages(folder: "str | Path") -> int:
    """Anzahl noch offener Makeover-Stufen einer Seite (für die Auswahl im Night-Builder).
    Berücksichtigt die Struktur-Version: ältere Seiten zählen als voll offen."""
    return len(_ALL_KEYS - _done_keys(Path(folder)))


def all_done(folder: "str | Path") -> bool:
    return open_stages(folder) == 0


def _required_keys() -> set:
    """Keys der PFLICHT-Stufen (nicht-optionale). Die optionale Claude-Politur zählt nicht."""
    return {s["key"] for s in STAGES if not s.get("optional")}


def open_required_stages(folder: "str | Path") -> int:
    return len(_required_keys() - _done_keys(Path(folder)))


def review_ready(folder: "str | Path") -> bool:
    """True, sobald alle PFLICHT-Stufen fertig sind — die Seite ist dann vollständig &
    deploybar. Die optionale Feinschliff-Stufe (Claude) darf die Discord-Freigabe (und damit
    die Angebots-Mail) NICHT blockieren: ist sie am Limit hängen geblieben, soll die Seite
    trotzdem zur Freigabe gehen."""
    return open_required_stages(folder) == 0


# ── Git ──────────────────────────────────────────────────────────────────────────

def _git_commit(folder: Path, message: str) -> None:
    """Commitet den aktuellen Stand als Rollback-Punkt. Initialisiert das Repo bei Bedarf.
    Best-effort — Fehler werden geschluckt (der finale Deploy pusht ohnehin alles)."""
    folder = Path(folder)

    def _run(args: list) -> int:
        try:
            return subprocess.run(["git", *args], cwd=str(folder),
                                  capture_output=True, text=True, timeout=60).returncode
        except Exception:
            return 1

    try:
        if not (folder / ".git").exists():
            _run(["init"])
            _run(["branch", "-M", "main"])
        _run(["add", "-A"])
        _run(["-c", "user.email=jarvis@local", "-c", "user.name=JARVIS",
              "commit", "-m", message])
    except Exception:
        pass


# ── Kontext + Prompt ──────────────────────────────────────────────────────────────

def _reset_dirty(folder: Path) -> None:
    """Verwirft uncommittete Änderungen (eine mittendrin abgebrochene Stufe) zurück zum
    letzten Stufen-Commit — für einen sauberen Resume nach Programm-Absturz/Schließen.
    Betrifft nur getrackte Dateien (index.html/style.css/content.json etc.)."""
    folder = Path(folder)
    if not (folder / ".git").exists():
        return

    def _run(args):
        try:
            return subprocess.run(["git", *args], cwd=str(folder),
                                  capture_output=True, text=True, timeout=60)
        except Exception:
            return None

    st = _run(["status", "--porcelain"])
    if st and (st.stdout or "").strip():
        _run(["reset", "--hard"])
        logger.info("Makeover", f"Resume: uncommittete Halbstufe verworfen ({folder.name})")


def _doc_details(folder: Path, meta: dict) -> dict:
    """Zusätzliche dokumentierte Fakten zu Seite/Lead aus den DBs (best-effort) — die
    „gesammelten Details", auf die jede Stufe zurückgreift. Stilles Scheitern erlaubt."""
    out: dict = {}
    try:
        import db_websites
        row = db_websites.get_by_folder(str(folder)) or {}
        for k in ("kontakt_email", "ansprechpartner", "live_url", "repo_url"):
            if row.get(k):
                out[k] = row[k]
        lead_id = row.get("lead_id")
        if lead_id:
            import db_evaluated
            # lead_id ist i.d.R. die db_evaluated-id; robust auch raw_id versuchen.
            lead = (db_evaluated.get_by_id(int(lead_id))
                    or db_evaluated.get_by_raw_id(int(lead_id)) or {})
            for k in ("beschreibung", "firmengroesse", "pitch_hook", "potenzial_begruendung",
                      "adresse", "telefon", "email_adresse", "social_media", "bundesland",
                      "branche", "stadt", "ansprechpartner", "potenzial_euro"):
                if lead.get(k) and k not in out:
                    out[k] = lead[k]
    except Exception:
        pass
    return out


def _wa_number(tel: str) -> str:
    """Deutsche Telefonnummer → wa.me-Format (nur Ziffern, Ländervorwahl 49, ohne führende 0).
    Leerstring, wenn keine plausible Nummer vorliegt."""
    import re
    digits = re.sub(r"\D", "", tel or "")
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = "49" + digits[1:]
    elif not digits.startswith("49"):
        digits = "49" + digits
    return digits if len(digits) >= 8 else ""


def _context_block(folder: Path, meta: dict) -> str:
    """Kompakte, angereicherte Fakten zu Seite/Lead — bewusst OHNE content.json-Dump
    (Claude liest content.json selbst aus dem Ordner; das spart pro Stufe ~3,5 KB Tokens)."""
    c = _read_content(folder)
    d = _doc_details(folder, meta)

    def pick(*keys, default=""):
        for src in (meta, c, d):
            for k in keys:
                v = src.get(k)
                if v:
                    return v
        return default

    name = (meta.get("name") or c.get("site_name") or "Der Betrieb").strip()
    lines = [
        "BETRIEB (alle Inhalte müssen dazu passen — nichts erfinden):",
        f"- Name: {name}",
        f"- Branche: {pick('branche')}",
        f"- Stadt/Region: {pick('stadt')}{(' · ' + d['bundesland']) if d.get('bundesland') else ''}",
        f"- Adresse: {pick('adresse')}",
        f"- Telefon: {pick('telefon')}",
        f"- E-Mail: {pick('email', 'email_adresse', 'kontakt_email')}",
        f"- Ansprechpartner: {pick('ansprechpartner')}",
        f"- Akzentfarbe: {c.get('akzent') or '#c8102e'}",
    ]
    wa = _wa_number(pick('telefon'))
    if wa:
        lines.append(f"- WhatsApp-Link: https://wa.me/{wa} (für den WhatsApp-Button verwenden)")
    if d.get("beschreibung"):
        lines.append(f"- Beschreibung (Recherche): {str(d['beschreibung'])[:280]}")
    if d.get("pitch_hook"):
        lines.append(f"- Aufhänger: {str(d['pitch_hook'])[:180]}")
    lines.append("Die VOLLSTÄNDIGEN Inhalte stehen in content.json im Ordner — lies sie dort "
                 "direkt (sie sind hier bewusst nicht eingefügt, um Tokens zu sparen).")
    return "\n".join(lines)


def _build_stage_prompt(folder: Path, meta: dict, stage: dict, idx: int, total: int) -> str:
    context = _context_block(folder, meta)
    return (
        "Headless-Web-Editor im AKTUELLEN Ordner: fertige Django-Landing-Page, rendert aus "
        "content.json über templates/index.html + static/css/style.css (+ static/img, static/js). "
        f"Schritt {idx}/{total} eines Upgrades von Standard-Vorlage zu echter Premium-Seite "
        "(Top-Agentur-Niveau, nicht templated/KI-haft).\n\n"
        f"{context}\n\n"
        f"AUFGABE — {stage['label']}:\n{stage['task']}\n\n"
        f"WENDE DAS SKILL «{stage['skill']}» VOLLSTÄNDIG AN: lies es und setze sein "
        "Farb-Token-System (EINE Akzentfarbe + leicht getönte Neutrals als CSS-Variablen, "
        "WCAG-AA-Kontraste — keine verstreuten Hex-Werte), sein Font-Pairing und seine "
        "Spacing-/Radius-/Schatten-Skala konsequent über die ganze Sektion um. Farben, "
        "Schriften und Abstände sind nicht optional, sondern das Herz dieser Stufe.\n"
        "REGELN: Sofort autonom umsetzen, KEINE Rückfragen. content.json + templates/index.html + "
        "static/css/style.css bei Bedarf direkt aus dem Ordner lesen und WIRKLICH editieren (echtes "
        "Design, nicht nur Text). content.json bleibt valides JSON; hero_image/logo_image/fotos "
        "erhalten, vorhandene Keys nicht löschen. Deutsch, konkret, betriebsgenau — kein Geschwurbel "
        "(echte Lead-Daten; fehlende Bilder als saubere Platzhalter, nie ein gebrochenes <img>). "
        "Auf den Vorstufen AUFBAUEN, minimaler gezielter Diff. "
        "ARBEITE EFFIZIENT (Token-Budget): jede Datei höchstens EINMAL lesen, in wenigen gezielten "
        "Edits umsetzen, KEINE Endlos-Iterationen, keine unnötigen Probe-Renders. Am Ende MUSS das "
        "Template fehlerfrei rendern. Schließe mit genau einem Satz, was du geändert hast."
    )


# ── Session-Limit: warten & wiederholen ────────────────────────────────────────────

def _is_limit(res: dict, changed: bool) -> bool:
    """Session-/Usage-Limit erkannt? Nur wenn die Stufe NICHTS geändert hat und der Text
    (summary ODER reason) nach Limit aussieht."""
    if changed:
        return False
    return _looks_limited((res.get("summary") or "") + " " + (res.get("reason") or ""))


def _sleep_interruptible(seconds: int, stop, say=None, attempt: int = 0, total: int = 0,
                         pct: int = 50) -> bool:
    """Wartet `seconds`, bricht bei stop() sofort ab. Meldet die Restzeit ~alle 30 s — mit
    dem AKTUELLEN Stufen-Fortschritt (nicht 95/100, damit der Balken nicht „fertig" wirkt,
    während noch gewartet wird). True = volle Wartezeit abgelaufen, False = Abbruch."""
    end = time.time() + seconds
    while True:
        rem = end - time.time()
        if rem <= 0:
            return True
        if stop and stop():
            return False
        if say:
            mins = int(rem // 60) + (1 if int(rem) % 60 else 0)
            say(pct, f"⏳ Claude-Session-Limit — warte {mins} Min, dann Versuch {attempt}/{total}…")
        time.sleep(min(30.0, rem))


# ── Hauptlauf ─────────────────────────────────────────────────────────────────────

def _ensure_hero(folder: Path, meta: dict, say) -> bool:
    """Ersetzt das Hero-Bild EINMAL je Seite durch ein frisches, lead-angepasstes Bild über
    die konfigurierte Cloud-Engine (JARVIS_HERO_ENGINE, Default Higgsfield = Sirs Abo; OpenAI
    nur wenn explizit gewählt). So bauen die Design-Stufen auf dem hochwertigen Bild auf.
    Best-effort. Gibt True, wenn ein Bild erzeugt wurde."""
    try:
        import media_engine
    except Exception:
        return False
    content = _read_content(folder)
    if content.get("hero_source") in ("higgsfield", "higgsfield_mcp", "openai", "template"):
        return False                             # schon ein Cloud-/Vorlagen-Hero — nicht ersetzen
    if content.get("hero_custom"):
        return False                             # vom Inhaber hochgeladenes Hero nie ersetzen
    d = _doc_details(folder, meta)
    branche = meta.get("branche") or content.get("branche") or d.get("branche", "")
    # STUFE 1 zuerst LOKAL: passt eine branchengenaue Hero-Vorlage (ohne Text), diese nehmen —
    # spart ein Higgsfield-Bild (Tagesbudget) und ist sofort da. Nur sonst Cloud-Generierung.
    try:
        import hero_templates
        if hero_templates.apply(folder, branche, content):
            _write_content(folder, content)
            _git_commit(folder, f"Hero: Branchen-Vorlage ({content.get('hero_template','')})")
            try:
                logger.activity("Makeover", "Hero-Vorlage eingesetzt",
                                (meta.get("name") or folder.name), "🖼", "image")
            except Exception:
                pass
            if say:
                say(6, f"Branchen-Hero-Vorlage eingesetzt ({content.get('hero_template','')}).")
            return True
    except Exception:
        pass
    name    = meta.get("name") or content.get("site_name", "")
    stadt   = meta.get("stadt") or content.get("stadt") or d.get("stadt", "")
    beschr  = d.get("beschreibung") or content.get("ueber_text", "")
    prompt  = media_engine.hero_prompt_smart(branche=branche, name=name, stadt=stadt,
                                             beschreibung=beschr, akzent=content.get("akzent", ""),
                                             leistungen=content.get("leistungen"))
    try:
        say(6, f"Hero-Bild wird frisch erzeugt ({media_engine.hero_engine()})…")
        res = media_engine.generate_hero_cloud(
            prompt, output_dir=(folder / "static" / "img"),
            filename="hero.png", width=1536, height=1024, name=name)
        content = _read_content(folder)          # frisch lesen (kann sich geändert haben)
        content["hero_image"] = "/static/img/hero.png"
        content["hero_source"] = res.get("engine", "higgsfield")
        _write_content(folder, content)
        _git_commit(folder, f"Hero: frisches Bild ({content['hero_source']})")
        try:
            logger.activity("Makeover", f"Hero erneuert ({content['hero_source']})",
                            name or folder.name, "🖼", "image")
        except Exception:
            pass
        return True
    except Exception as e:
        logger.warn("Makeover", f"Hero-Refresh übersprungen: {type(e).__name__}: {str(e)[:120]}")
        return False


def _ensure_legal(folder: Path, meta: dict) -> None:
    """Schreibt deterministische Rechtstexte (Impressum/Datenschutz/AGB) in content.json,
    sofern noch nicht vorhanden — lokal generiert, 0 Claude-Tokens. Die QA-Stufe rendert sie
    danach nur noch + verlinkt sie. Best-effort."""
    try:
        import legal_pages
    except Exception:
        return
    content = _read_content(folder)
    if content.get("impressum") and content.get("datenschutz") and content.get("agb"):
        return
    d = _doc_details(folder, meta)
    src = {
        "name":  meta.get("name") or content.get("site_name") or "",
        "adresse": content.get("adresse") or d.get("adresse") or "",
        "telefon": content.get("telefon") or d.get("telefon") or "",
        "email": content.get("email") or d.get("email_adresse") or d.get("kontakt_email") or "",
        "ansprechpartner": content.get("ansprechpartner") or d.get("ansprechpartner") or "",
    }
    legal = legal_pages.build_all(src)
    for k, v in legal.items():
        content.setdefault(k, v)
    _write_content(folder, content)


def _ensure_geo(folder: Path, meta: dict) -> None:
    """Geocodet die Betriebsadresse EINMAL (Google Maps, Key in .env) → lat/lng in content.json,
    damit die Kontakt-Sektion eine echte eingebettete Karte (OSM, kein Key) zeigt. Best-effort;
    ohne Treffer bleibt der Maps-Suchlink. Idempotent (lat/lng schon da → nichts tun)."""
    content = _read_content(folder)
    if content.get("lat") and content.get("lng"):
        return
    adr = (content.get("adresse") or meta.get("adresse")
           or _doc_details(folder, meta).get("adresse") or "").strip()
    if not adr:
        return
    try:
        import agent_maps
        ll = agent_maps.geocode_latlng(adr)
    except Exception:
        ll = None
    if not ll:
        return
    content = _read_content(folder)
    content["lat"], content["lng"] = ll[0], ll[1]
    _write_content(folder, content)
    try:
        logger.info("Makeover", f"Adresse geocodet ({folder.name}): {ll[0]:.4f}, {ll[1]:.4f}")
    except Exception:
        pass


def _content_model() -> str:
    """Bestes lokales Modell für deutsche Prosa-Inhalte — GPU-/VRAM-bewusst (meidet das winzige
    Coder-Modell, nutzt z.B. qwen2.5:7b/14b auf einer GPU). '' = ask_ollama-Default. Per
    JARVIS_CONTENT_MODEL fest wählbar."""
    m = (os.environ.get("JARVIS_CONTENT_MODEL") or "").strip()
    if m:
        return m
    try:
        from scrapers._http import best_chat_model
        return best_chat_model() or ""
    except Exception:
        return ""


def _grade_fotos_once(folder: Path, meta: dict, say=None) -> None:
    """Bewertet die Lead-Fotos der Seite LOKAL (Logos/Karten/unscharfe verwerfen) und ordnet
    Galerie + Über-uns-Bild neu — auch für Seiten, die vor der Bewertung gebaut wurden.
    Lässt ein bereits gesetztes Hero unangetastet. Idempotent über content['fotos_graded']."""
    try:
        content = _read_content(folder)
    except Exception:
        return
    if content.get("fotos_graded"):
        return
    fotos = content.get("fotos") or []
    try:
        import lead_images
        branche = meta.get("branche") or content.get("branche") or ""
        arr = lead_images.evaluate_and_arrange(fotos, folder, branche)
        ev = arr.get("evaluated") or []
        if ev:                              # es gab echte Rasterfotos → Ergebnis übernehmen
            content["fotos"] = arr.get("gallery") or []
            about = arr.get("about")
            cur_about = (content.get("about_image") or "")
            if about and (not cur_about or cur_about.endswith("about_ph.svg")):
                content["about_image"] = about
            if arr.get("captions"):
                content["foto_captions"] = arr["captions"]
            if say:
                gut = sum(1 for r in ev if r.get("ok"))
                say(6, f"{gut}/{len(ev)} Lead-Foto(s) lokal bewertet & eingeordnet.")
        content["fotos_graded"] = True
        _write_content(folder, content)
    except Exception:
        pass


def _ensure_akzent(folder: Path, meta: dict, say=None) -> None:
    """Zieht die Akzentfarbe einer Seite auf den branchengerechten Wert nach — aber NUR, wenn
    sie leer ist oder dem alten pauschalen Default-Rot (#c8102e) entspricht. So bekommen Seiten,
    die früher mit der generischen Farbe gebaut wurden, beim Verbessern eine passende Farbe,
    ohne bewusst gesetzte/branchenrichtige Farben zu überschreiben."""
    try:
        content = _read_content(folder)
    except Exception:
        return
    cur = (content.get("akzent") or "").strip().lower()
    if cur and cur != "#c8102e":
        return                                    # bereits eine passende Farbe → nicht anfassen
    branche = meta.get("branche") or content.get("branche") or ""
    try:
        import website_builder
        akz = website_builder.akzent_for(branche)
    except Exception:
        return
    if akz and akz.lower() != cur:
        content["akzent"] = akz
        _write_content(folder, content)
        if say:
            say(5, f"Akzentfarbe an Branche angepasst ({akz}).")


_VORLAGE_RECHNER_JS = Path(__file__).resolve().parent / "vorlage_landing" / "static" / "js" / "kostenrechner.js"


def _ensure_rechner(folder: Path, meta: dict, say=None) -> None:
    """Stellt sicher, dass die Seite einen branchengerechten Kostenrechner-Datensatz
    (content.rechner) UND die kostenrechner.js besitzt — auch ältere Seiten, die ohne den
    Hero-Rechner gebaut wurden. Idempotent."""
    try:
        content = _read_content(folder)
    except Exception:
        return
    rech = content.get("rechner")
    if not (isinstance(rech, dict) and rech.get("posten")):
        try:
            import website_builder
            branche = meta.get("branche") or content.get("branche") or ""
            content["rechner"] = website_builder.rechner_for(branche, content.get("leistungen"))
            _write_content(folder, content)
            if say:
                say(5, "Kostenrechner-Daten ergänzt.")
        except Exception:
            pass
    # kostenrechner.js in die Seite kopieren, falls noch nicht vorhanden (für den Makeover-Einbau).
    try:
        dst = folder / "static" / "js" / "kostenrechner.js"
        if not dst.exists() and _VORLAGE_RECHNER_JS.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copyfile(_VORLAGE_RECHNER_JS, dst)
    except Exception:
        pass


def _refresh_hero_on_upgrade(folder: Path) -> None:
    """Beim Re-Makeover wegen einer NEUEN _MAKEOVER_VERSION einmalig ein frisches Higgsfield-
    Hero erzwingen: nur hero_source zurücksetzen, damit _ensure_hero ein neues Bild erzeugt
    (im Tagesbudget). hero_image bleibt als Fallback erhalten (falls das Budget erschöpft ist).
    Vom Inhaber hochgeladenes Hero (hero_custom) bleibt unangetastet. Idempotent pro Version."""
    try:
        content = _read_content(folder)
    except Exception:
        return
    if content.get("hero_custom"):
        return
    if int(content.get("makeover_version") or 0) >= _MAKEOVER_VERSION:
        return                                      # kein Upgrade → kein erzwungenes Neu-Hero
    if int(content.get("hero_refresh_version") or 0) >= _MAKEOVER_VERSION:
        return                                      # für diese Version schon erneuert
    content["hero_source"] = ""                      # _ensure_hero erzeugt jetzt frisch (Higgsfield)
    content["hero_refresh_version"] = _MAKEOVER_VERSION
    _write_content(folder, content)


def _prefill_content_local(folder: Path, meta: dict, say=None) -> None:
    """Reichert content.json VOR dem Makeover LOKAL über Ollama an (kostenlos, 32-GB-Maschine):
    4–6 betriebsgenaue Leistungen, eine glaubwürdige Über-uns-Geschichte, 4–5 FAQ und Trust-
    Signale. So muss der teure Headless-Claude in den Stufen die Texte nur noch EINBAUEN/GESTALTEN
    statt selbst zu schreiben → deutlich weniger Tokens (≥3 Seiten pro Session). Idempotent über
    das Flag content['content_enriched']; per JARVIS_MAKEOVER_PREFILL=0 abschaltbar. Best-effort."""
    _grade_fotos_once(folder, meta, say)        # Lead-Fotos lokal bewerten (immer, idempotent)
    _ensure_akzent(folder, meta, say)           # Farbe branchengerecht nachziehen (immer)
    _ensure_rechner(folder, meta, say)          # Kostenrechner-Daten + JS sicherstellen (immer)
    if os.environ.get("JARVIS_MAKEOVER_PREFILL", "1") == "0":
        return
    content = _read_content(folder)
    if content.get("content_enriched"):
        return
    try:
        from scrapers._http import ask_ollama
    except Exception:
        return
    cmodel = _content_model()
    d = _doc_details(folder, meta)
    name    = meta.get("name") or content.get("site_name") or "Der Betrieb"
    branche = meta.get("branche") or content.get("branche") or d.get("branche", "")
    stadt   = meta.get("stadt") or content.get("stadt") or d.get("stadt", "")
    beschr  = d.get("beschreibung") or content.get("ueber_text", "")
    if say:
        say(7, f"Inhalte lokal anreichern (Ollama, spart Tokens) — {name}…")
    sys = ("Du bist Senior-Texter (design-pro) für lokale Handwerks-/Dienstleister-Landingpages. "
           "Schreibe betriebsgenau, seriös, konkret, deutsch — KEIN Fülltext, KEINE Floskeln, "
           "nichts erfinden, was den Daten widerspricht. Antworte AUSSCHLIESSLICH mit JSON.")
    usr = (f"Betrieb: {name}\nBranche: {branche}\nStadt/Region: {stadt}\n"
           f"Beschreibung (Recherche): {str(beschr)[:400]}\n\n"
           "Erzeuge JSON mit GENAU diesen Feldern:\n{\n"
           '  "leistungen": [{"titel":"…","text":"1 konkreter Nutzen-Satz"} … 4 bis 6 '
           "branchenspezifische Leistungen],\n"
           '  "ueber_text": "3-4 Sätze glaubwürdige Über-uns-Geschichte (Region, Erfahrung, Werte)",\n'
           '  "faq": [{"frage":"…","antwort":"…"} … 4 bis 5 echte, branchentypische Fragen],\n'
           '  "trust": ["3-5 kurze Vertrauenssignale, z.B. Erreichbarkeit, Garantie, Region"]\n}\n'
           "Nur das JSON.")
    try:
        out = ask_ollama(usr, system=sys, model=cmodel,
                         timeout=int(os.environ.get("JARVIS_PREFILL_TIMEOUT", "180") or "180"))
    except Exception:
        return
    try:
        import website_builder
        data = website_builder._extract_json(out or "")
    except Exception:
        data = None
    if not isinstance(data, dict):
        return
    content = _read_content(folder)                      # frisch lesen
    # Leistungen: nur ersetzen, wenn lokal mehr/bessere geliefert wurden.
    leist = [{"titel": str(x.get("titel", "")).strip(), "text": str(x.get("text", "")).strip()}
             for x in (data.get("leistungen") or []) if isinstance(x, dict) and x.get("titel")]
    if len(leist) >= 4:
        content["leistungen"] = leist[:6]
    ueber = str(data.get("ueber_text", "")).strip()
    if len(ueber) > len(str(content.get("ueber_text", ""))):
        content["ueber_text"] = ueber
    faq = [{"frage": str(x.get("frage", "")).strip(), "antwort": str(x.get("antwort", "")).strip()}
           for x in (data.get("faq") or []) if isinstance(x, dict) and x.get("frage")]
    if faq and not content.get("faq"):
        content["faq"] = faq[:5]
    trust = [str(x).strip() for x in (data.get("trust") or []) if str(x).strip()]
    if trust and not content.get("trust"):
        content["trust"] = trust[:5]
    content["content_enriched"] = True
    _write_content(folder, content)
    try:
        logger.info("Makeover", f"Inhalte lokal angereichert (Ollama): {len(leist)} Leistungen, "
                                f"{len(faq)} FAQ — {name}")
    except Exception:
        pass


def _run_local_stage(folder: Path, meta: dict, say=None) -> bool:
    """LOKALE Makeover-Stufe (0 Claude-Tokens): Farbwelt + Font-Pairing über design_tokens
    anwenden (tokens.css + Template-Einbindung) und Bilder final einordnen (Lead-Fotos
    bewerten/zuordnen + leere Slots als saubere Platzhalter, nie ein gebrochenes <img>).
    Gibt True, wenn etwas geändert wurde."""
    folder = Path(folder)
    changed = False
    # 1) Farben/Fonts: tokens.css aus Akzent+Branche schreiben + ins Template einbinden.
    try:
        import design_tokens
        content = _read_content(folder)
        branche = meta.get("branche") or content.get("branche") or ""
        content = design_tokens.apply(folder, content, branche)
        _write_content(folder, content)
        changed = True
        if say:
            say(70, f"Farbwelt + Fonts lokal gesetzt "
                    f"({content.get('font_display')}/{content.get('font_body')}).")
    except Exception as e:
        logger.warn("Makeover", f"Lokale Farb-/Font-Stufe übersprungen: {type(e).__name__}: {str(e)[:120]}")
    # 2) Bilder final einordnen — Lead-Fotos bewerten (idempotent) + leere Slots als Platzhalter.
    try:
        _grade_fotos_once(folder, meta, say)        # idempotent (überspringt, wenn schon bewertet)
        import ref_images
        content = _read_content(folder)
        content = ref_images.ensure_placeholders(
            folder, content, meta.get("branche") or content.get("branche", ""))
        _write_content(folder, content)
        changed = True
        if say:
            say(78, "Bilder lokal eingeordnet (Lead-Fotos + saubere Platzhalter).")
    except Exception as e:
        logger.warn("Makeover", f"Lokale Bild-Stufe übersprungen: {type(e).__name__}: {str(e)[:120]}")
    return changed


def run_makeover(folder: "str | Path", meta: dict, say=None, stop=None,
                 on_stage_done=None) -> dict:
    """Fährt die Seite durch alle noch offenen Makeover-Stufen (resume-fähig).
    say(progress:int, text:str) meldet Fortschritt; stop() bricht sauber ab.
    on_stage_done(key, label, n_done): wird nach JEDER fertig gebauten + committeten Stufe
    aufgerufen — damit der Aufrufer die Stufe sofort live pushen kann („pushen jeweils"),
    statt erst am Ende. Gibt {ok, stages_done (neu in diesem Lauf), all_done, reason}."""
    folder = Path(folder)
    say = say or (lambda p, t: None)

    if not folder.is_dir():
        return {"ok": False, "reason": "Ordner nicht gefunden", "all_done": False, "stages_done": []}
    if not claude_coder.is_available():
        say(100, "Claude-CLI fehlt — Makeover nicht möglich (npm i -g @anthropic-ai/claude-code).")
        return {"ok": False, "reason": "claude-CLI fehlt", "all_done": False, "stages_done": []}

    # Limit-Gate: ist Claude erschöpft und die 4-h-Pause (dann stündlich) noch nicht vorbei,
    # gar nicht erst einen Lauf starten — spart Token und respektiert den Retry-Plan.
    # Mehrere Keys: ist noch einer frei, trotz „limited"-Zeichen weiterlaufen (anderer Claude).
    # ABER: ist noch eine LOKALE Stufe offen (0 Tokens), läuft sie auch bei vollem Limit durch —
    # die teure Claude-Politur pausiert dann separat (sie wird im Stufen-Loop sauber gestoppt).
    _open = _ALL_KEYS - _done_keys(folder)
    _local_open = any(s["key"] in _open for s in STAGES if s.get("local"))
    _key_free = False
    try:
        import claude_keys
        _key_free = claude_keys.count() > 1 and claude_keys.has_available()
    except Exception:
        _key_free = False
    if not _local_open and not _key_free and not claude_limit.should_try_now():
        mins = claude_limit.seconds_to_retry() // 60
        say(100, f"Claude-Limit aktiv — nächster Versuch in ~{mins} Min.")
        return {"ok": False, "reason": "session_limit", "all_done": all_done(folder),
                "stages_done": []}

    # Sauberer Resume: eine beim letzten Mal abgebrochene (uncommittete) Stufe verwerfen.
    _reset_dirty(folder)

    # Hero-Bild zuerst frisch erzeugen (einmal je Seite, Default Higgsfield), damit die
    # folgenden Design-Stufen auf dem hochwertigen Bild aufbauen.
    if not (stop and stop()):
        _refresh_hero_on_upgrade(folder)        # neue Version → frisches Higgsfield-Hero erzwingen
        _ensure_hero(folder, meta, say)
    # Rechtstexte lokal vorbefüllen (0 Claude-Tokens) — die QA-Stufe rendert sie nur noch.
    _ensure_legal(folder, meta)
    # Adresse → Koordinaten (für echte eingebettete Karte). Best-effort, 0 Claude-Tokens.
    if not (stop and stop()):
        _ensure_geo(folder, meta)
    # Inhalte (Leistungen/Über-uns/FAQ/Trust) LOKAL über Ollama anreichern (0 Claude-Tokens),
    # damit die teuren Stufen nur noch einbauen/gestalten statt zu schreiben → ≥3 Seiten/Session.
    if not (stop and stop()):
        _prefill_content_local(folder, meta, say)
    # Leere Bild-Slots mit Referenz-Platzhaltern füllen (auch für ältere Seiten ohne
    # about/Galerie), damit die Design-Stufen auf vollständigen Inhalten aufbauen.
    try:
        import ref_images
        content0 = _read_content(folder)
        content0 = ref_images.ensure_placeholders(
            folder, content0, meta.get("branche") or content0.get("branche", ""))
        _write_content(folder, content0)
    except Exception:
        pass
    # Vorbereitung (Hero-Bild, lokale Inhalte, Rechtstexte) als Commit sichern — sonst würde
    # ein Resume sie via _reset_dirty verwerfen und das Hero-Bild (Budget!) neu erzeugen.
    _git_commit(folder, "Vorbereitung: Hero-Bild, lokale Inhalte & Rechtstexte")

    done = _done_keys(folder)
    name = meta.get("name", "?")
    new_done: list[str] = []
    total = len(STAGES)
    run_start = time.time()
    offen = [s["label"] for s in STAGES if s["key"] not in done]
    logger.info("Makeover", f"━━ Start: {name} · {len(done)}/{total} bereits fertig · "
                            f"{len(offen)} offen: {', '.join(offen) or '—'}")

    for i, stage in enumerate(STAGES):
        if stop and stop():
            logger.info("Makeover", f"{name} — gestoppt vor Stufe {stage['label']}.")
            break
        # Ordner-weg-Schutz: Wurde die Seite mittendrin gelöscht (Ordner verschwunden), den
        # Makeover sauber abbrechen — sonst liefe eine teure Claude-Stufe auf einem toten Ordner
        # und der Makeover-Slot bliebe unnötig belegt (Night-Builder hing genau daran).
        if not folder.is_dir():
            logger.warn("Makeover", f"{name} — Ordner verschwunden (gelöscht?) → Makeover abgebrochen.")
            break
        if stage["key"] in done:
            continue
        pct = 8 + int(i / total * 82)
        st_start = time.time()

        # ── LOKALE Stufe (0 Claude-Tokens): direkt ausführen, kein headless-Claude ──
        if stage.get("local"):
            logger.info("Makeover", f"→ {name} · Stufe {i+1}/{total}: {stage['label']} (lokal)")
            say(pct, f"Makeover {i + 1}/{total} · {stage['label']}…")
            ch = _run_local_stage(folder, meta, say)
            st_dur = round(time.time() - st_start, 1)
            if not ch:
                logger.warn("Makeover", f"⊘ {name} · lokale Stufe ohne Änderung nach {st_dur}s.")
                continue
            _mark_done(folder, stage["key"])
            claude_limit.clear()
            _git_commit(folder, f"Makeover (lokal): {stage['label']}")
            new_done.append(stage["key"])
            logger.success("Makeover", f"✓ {name} · Stufe {i+1}/{total} {stage['label']} "
                                       f"(lokal, {st_dur}s) · {len(done)+len(new_done)}/{total}")
            try:
                logger.activity("Makeover", stage["label"], name, "✨", "build")
            except Exception:
                pass
            if on_stage_done:
                try:
                    on_stage_done(stage["key"], stage["label"], len(new_done))
                except Exception as e:
                    logger.warn("Makeover", f"Per-Stufe-Push übersprungen: {type(e).__name__}")
            continue

        logger.info("Makeover", f"→ {name} · Stufe {i+1}/{total}: {stage['label']} "
                                f"(Skill {stage.get('skill', '?')}, Modell {stage.get('model') or _MODEL})")
        prompt = _build_stage_prompt(folder, meta, stage, i + 1, total)

        # Stufe ausführen — bei Claude-Session-Limit bis zu _LIMIT_RETRIES× je _LIMIT_WAIT
        # (Default 7× 1 h) warten und dieselbe Stufe erneut versuchen. Ein interner CLI-Fehler
        # (cli_error, z.B. 'error_during_execution' — der headless-Prozess bricht mitten im Lauf
        # ab, meist ein kurzer API-Aussetzer) bekommt zusätzlich ein paar SCHNELLE Retries: ohne
        # das wäre die Stufe nach einem einzigen Aussetzer für den Rest der Nacht verloren (die
        # Stufe bliebe unmarkiert offen → Night-Builder landet in _makeover_stuck) statt dass ein
        # zweiter Versuch direkt durchläuft.
        res: dict = {}
        changed = False
        attempt = 0
        cli_attempt = 0
        while True:
            if stop and stop():
                break
            say(pct, f"Makeover {i + 1}/{total} · {stage['label']} ({stage['skill']})…")
            fp0 = _fingerprint(folder)
            res = claude_coder.run_prompt(
                str(folder), prompt, branche=meta.get("branche", ""),
                model=stage.get("model") or _MODEL, task=f"makeover:{stage['key']}", name=name,
                max_turns=stage.get("max_turns", 0), timeout=stage.get("timeout", 0),
                on_progress=lambda s, _p=pct, _l=stage["label"], _i=i + 1, _t=total:
                    say(_p, f"Makeover {_i}/{_t} · {_l} · {s}"),
            )
            changed = _fingerprint(folder) != fp0
            if _is_limit(res, changed):
                pass                                       # → Limit-Handling weiter unten
            elif (res.get("cli_error") and res.get("retryable") and not changed
                  and cli_attempt < _CLI_ERROR_RETRIES):
                cli_attempt += 1
                logger.warn("Makeover", f"{name} · '{stage['label']}' interner Claude-Fehler — "
                                        f"Versuch {cli_attempt}/{_CLI_ERROR_RETRIES} in "
                                        f"{_CLI_ERROR_WAIT}s: {str(res.get('reason',''))[:120]}")
                say(pct, f"Claude-Fehler — erneuter Versuch ({cli_attempt}/{_CLI_ERROR_RETRIES})…")
                if not _sleep_interruptible(_CLI_ERROR_WAIT, stop, None):
                    break
                continue
            else:
                break
            # Limit erkannt. Scope (Session/Weekly) + Roh-Meldung (für Reset-Zeit) bestimmen.
            _ltext = (res.get("summary") or "") + " " + (res.get("reason") or "")
            scope = _limit_scope(_ltext)
            # Mehrere Keys? Aktiven Key erschöpft setzen und SOFORT auf den nächsten „Claude"
            # wechseln (ohne die ganze Cooldown-Pause).
            try:
                import claude_keys
                if claude_keys.count() > 1:
                    ak = claude_keys.active_key()
                    if ak:
                        claude_keys.mark_exhausted(ak, scope)
                    if claude_keys.has_available():
                        logger.warn("Makeover", f"{scope}-Limit auf einem Key — wechsle sofort "
                                                "auf den nächsten Claude-Key.")
                        say(pct, f"{scope}-Limit — wechsle auf nächsten Claude-Key…")
                        claude_limit.clear()
                        continue                       # sofort mit nächstem Key erneut
            except Exception:
                pass
            # Limit-Zeichen fürs Dashboard setzen + Budget lernen. reset_hint übergibt die
            # Roh-Meldung — enthält sie eine Uhrzeit („resets 5am"), wird der Retry exakt dahin gelegt.
            claude_limit.mark(stage["label"], _LIMIT_WAIT, site=name, scope=scope, reset_hint=_ltext)
            # Debug-Kontext an der Problemstelle: was gelernt wurde + wann der nächste Versuch liegt.
            try:
                _ls = claude_limit.status()
                _ra = _ls.get("reset_at") or 0
                _when = (time.strftime("%H:%M", time.localtime(_ra)) if _ra
                         else f"in {_ls.get('minutes_to_retry', 0)} Min")
                logger.debug("Makeover", f"⤷ {scope}-Limit gelernt: ~{_ls.get('learned_limit',0):,} Tok/Fenster "
                                         f"(n={_ls.get('obs_count',0)}, Quelle {_ls.get('retry_source','?')}) "
                                         f"· nächster Versuch {_when}")
            except Exception:
                pass
            if attempt >= _LIMIT_RETRIES:
                say(pct, f"Claude-Session-Limit auch nach {_LIMIT_RETRIES} Versuchen aktiv — "
                         "Makeover pausiert (später fortsetzbar).")
                logger.warn("Makeover", f"Session-Limit nach {_LIMIT_RETRIES} Wartezyklen — pausiert.")
                return {"ok": False, "reason": "session_limit",
                        "stages_done": new_done, "all_done": all_done(folder)}
            attempt += 1
            logger.warn("Makeover", f"Claude-Session-Limit — warte {_LIMIT_WAIT // 60} Min, "
                                    f"dann Versuch {attempt}/{_LIMIT_RETRIES} ({stage['label']}).")
            if not _sleep_interruptible(_LIMIT_WAIT, stop, say, attempt, _LIMIT_RETRIES, pct):
                # Während des Wartens gestoppt → pausieren, Resume beim nächsten Lauf.
                return {"ok": False, "reason": "session_limit",
                        "stages_done": new_done, "all_done": all_done(folder)}

        if stop and stop():
            break

        st_dur = round(time.time() - st_start, 1)
        if not res.get("ok"):
            logger.error("Makeover", f"✕ {name} · Stufe '{stage['label']}' fehlgeschlagen nach "
                                     f"{st_dur}s: {str(res.get('reason', ''))[:160]}")
            continue

        summ = res.get("summary") or ""
        # Eine Stufe gilt NUR als erledigt, wenn sie wirklich Dateien geändert hat (kein Limit
        # mehr — das ist oben abgefangen; hier bleibt nur eine echte Rückfrage/Leerlauf).
        if not changed:
            logger.warn("Makeover", f"⊘ {name} · Stufe '{stage['label']}' ohne Datei-Änderung "
                                    f"nach {st_dur}s — nicht markiert: {summ[:90]}")
            continue

        _mark_done(folder, stage["key"])
        claude_limit.clear()                 # eine Stufe lief durch → Limit-Zeichen weg
        _git_commit(folder, f"Makeover: {stage['label']} — {summ[:80]}")
        new_done.append(stage["key"])
        logger.success("Makeover", f"✓ {name} · Stufe {i+1}/{total} {stage['label']} fertig "
                                   f"({st_dur}s) · {len(done)+len(new_done)}/{total} gesamt")
        try:
            logger.activity("Makeover", stage["label"], name, "✨", "build")
        except Exception:
            pass
        # Stufe sofort live pushen (token-arm: eine Stufe = ein Push). Selbst wenn eine
        # spätere Stufe am Rate-Limit hängt, sind die fertigen Skills schon deployt.
        if on_stage_done:
            try:
                on_stage_done(stage["key"], stage["label"], len(new_done))
            except Exception as e:
                logger.warn("Makeover", f"Per-Stufe-Push übersprungen: {type(e).__name__}")

    fertig = all_done(folder)
    total_dur = round(time.time() - run_start, 1)
    if fertig:
        logger.success("Makeover", f"━━ {name}: KOMPLETT — alle {total} Stufen fertig "
                                   f"(+{len(new_done)} in diesem Lauf, {total_dur}s).")
    else:
        rest = [s["label"] for s in STAGES if s["key"] not in _done_keys(folder)]
        logger.info("Makeover", f"━━ {name}: Lauf-Ende +{len(new_done)} Stufen in {total_dur}s · "
                                f"noch offen: {', '.join(rest) or '—'}")
    return {"ok": True, "stages_done": new_done, "all_done": fertig}


# ── Premium-Upgrade NACH dem Versand (1A-Standard, ein Master-Prompt) ─────────────
# Sobald eine Seite an den echten Kunden geschickt wurde, ist sie „verkaufsrelevant" —
# jetzt darf sie maximal teuer werden. EIN großer Claude-Lauf mit dem VOLLEN taste-Skill,
# der ALLE Bilder einbaut, ALLE auffindbaren Firmeninfos verwendet und die Seite auf echtes
# 1A-Agentur-Niveau hebt. Läuft nur EINMAL je Seite (Latch content['premium_upgraded']),
# im Hintergrund, und blockiert den 12-Uhr-Versand nie.
_PREMIUM_SKILL = (os.environ.get("JARVIS_PREMIUM_SKILL") or _TASTE).strip() or _TASTE
# Hochwertiges Modell — diese Seite ist bereits verkauft/verschickt, Qualität geht hier vor
# Tokensparen. Default opus; per .env auf 'sonnet' senkbar.
_PREMIUM_MODEL = (os.environ.get("JARVIS_PREMIUM_MODEL") or "opus").strip() or "opus"


def _build_premium_prompt(context: str) -> str:
    return (
        "Headless-Web-Editor im AKTUELLEN Ordner: eine fertige, bereits LIVE gegangene und an "
        "den Kunden verschickte Django-Landing-Page (rendert aus content.json über "
        "templates/index.html + static/css/style.css, dazu static/img + static/js).\n\n"
        "AUFTRAG: Hebe DIESE Seite jetzt auf echten 1A-PREMIUM-STANDARD — sie soll richtig krass "
        "aussehen, wie das Referenzprojekt einer preisgekrönten Agentur, absolut nicht templated "
        "oder KI-generiert. Das ist die finale Ausbaustufe einer verkauften Seite: Qualität geht "
        "vor allem anderen, aber ohne vorhandene Funktion zu beschädigen (Funktion vor Design).\n\n"
        f"{context}\n\n"
        "WENDE ALLE RELEVANTEN DESIGN-SKILLS VOLL AN — lies und nutze das Skill "
        f"«{_PREMIUM_SKILL}» (taste/ui-ux-pro-max/impeccable-design/frontend-pro destilliert) "
        "konsequent: durchgängiges Farb-Token-System (EINE Akzentfarbe + getönte Neutrals als "
        "CSS-Variablen, WCAG-AA), charakterstarkes Display-/Body-Font-Pairing (Google Fonts), "
        "fluide Typo-Skala mit clamp(), feste Spacing-Skala, weiche mehrschichtige Schatten, ein "
        "konsistentes Inline-SVG-Icon-Set, dezente performante Motion (transform/opacity, "
        "prefers-reduced-motion), ALLE Zustände (hover/focus-visible/active/disabled).\n\n"
        "PFLICHT:\n"
        "1) ALLE BILDER EINBAUEN: Sämtliche Bilder aus content.json (hero_image, about_image, "
        "alle content.fotos, foto_captions, logo_image) müssen sinnvoll und hochwertig platziert "
        "werden — Hero, Über-uns, eine ECHTE Galerie/Referenz-Sektion, Team. Kein Bild "
        "verschwenden, KEINE Dopplung des Hero-Bilds, nie ein gebrochenes <img>; fehlt ein Bild, "
        "ein sauberer Platzhalter. Bilder mit object-fit, korrekten Seitenverhältnissen, "
        "loading=\"lazy\", aussagekräftigen alt-Texten.\n"
        "2) ALLE AUFFINDBAREN FIRMENINFOS verwenden: Jede bekannte Angabe (Name, Branche, Adresse, "
        "Telefon, E-Mail, Ansprechpartner, Öffnungszeiten, Beschreibung, USPs, Trust-Signale, "
        "Social-Media) gehört prominent und betriebsgenau auf die Seite — Kontakt, Über-uns, "
        "Footer, Karte. Stehen Details in content.json bzw. im Kontext oben, baue sie ein; "
        "erfinde NICHTS, was den Daten widerspricht.\n"
        "3) Above-the-fold-HERO perfekt: zwei Spalten — links Text (Eyebrow → kraftvolle Headline "
        "→ Subline → CTA-Reihe inkl. WhatsApp wa.me / Anruf tel: / E-Mail mailto: → Trust-Signale), "
        "rechts die funktionierende Kostenrechner-Karte (content.rechner + static/js/kostenrechner.js). "
        "Auf Mobil sauber stapeln (Touch-Ziele ≥ 44 px).\n"
        "4) Vollständige Sektionen: Leistungen (Karten-Grid, SVG-Icons), FAQ, Über-uns, Galerie, "
        "Kontakt mit echter eingebetteter Karte (content.map_embed/maps_url) + Kontaktformular "
        "(method=post, {% csrf_token %}, Einwilligung → Datenschutz). Rechtstexte "
        "(impressum/datenschutz/agb) 1:1 rendern + unten links verlinken; Credit «Erstellt von "
        f"WVM-IT» (wvm_url/wvm_name) + Shop-Link (wvm_shop) im Footer erhalten.\n"
        "5) QA: perfekt mobil (echte Breakpoints, Sticky-Anruf/WhatsApp), keine Überläufe, kein "
        "CLS, alle Links funktionieren, SEO-Grundgerüst (title, meta description, H-Hierarchie, "
        "alt-Texte). content.json bleibt valides JSON, keine vorhandenen Keys löschen.\n\n"
        "REGELN: Sofort autonom umsetzen, KEINE Rückfragen. content.json + templates/index.html + "
        "static/css/style.css direkt aus dem Ordner lesen und WIRKLICH editieren (echtes Design, "
        "nicht nur Text). Deutsch, konkret, betriebsgenau. Am Ende MUSS `python manage.py check` "
        "fehlerfrei sein und das Template ohne Fehler rendern. Schließe mit genau einem Satz, was "
        "du verbessert hast."
    )


def premium_upgraded(folder: "str | Path") -> bool:
    """True, wenn die Seite den einmaligen 1A-Premium-Ausbau schon erhalten hat."""
    try:
        return bool(_read_content(Path(folder)).get("premium_upgraded"))
    except Exception:
        return False


def run_premium_upgrade(folder: "str | Path", meta: dict, say=None, stop=None) -> dict:
    """Einmaliger 1A-Premium-Ausbau einer bereits verschickten Seite (ein großer Claude-Lauf,
    volles taste-Skill, alle Bilder + alle Firmeninfos). Idempotent über content['premium_upgraded'].
    Gibt {ok, changed, reason, summary}. Best-effort — Fehler blockieren nichts."""
    folder = Path(folder)
    say = say or (lambda p, t: None)
    if not folder.is_dir():
        return {"ok": False, "reason": "Ordner nicht gefunden", "changed": False}
    if premium_upgraded(folder):
        return {"ok": True, "reason": "bereits ausgebaut", "changed": False}
    if not claude_coder.is_available():
        return {"ok": False, "reason": "claude-CLI fehlt", "changed": False}

    # Limit-Gate: erschöpfter Claude (und kein freier Zweitschlüssel) → später nachziehen.
    _key_free = False
    try:
        import claude_keys
        _key_free = claude_keys.count() > 1 and claude_keys.has_available()
    except Exception:
        _key_free = False
    if not _key_free and not claude_limit.should_try_now():
        mins = claude_limit.seconds_to_retry() // 60
        say(100, f"Claude-Limit aktiv — Premium-Ausbau in ~{mins} Min.")
        return {"ok": False, "reason": "session_limit", "changed": False}

    name = meta.get("name", "?")
    _reset_dirty(folder)
    # Vollständige Vorbereitung (idempotent, 0 Claude-Tokens): frisches Hero, Rechtstexte, Geo,
    # lokale Inhalte, Lead-Foto-Bewertung + saubere Platzhalter — damit der Master-Lauf auf
    # WIRKLICH allen Bildern und Infos aufbaut.
    if not (stop and stop()):
        _ensure_hero(folder, meta, say)
    _ensure_legal(folder, meta)
    if not (stop and stop()):
        _ensure_geo(folder, meta)
    if not (stop and stop()):
        _prefill_content_local(folder, meta, say)
    try:
        import ref_images
        c0 = _read_content(folder)
        c0 = ref_images.ensure_placeholders(folder, c0, meta.get("branche") or c0.get("branche", ""))
        _write_content(folder, c0)
    except Exception:
        pass
    _git_commit(folder, "Premium-Ausbau: Vorbereitung (Bilder, Infos, Recht)")

    logger.info("Makeover", f"★ Premium-1A-Ausbau startet: {name} (Skill {_PREMIUM_SKILL}, "
                            f"Modell {_PREMIUM_MODEL})")
    say(20, f"1A-Premium-Ausbau für {name} (Master-Prompt, alle Bilder + Infos)…")
    context = _context_block(folder, meta)
    prompt = _build_premium_prompt(context)
    fp0 = _fingerprint(folder)
    res = claude_coder.run_prompt(
        str(folder), prompt, branche=meta.get("branche", ""),
        model=_PREMIUM_MODEL, task="premium", name=name,
        max_turns=int(os.environ.get("JARVIS_PREMIUM_TURNS", "120") or "120"),
        timeout=int(os.environ.get("JARVIS_PREMIUM_TIMEOUT", "2400") or "2400"),
        on_progress=lambda s: say(60, f"Premium-Ausbau · {s}"))
    changed = _fingerprint(folder) != fp0

    if _is_limit(res, changed):
        _ltext = (res.get("summary") or "") + " " + (res.get("reason") or "")
        scope = _limit_scope(_ltext)
        claude_limit.mark("Premium-Ausbau", _LIMIT_WAIT, site=name, scope=scope, reset_hint=_ltext)
        return {"ok": False, "reason": "session_limit", "changed": False}
    if not res.get("ok"):
        logger.warn("Makeover", f"Premium-Ausbau fehlgeschlagen ({name}): {str(res.get('reason',''))[:140]}")
        return {"ok": False, "reason": res.get("reason", ""), "changed": changed}

    summ = res.get("summary") or ""
    if changed:
        claude_limit.clear()
        content = _read_content(folder)
        content["premium_upgraded"] = True
        content["premium_upgraded_ts"] = time.time()
        _write_content(folder, content)
        _git_commit(folder, f"Premium-Ausbau (1A): {summ[:80]}")
        logger.success("Makeover", f"★ Premium-1A-Ausbau fertig: {name} — {summ[:100]}")
        try:
            logger.activity("Makeover", "1A-Premium-Ausbau (verkaufte Seite)", name, "★", "build")
        except Exception:
            pass
    else:
        logger.info("Makeover", f"Premium-Ausbau ohne Datei-Änderung ({name}): {summ[:90]}")
    return {"ok": True, "changed": changed, "summary": summ}


# ── Freigabe (Discord 1× 👍, sonst Vorschau-Mail) ──────────────────────────────────

def _mark_review_submitted(folder: str) -> None:
    """Latch: merkt in content.json, dass die Seite EINMAL zur Freigabe eingereicht wurde —
    so postet ein späterer Politur-Lauf nicht erneut in Discord. Best-effort."""
    try:
        if not folder:
            return
        content = _read_content(Path(folder))
        content["review_submitted"] = True
        _write_content(Path(folder), content)
    except Exception:
        pass


def finalize_review(meta: dict, live_url: str, folder: str) -> dict:
    """Postet die fertige Seite zur Freigabe in Discord (1× 👍 = Mail, 1× 👎 = verwerfen).
    Ist der Discord-Bot aus, geht eine Vorschau-Mail an die Fallback-Adresse.
    Die Plaintext-Version des Angebots-Mails wird mit zur Discord-Nachricht geschickt,
    damit Bastian den Text direkt in der Abstimmung sehen und freigeben kann."""
    name    = meta.get("name", "")
    stadt   = meta.get("stadt", "")
    branche = meta.get("branche", "")
    email   = meta.get("email", "")
    ap      = meta.get("ansprechpartner", "")
    # Zentrales Gate: Sobald alle PFLICHT-Stufen fertig sind (die optionale Claude-Politur
    # zählt NICHT — sie darf die Freigabe + Angebots-Mail nie blockieren), geht die Seite in
    # die Freigabe. Latch `review_submitted` verhindert einen zweiten Discord-Post, falls die
    # Politur in einem späteren Lauf nachzieht. force=True erzwingt (manuelle Eigene-Marke-Sendung).
    try:
        if folder and not meta.get("force"):
            if not review_ready(folder):
                logger.info("Makeover", f"finalize_review übersprungen ({name}) — Pflicht-Stufen "
                                        "noch nicht fertig.")
                return {"review": False, "reason": "nicht fertig"}
            if _read_content(Path(folder)).get("review_submitted"):
                logger.info("Makeover", f"finalize_review übersprungen ({name}) — bereits eingereicht.")
                return {"review": False, "reason": "bereits eingereicht"}
    except Exception:
        pass
    # Eigene-Marke-Empfänger (vom Nutzer im Formular eingegeben) aus content.json holen.
    recipients = meta.get("recipients") or _read_content(Path(folder)).get("custom_recipients") or None

    # Angebotspreis (Tier) best-effort aus den Lead-Daten — sonst fairer Standardpreis.
    preis = int(meta.get("preis") or 0)
    if not preis:
        try:
            d = _doc_details(Path(folder), meta)
            preis = int(d.get("potenzial_euro") or 0)
        except Exception:
            preis = 0

    # Angebots-Mail-Text vorbauen (für Discord-Vorschau + Fallback-Mail)
    betreff = text = html_mail = ""
    try:
        import offer_mail
        betreff, text, html_mail = offer_mail.build(name, live_url, branche, stadt, ap, preis=preis)
    except Exception:
        pass

    try:
        import discord_bot
        # Auto-Send ODER verbundener Bot → in die Versand-Queue. Im Auto-Send-Modus geht die
        # Seite ohne Bestätigung raus; ist Discord verbunden, wird sie zusätzlich gepostet.
        if discord_bot.auto_send() or discord_bot.enabled():
            r = discord_bot.submit_for_review(
                name, stadt, branche, live_url, email, ap, str(folder),
                recipients=recipients, email_text=text, email_subject=betreff, preis=preis)
            if r:
                verb = "automatisch freigegeben (Auto-Send)" if discord_bot.auto_send() \
                    else "zur Discord-Freigabe gepostet"
                logger.info("Makeover", f"{name}: {verb}")
                _mark_review_submitted(folder)
                return {"review": True}
    except Exception as e:
        logger.warn("Makeover", f"Discord-Review fehlgeschlagen: {type(e).__name__}")

    # Fallback: Vorschau-Mail an Bastian
    try:
        import mailer
        to = os.environ.get("JARVIS_FALLBACK_EMAIL", "bastian.scherzinger05@gmail.com")
        if betreff and text:
            mailer.send_email(to, betreff, text, html=html_mail, bypass_redirect=True)
        else:
            import offer_mail
            b, t, h = offer_mail.build(name, live_url, branche, stadt, ap)
            mailer.send_email(to, b, t, html=h, bypass_redirect=True)
        logger.info("Makeover", f"Vorschau-Mail an {to}: {name}")
        _mark_review_submitted(folder)
    except Exception as e:
        logger.warn("Makeover", f"Vorschau-Mail fehlgeschlagen: {type(e).__name__}")
    return {"review": False}
