"""
Harte Zeitschranke für Ollama-Aufrufe aus interaktiven LeadForge-Endpunkten.

scrapers._http.ask_ollama() hat einen Default-Timeout von 180s (fürs Overnight-
Makeover gedacht, wo das ok ist) — für einen Dashboard-Button/Preview ist das
inakzeptabel lang, wenn Ollama gerade nicht läuft. Diese Funktion erzwingt eine
kurze externe Deadline per ThreadPoolExecutor, unabhängig vom internen Verhalten
von ask_ollama.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="leadforge-ollama")


def ask_bounded(prompt: str, system: str = "", hard_timeout: float = 6.0,
                 inner_timeout: int = 15) -> str | None:
    """Ruft ask_ollama in einem Worker-Thread auf und gibt spätestens nach
    hard_timeout Sekunden zurück — None bei Timeout/Fehler/fehlendem Ollama."""
    try:
        from scrapers._http import ask_ollama
    except Exception:
        return None
    future = _executor.submit(ask_ollama, prompt, system, "", inner_timeout)
    try:
        return future.result(timeout=hard_timeout)
    except Exception:
        return None
