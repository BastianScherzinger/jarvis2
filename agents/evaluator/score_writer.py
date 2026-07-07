"""
Agent 3 — Score-Writer.

Differenzierter deterministischer Basis-Score (0-100) aus allen verifizierten
Signalen. Ollama verfeinert nur (Feinschliff + Texte). Fällt Ollama aus,
bleibt der differenzierte Basis-Score erhalten.

Preissystem (reale Paketpreise — kein berechneter Erwartungswert mehr):
  0 €   — Betrieb hat bereits eine gute, aktuelle Website → kein Bedarf
  200 € — Mini-Betrieb (1-2 Personen, wenig Bewertungen, einfachste Lösung)
  350 € — Standard-KMU (lokaler Handwerker/Dienstleister ohne oder mit alter Website)
  550 € — Mittlerer Betrieb (mehr Bewertungen, High-Value-Branche, klares Potenzial)
  850 € — Großes Potenzial (viele Bewertungen, starke Branche, echte Lösung sichtbar)
 1200 € — Außergewöhnliches Potenzial (KI sieht Grund für mehr als 850 €)
"""
import json
import os
import statistics

from scrapers._http import ask_ollama, extract_json, best_chat_model, model_for_role
from scrapers.regions import HIGH_VALUE
import logger


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except (ValueError, TypeError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except (ValueError, TypeError):
        return default

# Feste Paketpreise — kein freier Potenzialwert mehr.
# Ollama wählt einen dieser Tiers; bei Ablehnung greift die Heuristik.
PREIS_TIERS = [0, 200, 350, 550, 850, 1200]

_GASTRO = ["restaurant", "café", "cafe", "bäckerei", "baeckerei", "catering",
           "einzelhandel", "laden", "shop", "kiosk"]

# ── Sicherheits-Gewichte (Confidence 0-100) — kalibrierbar ────────────────────
SICHERHEIT_GEWICHTE = {
    "email":             35,   # E-Mail per DNS/MX als zustellbar bestätigt → wichtigster Faktor
    "email_unverifiziert": 22, # E-Mail nur syntaktisch gefunden, Domain nicht verifizierbar
                               # (DNS-Ausfall): weniger Sicherheit, könnte bouncen → NICHT volle 35
    "telefon":           20,   # Telefon verifiziert → erreichbar
    "online_auffindbar": 10,   # Website oder Social vorhanden → real existent
    "adresse":            8,   # Postadresse bekannt
    "aktiv":             12,   # >=5 Bewertungen → aktiver, lebendiger Betrieb
    "privatzahler":      15,   # Einzelbetrieb/KMU entscheidet selbst & zahlt privat
    "kette_malus":      -45,   # Kette/Konzern → zentrale Beschaffung, kaum direkter Abschluss
}

HOT_MIN_SICHERHEIT = 50


def _sicherheit(lead: dict, web: dict, social_media: dict, rev: int,
                ist_privat: int, firmengroesse: str) -> tuple[int, dict]:
    """Belastbarkeit des Leads (0-100) + nachvollziehbare Aufschlüsselung."""
    g  = SICHERHEIT_GEWICHTE
    bd: dict[str, int] = {}
    if web.get("email_vorhanden"):
        # Volle Punkte nur für eine per DNS/MX bestätigt zustellbare Adresse. Eine nur
        # syntaktisch gefundene (Domain nicht verifiziert) zählt reduziert — sie könnte
        # unzustellbar sein und ist als Kontaktkanal weniger belastbar.
        bd["E-Mail erreichbar"] = g["email"] if web.get("email_geprueft") else g["email_unverifiziert"]
    if web.get("telefon_verifiziert"):   bd["Telefon verifiziert"] = g["telefon"]
    if web.get("has_website") or social_media:
        bd["Online auffindbar"] = g["online_auffindbar"]
    if (lead.get("adresse") or "").strip():
        bd["Adresse bekannt"] = g["adresse"]
    if rev >= 5:                          bd["Aktiver Betrieb"]     = g["aktiv"]
    if ist_privat == 1:                   bd["Privatzahler/KMU"]    = g["privatzahler"]
    elif firmengroesse == "Kette":        bd["Kette (unsicher)"]    = g["kette_malus"]
    return _clamp(sum(bd.values())), bd


def _potenzial_fuer_branche(branche: str) -> int:
    """Basis-Branchenwert — als Plausibilitäts-Anker für den Score."""
    b = (branche or "").lower()
    if any(x in b for x in ["zahnarzt", "physiotherapeut", "rechtsanwalt", "steuerberater"]):
        return 3000
    if any(x in b for x in ["elektriker", "dachdecker", "heizung", "klempner", "sanitär", "bauunternehmen"]):
        return 2000
    if any(x in b for x in ["kfz", "werkstatt", "umzug", "reinigung"]):
        return 1500
    return 800


def _clamp(v: int) -> int:
    return max(0, min(100, int(v)))


def _score_0_100(v) -> "int | None":
    """Castet einen LLM-Gesamt-Score robust auf 0-100 (None = ungültig/fehlt)."""
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, n))


