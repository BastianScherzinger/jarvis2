"""
auto_builder.py — Täglicher Auto-Website-Builder + Nightly-Improver.

Tagesrhythmus (läuft ab Start und ab 0 Uhr jeden Tag neu):
  Phase 1  Bauen   — bis zu JARVIS_DAILY_SITES (Default 5) neue Seiten für die
                     besten Leads OHNE Website: bauen → deployen → verbessern →
                     E-Mail an Bastian. Jede gebaute Seite wird in der Tages-
                     Historie (data/daily_builds.json) gespeichert.
  Phase 2  Verbessern — sind die 5 gebaut (oder keine Leads mehr offen), werden bis
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

_DAILY_LIMIT   = int(os.environ.get("JARVIS_DAILY_SITES", "5") or "5")

# Paid-Boost: erkennt cost_tracker bezahlte Extra-Tokens (API-Kosten heute > 0 ODER mehrere
# ANTHROPIC-Keys → headless-Läufe über API-Key), verdoppelt sich das Tageslimit — wer pro
# Token zahlt, hängt nicht am Abo-Session-Limit. Abschaltbar mit JARVIS_PAID_BOOST=0.
_boost_logged = [False]


def _daily_limit() -> int:
    """Effektives Tageslimit je Session: _DAILY_LIMIT, ×2 im Paid-Boost-Modus."""
    try:
        import cost_tracker as _ct
        if _ct.paid_boost_active():
            if not _boost_logged[0]:
                _boost_logged[0] = True
                info = _ct.paid_tokens_detected()
                logger.info("AutoBuilder",
                            f"💳 Paid-Boost aktiv ({info.get('reason', '?')}) — "
                            f"Tageslimit verdoppelt: {_DAILY_LIMIT} → {_DAILY_LIMIT * 2}")
            return _DAILY_LIMIT * 2
    except Exception:
        pass
    return _DAILY_LIMIT
_IMPROVE_UNTIL = int(os.environ.get("JARVIS_IMPROVE_UNTIL_HOUR", "10") or "10")  # bis 10:00 verbessern
# N× täglich bauen (Default 3 Sessions × _DAILY_LIMIT = 15 Seiten/Tag). Jede Session hat ihr
# eigenes Tageslimit; nach Ablauf des Session-Fensters startet die nächste Runde mit frischen 5.
# So entstehen 10–20 Seiten/Tag (untere Grenze bei Limit-Erschöpfung). Fenster über
# JARVIS_SESSION_HOURS (z.B. "0,12,18"); sonst gleichmäßig über den Tag verteilt.
_SESSIONS_PER_DAY = max(1, int(os.environ.get("JARVIS_SESSIONS_PER_DAY", "3") or "3"))
_PM_START      = int(os.environ.get("JARVIS_PM_START", "12") or "12")  # Legacy (2-Session-Kompat)
# Lokale-KI-Parallelität (für Hochskalieren): wie viele lokale Sub-Tasks gleichzeitig laufen
# dürfen. 0 = automatisch aus der Hardware ableiten (siehe scaling_info()).
_LOCAL_CONCURRENCY = int(os.environ.get("JARVIS_LOCAL_CONCURRENCY", "0") or "0")
# Die Cutoff-Stunde ist ein Konzept für den unbeaufsichtigten Dauerbetrieb. Ein
# MANUELLER Start soll sofort arbeiten — sonst „passiert nichts", wenn Sir den
# Builder tagsüber startet. Mit JARVIS_IMPROVE_RESPECT_CUTOFF=1 gilt wieder die
# alte Logik (Verbessern nur vor der Cutoff-Stunde).
_RESPECT_CUTOFF = (os.environ.get("JARVIS_IMPROVE_RESPECT_CUTOFF", "0").strip().lower()
                   in ("1", "true", "yes", "ja"))
# Ein volles 7-Stufen-Makeover (Headless Claude Code) dauert lange — bis zu ~15 Min je
# Stufe. Bei Claude-Session-Limit wartet das Makeover zudem bis zu 7× 1 h und versucht erneut
# (overnight_makeover._LIMIT_RETRIES/_LIMIT_WAIT). Das Warte-Limit muss das abdecken, sonst
# zieht der Builder weiter, während das Makeover im Hintergrund noch wartet. Default 10 h.
_MAKEOVER_WAIT = int(os.environ.get("JARVIS_MAKEOVER_WAIT", "36000") or "36000")
# Tiefen-Modus für den Nightly-Improver: off | local (Claude plant, Ollama baut) |
# claude (Claude Code headless baut echte Code-Features).
_NIGHTLY_DEEP  = os.environ.get("JARVIS_NIGHTLY_DEEP", "off").strip().lower()

_state = {
    "running": False, "current": "", "phase": "", "done": 0, "failed": 0,
    "last": "", "started": 0.0, "day": "", "session": "", "today_count": 0,
    "daily_limit": _DAILY_LIMIT, "improve_until_hour": _IMPROVE_UNTIL, "mode": "",
    "nightly_deep": _NIGHTLY_DEEP, "last_feature": "",
}
_lock = threading.Lock()

# Ordner, bei denen in dieser Session kein Makeover-Fortschritt erzielt wurde.
# Wird täglich um Mitternacht zurückgesetzt. Verhindert Endlosschleifen wenn
# z.B. die claude-CLI fehlt oder alle Stufen schon erledigt sind.
_makeover_stuck: set = set()

# Rettungs-Versuche je Ordner (Seite war unterbrochen/nicht live). Ein Railway-Build kann ein
# paar Minuten brauchen → wir geben einer Rettung mehrere Runden, bevor sie als „stuck" gilt.
_rescue_tries: dict = {}
_RESCUE_MAX = int(os.environ.get("JARVIS_RESCUE_MAX_TRIES", "4") or "4")

# Latch für die Discord-Verabschiedung: einmal posten, wenn ALLE Seiten auf 7/7 sind.
# Wird zurückgesetzt, sobald wieder eine Seite offene Stufen hat (neue Seite gebaut o.ä.).
_farewell_sent: bool = False

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
    s["daily_limit"] = _daily_limit()          # effektiv (Paid-Boost: ×2)
    s["paid_boost"]  = s["daily_limit"] > _DAILY_LIMIT
    return s


def is_running() -> bool:
    with _lock:
        return _state["running"]


def _set(**kw) -> None:
    with _lock:
        _state.update(kw)


def start(_resume: bool = False) -> dict:
    global _farewell_sent, _claude_limited
    _farewell_sent = False
    _claude_limited = False
    with _lock:
        if _state["running"]:
            return {"ok": True, "already": True}
        _state.update({"running": True, "started": time.time(), "current": "",
                       "day": _today(),
                       "phase": "Setze fort…" if _resume else "Starte Tagesplan…",
                       "mode": "build"})
    _persist_running(True)
    threading.Thread(target=_loop, name="AutoBuilder", daemon=True).start()
    try:
        import overnight_makeover as _om
        _nstages = len(_om.STAGES)
    except Exception:
        _nstages = 3
    logger.info("AutoBuilder",
                ("fortgesetzt" if _resume else "gestartet")
                + f" — {_SESSIONS_PER_DAY}×{_daily_limit()} = {_SESSIONS_PER_DAY * _daily_limit()} "
                + f"Seiten/Tag (Sessions {_session_hours()}), Makeover {_nstages} Stufen/Seite, "
                + f"lokale Parallelität {local_concurrency()}")
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
    """Beim App-Start aufrufen: veraltete Demos abbauen (7-Tage-Regel) + Night-Builder
    fortsetzen wenn er beim letzten Mal lief."""
    try:
        teardown_stale_demos()
    except Exception as e:
        logger.warn("AutoBuilder", f"Startup-Teardown: {type(e).__name__}")
    if _persisted_running() and not is_running():
        logger.info("AutoBuilder", "Vorheriger Lauf war aktiv → automatische Fortsetzung")
        start(_resume=True)
        return True
    return False


# ── Tages-Historie (persistente Speicherung welche Seiten wann gebaut wurden) ──

def _today() -> str:
    return date.today().isoformat()


def _session_hours() -> list:
    """Startstunden der Bau-Sessions (aufsteigend). Aus JARVIS_SESSION_HOURS (z.B. '0,12,18')
    oder — wenn leer — gleichmäßig über 24 h verteilt aus _SESSIONS_PER_DAY abgeleitet.
    Bei genau 2 Sessions gilt der Legacy-Mittagsstart _PM_START (0 und _PM_START)."""
    raw = os.environ.get("JARVIS_SESSION_HOURS", "").strip()
    if raw:
        hrs = sorted({max(0, min(23, int(x))) for x in raw.split(",")
                      if x.strip().lstrip("-").isdigit()})
        if hrs:
            return hrs
    n = _SESSIONS_PER_DAY
    if n <= 1:
        return [0]
    if n == 2:
        return [0, max(1, min(23, _PM_START))]
    return [int(i * 24 / n) for i in range(n)]


def _session_index() -> int:
    """Index (0-basiert) der aktuell laufenden Session anhand der Tagesstunde."""
    h = datetime.now().hour
    idx = 0
    for i, start in enumerate(_session_hours()):
        if h >= start:
            idx = i
    return idx


def _session() -> str:
    """Aktuelle Bau-Session: '{datum}_s{n}' (n = 1-basiert). Wird statt _today() für die
    Bau-Zählung genutzt — nach jedem Session-Fenster startet eine frische Runde (Limit 5)."""
    return f"{_today()}_s{_session_index() + 1}"


def _keys_for_date(log: dict, date_str: str) -> list:
    """Alle Log-Schlüssel, die zu einem Datum gehören — inkl. neuer '_s{n}'- und alter
    '_am'/'_pm'-Suffixe sowie des ungesuffixten Legacy-Keys."""
    return [k for k in log if k == date_str or k.startswith(date_str + "_")]


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
    """Aktive Seiten in der AKTUELLEN Bau-Session (am/pm). Nicht gelöscht, nicht archiviert.
    Zählt per Session, damit nach _PM_START eine zweite Runde mit frischem Limit startet.
    WICHTIG: NICHT nach Ordner-Existenz zählen (archivierter Ordner liegt noch auf der
    Platte → würde sonst mitgezählt → Builder dächte „fertig" und baut nichts)."""
    entries = _load_log().get(_session(), [])
    if not entries:
        return 0
    # Aktive (nicht-archivierte) Ordner aus der Webseiten-DB — NUR diese zählen als „vorhanden".
    active_folders: set = set()
    try:
        import db_websites
        for w in db_websites.get_all():            # include_archived=False (Standard) → nur aktive
            f = (w.get("folder") or "").strip()
            if f and not w.get("archived"):
                try:
                    active_folders.add(os.path.normcase(os.path.abspath(f)))
                except Exception:
                    active_folders.add(f)
    except Exception:
        pass
    n = 0
    for e in entries:
        f = (e.get("folder") or "").strip()
        if not f:
            continue                               # ohne Ordner nicht zählbar (keine aktive Zeile)
        try:
            norm = os.path.normcase(os.path.abspath(f))
        except Exception:
            norm = f
        if norm in active_folders:                 # nur AKTIVE (nicht archivierte) Seiten zählen
            n += 1
    return n


def _record(entry: dict) -> None:
    """Speichert eine gebaute Seite in der Session-Historie (data/daily_builds.json)."""
    log = _load_log()
    sess = _session()
    log.setdefault(sess, []).append(entry)
    _save_log(log)
    _set(today_count=len(log[sess]))


def record_custom(name: str, stadt: str = "", branche: str = "", link: str = "",
                  email: str = "", folder: str = "") -> None:
    """Trägt eine im 'Eigene-Marke'-Modus gebaute Seite in die Tages-Historie ein —
    so zählt sie zum Session-Kontingent und taucht im Mittags-Report auf (Sirs Vorgabe:
    Custom-Seiten laufen im selben 3×5-Tagesrhythmus mit). Idempotent je Ordner/Session."""
    if not (name or "").strip():
        return
    try:
        sess = _session()
        for e in _load_log().get(sess, []):
            same_folder = folder and (e.get("folder") or "").strip() == folder.strip()
            same_name   = (e.get("name") or "").strip().lower() == name.strip().lower()
            if same_folder or same_name:
                return                                # schon erfasst → nicht doppelt zählen
        _record({"name": name.strip(), "stadt": stadt, "branche": branche, "link": link,
                 "email": email, "folder": folder, "source": "custom",
                 "review": True, "ts": time.time()})
        logger.info("AutoBuilder", f"Eigene-Marke-Seite in Tagesplan erfasst: {name}")
    except Exception as e:
        logger.warn("AutoBuilder", f"record_custom übersprungen: {type(e).__name__}")


def scaling_info() -> dict:
    """Hardware-basierte Skalierungs-Empfehlung für den Dauerbetrieb (Hochskalieren).
    Liest das System-Profil und schlägt Sessions/Seiten + lokale Parallelität vor.
    Die aktiven Werte stammen weiter aus den Env-Knöpfen — das hier ist die Empfehlung."""
    ram = 8.0
    tier = "LAPTOP"
    try:
        import system_profile
        prof = system_profile.analyze()
        ram  = float(prof.get("ram_gb") or 8.0)
        tier = prof.get("tier", "LAPTOP")
    except Exception:
        pass
    # Empfehlung skaliert mit dem RAM (= Indikator für lokale KI-Kapazität).
    if ram >= 64:
        rec_sites, rec_sessions, rec_conc = 10, 4, 6
    elif ram >= 32:
        rec_sites, rec_sessions, rec_conc = 8, 3, 4
    elif ram >= 16:
        rec_sites, rec_sessions, rec_conc = 5, 3, 2
    else:
        rec_sites, rec_sessions, rec_conc = 5, 3, 1
    conc = _LOCAL_CONCURRENCY or rec_conc
    return {
        "tier": tier, "ram_gb": round(ram, 1),
        "active": {"daily_sites": _daily_limit(), "sessions_per_day": _SESSIONS_PER_DAY,
                   "session_hours": _session_hours(), "local_concurrency": conc},
        "recommended": {"daily_sites": rec_sites, "sessions_per_day": rec_sessions,
                        "local_concurrency": rec_conc},
        "max_per_day_active": _daily_limit() * _SESSIONS_PER_DAY,
    }


def local_concurrency() -> int:
    """Effektive lokale-KI-Parallelität: Env-Wert, sonst aus der Hardware abgeleitet."""
    if _LOCAL_CONCURRENCY > 0:
        return _LOCAL_CONCURRENCY
    try:
        return int(scaling_info()["recommended"]["local_concurrency"])
    except Exception:
        return 1


def daily_log(days: int = 14) -> dict:
    """Tages-Historie (neueste Tage zuerst, begrenzt) für die UI.
    Session-Schlüssel (_am/_pm) werden nach echtem Datum gruppiert."""
    log = _load_log()
    from collections import defaultdict
    grouped: dict = defaultdict(list)
    for k, entries in log.items():
        # Session-Suffix ('_s1'/'_am'/'_pm') abschneiden → echtes Datum als Gruppenkey.
        # Das Datum selbst enthält nur '-', also trennt der erste '_' Datum von Suffix.
        date_k = k.split("_", 1)[0]
        grouped[date_k].extend(entries)
    tage = sorted(grouped.keys(), reverse=True)[:max(1, days)]
    return {"today": _today(), "daily_limit": _daily_limit(),
            "sessions_per_day": _SESSIONS_PER_DAY, "session_hours": _session_hours(),
            "pm_start_hour": _PM_START,
            "days": [{"date": t, "sites": grouped[t]} for t in tage]}


# ── Lead-Auswahl ──────────────────────────────────────────────────────────────

def _built_keys() -> set:
    """Alle jemals gebauten Site-Keys (inkl. archivierte) — verhindert Doppelbau."""
    try:
        import db_websites
        return {w.get("site_key") for w in db_websites.get_all(include_archived=True)
                if w.get("site_key")}
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


# Night-Build verbessert standardmäßig NUR die heute gebauten Seiten (Sirs Vorgabe).
# Mit JARVIS_IMPROVE_TODAY_ONLY=0 werden wie früher auch ältere Seiten weiter verbessert.
_IMPROVE_TODAY_ONLY = (os.environ.get("JARVIS_IMPROVE_TODAY_ONLY", "1").strip().lower()
                       not in ("0", "false", "no", "nein"))


def _today_folders() -> set:
    """Ordner-Pfade ALLER heute gebauten Seiten (beide Sessions am+pm, normalisiert).
    Der Improver soll Seiten aus beiden Sessions nachziehen — nicht nur der aktuellen."""
    out: set = set()
    log = _load_log()
    today = _today()
    for key in _keys_for_date(log, today):
        for e in log.get(key, []):
            f = (e.get("folder") or "").strip()
            if f:
                try:
                    out.add(os.path.normcase(os.path.abspath(f)))
                except Exception:
                    out.add(f)
    return out


def _is_today_folder(folder: str) -> bool:
    """True, wenn der Ordner zu einer heute gebauten Seite gehört (oder Filter aus)."""
    if not _IMPROVE_TODAY_ONLY:
        return True
    try:
        return os.path.normcase(os.path.abspath(folder)) in _today_folders()
    except Exception:
        return folder in _today_folders()


def is_improve_eligible(folder: str) -> bool:
    """Öffentlicher Wrapper um `_is_today_folder` — für die Dashboard-Anzeige. Eine Seite,
    die der Night-Builder (Sirs Vorgabe: nur heutige Seiten) nie wieder anfasst, soll dort
    nicht als 'hängengeblieben' erscheinen, wenn sie längst live ist."""
    return _is_today_folder(folder)


def _needs_rescue(w: dict) -> bool:
    """True, wenn eine Seite NICHT sauber fertig+live ist und „weiterarbeiten" braucht:
    unterbrochener/fehlerhafter Bau (status != done) ODER kein erreichbarer Live-Link.
    Solche Seiten werden im Night-Builder ZUERST nachgezogen (deploy + restliche Stufen)."""
    if (w.get("status") or "") != "done":
        return True
    if not (w.get("live_url") or "").strip() or not int(w.get("live") or 0):
        return True
    return False


def _pick_improve_target():
    """Nächste HEUTE gebaute Seite, die Arbeit braucht. Reihenfolge:
      1) UNTERBROCHENE / nicht-live Seiten ZUERST (status != done oder kein Live-Link) —
         die werden gerettet (restliche Stufen + Deploy), sonst bleiben sie ewig „Unterbrochen".
      2) Danach fertige Seiten mit den MEISTEN offenen Makeover-Stufen; bei Gleichstand die
         NEUESTE ('updated' absteigend).
    `_makeover_stuck` (kein Fortschritt heute) wird ausgelassen. Gibt None, wenn alle Seiten
    fertig UND live UND komplett makeovert sind."""
    try:
        import db_websites
        import overnight_makeover
        sites = [w for w in db_websites.get_all()      # include_archived=False (Standard)
                 if (w.get("folder") and os.path.isdir(w["folder"])
                     and not w.get("archived")
                     and w["folder"] not in _makeover_stuck
                     and _is_today_folder(w["folder"]))]
        if not sites:
            return None

        def _open(w):
            try:
                return overnight_makeover.open_stages(w["folder"])
            except Exception:
                return 0

        # Eine Seite ist „erledigt", wenn sie fertig+live ist UND keine offenen Stufen hat.
        offen = [w for w in sites if _needs_rescue(w) or _open(w) > 0]
        if not offen:
            return None
        # Rettung zuerst (rescue=1 vor 0), dann meiste offene Stufen, dann neueste.
        offen.sort(key=lambda w: (0 if _needs_rescue(w) else 1, -_open(w), -(w.get("updated") or 0)))
        return offen[0]
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


def _already_reviewed(name: str) -> bool:
    """True wenn für diese Seite bereits ein offener (pending/approved) Discord-Review
    existiert — verhindert Doppel-Posts nach build+makeover."""
    try:
        import review_queue as _rq
        return any(r.get("name", "").lower().strip() == name.lower().strip()
                   and r.get("status") in ("pending", "approved")
                   for r in _rq.all(limit=100))
    except Exception:
        return False


def _makeover_sites() -> list:
    """Die Arbeitsmenge des Night-Builders: HEUTE gebaute, nicht-archivierte Seiten mit lokalem
    Ordner — UNABHÄNGIG vom Status, damit auch unterbrochene (status != done) Seiten mitzählen
    und nachgezogen werden (sonst gälten sie fälschlich als „nicht da" → Verabschiedung zu früh)."""
    try:
        import db_websites
        return [w for w in db_websites.get_all()
                if (w.get("folder") and os.path.isdir(w["folder"])
                    and not w.get("archived")
                    and _is_today_folder(w["folder"]))]
    except Exception:
        return []


# ── Claude-/ChatGPT-Erschöpfung: Fallback + Auto-Neustart ──────────────────────
# Ist das Claude-Code-Limit leer, nutzt der Builder „ein bisschen ChatGPT" (OpenAI-Hero-
# Bilder = echter Fortschritt ohne Claude). Sind BEIDE leer, schaltet er ab und startet
# nach _EXHAUST_WAIT automatisch neu (teste & starte neu).
_EXHAUST_WAIT  = int(os.environ.get("JARVIS_EXHAUST_WAIT", "3600") or "3600")
_restart_timer = None
_claude_limited = False


# Phrasen, die auf einen VORÜBERGEHENDEN Netz-/API-Fehler hindeuten (Internet weg, DNS,
# Timeout, 502/503/504, Verbindungsabbruch) — KEIN echtes Nutzungslimit. Bei diesen bleibt
# der Night-Builder dran (kurzes Warten + weiter), statt sich stundenlang zu pausieren.
_TRANSIENT = (
    "connection", "connect ", "connectionerror", "timed out", "timeout", "temporarily",
    "getaddrinfo", "name resolution", "name or service", "max retries", "remote disconnected",
    "reset by peer", "unreachable", "no route", "broken pipe", "eof occurred",
    "502", "503", "504", "bad gateway", "service unavailable", "gateway time",
    "internet", "network is", "ssl", "handshake", "apiconnection", "newconnectionerror",
)


def _is_transient(text: str) -> bool:
    t = (text or "").lower()
    return any(s in t for s in _TRANSIENT)


def _internet_ok() -> bool:
    """Kurzer TCP-Check, ob das Internet (bzw. die Anthropic-API) erreichbar ist."""
    import socket
    for host in ("api.anthropic.com", "1.1.1.1", "8.8.8.8"):
        try:
            s = socket.create_connection((host, 443), timeout=4)
            s.close()
            return True
        except Exception:
            continue
    return False


def _wait_online(max_wait: int = 900) -> None:
    """Wartet (mit kurzem Backoff) bis das Internet wieder da ist — aber höchstens max_wait s
    und nur solange der Builder läuft. So bleibt der Night-Builder nach einem Internet-/API-
    Ausfall dran, statt abzubrechen oder sich lange zu pausieren."""
    if _internet_ok():
        return
    waited, step = 0, 15
    _set(phase="Internet-/API-Störung — warte auf Verbindung, bleibe dran…")
    while is_running() and waited < max_wait:
        time.sleep(step)
        waited += step
        if _internet_ok():
            logger.info("AutoBuilder", f"Verbindung nach {waited}s wieder da — Night-Builder macht weiter.")
            return
        step = min(60, step + 10)
    logger.warn("AutoBuilder", "Verbindung weiterhin gestört — nächster Versuch im regulären Takt.")


def _note_job_limit(job) -> bool:
    """Hat der Makeover-Job ein ECHTES Claude-Nutzungslimit gemeldet? Setzt das Flag.
    Vorübergehende Netz-/API-Fehler (Internet weg, Timeout, 5xx) zählen NICHT als Limit —
    sonst würde sich der Builder bei einem kurzen Aussetzer stundenlang pausieren."""
    global _claude_limited
    if not job:
        return False
    txt = (str(job.get("step", "")) + " " + str(job.get("error", ""))).lower()
    if _is_transient(txt):
        return False                              # nur ein Aussetzer → kein Limit, dranbleiben
    hit = "session_limit" in txt
    if not hit:
        try:
            import overnight_makeover as om
            hit = om._looks_limited(txt)
        except Exception:
            pass
    if hit:
        _claude_limited = True
    return hit


def _cloud_hero_can_help() -> bool:
    """Kann die Cloud-Hero-Engine (Higgsfield-Default, sonst OpenAI) gerade Bilder liefern?"""
    try:
        import media_engine
        if media_engine.higgsfield_available():
            return True
        return media_engine.openai_available() and media_engine.openai_quota_left() > 0
    except Exception:
        return False


def _cloud_hero_progress() -> bool:
    """Claude-Limit aktiv → echter Fortschritt OHNE Claude: erneuert bei EINER Seite ohne
    Cloud-Hero das Hero-Bild über die konfigurierte Engine (Default Higgsfield = Abo).
    True, wenn etwas getan wurde."""
    if not _cloud_hero_can_help():
        return False
    try:
        import overnight_makeover as om
        for w in _makeover_sites():
            folder = Path(w["folder"])
            if om._read_content(folder).get("hero_source") in (
                    "higgsfield", "higgsfield_mcp", "openai"):
                continue                          # schon ein Cloud-Hero (inkl. Abo-MCP) → Budget schonen
            meta = {"name": w.get("name", ""), "branche": w.get("branche", ""),
                    "stadt": w.get("stadt", ""), "email": w.get("kontakt_email", ""),
                    "ansprechpartner": w.get("ansprechpartner", "")}
            _set(mode="improve", current=w.get("name", ""),
                 phase=f"Claude-Limit → Hero erneuern: {w.get('name','')}")
            if om._ensure_hero(folder, meta, lambda p, t: _set(phase=t)):
                logger.info("AutoBuilder", f"Claude-Limit → Hero erneuert: {w.get('name','')}")
                return True
        return False
    except Exception as e:
        logger.warn("AutoBuilder", f"Cloud-Hero-Fallback fehlgeschlagen: {type(e).__name__}")
        return False


def _schedule_restart(seconds: int) -> None:
    """Beide Limits leer → nach `seconds` automatisch erneut testen & starten."""
    global _restart_timer
    with _lock:                                   # Doppel-Timer/Doppel-Loop verhindern
        if _restart_timer is not None:
            return

        def _restart():
            global _restart_timer
            _restart_timer = None
            logger.success("AutoBuilder", f"Reset-Zeit erreicht ({time.strftime('%H:%M')}) — "
                                          "teste Claude erneut & setze Night-Builder fort.")
            start(_resume=True)

        _restart_timer = threading.Timer(seconds, _restart)
        _restart_timer.daemon = True
        _restart_timer.start()
    _target = time.strftime("%H:%M", time.localtime(time.time() + seconds))
    logger.warn("AutoBuilder", f"Claude- UND ChatGPT-Limit erschöpft — Builder pausiert bis "
                               f"{_target} Uhr ({seconds // 60} Min), dann automatischer Neustart.")


def _handle_exhaustion() -> None:
    """Claude-Limit erkannt: erst ein bisschen ChatGPT; sind beide leer → stop + Neustart-Timer.
    Der Neustart folgt dem gelernten Retry-Plan: 4 h Pause nach dem Limit, danach stündlich."""
    global _claude_limited
    _claude_limited = False
    if _cloud_hero_progress():
        return                      # Cloud-Hero (Higgsfield/OpenAI) half → normaler Loop weiter
    stop()
    # Wiederaufnahme nach dem gelernten Plan (claude_limit: 4 h, dann stündlich) statt fix 1 h.
    wait = _EXHAUST_WAIT
    try:
        import claude_limit
        s = claude_limit.seconds_to_retry()
        if s > 0:
            wait = s
    except Exception:
        pass
    _schedule_restart(wait)


def _all_sites_complete() -> bool:
    """True, wenn es ≥1 heute gebaute Seite gibt und JEDE fertig+live ist UND alle Makeover-
    Stufen durch hat. Unterbrochene/nicht-live Seiten halten es False → der Builder arbeitet
    weiter und verabschiedet sich nicht zu früh."""
    try:
        import overnight_makeover
        sites = _makeover_sites()
        if not sites:
            return False
        return all((not _needs_rescue(w)) and overnight_makeover.open_stages(w["folder"]) == 0
                   for w in sites)
    except Exception:
        return False


def _today_links() -> list:
    """Alle heute gebauten Seiten mit Live-Link (dedupliziert nach Name, neueste zuerst) —
    für die Abschluss-Übersicht mit klickbaren Links zum Bewerten.
    Liest aus allen Session-Keys des heutigen Tages (am/pm + ungesuffixten Legacy-Key)."""
    out: list = []
    seen: set = set()
    log   = _load_log()
    today = _today()
    # Alle Session-Schlüssel für heute zusammenführen (s1..sN + Legacy am/pm)
    entries: list = []
    for key in _keys_for_date(log, today):
        entries.extend(log.get(key, []))
    for e in reversed(entries):
        name = (e.get("name") or "").strip()
        link = (e.get("link") or "").strip()
        if not name or not link or not link.startswith("http"):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "link": link, "branche": e.get("branche", ""),
                    "stadt": e.get("stadt", "")})
    return out


