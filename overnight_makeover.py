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


# ── Die 7 Stufen ───────────────────────────────────────────────────────────────
# TOKEN-SPARSAM (seit 25.06.2026): Der headless Makeover-Claude lädt das referenzierte
# Skill bei jeder Stufe in den Kontext. taste (88 KB) + ui-ux-pro-max (45 KB) je Stufe ×
# 7 × Seiten haben das Claude-Session-Limit in Minuten geleert (Symptom: „hängt bei Stufe 1").
# Lösung — ein EIGENER, kompakter Skill statt der großen:
#   _LANDING = «premium-landing» (~12 KB, skills/premium-landing/SKILL.md) — destilliert
#              taste/design-pro/ui-ux-pro-max auf GENAU dieses Seiten-Rezept (Tokens, Fonts,
#              Spacing, Sektions-Bauplan inkl. WhatsApp, Team-/Foto-Platzhalter, Footer-Recht).
#              Standard für ALLE Sektions-Stufen → gleiche Qualität, ein Bruchteil der Tokens.
#   _TASTE   = «design-taste-frontend» (88 KB) — nur EINMAL, im großen Design-Durchgang,
#              wo die volle Anti-Slop-Tiefe für Farb-/Font-/Typo-Feinschliff den Preis wert ist.
_TASTE   = "design-taste-frontend"
_LANDING = "premium-landing"

# Makeover-Struktur-Version. Wird sie erhöht (neue/umgebaute STAGES), behandelt der
# Builder bereits „fertige" Seiten als komplett offen und makeovert sie mit dem neuen
# Bauplan neu — so werden nach einem Update die heute gebauten Seiten überall aktualisiert.
_MAKEOVER_VERSION = 2

