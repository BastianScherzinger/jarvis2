import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass   # python-dotenv optional — .env wird auch manuell gelesen


def get_api_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_KEY", "")


def get_mode() -> str:
    return os.environ.get("JARVIS_AI_MODE", "local").strip().lower()


def get_local_model() -> str:
    return (
        os.environ.get("JARVIS_TOOL_MODEL")
        or os.environ.get("JARVIS_LOCAL_MODEL", "qwen2.5:7b")
    )
