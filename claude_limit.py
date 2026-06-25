"""
claude_limit.py — Claude-Budget, Limit-Lernen & Fixkosten.

Single Source of Truth rund um das Claude-Code-Session-/Usage-Limit:

1. ZEICHEN: das Makeover meldet ein erkanntes Limit (`mark`) bzw. das Weiterlaufen
   (`clear`); das Dashboard liest `state()`/`status()` und zeigt direkt ein Zeichen
   (Banner über den Webseiten + Badge auf der Karte).

2. LERNEN: jeder Claude-CLI-Lauf bucht seine Token (`record_usage`). Kommt das Limit,
   merkt sich das Modul, bei WIE VIEL Token-Verbrauch im aktuellen 5-Stunden-Fenster es
   kam (`mark` → gleitender Mittelwert `learned_limit`). So schätzt es künftig den
   Verbrauch in Prozent und WARNT bei ~95 % („gleich voll"). Es wird mit jedem Limit
   genauer. Beim Programmstart weiß es sofort: „Claude ist (noch) voll, ~X %".

3. RETRY-PLAN: kommt das Limit, wird die Uhrzeit gespeichert; 4 Stunden später wird
   stündlich ein neuer Versuch erlaubt (`should_try_now`/`note_retry_failed`).

4. KOSTEN: Claude bleibt im Abo (Flat 20 €/Monat) — solange es nur bis zum Limit geht,
   entstehen KEINE variablen Claude-Kosten. Higgsfield-Abo ~35 €/Monat. `costs()` liefert
   die Fixkosten pro Monat/Tag fürs Kosten-Dashboard.

State liegt in data/claude_budget.json (gitignored, maschinenlokal).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

_FILE = Path(__file__).resolve().parent / "data" / "claude_budget.json"

# ── Konstanten ────────────────────────────────────────────────────────────────
_WINDOW      = 5 * 3600          # Claude-Abo: rollendes 5-Stunden-Session-Fenster
_COOLDOWN    = 4 * 3600          # nach einem Session-Limit: 4 h Pause (Sirs Vorgabe)
_RETRY_EVERY = 3600              # danach stündlich ein neuer Versuch
_WEEKLY_RECHECK = 6 * 3600       # Weekly-Limit: alle 6 h erneut testen (Reset rollt ~wöchentlich)
_NEAR        = 0.95              # ab 95 % Verbrauch = „gleich voll" (5 % übrig)
_EMA_ALPHA   = 0.4               # Lerngewicht neuer Limit-Beobachtungen
_DEFAULT_LIMIT = 1_800_000       # Start-Schätzung Token/Fenster bis Limit (wird gelernt)

# Fixkosten (Abos) in EUR
CLAUDE_MONTHLY = 20.0
HF_MONTHLY     = 35.0


def _read() -> dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(d: dict) -> None:
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _maybe_reset_window(d: dict, now: float) -> bool:
    """Ist das 5-h-Fenster abgelaufen, beginnt ein frisches: Verbrauch 0, Limit aufgehoben.
    Gibt True zurück, wenn ein Reset passiert ist."""
    start = float(d.get("session_start") or 0)
    if not start:
        d["session_start"] = now
        return False
    if now - start > _WINDOW:
        d["session_start"] = now
        d["tokens_used"] = 0
        if d.get("limited"):
            d["limited"] = False          # Fenster erholt → Limit weg
            d["since"] = 0
            d["next_try"] = 0
        return True
    return False


def _learned_limit(d: dict) -> int:
    return int(d.get("learned_limit") or _DEFAULT_LIMIT)


# ── Token-Verbrauch buchen (vom Claude-CLI-Lauf) ──────────────────────────────

def record_usage(tokens: int) -> None:
    """Bucht die Token eines Claude-Code-Laufs ins aktuelle 5-h-Fenster (Grundlage der
    Prozent-Schätzung). Silent."""
    try:
        tokens = int(tokens or 0)
        if tokens <= 0:
            return
        now = time.time()
        d = _read()
        _maybe_reset_window(d, now)
        d["tokens_used"] = int(d.get("tokens_used") or 0) + tokens
        _write(d)
    except Exception:
        pass


# ── Limit-Ereignis (Zeichen + Lernen + Retry-Plan) ────────────────────────────

def mark(stage: str = "", wait_seconds: int = 0, site: str = "", scope: str = "session") -> None:
    """Markiert das Claude-Limit als erschöpft. Speichert Uhrzeit + Scope (session|weekly), LERNT
    die Token-Schwelle (nur Session) und plant den nächsten Versuch: Session 4 h dann stündlich,
    Weekly alle 6 h erneut testen. `wait_seconds` bleibt nur für Rückwärtskompatibilität."""
    now = time.time()
    d = _read()
    _maybe_reset_window(d, now)
    used = int(d.get("tokens_used") or 0)
    # Lernen nur beim Session-Limit (Weekly hängt nicht am 5-h-Token-Fenster).
    if used > 0 and scope != "weekly":
        prev = float(d.get("learned_limit") or _DEFAULT_LIMIT)
        d["learned_limit"] = int(prev * (1 - _EMA_ALPHA) + used * _EMA_ALPHA)
        ev = d.get("events") or []
        mins = int((now - float(d.get("session_start") or now)) // 60)
        ev.append({"ts": now, "tokens": used, "mins": mins})
        d["events"] = ev[-30:]
    was_limited = bool(d.get("limited"))
    d["limited"] = True
    d["scope"] = scope
    d["since"] = d.get("since") if was_limited else now
    d["stage"] = stage or d.get("stage", "")
    d["site"] = site or d.get("site", "")
    if scope == "weekly":
        d["next_try"] = now + _WEEKLY_RECHECK
    else:
        # Erstes Session-Limit → 4 h Cooldown; läuft ein späterer Versuch erneut aufs Limit → stündlich.
        d["next_try"] = now + (_RETRY_EVERY if was_limited else _COOLDOWN)
    d["updated"] = now
    _write(d)


def reset() -> dict:
    """Manuelles „nochmal testen": hebt das Limit-Zeichen auf UND startet das 5-h-Token-Fenster
    frisch (Verbrauch 0). Der Makeover darf danach sofort wieder laufen."""
    d = _read()
    now = time.time()
    d["limited"] = False
    d["scope"] = ""
    d["since"] = 0
    d["next_try"] = 0
    d["session_start"] = now
    d["tokens_used"] = 0
    d["updated"] = now
    _write(d)
    return {"ok": True}


def note_retry_failed() -> None:
    """Ein Wiederaufnahme-Versuch ist erneut aufs Limit gelaufen → nächster Versuch in 1 h."""
    d = _read()
    if d.get("limited"):
        d["next_try"] = time.time() + _RETRY_EVERY
        _write(d)


def clear() -> None:
    """Hebt die Limit-Markierung auf (eine Stufe lief wieder durch / Makeover fertig).
    Der Token-Verbrauch des Fensters bleibt erhalten (nur das Zeitfenster setzt ihn zurück)."""
    d = _read()
    if d.get("limited"):
        d["limited"] = False
        d["since"] = 0
        d["next_try"] = 0
        d["updated"] = time.time()
        _write(d)


def should_try_now() -> bool:
    """Darf das Makeover gerade (wieder) laufen? True wenn kein Limit aktiv ODER der
    geplante Wiederaufnahme-Zeitpunkt erreicht ist (4 h, danach stündlich)."""
    d = _read()
    now = time.time()
    if _maybe_reset_window(d, now):
        _write(d)
        return True
    if not d.get("limited"):
        return True
    return now >= float(d.get("next_try") or 0)


def seconds_to_retry() -> int:
    d = _read()
    if not d.get("limited"):
        return 0
    return max(0, int(float(d.get("next_try") or 0) - time.time()))


# ── Prozent-Schätzung & Status fürs Dashboard ─────────────────────────────────

def percent() -> int:
    """Geschätzter Verbrauch des aktuellen Claude-Fensters in Prozent (0–100).
    Aktives Limit → 100. Sonst gelernter Anteil tokens_used / learned_limit."""
    d = _read()
    now = time.time()
    _maybe_reset_window(d, now)
    if d.get("limited") and now < float(d.get("next_try") or 0):
        return 100
    used = int(d.get("tokens_used") or 0)
    lim = _learned_limit(d)
    if lim <= 0:
        return 0
    return max(0, min(100, int(used / lim * 100)))


def state() -> dict:
    """Schlanker Limit-Status (Rückwärtskompatibel mit dem alten Banner/Badge-Code).
    {limited, since, stage, site, until, minutes_left}."""
    d = _read()
    now = time.time()
    if _maybe_reset_window(d, now):
        _write(d)
    if not d.get("limited"):
        return {"limited": False}
    nxt = float(d.get("next_try") or 0)
    mins = max(0, int((nxt - now) // 60)) if nxt else 0
    return {
        "limited": True,
        "scope": d.get("scope", "session"),
        "since": d.get("since", 0),
        "stage": d.get("stage", ""),
        "site": d.get("site", ""),
        "until": nxt,
        "minutes_left": mins,
    }


def status() -> dict:
    """Voller Budget-Status fürs Kosten-Dashboard."""
    d = _read()
    now = time.time()
    if _maybe_reset_window(d, now):
        _write(d)
    pct = percent()
    limited = bool(d.get("limited"))
    # Mehrfach-Key-Übersicht (mehrere „Claudes") best-effort beilegen.
    keys_info = {}
    try:
        import claude_keys
        keys_info = claude_keys.status()
    except Exception:
        keys_info = {}
    return {
        "limited": limited,
        "scope": d.get("scope", "") if limited else "",
        "percent": pct,
        "near_limit": (pct >= int(_NEAR * 100)),   # ≥95 % → „gleich voll"
        "keys": keys_info,
        "since": d.get("since", 0),
        "stage": d.get("stage", ""),
        "site": d.get("site", ""),
        "next_try": d.get("next_try", 0),
        "minutes_to_retry": (max(0, int((float(d.get("next_try") or 0) - now) // 60))
                             if limited else 0),
        "tokens_used": int(d.get("tokens_used") or 0),
        "learned_limit": _learned_limit(d),
        "events_count": len(d.get("events") or []),
        "window_minutes_left": max(0, int((float(d.get("session_start") or now)
                                           + _WINDOW - now) // 60)),
    }


def costs() -> dict:
    """Fixkosten der Abos (Claude im Limit = im Abo enthalten, 0 variabel) + Tagesanteil."""
    fix_month = CLAUDE_MONTHLY + HF_MONTHLY
    return {
        "claude_month": CLAUDE_MONTHLY,
        "hf_month": HF_MONTHLY,
        "fix_month": round(fix_month, 2),
        "fix_day": round(fix_month / 30.0, 2),
        "claude_in_budget": True,     # Claude geht nur bis Limit → keine variablen Kosten
    }
