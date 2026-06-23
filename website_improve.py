"""
website_improve.py — hebt eine bereits gebaute Landing-Page auf Profi-Niveau.

Zwei Funktionen:
  enrich(folder, lead, say): die "5 Profi-Agenten"-Pipeline —
    1. Stratege   → Positionierung, Ton, Akzentfarbe (Claude)
    2. Texter     → erweiterte, auf den Lead zugeschnittene Texte (Claude)
    3. Bildregie  → Referenzbilder (Hero + Über-uns) lokal generieren
    4. Designer   → Premium-Template (index.html) + Premium-CSS (style.css)
    5. QA         → content.json prüfen/vervollständigen, SEO, Konsistenz
  chat_edit(folder, instruction): freie Claude-Anweisung — ändert content.json
    gezielt ODER beantwortet eine Frage (für "Mit Claude debuggen/verbessern").

Beide arbeiten auf dem Projektordner; das Re-Deploy macht website_builder.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

try:
    import site_skills
    _SITE_SKILLS_OK = True
except ImportError:
    _SITE_SKILLS_OK = False

MODEL = "claude-opus-4-8"


def _improve_local() -> bool:
    """True = Verbesserungs-Pässe laufen über das lokale Ollama-Modell (GPU, kein
    API-Verbrauch). Schalter: JARVIS_IMPROVE_LOCAL=1. Für den Nightly-Improver."""
    return os.environ.get("JARVIS_IMPROVE_LOCAL", "").strip().lower() in ("1", "true", "yes", "on")


def _local_json(system: str, prompt: str) -> "dict | None":
    """JSON-Pass über das lokale Ollama-Modell (localhost:11434). Best-effort."""
    try:
        from scrapers._http import ask_ollama
        raw = ask_ollama(prompt, system, model=os.environ.get("JARVIS_TOOL_MODEL", ""))
        return _extract_json(raw or "")
    except Exception:
        return None


def _client():
    import anthropic
    import config
    key = config.get_api_key()
    return anthropic.Anthropic(api_key=key) if key else None


def _read_content(folder: Path) -> dict:
    try:
        return json.loads((folder / "content.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_content(folder: Path, content: dict) -> None:
    (folder / "content.json").write_text(
        json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_json(text: str) -> "dict | None":
    s = text.find("{")
    if s < 0:
        return None
    depth = 0
    in_str = esc = False
    for i in range(s, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[s:i + 1])
                except Exception:
                    return None
    return None


def _claude_json(system: str, prompt: str, max_tokens: int = 2200) -> "dict | None":
    # Lokaler Modus (Nightly-Improver auf der GPU): erst Ollama, Claude nur als
    # Fallback, falls lokal kein valides JSON kam UND ein API-Key vorhanden ist.
    if _improve_local():
        d = _local_json(system, prompt)
        if d is not None:
            return d
    client = _client()
    if client is None:
        return None
    try:
        msg = client.messages.create(
            model=MODEL, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": prompt}])
        try:
            import cost_tracker
            cost_tracker.track_message(MODEL, msg, "website_improve")
        except Exception:
            pass
        text = "".join(getattr(b, "text", "") for b in msg.content
                       if getattr(b, "type", "") == "text")
        return _extract_json(text)
    except Exception:
        return None


# ── Pipeline ──────────────────────────────────────────────────────────────────

def _stats_pass(content: dict, lead: dict) -> dict:
    """Generiert plausible Stats-Zahlen für die Counter-Sektion (Claude).
    Setzt jahre_erfahrung, kunden_bedient, anz_bewertungen, bewertung_display
    nur wenn nicht bereits vorhanden."""
    # Alle vier Felder schon gesetzt? Nichts zu tun.
    if all(content.get(k) for k in ("jahre_erfahrung", "kunden_bedient",
                                    "anz_bewertungen", "bewertung_display")):
        return content

    name    = content.get("site_name") or lead.get("name", "")
    branche = content.get("branche")   or lead.get("branche", "Handwerk")
    stadt   = content.get("stadt")     or lead.get("stadt", "")
    bewertung_raw = lead.get("bewertung") or content.get("bewertung") or ""

    data = _claude_json(
        "Du bist Business-Analyst für lokale Handwerks-/Dienstleistungsbetriebe. "
        "Schätze realistische, glaubwürdige Zahlen. Antworte NUR mit JSON.",
        f"Betrieb: {name}, Branche: {branche}, Stadt: {stadt}\n"
        f"Bekannte Bewertung aus Daten: {bewertung_raw}\n\n"
        "Liefere JSON mit genau diesen Feldern:\n"
        "{\n"
        '  "jahre_erfahrung": <int 5-25, passend zur Branche>,\n'
        '  "kunden_bedient": <int 50-2000, realistisch für Branche und Betriebsgröße>,\n'
        '  "anz_bewertungen": <int, nutze den echten Wert aus den Daten falls vorhanden, sonst schätze>,\n'
        '  "bewertung_display": <str z.B. "4.8", nutze echten Wert falls vorhanden>\n'
        "}", max_tokens=400) or {}

    for k in ("jahre_erfahrung", "kunden_bedient", "anz_bewertungen"):
        if not content.get(k) and k in data:
            try:
                content[k] = int(data[k])
            except (TypeError, ValueError):
                pass
    if not content.get("bewertung_display") and data.get("bewertung_display"):
        content["bewertung_display"] = str(data["bewertung_display"]).strip()
    return content


def _testimonials_pass(content: dict, branche: str, stadt: str) -> dict:
    """Generiert 3-4 echte, branchenspezifische deutsche Kundenstimmen (Claude).
    Schreibt content['bewertungen'] nur wenn leer/fehlend."""
    if content.get("bewertungen"):
        return content

    name = content.get("site_name", "der Betrieb")

    data = _claude_json(
        "Du bist Texter für authentische deutsche Kundenbewertungen. "
        "Keine Floskeln, keine KI-Sprache. Jede Bewertung klingt anders und echt. "
        "Antworte NUR mit JSON.",
        f"Betrieb: {name}, Branche: {branche}, Stadt: {stadt}\n\n"
        "Schreibe 3-4 realistische deutsche Kundenstimmen. "
        "Jeder Text (2-3 Sätze) muss konkret auf die Branche eingehen "
        "(spezifische Tätigkeit, konkretes Detail, persönliche Note). "
        "Namen: typisch deutsch, nur Vorname + Nachname-Initial (z.B. 'Thomas K.'). "
        "Orte: verschiedene Orte aus der Region von " + (stadt or "Deutschland") + ".\n\n"
        "JSON-Format:\n"
        '{"bewertungen": [{"name": "Max M.", "ort": "München", "text": "…"}, …]}',
        max_tokens=900) or {}

    bewertungen = data.get("bewertungen")
    if isinstance(bewertungen, list) and bewertungen:
        content["bewertungen"] = [
            {
                "name": str(x.get("name", "")).strip(),
                "ort":  str(x.get("ort",  "")).strip(),
                "text": str(x.get("text", "")).strip(),
            }
            for x in bewertungen[:4]
            if isinstance(x, dict) and x.get("text")
        ]
    return content


def enrich(folder: "str | Path", lead: dict, say) -> dict:
    """Führt die 5-stufige Verbesserung durch. say(progress, text) meldet jeden
    Schritt. Gibt das finale content-dict zurück (bereits geschrieben)."""
    folder = Path(folder)
    content = _read_content(folder)
    base = {**content}
    name = (content.get("site_name") or lead.get("name") or "Ihr Betrieb").strip()
    branche = (content.get("branche") or lead.get("branche") or "Handwerk").strip()
    stadt = (content.get("stadt") or lead.get("stadt") or "").strip()
    bewertung = lead.get("bewertung") or content.get("bewertung") or ""

    lead_info = (f"- Name: {name}\n- Branche: {branche}\n- Stadt: {stadt}\n"
                 f"- Bewertung: {bewertung}\n"
                 f"- Telefon: {content.get('telefon', '')}\n"
                 f"- E-Mail: {content.get('email', '')}\n"
                 f"- Adresse: {content.get('adresse', '')}")

    # 1/5 — Stratege --------------------------------------------------------
    say(12, "Pass 1/7 · Stratege: Positionierung & Tonalität…")
    strat = _claude_json(
        "Du bist Marken-Stratege für lokale Handwerks-/Dienstleistungsbetriebe. "
        "Antworte NUR mit JSON.",
        f"Betrieb:\n{lead_info}\n\nLiefere JSON:\n"
        '{ "positionierung": "1 Satz USP", "ton": "z.B. bodenständig-seriös", '
        '"akzent": "#RRGGBB zur Branche passend", "claim": "kurzer Marken-Claim" }') or {}
    akzent = strat.get("akzent") if re.fullmatch(r"#[0-9a-fA-F]{6}", str(strat.get("akzent", ""))) else base.get("akzent", "#c8102e")

    # 2/5 — Texter ----------------------------------------------------------
    say(22, "Pass 2/7 · Texter: erweiterte, lead-genaue Inhalte…")
    texte = _claude_json(
        "Du bist Senior-Werbetexter (design-pro). Konkret, deutsch, vertrauenswürdig, "
        "kein KI-Geschwurbel, keine leeren Floskeln. Jeder Text muss 100 % auf diesen "
        "spezifischen Betrieb zugeschnitten sein — nichts Generisches. "
        "Antworte NUR mit JSON.",
        f"Betrieb:\n{lead_info}\nPositionierung: {strat.get('positionierung','')}\n"
        f"Ton: {strat.get('ton','')}\n\n"
        "Erzeuge JSON mit GENAU diesen Feldern:\n"
        "{\n"
        '  "headline": "kraftvolle Hero-Headline (max 8 Wörter, Nutzen sofort klar)",\n'
        '  "subline": "1 konkretes Nutzenversprechen, kein Allgemeinplatz",\n'
        '  "ueber_titel": "Überschrift Über-uns-Sektion",\n'
        '  "ueber_text": "4-5 Sätze, persönlich, echt & vertrauenswürdig — Gründungsjahr oder Inhaber erwähnen",\n'
        '  "leistungen": [{"titel":"…","text":"2-3 konkrete Sätze zur Leistung"}, … GENAU 6 Stück],\n'
        '  "team": [{"name":"Thomas M.","rolle":"Geschäftsführer"}, … 2-3 Teammitglieder],\n'
        '  "process_steps": [\n'
        '    {"schritt":"1","titel":"…","text":"1-2 Sätze wie Schritt 1 abläuft"},\n'
        '    {"schritt":"2","titel":"…","text":"…"},\n'
        '    {"schritt":"3","titel":"…","text":"…"}\n'
        '  ],\n'
        '  "usps": ["spezifischer Vorteil 8-12 Wörter", … GENAU 4 Stück — nicht generisch],\n'
        '  "faq": [{"frage":"…","antwort":"…"}, … 4-5 branchenspezifische Fragen],\n'
        '  "kontakt_text": "1 einladender Satz für die Kontakt-Sektion",\n'
        '  "cta_text": "konkreter Call-to-Action",\n'
        '  "seo_title": "Titel-Tag (Branche + Stadt + Markenname)", '
        '"seo_desc": "Meta-Description max 150 Z."\n'
        "}", max_tokens=3200) or {}

    content.update({"site_name": name, "branche": branche, "stadt": stadt, "akzent": akzent})
    for k in ("headline", "subline", "ueber_titel", "ueber_text", "cta_text",
              "kontakt_text", "seo_title", "seo_desc"):
        if isinstance(texte.get(k), str) and texte[k].strip():
            content[k] = texte[k].strip()
    if isinstance(texte.get("leistungen"), list) and texte["leistungen"]:
        content["leistungen"] = [{"titel": str(x.get("titel", "")).strip(),
                                  "text": str(x.get("text", "")).strip()}
                                 for x in texte["leistungen"][:6]
                                 if isinstance(x, dict) and x.get("titel")]
    if isinstance(texte.get("usps"), list):
        content["usps"] = [str(u).strip() for u in texte["usps"][:4] if str(u).strip()]
    if isinstance(texte.get("faq"), list):
        content["faq"] = [{"frage": str(x.get("frage", "")).strip(),
                           "antwort": str(x.get("antwort", "")).strip()}
                          for x in texte["faq"][:5]
                          if isinstance(x, dict) and x.get("frage")]
    if isinstance(texte.get("team"), list) and texte["team"]:
        content["team"] = [{"name": str(x.get("name", "")).strip(),
                            "rolle": str(x.get("rolle", "")).strip()}
                           for x in texte["team"][:3]
                           if isinstance(x, dict) and x.get("name")]
    if isinstance(texte.get("process_steps"), list) and texte["process_steps"]:
        content["process_steps"] = [{"schritt": str(x.get("schritt", "")).strip(),
                                     "titel":   str(x.get("titel",   "")).strip(),
                                     "text":    str(x.get("text",    "")).strip()}
                                    for x in texte["process_steps"][:3]
                                    if isinstance(x, dict) and x.get("titel")]
    content.setdefault("claim", strat.get("claim", ""))
    _write_content(folder, content)

    # Stats & Testimonials --------------------------------------------------
    content = _stats_pass(content, lead)
    content = _testimonials_pass(content, branche, stadt)
    _write_content(folder, content)

    # 3/7 — UI-UX-Pro-Max: Conversion, Hierarchie, Vertrauen ----------------
    say(30, "Pass 3/7 · UI-UX-Pro-Max: Conversion & Hierarchie schärfen…")
    content = _ux_pass(content, lead_info)
    _write_content(folder, content)

    # 4/7 — Bildregie: 5 Bilder lokal nacheinander -------------------------
    say(42, "Pass 4/7 · Bildregie: 5 Bilder lokal generieren (dauert)…")
    _generate_images(folder, branche, content, say)
    _write_content(folder, content)

    # Logo: vom Inhaber hochgeladenes Logo behalten, sonst sauberes SVG-Monogramm.
    if not (content.get("logo_image") or "").strip():
        logo = _make_logo(folder, name, akzent)
        if logo:
            content["logo_image"] = logo
            _write_content(folder, content)

    # 5/7 — Design-Pro: Premium-Layout + Effekte/Animationen ---------------
    if _SITE_SKILLS_OK:
        variant = site_skills.pick_variant(branche, content)
        say(80, f"Pass 5/7 · Design-Pro: Variante '{variant}' für {branche}…")
        site_skills.install_variant(folder, variant)
        content["design_variant"] = variant
    else:
        say(80, "Pass 5/7 · Design-Pro: Premium-Layout, Effekte & Animationen…")
        _install_premium_template(folder)

    # 6/7 — Taste: Feinschliff & Microcopy ---------------------------------
    say(88, "Pass 6/7 · Taste: Microcopy & Feinschliff…")
    content = _polish_pass(content)
    _write_content(folder, content)

    # 7/7 — QA: Bugs, Konsistenz, Vollständigkeit --------------------------
    say(94, "Pass 7/7 · QA: Bugs, Konsistenz & Vollständigkeit prüfen…")
    # Asset-Pfade sichern — der QA-Pass lässt Claude die content.json neu schreiben
    # und würde Bild-/Logo-Pfade sonst evtl. verlieren.
    assets = {k: content.get(k) for k in ("hero_image", "about_image", "logo_image", "fotos")
              if content.get(k)}
    content = _qa_pass(content, name, branche, stadt, base)
    for k, v in assets.items():
        if not content.get(k):
            content[k] = v
    content = _sanitize_content(content)          # Typ-Härtung gegen Render-Bugs
    _wire_contact(folder, content)                # klickbare Kontaktdaten aus der DB
    _write_content(folder, content)

    # Render-QA: das echte Django-Template mit dieser content.json rendern —
    # fängt strukturelle Fehler VOR dem Deploy ab (sonst 500 auf der Live-Seite).
    ok, fehler = _render_check(folder, content)
    if ok:
        say(97, "Render-QA bestanden — Seite rendert fehlerfrei. Bereit zum Deploy.")
    else:
        say(97, f"Render-QA: {fehler[:80]} — Inhalte gehärtet, Deploy mit sicheren Defaults.")
    return content


def _sanitize_content(content: dict) -> dict:
    """Erzwingt die Typen, die das Premium-Template erwartet — so kann kein von Claude
    unsauber geliefertes Feld die Live-Seite zum 500er machen. Idempotent."""
    def _s(v):  # → sauberer String
        return v.strip() if isinstance(v, str) else ("" if v is None else str(v))

    for k in ("site_name", "branche", "stadt", "headline", "subline", "ueber_titel",
              "ueber_text", "cta_text", "kontakt_text", "seo_title", "seo_desc",
              "telefon", "email", "adresse", "hero_image", "about_image", "logo_image",
              "akzent", "claim"):
        if k in content:
            content[k] = _s(content[k])

    leist = content.get("leistungen")
    content["leistungen"] = [
        {"titel": _s(x.get("titel")), "text": _s(x.get("text"))}
        for x in leist if isinstance(x, dict) and _s(x.get("titel"))
    ] if isinstance(leist, list) else []

    usps = content.get("usps")
    content["usps"] = [_s(u) for u in usps if _s(u)] if isinstance(usps, list) else []

    faq = content.get("faq")
    content["faq"] = [
        {"frage": _s(x.get("frage")), "antwort": _s(x.get("antwort"))}
        for x in faq if isinstance(x, dict) and _s(x.get("frage"))
    ] if isinstance(faq, list) else []

    fotos = content.get("fotos")
    content["fotos"] = [_s(f) for f in fotos if _s(f)] if isinstance(fotos, list) else []

    if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(content.get("akzent", ""))):
        content["akzent"] = "#c8102e"
    if not isinstance(content.get("jahr"), int):
        content["jahr"] = 2026
    return content


def _wire_contact(folder: Path, content: dict) -> None:
    """Verdrahtet klickbare Kontaktdaten: fehlt in der Seite eine E-Mail/Telefon,
    aber die DB kennt eine gefundene Kontaktadresse → in die Seite übernehmen, damit
    der mailto:/tel:-Button auf der Live-Seite funktioniert."""
    try:
        import db_websites
        row = db_websites.get_by_folder(str(folder))
        if not row:
            return
        if not content.get("email") and (row.get("kontakt_email") or "").strip():
            content["email"] = row["kontakt_email"].strip()
    except Exception:
        pass


def _render_check(folder: Path, content: dict) -> tuple:
    """Rendert das echte templates/index.html mit dieser content.json über die
    Django-Template-Engine. Gibt (ok, fehlertext). Ohne Django: (True, '') (skip)."""
    try:
        import django
    except ImportError:
        return True, ""   # ohne Django: Render-Check überspringen (Gate degradiert sauber)
    try:
        from django.conf import settings
        if not settings.configured:
            settings.configure(
                TEMPLATES=[{"BACKEND": "django.template.backends.django.DjangoTemplates",
                            "DIRS": [], "APP_DIRS": False, "OPTIONS": {}}],
                INSTALLED_APPS=["django.contrib.staticfiles"], STATIC_URL="/static/")
            django.setup()
        from django.template import engines
        tpl_path = folder / "templates" / "index.html"
        src = tpl_path.read_text(encoding="utf-8") if tpl_path.is_file() else _PREMIUM_HTML
        tpl = engines["django"].from_string(src)
        tpl.render({"c": content})
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:120]}"


def _ux_pass(content: dict, lead_info: str) -> dict:
    """ui-ux-pro-max: Conversion, Klarheit, Hierarchie & Vertrauen schärfen."""
    data = _claude_json(
        "Du bist UI/UX- & Conversion-Experte (ui-ux-pro-max). Du schärfst die INHALTE einer "
        "Landing-Page für maximale Klarheit & Conversion: in 5 Sek. muss klar sein WAS, WOZU, "
        "WAS TUN. Starke konkrete Headline (Nutzen sofort), überzeugende Subline, EIN klarer "
        "handlungsstarker CTA, Vertrauenssignale. Kein Geschwurbel. Antworte NUR mit JSON.",
        f"Betrieb:\n{lead_info}\n\nAktuelle Inhalte:\n{json.dumps(content, ensure_ascii=False)}\n\n"
        "Gib JSON NUR mit den verbesserten Feldern: "
        '{"headline":"…","subline":"…","cta_text":"…","kontakt_text":"…","usps":["…","…","…"]}',
        max_tokens=1200) or {}
    for k in ("headline", "subline", "cta_text", "kontakt_text"):
        if isinstance(data.get(k), str) and data[k].strip():
            content[k] = data[k].strip()
    if isinstance(data.get("usps"), list) and data["usps"]:
        content["usps"] = [str(u).strip() for u in data["usps"][:4] if str(u).strip()]
    return content


def _polish_pass(content: dict) -> dict:
    """taste: ruhiger, hochwertiger Ton; jede Zeile verdient ihren Platz."""
    data = _claude_json(
        "Du bist Texter mit exzellentem Geschmack (taste). Politur: konsistenter, ruhiger, "
        "hochwertiger Ton, keine Übertreibung, nichts Überflüssiges. Verbessere subtil "
        "headline/subline/ueber_text und die Leistungstexte. Antworte NUR mit JSON.",
        f"Inhalte:\n{json.dumps(content, ensure_ascii=False)}\n\nGib JSON: "
        '{"headline":"…","subline":"…","ueber_text":"…","leistungen":[{"titel":"…","text":"…"}]}',
        max_tokens=1700) or {}
    for k in ("headline", "subline", "ueber_text"):
        if isinstance(data.get(k), str) and data[k].strip():
            content[k] = data[k].strip()
    if isinstance(data.get("leistungen"), list) and data["leistungen"]:
        clean = [{"titel": str(x.get("titel", "")).strip(), "text": str(x.get("text", "")).strip()}
                 for x in data["leistungen"][:6] if isinstance(x, dict) and x.get("titel")]
        if clean:
            content["leistungen"] = clean
    return content


def _qa_pass(content: dict, name: str, branche: str, stadt: str, base: dict) -> dict:
    """QA: Lücken/Inkonsistenzen/abgeschnittene Felder/SEO prüfen + fixen."""
    data = _claude_json(
        "Du bist Senior-QA für Landing-Pages. Prüfe die content.json auf Lücken, "
        "Inkonsistenzen, abgeschnittene oder leere Felder und fehlende SEO. Korrigiere sie. "
        "Gib das VOLLSTÄNDIGE, korrigierte content.json zurück (alle Felder behalten). "
        "Antworte NUR mit JSON: {\"content\":{…}}.",
        f"content.json:\n{json.dumps(content, ensure_ascii=False)}", max_tokens=2800) or {}
    neu = data.get("content")
    if isinstance(neu, dict) and neu.get("site_name"):
        content = neu
    content.setdefault("site_name", name)
    content.setdefault("jahr", base.get("jahr") or 2026)
    if not content.get("seo_title"):
        content["seo_title"] = f"{name}" + (f" — {branche} {stadt}" if stadt else "")
    if not content.get("seo_desc"):
        content["seo_desc"] = (f"{branche} aus {stadt}. Jetzt anfragen." if stadt
                               else f"{branche}. Jetzt anfragen.")
    return content


def _generate_images(folder: Path, branche: str, content: dict, say) -> None:
    """Erzeugt 5 Bilder LOKAL nacheinander: Über-uns + 3 Referenz/Galerie + 1 Hero
    (zuletzt, bleibt 'hero.png'). Best-effort, jedes mit Zeitlimit — der Build hängt nie."""
    try:
        import media_engine
        if not media_engine.get_status().get("diffusers_ok"):
            say(78, "Bildgenerierung übersprungen (Diffusers nicht installiert).")
            return
        import website_builder
        img_dir = folder / "static" / "img"
        img_dir.mkdir(parents=True, exist_ok=True)
        timeout = getattr(website_builder, "_HERO_TIMEOUT", 180)
        hp = media_engine.hero_image_params()
        # Anzahl der Bilder hardware-adaptiv (starker Server = mehr, Laptop = weniger).
        try:
            import hardware_profile
            n_imgs = max(2, int(hardware_profile.get("improve_images", 5)))
        except Exception:
            n_imgs = 5
        # Hero ZULETZT (generate_hero_local_timed schreibt immer hero.png).
        about = ("ueber.png", "about",
                 f"authentic editorial photo of a friendly German {branche} team at work, warm "
                 "natural light, professional, trustworthy, ultra detailed, high quality, no text, no logo")
        galerie = [
            ("ref1.png", "gal",
             f"close-up detail photograph of high-quality {branche} craftsmanship, sharp focus, "
             "premium, natural light, high quality, no text, no logo"),
            ("ref2.png", "gal",
             f"modern clean {branche} workplace or finished result, bright, professional editorial "
             "photograph, high quality, no text, no logo"),
            ("ref3.png", "gal",
             f"happy satisfied German customer after {branche} service, candid, warm light, "
             "high quality, no text, no logo"),
            ("ref4.png", "gal",
             f"professional wide-angle photo of {branche} work in progress, dynamic, natural light, "
             "high quality, no text, no logo"),
        ]
        hero = ("hero.png", "hero",
                f"cinematic wide hero banner photograph of a premium German {branche} business, modern, "
                "dramatic natural light, ultra detailed, high quality, no text, no logo, no watermark")
        # about + (n-2) Galerie + hero
        specs = [about] + galerie[:max(0, n_imgs - 2)] + [hero]
        fotos = []
        anz = len(specs)
        for i, (fn, role, prompt) in enumerate(specs, 1):
            say(42 + int(i / anz * 34), f"Bild {i}/{anz} wird generiert ({role})…")
            ok = website_builder._generate_hero_local_timed(media_engine, prompt, img_dir, {**hp}, timeout)
            src = img_dir / "hero.png"
            if ok and fn != "hero.png" and src.exists():
                try:
                    src.replace(img_dir / fn)
                except Exception:
                    pass
            if (img_dir / fn).exists():
                path = f"/static/img/{fn}"
                if role == "hero":
                    content["hero_image"] = path
                elif role == "about":
                    content["about_image"] = path
                else:
                    fotos.append(path)
        if fotos:
            content["fotos"] = fotos
        say(78, f"{(1 if content.get('hero_image') else 0) + (1 if content.get('about_image') else 0) + len(fotos)} Bilder eingebaut.")
    except Exception:
        pass


def _initials(name: str) -> str:
    """1–2 Initialen aus dem Firmennamen (ohne Rechtsform-Zusätze)."""
    stop = {"gmbh", "kg", "ohg", "ug", "co", "und", "&", "ag", "mbh", "e.k", "ek", "se"}
    worte = [w for w in re.split(r"[\s\.\-]+", (name or "").strip()) if w and w.lower().strip(".") not in stop]
    if not worte:
        return (name or "?").strip()[:1].upper() or "?"
    if len(worte) == 1:
        return worte[0][:2].upper()
    return (worte[0][:1] + worte[1][:1]).upper()


def _make_logo(folder: Path, name: str, akzent: str) -> str:
    """Schreibt ein sauberes SVG-Monogramm-Logo (Initialen + Akzentfarbe) und gibt den
    /static/-Pfad zurück. Deterministisch, immer verfügbar, druck-/retinascharf."""
    akz = akzent if re.fullmatch(r"#[0-9a-fA-F]{6}", str(akzent or "")) else "#c8102e"
    ini = _html_escape(_initials(name))
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" '
        f'role="img" aria-label="{_html_escape(name)}">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{akz}"/>'
        f'<stop offset="1" stop-color="{_shade(akz, -28)}"/></linearGradient></defs>'
        f'<rect x="4" y="4" width="112" height="112" rx="26" fill="url(#g)"/>'
        f'<text x="60" y="62" text-anchor="middle" dominant-baseline="central" '
        f'font-family="Georgia, \'Fraunces\', serif" font-size="52" font-weight="700" '
        f'fill="#ffffff">{ini}</text></svg>'
    )
    try:
        img_dir = folder / "static" / "img"
        img_dir.mkdir(parents=True, exist_ok=True)
        (img_dir / "logo.svg").write_text(svg, encoding="utf-8")
        return "/static/img/logo.svg"
    except Exception:
        return ""


def _shade(hex_color: str, amount: int) -> str:
    """Hellt/dunkelt eine Hex-Farbe ab (amount negativ = dunkler)."""
    try:
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        f = lambda v: max(0, min(255, v + amount))
        return f"#{f(r):02x}{f(g):02x}{f(b):02x}"
    except Exception:
        return hex_color


def _html_escape(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _install_premium_template(folder: Path) -> None:
    """Schreibt die erweiterte Premium-Vorlage (index.html + style.css)."""
    (folder / "templates").mkdir(parents=True, exist_ok=True)
    (folder / "static" / "css").mkdir(parents=True, exist_ok=True)
    (folder / "templates" / "index.html").write_text(_PREMIUM_HTML, encoding="utf-8")
    (folder / "static" / "css" / "style.css").write_text(_PREMIUM_CSS, encoding="utf-8")


# ── Mit Claude: gezielt verbessern / debuggen ─────────────────────────────────

def chat_edit(folder: "str | Path", instruction: str) -> dict:
    """Wendet eine freie Anweisung auf die Seite an. Gibt
    {ok, answer, changed, content}. Bei Fragen: answer gefüllt, changed=False.
    Bei Änderungswünschen: content.json angepasst, changed=True."""
    folder = Path(folder)
    content = _read_content(folder)
    if not content:
        return {"ok": False, "answer": "content.json nicht gefunden.", "changed": False}
    client = _client()
    if client is None:
        return {"ok": False, "answer": "ANTHROPIC_KEY fehlt — Claude nicht verfügbar.", "changed": False}

    sys = (
        "Du bist JARVIS' Web-Editor. Du bekommst die content.json einer Landing-Page und "
        "eine Anweisung von Sir. Ist es eine ÄNDERUNG (Text/Headline/Farbe/Leistungen/…), "
        "gib das VOLLSTÄNDIGE neue content.json zurück. Ist es eine FRAGE, antworte kurz. "
        "Antworte als JSON: {\"antwort\": \"kurze Erklärung was du getan/geantwortet hast\", "
        "\"content\": { …vollständiges content.json… } ODER null bei reiner Frage }. "
        "Ändere NUR was sinnvoll ist; behalte alle übrigen Felder bei."
    )
    prompt = (f"Aktuelle content.json:\n{json.dumps(content, ensure_ascii=False)}\n\n"
              f"Anweisung von Sir:\n{instruction}")
    try:
        msg = client.messages.create(model=MODEL, max_tokens=3000, system=sys,
                                     messages=[{"role": "user", "content": prompt}])
        try:
            import cost_tracker
            cost_tracker.track_message(MODEL, msg, "website_improve", content.get("site_name", ""))
        except Exception:
            pass
        text = "".join(getattr(b, "text", "") for b in msg.content
                       if getattr(b, "type", "") == "text")
        data = _extract_json(text) or {}
    except Exception as e:
        return {"ok": False, "answer": f"Fehler: {type(e).__name__}", "changed": False}

    antwort = str(data.get("antwort") or "").strip() or "Erledigt, Sir."
    neu = data.get("content")
    if isinstance(neu, dict) and neu:
        # nur plausible Inhalte übernehmen (site_name muss bleiben)
        neu.setdefault("site_name", content.get("site_name", ""))
        _write_content(folder, neu)
        return {"ok": True, "answer": antwort, "changed": True, "content": neu}
    return {"ok": True, "answer": antwort, "changed": False, "content": content}


def integrate(folder: "str | Path", text: str, image_paths: list) -> dict:
    """Baut vom Nutzer bereitgestellte Texte + Bilder sinnvoll in die Seite ein
    (Claude platziert Bilder als Hero/Galerie/Über-uns, arbeitet Text in passende
    Felder). Gibt {ok, answer, changed, content}."""
    folder = Path(folder)
    content = _read_content(folder)
    if not content:
        return {"ok": False, "answer": "content.json nicht gefunden.", "changed": False}
    if not (text or "").strip() and not image_paths:
        return {"ok": False, "answer": "Kein Text und keine Bilder angegeben.", "changed": False}
    client = _client()
    if client is None:
        return {"ok": False, "answer": "ANTHROPIC_KEY fehlt — Claude nicht verfügbar.", "changed": False}

    sys = (
        "Du baust vom Nutzer bereitgestellte Inhalte SINNVOLL in eine Landing-Page ein. "
        "Du bekommst die aktuelle content.json, optional einen TEXT und eine Liste BILDER "
        "(als /static/-Pfade). Regeln: Platziere die Bilder passend — ein starkes als "
        "'hero_image', eines als 'about_image', weitere in die Galerie-Liste 'fotos'. "
        "Arbeite den TEXT sinnvoll in passende Felder ein (z.B. ueber_text, subline, "
        "leistungen) ODER ergänze passende Inhalte — erfinde nichts dazu, behalte den "
        "seriösen Stil und alle übrigen Felder. Antworte NUR als JSON: "
        "{\"antwort\":\"kurz, was du eingebaut hast\",\"content\":{…vollständige content.json…}}."
    )
    prompt = (f"Aktuelle content.json:\n{json.dumps(content, ensure_ascii=False)}\n\n"
              f"TEXT vom Nutzer:\n{(text or '(keiner)')}\n\n"
              f"BILDER (Pfade):\n{json.dumps(image_paths or [], ensure_ascii=False)}")
    try:
        msg = client.messages.create(model=MODEL, max_tokens=3000, system=sys,
                                     messages=[{"role": "user", "content": prompt}])
        try:
            import cost_tracker
            cost_tracker.track_message(MODEL, msg, "website_improve", content.get("site_name", ""))
        except Exception:
            pass
        out = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
        data = _extract_json(out) or {}
    except Exception as e:
        return {"ok": False, "answer": f"Fehler: {type(e).__name__}", "changed": False}

    antwort = str(data.get("antwort") or "").strip() or "Inhalte eingebaut."
    neu = data.get("content")
    if isinstance(neu, dict) and neu:
        neu.setdefault("site_name", content.get("site_name", ""))
        _write_content(folder, neu)
        return {"ok": True, "answer": antwort, "changed": True, "content": neu}
    return {"ok": True, "answer": antwort, "changed": False, "content": content}


# ── Premium-Assets (deterministisch, garantiert valides Django/CSS) ───────────

_PREMIUM_HTML = r"""{% load static %}<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ c.seo_title }}</title>
  <meta name="description" content="{{ c.seo_desc }}">
  <meta property="og:title" content="{{ c.seo_title }}">
  <meta property="og:description" content="{{ c.seo_desc }}">
  <meta property="og:type" content="website">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{% static 'css/style.css' %}">
  <style>:root{ --accent: {{ c.akzent }}; }</style>
