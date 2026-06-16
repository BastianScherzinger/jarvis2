"""
JARVIS — Claude-Chat-Backend (Anthropic API, Streaming).

Versorgt den Dashboard-Tab "Claude" mit einem echten Claude-Chat. Streamt die
Antwort tokenweise. Optional: "Think" (adaptives Denken) und "Search" (Websuche).
"""
from __future__ import annotations

import os

import anthropic

import config

MODEL = os.environ.get("JARVIS_CLAUDE_MODEL", "claude-opus-4-8")

SYSTEM = (
    "Du bist JARVIS — Just A Rather Very Intelligent System, die KI aus Iron Man. "
    "Sprich den Nutzer mit \"Sir\" an. Antworte kurz, präzise und kompetent, mit "
    "einem Hauch britischer Förmlichkeit, immer auf Deutsch (außer Sir wechselt die "
    "Sprache). Keine Begrüßungsfloskeln wie \"Natürlich!\" oder \"Gerne!\". Du bist "
    "Experte für Python-Entwicklung, das JARVIS-LeadHunter-System (Flask + SQLite + "
    "Ollama-Evaluator + Supabase) und allgemeine Software-Themen. Bei Code: sauber, "
    "idiomatisch, knapp erklärt."
)


def _client() -> "anthropic.Anthropic | None":
    key = config.get_api_key()
    return anthropic.Anthropic(api_key=key) if key else None


def is_ready() -> bool:
    return bool(config.get_api_key())


def stream_chat(messages: list[dict], *, think: bool = False, search: bool = False):
    """
    Generator: liefert dicts {"text": "..."} mit Antwort-Stücken oder
    {"_error": "..."} bei Problemen. Erschöpft sich, wenn die Antwort fertig ist.
    `messages` ist im Anthropic-Format ([{role, content}], content = String oder Blöcke).
    """
    client = _client()
    if client is None:
        yield {"_error": "ANTHROPIC_KEY fehlt in der .env — Claude-Chat nicht verfügbar."}
        return

    kwargs: dict = {
        "model":     MODEL,
        "max_tokens": 4096,
        "system":     SYSTEM,
        "messages":   messages,
    }
    if think:   # tieferes Denken für komplexe Fragen (adaptiv)
        kwargs["thinking"]      = {"type": "adaptive", "display": "summarized"}
        kwargs["output_config"] = {"effort": "high"}
    if search:  # Websuche serverseitig
        kwargs["tools"] = [{"type": "web_search_20260209", "name": "web_search"}]

    try:
        with client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                yield {"text": text}
    except anthropic.AuthenticationError:
        yield {"_error": "API-Key ungültig (401). Bitte ANTHROPIC_KEY in .env prüfen."}
    except anthropic.RateLimitError:
        yield {"_error": "Rate-Limit erreicht — bitte kurz warten."}
    except anthropic.BadRequestError as e:
        yield {"_error": f"Anfrage abgelehnt: {getattr(e, 'message', str(e))[:200]}"}
    except Exception as e:   # Netzwerk u. a. — nie den Server crashen lassen
        yield {"_error": f"{type(e).__name__}: {str(e)[:200]}"}
