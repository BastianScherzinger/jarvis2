"""
custom_build.py — "Eigene Marke"-Modus: Sir gibt Name, Logo, Hero-Hintergrund und
Beschreibung selbst vor; gebaut wird mit derselben Engine (website_builder) wie der
Auto-Builder.

Zwei GETRENNTE, vom Nutzer gesteuerte Schritte (kein Auto-Pilot mehr):
  1. start(data)    → baut & deployt die Seite. KEIN Auto-Verbessern, KEIN Auto-Versand.
  2. improve(jid)   → fährt das 7-Stufen-Skill-Makeover (design-pro/taste/frontend-design)
                      über die gebaute Seite. Wiederholbar. Discord-Freigabe erst, wenn
                      alle Stufen durch sind (in website_builder._run_makeover).

Zusätzlich:
  suggest(data)     → KI-Vorschläge (Beschreibung, Branche, Tagline, Hero-Prompt, Leistungen)
                      für die Marke — lokal via Ollama, mit deterministischem Fallback.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import logger

_BASE        = Path(__file__).parent
_UPLOAD_BASE = _BASE / "workspace" / "custom_uploads"

_jobs: dict = {}                 # job_id → Custom-Job-Status (siehe start())
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


# ── KI-Vorschläge ─────────────────────────────────────────────────────────────

def _fallback_suggestion(name: str, branche: str, stadt: str) -> dict:
    """Deterministischer Vorschlag, wenn keine lokale KI erreichbar ist."""
    b = branche or "Ihr Fachbetrieb"
    ort = f" aus {stadt}" if stadt else ""
    return {
        "branche": branche or "Dienstleistung",
        "tagline": f"{name} — {b}{ort}, auf den Sie sich verlassen können.",
        "beschreibung": (
            f"{name} ist Ihr zuverlässiger Partner im Bereich {b}{ort}. "
            "Wir stehen für saubere, termingerechte Arbeit, faire Preise und persönliche "
            "Beratung auf Augenhöhe. Vom ersten Gespräch bis zur fertigen Umsetzung "
            "begleiten wir Sie mit Erfahrung, Sorgfalt und einem klaren Blick fürs Detail."
        ),
        "hero_prompt": (
            f"cinematic wide banner photo of a professional {branche or 'service business'}, "
            "bright natural daylight, modern and trustworthy, high detail, no text, no logo"
        ),
        "leistungen": ["Beratung", "Planung", "Umsetzung", "Service & Wartung"],
    }


def suggest(data: dict) -> dict:
    """KI-Vorschläge für die Marke. Nutzt das lokale Ollama-Modell (kostenlos, offline);
    bei Nichtverfügbarkeit greift ein deterministischer Fallback. Gibt {ok, suggestion}."""
    name    = (data.get("name") or "").strip()
    branche = (data.get("branche") or "").strip()
    stadt   = (data.get("stadt") or "").strip()
    notiz   = (data.get("beschreibung") or "").strip()
    if not name:
        return {"ok": False, "reason": "Name fehlt"}

    fb = _fallback_suggestion(name, branche, stadt)
    try:
        from scrapers._http import ask_ollama
        system = (
            "Du bist ein erfahrener Marketing-Texter für lokale Handwerks- und "
            "Dienstleistungsbetriebe. Antworte AUSSCHLIESSLICH mit einem JSON-Objekt, "
            "keine Erklärung. Sprache: Deutsch, Sie-Form, konkret, ohne Floskeln."
        )
        prompt = (
            f"Betrieb: {name}\n"
            f"Branche: {branche or '(unbekannt — leite sie aus dem Namen ab)'}\n"
            f"Stadt: {stadt or '(unbekannt)'}\n"
            f"Notizen von Sir: {notiz or '(keine)'}\n\n"
            "Erzeuge Vorschläge für die Webseite. JSON-Felder:\n"
            '{ "branche": "kurz", "tagline": "ein einprägsamer Slogan", '
            '"beschreibung": "3-4 Sätze Über-uns, verbindlich nutzbar", '
            '"hero_prompt": "englischer Bildprompt fürs Hero-Banner, no text", '
            '"leistungen": ["4-6 konkrete Leistungen"] }'
        )
        raw = ask_ollama(prompt, system, timeout=60) or ""
        parsed = None
        try:
            from website_improve import _extract_json
            parsed = _extract_json(raw)
        except Exception:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("beschreibung"):
            out = {
                "branche": (parsed.get("branche") or branche or fb["branche"]).strip(),
                "tagline": (parsed.get("tagline") or fb["tagline"]).strip(),
                "beschreibung": (parsed.get("beschreibung") or fb["beschreibung"]).strip(),
                "hero_prompt": (parsed.get("hero_prompt") or fb["hero_prompt"]).strip(),
                "leistungen": parsed.get("leistungen") or fb["leistungen"],
            }
            return {"ok": True, "suggestion": out, "source": "ollama"}
    except Exception as e:
        logger.warn("CustomBuild", f"KI-Vorschlag-Fallback: {type(e).__name__}")
    return {"ok": True, "suggestion": fb, "source": "fallback"}


# ── Schritt 1: Bauen ──────────────────────────────────────────────────────────

def start(data: dict) -> dict:
    """Startet einen Custom-Build (NUR bauen + deployen). data:
        name, branche, stadt, beschreibung, telefon, email, adresse,
        hero_prompt, logo_path, hero_path, recipients(list)
    Gibt {ok, job_id} zurück."""
    import website_builder
    lead, recipients = _build_lead(data)
    name = lead["name"]
    if not name:
        return {"ok": False, "reason": "Name fehlt"}
    jid = website_builder.build(lead)
    try:
        import overnight_makeover
        _stage_total = len(overnight_makeover.STAGES)
    except Exception:
        _stage_total = 2
    with _lock:
        _jobs[jid] = {
            "job_id": jid, "name": name, "phase": "Baue Webseite…",
            "recipients": recipients, "folder": "", "live_url": "",
            "built": False, "improving": False, "improve_job": "",
            "stages_done": 0, "stages_total": _stage_total, "done": False,
            "started": time.time(),
        }
    threading.Thread(target=_watch_build, args=(jid,),
                     name=f"custom-build-{jid}", daemon=True).start()
    logger.info("CustomBuild", f"Eigene-Marke-Build gestartet: {name}")
    return {"ok": True, "job_id": jid}


def _watch_build(job_id: str) -> None:
    """Wartet auf den Build und markiert ihn als fertig (bereit zum Verbessern)."""
    import website_builder
    job = _wait_job(job_id)
    folder = (job or {}).get("folder", "")
    live   = (job or {}).get("live_url", "")
    if (job or {}).get("status") == "error":
        _set(job_id, phase="Bau fehlgeschlagen — siehe Webseiten-Reiter.", done=True)
        return
    _set(job_id, folder=folder, live_url=live, built=True, done=True,
         stages_done=_stages_done(folder),
         phase="Fertig — bereit zum Verbessern" if folder else "Fertig (lokal)")
    logger.success("CustomBuild", f"Custom-Build gebaut: {job_id} ({live or 'lokal'})")
    # Im Tagesplan erfassen → zählt zum 3×5-Session-Rhythmus + erscheint im Mittags-Report.
    try:
        import auto_builder
        import db_websites
        cj  = _jobs.get(job_id) or {}
        row = db_websites.get_by_job(job_id) or {}
        auto_builder.record_custom(
            cj.get("name", ""), row.get("stadt", ""), row.get("branche", ""),
            live, row.get("kontakt_email", ""), folder)
    except Exception as e:
        logger.warn("CustomBuild", f"Tagesplan-Eintrag übersprungen: {type(e).__name__}")


# ── Schritt 2: Verbessern (Skill-Makeover, wiederholbar) ──────────────────────

def improve(job_id: str) -> dict:
    """Startet das 7-Stufen-Skill-Makeover für die bereits gebaute Seite. Wiederholbar.
    Gibt {ok, improve_job} zurück."""
    import website_builder
    with _lock:
        cj = dict(_jobs.get(job_id) or {})
    folder = cj.get("folder", "")
    name   = cj.get("name", "")
    if not folder or not Path(folder).is_dir():
        return {"ok": False, "reason": "Keine gebaute Seite gefunden — erst bauen, Sir."}
    if cj.get("improving"):
        return {"ok": False, "reason": "Verbesserung läuft bereits."}
    # Vom Nutzer eingegebene Empfänger in content.json sichern, damit die Discord-Freigabe
    # am Ende des Makeovers (finalize_review) sie wiederfindet — sonst gingen sie verloren.
    recipients = cj.get("recipients") or []
    if recipients:
        try:
            cj_path = Path(folder) / "content.json"
            content = json.loads(cj_path.read_text(encoding="utf-8"))
            content["custom_recipients"] = recipients
            cj_path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    ij = website_builder.makeover_existing(folder, name)
    _set(job_id, improving=True, improve_job=ij, done=False,
         phase="Skill-Makeover läuft…")
    threading.Thread(target=_watch_improve, args=(job_id, ij, folder),
                     name=f"custom-improve-{ij}", daemon=True).start()
    logger.info("CustomBuild", f"Custom-Makeover gestartet: {name} ({folder})")
    return {"ok": True, "improve_job": ij}


def _watch_improve(job_id: str, improve_job: str, folder: str) -> None:
    """Wartet auf den Makeover-Lauf und schreibt den Endzustand zurück."""
    import website_builder
    job = _wait_job(improve_job, timeout=int(os.environ.get("JARVIS_MAKEOVER_WAIT", "36000")))
    final = (job or {}).get("step", "") or "Verbesserung abgeschlossen."
    live  = (job or {}).get("live_url", "")
    _set(job_id, improving=False, done=True,
         live_url=live or _jobs.get(job_id, {}).get("live_url", ""),
         stages_done=_stages_done(folder), phase=final)
    logger.success("CustomBuild", f"Custom-Makeover fertig: {job_id} ({final[:60]})")


# ── Status & Helfer ─────────────────────────────────────────────────────────

def status(job_id: str) -> dict:
    """Kombinierter Status: Fortschritt des aktiven (Bau- ODER Verbesserungs-)Jobs +
    Custom-Phase. Während des Makeovers wird der Verbesserungs-Job verfolgt."""
    import website_builder
    with _lock:
        cj = dict(_jobs.get(job_id) or {})
    active = cj.get("improve_job") if cj.get("improving") else job_id
    job = website_builder.get(active) or {}
    return {
        "build": {"status": job.get("status", ""), "progress": job.get("progress", 0),
                  "step": job.get("step", ""), "live_url": job.get("live_url", "")},
        "custom": cj,
    }


def _stages_done(folder: str) -> int:
    try:
        import overnight_makeover
        return max(0, len(overnight_makeover.STAGES) - overnight_makeover.open_stages(folder))
    except Exception:
        return 0


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
    return website_builder.get(job_id)
