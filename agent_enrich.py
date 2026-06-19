"""
Akquise-Anreicherung on demand für den Claude-Dashboard-Agenten.

Wendet die VOLLE Bewertungs-Pipeline (Website-Analyse → Social → Score) auf einen
beliebigen Betrieb an und liefert sofort die Akquise-Tauglichkeit — ohne dass der
Betrieb erst gescrapt werden muss. Nutzt exakt dieselben Module wie der Evaluator.
"""
from __future__ import annotations

import json


def enrich(name: str, stadt: str = "", branche: str = "") -> str:
    name = (name or "").strip()
    if not name:
        return "Kein Betriebsname angegeben."

    from agents.evaluator.web_analyst import analyze
    from agents.evaluator.social_researcher import research
    from agents.evaluator.score_writer import evaluate

    lead = {"name": name, "stadt": stadt.strip(), "branche": branche.strip()}

    try:
        web = analyze(lead)
    except Exception as e:
        return f"Website-Analyse fehlgeschlagen: {type(e).__name__}"
    try:
        social = research(lead, web.get("search_hits"))
    except Exception:
        social = {"social_media": {}}
    try:
        scored = evaluate(lead, web, social)
    except Exception as e:
        return f"Scoring fehlgeschlagen: {type(e).__name__}"

    # — Website-Status / Akquise-Signal —
    has_web = int(web.get("has_website", 0))
    if not has_web:
        web_status = "KEINE eigene Website  → starkes Akquise-Signal"
    elif web.get("website_veraltet"):
        alter = web.get("website_alter_jahre", -1)
        web_status = f"Veraltete Website ({alter}J)  → gutes Akquise-Signal"
    else:
        web_status = "Moderne Website  → geringer Bedarf"

    probleme = web.get("website_probleme") or []
    social_keys = list((social.get("social_media") or {}).keys())
    eur = lambda n: f"{int(n or 0):,}".replace(",", ".") + " €"

    lines = [
        f"Akquise-Analyse: {name}" + (f" ({stadt})" if stadt else ""),
        f"  Website:   {web_status}",
    ]
    if web.get("discovered_website"):
        lines.append(f"  Gefunden:  {web['discovered_website']}")
    if probleme:
        lines.append(f"  Mängel:    {', '.join(probleme[:5])}")
    lines += [
        f"  Kontakt:   " + (("E-Mail " + web.get("email_adresse", "")) if web.get("email_vorhanden")
                            else "keine E-Mail") + (f" · {web.get('ansprechpartner')}" if web.get("ansprechpartner") else ""),
        f"  Social:    {', '.join(social_keys) or 'keins'}",
        f"  Bilder:    {'ja' if web.get('bilder_vorhanden') else 'nein'}",
        "",
        f"  → BEDARF-SCORE:   {scored.get('score')}/100  ({scored.get('lead_typ')})",
        f"  → SICHERHEIT:     {scored.get('sicherheit')}/100",
        f"  → ERWARTUNGSWERT: {eur(scored.get('erwartungswert_euro'))}  (Potenzial {eur(scored.get('potenzial_euro'))})",
    ]
    if scored.get("pitch_hook"):
        lines.append(f"  → Pitch:          {scored['pitch_hook']}")
    return "\n".join(lines)
