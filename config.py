import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def get_mode() -> str:
    """'local' (nur Ollama) oder 'cloud' (Claude API). Default: cloud."""
    return os.environ.get("JARVIS_MODE", "cloud").strip().lower()


def get_api_key() -> str:
    """Im Local Mode optional — kein Key nötig."""
    key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_KEY", "")
    if not key and get_mode() != "local":
        raise ValueError(
            "Kein Anthropic API Key gefunden. "
            "Setze ANTHROPIC_API_KEY oder ANTHROPIC_KEY in .env "
            "(oder JARVIS_MODE=local für vollständig lokalen Betrieb)"
        )
    return key


def get_local_model() -> str:
    """Lokales Ollama-Modell für Tool-Use (mind. qwen2.5:7b empfohlen)."""
    return (
        os.environ.get("JARVIS_TOOL_MODEL")
        or os.environ.get("JARVIS_LOCAL_MODEL", "qwen2.5:7b")
    )
