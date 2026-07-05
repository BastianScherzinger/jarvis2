"""
cost_tracker.py — JARVIS Tageskostentracking.
Verfolgt: Anthropic API Tokens (→ €), Higgsfield Credits (→ €), Stromverbrauch.
Persistiert täglich-aggregiert in data/costs.json.
Thread-safe. Jeder track_*()-Aufruf ist fire-and-forget (kein Crash bei Fehler).
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from jsonstate import atomic_write_json

_BASE    = Path(__file__).parent
_DB_PATH = _BASE / "data" / "costs.json"
_lock    = threading.Lock()

# ── Preise (EUR) ──────────────────────────────────────────────────────────────

_USD_EUR = 0.92   # aktueller Wechselkurs-Faktor

# Anthropic Input/Output-Preise in $ pro 1M Tokens → in EUR umgerechnet
_API_PRICES: dict[str, dict] = {
    "claude-sonnet-4-6":         {"in": 3.00 / 1e6 * _USD_EUR, "out": 15.0 / 1e6 * _USD_EUR},
    "claude-sonnet-4-5":         {"in": 3.00 / 1e6 * _USD_EUR, "out": 15.0 / 1e6 * _USD_EUR},
    "claude-opus-4-8":           {"in": 15.0 / 1e6 * _USD_EUR, "out": 75.0 / 1e6 * _USD_EUR},
    "claude-opus-4-7":           {"in": 15.0 / 1e6 * _USD_EUR, "out": 75.0 / 1e6 * _USD_EUR},
    "claude-haiku-4-5-20251001": {"in": 0.80 / 1e6 * _USD_EUR, "out":  4.0 / 1e6 * _USD_EUR},
    "claude-haiku":              {"in": 0.80 / 1e6 * _USD_EUR, "out":  4.0 / 1e6 * _USD_EUR},
    "default":                   {"in": 3.00 / 1e6 * _USD_EUR, "out": 15.0 / 1e6 * _USD_EUR},
}

_HF_CREDIT_EUR = 0.04    # ~4 Cent pro Higgsfield-Credit (Schätzung)
_CPU_W         = 45      # Watt Notebook-CPU
_GPU_W         = 180     # Watt Mid-Range GPU
_EUR_PER_KWH   = 0.35    # Deutschland Ø Strompreis


def _power_eur(seconds: float, use_gpu: bool) -> float:
    watt = (_CPU_W + _GPU_W) if use_gpu else _CPU_W
    return round((watt * seconds) / (1000 * 3600) * _EUR_PER_KWH, 6)


# ── Persistenz ────────────────────────────────────────────────────────────────

def _today() -> str:
    return date.today().isoformat()


def _load() -> dict:
    try:
        return json.loads(_DB_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        atomic_write_json(_DB_PATH, data, indent=2)
    except Exception:
        pass


def _day_entry(data: dict, d: str) -> dict:
    if d not in data:
        data[d] = {
            "events": [],
            "totals": {
                "tokens_in": 0, "tokens_out": 0, "api_eur": 0.0,
                "hf_credits": 0, "hf_eur": 0.0,
                "compute_sec": 0.0, "power_eur": 0.0,
                "total_eur": 0.0,
                "sites_built": 0, "leads_evaluated": 0,
                "images_generated": 0, "videos_generated": 0,
            },
        }
    return data[d]


def _recalc_total(day: dict) -> None:
    t = day["totals"]
    t["total_eur"] = round(t["api_eur"] + t["hf_eur"] + t["power_eur"], 4)


# ── Öffentliche Track-Funktionen ──────────────────────────────────────────────

def track_api(model: str, input_tokens: int, output_tokens: int,
              task: str = "", name: str = "") -> float:
    """Trackt einen Anthropic API-Call. Gibt Kosten in EUR zurück. Thread-safe, silent."""
    try:
        p    = _API_PRICES.get(model) or _API_PRICES["default"]
        cost = round(input_tokens * p["in"] + output_tokens * p["out"], 6)
        ev   = {
            "ts": datetime.now().strftime("%H:%M:%S"),
            "type": "api", "model": model[:30],
            "in": int(input_tokens), "out": int(output_tokens),
            "eur": cost, "task": task, "name": name[:60],
        }
        with _lock:
            data = _load()
            d    = _day_entry(data, _today())
            d["events"].append(ev)
            d["totals"]["tokens_in"]  += int(input_tokens)
            d["totals"]["tokens_out"] += int(output_tokens)
            d["totals"]["api_eur"]     = round(d["totals"]["api_eur"] + cost, 6)
            _recalc_total(d)
            _save(data)
        return cost
    except Exception:
        return 0.0


def track_higgsfield(credits: int, task: str = "", name: str = "") -> float:
    """Trackt einen Higgsfield-API-Aufruf. Gibt Kosten in EUR zurück."""
    try:
        cost = round(int(credits) * _HF_CREDIT_EUR, 4)
        ev   = {
            "ts": datetime.now().strftime("%H:%M:%S"),
            "type": "higgsfield", "credits": int(credits),
            "eur": cost, "task": task, "name": name[:60],
        }
        with _lock:
            data = _load()
            d    = _day_entry(data, _today())
            d["events"].append(ev)
            d["totals"]["hf_credits"] += int(credits)
            d["totals"]["hf_eur"]      = round(d["totals"]["hf_eur"] + cost, 4)
            if task in ("video_gen", "image_gen"):
                key = "videos_generated" if "video" in task else "images_generated"
                d["totals"][key] = d["totals"].get(key, 0) + 1
            _recalc_total(d)
            _save(data)
        return cost
    except Exception:
        return 0.0


def track_openai_image(quality: str = "medium", task: str = "image_gen",
                       name: str = "") -> float:
    """Trackt ein OpenAI-Bild (gpt-image-1). Kosten je Bild geschätzt nach Qualität
    (Landscape ~1536×1024). Gibt EUR zurück. Thread-safe, silent."""
    try:
        usd = {"low": 0.02, "medium": 0.07, "high": 0.25}.get(
            (quality or "medium").lower(), 0.07)
        cost = round(usd * _USD_EUR, 4)
        ev = {
            "ts": datetime.now().strftime("%H:%M:%S"),
            "type": "openai_image", "quality": (quality or "medium")[:10],
            "eur": cost, "task": task, "name": name[:60],
        }
        with _lock:
            data = _load()
            d    = _day_entry(data, _today())
            d["events"].append(ev)
            d["totals"]["api_eur"] = round(d["totals"]["api_eur"] + cost, 6)
            d["totals"]["images_generated"] = d["totals"].get("images_generated", 0) + 1
            _recalc_total(d)
            _save(data)
        return cost
    except Exception:
        return 0.0


def track_compute(seconds: float, use_gpu: bool = False,
                  task: str = "", name: str = "") -> float:
    """Trackt CPU/GPU-Rechenzeit (Stromkosten). Gibt Kosten in EUR zurück."""
    try:
        cost = _power_eur(seconds, use_gpu)
        ev   = {
            "ts": datetime.now().strftime("%H:%M:%S"),
            "type": "compute", "seconds": round(float(seconds), 1),
            "gpu": bool(use_gpu), "eur": cost, "task": task, "name": name[:60],
        }
        with _lock:
            data = _load()
            d    = _day_entry(data, _today())
            d["events"].append(ev)
            d["totals"]["compute_sec"] = round(d["totals"]["compute_sec"] + float(seconds), 1)
            d["totals"]["power_eur"]   = round(d["totals"]["power_eur"] + cost, 6)
            # Aktivitätszähler
            if task == "website_build":
                d["totals"]["sites_built"] = d["totals"].get("sites_built", 0) + 1
            elif task == "lead_eval":
                d["totals"]["leads_evaluated"] = d["totals"].get("leads_evaluated", 0) + 1
            elif task == "image_gen":
                d["totals"]["images_generated"] = d["totals"].get("images_generated", 0) + 1
            elif task == "video_gen":
                d["totals"]["videos_generated"] = d["totals"].get("videos_generated", 0) + 1
            _recalc_total(d)
            _save(data)
        return cost
    except Exception:
        return 0.0


def track_message(model: str, msg, task: str = "", name: str = "") -> float:
    """Bequemer Wrapper: liest die Token-Usage direkt aus einem Anthropic-Message-
    Objekt (egal ob aus messages.create() oder stream.get_final_message()) und
    bucht sie als API-Kosten. Thread-safe, silent — nie crashend."""
    try:
        u = getattr(msg, "usage", None)
        if not u:
            return 0.0
        return track_api(
            model,
            getattr(u, "input_tokens", 0) or 0,
            getattr(u, "output_tokens", 0) or 0,
            task, name,
        )
    except Exception:
        return 0.0


def today_summary() -> dict:
    """Heutiger Kostenzusammenfassung-Dict."""
    with _lock:
        data = _load()
    return _day_entry(data, _today()).get("totals", {})


# ── Paid-Modus: bezahlte Extra-Tokens erkennen + Builder-Boost ────────────────
#
# Normalfall: der Site-Builder läuft über die Claude-Abo-Anmeldung (claude -p) und lokale
# Ollama-Modelle — es fallen KEINE Extra-Token-Kosten an. Bezahlte Extra-TOKENS fließen nur:
# (a) heute wurden echte Anthropic-API-Tokens gebucht (tokens_in/out > 0 — NICHT api_eur,
#     das auch OpenAI-Hero-Bilder enthält, die das Claude-Session-Limit nicht aufheben), oder
# (b) mehrere ANTHROPIC-Keys sind konfiguriert — dann laufen die headless-Builder-Läufe über
#     ANTHROPIC_API_KEY (claude_coder) statt über das Abo = bezahlt pro Token.
# Ist der Paid-Modus aktiv (JARVIS_PAID_BOOST, Default AN), verdoppelt der Auto-Builder sein
# Tageslimit: wer pro Token zahlt, hängt nicht am Abo-Session-Limit und kann doppelt bauen.

def paid_tokens_detected() -> dict:
    """Erkennt, ob aktuell bezahlte Extra-Tokens im Spiel sind.
    Gibt {"paid": bool, "reason": str, "api_eur_today": float} zurück. Wirft nie."""
    api_eur, tokens = 0.0, 0
    try:
        t = today_summary()
        api_eur = float(t.get("api_eur", 0.0) or 0.0)
        tokens  = int(t.get("tokens_in", 0) or 0) + int(t.get("tokens_out", 0) or 0)
    except Exception:
        pass
    if tokens > 0:
        return {"paid": True,
                "reason": f"heute {tokens:,} API-Tokens gebucht ({api_eur:.4f} €)",
                "api_eur_today": api_eur}
    try:
        import claude_keys
        n = claude_keys.count()
        if n > 1:
            return {"paid": True,
                    "reason": f"{n} ANTHROPIC-Keys — Builder läuft "
                              "über API-Key (bezahlt pro Token)",
                    "api_eur_today": api_eur}
    except Exception:
        pass
    return {"paid": False, "reason": "nur Abo/lokal — keine Extra-Token-Kosten",
            "api_eur_today": api_eur}


# 60s-TTL-Cache: paid_boost_active() sitzt in Hot-Paths (auto_builder-Loop, Status-Poll des
# Dashboards alle paar Sekunden) — ohne Cache würde JEDER Aufruf die komplette, wachsende
# data/costs.json unter _lock lesen und parsen. (TTL-Muster wie _BEST_MODEL in scrapers/_http.)
_PAID_CACHE: list = [None, 0.0]   # [bool, cache_ts]
_PAID_CACHE_TTL = 60


def paid_boost_active() -> bool:
    """True, wenn bezahlte Tokens erkannt wurden UND der Boost eingeschaltet ist
    (JARVIS_PAID_BOOST, Default AN; aus mit 0/false/no/off). Ergebnis 60s gecacht. Wirft nie."""
    flag = os.environ.get("JARVIS_PAID_BOOST", "1").strip().lower() \
        not in ("0", "false", "no", "off", "")
    if not flag:
        return False
    if _PAID_CACHE[0] is not None and time.time() - _PAID_CACHE[1] < _PAID_CACHE_TTL:
        return _PAID_CACHE[0]
    try:
        val = bool(paid_tokens_detected().get("paid"))
    except Exception:
        val = False
    _PAID_CACHE[0] = val
    _PAID_CACHE[1] = time.time()
    return val


# ── Monatliche Extra-Nutzung (Claude Pro: Tokens sind gratis bis zum Abo-Limit;
# NUR wenn Anthropic-"Extra usage" greift, fließt echtes Geld) + Higgsfield ─────
#
# track_api()/track_message() bucht NUR dann ein "api"-Event, wenn tatsächlich über einen
# echten Anthropic-API-Key abgerechnete Tokens anfallen (siehe paid_tokens_detected() oben:
# reguläre `claude`-CLI-Läufe über die Pro-Abo-Session laufen NIE durch track_api()). Die
# Summe aller "api"-Events des laufenden Kalendermonats IST daher exakt die reale Extra-
# Nutzung in EUR — kein neuer Heuristik-Layer nötig. Persistiert automatisch über
# data/costs.json (Tage werden nie gelöscht) und "resettet" sich jeden Monat von selbst,
# weil nur Tage mit passendem Monats-Präfix gezählt werden — überlebt jeden Neustart bis
# zum Monatswechsel, ganz ohne eigene State-Datei.

def _month_key(d: str | None = None) -> str:
    return (d or _today())[:7]                      # "YYYY-MM"


def _events_for_month(month: str | None = None) -> list:
    month = month or _month_key()
    with _lock:
        data = _load()
    out: list = []
    for day_key, day in data.items():
        if day_key[:7] == month:
            out.extend(day.get("events", []))
    return out


def extra_usage_month(month: str | None = None) -> dict:
    """Echte Anthropic-Extra-Nutzung (nur `type=='api'`-Events, KEINE OpenAI-Bilder/Compute/
    Higgsfield) des laufenden Kalendermonats. {month, eur, tokens_in, tokens_out}."""
    month = month or _month_key()
    eur = 0.0
    tokens_in = tokens_out = 0
    for ev in _events_for_month(month):
        if ev.get("type") == "api":
            eur        += float(ev.get("eur", 0.0) or 0.0)
            tokens_in  += int(ev.get("in", 0) or 0)
            tokens_out += int(ev.get("out", 0) or 0)
    return {"month": month, "eur": round(eur, 4),
            "tokens_in": tokens_in, "tokens_out": tokens_out}


def higgsfield_month(month: str | None = None) -> dict:
    """Higgsfield-Nutzung (Credits + geschätzte EUR) des laufenden Kalendermonats —
    dieselben persistierten Tages-Events wie extra_usage_month(), nur `type=='higgsfield'`."""
    month = month or _month_key()
    credits = 0
    eur = 0.0
    for ev in _events_for_month(month):
        if ev.get("type") == "higgsfield":
            credits += int(ev.get("credits", 0) or 0)
            eur     += float(ev.get("eur", 0.0) or 0.0)
    return {"month": month, "credits": credits, "eur": round(eur, 4)}


def history(days: int = 14) -> list:
    """Letzte N Tage als Liste [{date, total_eur, api_eur, ...}]."""
    with _lock:
        data = _load()
    result = []
    for i in range(days - 1, -1, -1):
        d   = (date.today() - timedelta(days=i)).isoformat()
        tot = data.get(d, {}).get("totals", {})
        result.append({
            "date":       d,
            "total_eur":  tot.get("total_eur", 0.0),
            "api_eur":    tot.get("api_eur", 0.0),
            "power_eur":  tot.get("power_eur", 0.0),
            "hf_eur":     tot.get("hf_eur", 0.0),
            "tokens_in":  tot.get("tokens_in", 0),
            "tokens_out": tot.get("tokens_out", 0),
            "hf_credits": tot.get("hf_credits", 0),
            "sites":      tot.get("sites_built", 0),
            "leads":      tot.get("leads_evaluated", 0),
        })
    return result


def recent_events(limit: int = 30) -> list:
    """Letzte N Events des heutigen Tages."""
    with _lock:
        data = _load()
    events = data.get(_today(), {}).get("events", [])
    return events[-limit:]


def per_site_costs(limit: int = 20) -> list:
    """Kosten aggregiert pro Website-Name (heute)."""
    with _lock:
        data = _load()
    events = data.get(_today(), {}).get("events", [])
    agg: dict[str, dict] = {}
    for ev in events:
        n = ev.get("name", "").strip() or "Unbekannt"
        if n not in agg:
            agg[n] = {"name": n, "total_eur": 0.0, "tokens": 0, "tasks": []}
        agg[n]["total_eur"] = round(agg[n]["total_eur"] + ev.get("eur", 0.0), 4)
        if ev.get("type") == "api":
            agg[n]["tokens"] += ev.get("in", 0) + ev.get("out", 0)
        task = ev.get("task", "")
        if task and task not in agg[n]["tasks"]:
            agg[n]["tasks"].append(task)
    return sorted(agg.values(), key=lambda x: x["total_eur"], reverse=True)[:limit]
