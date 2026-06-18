"""
Personalisierte Outreach-E-Mails via Ollama — aus Pitch-Hook + Website-Problemen.
"""
import json

from scrapers import _http
import db


def generate_email(lead: dict, persist: bool = True) -> dict:
    """
    Generiert eine personalisierte Akquise-E-Mail für einen Lead.
    Gibt {betreff, text} zurück. Fallback bei Ollama-Ausfall: {..., error:...}.

    persist=True  → speichert email_draft in db.py (DB1) unter lead["id"].
    persist=False → kein DB-Schreibzugriff (z.B. wenn der Mailer eine DB2-Zeile
                    übergibt — deren id gehört NICHT zur DB1-Tabelle).
    """
    name    = (lead.get("name") or "").strip() or "das Unternehmen"
    branche = (lead.get("branche") or "").strip() or "Betrieb"
    stadt   = (lead.get("stadt") or "").strip()
    pitch   = (lead.get("pitch_hook") or "").strip()

    # Website-Probleme aus JSON-Feld extrahieren
    issues_raw = lead.get("website_issues") or ""
    issues_list: list = []
    if issues_raw:
        try:
            parsed = json.loads(issues_raw)
            if isinstance(parsed, list):
                issues_list = parsed
        except Exception:
            issues_list = []
    issues_txt = "; ".join(str(i) for i in issues_list) if issues_list else "keine bekannt"

    if pitch:
        prompt = (
            f"Schreibe eine kurze, persönliche Akquise-E-Mail (max 150 Wörter) "
            f"an {name} ({branche}, {stadt}). Kontext: {pitch}. "
            f"Website-Probleme: {issues_txt}. "
            f"Kein Betreff-Spam, seriös, konkreter Nutzen, klare Handlungsaufforderung "
            f"(kurzes Telefonat). Absender: Webdesign-Dienstleister. "
            f'NUR JSON: {{"betreff": "...", "text": "..."}}'
        )
    else:
        prompt = (
            f"Schreibe eine kurze, persönliche Akquise-E-Mail (max 150 Wörter) "
            f"an {name}, einen {branche}-Betrieb in {stadt}. "
            f"Gehe konkret auf typische Online-Schwächen von {branche}-Betrieben ein "
            f"(z.B. veraltete oder fehlende Website, schlechte Auffindbarkeit). "
            f"Kein Betreff-Spam, seriös, konkreter Nutzen, klare Handlungsaufforderung "
            f"(kurzes Telefonat). Absender: Webdesign-Dienstleister. "
            f'NUR JSON: {{"betreff": "...", "text": "..."}}'
        )

    raw = _http.ask_ollama(prompt)
    if not raw:
        return {"betreff": "", "text": "", "error": "Ollama nicht erreichbar"}

    data = _http.extract_json(raw)
    betreff = str(data.get("betreff", "") or "").strip()[:100]
    text    = str(data.get("text", "") or "").strip()[:2000]

    if not betreff and not text:
        return {"betreff": "", "text": "", "error": "Keine gültige Antwort"}

    result = {"betreff": betreff, "text": text}

    # In DB1 speichern — nur wenn die id wirklich zur leads-Tabelle gehört.
    if persist:
        try:
            lead_id = lead.get("id")
            if lead_id:
                db.set_lead_field(lead_id, "email_draft", json.dumps(result, ensure_ascii=False))
        except Exception:
            pass

    return result