def _preis_tier(has_web: int, veraltet: int, firmengroesse: str,
                branche: str, rev: int, score_100: int,
                ollama_tier: int = None, rating: float = 0.0) -> int:
    """Weist einen REALISTISCHEN Paketpreis zu (PREIS_TIERS).

    Ollama-Tier hat Vorrang wenn er in PREIS_TIERS liegt. Sonst greift eine
    mehrfaktorielle Heuristik aus echten Signalen — Branchen-Zahlkraft, Bedarf (Score),
    Etabliertheit (Bewertungen/Rating), Firmengröße und Upgrade-Motiv (veraltete Website).
    So spiegelt der Preis die tatsächliche Zahlkraft + den Projektumfang wider, statt nur
    grob an einer Score-Schwelle zu hängen."""
    b = (branche or "").lower()

    # Gute, aktuelle Website vorhanden → kein Bedarf für uns
    if has_web and not veraltet:
        return 0
    # Kette → kein Direktabschluss möglich
    if firmengroesse == "Kette":
        return 0

    # Ollama-Tier übernehmen wenn valide
    if ollama_tier in PREIS_TIERS:
        return ollama_tier

    high_val   = any(x in b for x in ["zahnarzt", "physiotherapeut", "rechtsanwalt",
                                       "steuerberater", "notar", "facharzt", "arzt", "kanzlei"])
    medium_val = any(x in b for x in ["elektriker", "dachdecker", "heizung",
                                       "klempner", "kfz", "sanitär", "bauunternehmen",
                                       "umzug", "reinigung", "tischler", "maler", "garten"])
    big_betrieb = firmengroesse in ("3-10", "11-50")

    # ── Mehrfaktorieller Wert-Index ──────────────────────────────────────────
    val  = 3 if high_val else (2 if medium_val else 1)        # Branchen-Zahlkraft
    val += 2 if score_100 >= 70 else (1 if score_100 >= 45 else 0)   # Bedarf/Dringlichkeit
    val += 1 if rev >= 20 else 0                              # etablierter Betrieb
    val += 1 if rev >= 80 else 0                              # sehr stark frequentiert
    val += 1 if big_betrieb else 0                            # mehrere Mitarbeiter
    val += 1 if (has_web and veraltet) else 0                 # klares Upgrade-Motiv
    if rating >= 4.5 and rev >= 10:
        val += 1                                             # gut bewertet → investitionsbereit

    # Wert-Index → realistischer Tier
    if val >= 8:
        return 1200
    if val >= 6:
        return 850
    if val >= 4:
        return 550
    if val >= 2:
        return 350
    return 200  # Mindest-Einstiegspreis, solange der Lead überhaupt Bedarf hat