def _farewell_if_done() -> None:
    """Sind alle Seiten auf 7/7, postet JARVIS EINMAL eine Abschlussnachricht in Discord
    (Verabschiedung) — inklusive aller HEUTE gebauten Seiten als klickbare Links zum
    Bewerten. Der Latch wird zurückgesetzt, sobald wieder Arbeit anfällt."""
    global _farewell_sent
    if not _all_sites_complete():
        _farewell_sent = False           # wieder offene Stufen → Latch lösen
        return
    if _farewell_sent:
        return
    sites = _makeover_sites()
    n     = len(sites)
    live  = sum(1 for w in sites if w.get("live"))

    head = (f"Alle **{n} Webseiten** sind durch alle 7 Skill-Stufen makeovert — alle auf "
            f"demselben Niveau, **{live} live**, deployt und als erledigt markiert.")

    # Ehrlich: makeovert ≠ verschickt. Offene Freigaben (warten auf 👍) klar ausweisen,
    # damit keine widersprüchliche „gebaut & verschickt, aber eine wartet"-Meldung entsteht.
    try:
        import review_queue as _rq
        st = _rq.stats()
        pend, sent_n = int(st.get("pending", 0)), int(st.get("sent", 0))
        appr = int(st.get("approved", 0))
        status_line = []
        if sent_n:
            status_line.append(f"📨 {sent_n} bereits an Kunden verschickt")
        try:
            import discord_bot as _db
            auto = _db.auto_send()
            hour = _db._send_hour()
        except Exception:
            auto, hour = False, 12
        if auto:
            # Auto-Send: nichts wartet auf 👍 — freigegebene Seiten gehen automatisch raus.
            if appr:
                status_line.append(f"⚙️ {appr} gehen um {hour}:00 automatisch an die Kunden")
        elif pend:
            status_line.append(f"🕓 {pend} warten noch auf deine Freigabe (👍)")
        if status_line:
            head += "\n" + " · ".join(status_line) + "."
    except Exception:
        pass

    # Alle heutigen Seiten als klickbare Links zum Bewerten auflisten.
    links = _today_links()
    if links:
        lines = ["", "**Heutige Webseiten — zum Bewerten:**"]
        for i, s in enumerate(links, 1):
            extra = " · ".join(x for x in (s.get("branche"), s.get("stadt")) if x)
            line = f"{i}. [{s['name']}]({s['link']})" + (f" — {extra}" if extra else "")
            # Discord-Embed-Beschreibung max ~4096 Zeichen — sicher unter Limit bleiben.
            if sum(len(x) + 1 for x in lines) + len(line) > 3800:
                lines.append(f"… und {len(links) - i + 1} weitere.")
                break
            lines.append(line)
        body = "\n".join(lines)
    else:
        body = ""

    msg = f"{head}\n{body}\n\nJARVIS verabschiedet sich für heute, Sir. 🫡".strip()

    posted = False
    try:
        import discord_bot
        posted = discord_bot.notify(
            f"✅ Makeover komplett — {n} Seiten fertig", msg, 0x2ecc71)
    except Exception as e:
        logger.warn("AutoBuilder", f"Verabschiedung fehlgeschlagen: {type(e).__name__}")
    _farewell_sent = True               # auch ohne Discord nur einmal versuchen/loggen
    logger.success("AutoBuilder",
                   f"Alle {n} Seiten auf 7/7 — Verabschiedung "
                   f"{'in Discord gepostet' if posted else 'lokal protokolliert'} "
                   f"({len(links)} Links)")


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

    _set(mode="build", current=name, phase=f"Baue Webseite ({_count_today()+1}/{_daily_limit()})…")
    logger.info("AutoBuilder", f"Baue Webseite für {name}")
    # deploy=False: erst lokal komplett bauen, der Makeover deployt am Ende EINMAL (verifiziert)
    # → nur ein Railway-Build, keine 404-Phasen durch mehrfaches Deployen.
    jid = website_builder.build(dict(lead), deploy=False)
    job = _wait_job(jid)
    if not is_running():
        return
    folder = (job or {}).get("folder", "")
    # Mehrstufiges Skill-Makeover (7 Stufen, Commit je Stufe, Deploy am Ende). Die
    # Discord-Freigabe (1× 👍 = Mail / 1× 👎 = verwerfen) bzw. die Vorschau-Mail an
    # Bastian erfolgt am Ende INNERHALB der Makeover-Pipeline (finalize_review).
    if folder:
        _set(phase="Makeover (7 Skill-Stufen)…")
        mj   = website_builder.makeover_existing(folder, name, stop=lambda: not is_running())
        mjob = _wait_job(mj, timeout=_MAKEOVER_WAIT)
        _note_job_limit(mjob)
        job  = mjob or job
    if not is_running():
        return
    link = (job or {}).get("live_url") or ""
    wrow = {}
    try:
        wrow = db_websites.get_by_job(jid) or {}
    except Exception:
        pass
    email_addr    = wrow.get("kontakt_email", "")
    ansprechpart  = wrow.get("ansprechpartner", "")
    # E-Mail schon JETZT (beim Bau) aktiv suchen, nicht erst beim Versand — so steht die
    # Kundenadresse früh fest und erscheint in Discord/Report. Best-effort, blockiert kurz.
    if "@" not in (email_addr or ""):
        try:
            import contact_finder
            cf = contact_finder.find(name, stadt, branche, link)
            if cf.get("email"):
                email_addr   = cf["email"]
                ansprechpart = ansprechpart or cf.get("ansprechpartner", "")
                try:
                    db_websites.update(jid, kontakt_email=email_addr,
                                       ansprechpartner=ansprechpart or "")
                except Exception:
                    pass
                logger.info("AutoBuilder",
                            f"Kontakt für {name} gefunden ({cf.get('quelle','?')}): {email_addr}")
        except Exception as _ce:
            logger.warn("AutoBuilder", f"Kontaktsuche übersprungen: {type(_ce).__name__}")
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

    # Discord-Freigabe (= Angebots-Mail nach 👍), sobald die Seite review-ready ist: alle
    # PFLICHT-Stufen durch (die optionale Claude-Politur darf das NICHT blockieren) + erreichbarer
    # Live-Link. (_run_makeover postet selbst; diese Sicherung greift, falls er es nicht tat —
    # finalize_review hat Gate + Latch, also kein Doppelpost.)
    try:
        import overnight_makeover as _om
        fertig = bool(folder) and _om.review_ready(folder)
    except Exception:
        fertig = False
    if link and fertig and not _already_reviewed(name):
        try:
            import overnight_makeover as _om
            _om.finalize_review(
                {"name": name, "stadt": stadt, "branche": branche,
                 "email": email_addr, "ansprechpartner": ansprechpart},
                link, folder or "")
        except Exception as _de:
            logger.warn("AutoBuilder", f"Discord-Freigabe: {type(_de).__name__}")
    elif link and not fertig:
        logger.info("AutoBuilder", f"'{name}' noch nicht fertig — keine Discord-Freigabe "
                                   "(kommt rein, sobald die Pflicht-Stufen durch sind).")


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
    # Läuft bereits ein Makeover (z.B. manuell gestartet), NICHT parallel anfangen — nur eine
    # Seite gleichzeitig. Kurz warten und diese Runde überspringen (NICHT als 'stuck' markieren).
    if website_builder.makeover_busy():
        logger.info("AutoBuilder", f"Makeover läuft bereits ('{website_builder.makeover_current()}') "
                                   f"— warte (immer nur eine Seite gleichzeitig).")
        _idle_sleep(5)
        return True
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
    rescue_before = _needs_rescue(tgt)            # war die Seite unterbrochen/nicht live?

    _set(mode="improve", current=name,
         phase=(f"Seite nachziehen (Deploy)… {name}" if rescue_before and open_before == 0
                else f"Makeover… {name}"))
    logger.info("AutoBuilder", f"{'Rettung+' if rescue_before else ''}Makeover: {name} "
                               f"({open_before} Stufen offen)")
    limited = False
    transient = False
    try:
        if rescue_before and open_before == 0:
            # Reine Deploy-Rettung: Seite ist fertig (0 offene Stufen), nur nicht live.
            # Direkt deployen statt die ganze Makeover-Pipeline für einen No-Op hochzufahren
            # (spart Claude/Ollama-Overhead und das „KOMPLETT 0.0s"-Log-Rauschen).
            mj = website_builder.deploy_existing(folder, name)
        else:
            mj = website_builder.makeover_existing(folder, name, stop=lambda: not is_running())
        mjob = _wait_job(mj, timeout=_MAKEOVER_WAIT)
        limited = _note_job_limit(mjob)
        job_txt = ((str((mjob or {}).get("step", "")) + " " + str((mjob or {}).get("error", "")))
                   if isinstance(mjob, dict) else str(mjob))
        transient = _is_transient(job_txt)
    except Exception as e:
        emsg = f"{type(e).__name__}: {e}"
        if _is_transient(emsg):
            # Internet-/API-Aussetzer: NICHT als „stuck" markieren — auf Verbindung warten und
            # nächste Runde dieselbe Seite erneut versuchen → der Builder bleibt dran.
            logger.warn("AutoBuilder", f"Makeover-Aussetzer ({type(e).__name__}) — bleibe dran.")
            _wait_online(600)
            return True
        logger.warn("AutoBuilder", f"Makeover fehlgeschlagen: {type(e).__name__}")
        _makeover_stuck.add(folder)
        return True

    # Fortschritts-Check: hat der Lauf mindestens eine Stufe erledigt ODER die Seite live gemacht?
    try:
        open_after = overnight_makeover.open_stages(folder)
        # Aktuellen Live-Status der Seite frisch lesen (die Rettung kann sie live gemacht haben).
        now_live = False
        try:
            import db_websites
            row = db_websites.get_by_folder(folder) or {}
            now_live = bool(int(row.get("live") or 0)) and bool((row.get("live_url") or "").strip())
        except Exception:
            now_live = False
        rescued = rescue_before and now_live      # war kaputt/nicht-live → jetzt live = Fortschritt

        if open_after < open_before or rescued:
            _rescue_tries.pop(folder, None)        # Erfolg → Versuchszähler zurücksetzen
            note = []
            if open_after < open_before:
                note.append(f"{open_before - open_after} Stufe(n) erledigt")
            if rescued:
                note.append("Seite ist jetzt live")
            logger.success("AutoBuilder", f"Makeover: {name} — {', '.join(note)}, {open_after} offen")
        elif rescue_before and open_before == 0:
            # Reine Deploy-Rettung (keine Stufen offen), Seite noch nicht erreichbar — meist baut
            # Railway noch. Ein paar Runden Geduld geben, erst dann aufgeben (nicht sofort „stuck").
            n = _rescue_tries.get(folder, 0) + 1
            _rescue_tries[folder] = n
            if transient:
                _wait_online(600)
            elif n >= _RESCUE_MAX:
                logger.warn("AutoBuilder", f"'{name}' nach {n} Deploy-Versuchen nicht erreichbar — "
                                           "überspringe heute (Railway-Build-Log prüfen).")
                _makeover_stuck.add(folder)
            else:
                logger.info("AutoBuilder", f"'{name}' noch nicht live (Deploy-Versuch {n}/{_RESCUE_MAX}) "
                                           "— Railway baut evtl. noch, nächste Runde erneut.")
                _idle_sleep(20)                    # kurz dem Build Zeit geben
        else:
            # Kein Fortschritt. Bei Claude-LIMIT oder transientem Netz-/API-Fehler NICHT als
            # „stuck" markieren — beides temporär; die Seite soll wieder dran kommen.
            if transient:
                logger.warn("AutoBuilder", f"Makeover-Aussetzer bei '{name}' — bleibe dran.")
                _wait_online(600)
            elif not limited:
                logger.warn("AutoBuilder",
                            f"Kein Fortschritt für '{name}' — überspringe heute")
                _makeover_stuck.add(folder)
    except Exception:
        pass

    return True


