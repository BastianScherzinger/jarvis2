"""
email_suppress.py — Abmelde-/Unterdrückungsliste für die Kalt-Akquise (UWG/DSGVO).

Wer sich abmeldet (oder per E-Mail widerspricht), landet hier. mailer.send_email prüft die
Liste vor JEDEM echten Versand und sendet dann nicht mehr an diese Adresse. Die Abmeldung
geschieht über einen tokenisierten Link (`/abmelden?e=…&t=…`) ODER eine List-Unsubscribe-
Mail — beides rechtlich saubere Wege.

Speicher: data/email_optout.json  → {"emails": ["a@b.de", ...], "ts": {...}}.
Token:    hmac_sha256(JARVIS_UNSUB_SECRET, lower(email))[:20] — verhindert Fremd-Abmeldung
          und Adress-Enumeration ohne gültigen Link.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from pathlib import Path

_PATH = Path(__file__).parent / "data" / "email_optout.json"
_lock = threading.Lock()


def _secret() -> bytes:
    return (os.environ.get("JARVIS_UNSUB_SECRET") or "jarvis-unsub-default-secret").encode()


def token_for(email: str) -> str:
    """Stabiles Abmelde-Token für eine Adresse."""
    e = (email or "").strip().lower()
    return hmac.new(_secret(), e.encode(), hashlib.sha256).hexdigest()[:20]


def verify(email: str, token: str) -> bool:
    return bool(email) and hmac.compare_digest(token_for(email), (token or "").strip())


def unsub_link(email: str) -> str:
    """Öffentlicher Abmelde-Link (leer, wenn JARVIS_PUBLIC_URL fehlt oder Adresse ungültig)."""
    base = (os.environ.get("JARVIS_PUBLIC_URL") or "").strip().rstrip("/")
    if not base or "@" not in (email or ""):
        return ""
    import urllib.parse
    return f"{base}/abmelden?" + urllib.parse.urlencode({"e": email, "t": token_for(email)})


def _load() -> dict:
    try:
        d = json.loads(_PATH.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            d.setdefault("emails", [])
            d.setdefault("ts", {})
            return d
    except Exception:
        pass
    return {"emails": [], "ts": {}}


def _save(d: dict) -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def is_suppressed(email: str) -> bool:
    e = (email or "").strip().lower()
    if "@" not in e:
        return False
    with _lock:
        return e in {x.lower() for x in _load().get("emails", [])}


def suppress(email: str, quelle: str = "link") -> bool:
    """Trägt eine Adresse in die Abmeldeliste ein. True, wenn neu hinzugefügt."""
    e = (email or "").strip().lower()
    if "@" not in e:
        return False
    with _lock:
        d = _load()
        if e in {x.lower() for x in d.get("emails", [])}:
            return False
        d.setdefault("emails", []).append(e)
        d.setdefault("ts", {})[e] = {"ts": time.time(), "quelle": quelle}
        _save(d)
    try:
        import logger
        logger.info("Abmeldung", f"Opt-out eingetragen ({quelle}): {e}")
    except Exception:
        pass
    return True


def count() -> int:
    with _lock:
        return len(_load().get("emails", []))
