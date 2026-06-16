"""
Agent 3 — Score-Writer.

Differenzierter deterministischer Basis-Score (0-100) aus allen verifizierten
Signalen. KEIN flaches 40 mehr. Ollama verfeinert nur (Feinschliff + Texte);
fällt Ollama aus, bleibt der differenzierte Basis-Score erhalten.
"""
import json

from scrapers._http import ask_ollama, extract_json, best_chat_model
from scrapers.regions import HIGH_VALUE
import logger

POTENZIAL_STUFEN = [500, 1500, 3000, 5000]

_GASTRO = ["restaurant", "café", "cafe", "bäckerei", "baeckerei", "catering",
           "einzelhandel", "laden", "shop", "kiosk"]

# ── Sicherheits-Gewichte (Confidence 0-100) — kalibrierbar "für uns" ─────────
# Der Bedarfs-Score (oben) sagt, wie SEHR ein Betrieb Webdesign braucht. Die
# Sicherheit sagt, wie BELASTBAR der Lead ist: erreichbar (E-Mail/Telefon),
# zahlungsfähig (Privatzahler/KMU) und eindeutig verifiziert. Zusammen ergeben
# sie den Erwartungswert (€) = "wo verdienen wir am sichersten Geld".
# Werte hier anpassen, um die Rangliste an die eigene Verkaufsrealität zu eichen.
SICHERHEIT_GEWICHTE = {
    "email":             35,   # E-Mail gefunden → direkt anschreibbar (wichtigster Faktor)
    "telefon":           20,   # Telefon verifiziert → erreichbar
    "online_auffindbar": 10,   # Website oder Social vorhanden → real existent
    "adresse":            8,   # Postadresse bekannt
    "aktiv":             12,   # >=5 Bewertungen → aktiver, lebendiger Betrieb
    "privatzahler":      15,   # Einzelbetrieb/KMU entscheidet selbst & zahlt privat
    "kette_malus":      -45,   # Kette/Konzern → zentrale Beschaffung, kaum direkter Abschluss
}

# Mindest-Sicherheit, ab der ein bedarfsstarker Lead als "Hot" gilt (sonst "Warm").
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
    """Basis-Schätzung ohne KI — als Plausibilitäts-Anker."""
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


def evaluate(lead: dict, web: dict, social: dict) -> dict:
    """Kombiniert alle Signale → differenzierter Score, Pitch, E-Mail."""
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
    # Höchster Verkaufswert: keine Website. Dann veraltet. Moderne Seite = wenig Bedarf.
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
    if firmengroesse in ("1-2 Personen", "3-10"):
        breakdown["Privatzahler (KMU)"] = 8
        heur_privat = 1
    elif firmengroesse == "Kette":
        breakdown["Kette (kein Zahler)"] = -35
        heur_privat = 0
    else:
        heur_privat = 0

    base = _clamp(sum(breakdown.values()))

    basis_potenzial = _potenzial_fuer_branche(branche)

    # ── Ollama-Verfeinerung (nur Feinschliff) ───────────────────────────────
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
        "- Moderne, gepflegte Website = niedriger Verkaufswert (brauchen nichts).\n"
        "- beschreibung: 1-2 sachliche Sätze NUR aus den Fakten, keine Erfindungen.\n"
        "- pitch_hook: 1 konkreter Satz, der einen echten Mangel anspricht.\n\n"
        "Antworte EXAKT in diesem JSON-Format (kein Markdown, deutsche Texte):\n"
        '{"anpassung": Zahl -15 bis 15 (Korrektur des Basis-Scores), '
        '"beschreibung": "1-2 sachliche Sätze, nur aus den Fakten", '
        '"potenzial_euro": 500 oder 1500 oder 3000 oder 5000, '
        '"ist_privat_zahler": 1 oder 0 (1=Einzelbetrieb/KMU, 0=Kette/Konzern), '
        '"potenzial_begruendung": "1 Satz warum dieser Betrag", '
        '"pitch_hook": "1 konkreter Gesprächseinstieg zu einem echten Mangel", '
        '"email_betreff": "kurze Betreffzeile", '
        '"email_text": "sachliche Akquise-Mail, max 80 Wörter, keine Erfindungen"}'
    )

    raw  = ask_ollama(prompt, system=system, model=best_chat_model())
    data = extract_json(raw)

    # Anpassung anwenden (begrenzt) — bei Fehlschlag 0.
    try:
        anpassung = int(data.get("anpassung", 0))
        anpassung = max(-15, min(15, anpassung))
    except (TypeError, ValueError):
        anpassung = 0

    score = _clamp(base + anpassung)

    potenzial = data.get("potenzial_euro")
    if potenzial not in POTENZIAL_STUFEN:
        potenzial = basis_potenzial

    ist_privat = data.get("ist_privat_zahler")
    if ist_privat not in (0, 1):
        ist_privat = heur_privat

    # ── Sicherheit + Erwartungswert ─────────────────────────────────────────
    sicherheit, sicherheit_bd = _sicherheit(
        lead, web, social_media, rev, ist_privat, firmengroesse
    )
    # Abschlusswahrscheinlichkeit ≈ Bedarf × Sicherheit (0..1). Erwartungswert =
    # potenzieller Auftragswert × Abschlusswahrscheinlichkeit → "sicherstes Geld".
    abschluss      = round((score / 100.0) * (sicherheit / 100.0), 3)
    erwartungswert = int(round(potenzial * abschluss))

    # Hot nur bei hohem Bedarf UND ausreichender Sicherheit (sonst max. Warm).
    if score >= 72 and sicherheit >= HOT_MIN_SICHERHEIT:
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
        f"Sicherheit {sicherheit} | EW {erwartungswert}€ (von {potenzial}€)",
    )

    return {
        "score":                 score,
        "sicherheit":            sicherheit,
        "erwartungswert_euro":   erwartungswert,
        "lead_typ":              lead_typ,
        "beschreibung":          str(data.get("beschreibung") or "")[:400],
        "ist_privat_zahler":     ist_privat,
        "firmengroesse":         firmengroesse,
        "potenzial_euro":        potenzial,
        "potenzial_begruendung": str(data.get("potenzial_begruendung") or "")[:300],
        "pitch_hook":            str(data.get("pitch_hook") or "")[:200],
        "email_entwurf":         email_draft,
        "score_breakdown":       json.dumps(breakdown, ensure_ascii=False),
        "sicherheit_breakdown":  json.dumps(sicherheit_bd, ensure_ascii=False),
        "discovered_website":    web.get("discovered_website", ""),
        "bilder_vorhanden":      bilder,
    }
