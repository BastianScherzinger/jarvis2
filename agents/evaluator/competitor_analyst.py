"""
Agent (neu) — Wettbewerbs-/Markt-Analyst.

Bringt den bisher ungenutzten regionalen Wettbewerbs-Kontext (`db_raw.get_competition`) ins
Scoring: Wie viele Betriebe gleicher Branche/Stadt gibt es, und wie viele davon ohne Website?
Ein Betrieb ohne Website in einem Markt, in dem alle anderen schon eine haben, hat höheren
Handlungsdruck (Wettbewerbsnachteil) — genau das war als Verkaufsargument (`prozent_ohne`)
schon in der DB, floss aber nie in die Bewertung ein.

Design (wie die übrige Pipeline):
  • DB-Abfrage immer (0 Kosten). LLM-Verfeinerung nur wenn genug Kontext da ist.
  • EIN optionaler LLM-Call, starkes Modell. Ohne Ollama: rein heuristischer markt_score.
  • Nie Exception — immer ein Dict mit markt_score (0-10) + Kurztext.
"""
from __future__ import annotations

import db_raw
from scrapers._http import ask_ollama, extract_json, model_for_role
import logger


def _heuristik_markt_score(has_web: int, gesamt: int, prozent_ohne: int) -> int:
    """Markt-Dringlichkeit 0-10 rein aus den DB-Zahlen (Fallback ohne LLM).

    Kern-Idee: Der eigene Betrieb OHNE Website in einem Markt, in dem die meisten
    Wettbewerber schon eine haben (niedriges prozent_ohne), steht unter dem größten
    Druck → hoher Score. Hat er selbst schon eine Website, ist der Druck geringer."""
    if gesamt <= 1:
        return 5 if not has_web else 3        # kaum Vergleichsdaten → neutral-mittig
    if not has_web:
        # Wenige andere ohne Website (prozent_ohne klein) = starker Nachteil → hoher Score.
        if prozent_ohne <= 20:
            return 9
        if prozent_ohne <= 40:
            return 8
        if prozent_ohne <= 60:
            return 6
        return 5
    else:
        # Betrieb hat selbst eine Website → geringerer Handlungsdruck.
        if prozent_ohne <= 20:
            return 5
        if prozent_ohne <= 50:
            return 4
        return 3


def analyze(lead: dict, web: dict) -> dict:
    stadt   = (lead.get("stadt") or "").strip()
    branche = (lead.get("branche") or "").strip()
    has_web = int(web.get("has_website", 0))

    res = {"markt_score": None, "markt_text": "",
           "wettbewerb_gesamt": 0, "wettbewerb_ohne_website": 0, "wettbewerb_prozent_ohne": 0}

    try:
        comp = db_raw.get_competition(stadt, branche)
    except Exception:
        comp = {}
    gesamt   = int(comp.get("gesamt") or 0)
    ohne     = int(comp.get("ohne_website") or 0)
    prozent  = int(comp.get("prozent_ohne") or 0)
    res.update({"wettbewerb_gesamt": gesamt, "wettbewerb_ohne_website": ohne,
                "wettbewerb_prozent_ohne": prozent})

    heur = _heuristik_markt_score(has_web, gesamt, prozent)
    res["markt_score"] = heur

    # Ohne belastbaren Kontext (fast keine Vergleichsbetriebe) kein LLM-Call — Heuristik reicht.
    if gesamt < 3:
        res["markt_text"] = f"Zu wenig Vergleichsdaten in {stadt or '—'} ({gesamt} Betriebe)."
        return res

    system = ("Du bist ein nüchterner deutscher Markt-Analyst. Bewerte NUR anhand der Zahlen. "
              "Antworte AUSSCHLIESSLICH mit JSON.")
    prompt = (
        f"Betrieb-Branche: {branche} | Stadt: {stadt}\n"
        f"Eigene Website: {'ja' if has_web else 'NEIN'}\n"
        f"Wettbewerber gleicher Branche/Stadt in der Datenbank: {gesamt}\n"
        f"Davon OHNE Website: {ohne} ({prozent}%)\n\n"
        "Wie hoch ist der Handlungsdruck für diesen Betrieb, (bald) eine gute Website zu haben? "
        "Ein Betrieb ohne Website in einem Markt, in dem die meisten Konkurrenten schon eine "
        "haben, hat den höchsten Druck.\n"
        "Antworte EXAKT so (deutscher Text):\n"
        '{"markt_score": 0-10, "markt_text": "1 kurzer Satz zur Wettbewerbssituation"}'
    )
    raw  = ask_ollama(prompt, system=system, model=model_for_role("strong"))
    data = extract_json(raw)
    if data:
        try:
            ms = int(round(float(data.get("markt_score"))))
            res["markt_score"] = max(0, min(10, ms))
        except (TypeError, ValueError):
            pass
        res["markt_text"] = str(data.get("markt_text") or "")[:200]

    logger.eval_("CompetitorAnalyst",
                 f"✓ {lead.get('name') or '?'}: Markt {res['markt_score']}/10 "
                 f"({ohne}/{gesamt} ohne Website)")
    return res