# ── Live-Watcher: Links ehrlich halten + kaputte Seiten selbst heilen ──────────
# Prüft regelmäßig, ob jede aktive Seite WIRKLICH antwortet (HTTP 200, kein 404), setzt das
# live-Flag in der DB ehrlich und deployt kaputte LOKALE Seiten automatisch neu. Läuft IMMER
# (auch wenn der Night-Builder aus/pausiert ist), damit „alle Links live" werden + bleiben.
_LIVE_WATCH_INTERVAL = int(os.environ.get("JARVIS_LIVE_WATCH_INTERVAL", "120") or "120")
_LIVE_REDEPLOY_COOLDOWN = int(os.environ.get("JARVIS_LIVE_REDEPLOY_COOLDOWN", "600") or "600")
# Nach so vielen erfolglosen Re-Deploys in Folge gilt eine Seite als dauerhaft kaputt
# (z.B. Railway-Build schlägt reproduzierbar fehl). Dann NICHT weiter alle 10 Min hämmern,
# sondern auf einen langen Backoff gehen — spart Railway-Builds und Log-Rauschen.
_LIVE_MAX_FAILS = int(os.environ.get("JARVIS_LIVE_MAX_FAILS", "3") or "3")
_LIVE_GIVEUP_COOLDOWN = int(os.environ.get("JARVIS_LIVE_GIVEUP_COOLDOWN", "14400") or "14400")  # 4 h
# Mehrere Seiten gleichzeitig offline = Symptom eines vollen/blockierten Railway-Sammel-
# projekts (historische Ursache für „Seiten werden gebaut, gehen aber nie live"). Ab dieser
# Zahl gleichzeitig toter Seiten wird SOFORT ein neues Sammel-Projekt für kommende Deploys
# erzwungen (agent_railway.force_rotate), statt nur auf den Service-Zähler zu warten.
_LIVE_ROTATE_THRESHOLD = max(2, int(os.environ.get("JARVIS_LIVE_ROTATE_THRESHOLD", "3") or "3"))
_LIVE_ROTATE_COOLDOWN  = max(600, int(os.environ.get("JARVIS_LIVE_ROTATE_COOLDOWN", "21600") or "21600"))
_live_watch_started = False
_live_redeploy_at: dict = {}        # folder → letzter Re-Deploy-Zeitpunkt (Cooldown)
_live_fail_count: dict = {}         # folder → erfolglose Re-Deploys in Folge (Backoff-Zähler)
_live_last_forced_rotation = [0.0]  # Cooldown-Zeitstempel für die erzwungene Rotation
_live_gaveup: set = set()           # folder → „gebe vorerst auf" bereits geloggt (einmal pro Serie)
# Wie viele Seiten EIN _live_check_once()-Durchlauf höchstens nacheinander repariert (statt
# nur einer pro 120s-Zyklus — bei einem größeren Rückstand (z.B. nach einer fehlerhaften
# Rotation) dauerte das Abarbeiten sonst Stunden). Jede Seite wird sequenziell abgewartet
# (kein Gate-Gerangel), darum trotzdem ein Deckel gegen unbegrenzt lange Durchläufe.
_LIVE_REPAIR_BATCH = max(1, int(os.environ.get("JARVIS_LIVE_REPAIR_BATCH", "30") or "30"))


