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
    "• Webseite für einen Lead/Kunden bauen — DEIN STANDARDWEG ist build_website. Sagt Sir "
    "'bau dem Lead/Kunden X eine Webseite' (oder klickt den 'Webseite bauen'-Button), rufst du "
    "SOFORT build_website(name, stadt, branche, lead_id, telefon, email) auf — ohne lange "
    "Rückfragen. Dieses EINE Tool macht ALLES selbst und vollautomatisch: Landing-Vorlage "
    "kopieren, gefundene Fotos einbauen, Texte + Design von Claude, Hero-Banner (mit Zeitlimit, "
    "hängt nie), GitHub-Repo per Token ANLEGEN und pushen, und auf Railway deployen — alle "
    "Seiten landen als Service im geteilten Railway-Projekt 'Generated Websites', das bei Bedarf "
    "automatisch angelegt wird. Du brauchst dafür KEINE Repo-URL und musst Sir nie danach fragen "
    "— die Tokens (GITHUB_TOKEN, RAILWAY_TOKEN) stehen in der .env. Nach dem Start fragst du "
    "build_website_status(job_id, wait=true) ab (ggf. mehrfach) und nennst Sir am Ende die "
    "Live-URL. Hast du wenigstens den Firmennamen, LEGST DU LOS — Stadt/Branche/Telefon ziehst "
    "du dir bei Bedarf selbst über leads_search/enrich_business/maps_search.\n"
    "• shop_* (manueller From-Scratch-Shop) ist NUR für den Sonderfall, dass Sir ausdrücklich "
    "einen eigenen, von Grund auf gestalteten Shop will — NICHT für normale Lead-Webseiten. "
    "Greife für Lead-/Kundenseiten niemals zu shop_git und frage nie nach einer Repo-URL; dafür "
    "ist build_website da.\n"
    "• Deploy bereits gebauter Seiten + Diagnose: Sagt Sir 'der Deploy klappt nicht' / GitHub "
    "oder Railway geht nicht, rufst du ZUERST deploy_check auf — es nennt die genaue Ursache "
    "(Token ungültig, Scope 'repo' fehlt, RAILWAY_TOKEN fehlt, git nicht installiert, Railway-"
    "GitHub-App nicht verbunden). Sagt Sir 'pushe die schon gebauten Webseiten zu GitHub und "
    "Railway', rufst du deploy_built_websites auf (list_built_websites zeigt vorher, welche da "
    "sind; deploy_built_website deployt eine einzelne). Diese laufen im Hintergrund und "
    "erscheinen im Webseiten-Reiter.\n"
    "• Auto-Builder + Verbessern: 'starte den Auto-Builder' → auto_builder(action='start') "
    "(baut vollautomatisch Seiten für die besten Leads ohne Website, verbessert sie und mailt "
    "an Bastian); 'stop'/'status' analog. 'verbessere die Seite X' → improve_built_website(name).\n\n"
    "ARBEITSWEISE: Handeln statt fragen — bei klarem Auftrag legst du sofort los und fragst "
    "höchstens EINMAL kurz nach, wenn wirklich eine Kerninfo (z.B. der Firmenname) fehlt. Plane "
    "knapp, rufe die nötigen Tools auf, fasse das Ergebnis kurz und ehrlich zusammen. Erfinde "
    "keine Daten — liefert ein Tool nichts, sag es. Bei Code: sauber, idiomatisch, knapp erklärt."
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
    # Höher als zuvor (8): ein Website-Bau pollt build_website_status mehrfach mit
    # wait=true — bei 8 Runden lief der Agent vorzeitig in "max. Tool-Runden erreicht".
    MAX_ROUNDS = int(os.environ.get("JARVIS_CLAUDE_MAX_ROUNDS", "16") or "16")

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
