"""
video_prompt.py — lokale KI-Unterstützung für den Video-Studio-Tab.

Zwei Aufgaben, beide nach dem Muster von custom_build.suggest(): deterministischen
Fallback ZUERST berechnen, dann Ollama versuchen — nie werfend, nie blockierend ohne
Ollama.

  improve_instruction(raw) — verwandelt eine rohe (oft per Whisper diktierte, mit
    Tippfehlern behaftete) Bearbeitungsanweisung in einen klaren, konkreten Text.
  chat_reply(message)      — kurzer Hilfschat für den Tab (kein SSE-Streaming nötig,
    Ollama antwortet in Sekunden).
"""
from __future__ import annotations

import re

_MIN_IMPROVED_LEN = 8   # kürzere Ollama-Antworten gelten als ungültig → Fallback greift


def _normalize_fallback(raw: str) -> str:
    """Deterministischer Fallback ohne KI: Whitespace kollabieren, Großschreibung am
    Satzanfang, Satzzeichen am Ende ergänzen falls es fehlt."""
    s = re.sub(r"\s+", " ", (raw or "").strip())
    if not s:
        return s
    s = s[0].upper() + s[1:]
    if s[-1] not in ".!?":
        s += "."
    return s


def improve_instruction(raw: str) -> dict:
    """Verbessert eine Bearbeitungsanweisung lokal per Ollama. Gibt immer
    {"ok", "improved", "original", "source": "ollama"|"fallback"} zurück — wirft nie."""
    raw = (raw or "").strip()
    if not raw:
        return {"ok": False, "reason": "empty"}
    fallback = _normalize_fallback(raw)
    try:
        from scrapers._http import ask_ollama
        system = (
            "Du bist ein präziser Editor für Video-Bearbeitungsanweisungen an eine "
            "KI-Videoschnitt-Engine (Filmora). Der Nutzer spricht oft undeutlich per "
            "Diktat (Whisper) — Tippfehler, abgebrochene Sätze, fehlende Satzzeichen "
            "sind normal, keine Rückfragen stellen. Wandle die rohe Eingabe in EINE "
            "klare, konkrete, gut strukturierte Bearbeitungsanweisung um, gleiche "
            "Sprache wie die Eingabe beibehalten. Antworte NUR mit dem reinen Text "
            "der verbesserten Anweisung, keine Anführungszeichen, keine Erklärung."
        )
        out = (ask_ollama(raw, system, timeout=30) or "").strip().strip('"').strip()
        if out and len(out) >= _MIN_IMPROVED_LEN:
            return {"ok": True, "improved": out, "original": raw, "source": "ollama"}
    except Exception:
        pass
    return {"ok": True, "improved": fallback, "original": raw, "source": "fallback"}


_EDIT_HINT = re.compile(
    r"youtu\.?be|schneid|k[uü]rz|trim|cut|f[uü]ge|entfern|farbe|untertitel|musik|video",
    re.I,
)


def chat_reply(message: str) -> dict:
    """Leichter, synchroner Hilfschat für den Video-Studio-Tab. Gibt immer
    {"ok", "reply", "looks_like_edit", "source"} zurück — wirft nie, auch ohne Ollama."""
    message = (message or "").strip()
    if not message:
        return {"ok": False, "reason": "empty"}
    looks_like_edit = bool(_EDIT_HINT.search(message))
    try:
        from scrapers._http import ask_ollama
        system = ("Du bist der Assistent im 'Video-Studio'-Tab von JARVIS. Du hilfst bei "
                 "Fragen zur Filmora-MCP-Video-Bearbeitung (YouTube-Link + Anweisung). "
                 "Antworte kurz, konkret, Deutsch, Sie-Form.")
        reply = (ask_ollama(message, system, timeout=45) or "").strip()
        if not reply:
            raise RuntimeError("leere Antwort")
        return {"ok": True, "reply": reply, "looks_like_edit": looks_like_edit, "source": "ollama"}
    except Exception:
        return {"ok": True, "reply": ("Ollama ist gerade nicht erreichbar, Sir. Tragen Sie den "
                "YouTube-Link und die Anweisung direkt in die Felder oben ein — das "
                "funktioniert auch ohne Chat."),
                "looks_like_edit": looks_like_edit, "source": "fallback"}
