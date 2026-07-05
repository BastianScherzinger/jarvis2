"""
claude_keys.py — Pool mehrerer Anthropic-API-Keys + automatische Rotation bei Limit.

Mehrere Keys = mehrere „Claudes": ist einer am Session- oder Weekly-Limit, schaltet das System
automatisch auf den nächsten verfügbaren Key (sofort, ohne die ganze Cooldown-Pause). Per-Key-
Erschöpfung wird mit Cooldown gemerkt (Session 4 h, Weekly 7 Tage) und kann manuell zurück-
gesetzt werden („nochmal testen").

Keys aus der .env (dedupliziert, in dieser Reihenfolge):
  ANTHROPIC_KEY, ANTHROPIC_API_KEY, ANTHROPIC_KEY_2 .. ANTHROPIC_KEY_9,
  ANTHROPIC_KEYS="k1,k2,k3" (komma-getrennt).

State: data/claude_keys.json — {keyid: {"exhausted_until": ts, "scope": "session|weekly", "since": ts}}
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

try:
    import config  # lädt .env in os.environ (damit die Keys hier sicher sichtbar sind)
except Exception:
    pass

from jsonstate import atomic_write_json

_FILE = Path(__file__).resolve().parent / "data" / "claude_keys.json"
_lock = threading.Lock()

_SESSION_COOLDOWN = 4 * 3600
_WEEKLY_COOLDOWN  = 7 * 86400


def _kid(key: str) -> str:
    return hashlib.sha256((key or "").encode()).hexdigest()[:12]


def all_keys() -> list[str]:
    """Alle konfigurierten Keys (dedupliziert, Reihenfolge = Priorität)."""
    cands: list[str] = []
    for n in ("ANTHROPIC_KEY", "ANTHROPIC_API_KEY"):
        v = (os.environ.get(n) or "").strip()
        if v:
            cands.append(v)
    for i in range(2, 10):
        v = (os.environ.get(f"ANTHROPIC_KEY_{i}") or "").strip()
        if v:
            cands.append(v)
    multi = (os.environ.get("ANTHROPIC_KEYS") or "").strip()
    if multi:
        cands += [x.strip() for x in multi.split(",") if x.strip()]
    seen: set = set()
    out: list[str] = []
    for k in cands:
        if (k.startswith("sk-") or len(k) > 20) and "dein_" not in k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def count() -> int:
    return len(all_keys())


def _read() -> dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(d: dict) -> None:
    try:
        atomic_write_json(_FILE, d, indent=2)
    except Exception:
        pass


def _exhausted_until(key: str, d: dict | None = None) -> float:
    d = d if d is not None else _read()
    return float((d.get(_kid(key)) or {}).get("exhausted_until") or 0)


def active_key() -> str:
    """Erster nicht-erschöpfter Key. Sind alle erschöpft, der mit dem frühesten Ablauf
    (damit der Makeover-Gate die Wartezeit korrekt anzeigt). '' wenn kein Key konfiguriert."""
    keys = all_keys()
    if not keys:
        return ""
    now = time.time()
    d = _read()
    for k in keys:
        if _exhausted_until(k, d) <= now:
            return k
    return min(keys, key=lambda k: _exhausted_until(k, d))


def has_available() -> bool:
    """Gibt es JETZT mindestens einen nutzbaren Key?"""
    keys = all_keys()
    if not keys:
        return False
    now = time.time()
    d = _read()
    return any(_exhausted_until(k, d) <= now for k in keys)


def mark_exhausted(key: str, scope: str = "session") -> None:
    """Markiert EINEN Key als erschöpft (Session 4 h / Weekly 7 Tage Cooldown)."""
    if not key:
        return
    cd = _WEEKLY_COOLDOWN if scope == "weekly" else _SESSION_COOLDOWN
    with _lock:
        d = _read()
        d[_kid(key)] = {"exhausted_until": time.time() + cd, "scope": scope, "since": time.time()}
        _write(d)
    try:
        import logger
        logger.warn("ClaudeKeys", f"Key …{key[-4:]} am {scope}-Limit — Cooldown {cd // 3600} h.")
    except Exception:
        pass


def reset(key: str = "") -> dict:
    """Hebt die Erschöpfung auf (manuelles „nochmal testen"). Ohne key: ALLE Keys freigeben."""
    with _lock:
        d = _read()
        if key:
            d.pop(_kid(key), None)
        else:
            d = {}
        _write(d)
    return {"ok": True, "available": sum(1 for _ in all_keys()) if not key else None}


def seconds_to_available() -> int:
    """Sekunden bis frühestens wieder ein Key frei ist (0 = jetzt verfügbar / keine Keys)."""
    keys = all_keys()
    if not keys or has_available():
        return 0
    now = time.time()
    d = _read()
    return max(0, int(min(_exhausted_until(k, d) for k in keys) - now))


def status() -> dict:
    """Übersicht für Dashboard: wie viele Keys, wie viele frei, welcher aktiv."""
    keys = all_keys()
    now = time.time()
    d = _read()
    items = []
    for i, k in enumerate(keys):
        eu = _exhausted_until(k, d)
        st = d.get(_kid(k)) or {}
        items.append({
            "index": i + 1,
            "masked": (k[:8] + "…" + k[-4:]) if len(k) > 14 else "key",
            "exhausted": eu > now,
            "scope": st.get("scope", ""),
            "minutes_left": max(0, int((eu - now) // 60)) if eu > now else 0,
        })
    act = active_key()
    return {
        "total": len(keys),
        "available": sum(1 for it in items if not it["exhausted"]),
        "active_masked": (act[:8] + "…" + act[-4:]) if len(act) > 14 else ("" if not act else "key"),
        "keys": items,
    }
