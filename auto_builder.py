"""
auto_builder.py — Auto-Website-Builder.

Hintergrund-Schleife: sucht den besten Lead OHNE Webseite (höchster Erwartungswert,
noch nicht gebaut), baut + deployt eine Seite, verbessert sie (Top-verbessern) und
schickt jedes Mal eine E-Mail an Bastian. Läuft, bis er gestoppt wird oder keine
offenen Leads mehr da sind.
"""
from __future__ import annotations

import threading
import time

import logger

_BASTIAN = "bastian.scherzinger05@gmail.com"

_state = {"running": False, "current": "", "phase": "", "done": 0, "failed": 0,
          "last": "", "started": 0.0}
_lock = threading.Lock()


def status() -> dict:
    with _lock:
        return dict(_state)


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
                       "phase": "Suche besten Lead…"})
    threading.Thread(target=_loop, name="AutoBuilder", daemon=True).start()
    logger.info("AutoBuilder", "gestartet")
    return {"ok": True}


def stop() -> dict:
    _set(running=False, phase="gestoppt", current="")
    logger.info("AutoBuilder", "gestoppt")
    return {"ok": True}


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


def _wait_job(job_id: str, timeout: int = 900):
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
    return website_builder.get(job_id)


def _email(name: str, link: str, branche: str, stadt: str, ansprechpartner: str = "") -> None:
    try:
        import mailer
        import offer_mail
        betreff, text, html = offer_mail.build(name, link, branche, stadt, ansprechpartner)
        mailer.send_email(_BASTIAN, betreff, text, html=html, bypass_redirect=True)
    except Exception as e:
        logger.warn("AutoBuilder", f"E-Mail fehlgeschlagen: {type(e).__name__}")


def _loop() -> None:
    import website_builder
    while is_running():
        lead = _pick_next_lead()
        if not lead:
            _set(phase="Keine offenen Leads mehr — fertig.", current="", running=False)
            logger.success("AutoBuilder", "Alle offenen Leads abgearbeitet")
            return
        name = (lead.get("name") or "").strip()
        stadt = lead.get("stadt", "")
        branche = lead.get("branche", "")
        _set(current=name, phase="Baue Webseite…")
        logger.info("AutoBuilder", f"Baue Webseite für {name}")
        try:
            jid = website_builder.build(dict(lead))
            job = _wait_job(jid)
            if not is_running():
                return
            folder = (job or {}).get("folder", "")
            # Jedes Mal verbessern (Top-verbessern)
            if folder:
                _set(phase="Top-verbessern…")
                ij = website_builder.improve_existing(folder, name)
                job = _wait_job(ij) or job
            if not is_running():
                return
            # Nur der echte Live-Link taugt als Webseiten-CTA (kein Repo-Link).
            link = (job or {}).get("live_url") or ""
            ap = ""
            try:
                import db_websites
                wrow = db_websites.get_by_job(jid) or {}
                ap = wrow.get("ansprechpartner") or ""
            except Exception:
                pass
            _set(phase="E-Mail an Bastian…")
            _email(name, link, branche, stadt, ap)
            with _lock:
                _state["done"] += 1
                _state["last"] = name
            logger.success("AutoBuilder", f"Fertig: {name} ({link or 'lokal'})")
        except Exception as e:
            with _lock:
                _state["failed"] += 1
            logger.error("AutoBuilder", f"Fehler bei {name}: {type(e).__name__}")
        time.sleep(2)
