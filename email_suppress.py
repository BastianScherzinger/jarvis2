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

from jsonstate import atomic_write_json

_PATH = Path(__file__).parent / "data" / "email_optout.json"
_lock = threading.Lock()

# DSGVO-Nachweis: unveränderliches Append-Log jedes Widerspruchs/Opt-outs. Die Adresse wird
# NUR als HMAC-Hash abgelegt (kein Klartext-PII-Duplikat), zusammen mit Zeitpunkt, Quelle und
# Aktion — reicht als Beleg "Widerspruch X wurde am Y beachtet", ohne selbst eine neue
# Personendaten-Sammlung anzulegen.
_AUDIT_PATH  = Path(__file__).parent / "data" / "consent_log.jsonl"
_audit_lock  = threading.Lock()


_SECRET_PATH = Path(__file__).parent / "data" / "unsub_secret.txt"


def _secret() -> bytes:
    """Abmelde-Token-Geheimnis. Bevorzugt JARVIS_UNSUB_SECRET (.env). Fehlt es, wird EINMALIG
    ein zufälliges Secret erzeugt und persistiert — niemals ein hartkodiertes (fälschbares) Default."""
    env = (os.environ.get("JARVIS_UNSUB_SECRET") or "").strip()
    if env:
        return env.encode()
    try:
        if _SECRET_PATH.is_file():
            val = _SECRET_PATH.read_text(encoding="utf-8").strip()
            if val:
                return val.encode()
    except Exception:
        pass
    import secrets as _secrets
    val = _secrets.token_hex(32)
    try:
        _SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SECRET_PATH.write_text(val, encoding="utf-8")
    except Exception:
        pass
    return val.encode()


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


def email_hash(email: str) -> str:
    """Nicht umkehrbarer HMAC-Hash einer Adresse fürs Audit-Log (kein Klartext-PII)."""
    e = (email or "").strip().lower()
    return hmac.new(_secret(), e.encode(), hashlib.sha256).hexdigest()


def log_event(email: str, quelle: str, aktion: str = "opt-out") -> None:
    """Hängt einen DSGVO-Nachweis-Eintrag ans Audit-Log (Adresse nur gehasht). Best-effort —
    ein Schreibfehler darf den Abmelde-Vorgang nie scheitern lassen."""
    try:
        rec = {
            "ts":     time.strftime("%Y-%m-%dT%H:%M:%S"),
            "aktion": aktion,
            "quelle": quelle,
            "email_hash": email_hash(email),
        }
        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _audit_lock:
            with open(_AUDIT_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def audit_count() -> int:
    """Anzahl der Audit-Log-Einträge (0 wenn keine Datei)."""
    try:
        with _audit_lock, open(_AUDIT_PATH, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except Exception:
        return 0


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
        atomic_write_json(_PATH, d, indent=2)
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
    log_event(e, quelle, aktion="opt-out")   # DSGVO-Nachweis (gehasht)
    try:
        import logger
        logger.info("Abmeldung", f"Opt-out eingetragen ({quelle}): {e}")
    except Exception:
        pass
    return True


def count() -> int:
    with _lock:
        return len(_load().get("emails", []))
