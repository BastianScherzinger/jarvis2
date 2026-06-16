"""
JARVIS — Sprach-Backend für den Claude-Tab (kostenlos, lokal, schnell).

STT:  faster-whisper (lokal, kein API-Key). Modell wird einmal lazy geladen.
TTS:  edge-tts via tts.speak() (kostenlose Neural-Stimme "Conrad", pyttsx3-Fallback).

Browser schickt MediaRecorder-Audio (webm/opus); faster-whisper decodiert das
direkt über PyAV — kein separates ffmpeg nötig.
"""
from __future__ import annotations

import os
import re
import tempfile
import threading

STT_MODEL_NAME = os.environ.get("JARVIS_STT_MODEL", "base")

_model = None
_model_lock = threading.Lock()


def _get_model():
    """Lädt das Whisper-Modell genau einmal (thread-sicher, int8 = schnell auf CPU)."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from faster_whisper import WhisperModel
                _model = WhisperModel(STT_MODEL_NAME, device="cpu", compute_type="int8")
    return _model


def stt_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def tts_available() -> bool:
    try:
        import edge_tts  # noqa: F401
        return True
    except Exception:
        try:
            import pyttsx3  # noqa: F401
            return True
        except Exception:
            return False


def status() -> dict:
    return {"stt": stt_available(), "tts": tts_available(), "stt_model": STT_MODEL_NAME}


def warmup() -> None:
    """Lädt das Whisper-Modell vorab. Beim allerersten Start wird es dabei
    automatisch heruntergeladen (~140 MB für 'base'). Blockiert nichts — wird
    beim App-Start in einem Hintergrund-Thread aufgerufen."""
    import logger
    if not stt_available():
        logger.warn("Voice", "faster-whisper nicht installiert — Spracheingabe deaktiviert")
        return
    try:
        logger.info("Voice", f"Lade Whisper-Modell '{STT_MODEL_NAME}' "
                             f"(einmaliger Download beim ersten Start, danach aus dem Cache)…")
        _get_model()
        logger.success("Voice", f"Whisper-Modell '{STT_MODEL_NAME}' bereit — Spracheingabe einsatzbereit.")
    except Exception as e:
        logger.error("Voice", f"Whisper-Warmup fehlgeschlagen: {type(e).__name__}: {str(e)[:160]}")


# ── Spracherkennung ───────────────────────────────────────────────────────────

def transcribe(audio_bytes: bytes, suffix: str = ".webm") -> str:
    """Wandelt rohe Audio-Bytes (vom Browser-MediaRecorder) in Text. "" bei Stille."""
    if not audio_bytes:
        return ""
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        model = _get_model()
        segments, _info = model.transcribe(
            tmp_path,
            language="de",
            beam_size=1,            # schnell
            vad_filter=True,        # Stille rausfiltern
            vad_parameters={"min_silence_duration_ms": 400},
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ── Sprachausgabe ─────────────────────────────────────────────────────────────

_CODE_BLOCK = re.compile(r"```[\s\S]*?```")
_INLINE     = re.compile(r"`([^`]+)`")
_BOLD       = re.compile(r"\*\*([^*]+)\*\*")
_URL        = re.compile(r"https?://\S+")


def _clean_for_speech(text: str, limit: int = 1200) -> str:
    """Entfernt Markdown/Code/URLs, damit die Stimme nur sinnvollen Text vorliest."""
    t = _CODE_BLOCK.sub(" (Codeblock) ", text or "")
    t = _INLINE.sub(r"\1", t)
    t = _BOLD.sub(r"\1", t)
    t = _URL.sub(" Link ", t)
    t = re.sub(r"[#>*_`]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > limit:
        cut = t[:limit]
        # an letzter Satzgrenze abschneiden
        m = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        t = cut[: m + 1] if m > 200 else cut
    return t


def speak(text: str) -> "tuple[bytes, str]":
    """Text → (Audio-Bytes, MIME). Nutzt das vorhandene tts-Modul."""
    import tts
    clean = _clean_for_speech(text)
    if not clean:
        raise ValueError("Kein vorlesbarer Text")
    return tts.speak(clean)
