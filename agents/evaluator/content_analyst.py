"""
Agent (neu) — Content-Analyst.

Bewertet den INHALT der (bereits von web_analyst geladenen) Website semantisch mit einem
lokalen LLM — das war bisher die größte Lücke: web_analyst prüft nur technisch per Regex
(HTTPS/Viewport/Copyright/Legacy-Tags), aber NIE, ob das Angebot klar ist, die Texte gut sind
oder die Seite modern wirkt. Genau das liefert dieser Agent.

Design-Prinzipien (wie der Rest der Evaluator-Pipeline):
  • Nutzt die schon geladene HTML aus web_analyst (kein zweiter HTTP-Fetch).
  • EIN LLM-Call, starkes Modell (model_for_role("strong")).
  • Fällt bei Ollama-Ausfall / fehlender Website auf neutrale Defaults zurück — nie Exception.
  • Kein Lead ohne Website verschwendet einen LLM-Call (keine_website=True, sofort zurück).
"""
from __future__ import annotations

import re

from scrapers._http import ask_ollama, extract_json, model_for_role
import logger


# Neutrale Rückgabe (Ollama aus, keine Website, kaputtes JSON) — nie None/Exception.
_NEUTRAL = {
    "keine_website":        0,
    "angebot_klarheit":     None,   # 0-10, None = nicht bewertet
    "text_qualitaet":       None,
    "modernitaet":          None,
    "mobil_ok":             None,   # True/False/None
    "conversion_schwaeche": "",     # Freitext: wo die Seite Kunden verliert
    "pitch_haken":          "",     # konkreter Aufhänger für die Akquise-Mail
}


def _sichtbarer_text(html: str, limit: int = 4000) -> str:
    """Grober Text-Auszug aus HTML für das LLM (Skripte/Styles raus, Tags weg)."""
    if not html:
        return ""
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    # <title> + Meta-Description vorn anhängen (starke Signale fürs Angebot)
    kopf = []
    mt = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    if mt:
        kopf.append("TITEL: " + re.sub(r"\s+", " ", mt.group(1)).strip())
    md = re.search(r'(?is)<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html)
    if md:
        kopf.append("BESCHREIBUNG: " + re.sub(r"\s+", " ", md.group(1)).strip())
    body = re.sub(r"(?s)<[^>]+>", " ", html)
    body = re.sub(r"\s+", " ", body).strip()
    text = ("\n".join(kopf) + "\n" + body).strip()
    return text[:limit]


def _viewport_vorhanden(html: str) -> "bool | None":
    if not html:
        return None
    return bool(re.search(r'(?i)<meta[^>]+name=["\']viewport["\']', html))


def _cast_0_10(v) -> "int | None":
    try:
        n = int(round(float(v)))
        return max(0, min(10, n))
    except (TypeError, ValueError):
        return None


def analyze(lead: dict, web: dict) -> dict:
    """Semantische Inhaltsbewertung. `web` = Rückgabe von web_analyst.analyze (enthält
    'html' der geladenen Startseite, wenn vorhanden)."""
    res = dict(_NEUTRAL)

    if not int(web.get("has_website", 0)):
        res["keine_website"] = 1
        return res

    html = web.get("html") or ""
    text = _sichtbarer_text(html)
    if not text:
        # Website da, aber kein Text greifbar (JS-App / nicht erreichbar) — kein LLM-Call.
        res["conversion_schwaeche"] = "Kein auslesbarer Seiteninhalt (evtl. reine JS-Seite)."
        return res

    # Technischer Vor-Hinweis fürs Modell (mobil), damit es nicht raten muss.
    mobil = _viewport_vorhanden(html)
    name    = lead.get("name") or "?"
    branche = lead.get("branche") or ""

    system = (
        "Du bist ein nüchterner deutscher Webdesign- und Conversion-Analyst. Bewerte NUR den "
        "gegebenen Seiteninhalt. Erfinde nichts dazu. Antworte AUSSCHLIESSLICH mit JSON."
    )
    prompt = (
        f"Betrieb: {name} | Branche: {branche}\n"
        f"Viewport/mobil-Tag vorhanden: {'ja' if mobil else 'nein/unbekannt'}\n"
        f"--- Seiteninhalt (Auszug) ---\n{text}\n--- Ende ---\n\n"
        "Bewerte die Website als möglicher Kunde eines Webdesign-Angebots. Skalen 0-10 "
        "(0=sehr schlecht/fehlt, 10=exzellent):\n"
        "- angebot_klarheit: Wird sofort klar, was der Betrieb anbietet?\n"
        "- text_qualitaet: Sind die Texte professionell, fehlerfrei, überzeugend?\n"
        "- modernitaet: Wirkt die Seite zeitgemäß oder veraltet?\n"
        "- mobil_ok: true/false — wirkt die Seite für Handys gemacht?\n"
        "- conversion_schwaeche: 1 kurzer Satz, WO die Seite Kunden verliert (oder \"\").\n"
        "- pitch_haken: 1 konkreter Satz, mit dem man den Betrieb auf eine bessere Seite "
        "anspricht (echter, benannter Mangel — keine Floskel).\n\n"
        "Antworte EXAKT so (deutsche Texte, kein Markdown):\n"
        '{"angebot_klarheit": 0-10, "text_qualitaet": 0-10, "modernitaet": 0-10, '
        '"mobil_ok": true oder false, "conversion_schwaeche": "…", "pitch_haken": "…"}'
    )

    raw  = ask_ollama(prompt, system=system, model=model_for_role("strong"))
    data = extract_json(raw)
    if not data:
        # Ollama aus / kaputtes JSON → mobil-Signal wenigstens durchreichen.
        res["mobil_ok"] = mobil
        return res

    res["angebot_klarheit"]  = _cast_0_10(data.get("angebot_klarheit"))
    res["text_qualitaet"]    = _cast_0_10(data.get("text_qualitaet"))
    res["modernitaet"]       = _cast_0_10(data.get("modernitaet"))
    mv = data.get("mobil_ok")
    res["mobil_ok"]          = bool(mv) if isinstance(mv, bool) else (mobil if mobil is not None else None)
    res["conversion_schwaeche"] = str(data.get("conversion_schwaeche") or "")[:300]
    res["pitch_haken"]       = str(data.get("pitch_haken") or "")[:200]

    vals = [v for v in (res["angebot_klarheit"], res["text_qualitaet"], res["modernitaet"])
            if v is not None]
    schnitt = round(sum(vals) / len(vals), 1) if vals else "?"
    logger.eval_("ContentAnalyst", f"✓ {name}: Inhalt Ø {schnitt}/10 "
                 f"(mobil {'ja' if res['mobil_ok'] else 'nein'})")
    return res