def start_live_watch() -> None:
    """Startet den Live-Watcher EINMAL (idempotent). Best-effort."""
    global _live_watch_started
    if _live_watch_started:
        return
    _live_watch_started = True
    threading.Thread(target=_live_watch_loop, name="LiveWatch", daemon=True).start()
    logger.info("LiveWatch", f"Link-Überwachung aktiv (alle {_LIVE_WATCH_INTERVAL}s · "
                             "kaputte lokale Seiten werden automatisch neu deployt).")


def _live_watch_loop() -> None:
    time.sleep(20)                  # App-Start abwarten
    while True:
        try:
            _live_check_once()
        except Exception as e:
            logger.warn("LiveWatch", f"Durchlauf-Fehler: {type(e).__name__}")
        time.sleep(max(30, _LIVE_WATCH_INTERVAL))


def _wait_repair_job(job_id: str, timeout: int = 600):
    """Wartet auf einen Live-Watch-Re-Deploy-Job, BEVOR die nächste Seite drankommt — sonst
    würde website_builder._run_deploy() nach nur 30s Warten auf den Makeover-Gate aufgeben
    ('verschoben'), sobald mehrere Re-Deploys kurz hintereinander ausgelöst werden. Bewusst
    UNABHÄNGIG von auto_builder.is_running(): der Live-Watcher läuft auch, wenn der
    Night-Builder gerade aus ist (siehe Modul-Docstring von start_live_watch())."""
    import website_builder
    end = time.time() + timeout
    while time.time() < end:
        job = website_builder.get(job_id)
        if not job or job.get("status") in ("done", "error"):
            return job
        time.sleep(3)
    return website_builder.get(job_id)


