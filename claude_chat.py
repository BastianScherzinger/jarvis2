"""
JARVIS — Claude-Chat-Backend (Anthropic API, agentischer Tool-Use-Loop, Streaming).

Versorgt den Dashboard-Tab "Claude" mit einem echten, werkzeugfähigen Agenten:
Browser (öffnen/scrollen/klicken), Google Maps, Medien-Generierung und Zugriff
auf die eigene Lead-Datenbank. Streamt die Antwort tokenweise und meldet Tool-Calls.
"""
from __future__ import annotations

import os

import anthropic

import config

MODEL = os.environ.get("JARVIS_CLAUDE_MODEL", "claude-opus-4-8")

SYSTEM = (
    "Du bist JARVIS — Just A Rather Very Intelligent System, die KI von Bastian (Sir) "
    "im JARVIS-LeadHunter-Dashboard. Du weißt genau, wer du bist und was du kannst.\n\n"
    "PERSÖNLICHKEIT: Sprich Sir mit \"Sir\" an. Kurz, präzise, kompetent, mit einem Hauch "
    "britischer Förmlichkeit — wie Tony Starks JARVIS. Keine Floskeln wie \"Natürlich!\" "
    "oder \"Gerne!\". Du hast eine Meinung; ist etwas ineffizient, sagst du es knapp. "
    "Immer Deutsch, außer Sir wechselt die Sprache.\n\n"
    "DAS SYSTEM, IN DEM DU LEBST: JARVIS LeadHunter ist ein B2B-Lead-Generator — Scraper "
    "finden deutsche Betriebe, ein lokales KI-Team bewertet sie nach Bedarf (Score), "
    "Sicherheit und Erwartungswert (€), Ergebnisse landen in einer Rangliste und werden "
    "über Supabase auf mehrere PCs + eine Railway-Seite synchronisiert. Es gibt ein "
    "Auto-E-Mail-Gerüst (Gmail/SMTP, standardmäßig deaktiviert).\n\n"
    "DEINE WERKZEUGE — nutze sie eigenständig, wenn sie die Antwort verbessern (frag bei "
    "Lese-Aktionen nicht um Erlaubnis):\n"
    "• Browser (browser_*): echte Webseiten öffnen, scrollen, klicken, tippen, lesen, "
    "Screenshot — für Live-Recherche.\n"
    "• Maps (maps_*): reale Betriebe/Orte finden, Adressen, Telefon, Website, Routen.\n"
    "• Medien (generate_image/generate_video): Bilder/Videos erzeugen (asynchron).\n"
    "• Leads: leads_top/leads_search (lesen), leads_update (Status/Notiz SCHREIBEN — du "
    "handelst, nicht nur lesen), enrich_business (beliebigen Betrieb sofort auf "
    "Akquise-Tauglichkeit prüfen: Website-Status, Score, Sicherheit, Erwartungswert), "
    "leads_conversion_stats (was wird zu Kunden).\n"
    "• Webseiten/Shops bauen (shop_*): Sobald Sir eine Website, Seite oder einen Shop bauen "
    "will, ist das dein FESTER Ablauf — ohne lange Rückfragen: (1) shop_skill lesen, "
    "(2) shop_new(name) kopiert die Vorlage in einen NEUEN Ordner, (3) die Seite NEU DESIGNEN "
    "und inhaltlich anpassen — modernes, eigenständiges Design (keine 0815-Optik): Farben/Theme "
    "in static/css/variables.css, Branding in base.html + components/navbar.html, Inhalte in "
    "home.html etc. via shop_read/shop_write, (4) ZULETZT Sir nach der GitHub-Repo-URL fragen "
    "und mit shop_git pushen. Frage nur kurz nach Name/Branche/Farbe, dann leg los.\n"
    "• Lead-Webseite VOLLAUTOMATISCH (build_website): Sagt Sir 'bau dem Lead/Kunden X eine "
    "Webseite', startest du build_website(name, stadt, branche, lead_id) — das kopiert die "
    "Landing-Vorlage, baut die GEFUNDENEN Fotos ein, textet/gestaltet die Seite, erstellt ein "
    "GitHub-Repo und deployt auf Railway (Tokens aus .env). Danach build_website_status(job_id, "
    "wait=true) abfragen und Sir die Live-URL nennen. Dafür ist auch der Lead-'Webseite "
    "bauen'-Button im Dashboard da.\n\n"
    "ARBEITSWEISE: Plane kurz, rufe die nötigen Tools auf, fasse das Ergebnis knapp und "
    "ehrlich zusammen. Erfinde keine Daten — wenn ein Tool nichts liefert, sag es. Bei "
    "Code: sauber, idiomatisch, knapp erklärt."
)


