"""
JARVIS TTS
Prioritaet: ElevenLabs > edge-tts (Neural, kostenlos) > pyttsx3 (lokal, Fallback)
"""
import asyncio
import io
import os
import sys
import threading
import time

ELEVENLABS_KEY   = os.getenv("ELEVENLABS_KEY",  "").strip()
ELEVENLABS_VOICE = os.getenv("ELEVENLABS_VOICE", "JBFqnCBsd6RMkjVDRZzb")
EDGE_VOICE       = os.getenv("JARVIS_VOICE",     "de-DE-ConradNeural")
EDGE_RATE        = os.getenv("JARVIS_RATE",      "+15%")

# 100% lokale Sprache (offline-fähig): erzwingt pyttsx3 (Windows-SAPI/espeak),
# umgeht edge-tts/ElevenLabs (Cloud). Für Server/Offline-Betrieb.
def _local_only() -> bool:
    return os.getenv("JARVIS_TTS_LOCAL", "").strip().lower() in ("1", "true", "yes", "on")

# ── Prebuild-Cache ─────────────────────────────────────────────────
_cache: dict[str, tuple[bytes, str]] = {}


def prebuild(text: str, rid: str) -> None:
    """Generiert TTS im Hintergrund, cached das Ergebnis unter `rid`."""
    def _run():
        try:
            _cache[rid] = speak(text)
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()


def get_cached(rid: str) -> tuple[bytes, str] | None:
    return _cache.pop(rid, None)


# ── Haupt-Einstiegspunkt ───────────────────────────────────────────
def speak(text: str) -> tuple[bytes, str]:
    text = text.strip()
    if not text:
        raise ValueError("Kein Text")
    if _local_only():                       # 100% lokal/offline erzwungen
        return _pyttsx3_speak(text)
    if ELEVENLABS_KEY:
        return _elevenlabs(text)
    try:
        return _edge_tts(text)
    except Exception as primary_err:
        try:
            return _pyttsx3_speak(text)
        except Exception:
            raise RuntimeError(f"TTS komplett fehlgeschlagen: {primary_err}")


# ── edge-tts (Microsoft Neural, kostenlos) ────────────────────────
_edge_lock = threading.Lock()   # ein TTS-Call pro Thread gleichzeitig


def _edge_tts(text: str) -> tuple[bytes, str]:
    try:
        import edge_tts
    except ImportError:
        raise RuntimeError("edge-tts nicht installiert: pip install edge-tts")

    async def _stream() -> bytes:
        comm = edge_tts.Communicate(text, EDGE_VOICE, rate=EDGE_RATE)
        buf  = io.BytesIO()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        return buf.getvalue()

    last_err = None
    for attempt in range(2):
        try:
            with _edge_lock:
                # asyncio.run() erstellt sauberen Loop und räumt danach auf — kein Warning
                data = asyncio.run(_stream())
            if data:
                return data, "audio/mpeg"
            raise RuntimeError("Kein Audio erhalten")
        except Exception as e:
            last_err = e
            if attempt == 0:
                time.sleep(0.3)

    raise RuntimeError(f"edge-tts: {last_err}")


# ── pyttsx3 (lokal, Windows SAPI — Fallback wenn edge-tts versagt) ─
_pytts_lock = threading.Lock()

# Stimmen-Praeferenz (erste passende gewinnt)
_VOICE_PREF = ["ryan", "stefan", "konrad", "david", "hedda", "guy", "george", "mark", "zira"]


def _pyttsx3_speak(text: str) -> tuple[bytes, str]:
    try:
        import pyttsx3
    except ImportError:
        raise RuntimeError("pyttsx3 nicht installiert: pip install pyttsx3")

    import tempfile

    with _pytts_lock:
        engine = pyttsx3.init()
        try:
            voices = engine.getProperty("voices") or []
            custom = os.getenv("JARVIS_VOICE_LOCAL", "").lower()
            order  = ([custom] if custom else []) + _VOICE_PREF

            for kw in order:
                for v in voices:
                    if kw in v.name.lower():
                        engine.setProperty("voice", v.id)
                        break
                else:
                    continue
                break

            rate = int(os.getenv("JARVIS_LOCAL_RATE", "170"))
            engine.setProperty("rate",   rate)
            engine.setProperty("volume", 1.0)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp = f.name

            try:
                engine.save_to_file(text, tmp)
                engine.runAndWait()
                with open(tmp, "rb") as f:
                    data = f.read()
            finally:
                try: os.unlink(tmp)
                except OSError: pass

            if not data:
                raise RuntimeError("pyttsx3: kein Audio generiert")
            return data, "audio/wav"
        finally:
            try: engine.stop()
            except Exception: pass


# ── ElevenLabs (Premium) ──────────────────────────────────────────
def _elevenlabs(text: str) -> tuple[bytes, str]:
    import urllib.request, json
    url     = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE}"
    payload = json.dumps({
        "text":           text,
        "model_id":       "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.80},
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={
        "xi-api-key":   ELEVENLABS_KEY,
        "Content-Type": "application/json",
        "Accept":       "audio/mpeg",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read(), "audio/mpeg"


def backend_name() -> str:
    if _local_only():
        return "pyttsx3 (lokal/offline)"
    if ELEVENLABS_KEY:
        return f"ElevenLabs ({ELEVENLABS_VOICE[:12]}...)"
    return f"edge-tts ({EDGE_VOICE})  +  pyttsx3 Fallback"