def _live_check_once() -> None:
    """Ein Durchlauf: jede aktive Seite mit Live-URL HTTP-prüfen, live-Flag ehrlich setzen,
    dann bis zu _LIVE_REPAIR_BATCH kaputte LOKALE Seiten (Ordner vorhanden) NACHEINANDER neu
    deployen — jede wird abgewartet, bevor die nächste startet (kein Gate-Timeout-Gerangel).
    Cross-PC-Seiten ohne lokalen Ordner werden nur ehrlich als offline markiert."""
    import db_websites
    import website_builder
    try:
        import discord_bot
        _is_live = discord_bot.link_is_live
    except Exception:
        _is_live = lambda u, timeout=8: False

    sites = db_websites.get_all()            # aktive (nicht archivierte)

    # Symptom-Check VOR dem Redeploy-Durchgang: nutzt den zuletzt bekannten 'live'-Stand
    # (dieser Loop hält ihn selbst aktuell) statt eines teuren Extra-HTTP-Durchgangs.
    down = sum(1 for w in sites if (w.get("live_url") or "").strip() and not w.get("live"))
    if down >= _LIVE_ROTATE_THRESHOLD:
        _maybe_force_rotation(down)

    to_repair: list[tuple[str, str]] = []    # [(folder, name)] — erst sammeln, dann seriell abarbeiten
    for w in sites:
        url    = (w.get("live_url") or "").strip()
        folder = (w.get("folder") or "").strip()
        has_local = bool(folder) and os.path.isdir(folder)
        job_id = w.get("job_id") or ""

        if url:
            live_now = bool(_is_live(url, timeout=8))
            # live-Flag nur bei Änderung schreiben (spart DB-Schreibzugriffe + Cloud-Sync).
            if int(w.get("live") or 0) != (1 if live_now else 0):
                if live_now:
                    txt = "Live erreichbar."
                elif has_local:
                    txt = "Link nicht erreichbar (404/Build) — wird neu deployt."
                else:
                    txt = "Nicht erreichbar (auf anderem PC gebaut — hier nicht steuerbar)."
                try:
                    db_websites.update(job_id, live=1 if live_now else 0, step=txt)
                    _sync_one(job_id)
                except Exception:
                    pass
                # Zustandswechsel an der Problemstelle klar loggen (nicht nur still in die DB).
                _nm = (w.get("name") or "Seite").strip()
                if live_now and folder in _live_fail_count:
                    logger.success("LiveWatch", f"'{_nm}' ist nach {_live_fail_count.get(folder, 0)} "
                                                "Re-Deploy(s) wieder live. ✓")
                elif not live_now:
                    logger.warn("LiveWatch", f"'{_nm}' offline geworden → "
                                             + ("Selbstheilung startet." if has_local
                                                else "auf anderem PC gebaut, hier nicht reparierbar."))
            if live_now:
                # Seite (wieder) gesund → Backoff-Zähler zurücksetzen, damit ein späterer
                # Ausfall wieder normal (nicht im langen Give-up-Cooldown) behandelt wird.
                _live_fail_count.pop(folder, None)
                _live_gaveup.discard(folder)
                continue                     # alles gut
        # Hier: Seite NICHT live (oder ohne URL).
        if not has_local:
            continue                         # Cross-PC-Seite ohne Ordner → hier nicht reparierbar
        # Cooldown je Ordner, damit nicht im Kreis neu deployt wird. Nach mehreren
        # erfolglosen Versuchen (Seite gilt als dauerhaft kaputt) auf langen Backoff gehen,
        # statt eine tote Seite endlos alle 10 Min neu zu deployen.
        fails = _live_fail_count.get(folder, 0)
        cooldown = _LIVE_GIVEUP_COOLDOWN if fails >= _LIVE_MAX_FAILS else _LIVE_REDEPLOY_COOLDOWN
        last = _live_redeploy_at.get(folder, 0)
        if time.time() - last < cooldown:
            continue
        name = (w.get("name") or "Seite").strip()
        if fails >= _LIVE_MAX_FAILS and folder not in _live_gaveup:
            _live_gaveup.add(folder)
            logger.warn("LiveWatch", f"'{name}' nach {fails} erfolglosen Re-Deploys weiterhin tot — "
                                     f"seltener Versuch (alle {_LIVE_GIVEUP_COOLDOWN // 3600} h). "
                                     "Railway-Build-Log prüfen.")
        to_repair.append((folder, name))
        if len(to_repair) >= _LIVE_REPAIR_BATCH:
            break

    if not to_repair:
        return
    if len(to_repair) > 1:
        logger.info("LiveWatch", f"{len(to_repair)} Seite(n) nicht erreichbar — arbeite sie "
                                 "nacheinander ab (jede wird vor der nächsten fertig abgewartet).")
    for folder, name in to_repair:
        # Nichts deployen, solange ein Build/Makeover läuft (eine Seite gleichzeitig) — läuft
        # gerade eins (z.B. manuell gestartet), Rest kommt im nächsten 120s-Durchlauf dran.
        if website_builder.makeover_busy():
            logger.info("LiveWatch", "Makeover läuft parallel — Rest-Reparatur folgt im "
                                     "nächsten Durchlauf.")
            break
        _live_redeploy_at[folder] = time.time()
        fails = _live_fail_count.get(folder, 0) + 1
        _live_fail_count[folder] = fails         # zählt hoch bis die Seite wieder live ist
        logger.info("LiveWatch", f"'{name}' nicht erreichbar → Re-Deploy wird angestoßen "
                                 f"(Versuch {fails}).")
        try:
            jid = website_builder.deploy_existing(folder, name)
            _wait_repair_job(jid)
        except Exception as e:
            logger.warn("LiveWatch", f"Re-Deploy '{name}' fehlgeschlagen: "
                                     f"{type(e).__name__}: {str(e)[:120]}")