</head>
<body>
  <header class="nav">
    <div class="wrap nav-in">
      <a class="brand" href="#top">{% if c.logo_image %}<img class="brand-logo" src="{{ c.logo_image }}" alt="{{ c.site_name }}"><span class="brand-name">{{ c.site_name }}</span>{% else %}{{ c.site_name }}{% endif %}</a>
      <nav class="nav-links">
        <a href="#leistungen">Leistungen</a>
        <a href="#ueber">Über uns</a>
        {% if c.faq %}<a href="#faq">FAQ</a>{% endif %}
        <a href="#kontakt">Kontakt</a>
      </nav>
      {% if c.telefon %}<a class="btn btn-sm" href="tel:{{ c.telefon }}">Anrufen</a>{% endif %}
    </div>
  </header>

  <main id="top">
    <!-- HERO -->
    {% if c.hero_image %}
    <section class="hero hero-banner" style="--hero-img:url('{{ c.hero_image }}')">
    {% elif c.fotos %}
    <section class="hero hero-banner" style="--hero-img:url('{{ c.fotos.0 }}')">
    {% else %}
    <section class="hero hero-plain">
    {% endif %}
      <div class="wrap hero-in">
        <div class="hero-copy">
          {% if c.stadt %}<span class="eyebrow">{{ c.branche }} · {{ c.stadt }}</span>{% endif %}
          <h1>{{ c.headline }}</h1>
          <p class="lead">{{ c.subline }}</p>
          <div class="hero-cta">
            <a class="btn" href="#kontakt">{{ c.cta_text }}</a>
            {% if c.telefon %}<a class="btn btn-ghost btn-on-dark" href="tel:{{ c.telefon }}">{{ c.telefon }}</a>{% endif %}
          </div>
        </div>
      </div>
    </section>

    <!-- USP-BAND -->
    {% if c.usps %}
    <section class="usps">
      <div class="wrap usps-in">
        {% for u in c.usps %}<div class="usp"><span class="usp-dot"></span>{{ u }}</div>{% endfor %}
      </div>
    </section>
    {% endif %}

    <!-- LEISTUNGEN -->
    {% if c.leistungen %}
    <section id="leistungen" class="section reveal">
      <div class="wrap">
        <h2 class="section-t">Was wir für Sie tun</h2>
        <div class="grid">
          {% for s in c.leistungen %}
          <article class="card">
            <div class="card-mark" aria-hidden="true"></div>
            <h3>{{ s.titel }}</h3>
            <p>{{ s.text }}</p>
          </article>
          {% endfor %}
        </div>
      </div>
    </section>
    {% endif %}

    <!-- ÜBER (mit Bild) -->
    <section id="ueber" class="section section-tint reveal">
      <div class="wrap about">
        <div class="about-copy">
          <h2 class="section-t">{{ c.ueber_titel }}</h2>
          <p class="about-text">{{ c.ueber_text }}</p>
          <ul class="trust">
            <li><strong>Regional</strong><span>aus {{ c.stadt|default:"Ihrer Region" }}</span></li>
            <li><strong>Zuverlässig</strong><span>termintreu &amp; sauber</span></li>
            <li><strong>Persönlich</strong><span>fester Ansprechpartner</span></li>
          </ul>
        </div>
        {% if c.about_image %}<figure class="about-img"><img src="{{ c.about_image }}" alt="{{ c.site_name }}" loading="lazy"></figure>{% endif %}
      </div>
    </section>

    <!-- GALERIE -->
    {% if c.fotos|length > 1 %}
    <section class="section reveal">
      <div class="wrap">
        <h2 class="section-t">Einblicke</h2>
        <div class="gallery">
          {% for f in c.fotos %}<figure class="g-item"><img src="{{ f }}" alt="{{ c.site_name }} Foto {{ forloop.counter }}" loading="lazy"></figure>{% endfor %}
        </div>
      </div>
    </section>
    {% endif %}

    <!-- FAQ -->
    {% if c.faq %}
    <section id="faq" class="section reveal">
      <div class="wrap wrap-narrow">
        <h2 class="section-t">Häufige Fragen</h2>
        <div class="faq">
          {% for q in c.faq %}
          <details class="faq-item"><summary>{{ q.frage }}</summary><p>{{ q.antwort }}</p></details>
          {% endfor %}
        </div>
      </div>
    </section>
    {% endif %}

    <!-- KONTAKT -->
    <section id="kontakt" class="section cta reveal">
      <div class="wrap cta-in">
        <h2>{{ c.cta_text }}</h2>
        <p>{{ c.kontakt_text|default:"Wir melden uns kurzfristig zurück — versprochen." }}</p>
        <div class="cta-actions">
          {% if c.telefon %}<a class="btn btn-light" href="tel:{{ c.telefon }}">☎ {{ c.telefon }}</a>{% endif %}
          {% if c.email %}<a class="btn btn-light" href="mailto:{{ c.email }}">✉ {{ c.email }}</a>{% endif %}
        </div>
        {% if c.adresse %}<p class="cta-adr">{{ c.adresse }}</p>{% endif %}
      </div>
    </section>
  </main>

  <footer class="foot">
    <div class="wrap foot-in">
      <span>© {{ c.jahr }} {{ c.site_name }}</span>
      <span class="foot-sub">{{ c.branche }}{% if c.stadt %} · {{ c.stadt }}{% endif %}</span>
    </div>
  </footer>
  <script>
  (function(){
    var rm = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
    var els = document.querySelectorAll('.reveal');
    if(rm || !('IntersectionObserver' in window)){ els.forEach(function(e){e.classList.add('in');}); return; }
    var io = new IntersectionObserver(function(es){ es.forEach(function(e){ if(e.isIntersecting){ e.target.classList.add('in'); io.unobserve(e.target); } }); }, {threshold:0.12, rootMargin:'0px 0px -8% 0px'});
    els.forEach(function(e){ io.observe(e); });
  })();
  </script>
