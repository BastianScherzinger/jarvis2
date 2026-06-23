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
# Die Cutoff-Stunde ist ein Konzept für den unbeaufsichtigten Dauerbetrieb. Ein
# MANUELLER Start soll sofort arbeiten — sonst „passiert nichts", wenn Sir den
# Builder tagsüber startet. Mit JARVIS_IMPROVE_RESPECT_CUTOFF=1 gilt wieder die
# alte Logik (Verbessern nur vor der Cutoff-Stunde).
_RESPECT_CUTOFF = (os.environ.get("JARVIS_IMPROVE_RESPECT_CUTOFF", "0").strip().lower()
                   in ("1", "true", "yes", "ja"))
# Ein volles 7-Stufen-Makeover (Headless Claude Code) dauert lange — bis zu ~15 Min je
# Stufe. Großzügiges Warte-Limit, damit der Night-Builder eine Seite KOMPLETT fertigstellt,
# bevor er die nächste beginnt (keine parallele Claude-/Deploy-Last).
_MAKEOVER_WAIT = int(os.environ.get("JARVIS_MAKEOVER_WAIT", "9000") or "9000")
# Tiefen-Modus für den Nightly-Improver: off | local (Claude plant, Ollama baut) |
# claude (Claude Code headless baut echte Code-Features).
_NIGHTLY_DEEP  = os.environ.get("JARVIS_NIGHTLY_DEEP", "off").strip().lower()

_state = {
    "running": False, "current": "", "phase": "", "done": 0, "failed": 0,
    "last": "", "started": 0.0, "day": "", "today_count": 0,
    "daily_limit": _DAILY_LIMIT, "improve_until_hour": _IMPROVE_UNTIL, "mode": "",
    "nightly_deep": _NIGHTLY_DEEP, "last_feature": "",
}
_lock = threading.Lock()

# Ordner, bei denen in dieser Session kein Makeover-Fortschritt erzielt wurde.
# Wird täglich um Mitternacht zurückgesetzt. Verhindert Endlosschleifen wenn
# z.B. die claude-CLI fehlt oder alle Stufen schon erledigt sind.
_makeover_stuck: set = set()

# Persistenter An/Aus-Schalter — überlebt einen Programm-Neustart. Steht hier "running":
# true, nimmt der Night-Builder beim nächsten App-Start automatisch wieder auf (genau da
# weiter, denn der Pro-Seite-Fortschritt liegt in content.json["makeover_stages"]).
_STATE_PATH = _BASE / "data" / "overnight_state.json"


