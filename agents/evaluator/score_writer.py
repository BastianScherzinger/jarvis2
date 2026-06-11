"""Agent 3 — Ollama bewertet alle Signale, generiert Score + Pitch + E-Mail."""
import json
from scrapers._http import ask_ollama, extract_json

POTENZIAL_STUFEN = [500, 1500, 3000, 5000]


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


def evaluate(lead: dict, web: dict, social: dict) -> dict:
    """
    Kombiniert alle Signale, ruft Ollama, gibt vollständiges Ergebnis zurück.
    Auch ohne Ollama (Fallback): liefert Heuristik-Ergebnis.
    """
    # Signale zusammenstellen
    issues = web.get("website_probleme") or []
    has_web = lead.get("has_website", 0)
    rev = int(lead.get("anz_bewertungen") or 0)
    rating = float(lead.get("bewertung") or 0)
    firmengroesse = social.get("firmengroesse_hinweis", "unbekannt")

    # Heuristik-Score (Fallback + Anker)
    pts = 0
    if not has_web:          pts += 30
    elif issues:             pts += 15
    if web.get("email_vorhanden"):  pts += 10
    if web.get("telefon_verifiziert"): pts += 8
    if rev >= 10:            pts += 10
    elif rev >= 3:           pts += 5
    if rating >= 4.0:        pts += 8
    if lead.get("bilder_maps"): pts += 5
    if firmengroesse in ("1-2 Personen", "3-10"): pts += 10
    pts = max(0, min(100, pts))

    basis_potenzial = _potenzial_fuer_branche(lead.get("branche", ""))

    # Ollama-Prompt
    context = (
        f"Betrieb: {lead.get('name')} | Branche: {lead.get('branche')} | Stadt: {lead.get('stadt')}\n"
        f"Website: {'Ja' if has_web else 'NEIN'}"
        + (f" | Probleme: {', '.join(issues[:3])}" if issues else "") + "\n"
        f"Bewertungen: {rev} ({rating}★) | Fotos: {'ja' if lead.get('bilder_maps') else 'nein'}\n"
        f"Firmengröße: {firmengroesse} | Social Media: {', '.join(social.get('social_media', {}).keys()) or 'keins'}\n"
        f"Telefon: {'ja' if lead.get('telefon') else 'nein'} | E-Mail gefunden: {'ja' if web.get('email_vorhanden') else 'nein'}"
    )

    system = (
        "Du bist ein erfahrener Vertriebsanalyst für Webdesign-Dienstleistungen. "
        "Analysiere Kleinbetriebe als potenzielle Kunden. Antworte NUR mit JSON."
    )

    prompt = (
        f"Bewerte diesen Betrieb als Webdesign-Kunden:\n{context}\n\n"
        "Antworte EXAKT in diesem JSON-Format (kein Markdown):\n"
        '{"score": 0-100, '
        '"beschreibung": "2-3 Sätze über den Betrieb und seine Online-Situation", '
        '"ist_privat_zahler": 1 oder 0 (1=Einzelbetrieb/KMU zahlt selbst, 0=Kette/zu groß), '
        '"potenzial_euro": eine dieser Zahlen: 500 oder 1500 oder 3000 oder 5000, '
        '"potenzial_begruendung": "1-2 Sätze warum dieser Betrag", '
        '"pitch_hook": "1 kurzer Satz als Gesprächseinstieg, konkret und persönlich", '
        '"email_betreff": "kurze E-Mail-Betreffzeile", '
        '"email_text": "kurze persönliche Akquise-Mail max 100 Wörter"}'
    )

    raw = ask_ollama(prompt, system=system)
    data = extract_json(raw)

    # Validierung + Fallback
    score = data.get("score")
    try:
        score = max(0, min(100, int(score)))
    except (TypeError, ValueError):
        score = pts  # Heuristik-Fallback

    potenzial = data.get("potenzial_euro")
    if potenzial not in POTENZIAL_STUFEN:
        potenzial = basis_potenzial

    ist_privat = data.get("ist_privat_zahler")
    if ist_privat not in (0, 1):
        ist_privat = 1 if firmengroesse in ("1-2 Personen", "3-10") else 0

    lead_typ = "Hot" if score >= 72 else "Warm" if score >= 48 else "Cold"

    email_draft = ""
    if data.get("email_betreff") and data.get("email_text"):
        email_draft = json.dumps({
            "betreff": str(data["email_betreff"])[:100],
            "text":    str(data["email_text"])[:2000],
        }, ensure_ascii=False)

    return {
        "score":                 score,
        "lead_typ":              lead_typ,
        "beschreibung":          str(data.get("beschreibung") or "")[:400],
        "ist_privat_zahler":     ist_privat,
        "firmengroesse":         firmengroesse,
        "potenzial_euro":        potenzial,
        "potenzial_begruendung": str(data.get("potenzial_begruendung") or "")[:300],
        "pitch_hook":            str(data.get("pitch_hook") or "")[:200],
        "email_entwurf":         email_draft,
    }