def _maybe_force_rotation(down_count: int) -> None:
    """Mehrere Seiten gleichzeitig offline -> erzwingt (nach Kapazitäts-Check in
    agent_railway.force_rotate) ein neues Railway-Sammelprojekt für KOMMENDE Deploys
    (repariert NICHT die aktuell toten Seiten selbst — das macht weiter der normale
    Redeploy-Pfad in _live_check_once). Cooldown verhindert Spam, solange dieselbe
    Ausfallserie andauert."""
    if time.time() - _live_last_forced_rotation[0] < _LIVE_ROTATE_COOLDOWN:
        return
    # Ein kurzer Aussetzer der EIGENEN Internetverbindung kann in einem einzigen 120s-
    # Durchlauf viele Seiten gleichzeitig fälschlich als "offline" erscheinen lassen (jede
    # einzelne HTTP-Prüfung schlägt dann fehl) — das hat nichts mit Railway zu tun. Denselben
    # Check nutzt der Night-Builder bereits bei der Exhaustion-Behandlung (_wait_online).
    if not _internet_ok():
        logger.info("LiveWatch", f"{down_count} Seiten offline, aber eigene Internetverbindung "
                                 "gerade instabil — werte das NICHT als Railway-Symptom.")
        return
    try:
        import agent_railway
        if not agent_railway.is_ready():
            return
        res = agent_railway.force_rotate(reason=f"{down_count} Seiten gleichzeitig offline")
        _live_last_forced_rotation[0] = time.time()
        if res.get("ok") and not res.get("already"):
            logger.warn("LiveWatch", f"{down_count} Seiten gleichzeitig offline -> neues "
                                     f"Railway-Projekt '{res['project']}' für neue Deploys angelegt.")
            try:
                import discord_bot
                discord_bot.notify(
                    "⚠ Railway-Rotation erzwungen",
                    f"{down_count} Seiten waren gleichzeitig nicht live — typisches Zeichen eines "
                    f"vollen/blockierten Railway-Projekts. Neue Webseiten werden ab sofort in "
                    f"'{res['project']}' gebaut.",
                    color=0xff9500,
                )
            except Exception:
                pass
        elif res.get("error") == "not_near_capacity":
            logger.info("LiveWatch", f"{down_count} Seiten offline, aber aktives Railway-Projekt "
                                     f"hat nur {res.get('service_count', '?')}/"
                                     f"{res.get('rotate_at', '?')} Services — keine Rotation, "
                                     "Ursache liegt vermutlich anderswo (einzelne Build-Fehler, "
                                     "Railway-Account-/Guthaben-Status manuell prüfen).")
        elif not res.get("ok"):
            logger.warn("LiveWatch", f"Erzwungene Rotation fehlgeschlagen: {res.get('error','')[:120]}")
    except Exception as e:
        logger.warn("LiveWatch", f"Erzwungene Rotation fehlgeschlagen: {type(e).__name__}")


