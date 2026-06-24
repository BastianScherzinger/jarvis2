"""
overnight_makeover.py — Mehrstufiges Skill-Makeover für gebaute Landing-Pages.

Statt nur content.json-Texte zu ändern (das alte website_improve.enrich), fährt diese
Pipeline eine Seite durch 7 aufeinanderfolgende Design-Stufen — jede mit einem echten
Skill (design-pro / taste / frontend-design) — und lässt den HEADLESS Claude Code
(`claude_coder`) wirklich templates/index.html + static/css/style.css umbauen.

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
from pathlib import Path

import claude_coder
import logger

# Modell für die Stufen — headless-Claude-Alias ('sonnet'/'opus') oder volle ID.
# Sonnet = starkes Design bei moderaten Kosten; per .env auf 'opus' anhebbar.
_MODEL = os.environ.get("JARVIS_MAKEOVER_MODEL", "sonnet").strip()


# ── Die 7 Stufen ───────────────────────────────────────────────────────────────
# Echte, mitgelieferte Skills (claude_skills.ensure_installed → ~/.claude/skills/), damit
# der headless Makeover-Claude sie im Webseiten-Ordner laden kann:
#   _UIUX  = «ui-ux-pro-max»        — Design-Intelligenz (Paletten, Font-Pairings, UX-Regeln)
#   _TASTE = «design-taste-frontend»— Anti-Slop-Politur für Landingpages/Redesigns (taste)
#   _PRO   = «design-pro»           — Bündel-Skill (ui-ux-pro-max/impeccable/taste/frontend-pro/shadcn)
# Jede Stufe nutzt das für ihre Facette stärkste Skill.
_UIUX  = "ui-ux-pro-max"
_TASTE = "design-taste-frontend"
_PRO   = "design-pro"

STAGES: list[dict] = [
    {
        "key": "inhalt", "label": "Inhalt & Struktur", "skill": _UIUX,
        "task": (
            "Facette: UX & Conversion (ui-ux-pro-max). Schärfe Inhalt und Seitenstruktur. "
            "Schreibe lead-genaue, glaubwürdige Texte: eine Hero-Headline mit klarem "
            "Nutzenversprechen + Subline, Über-uns, 4–6 KONKRETE Leistungen, echte USPs, "
            "4–5 branchenspezifische FAQ, konkrete CTAs («Kostenlose Anfrage» statt «Senden») "
            "und sichtbare Vertrauenssignale (Bewertung, Erreichbarkeit, Garantien). In 5 "
            "Sekunden muss klar sein: Was ist das, was bringt es mir, was soll ich tun. Bringe "
            "die Sektionen in eine konversionsstarke Reihenfolge und entferne jede Floskel."
        ),
    },
    {
        "key": "layout", "label": "Layout & Hierarchie", "skill": _UIUX,
        "task": (
            "Facette: Visuelle Hierarchie + Spacing (impeccable-design). Überarbeite Layout und "
            "Hierarchie: ein starker Above-the-fold-Hero (Nutzenversprechen + EIN dominanter "
            "primärer CTA + Vertrauenssignal), klar abgegrenzte Sektionen, konsistentes Grid, "
            "F-/Z-Lesemuster. Nutze eine feste Spacing-Skala (4/8/12/16/24/32/48/72) statt "
            "willkürlicher Werte und rhythmischen, großzügigen Weißraum. Sekundäre Aktionen "
            "deutlich leiser als die primäre."
        ),
    },
    {
        "key": "typografie", "label": "Typografie", "skill": _UIUX,
        "task": (
            "Facette: Typografie (impeccable-design §6). Paare einen charakterstarken Display-Font "
            "mit einem ruhigen, gut lesbaren Body-Font (passend zur Branche, Google Fonts korrekt "
            "einbinden; generisches Arial/pures Inter meiden). Definiere eine fluide Typo-Skala mit "
            "clamp(), Zeilenhöhe 1.5–1.7 im Body und eng (1.05–1.2) bei großen Headlines, leicht "
            "negatives letter-spacing bei großen/fetten Headlines, optimale Zeilenlänge. Beste "
            "Lesbarkeit auf Mobil und Desktop."
        ),
    },
    {
        "key": "farbe", "label": "Farbe & Theming", "skill": _UIUX,
        "task": (
            "Facette: Tokens & Theming (shadcn-Prinzipien). Entwickle eine stimmige Markenpalette "
            "rund um die Akzentfarbe: EINE konsequent eingesetzte Akzentfarbe + leicht getönte "
            "Neutrals (kein Grau-Einheitsbrei). Lege ALLE Farben als CSS-Custom-Properties/Tokens "
            "an (--background --foreground --card --muted --border --primary --accent --ring), nutze "
            "HSL/OKLCH für stimmige Abstufungen, sichere WCAG-AA-Kontraste (Text ≥ 4.5:1) und saubere "
            "hover/focus-visible/active-States. Keine Effekt-Häufung (nicht Glow + Gradient + Schatten + Border zugleich)."
        ),
    },
    {
        "key": "politur", "label": "Politur (taste)", "skill": _TASTE,
        "task": (
            "Skill «design-taste-frontend» (taste) — Anti-Slop-Politur & Zurückhaltung. "
            "Weniger, aber besser: jedes Element braucht einen Grund, im Zweifel weglassen. "
            "Nichts darf templated/KI-generiert wirken. "
            "Feinjustiere Spacing-Rhythmus, konsistente Border-Radien und Stroke-Breiten, WEICHE "
            "mehrschichtige Schatten (kein harter Glow), Trennlinien, Icon- und Button-Konsistenz "
            "(ein Icon-Set, eine Strichstärke — keine Emojis als UI-Icons, Inline-SVG nutzen) und "
            "Bildbehandlung. Vervollständige alle Zustände (hover, focus-visible, active, disabled, "
            "loading, empty). Entferne alles, was billig oder KI-generiert wirkt."
        ),
    },
    {
        "key": "motion", "label": "Motion & Interaktion", "skill": _PRO,
        "task": (
            "Facette: Animation (frontend-pro §5). Füge dezente, performante Motion hinzu: sanfte "
            "Scroll-Reveal-Animationen, Hover-Microinteractions und – falls passend – eine "
            "Zähler-Animation. NUR transform/opacity animieren, 150–500 ms, ease-out für Eintritte, "
            "`will-change` gezielt. `prefers-reduced-motion: reduce` respektieren. Hover hebt dezent "
            "an (1–2 px), springt nicht. Nie verspielt oder kitschig."
        ),
    },
    {
        "key": "responsive", "label": "Responsive & QA", "skill": _UIUX,
        "task": (
            "Facette: Mobile-first + Self-Check (frontend-pro §5). Perfekte Darstellung auf Mobil "
            "(echte Breakpoints prüfen), ein mobiler Sticky-Anruf/CTA, Touch-Ziele ≥ 44 px, keine "
            "horizontalen Überläufe, kein CLS. Abschließender Qualitätscheck: Konsole fehlerfrei, "
            "Links/Buttons/Formulare funktionieren, SEO-Struktur intakt — und es MUSS "
            "`python manage.py check` fehlerfrei sein und das Template ohne Fehler rendern."
        ),
    },
]

_ALL_KEYS = {s["key"] for s in STAGES}


# ── content.json Helfer ─────────────────────────────────────────────────────────

def _read_content(folder: Path) -> dict:
    try:
        return json.loads((Path(folder) / "content.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_content(folder: Path, content: dict) -> None:
    try:
        (Path(folder) / "content.json").write_text(
            json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _mark_done(folder: Path, key: str) -> None:
    """Markiert eine Stufe als erledigt (frisch lesen — die KI hat content.json verändert)."""
    content = _read_content(folder)
    done = list(content.get("makeover_stages") or [])
    if key not in done:
        done.append(key)
    content["makeover_stages"] = done
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
    """Anzahl noch offener Makeover-Stufen einer Seite (für die Auswahl im Night-Builder)."""
    done = set(_read_content(Path(folder)).get("makeover_stages") or [])
    return len(_ALL_KEYS - done)


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


def _context_block(folder: Path, meta: dict) -> str:
    """Standardisierte Fakten zu genau dieser Seite/diesem Lead — in JEDEM Stufen-Prompt."""
    c = _read_content(folder)
    name    = (meta.get("name") or c.get("site_name") or "Der Betrieb").strip()
    branche = (meta.get("branche") or c.get("branche") or "").strip()
    stadt   = (meta.get("stadt") or c.get("stadt") or "").strip()
    akzent  = c.get("akzent") or "#c8102e"
    # Kompakter content.json-Auszug (gekürzt, nur als Orientierung)
    dump = json.dumps(c, ensure_ascii=False)
    if len(dump) > 1800:
        dump = dump[:1800] + " …"
    return (
        "BETRIEB (alle Texte müssen 100 % hierzu passen — nichts erfinden):\n"
        f"- Name: {name}\n"
        f"- Branche: {branche}\n"
        f"- Stadt: {stadt}\n"
        f"- Adresse: {c.get('adresse', '')}\n"
        f"- Telefon: {c.get('telefon', meta.get('telefon', ''))}\n"
        f"- E-Mail: {c.get('email', meta.get('email', ''))}\n"
        f"- Bewertung: {meta.get('bewertung', c.get('bewertung', ''))}\n"
        f"- Ansprechpartner: {meta.get('ansprechpartner', '')}\n"
        f"- Aktuelle Akzentfarbe: {akzent}\n"
        f"- Vorhandene Bilder: {', '.join((c.get('fotos') or [])[:6]) or 'hero_image/logo_image siehe content.json'}\n\n"
        f"Aktuelle content.json (Auszug):\n{dump}"
    )


def _build_stage_prompt(folder: Path, meta: dict, stage: dict) -> str:
    context = _context_block(folder, meta)
    return (
        "Du bist Senior-Webdesigner und arbeitest im AKTUELLEN Ordner an einer fertigen, "
        "deployten Django-Landing-Page eines echten lokalen Betriebs. Die Seite rendert aus "
        "content.json über templates/index.html + static/css/style.css (+ static/img, static/js).\n\n"
        f"NUTZE für diese Aufgabe das Skill «{stage['skill']}».\n\n"
        f"{context}\n\n"
        f"AUFGABE — {stage['label']}:\n{stage['task']}\n\n"
        "HARTE REGELN:\n"
        "- Beginne SOFORT und stelle KEINE Rückfragen — setze die Aufgabe autonom vollständig um.\n"
        "- Bearbeite WIRKLICH templates/index.html und static/css/style.css (echtes Design), "
        "nicht nur content.json.\n"
        "- content.json bleibt valides JSON; vorhandene Keys NIE löschen/umbenennen; "
        "hero_image, logo_image und fotos erhalten.\n"
        "- Alles deutsch, konkret, auf genau diesen Betrieb zugeschnitten — kein Lorem/Platzhalter, "
        "kein KI-Geschwurbel.\n"
        "- Minimaler, gezielter Diff für genau diese Aufgabe; bestehende funktionierende Teile "
        "nicht zerstören.\n"
        "- Am Ende MUSS `python manage.py check` fehlerfrei sein und das Template ohne Fehler rendern.\n"
        "Fasse zum Schluss in genau einem Satz zusammen, was du verändert hast."
    )


# ── Hauptlauf ─────────────────────────────────────────────────────────────────────

def run_makeover(folder: "str | Path", meta: dict, say=None, stop=None) -> dict:
    """Fährt die Seite durch alle noch offenen Makeover-Stufen (resume-fähig).
    say(progress:int, text:str) meldet Fortschritt; stop() bricht sauber ab.
    Gibt {ok, stages_done (neu in diesem Lauf), all_done, reason}."""
    folder = Path(folder)
    say = say or (lambda p, t: None)

    if not folder.is_dir():
        return {"ok": False, "reason": "Ordner nicht gefunden", "all_done": False, "stages_done": []}
    if not claude_coder.is_available():
        say(100, "Claude-CLI fehlt — Makeover nicht möglich (npm i -g @anthropic-ai/claude-code).")
        return {"ok": False, "reason": "claude-CLI fehlt", "all_done": False, "stages_done": []}

    # Sauberer Resume: eine beim letzten Mal abgebrochene (uncommittete) Stufe verwerfen.
    _reset_dirty(folder)

    done = set(_read_content(folder).get("makeover_stages") or [])
    name = meta.get("name", "?")
    new_done: list[str] = []
    total = len(STAGES)

    for i, stage in enumerate(STAGES):
        if stop and stop():
            break
        if stage["key"] in done:
            continue
        pct = 8 + int(i / total * 82)
        say(pct, f"Makeover {i + 1}/{total} · {stage['label']} ({stage['skill']})…")
        logger.info("Makeover", f"{name} — Stufe {stage['label']}")
        prompt = _build_stage_prompt(folder, meta, stage)
        fp0 = _fingerprint(folder)
        res = claude_coder.run_prompt(
            str(folder), prompt, branche=meta.get("branche", ""),
            model=_MODEL, task=f"makeover:{stage['key']}", name=name,
        )
        if not res.get("ok"):
            logger.warn("Makeover", f"Stufe '{stage['label']}' übersprungen: {str(res.get('reason', ''))[:140]}")
            continue

        summ = res.get("summary") or ""
        # Eine Stufe gilt NUR als erledigt, wenn sie wirklich Dateien geändert hat —
        # sonst (Session-Limit, reine Rückfrage o.ä.) würde eine leere Stufe für immer
        # übersprungen. Bei erkanntem Limit pausieren (Resume später möglich).
        if _fingerprint(folder) == fp0:
            logger.warn("Makeover", f"Stufe '{stage['label']}' ohne Datei-Änderung — nicht markiert: {summ[:90]}")
            if _looks_limited(summ):
                say(95, "Claude-Session-Limit erreicht — Makeover pausiert (später fortsetzbar).")
                logger.warn("Makeover", "Claude-Session-Limit — Pipeline pausiert; Resume beim nächsten Lauf.")
                return {"ok": False, "reason": "session_limit",
                        "stages_done": new_done, "all_done": all_done(folder)}
            continue

        _mark_done(folder, stage["key"])
        _git_commit(folder, f"Makeover: {stage['label']} — {summ[:80]}")
        new_done.append(stage["key"])
        try:
            logger.activity("Makeover", stage["label"], name, "✨", "build")
        except Exception:
            pass

    return {"ok": True, "stages_done": new_done, "all_done": all_done(folder)}


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
    # Eigene-Marke-Empfänger (vom Nutzer im Formular eingegeben) aus content.json holen.
    recipients = meta.get("recipients") or _read_content(Path(folder)).get("custom_recipients") or None

    # Angebots-Mail-Text vorbauen (für Discord-Vorschau + Fallback-Mail)
    betreff = text = html_mail = ""
    try:
        import offer_mail
        betreff, text, html_mail = offer_mail.build(name, live_url, branche, stadt, ap)
    except Exception:
        pass

    try:
        import discord_bot
        if discord_bot.enabled():
            r = discord_bot.submit_for_review(
                name, stadt, branche, live_url, email, ap, str(folder),
                recipients=recipients, email_text=text, email_subject=betreff)
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