def _persist_running(running: bool) -> None:
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(
            json.dumps({"running": bool(running), "ts": time.time()}, ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        pass


def _persisted_running() -> bool:
    try:
        return bool(json.loads(_STATE_PATH.read_text(encoding="utf-8")).get("running"))
    except Exception:
        return False


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


def start(_resume: bool = False) -> dict:
    with _lock:
        if _state["running"]:
            return {"ok": True, "already": True}
        _state.update({"running": True, "started": time.time(), "current": "",
                       "day": _today(),
                       "phase": "Setze fort…" if _resume else "Starte Tagesplan…",
                       "mode": "build"})
    _persist_running(True)
    threading.Thread(target=_loop, name="AutoBuilder", daemon=True).start()
    logger.info("AutoBuilder",
                ("fortgesetzt" if _resume else "gestartet")
                + f" — {_DAILY_LIMIT} Seiten/Tag, Makeover 7 Stufen/Seite")
    return {"ok": True}


def stop() -> dict:
    """Stoppt den Night-Builder. Wirkt zwischen den Makeover-Stufen (eine laufende Stufe
    läuft noch zu Ende bzw. bis Timeout). Der Aus-Zustand wird persistiert — beim nächsten
    App-Start bleibt der Builder aus, bis er erneut gestartet wird."""
    _set(running=False, phase="gestoppt", current="", mode="")
    _persist_running(False)
    logger.info("AutoBuilder", "gestoppt — Fortschritt gesichert, jederzeit fortsetzbar")
    return {"ok": True}


def resume_if_needed() -> bool:
    """Beim App-Start aufrufen: war der Night-Builder beim letzten Mal an, läuft er
    automatisch wieder an (genau da weiter — Pro-Seite-Stufen liegen in content.json)."""
    if _persisted_running() and not is_running():
        logger.info("AutoBuilder", "Vorheriger Lauf war aktiv → automatische Fortsetzung")
        start(_resume=True)
        return True
    return False


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
    """Bester Lead (Erwartungswert) OHNE Website, noch nicht gebaut, nicht archiviert."""
    import db_evaluated
    import duplicate_guard
    try:
        from leadkey import lead_key
    except Exception:
        lead_key = None
    built = _built_keys()
    for r in db_evaluated.get_all(limit=400, sort="erwartungswert"):
        # Leads mit vorhandener Website oder bereits archivierten überspringen
        if int(r.get("has_website") or 0):
            continue
        if r.get("lead_typ") == "Archiviert":
            continue
        if int(r.get("erwartungswert_euro") or 0) == 0:
            continue
        name = (r.get("name") or "").strip()
        if not name:
            continue
        sk = lead_key(name, r.get("stadt", "")) if lead_key else None
        if sk and sk in built:
            continue
        # Schnelle lokale Duplikat-Prüfung (kein API-Call, nur DB + Ordner)
        already, _ = duplicate_guard.is_already_built(r, check_apis=False)
        if already:
            continue
        return r
    return None


def _pick_improve_target():
    """Bestehende, fertige Seite mit den MEISTEN offenen Makeover-Stufen zuerst
    (danach älteste 'updated'). Seiten, die alle 7 Stufen durch haben, werden
    übersprungen. Seiten, bei denen in dieser Session kein Fortschritt möglich war
    (_makeover_stuck), werden bis zum nächsten Tag ausgelassen."""
    try:
        import db_websites
        import overnight_makeover
        sites = [w for w in db_websites.get_all()
                 if (w.get("folder") and os.path.isdir(w["folder"])
                     and (w.get("status") == "done")
                     and w["folder"] not in _makeover_stuck)]
        if not sites:
            return None

        def _open(w):
            try:
                return overnight_makeover.open_stages(w["folder"])
            except Exception:
                return 0

        sites.sort(key=lambda w: (-_open(w), w.get("updated") or 0))
        top = sites[0]
        if _open(top) == 0:          # alle Seiten komplett makeovert → nichts zu tun
            return None
        return top
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


def _improve_gate() -> bool:
    """Darf die Verbesserungs-Phase jetzt laufen? Standardmäßig immer (ein manueller
    Start soll sofort arbeiten); nur mit JARVIS_IMPROVE_RESPECT_CUTOFF=1 greift die
    Cutoff-Stunde."""
    return (not _RESPECT_CUTOFF) or _before_cutoff()


def _idle_sleep(seconds: int = 60) -> None:
    """Schläft in kleinen Schritten, damit Stop sofort greift."""
    end = time.time() + seconds
    while time.time() < end and is_running():
        time.sleep(2)


# ── Hauptschleife ─────────────────────────────────────────────────────────────

def _build_and_email(lead: dict) -> None:
    import website_builder
    import db_websites
    import duplicate_guard
    _t0     = time.time()
    name    = (lead.get("name") or "").strip()
    stadt   = lead.get("stadt", "")
    branche = lead.get("branche", "")

    # Vollständige Duplikat-Prüfung inkl. GitHub + Railway (einmalig vor dem Bau)
    already, reason = duplicate_guard.is_already_built(lead, check_apis=True)
    if already:
        logger.warn("AutoBuilder",
                    f"Lead '{name}' übersprungen — bereits verarbeitet: {reason}")
        duplicate_guard.mark_archived(lead, reason)
        return

    _set(mode="build", current=name, phase=f"Baue Webseite ({_count_today()+1}/{_DAILY_LIMIT})…")
    logger.info("AutoBuilder", f"Baue Webseite für {name}")
    jid = website_builder.build(dict(lead))
    job = _wait_job(jid)
    if not is_running():
        return
    folder = (job or {}).get("folder", "")
    # Mehrstufiges Skill-Makeover (7 Stufen, Commit je Stufe, Deploy am Ende). Die
    # Discord-Freigabe (1× 👍 = Mail / 1× 👎 = verwerfen) bzw. die Vorschau-Mail an
    # Bastian erfolgt am Ende INNERHALB der Makeover-Pipeline (finalize_review).
    if folder:
        _set(phase="Makeover (7 Skill-Stufen)…")
        mj  = website_builder.makeover_existing(folder, name, stop=lambda: not is_running())
        job = _wait_job(mj, timeout=_MAKEOVER_WAIT) or job
    if not is_running():
        return
    link = (job or {}).get("live_url") or ""
    wrow = {}
    try:
        wrow = db_websites.get_by_job(jid) or {}
    except Exception:
        pass
    email_addr = wrow.get("kontakt_email", "")
    _record({"name": name, "stadt": stadt, "branche": branche, "link": link,
             "email": email_addr, "folder": folder,
             "review": True, "ts": time.time()})
    with _lock:
        _state["done"] += 1
        _state["last"] = name
    logger.success("AutoBuilder", f"Fertig: {name} ({link or 'lokal'})")
    try:
        logger.activity("AutoBuilder", "Webseite gebaut",
                        f"{name} · {branche} · {stadt}{' · ' + link if link else ''}",
                        "🌐", "build")
        import cost_tracker as _ct
        _ct.track_compute(time.time() - _t0, False, "website_build", name)
    except Exception:
        pass


def _deep_claude(folder: str, branche: str) -> dict:
    """Tiefen-Feature über Claude Code (Variante A): nächstes Backlog-Feature bauen,
    markieren, Changelog. Render-Gate/Rollback macht claude_coder selbst."""
    import json as _json
    import feature_backlog
    import claude_coder
    import local_coder
    cj = Path(folder) / "content.json"
    content = {}
    try:
        if cj.is_file():
            content = _json.loads(cj.read_text(encoding="utf-8"))
    except Exception:
        pass
    feat = feature_backlog.next_feature(branche, content)
    if not feat:
        return {"ok": False, "reason": "keine offenen Features"}
    res = claude_coder.run_feature(folder, feat["spec"], branche)
    if not res.get("ok"):
        return {"ok": False, "feature": feat["label"], "reason": res.get("reason", "Bau fehlgeschlagen")}
    try:
        content = _json.loads(cj.read_text(encoding="utf-8"))
        feature_backlog.mark_done(content, feat["key"])
        cj.write_text(_json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    local_coder._append_changelog(Path(folder), feat["label"], res.get("summary", ""))
    return {"ok": True, "feature": feat["label"], "summary": res.get("summary", "")}


def _deep_step(folder: str, branche: str, name: str) -> dict:
    """Führt EINEN Tiefen-Feature-Schritt im konfigurierten Modus aus."""
    if _NIGHTLY_DEEP == "local":
        import local_coder
        return local_coder.build_feature(folder, branche, name)
    if _NIGHTLY_DEEP == "mcp":
        import mcp_bridge
        if mcp_bridge.available():
            return mcp_bridge.build_feature(folder, branche, name)
        import local_coder                            # Fallback, falls ollama-Lib fehlt
        return local_coder.build_feature(folder, branche, name)
    if _NIGHTLY_DEEP == "claude":
        return _deep_claude(folder, branche)
    return {"ok": False, "reason": "off"}


def _improve_existing_once() -> bool:
    """Holt bei EINER bestehenden Seite die offenen Makeover-Stufen nach (Resume).
    Ist die Seite danach komplett (alle 7 Stufen durch), postet die Makeover-Pipeline
    sie automatisch zur Discord-Freigabe. True, wenn eine Seite mit offenen Stufen
    bearbeitet wurde; False, wenn alle Seiten bereits fertig makeovert sind.

    Kein Fortschritt nach dem Lauf (gleiche Anzahl offener Stufen) → Seite wird in
    _makeover_stuck eingetragen und heute nicht mehr angefasst (verhindert Endlosschleife
    z.B. wenn die claude-CLI fehlt oder ein Render fehlschlug)."""
    import website_builder
    import overnight_makeover
    tgt = _pick_improve_target()
    if not tgt:
        return False
    name   = tgt.get("name") or "Seite"
    folder = tgt["folder"]

    open_before = 0
    try:
        open_before = overnight_makeover.open_stages(folder)
    except Exception:
        pass

    _set(mode="improve", current=name,
         phase=f"Makeover ({7 - open_before + 1}/7)… {name}")
    logger.info("AutoBuilder", f"Makeover: {name} ({open_before} Stufen offen)")
    try:
        mj = website_builder.makeover_existing(folder, name, stop=lambda: not is_running())
        _wait_job(mj, timeout=_MAKEOVER_WAIT)
    except Exception as e:
        logger.warn("AutoBuilder", f"Makeover fehlgeschlagen: {type(e).__name__}")
        _makeover_stuck.add(folder)
        return True

    # Fortschritts-Check: hat der Lauf mindestens eine Stufe erledigt?
    try:
        open_after = overnight_makeover.open_stages(folder)
        if open_after >= open_before:
            # Keine Verbesserung — heute nicht mehr versuchen
            logger.warn("AutoBuilder",
                        f"Kein Makeover-Fortschritt für '{name}' — überspringe heute")
            _makeover_stuck.add(folder)
        else:
            logger.success("AutoBuilder",
                           f"Makeover: {name} — {open_before - open_after} Stufe(n) erledigt, "
                           f"{open_after} offen")
    except Exception:
        pass

    return True


def _loop() -> None:
    while is_running():
        today = _today()
        with _lock:
            if _state["day"] != today:               # neuer Tag → Zähler/Phase zurück
                _state["day"] = today
                _makeover_stuck.clear()              # täglich zurücksetzen
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

        # ── Phase 2: bestehende Seiten verbessern (manueller Start: jederzeit) ─
        if _improve_gate():
            if _improve_existing_once():
                continue

        # ── Phase 3: Pause bis zum nächsten Tag/Fenster ──────────────────────
        _set(mode="idle",
             phase=f"Pause — heute {_count_today()}/{_DAILY_LIMIT} gebaut. Warte auf 0 Uhr…",
             current="")
        _idle_sleep(120)
