import os
from pathlib import Path


def _parse_env_file() -> dict:
    """Liest die .env robust gegen die Datei-Kodierung und gibt {key: value} zurück. Wird die
    .env in einem Windows-Editor gespeichert, ist sie oft cp1252 (ANSI) statt UTF-8 —
    `python-dotenv` liest aber UTF-8 und macht aus Umlauten (ä/ö/ü/ß) sonst kaputte Zeichen
    (z.B. im Impressum der Kundenmails). Darum dekodieren wir die Bytes selbst."""
    p = Path(__file__).parent / ".env"
    if not p.exists():
        return {}
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
        return {k: v for k, v in dotenv_values(stream=StringIO(text)).items() if v is not None}
    except ImportError:
        pass
    # Manueller Fallback, falls python-dotenv fehlt.
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k:
            out[k] = v
    return out


def reload_env(override: bool = False, only: "set[str] | None" = None) -> int:
    """Lädt Werte aus der .env in os.environ.

    override=False (Default): bestehende os.environ-Keys bleiben unangetastet (load_dotenv-Verhalten).
    override=True: überschreibt auch bereits gesetzte (evtl. LEERE) Keys — nötig, wenn ein Key
    vorab leer im Prozess-Environment stand und der Default-Load ihn deshalb übersprungen hat
    (genau der Fall, der den Discord-Bot auf dem Ziel-PC still ausfallen ließ: DISCORD_BOT_TOKEN
    stand in der .env, war aber in os.environ leer → `k not in os.environ` überging ihn).
    `only`: optionale Key-Whitelist. Gibt die Anzahl gesetzter Keys zurück."""
    n = 0
    for k, v in _parse_env_file().items():
        if only is not None and k not in only:
            continue
        if override or k not in os.environ:
            # Bei override nur überschreiben, wenn sich der Wert wirklich unterscheidet (leer→voll).
            if not override or os.environ.get(k, "") != v:
                os.environ[k] = v
                n += 1
    return n


def _load_env() -> None:
    reload_env(override=False)


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