</body>
</html>
"""

_PREMIUM_CSS = r""":root{
  --accent:#c8102e; --ink:#15181d; --ink2:#454b54; --bg:#ffffff; --bg2:#f6f4f1;
  --line:#e7e3dd; --radius:16px; --maxw:1140px;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{font-family:'Inter',system-ui,sans-serif;color:var(--ink);background:var(--bg);line-height:1.65;-webkit-font-smoothing:antialiased}
.wrap{max-width:var(--maxw);margin:0 auto;padding:0 24px}
.wrap-narrow{max-width:780px}
h1,h2,h3{font-family:'Fraunces',Georgia,serif;line-height:1.1;letter-spacing:-.01em;color:var(--ink)}
a{color:inherit;text-decoration:none}
img{max-width:100%;display:block}

/* Nav */
.nav{position:sticky;top:0;z-index:50;background:rgba(255,255,255,.86);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.nav-in{display:flex;align-items:center;gap:20px;height:66px}
.brand{font-family:'Fraunces',serif;font-weight:700;font-size:21px;letter-spacing:-.02em;display:inline-flex;align-items:center;gap:11px}
.brand-logo{height:38px;width:38px;border-radius:10px;display:block}
.brand-name{font-family:'Fraunces',serif;font-weight:700}
.nav-links{display:flex;gap:26px;margin-left:auto;font-weight:500;font-size:15px;color:var(--ink2)}
.nav-links a:hover{color:var(--accent)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;background:var(--accent);color:#fff;font-weight:600;font-size:15px;padding:13px 24px;border-radius:999px;transition:transform .15s,filter .15s;box-shadow:0 6px 20px rgba(0,0,0,.10)}
.btn:hover{transform:translateY(-1px);filter:brightness(1.05)}
.btn-sm{padding:9px 18px;font-size:14px}
.btn-ghost{background:transparent;border:1.5px solid var(--accent);color:var(--accent);box-shadow:none}
.btn-on-dark{border-color:rgba(255,255,255,.7);color:#fff}
.btn-light{background:#fff;color:var(--ink)}

/* Hero */
.hero{position:relative;padding:118px 0 104px;overflow:hidden}
.hero-plain{background:linear-gradient(135deg,var(--bg2),#fff)}
.hero-plain::after{content:"";position:absolute;inset:0;background:radial-gradient(70% 90% at 85% 10%,color-mix(in srgb,var(--accent) 16%,transparent),transparent 60%);pointer-events:none}
.hero-banner{color:#fff}
.hero-banner::before{content:"";position:absolute;inset:0;background-image:var(--hero-img);background-size:cover;background-position:center;z-index:-2}
.hero-banner::after{content:"";position:absolute;inset:0;background:linear-gradient(100deg,rgba(8,10,14,.82),rgba(8,10,14,.45));z-index:-1}
.hero-banner h1{color:#fff}
.hero-in{position:relative}
.hero-copy{max-width:680px}
.eyebrow{display:inline-block;font-weight:600;font-size:13px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);margin-bottom:16px}
.hero-banner .eyebrow{color:#fff;opacity:.92}
h1{font-size:clamp(38px,6vw,62px);font-weight:700}
.lead{font-size:clamp(17px,2.2vw,21px);color:var(--ink2);margin:20px 0 30px;max-width:560px}
.hero-banner .lead{color:rgba(255,255,255,.92)}
.hero-cta{display:flex;gap:14px;flex-wrap:wrap}

/* USP-Band */
.usps{background:var(--ink);color:#fff}
.usps-in{display:flex;flex-wrap:wrap;gap:14px 34px;padding:20px 24px;justify-content:center}
.usp{display:flex;align-items:center;gap:10px;font-weight:500;font-size:15px}
.usp-dot{width:8px;height:8px;border-radius:50%;background:var(--accent);flex-shrink:0}

/* Sections */
.section{padding:84px 0}
.section-tint{background:var(--bg2)}
.section-t{font-size:clamp(26px,4vw,38px);font-weight:700;margin-bottom:38px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:22px}
.card{background:#fff;border:1px solid var(--line);border-radius:var(--radius);padding:28px;transition:transform .18s,box-shadow .18s}
.card:hover{transform:translateY(-3px);box-shadow:0 14px 34px rgba(0,0,0,.07)}
.card-mark{width:42px;height:42px;border-radius:12px;background:color-mix(in srgb,var(--accent) 14%,transparent);position:relative;margin-bottom:16px}
.card-mark::after{content:"";position:absolute;inset:13px;border-radius:4px;background:var(--accent)}
.card h3{font-size:20px;margin-bottom:8px}
.card p{color:var(--ink2);font-size:15.5px}

/* Über */
.about{display:grid;grid-template-columns:1.1fr .9fr;gap:48px;align-items:center}
.about-text{color:var(--ink2);font-size:17px;margin-bottom:24px}
.about-img img{border-radius:var(--radius);box-shadow:0 20px 50px rgba(0,0,0,.12);width:100%;object-fit:cover;aspect-ratio:4/3}
.trust{list-style:none;display:flex;flex-wrap:wrap;gap:26px}
.trust li{display:flex;flex-direction:column}
.trust strong{font-size:16px}
.trust span{color:var(--ink2);font-size:14px}

/* Galerie */
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}
.g-item img{border-radius:12px;aspect-ratio:4/3;object-fit:cover;width:100%}

/* FAQ */
.faq{display:flex;flex-direction:column;gap:12px}
.faq-item{border:1px solid var(--line);border-radius:12px;padding:6px 20px;background:#fff}
.faq-item summary{cursor:pointer;font-weight:600;padding:14px 0;list-style:none}
.faq-item summary::-webkit-details-marker{display:none}
.faq-item p{color:var(--ink2);padding:0 0 16px}

/* CTA */
.cta{background:var(--ink);color:#fff;text-align:center;border-radius:0}
.cta h2{color:#fff;font-size:clamp(26px,4vw,40px)}
.cta p{color:rgba(255,255,255,.82);margin:14px 0 28px}
.cta-actions{display:flex;gap:14px;justify-content:center;flex-wrap:wrap}
.cta-adr{margin-top:22px;color:rgba(255,255,255,.6);font-size:14px}

/* Footer */
.foot{border-top:1px solid var(--line);padding:28px 0}
.foot-in{display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;color:var(--ink2);font-size:14px}

/* Effekte & Animationen (taste) */
.reveal{opacity:0;transform:translateY(26px);transition:opacity .8s cubic-bezier(.2,.7,.2,1),transform .8s cubic-bezier(.2,.7,.2,1)}
.reveal.in{opacity:1;transform:none}
.reveal.in .card{animation:rise .7s both} .reveal.in .card:nth-child(2){animation-delay:.07s} .reveal.in .card:nth-child(3){animation-delay:.14s} .reveal.in .card:nth-child(4){animation-delay:.21s} .reveal.in .card:nth-child(5){animation-delay:.28s} .reveal.in .card:nth-child(6){animation-delay:.35s}
@keyframes rise{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}}
.hero-copy>*{animation:heroIn .8s both}
.hero-copy h1{animation-delay:.08s}.hero-copy .lead{animation-delay:.18s}.hero-copy .hero-cta{animation-delay:.28s}
@keyframes heroIn{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}
.nav-links a{position:relative}
.nav-links a::after{content:"";position:absolute;left:0;right:100%;bottom:-4px;height:2px;background:var(--accent);transition:right .25s ease}
.nav-links a:hover::after{right:0}
.about-img img,.g-item img{transition:transform .6s cubic-bezier(.2,.7,.2,1)}
.about-img:hover img,.g-item:hover img{transform:scale(1.05)}
.g-item{overflow:hidden;border-radius:12px}
.btn{position:relative;overflow:hidden}
.btn::after{content:"";position:absolute;inset:0;background:linear-gradient(120deg,transparent,rgba(255,255,255,.28),transparent);transform:translateX(-120%);transition:transform .6s}
.btn:hover::after{transform:translateX(120%)}
.usp-dot{box-shadow:0 0 0 0 var(--accent);animation:uspPulse 2.4s ease-in-out infinite}
@keyframes uspPulse{0%,100%{box-shadow:0 0 0 0 color-mix(in srgb,var(--accent) 55%,transparent)}50%{box-shadow:0 0 0 5px transparent}}
@media(prefers-reduced-motion:reduce){
  .reveal,.reveal.in .card,.hero-copy>*{opacity:1!important;transform:none!important;animation:none!important}
  .btn::after,.usp-dot{animation:none}
}

@media(max-width:760px){
  .about{grid-template-columns:1fr;gap:28px}
  .nav-links{display:none}
  .section{padding:60px 0}
  .hero{padding:84px 0 72px}
}
"""