STAGES: list[dict] = [
    {
        "key": "hero", "label": "Hero-Bereich", "skill": _LANDING,
        "task": (
            "Baue den HERO-BEREICH (Above-the-fold) zu einem echten Premium-Eyecatcher um. "
            "In 5 Sekunden muss klar sein: Was ist das, was bringt es mir, was soll ich tun.\n"
            "WICHTIG zum Bild: Das Hero-Bild (content.json.hero_image, von Higgsfield erzeugt) "
            "enthält NIEMALS Text, Wörter, Buchstaben oder Logos — es ist ein reines Foto. Die "
            "Headline & alle Texte sind ausschließlich HTML-Text in einem .hero-copy-Overlay ÜBER "
            "dem Bild; sichere die Lesbarkeit über einen Scrim/Gradient. hero_image NICHT entfernen.\n"
            "Inhalt: Eyebrow (Branche · Stadt), kraftvolle betriebsgenaue Headline mit konkretem "
            "Nutzenversprechen + Subline, dann eine Button-Reihe: primärer CTA («Kostenlose Anfrage» "
            "/«Termin anfragen»), ein WhatsApp-Button (https://wa.me/<Telefon nur Ziffern, Länder-"
            "vorwahl 49 ohne führende 0 und ohne +/Leerzeichen>?text=Hallo%2C%20ich%20interessiere"
            "%20mich%20f%C3%BCr…), ein E-Mail-Button (mailto:) und ein Anruf-Button (tel:). Primär "
            "dominant, der Rest leiser (Ghost-Stil). Darunter dezente Vertrauenssignale (Bewertung, "
            "Erreichbarkeit, Region, Jahre Erfahrung). Bearbeite den Hero-Block in "
            "templates/index.html und das zugehörige CSS wirklich."
        ),
    },
    {
        "key": "leistungen", "label": "Beschreibung & Dienstleistungen", "skill": _LANDING,
        "task": (
            "Baue die Sektion BESCHREIBUNG & DIENSTLEISTUNGEN. Die Inhalte stehen BEREITS in "
            "content.json: `leistungen` (4–6 Einträge mit titel/text) und `faq`. NICHT neu "
            "erfinden oder umschreiben — übernimm die vorhandenen Texte 1:1 und BAUE sie sauber "
            "ein: ein kurzer Einleitungssatz, dann die Leistungen als übersichtliches Karten-Grid "
            "(je Titel, Nutzen-Text und ein konsistentes Inline-SVG-Icon, 1.5px stroke, currentColor "
            "— KEINE Emojis), darunter eine FAQ-Sektion aus `faq`. Integriere dezent ein Mockup-/"
            "Platzhalterbild, falls vorhanden (sonst sauberer Platzhalter mit aspect-ratio, nie ein "
            "gebrochenes <img>). Dein Fokus ist LAYOUT + DESIGN, nicht Texten. Bearbeite "
            "templates/index.html + CSS wirklich."
        ),
    },
    {
        "key": "ueber", "label": "Über uns, Team & Kontakt-Band", "skill": _LANDING,
        "task": (
            "Zwei Dinge in dieser Reihenfolge:\n"
            "1) KONTAKT-BAND direkt zwischen Leistungen und Über uns: ein schmaler Streifen in "
            "Akzent-Tönung mit einer klaren Conversion-Zeile und zwei Buttons (WhatsApp via wa.me + "
            "Anrufen via tel:). Zweiter Conversion-Punkt der Seite.\n"
            "2) ÜBER UNS überzeugend ausbauen: die Geschichte steht BEREITS in content.json "
            "(`ueber_text`) und die Trust-Signale in `trust` — übernimm sie 1:1 (nicht neu "
            "schreiben), Fokus ist Layout/Design. Oben/links ein PLATZHALTER für das Foto des "
            "Inhabers (Label 'Inhaber', "
            "sauberes Bild-Placeholder mit aspect-ratio + dezentem Icon). Darunter ein TEAM-GRID mit "
            "GENAU 4 Mitarbeiter-Platzhaltern (rundes Avatar-Placeholder + '[Name]' / '[Position]'). "
            "Daneben eine echte Trust-/USP-Liste (Garantien, Referenzen, Erreichbarkeit, "
            "Mitgliedschaften falls branchenpassend). Alles betriebsgenau, kein Geschwurbel. Bearbeite "
            "templates/index.html + CSS wirklich."
        ),
    },
    {
        "key": "kontakt", "label": "Kontakt-Bereich", "skill": _LANDING,
        "task": (
            "Baue den KONTAKT-BEREICH vollständig aus: gut sichtbare echte Telefonnummer (klickbarer "
            "tel:-Link), WhatsApp-Button (wa.me), E-Mail (mailto:), vollständige Adresse, "
            "Öffnungszeiten (falls dokumentiert, sonst plausibel branchentypisch), Anfahrt/Region. "
            "Für die Karte den vorhandenen Link c.maps_url verwenden (Google-Maps-Suche nach der "
            "Adresse, ohne API-Key) ODER ein OSM-iframe NUR mit echten Koordinaten — NIEMALS ein "
            "leeres/graues Karten-iframe ohne bbox. Klare CTAs zum Anrufen, WhatsApp und Schreiben. Sauberes, gut "
            "lesbares Layout. Bearbeite templates/index.html + CSS wirklich."
        ),
    },
    {
        "key": "formular", "label": "Kontakt-Formular", "skill": _LANDING,
        "model": _MODEL_LITE,        # mechanisch (Felder/csrf/tel-mailto/Focus) → günstiges Modell
        "task": (
            "Baue ein funktionsfähiges, schön gestaltetes KONTAKT-FORMULAR (Name, E-Mail, Telefon, "
            "Nachricht, Einwilligungs-Checkbox zur Datenschutzerklärung). Setze method=\"post\" auf "
            "eine sinnvolle Action, ergänze {% csrf_token %} im Form, korrekte input-Typen, "
            "required-Felder, name-Attribute, sichtbare Labels, focus-visible-States und eine klare "
            "Erfolgs-/Fehlermeldungs-Stelle. Falls keine Backend-Route existiert, mailto-Fallback "
            "ODER ein dezenter Hinweis — aber das Formular MUSS valide rendern und gut aussehen. "
            "Touch-Ziele ≥ 44 px. Bearbeite templates/index.html + CSS wirklich."
        ),
    },
    {
        "key": "design", "label": "Komplett-Design (taste)", "skill": _TASTE,
        "task": (
            "Großer DESIGN-DURCHGANG über die GESAMTE Seite mit dem Skill «design-taste-frontend» "
            "(taste). Ziel: sieht aus wie von einer preisgekrönten Agentur, seriös aber farbig-"
            "schlicht, nicht templated/KI-generiert. Wähle mit taste eine stimmige Farbwelt um die "
            "Akzentfarbe + leicht getönte Neutrals als CSS-Tokens (--accent --bg --surface --ink "
            "--muted --line --ring), WCAG-AA-Kontraste. Wähle ein charakterstarkes, passendes "
            "Display-/Body-Font-Pairing (Google Fonts) und eine fluide Typo-Skala mit clamp(). Feste "
            "Spacing-Skala (4/8/12/16/24/32/48/72), rhythmischer Weißraum, konsistente Radien/Stroke-"
            "Breiten, WEICHE mehrschichtige Schatten (kein harter Glow), ein Icon-Set (Inline-SVG). "
            "Dezente, performante Motion (nur transform/opacity, 150–400 ms, ease-out; prefers-"
            "reduced-motion respektieren). Alle Zustände vollständig (hover, focus-visible, active, "
            "disabled). Weniger, aber besser — entferne alles Billige/KI-haft Wirkende. Bearbeite "
            "static/css/style.css + templates/index.html durchgreifend."
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
            "(Link wvm-it.at, Feld wvm_url/wvm_name) im Footer sauber erhalten.\n"
            "2) QA / RESPONSIVE: Perfekte Mobil-Darstellung (echte Breakpoints), ein mobiler "
            "Sticky-Anruf/WhatsApp-Balken, Touch-Ziele ≥ 44 px, keine horizontalen Überläufe, kein "
            "CLS, alle Links/Buttons/Anker funktionieren, SEO-Grundstruktur (title, meta description, "
            "Überschriften-Hierarchie, alt-Texte) intakt. Es MUSS `python manage.py check` "
            "fehlerfrei sein und das Template ohne Fehler rendern."
        ),
    },
]

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
    """Erkennt eine Claude-Code-Limit-/Abbruch-Meldung im Ergebnis-Text."""
    t = (text or "").lower()
    return any(s in t for s in (
        "session limit", "usage limit", "rate limit", "hit your limit",
        "resets", "quota", "try again later"))