def _sync_one(job_id: str) -> None:
    """Eine Webseiten-Zeile nach Supabase pushen (best-effort)."""
    try:
        import cloud_sync_websites
        import db_websites
        row = db_websites.get_by_job(job_id)
        if row:
            cloud_sync_websites.push(row)
    except Exception:
        pass


# Demo-Lebensdauer: Live-Demos OHNE Kundenantwort nach so vielen Tagen abbauen (Railway
# freihalten, damit das Projekt nicht ans Service-/Guthaben-Limit läuft → sonst deployt nichts
# mehr). Kürzer = Railway bleibt leerer. 0 = Teardown aus. Sirs Vorgabe (02.07.2026): 5 Tage.
_TEARDOWN_DAYS = int(os.environ.get("JARVIS_DEMO_TEARDOWN_DAYS", "5") or "5")


def _lead_converted(lead_id) -> bool:
    """True, wenn der Lead in einem aktiven Deal ist (verkauft/Termin) → Demo behalten."""
    if not lead_id:
        return False
    try:
        import db_evaluated
        lead = db_evaluated.get_by_id(int(lead_id)) or {}
        return (lead.get("status") or "").strip().lower() in ("verkauft", "termin")
    except Exception:
        return False


def teardown_stale_demos(max_age_days: int = 0) -> int:
    """Baut Live-Demos ab, die nach `max_age_days` (Default JARVIS_DEMO_TEARDOWN_DAYS=5) WEDER
    konvertiert sind (verkauft/Termin) NOCH eine Kundenantwort bekommen haben (Hosting-Kosten
    deckeln): löscht den Railway-Service und archiviert die Zeile. Verkaufte/Termin-Leads UND
    Seiten mit erkannter Antwort (replied=1, siehe inbox_reader.py/db_websites.mark_replied)
    bleiben unangetastet, egal wie alt — Sir arbeitet an denen noch. Gibt die Anzahl abgebauter
    Demos zurück. 0=aus."""
    days = max_age_days or _TEARDOWN_DAYS
    if days <= 0:
        return 0
    try:
        import db_websites
        import website_builder
        import agent_railway
    except Exception:
        return 0
    if not agent_railway.is_ready():
        return 0
    cutoff = time.time() - days * 86400
    abgebaut = 0
    for w in db_websites.get_all():                 # aktive (archived=0)
        try:
            created = float(w.get("created") or 0)
            if not created or created > cutoff:
                continue                            # zu jung
            if not (w.get("live_url") or "").strip():
                continue                            # nichts live → nichts abzubauen
            if _lead_converted(w.get("lead_id")):
                continue                            # verkauft/Termin → behalten
            if int(w.get("replied") or 0):
                continue                            # Kunde hat geantwortet → behalten
            # Service heißt IMMER web-<slug> — früher wurde ohne „web-" gelöscht, daher traf der
            # Löschbefehl nie und der Railway-Service blieb bestehen (Projekt lief trotzdem voll).
            slug = website_builder._slug(w.get("name", ""))
            r = agent_railway.service_delete_by_name(f"web-{slug}")
            db_websites.update(w["job_id"], archived=1, live=0, status="abgebaut")
            abgebaut += 1
            logger.info("AutoBuilder", f"Demo abgebaut (>{days} Tage, keine Antwort/nicht verkauft): "
                                       f"{w.get('name','?')} · Railway: {r.get('error') or 'ok'}")
        except Exception as e:
            logger.warn("AutoBuilder", f"Teardown übersprungen ({w.get('name','?')}): {type(e).__name__}")
    if abgebaut:
        logger.success("AutoBuilder",
                       f"{abgebaut} unbeantwortete Demo(s) nach {days} Tagen abgebaut.")
    return abgebaut


