"""
geo_cache.py — Adressgenaue Lead-Koordinaten für den 3D-Globus (Graph-Tab).

Die Lead-DB hat nur Stadt/Adresse, keine Koordinaten. Dieses Modul geocodet die STÄRKSTEN
Leads (nach Erwartungswert) EINMAL über Google Places (agent_maps.geocode_latlng) zu echten
lat/lng und cacht das dauerhaft in data/geocode_cache.json. So sitzt beim Reinzoomen jeder
Marker exakt am Betrieb — ohne bei jedem Aufruf die (kostenpflichtige) API zu treffen.

Ablauf:
  • points() liefert SOFORT alle bereits gecachten Punkte zurück und stößt im Hintergrund
    das Geocoding einer begrenzten Zahl noch fehlender Adressen an (API-schonend, gedrosselt).
  • Das Frontend pollt, solange `pending > 0`, und füllt die Karte nach und nach.
  • Treffer → [lat, lng]; kein Treffer → "none" (wird nicht erneut versucht).
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

try:
    import logger
except Exception:
    logger = None

from jsonstate import atomic_write_json

_DATA = Path(os.environ.get("JARVIS_DATA_DIR", "data"))
_CACHE_PATH = _DATA / "geocode_cache.json"

# Nur die stärksten N Leads geocoden (Kosten/Limit deckeln); pro Hintergrund-Lauf max. M.
_MAX_LEADS   = int(os.environ.get("JARVIS_GLOBE_MAX_LEADS", "400") or "400")
_BG_PER_CALL = int(os.environ.get("JARVIS_GEOCODE_PER_CALL", "30") or "30")

_lock = threading.Lock()
_busy = False


def _log(level: str, msg: str) -> None:
    try:
        if logger:
            getattr(logger, level, logger.info)("Globe", msg)
    except Exception:
        pass


def _load() -> dict:
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(d: dict) -> None:
    try:
        atomic_write_json(_CACHE_PATH, d)
    except Exception:
        pass


def _key(name: str, stadt: str) -> str:
    try:
        from leadkey import lead_key
        k = lead_key(name, stadt)
        if k:
            return k
    except Exception:
        pass
    return (f"{name}|{stadt}").strip().lower()


def _query(lead: dict) -> str:
    """Beste Geocoding-Anfrage für einen Lead: volle Adresse, sonst Name + Stadt
    (Places-Textsuche findet den Betrieb auch ohne Straße exakt)."""
    adr = (lead.get("adresse") or "").strip()
    name = (lead.get("name") or "").strip()
    stadt = (lead.get("stadt") or "").strip()
    if adr:
        # Stadt anhängen, falls in der Adresse nicht enthalten (eindeutiger Treffer).
        return adr if stadt.lower() in adr.lower() else f"{adr}, {stadt}"
    return f"{name}, {stadt}".strip(", ")


def _candidates() -> list[dict]:
    """Stärkste Leads mit Stadt (Erwartungswert absteigend), gedeckelt auf _MAX_LEADS.
    Archivierte/0-€-Leads werden mitgenommen (sie sind trotzdem echte Standorte)."""
    try:
        import db_evaluated
        # Schlanke Projektion (nur name/stadt/branche/lead_typ/adresse/erwartungswert) statt
        # SELECT * über 60+ Spalten bei JEDEM Globus-Poll.
        leads = db_evaluated.get_for_globe(limit=5000)
    except Exception:
        return []
    out: list[dict] = []
    for l in leads:
        if not (l.get("stadt") or "").strip():
            continue
        out.append(l)
        if len(out) >= _MAX_LEADS:
            break
    return out


def points(trigger_fill: bool = True) -> dict:
    """Gecachte, adressgenaue Lead-Punkte für den Globus. Stößt optional das Geocoding
    noch fehlender Adressen im Hintergrund an. Gibt {points:[…], pending:int, cached:int}."""
    cache = _load()
    cand = _candidates()
    pts: list[dict] = []
    missing: list[dict] = []
    for l in cand:
        k = _key(l.get("name", ""), l.get("stadt", ""))
        v = cache.get(k)
        if isinstance(v, list) and len(v) == 2:
            pts.append({
                "lat": v[0], "lng": v[1],
                "name": (l.get("name") or "").strip(),
                "stadt": (l.get("stadt") or "").strip(),
                "branche": (l.get("branche") or "").strip(),
                "typ": (l.get("lead_typ") or "cold").strip().lower(),
            })
        elif v == "none":
            continue                     # bekannt: kein Treffer → nicht erneut versuchen
        else:
            missing.append(l)
    if trigger_fill and missing:
        _start_fill(missing)
    return {"points": pts, "pending": len(missing), "cached": len(pts)}


def _start_fill(missing: list[dict]) -> None:
    """Geocodet bis zu _BG_PER_CALL fehlende Adressen in einem Hintergrund-Thread
    (gedrosselt) und schreibt sie in den Cache. Immer nur EIN Lauf gleichzeitig."""
    global _busy
    with _lock:
        if _busy:
            return
        _busy = True

    def _work() -> None:
        global _busy
        try:
            try:
                import agent_maps
            except Exception:
                return
            if not agent_maps.is_available():
                _log("warn", "Geocoding übersprungen — GOOGLE_MAPS_API_KEY fehlt in der .env.")
                return
            cache = _load()
            done = hits = 0
            for l in missing[:_BG_PER_CALL]:
                k = _key(l.get("name", ""), l.get("stadt", ""))
                try:
                    ll = agent_maps.geocode_latlng(_query(l))
                except Exception:
                    ll = None
                cache[k] = [round(ll[0], 5), round(ll[1], 5)] if ll else "none"
                done += 1
                if ll:
                    hits += 1
                time.sleep(0.12)                 # Places-API schonen (Drosselung)
            _save(cache)
            _log("info", f"Geocoding: {hits}/{done} Lead-Adressen ergänzt "
                         f"({max(0, len(missing) - done)} noch offen).")
        finally:
            with _lock:                          # _busy wird unter _lock gesetzt → auch hier zurücksetzen
                _busy = False

    threading.Thread(target=_work, name="geocode-fill", daemon=True).start()
