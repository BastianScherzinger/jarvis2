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

from scrapers._http import ask_ollama, extract_json, best_chat_model
from scrapers.regions import HIGH_VALUE
import logger

# Feste Paketpreise — kein freier Potenzialwert mehr.
# Ollama wählt einen dieser Tiers; bei Ablehnung greift die Heuristik.
PREIS_TIERS = [0, 200, 350, 550, 850, 1200]

_GASTRO = ["restaurant", "café", "cafe", "bäckerei", "baeckerei", "catering",
           "einzelhandel", "laden", "shop", "kiosk"]

# ── Sicherheits-Gewichte (Confidence 0-100) — kalibrierbar ────────────────────
SICHERHEIT_GEWICHTE = {
    "email":             35,   # E-Mail gefunden → direkt anschreibbar (wichtigster Faktor)
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
    if web.get("email_vorhanden"):       bd["E-Mail erreichbar"]   = g["email"]
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


def evaluate(lead: dict, web: dict, social: dict) -> dict:
    """Kombiniert alle Signale → differenzierter Score, Paketpreis, Pitch, E-Mail."""
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

    base = _clamp(sum(breakdown.values()))

    # ── Ollama-Verfeinerung (nur Feinschliff + Texte + Tier-Empfehlung) ─────
    context = (
        f"Betrieb: {lead.get('name')} | Branche: {branche} | Stadt: {lead.get('stadt')}\n"
        f"Website: {'Ja' if has_web else 'NEIN'}"
        + (f" ({alter}J alt)" if has_web and alter >= 0 else "")
        + (f" | Probleme: {', '.join(issues[:3])}" if issues else "") + "\n"
        f"Bewertungen: {rev} ({rating}★) | Bilder: {'ja' if bilder else 'nein'}\n"
        f"Firmengröße: {firmengroesse} | Social: {', '.join(social_media.keys()) or 'keins'}\n"
        f"Telefon: {'ja' if web.get('telefon_verifiziert') else 'nein'} | "
        f"E-Mail: {'ja' if web.get('email_vorhanden') else 'nein'}\n"
        f"Vorläufiger Basis-Score: {base}/100"
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
        '{"anpassung": Zahl -15 bis 15 (Korrektur des Basis-Scores), '
        '"preis_tier": 0 oder 200 oder 350 oder 550 oder 850 oder 1200, '
        '"ist_privat_zahler": 1 oder 0 (1=Einzelbetrieb/KMU, 0=Kette/Konzern), '
        '"beschreibung": "1-2 sachliche Sätze, nur aus den Fakten", '
        '"potenzial_begruendung": "1 Satz warum dieser Preis und nicht mehr/weniger", '
        '"pitch_hook": "1 konkreter Gesprächseinstieg zu einem echten Mangel", '
        '"email_betreff": "kurze Betreffzeile", '
        '"email_text": "sachliche Akquise-Mail, max 80 Wörter, keine Erfindungen"}'
    )

    raw  = ask_ollama(prompt, system=system, model=best_chat_model())
    data = extract_json(raw)

    # Anpassung anwenden (begrenzt)
    try:
        anpassung = int(data.get("anpassung", 0))
        anpassung = max(-15, min(15, anpassung))
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
        f"→ Basis {base} + Ollama {anpassung:+d} = {score} | {lead_typ} | "
        f"Preis {preis}€ | Sicherheit {sicherheit}",
    )

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
        "pitch_hook":            str(data.get("pitch_hook") or "")[:200],
        "email_entwurf":         email_draft,
        "score_breakdown":       json.dumps(breakdown, ensure_ascii=False),
        "sicherheit_breakdown":  json.dumps(sicherheit_bd, ensure_ascii=False),
        "discovered_website":    web.get("discovered_website", ""),
        "bilder_vorhanden":      bilder,
    }
