"""
cloud_sync_websites.py — Supabase-Sync für gebaute Webseiten (Cross-PC).

Push:  fire-and-forget, sobald eine Webseite fertig ist / ein Bild hinzugefügt /
       eine Seite gelöscht wird.
Pull:  beim App-Start + periodisch → alle PCs zeigen dieselben fertigen Seiten,
       Live-/Repo-Links und Bilder.
Bilder: hinzugefügte Bilder landen im öffentlichen Supabase-Storage-Bucket
        'website-images'; in der DB stehen dann öffentliche URLs (cross-PC sichtbar).

Sicherheit: SUPABASE_SERVICE_KEY nur aus .env, nie geloggt; HTTPS erzwungen.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request

import logger

_TABLE        = "jarvis_websites"
_BUCKET       = "website-images"
_TIMEOUT      = 20
PULL_INTERVAL = 300

# Webseiten-PULL (remote → lokale Anzeige) standardmäßig AUS: Webseiten sind LOKALE Ordner-
# Artefakte — die von einem anderen PC kann dieser hier weder bauen noch deployen noch
# reparieren. Sie nur reinzusyncen füllt das Dashboard mit fremden „404"-Karten und macht den
# 5-Seiten-Bestand unübersichtlich (Sirs Beschwerde „aufeinmal alle alten wieder da"). Der PUSH
# bleibt an (eigene Seiten erscheinen in der Cloud/Leadsite). Cross-PC-Anzeige wieder an:
# JARVIS_SYNC_WEBSITES_PULL=1.
def _pull_enabled() -> bool:
    return (os.environ.get("JARVIS_SYNC_WEBSITES_PULL", "0") or "0").strip().lower() in (
        "1", "true", "yes", "ja", "on")

_SYNC_COLS = ["name", "stadt", "branche", "repo_url", "live_url", "live",
              "status", "step", "kontakt_email"]

_started = False
_lock    = threading.Lock()


def _cfg() -> "tuple[str, str]":
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or ""
    return url, key


def is_configured() -> bool:
    url, key = _cfg()
    return bool(url and key and url.startswith("https://"))


def site_key(name: str, stadt: str) -> str:
    """Cross-PC-Schlüssel je Webseite — identisch zum Lead-Key (name|stadt)."""
    from leadkey import lead_key
    return lead_key(name or "", stadt or "")


def _headers(key: str, *, write: bool = False) -> dict:
    h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if write:
        h["Prefer"] = "resolution=merge-duplicates,return=minimal"
    return h


# ── Bilder → Supabase-Storage ─────────────────────────────────────────────────

def upload_image(name: str, stadt: str, filename: str, data: bytes,
                 content_type: str = "image/png") -> str:
    """Lädt ein Bild in den öffentlichen Bucket und gibt die öffentliche URL zurück
    (oder '' bei Fehler/nicht konfiguriert → Aufrufer nutzt dann den lokalen Pfad)."""
    if not is_configured() or not data:
        return ""
    url, key = _cfg()
    sk = site_key(name, stadt)
    safe = (filename or "bild.png").replace("/", "_").replace("\\", "_")
    path = f"{sk}/{int(time.time())}_{safe}"
    endpoint = f"{url}/storage/v1/object/{_BUCKET}/{path}"
    req = urllib.request.Request(endpoint, data=data, method="POST", headers={
        "apikey": key, "Authorization": f"Bearer {key}",
        "Content-Type": content_type, "x-upsert": "true"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT):
            return f"{url}/storage/v1/object/public/{_BUCKET}/{path}"
    except Exception:
        return ""


# ── Push ──────────────────────────────────────────────────────────────────────

def _remote_row(row: dict) -> dict:
    out = {k: row.get(k) for k in _SYNC_COLS}
    out["site_key"] = row.get("site_key") or site_key(row.get("name", ""), row.get("stadt", ""))
    imgs = row.get("images") or []
    out["images"]  = imgs if isinstance(imgs, list) else []
    out["live"]    = int(row.get("live") or 0)
    out["updated"] = row.get("updated") or time.time()
    return out


def push(row: dict) -> None:
    """Fire-and-forget: eine Webseiten-Zeile nach Supabase pushen."""
    if not is_configured():
        return
    threading.Thread(target=_push_one, args=(dict(row),), daemon=True).start()


def _push_one(row: dict) -> None:
    url, key = _cfg()
    payload = json.dumps([_remote_row(row)], ensure_ascii=False, default=str).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/rest/v1/{_TABLE}?on_conflict=site_key",
        data=payload, headers=_headers(key, write=True), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT):
            return
    except urllib.error.HTTPError as e:
        logger.error("WebSync", f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:160]}")
    except Exception as e:
        logger.warn("WebSync", f"Push fehlgeschlagen: {type(e).__name__}")


def delete_remote(name: str, stadt: str) -> None:
    if not is_configured():
        return
    url, key = _cfg()
    sk = site_key(name, stadt)
    req = urllib.request.Request(
        f"{url}/rest/v1/{_TABLE}?site_key=eq.{sk}",
        headers=_headers(key), method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT):
            return
    except Exception:
        pass


# ── Pull ──────────────────────────────────────────────────────────────────────

def pull_into_db() -> dict:
    """Zieht alle remote Webseiten in die lokale db_websites (Cross-PC-Anzeige).
    Standard AUS (s. _pull_enabled) — verhindert, dass fremde/alte Seiten das Dashboard fluten."""
    if not _pull_enabled():
        return {"ok": False, "reason": "websites-pull deaktiviert (JARVIS_SYNC_WEBSITES_PULL=1 aktiviert es)"}
    if not is_configured():
        return {"ok": False, "reason": "nicht konfiguriert"}
    url, key = _cfg()
    import db_websites
    endpoint = f"{url}/rest/v1/{_TABLE}?select=*&order=updated.desc&limit=10000"
    req = urllib.request.Request(endpoint, headers=_headers(key))
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            rows = json.loads(r.read())
    except Exception as e:
        logger.warn("WebSync", f"Pull-Fehler: {type(e).__name__}")
        return {"ok": False, "reason": type(e).__name__}
    n = 0
    for remote in rows:
        try:
            db_websites.upsert_remote(remote)
            n += 1
        except Exception:
            pass
    if n:
        logger.success("WebSync", f"↓ {n} Webseite(n) aus der Cloud synchronisiert")
    return {"ok": True, "pulled": n}


def push_all_local() -> dict:
    """Schiebt alle lokalen, identifizierbaren Webseiten in die Cloud — damit auch
    bestehende (vor dem Sync gebaute) Seiten cross-PC erscheinen. Best-effort."""
    if not is_configured():
        return {"ok": False}
    import db_websites
    n = 0
    for row in db_websites.get_all():
        if not row.get("site_key"):
            continue
        if (row.get("job_id") or "").startswith("remote-"):   # rein gepullte nicht zurückschieben
            continue
        if row.get("live_url") or row.get("repo_url") or row.get("status") == "done":
            _push_one(row)
            n += 1
    if n:
        logger.info("WebSync", f"↑ {n} lokale Webseite(n) in die Cloud gesynct")
    return {"ok": True, "pushed": n}


def _pull_loop() -> None:
    time.sleep(PULL_INTERVAL)
    while True:
        try:
            pull_into_db()
        except Exception as e:
            logger.error("WebSync", f"Pull-Loop-Fehler: {type(e).__name__}")
        time.sleep(PULL_INTERVAL)


def start() -> None:
    """Startet den periodischen Pull-Thread (idempotent). Nur wenn der Webseiten-Pull aktiviert
    ist (Standard AUS) — sonst zeigt jeder PC nur seine EIGENEN gebauten Seiten."""
    global _started
    if not _pull_enabled():
        logger.info("WebSync", "Webseiten-Cross-PC-Pull aus (Standard) — nur eigene Seiten werden "
                               "gezeigt. Aktivieren: JARVIS_SYNC_WEBSITES_PULL=1.")
        return
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_pull_loop, name="WebSync-Pull", daemon=True).start()