def _loop() -> None:
    while is_running():
        today = _today()
        cur_session = _session()
        with _lock:
            neuer_tag     = _state["day"] != today
            neuer_session = _state.get("session", "") != cur_session
            if neuer_tag or neuer_session:
                _state["day"]     = today
                _state["session"] = cur_session
                _makeover_stuck.clear()              # je Session zurücksetzen
                _rescue_tries.clear()
                globals()["_farewell_sent"] = False
                if neuer_tag:
                    # Neuer Tag → LiveWatch-Backoff für dauerhaft tote Seiten zurücksetzen,
                    # falls die Infrastruktur (Railway) sich über Nacht erholt hat.
                    _live_fail_count.clear()
                    _live_gaveup.clear()
                    logger.info("AutoBuilder", f"Neuer Tag {today} — Tagesplan startet neu")
                else:
                    sess_label = cur_session.split("_")[-1].upper()
                    logger.info("AutoBuilder",
                                f"Neue Bau-Session ({sess_label}) — {_daily_limit()} Seiten")
        if neuer_tag:                                # einmal je Tag: alte Demos abbauen (best-effort)
            try:
                teardown_stale_demos()
            except Exception as e:
                logger.warn("AutoBuilder", f"Teardown-Lauf fehlgeschlagen: {type(e).__name__}")

        # ── Erschöpfung zuerst: Claude-Limit → ein bisschen ChatGPT; beide leer → aus+Neustart ─
        if _claude_limited:
            _handle_exhaustion()
            if not is_running():
                break
            _idle_sleep(3)
            continue

        # ── Phase 1: bis Tageslimit neue Seiten bauen (Paid-Boost: ×2) ───────
        if _count_today() < _daily_limit():
            lead = _pick_next_lead()
            if lead:
                try:
                    _build_and_email(lead)
                except Exception as e:
                    msg = f"{type(e).__name__}: {e}"
                    if _is_transient(msg):
                        # Internet-/API-Aussetzer: NICHT als Fehlschlag zählen, auf Verbindung
                        # warten und denselben Schritt erneut versuchen → der Builder bleibt dran.
                        logger.warn("AutoBuilder", f"Transienter Fehler beim Bau ({type(e).__name__}) — bleibe dran.")
                        _wait_online(600)
                    else:
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

        # ── Phase 3: nichts mehr zu bauen/verbessern → ggf. verabschieden, dann Pause ─
        _farewell_if_done()
        done_note = "✓ alle Seiten auf 7/7 — fertig." if _all_sites_complete() else "Warte auf 0 Uhr…"
        _set(mode="idle",
             phase=f"Pause — heute {_count_today()}/{_daily_limit()} gebaut. {done_note}",
             current="")
        _idle_sleep(120)