def open_stages(folder: "str | Path") -> int:
    """Anzahl noch offener Makeover-Stufen einer Seite (für die Auswahl im Night-Builder).
    Berücksichtigt die Struktur-Version: ältere Seiten zählen als voll offen."""
    return len(_ALL_KEYS - _done_keys(Path(folder)))


def all_done(folder: "str | Path") -> bool:
    return open_stages(folder) == 0


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
    if content.get("hero_source") in ("higgsfield", "higgsfield_mcp", "openai"):
        return False                             # schon ein Cloud-Hero — nicht erneut erzeugen
    if content.get("hero_custom"):
        return False                             # vom Inhaber hochgeladenes Hero nie ersetzen
    d = _doc_details(folder, meta)
    branche = meta.get("branche") or content.get("branche") or d.get("branche", "")
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


def _prefill_content_local(folder: Path, meta: dict, say=None) -> None:
    """Reichert content.json VOR dem Makeover LOKAL über Ollama an (kostenlos, 32-GB-Maschine):
    4–6 betriebsgenaue Leistungen, eine glaubwürdige Über-uns-Geschichte, 4–5 FAQ und Trust-
    Signale. So muss der teure Headless-Claude in den Stufen die Texte nur noch EINBAUEN/GESTALTEN
    statt selbst zu schreiben → deutlich weniger Tokens (≥3 Seiten pro Session). Idempotent über
    das Flag content['content_enriched']; per JARVIS_MAKEOVER_PREFILL=0 abschaltbar. Best-effort."""
    if os.environ.get("JARVIS_MAKEOVER_PREFILL", "1") == "0":
        return
    content = _read_content(folder)
    if content.get("content_enriched"):
        return
    try:
        from scrapers._http import ask_ollama
    except Exception:
        return
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
        out = ask_ollama(usr, system=sys, timeout=int(os.environ.get("JARVIS_PREFILL_TIMEOUT", "180") or "180"))
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
    if not claude_limit.should_try_now():
        mins = claude_limit.seconds_to_retry() // 60
        say(100, f"Claude-Session-Limit aktiv — nächster Versuch in ~{mins} Min.")
        return {"ok": False, "reason": "session_limit", "all_done": all_done(folder),
                "stages_done": []}

    # Sauberer Resume: eine beim letzten Mal abgebrochene (uncommittete) Stufe verwerfen.
    _reset_dirty(folder)

    # Hero-Bild zuerst frisch erzeugen (einmal je Seite, Default Higgsfield), damit die
    # folgenden Design-Stufen auf dem hochwertigen Bild aufbauen.
    if not (stop and stop()):
        _ensure_hero(folder, meta, say)
    # Rechtstexte lokal vorbefüllen (0 Claude-Tokens) — die QA-Stufe rendert sie nur noch.
    _ensure_legal(folder, meta)
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
        if stage["key"] in done:
            continue
        pct = 8 + int(i / total * 82)
        st_start = time.time()
        logger.info("Makeover", f"→ {name} · Stufe {i+1}/{total}: {stage['label']} "
                                f"(Skill {stage['skill']}, Modell {stage.get('model') or _MODEL})")
        prompt = _build_stage_prompt(folder, meta, stage, i + 1, total)

        # Stufe ausführen — bei Claude-Session-Limit bis zu _LIMIT_RETRIES× je _LIMIT_WAIT
        # (Default 7× 1 h) warten und dieselbe Stufe erneut versuchen.
        res: dict = {}
        changed = False
        attempt = 0
        while True:
            if stop and stop():
                break
            say(pct, f"Makeover {i + 1}/{total} · {stage['label']} ({stage['skill']})…")
            fp0 = _fingerprint(folder)
            res = claude_coder.run_prompt(
                str(folder), prompt, branche=meta.get("branche", ""),
                model=stage.get("model") or _MODEL, task=f"makeover:{stage['key']}", name=name,
                on_progress=lambda s, _p=pct, _l=stage["label"], _i=i + 1, _t=total:
                    say(_p, f"Makeover {_i}/{_t} · {_l} · {s}"),
            )
            changed = _fingerprint(folder) != fp0
            if not _is_limit(res, changed):
                break
            # Session-Limit erkannt → Zeichen fürs Dashboard setzen, warten, erneut versuchen.
            claude_limit.mark(stage["label"], _LIMIT_WAIT, site=name)
            # Session-Limit erkannt → warten und erneut versuchen.
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


# ── Freigabe (Discord 1× 👍, sonst Vorschau-Mail) ──────────────────────────────────

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
    # Zentrales Gate: NUR vollständig fertige Seiten (alle 7 Stufen) gehen in die Freigabe.
    # So landen in Discord ausschließlich abstimmungsreife Seiten (außer der Aufrufer erzwingt
    # es via meta['force']=True, z.B. für manuelle Eigene-Marke-Sendungen).
    try:
        if folder and not meta.get("force") and open_stages(folder) > 0:
            logger.info("Makeover", f"finalize_review übersprungen ({name}) — noch "
                                    f"{open_stages(folder)}/{len(STAGES)} Stufen offen.")
            return {"review": False, "reason": "nicht fertig"}
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
        if discord_bot.enabled():
            r = discord_bot.submit_for_review(
                name, stadt, branche, live_url, email, ap, str(folder),
                recipients=recipients, email_text=text, email_subject=betreff, preis=preis)
            if r:
                logger.info("Makeover", f"Zur Discord-Freigabe gepostet: {name}")
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
    except Exception as e:
        logger.warn("Makeover", f"Vorschau-Mail fehlgeschlagen: {type(e).__name__}")
    return {"review": False}