def evaluate(lead: dict, web: dict, social: dict,
             content: dict | None = None, competitor: dict | None = None) -> dict:
    """Kombiniert alle Signale → differenzierter Score, Paketpreis, Pitch, E-Mail.

    `content` = ContentAnalyst-Ergebnis (semantische Website-Bewertung), `competitor` =
    CompetitorAnalyst-Ergebnis (Markt/Wettbewerb). Beide optional (None → Verhalten wie die
    alte 3-Agenten-Kette), damit Bestandsaufrufe/Tests unverändert funktionieren."""
    content       = content or {}
    competitor    = competitor or {}
    issues        = web.get("website_probleme") or []
    has_web       = int(web.get("has_website", 0))
    veraltet      = int(web.get("website_veraltet", 0))
    alter         = int(web.get("website_alter_jahre", -1))
    social_media  = social.get("social_media") or {}
    firmengroesse = social.get("firmengroesse_hinweis", "unbekannt")
    rev           = int(lead.get("anz_bewertungen") or 0)
    rating        = float(lead.get("bewertung") or 0)
    bilder        = int(web.get("bilder_vorhanden", 0))
    branche       = lead.get("branche", "")
    n_probleme    = len(issues)

    breakdown: dict[str, int] = {}

    # ── Website-Situation (größter Faktor) ──────────────────────────────────
    if has_web == 0 and not social_media:
        breakdown["Keine Online-Präsenz"] = 42
    elif has_web == 0 and social_media:
        breakdown["Nur Social Media"] = 36
    elif has_web and veraltet:
        breakdown["Website veraltet"] = 30
    elif has_web and n_probleme >= 2:
        breakdown["Website mit Mängeln"] = 18
    elif has_web and n_probleme == 1:
        breakdown["Website kleinere Mängel"] = 10
    elif has_web:
        breakdown["Moderne Website"] = 4

    # ── Branche ─────────────────────────────────────────────────────────────
    if branche in HIGH_VALUE:
        breakdown["High-Value-Branche"] = 14
    elif any(g in (branche or "").lower() for g in _GASTRO):
        breakdown["Gastro/Einzelhandel"] = 3
    else:
        breakdown["Neutrale Branche"] = 6

    # ── Erreichbarkeit ──────────────────────────────────────────────────────
    if web.get("telefon_verifiziert"):
        breakdown["Telefon verifiziert"] = 8
    if web.get("email_vorhanden"):
        breakdown["E-Mail gefunden"] = 6

    # ── Aktivität (Reviews) ─────────────────────────────────────────────────
    if rev >= 50:
        breakdown["Viele Bewertungen"] = 12
    elif rev >= 20:
        breakdown["Etliche Bewertungen"] = 8
    elif rev >= 5:
        breakdown["Einige Bewertungen"] = 4
    if rating >= 4.5:
        breakdown["Top-Rating"] = 4

    # ── Bilder ──────────────────────────────────────────────────────────────
    if bilder:
        breakdown["Bildpräsenz"] = 4

    # ── Firmengröße / Zahler ────────────────────────────────────────────────
    heur_privat = 0
    if firmengroesse in ("1-2 Personen", "3-10"):
        breakdown["Privatzahler (KMU)"] = 8
        heur_privat = 1
    elif firmengroesse == "Kette":
        breakdown["Kette (kein Zahler)"] = -35
        heur_privat = 0

    # ── Inhalt (ContentAnalyst) — schwacher Inhalt = mehr Bedarf/Upgrade-Motiv ──
    inhalt_vals = [v for v in (content.get("angebot_klarheit"),
                               content.get("text_qualitaet"),
                               content.get("modernitaet")) if isinstance(v, (int, float))]
    content_score = round(sum(inhalt_vals) / len(inhalt_vals) * 10) if inhalt_vals else -1
    if has_web and inhalt_vals:
        avg = content_score / 10.0
        if avg <= 3:
            breakdown["Inhalt sehr schwach"] = 14
        elif avg <= 5:
            breakdown["Inhalt schwach"] = 9
        elif avg <= 7:
            breakdown["Inhalt mittelmäßig"] = 4
        # avg > 7 → guter Inhalt, kein Aufschlag
    if has_web and content.get("mobil_ok") is False:
        breakdown["Nicht mobil-optimiert"] = 6

    # ── Wettbewerb (CompetitorAnalyst) — hoher Marktdruck = höherer Score ──
    markt_score = competitor.get("markt_score")
    if isinstance(markt_score, (int, float)):
        if markt_score >= 8:
            breakdown["Starker Marktdruck"] = 10
        elif markt_score >= 6:
            breakdown["Erhöhter Marktdruck"] = 6
        elif markt_score >= 4:
            breakdown["Mittlerer Marktdruck"] = 3

    base = _clamp(sum(breakdown.values()))

    # ── Ollama-Verfeinerung: echtes Gesamt-Urteil + Texte + Tier-Empfehlung ─────
    # Inhalts-/Wettbewerbs-Zeilen nur anhängen, wenn die neuen Agenten Daten geliefert haben.
    inhalt_zeile = ""
    if inhalt_vals:
        inhalt_zeile = (f"Inhalts-Analyse: Angebot {content.get('angebot_klarheit')}/10, "
                        f"Texte {content.get('text_qualitaet')}/10, "
                        f"Modernität {content.get('modernitaet')}/10, "
                        f"mobil {'ja' if content.get('mobil_ok') else 'nein'}")
        if content.get("conversion_schwaeche"):
            inhalt_zeile += f" | Schwäche: {content['conversion_schwaeche']}"
        inhalt_zeile += "\n"
    markt_zeile = ""
    if isinstance(markt_score, (int, float)):
        markt_zeile = (f"Marktdruck: {markt_score}/10 "
                       f"({competitor.get('wettbewerb_ohne_website', 0)}/"
                       f"{competitor.get('wettbewerb_gesamt', 0)} Konkurrenten ohne Website)\n")

    context = (
        f"Betrieb: {lead.get('name')} | Branche: {branche} | Stadt: {lead.get('stadt')}\n"
        f"Website: {'Ja' if has_web else 'NEIN'}"
        + (f" ({alter}J alt)" if has_web and alter >= 0 else "")
        + (f" | Probleme: {', '.join(issues[:3])}" if issues else "") + "\n"
        f"Bewertungen: {rev} ({rating}★) | Bilder: {'ja' if bilder else 'nein'}\n"
        f"Firmengröße: {firmengroesse} | Social: {', '.join(social_media.keys()) or 'keins'}\n"
        f"Telefon: {'ja' if web.get('telefon_verifiziert') else 'nein'} | "
        f"E-Mail: {'ja' if web.get('email_vorhanden') else 'nein'}\n"
        + inhalt_zeile + markt_zeile +
        f"Vorläufiger Basis-Score (Heuristik): {base}/100"
    )

    system = (
        "Du bist ein nüchterner deutscher B2B-Vertriebsanalyst für Webdesign. "
        "WICHTIG: Nutze AUSSCHLIESSLICH die unten gegebenen Fakten. Erfinde NICHTS "
        "dazu — keine Annahmen über Ort, Geschichte, Mitarbeiter oder Angebot, die "
        "nicht in den Signalen stehen. Bleib sachlich und korrekt. Antworte NUR mit JSON."
    )

    prompt = (
        f"Bewerte diesen Betrieb als möglichen Webdesign-Kunden — nur anhand dieser Fakten:\n"
        f"{context}\n\n"
        "Regeln:\n"
        "- Hoher Verkaufswert = KEINE Website oder veraltete Website + erreichbar + aktiv.\n"
        "- Gute, aktuelle Website = preis_tier 0 (kein Potenzial für uns).\n"
        "- preis_tier muss EXAKT einer dieser Werte sein: 0, 200, 350, 550, 850, 1200.\n"
        "  0   = Betrieb hat bereits eine gute Website → kein Bedarf\n"
        "  200 = Mini-Betrieb (1 Person, Kiosk, sehr kleiner Handwerker)\n"
        "  350 = Standard-KMU (lokaler Handwerker/Dienstleister, keine/alte Website)\n"
        "  550 = Mittlerer Betrieb (mehrere Mitarbeiter, gute Branche, klares Potenzial)\n"
        "  850 = Großes Potenzial (viele Bewertungen, starke Branche, einfache Lösung sichtbar)\n"
        " 1200 = Außergewöhnlich (E-Commerce + Buchung + SEO oder ähnliches Mega-Projekt)\n"
        "- beschreibung: 1-2 sachliche Sätze NUR aus den Fakten, keine Erfindungen.\n"
        "- pitch_hook: 1 konkreter Satz, der einen echten Mangel anspricht.\n\n"
        "Antworte EXAKT in diesem JSON-Format (kein Markdown, deutsche Texte):\n"
        '{"gesamt_score": Zahl 0-100 (dein eigenes Gesamturteil als Verkaufschance, '
        'nutze ALLE Signale inkl. Inhalts- und Marktanalyse), '
        '"anpassung": Zahl -30 bis 30 (nur falls du keinen gesamt_score geben kannst), '
        '"preis_tier": 0 oder 200 oder 350 oder 550 oder 850 oder 1200, '
        '"ist_privat_zahler": 1 oder 0 (1=Einzelbetrieb/KMU, 0=Kette/Konzern), '
        '"beschreibung": "1-2 sachliche Sätze, nur aus den Fakten", '
        '"potenzial_begruendung": "1 Satz warum dieser Preis und nicht mehr/weniger", '
        '"pitch_hook": "1 konkreter Gesprächseinstieg zu einem echten Mangel", '
        '"email_betreff": "kurze Betreffzeile", '
        '"email_text": "sachliche Akquise-Mail, max 80 Wörter, keine Erfindungen"}'
    )

    # Echtes KI-Gesamturteil statt ±15-Kosmetik: Der finale Score ist das gewichtete Mittel
    # aus deterministischem Basis-Score und dem LLM-Gesamturteil (Gewicht JARVIS_SCORE_LLM_WEIGHT,
    # Default 0.5). Optionales Mehrfach-Sampling (JARVIS_SCORE_SAMPLES) nimmt den Median gegen
    # LLM-Rauschen. Harter Fallback bleibt: kein Ollama → reiner deterministischer Basis-Score.
    w       = max(0.0, min(1.0, _env_float("JARVIS_SCORE_LLM_WEIGHT", 0.5)))
    samples = max(1, min(5, _env_int("JARVIS_SCORE_SAMPLES", 1)))
    model   = model_for_role("strong")

    data: dict = {}
    llm_scores: list[int] = []
    for _ in range(samples):
        raw = ask_ollama(prompt, system=system, model=model)
        d   = extract_json(raw)
        if d and not data:
            data = d                     # Texte/Tier vom ersten validen Ergebnis übernehmen
        gs = _score_0_100(d.get("gesamt_score"))
        if gs is not None:
            llm_scores.append(gs)

    if llm_scores:
        llm_score = int(round(statistics.median(llm_scores)))
        score     = _clamp(round(base * (1 - w) + llm_score * w))
        anpassung = score - base         # nur fürs Log
    else:
        # Kein Gesamturteil verfügbar → alte Anpassungslogik (Deckel gelockert auf ±30),
        # sonst reiner Basis-Score.
        try:
            anpassung = max(-30, min(30, int(data.get("anpassung", 0))))
        except (TypeError, ValueError):
            anpassung = 0
        score = _clamp(base + anpassung)

    # Ollama-Tier auslesen (muss exakt in PREIS_TIERS sein)
    try:
        ollama_tier = int(data.get("preis_tier") or -1)
    except (TypeError, ValueError):
        ollama_tier = None
    if ollama_tier not in PREIS_TIERS:
        ollama_tier = None

    # Privat-Zahler: Ollama oder Heuristik (Ollama kann "1"/1.0/true liefern → robust casten)
    try:
        ist_privat = int(data.get("ist_privat_zahler"))
    except (TypeError, ValueError):
        ist_privat = None
    if ist_privat not in (0, 1):
        ist_privat = heur_privat

    # ── Sicherheit ──────────────────────────────────────────────────────────
    sicherheit, sicherheit_bd = _sicherheit(
        lead, web, social_media, rev, ist_privat, firmengroesse
    )

    # ── Paketpreis (ersetzt den alten potenzial × abschluss Wert) ───────────
    preis = _preis_tier(has_web, veraltet, firmengroesse, branche, rev, score, ollama_tier, rating)

    # Für Stats/CSV: potenzial_euro = Branchenbasis (intern), erwartungswert = Paketpreis
    basis_potenzial = _potenzial_fuer_branche(branche)

    # ── Lead-Typ ─────────────────────────────────────────────────────────────
    if preis == 0:
        lead_typ = "Archiviert"       # gute Website vorhanden oder Kette
    elif score >= 72 and sicherheit >= HOT_MIN_SICHERHEIT:
        lead_typ = "Hot"
    elif score >= 48:
        lead_typ = "Warm"
    else:
        lead_typ = "Cold"

    email_draft = ""
    if data.get("email_betreff") and data.get("email_text"):
        email_draft = json.dumps({
            "betreff": str(data["email_betreff"])[:100],
            "text":    str(data["email_text"])[:2000],
        }, ensure_ascii=False)

    logger.eval_(
        "ScoreWriter",
        f"→ Basis {base} {'+ KI-Urteil' if llm_scores else '+ Ollama'} {anpassung:+d} = {score} | "
        f"{lead_typ} | Preis {preis}€ | Sicherheit {sicherheit} | "
        f"Inhalt {content_score if content_score >= 0 else '—'} | Markt {markt_score if markt_score is not None else '—'}",
    )

    # Pitch bevorzugt aus dem Scoring-LLM, sonst den konkreten Haken des ContentAnalysten.
    pitch = str(data.get("pitch_hook") or "").strip() or str(content.get("pitch_haken") or "").strip()

    # Roh-Analysen für Nachvollziehbarkeit (Ranking-Detail) — ohne die große HTML.
    analyse_json = json.dumps({
        "content":    {k: v for k, v in content.items() if k != "html"},
        "competitor": competitor,
    }, ensure_ascii=False)[:4000]

    return {
        "score":                 score,
        "sicherheit":            sicherheit,
        "erwartungswert_euro":   preis,
        "lead_typ":              lead_typ,
        "beschreibung":          str(data.get("beschreibung") or "")[:400],
        "ist_privat_zahler":     ist_privat,
        "firmengroesse":         firmengroesse,
        "potenzial_euro":        basis_potenzial,
        "potenzial_begruendung": str(data.get("potenzial_begruendung") or "")[:300],
        "pitch_hook":            pitch[:200],
        "email_entwurf":         email_draft,
        "score_breakdown":       json.dumps(breakdown, ensure_ascii=False),
        "sicherheit_breakdown":  json.dumps(sicherheit_bd, ensure_ascii=False),
        "discovered_website":    web.get("discovered_website", ""),
        "bilder_vorhanden":      bilder,
        # Neue Bewertungs-Signale (persistiert in DB2)
        "content_score":         content_score,
        "markt_score":           markt_score if markt_score is not None else -1,
        "conversion_schwaeche":  str(content.get("conversion_schwaeche") or "")[:300],
        "analyse_json":          analyse_json,
    }