def _client() -> "anthropic.Anthropic | None":
    key = config.get_api_key()
    return anthropic.Anthropic(api_key=key) if key else None


def is_ready() -> bool:
    return bool(config.get_api_key())


def stream_chat(messages: list[dict], *, think: bool = False, search: bool = False):
    """
    Generator. Liefert dicts:
      {"text": "..."}         — Antwort-Stück
      {"tool": name, "input": {...}} — ein Tool wird aufgerufen
      {"tool_result": "..."}  — Kurzfassung des Tool-Ergebnisses
      {"_error": "..."}       — Problem
    Führt den vollständigen agentischen Tool-Loop aus.
    """
    client = _client()
    if client is None:
        yield {"_error": "ANTHROPIC_KEY fehlt in der .env — Claude-Chat nicht verfügbar."}
        return

    from agent_tools import TOOLS, run as run_tool
    tools = list(TOOLS)
    if search:
        tools.append({"type": "web_search_20260209", "name": "web_search"})

    opts: dict = {}
    if think:
        opts["thinking"]      = {"type": "adaptive", "display": "summarized"}
        opts["output_config"] = {"effort": "high"}

    convo = list(messages)
    MAX_ROUNDS = 8

    for _round in range(MAX_ROUNDS):
        try:
            with client.messages.stream(
                model=MODEL, max_tokens=4096, system=SYSTEM,
                messages=convo, tools=tools, **opts,
            ) as stream:
                for text in stream.text_stream:
                    yield {"text": text}
                final = stream.get_final_message()
            try:
                import metrics
                u = final.usage
                metrics.record_claude(getattr(u, "input_tokens", 0),
                                      getattr(u, "output_tokens", 0))
            except Exception:
                pass
        except anthropic.AuthenticationError:
            yield {"_error": "API-Key ungültig (401). Bitte ANTHROPIC_KEY in .env prüfen."}
            return
        except anthropic.RateLimitError:
            yield {"_error": "Rate-Limit erreicht — bitte kurz warten."}
            return
        except anthropic.BadRequestError as e:
            yield {"_error": f"Anfrage abgelehnt: {getattr(e, 'message', str(e))[:200]}"}
            return
        except Exception as e:
            yield {"_error": f"{type(e).__name__}: {str(e)[:200]}"}
            return

        reason = final.stop_reason

        if reason == "tool_use":
            convo.append({"role": "assistant", "content": final.content})
            results = []
            for block in final.content:
                if getattr(block, "type", "") == "tool_use":
                    yield {"tool": block.name, "input": block.input}
                    r = run_tool(block.name, dict(block.input or {}))
                    out = r["text"]
                    yield {"tool_result": out[:300]}
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": out or "(leer)", "is_error": not r["ok"]})
            convo.append({"role": "user", "content": results})
            continue

        if reason == "pause_turn":   # serverseitiges Tool (z.B. Websuche) fortsetzen
            convo.append({"role": "assistant", "content": final.content})
            continue

        return   # end_turn / max_tokens / refusal → fertig

    yield {"_error": "Maximale Tool-Runden erreicht."}
