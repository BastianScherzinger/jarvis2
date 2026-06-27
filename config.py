import os
from pathlib import Path


def _load_env() -> None:
    """Lädt .env robust gegen die Datei-Kodierung. Wird die .env in einem Windows-Editor
    gespeichert, ist sie oft cp1252 (ANSI) statt UTF-8 — `python-dotenv` liest aber UTF-8 und
    macht aus Umlauten (ä/ö/ü/ß) sonst kaputte Zeichen (z.B. im Impressum der Kundenmails).
    Darum dekodieren wir die Bytes selbst (UTF-8, sonst cp1252) und füttern den Text in dotenv.
    Bestehende Umgebungsvariablen werden NICHT überschrieben (wie load_dotenv-Default)."""
    p = Path(__file__).parent / ".env"
    if not p.exists():
        return
    raw = p.read_bytes()
    text = None
    for enc in ("utf-8", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", "replace")
    try:
        from io import StringIO
        from dotenv import dotenv_values
        for k, v in dotenv_values(stream=StringIO(text)).items():
            if v is not None and k not in os.environ:
                os.environ[k] = v
        return
    except ImportError:
        pass
    # Manueller Fallback, falls python-dotenv fehlt.
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_env()


def get_api_key() -> str:
    """Aktiver Anthropic-Key. Bei mehreren konfigurierten Keys rotiert claude_keys automatisch
    auf einen nicht-erschöpften (mehrere „Claudes"). Fallback: direkte Env-Variable."""
    try:
        import claude_keys
        k = claude_keys.active_key()
        if k:
            return k
    except Exception:
        pass
    return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_KEY", "")


def get_mode() -> str:
    return os.environ.get("JARVIS_AI_MODE", "local").strip().lower()


def get_local_model() -> str:
    return (
        os.environ.get("JARVIS_TOOL_MODEL")
        or os.environ.get("JARVIS_LOCAL_MODEL", "qwen2.5:7b")
    )
