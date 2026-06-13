"""
Cloud-Sync — überträgt bewertete Leads inkrementell nach Supabase.

Start: beim App-Launch (10s verzögert, damit Flask fertig initialisiert).
Danach: alle 10 Minuten — nur Leads mit raw_id > max(remote raw_id).
Manuell: POST /api/sync  (full=true für vollständige Neusynchronisation).

Sicherheit:
  - SUPABASE_SERVICE_KEY wird NUR aus .env gelesen, nie geloggt
  - Service-Role-Key umgeht RLS (Schreibzugriff) — Anon-Key liest nur
  - HTTPS erzwungen (Supabase-URLs beginnen immer mit https://)
  - Keine sensitiven Daten in Logs (kein Key, keine E-Mails in Fehlermeldungen)
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request

import db_evaluated
import logger

# ── Konfiguration ──────────────────────────────────────────────────────────────
SYNC_INTERVAL = 600          # Sekunden zwischen zwei Sync-Läufen
_BATCH        = 100          # Leads pro API-Request
_TIMEOUT      = 20           # HTTP-Timeout in Sekunden
_TABLE        = "jarvis_leads"

# Spalten die übertragen werden — kein email_entwurf, score_breakdown, verify_log
# (interne Langfelder, die die Railway-Seite nicht braucht)
_SYNC_COLS = [
    "raw_id", "schluessel", "name", "adresse", "stadt", "bundesland", "branche",
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


# ── Interne Helfer ─────────────────────────────────────────────────────────────

def _cfg() -> tuple[str, str]:
    """(supabase_url, service_key) — leere Strings wenn nicht konfiguriert."""
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


def _get_max_remote_id(url: str, key: str) -> int:
    """Höchste raw_id in Supabase — bestimmt den Startpunkt des inkrementellen Uploads."""
    endpoint = f"{url}/rest/v1/{_TABLE}?select=raw_id&order=raw_id.desc&limit=1"
    req = urllib.request.Request(endpoint, headers=_headers(key))
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            data = json.loads(r.read())
            return int(data[0]["raw_id"]) if data else 0
    except Exception as e:
        logger.warn("CloudSync", f"Konnte max raw_id nicht abrufen: {type(e).__name__}")
        return 0


def _upsert_batch(url: str, key: str, leads: list[dict]) -> int:
    """UPSERT einer Batch. Gibt Anzahl erfolgreich gesendeter Leads zurück."""
    rows = [{k: lead.get(k) for k in _SYNC_COLS if k in lead} for lead in leads]
    payload = json.dumps(rows, ensure_ascii=False, default=str).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/rest/v1/{_TABLE}",
        data=payload,
        headers=_headers(key),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT):
            return len(leads)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        logger.error("CloudSync", f"HTTP {e.code} beim Upload: {body}")
        return 0
    except Exception as e:
        logger.error("CloudSync", f"Netzwerkfehler: {type(e).__name__}: {e}")
        return 0


# ── Öffentliche API ────────────────────────────────────────────────────────────

def sync_once(full: bool = False) -> dict:
    """
    Einmalige Synchronisation.
    full=True  → alle Leads übertragen (ignoriert remote max_id).
    full=False → nur Leads mit raw_id > höchster bekannter remote raw_id.

    Gibt Status-Dict zurück:
      {ok, uploaded, skipped, total, reason?}
    """
    if not is_configured():
        return {
            "ok":     False,
            "reason": "SUPABASE_URL oder SUPABASE_SERVICE_KEY fehlen in .env",
        }

    url, key = _cfg()
    min_id   = 0 if full else _get_max_remote_id(url, key)
    all_local = db_evaluated.get_all(limit=100_000, sort="datum")
    to_upload = [l for l in all_local if (l.get("raw_id") or 0) > min_id]

    if not to_upload:
        return {"ok": True, "uploaded": 0, "skipped": len(all_local), "total": len(all_local)}

    uploaded = 0
    for i in range(0, len(to_upload), _BATCH):
        uploaded += _upsert_batch(url, key, to_upload[i : i + _BATCH])

    return {
        "ok":       True,
        "uploaded": uploaded,
        "skipped":  len(all_local) - len(to_upload),
        "total":    len(all_local),
    }


def _sync_loop() -> None:
    time.sleep(10)  # App-Start abwarten
    while True:
        try:
            r = sync_once()
            if r.get("ok"):
                if r["uploaded"]:
                    logger.success(
                        "CloudSync",
                        f"↑ {r['uploaded']} Leads hochgeladen "
                        f"({r['skipped']} bereits synchron, {r['total']} gesamt)",
                    )
                else:
                    logger.info("CloudSync", f"Alles synchron — {r['total']} Leads in Cloud")
            else:
                logger.warn("CloudSync", f"Sync übersprungen: {r.get('reason', '?')}")
        except Exception as e:
            logger.error("CloudSync", f"Unerwarteter Fehler: {e}")
        time.sleep(SYNC_INTERVAL)


def start() -> None:
    """Startet den Sync-Daemon-Thread. Mehrfachaufruf sicher (idempotent)."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    t = threading.Thread(target=_sync_loop, name="CloudSync", daemon=True)
    t.start()
    if is_configured():
        logger.info("CloudSync", "Sync-Thread aktiv — Upload alle 10 Min (inkrementell)")
    else:
        logger.warn("CloudSync", "SUPABASE_URL / SUPABASE_SERVICE_KEY fehlen — Sync deaktiviert")
