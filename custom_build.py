"""
custom_build.py — "Eigene Marke"-Modus: Sir gibt Name, Logo, Hero-Hintergrund und
Beschreibung selbst vor; gebaut wird mit derselben Engine (website_builder) wie der
Auto-Builder, danach über Nacht verbessert, und nach Discord-Freigabe an 11+ Empfänger
geschickt.

Ablauf:
  start(data) → Uploads sichern → website_builder.build(lead mit _custom) →
  Watcher-Thread: warten → improve_existing → discord_bot.submit_for_review(recipients)
  (oder Fallback: Vorschau-Mail an Bastian, wenn der Bot nicht läuft).
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from pathlib import Path

import logger

_BASE        = Path(__file__).parent
_UPLOAD_BASE = _BASE / "workspace" / "custom_uploads"


def _fallback_email() -> str:
    """Fallback-Empfänger für Vorschau-Mails wenn der Discord-Bot nicht läuft.
    Über CUSTOM_BUILD_FALLBACK_EMAIL in .env überschreibbar."""
    return os.environ.get("CUSTOM_BUILD_FALLBACK_EMAIL", "bastian.scherzinger05@gmail.com")

_jobs: dict = {}                 # job_id → {phase, name, recipients, review_id, ...}
_lock = threading.Lock()


def _slugify(text: str) -> str:
    text = (text or "").lower().strip()
    for a, b in {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "&": "und"}.items():
        text = text.replace(a, b)
    out = "".join(c if (c.isascii() and c.isalnum()) else "-" for c in text)
    return ("-".join(p for p in out.split("-") if p) or "marke")[:40]


def save_upload(file_storage, kind: str, slug: str) -> str:
    """Speichert ein hochgeladenes Bild (Werkzeug-FileStorage) und gibt den Pfad zurück."""
    if not file_storage or not getattr(file_storage, "filename", ""):
        return ""
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        ext = ".png"
    d = _UPLOAD_BASE / slug
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{kind}{ext}"
    try:
        file_storage.save(str(path))
        return str(path)
    except Exception:
        return ""


def _build_lead(data: dict) -> "tuple[dict, list]":
    """Baut aus den Formulardaten das Lead-Dict (mit _custom) + die Empfängerliste.
    Reine Funktion (testbar, keine Seiteneffekte)."""
    recipients = [e.strip() for e in (data.get("recipients") or []) if e and "@" in e]
    lead = {
        "name": (data.get("name") or "").strip(),
        "branche": (data.get("branche") or "").strip(),
        "stadt": (data.get("stadt") or "").strip(),
        "beschreibung": (data.get("beschreibung") or "").strip(),
        "telefon": (data.get("telefon") or "").strip(),
        "email": (data.get("email") or "").strip(),
        "adresse": (data.get("adresse") or "").strip(),
        "_custom": {
            "logo_path": (data.get("logo_path") or "").strip(),
            "hero_path": (data.get("hero_path") or "").strip(),
            "hero_prompt": (data.get("hero_prompt") or "").strip(),
        },
    }
    return lead, recipients


def start(data: dict) -> dict:
    """Startet einen Custom-Build. data:
        name, branche, stadt, beschreibung, telefon, email, adresse,
        hero_prompt, logo_path, hero_path, recipients(list)
    Gibt {ok, job_id} zurück."""
    import website_builder
    lead, recipients = _build_lead(data)
    name = lead["name"]
    if not name:
        return {"ok": False, "reason": "Name fehlt"}
    jid = website_builder.build(lead)
    with _lock:
        _jobs[jid] = {"job_id": jid, "name": name, "phase": "Baue Webseite…",
                      "recipients": recipients, "review_id": "", "done": False,
                      "started": time.time()}
    threading.Thread(target=_watch, args=(jid, lead, recipients),
                     name=f"custom-{jid}", daemon=True).start()
    logger.info("CustomBuild", f"Eigene-Marke-Build gestartet: {name} ({len(recipients)} Empfänger)")
    return {"ok": True, "job_id": jid}


def status(job_id: str) -> dict:
    """Kombinierter Status: Bau-Fortschritt (website_builder) + Custom-Phase."""
    import website_builder
    job = website_builder.get(job_id) or {}
    with _lock:
        cj = dict(_jobs.get(job_id) or {})
    return {"build": {"status": job.get("status", ""), "progress": job.get("progress", 0),
                      "step": job.get("step", ""), "live_url": job.get("live_url", "")},
            "custom": cj}


def _set(job_id: str, **kw) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(kw)


def _wait_job(job_id: str, timeout: int = 1800):
    import website_builder
    end = time.time() + timeout
    while time.time() < end:
        job = website_builder.get(job_id)
        if not job:
            return None
        if job.get("status") in ("done", "error"):
            return job
        time.sleep(3)
    import website_builder as wb
    return wb.get(job_id)


def _watch(job_id: str, lead: dict, recipients: list) -> None:
    """Wartet auf den Build, verbessert, postet zur Discord-Freigabe (oder mailt Vorschau)."""
    import website_builder
    import db_websites
    name    = lead.get("name", "")
    branche = lead.get("branche", "")
    stadt   = lead.get("stadt", "")

    job = _wait_job(job_id)
    folder = (job or {}).get("folder", "")
    if folder:
        _set(job_id, phase="Top-verbessern (7-Pass + Render-Gate)…")
        ij = website_builder.improve_existing(folder, name)
        job = _wait_job(ij) or job
    link = (job or {}).get("live_url") or ""

    wrow = {}
    try:
        wrow = db_websites.get_by_job(job_id) or {}
    except Exception:
        pass
    email_addr = (lead.get("email") or wrow.get("kontakt_email", "")).strip()
    ap = wrow.get("ansprechpartner", "")

    posted = False
    try:
        import discord_bot
        if discord_bot.enabled():
            _set(job_id, phase="Zur Discord-Freigabe gepostet…")
            posted = bool(discord_bot.submit_for_review(
                name, stadt, branche, link, email_addr, ap, folder, recipients))
    except Exception as e:
        logger.warn("CustomBuild", f"Discord-Review fehlgeschlagen: {type(e).__name__}")

    if not posted:
        # Fallback: Vorschau-Mail an Bastian (kein echter Kundenversand ohne Bot-Freigabe).
        _set(job_id, phase="Vorschau an Bastian (Bot nicht aktiv)…")
        try:
            import mailer
            import offer_mail
            betreff, text, html = offer_mail.build(name, link, branche, stadt, ap)
            mailer.send_email(_fallback_email(), betreff, text, html=html, bypass_redirect=True)
        except Exception:
            pass

    _set(job_id, phase="Fertig — wartet auf Freigabe" if posted else "Fertig (Vorschau gesendet)",
         done=True, link=link, review=posted)
    logger.success("CustomBuild", f"Custom-Build fertig: {name} ({link or 'lokal'})")
