"""
Cloud-Sync — Supabase als primärer Lead-Speicher.

Schreiben:  Sofort nach jeder Evaluierung (async, fire-and-forget).
Lesen:      Beim App-Start werden alle remote Leads in den lokalen Cache gezogen.
Batch-Sync: Alle 10 Min werden fehlende Leads nachgeschoben (Fallback).

Sicherheit:
  - SUPABASE_SERVICE_KEY nur aus .env, niemals geloggt
  - HTTPS erzwungen (URL beginnt immer https://)
  - Keine sensiblen Felder in Fehlermeldungen
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request

import db_evaluated
import logger

SYNC_INTERVAL = 600          # Sekunden zwischen Batch-Syncs
_BATCH        = 100          # Leads pro API-Request
_TIMEOUT      = 20           # HTTP-Timeout
_TABLE        = "jarvis_leads"

_SYNC_COLS = [
    "raw_id", "lead_key", "schluessel", "name", "adresse", "stadt", "bundesland", "branche",
    "telefon", "email_vorhanden", "email_adresse", "telefon_verifiziert",
    "has_website", "website_url", "discovered_website",
    "website_veraltet", "website_alter_jahre",
    "fotos_in_maps", "bilder_vorhanden", "foto_url",
    "hat_nur_social", "beschreibung", "ist_privat_zahler", "firmengroesse",
    "potenzial_euro", "potenzial_begruendung", "pitch_hook",
    "score", "lead_typ", "verifiziert", "status", "bewertet_am",
]

_started = False
_lock    = threading.Lock()


# ── Helfer ─────────────────────────────────────────────────────────────────────

def make_lead_key(name: str, stadt: str) -> str:
    """Globaler Unique-Key über alle PCs: MD5(lower(name)|lower(stadt)).
    Identisch mit db_evaluated._compute_lead_key — beide müssen synchron bleiben."""
    s = f"{(name or '').strip().lower()}|{(stadt or '').strip().lower()}"
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _cfg() -> tuple[str, str]:
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key =  os.environ.get("SUPABASE_SERVICE_KEY") or ""
    return url, key


def is_configured() -> bool:
    url, key = _cfg()
    return bool(url and key and url.startswith("https://"))


def _headers(key: str) -> dict:
    return {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
        "Prefer":        "resolution=merge-duplicates,return=minimal",
    }


def _upsert_batch(url: str, key: str, leads: list[dict]) -> int:
    rows = []
    for lead in leads:
        row = {k: lead.get(k) for k in _SYNC_COLS if k in lead}
        # lead_key immer mitschicken (Dedup-Schlüssel in Supabase)
        if not row.get("lead_key"):
            row["lead_key"] = make_lead_key(lead.get("name", ""), lead.get("stadt", ""))
        rows.append(row)
    payload = json.dumps(rows, ensure_ascii=False, default=str).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/rest/v1/{_TABLE}",
        data=payload, headers=_headers(key), method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT):
            return len(rows)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        logger.error("CloudSync", f"HTTP {e.code}: {body}")
        return 0
    except Exception as e:
        logger.error("CloudSync", f"Upload-Fehler: {type(e).__name__}")
        return 0


def _fetch_all_remote(url: str, key: str) -> list[dict]:
    """Alle lead_keys aus Supabase laden (für Dedup beim Pull)."""
    endpoint = f"{url}/rest/v1/{_TABLE}?select=lead_key,name,stadt&limit=50000"
    req = urllib.request.Request(endpoint, headers=_headers(key))
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return json.loads(r.read())
    except Exception:
        return []


def _fetch_remote_full(url: str, key: str, offset: int = 0) -> list[dict]:
    """Vollständige Lead-Daten aus Supabase (für lokalen Cache). Pagination via Range-Header."""
    endpoint = f"{url}/rest/v1/{_TABLE}?select=*&order=score.desc"
    hdrs = dict(_headers(key))
    hdrs["Range-Unit"] = "items"
    hdrs["Range"]      = f"{offset}-{offset + _BATCH - 1}"
    req = urllib.request.Request(endpoint, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return json.loads(r.read())
    except Exception:
        return []


# ── Sofort-Push (nach jeder Evaluierung) ──────────────────────────────────────

def push_lead(row: dict) -> None:
    """Fire-and-forget: einen einzelnen Lead sofort nach Supabase pushen."""
    threading.Thread(target=_push_one, args=(row,), daemon=True).start()


def _push_one(row: dict) -> None:
    if not is_configured():
        return
    url, key = _cfg()
    _upsert_batch(url, key, [row])


# ── Startup-Pull: Supabase → lokaler Cache ─────────────────────────────────────

def pull_and_cache() -> dict:
    """
    Zieht alle remote Leads in den lokalen Cache (db_evaluated).
    Wird beim App-Start aufgerufen — füllt den Cache mit Leads von allen PCs.
    """
    if not is_configured():
        return {"ok": False, "reason": "nicht konfiguriert"}
    url, key = _cfg()

    # Lokale lead_keys kennen (für schnellen Abgleich)
    local_leads = db_evaluated.get_all(limit=200_000)
    local_keys  = {make_lead_key(l.get("name", ""), l.get("stadt", "")) for l in local_leads}
    logger.info("CloudSync", f"Pull: {len(local_keys)} Leads lokal, lade remote Daten…")

    pulled = 0
    offset = 0
    while True:
        remote_batch = _fetch_remote_full(url, key, offset)
        if not remote_batch:
            break
        for remote in remote_batch:
            rk = remote.get("lead_key") or make_lead_key(remote.get("name",""), remote.get("stadt",""))
            if rk in local_keys:
                continue
            # Remote Lead in lokalen Cache schreiben
            cache_row = {k: remote.get(k) for k in db_evaluated._COLUMNS if k in remote}
            cache_row["lead_key"] = rk
            cache_row["raw_id"]   = None   # kein lokaler raw_id für remote Leads
            try:
                db_evaluated.insert_evaluated(cache_row)
                local_keys.add(rk)
                pulled += 1
            except Exception:
                pass
        if len(remote_batch) < _BATCH:
            break
        offset += _BATCH

    if pulled:
        logger.success("CloudSync", f"↓ {pulled} neue Leads aus Cloud in Cache geladen")
    else:
        logger.info("CloudSync", "Cache aktuell — keine neuen remote Leads")
    return {"ok": True, "pulled": pulled}


# ── Batch-Sync (alle 10 Min, Fallback) ────────────────────────────────────────

def sync_once(full: bool = False) -> dict:
    if not is_configured():
        return {"ok": False, "reason": "SUPABASE_URL / SUPABASE_SERVICE_KEY fehlen in .env"}

    url, key = _cfg()
    remote_keys: set[str] = set()
    if not full:
        for r in _fetch_all_remote(url, key):
            k = r.get("lead_key") or make_lead_key(r.get("name",""), r.get("stadt",""))
            remote_keys.add(k)

    all_local = db_evaluated.get_all(limit=100_000, sort="datum")
    to_upload = []
    for l in all_local:
        lk = l.get("lead_key") or make_lead_key(l.get("name",""), l.get("stadt",""))
        if full or lk not in remote_keys:
            to_upload.append(l)

    if not to_upload:
        return {"ok": True, "uploaded": 0, "skipped": len(all_local), "total": len(all_local)}

    uploaded = 0
    for i in range(0, len(to_upload), _BATCH):
        uploaded += _upsert_batch(url, key, to_upload[i : i + _BATCH])

    return {"ok": True, "uploaded": uploaded,
            "skipped": len(all_local) - len(to_upload), "total": len(all_local)}


def _sync_loop() -> None:
    time.sleep(12)  # App-Start abwarten
    while True:
        try:
            r = sync_once()
            if r.get("ok"):
                if r["uploaded"]:
                    logger.success("CloudSync",
                        f"↑ {r['uploaded']} Leads hochgeladen "
                        f"({r['skipped']} synchron, {r['total']} gesamt)")
                else:
                    logger.info("CloudSync", f"Alles synchron — {r['total']} Leads in Cloud")
            else:
                logger.warn("CloudSync", f"Sync übersprungen: {r.get('reason','?')}")
        except Exception as e:
            logger.error("CloudSync", f"Unerwarteter Fehler: {e}")
        time.sleep(SYNC_INTERVAL)


def start() -> None:
    """Startet Sync-Thread. Idempotent."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    t = threading.Thread(target=_sync_loop, name="CloudSync", daemon=True)
    t.start()
    logger.info("CloudSync", "Sync-Thread gestartet — Push nach jeder Evaluierung + Batch alle 10 Min")
