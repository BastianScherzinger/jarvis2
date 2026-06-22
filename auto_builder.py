"""
auto_builder.py — Täglicher Auto-Website-Builder + Nightly-Improver.

Tagesrhythmus (läuft ab Start und ab 0 Uhr jeden Tag neu):
  Phase 1  Bauen   — bis zu JARVIS_DAILY_SITES (Default 10) neue Seiten für die
                     besten Leads OHNE Website: bauen → deployen → verbessern →
                     E-Mail an Bastian. Jede gebaute Seite wird in der Tages-
                     Historie (data/daily_builds.json) gespeichert.
  Phase 2  Verbessern — sind die 10 gebaut (oder keine Leads mehr offen), werden bis
                     zur Cutoff-Stunde (JARVIS_IMPROVE_UNTIL_HOUR, Default 10 = 10:00)
                     bestehende Seiten rundlaufend weiter verbessert (lokal auf der GPU).
  Phase 3  Pause   — danach Leerlauf bis Mitternacht; um 0 Uhr beginnt Phase 1 neu.

Stoppt nur auf manuellen Stop — NICHT mehr, wenn keine Leads übrig sind.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import date, datetime
from pathlib import Path

import logger

_BASTIAN = "bastian.scherzinger05@gmail.com"
_BASE     = Path(__file__).parent
_LOG_PATH = _BASE / "data" / "daily_builds.json"

_DAILY_LIMIT   = int(os.environ.get("JARVIS_DAILY_SITES", "10") or "10")
_IMPROVE_UNTIL = int(os.environ.get("JARVIS_IMPROVE_UNTIL_HOUR", "10") or "10")  # bis 10:00 verbessern

_state = {
    "running": False, "current": "", "phase": "", "done": 0, "failed": 0,
    "last": "", "started": 0.0, "day": "", "today_count": 0,
    "daily_limit": _DAILY_LIMIT, "improve_until_hour": _IMPROVE_UNTIL, "mode": "",
}
_lock = threading.Lock()


# ── Status / Steuerung ────────────────────────────────────────────────────────

def status() -> dict:
    with _lock:
        s = dict(_state)
    s["today_count"] = _count_today()
    return s


def is_running() -> bool:
    with _lock:
        return _state["running"]


def _set(**kw) -> None:
    with _lock:
        _state.update(kw)


def start() -> dict:
    with _lock:
        if _state["running"]:
            return {"ok": True, "already": True}
        _state.update({"running": True, "started": time.time(), "current": "",
                       "day": _today(), "phase": "Starte Tagesplan…", "mode": "build"})
    threading.Thread(target=_loop, name="AutoBuilder", daemon=True).start()
    logger.info("AutoBuilder", f"gestartet — {_DAILY_LIMIT} Seiten/Tag, Verbesserung bis {_IMPROVE_UNTIL}:00")
    return {"ok": True}


def stop() -> dict:
    _set(running=False, phase="gestoppt", current="", mode="")
    logger.info("AutoBuilder", "gestoppt")
    return {"ok": True}


# ── Tages-Historie (persistente Speicherung welche Seiten wann gebaut wurden) ──

def _today() -> str:
    return date.today().isoformat()


def _load_log() -> dict:
    try:
        return json.loads(_LOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_log(log: dict) -> None:
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _count_today() -> int:
    return len(_load_log().get(_today(), []))


def _record(entry: dict) -> None:
    """Speichert eine gebaute Seite in der Tages-Historie (data/daily_builds.json)."""
    log = _load_log()
    log.setdefault(_today(), []).append(entry)
    _save_log(log)
    _set(today_count=len(log[_today()]))


def daily_log(days: int = 14) -> dict:
    """Tages-Historie (neueste Tage zuerst, begrenzt) für die UI."""
    log = _load_log()
    tage = sorted(log.keys(), reverse=True)[:max(1, days)]
    return {"today": _today(), "daily_limit": _DAILY_LIMIT,
            "days": [{"date": t, "sites": log[t]} for t in tage]}


# ── Lead-Auswahl ──────────────────────────────────────────────────────────────

def _built_keys() -> set:
    try:
        import db_websites
        return {w.get("site_key") for w in db_websites.get_all() if w.get("site_key")}
    except Exception:
        return set()


def _pick_next_lead():
    """Bester Lead (Erwartungswert) OHNE Website und noch nicht gebaut."""
    import db_evaluated
    try:
        from leadkey import lead_key
    except Exception:
        lead_key = None
    built = _built_keys()
    for r in db_evaluated.get_all(limit=400, sort="erwartungswert"):
        if int(r.get("has_website") or 0):
            continue
        name = (r.get("name") or "").strip()
        if not name:
            continue
        sk = lead_key(name, r.get("stadt", "")) if lead_key else None
        if sk and sk in built:
            continue
        return r
    return None


def _pick_improve_target():
    """Bestehende, fertige Seite mit dem ältesten 'updated' (rundlaufend verbessern)."""
    try:
        import db_websites
        sites = [w for w in db_websites.get_all()
                 if (w.get("folder") and os.path.isdir(w["folder"])
                     and (w.get("status") == "done"))]
        if not sites:
            return None
        sites.sort(key=lambda w: w.get("updated") or 0)
        return sites[0]
    except Exception:
        return None


# ── Job-Warten + E-Mail ───────────────────────────────────────────────────────

def _wait_job(job_id: str, timeout: int = 1800):
    import website_builder
    end = time.time() + timeout
    while time.time() < end:
        if not is_running():
            return None
        job = website_builder.get(job_id)
        if not job:
            return None
        if job.get("status") in ("done", "error"):
            return job
        time.sleep(3)
    import website_builder as wb
    return wb.get(job_id)


def _email(name: str, link: str, branche: str, stadt: str, ansprechpartner: str = "") -> None:
    try:
        import mailer
        import offer_mail
        betreff, text, html = offer_mail.build(name, link, branche, stadt, ansprechpartner)
        mailer.send_email(_BASTIAN, betreff, text, html=html, bypass_redirect=True)
    except Exception as e:
        logger.warn("AutoBuilder", f"E-Mail fehlgeschlagen: {type(e).__name__}")


def _before_cutoff() -> bool:
    """True solange vor der Cutoff-Stunde (Verbesserungs-Fenster offen)."""
    return datetime.now().hour < _IMPROVE_UNTIL


def _idle_sleep(seconds: int = 60) -> None:
    """Schläft in kleinen Schritten, damit Stop sofort greift."""
    end = time.time() + seconds
    while time.time() < end and is_running():
        time.sleep(2)


# ── Hauptschleife ─────────────────────────────────────────────────────────────

def _build_and_email(lead: dict) -> None:
    import website_builder
    import db_websites
    name    = (lead.get("name") or "").strip()
    stadt   = lead.get("stadt", "")
    branche = lead.get("branche", "")
    _set(mode="build", current=name, phase=f"Baue Webseite ({_count_today()+1}/{_DAILY_LIMIT})…")
    logger.info("AutoBuilder", f"Baue Webseite für {name}")
    jid = website_builder.build(dict(lead))
    job = _wait_job(jid)
    if not is_running():
        return
    folder = (job or {}).get("folder", "")
    if folder:
        _set(phase="Top-verbessern…")
        ij  = website_builder.improve_existing(folder, name)
        job = _wait_job(ij) or job
    if not is_running():
        return
    link = (job or {}).get("live_url") or ""
    wrow = {}
    try:
        wrow = db_websites.get_by_job(jid) or {}
    except Exception:
        pass
    _set(phase="E-Mail an Bastian…")
    _email(name, link, branche, stadt, wrow.get("ansprechpartner", ""))
    _record({"name": name, "stadt": stadt, "branche": branche, "link": link,
             "email": wrow.get("kontakt_email", ""), "folder": folder,
             "ts": time.time()})
    with _lock:
        _state["done"] += 1
        _state["last"] = name
    logger.success("AutoBuilder", f"Fertig: {name} ({link or 'lokal'})")


def _improve_existing_once() -> bool:
    """Verbessert EINE bestehende Seite (Nightly-Improver). True wenn etwas getan."""
    import website_builder
    tgt = _pick_improve_target()
    if not tgt:
        return False
    name = tgt.get("name") or "Seite"
    _set(mode="improve", current=name, phase="Verbessere bestehende Seite (lokal)…")
    logger.info("AutoBuilder", f"Nightly-Improve: {name}")
    try:
        ij = website_builder.improve_existing(tgt["folder"], name)
        _wait_job(ij)
    except Exception as e:
        logger.warn("AutoBuilder", f"Improve fehlgeschlagen: {type(e).__name__}")
    return True


def _loop() -> None:
    while is_running():
        today = _today()
        with _lock:
            if _state["day"] != today:               # neuer Tag → Zähler/Phase zurück
                _state["day"] = today
                logger.info("AutoBuilder", f"Neuer Tag {today} — Tagesplan startet neu")

        # ── Phase 1: bis Tageslimit neue Seiten bauen ────────────────────────
        if _count_today() < _DAILY_LIMIT:
            lead = _pick_next_lead()
            if lead:
                try:
                    _build_and_email(lead)
                except Exception as e:
                    with _lock:
                        _state["failed"] += 1
                    logger.error("AutoBuilder", f"Bau-Fehler: {type(e).__name__}")
                    _idle_sleep(5)
                continue
            # keine offenen Leads → in die Verbesserungs-Phase fallen

        # ── Phase 2: bestehende Seiten verbessern bis Cutoff-Stunde ──────────
        if _before_cutoff():
            if _improve_existing_once():
                continue

        # ── Phase 3: Pause bis zum nächsten Tag/Fenster ──────────────────────
        _set(mode="idle",
             phase=f"Pause — heute {_count_today()}/{_DAILY_LIMIT} gebaut. Warte auf 0 Uhr…",
             current="")
        _idle_sleep(120)
