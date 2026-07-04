"""
lead_collector.py — stündlicher, zeitbegrenzter Lead-Sammler mit Discord-Report.

Läuft als Hintergrund-Thread und stößt in einem festen Intervall (Default 1 h) einen
zeitbegrenzten Sammel-Lauf an: Scraper + lokaler Evaluator (scrapers.controller) laufen
`JARVIS_LEAD_RUN_SECONDS` (Default 600 = 10 Min), werden dann gestoppt, und das Ergebnis
(Anzahl neu bewerteter Leads + die besten `JARVIS_LEAD_TOP_N`) geht als Discord-Embed raus.

Robust nach dem Vorbild des Live-Watchers (auto_builder) und des Noon-Loops (discord_bot):
- ganzer Zyklus in try/except → ein Fehler killt den Loop nie
- Latch in data/lead_collector_state.json → überlebt Neustarts, feuert nicht doppelt
- unterbrechbares Warten über controller._stop_event → ein Dashboard-Stop beendet sofort
- Discord offline verhindert das Sammeln NICHT (Report ist best-effort)
- ein MANUELL (vom Nutzer) gestarteter Sammler wird NIE vom Scheduler weggestoppt

Abschaltbar per JARVIS_LEAD_COLLECTOR=0.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import logger

_BASE   = Path(__file__).parent
_LATCH  = _BASE / "data" / "lead_collector_state.json"
_lock   = threading.Lock()
_started = False


# ── Konfiguration ─────────────────────────────────────────────────────────────

def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)) or default)
    except (ValueError, TypeError):
        return default


def enabled() -> bool:
    """Stündlicher Sammler aktiv? Default AN; aus mit JARVIS_LEAD_COLLECTOR=0/false/no/off."""
    return os.environ.get("JARVIS_LEAD_COLLECTOR", "1").strip().lower() \
        not in ("0", "false", "no", "off", "")


def _interval() -> int:
    """Sekunden zwischen zwei Sammel-Läufen (Default 3600 = stündlich, min. 300)."""
    return max(300, _int_env("JARVIS_LEAD_INTERVAL", 3600))


def _run_seconds() -> int:
    """Dauer eines Sammel-Laufs (Default 600 = 10 Min, min. 30)."""
    return max(30, _int_env("JARVIS_LEAD_RUN_SECONDS", 600))


def _top_n() -> int:
    return max(1, min(10, _int_env("JARVIS_LEAD_TOP_N", 3)))


def _stop_buffer() -> int:
    """Puffer nach controller.stop(), damit ein gerade IN-FLIGHT befindlicher Lead (z.B.
    mitten in einem Ollama-Call) noch fertig wird und in DB2 landet, bevor wir zählen."""
    return max(0, _int_env("JARVIS_LEAD_STOP_BUFFER", 20))


def _drain_max_seconds() -> int:
    """Maximale Wartezeit NACH Fensterende, bis der Evaluator den Rest-Backlog (schon
    gesammelte, aber noch nicht bewertete Leads) abgearbeitet hat, bevor er zwangsweise
    mitgestoppt wird (Default 5 Min, min. 30s) — verhindert, dass ein hartnäckiger Rest
    den nächsten stündlichen Lauf verzögert."""
    return max(30, _int_env("JARVIS_LEAD_DRAIN_MAX", 300))


def _drain_evaluator_backlog() -> None:
    """Wartet, bis leads_raw keine 'pending'-Leads mehr hat (Scraper sind schon gestoppt,
    der Evaluator läuft aber noch weiter) — gekappt per _drain_max_seconds()."""
    import db_raw
    deadline = time.time() + _drain_max_seconds()
    n_start = None
    while time.time() < deadline:
        try:
            n = db_raw.count_pending()
        except Exception:
            return
        if n_start is None:
            n_start = n
        if n <= 0:
            return
        time.sleep(5)
    if n_start:
        logger.info("LeadCollector",
                     f"Drain-Zeitlimit erreicht — Evaluator wird trotz Rest-Backlog gestoppt.")


# ── Latch (überlebt Neustarts) ─────────────────────────────────────────────────

def _last_run() -> float:
    try:
        return float(json.loads(_LATCH.read_text(encoding="utf-8")).get("last_run", 0.0))
    except Exception:
        return 0.0


def _mark_ran() -> None:
    try:
        _LATCH.parent.mkdir(parents=True, exist_ok=True)
        _LATCH.write_text(json.dumps({"last_run": time.time()}, ensure_ascii=False),
                          encoding="utf-8")
    except Exception:
        pass


def _due() -> bool:
    """Ist wieder ein Lauf fällig? (erster Lauf sofort, danach alle _interval() Sekunden)."""
    return (time.time() - _last_run()) >= _interval()


# ── Report-Formatierung (rein, netzwerkfrei → testbar) ─────────────────────────

def _fmt_lead(i: int, lead: dict) -> "tuple[str, str]":
    """Baut (Feld-Name, Feld-Wert) für einen Lead — leere Angaben werden weggelassen."""
    name  = (lead.get("name") or "Unbekannt").strip()
    score = lead.get("score") or 0
    head  = f"#{i} · {name} — Score {score}"[:256]

    lines: list[str] = []
    ort = " ".join(x for x in [(lead.get("stadt") or "").strip(),
                               (lead.get("bundesland") or "").strip()] if x).strip()
    branche = (lead.get("branche") or "").strip()
    if ort or branche:
        lines.append("📍 " + " · ".join(x for x in [ort, branche] if x))

    typ  = (lead.get("lead_typ") or "").strip()
    sich = lead.get("sicherheit")
    ew   = lead.get("erwartungswert_euro") or 0
    zeile2 = []
    if typ:
        zeile2.append(f"🏷️ {typ}")
    if sich not in (None, ""):
        zeile2.append(f"Sicherheit {sich}%")
    if ew:
        zeile2.append(f"💶 {ew} €")
    if zeile2:
        lines.append(" · ".join(zeile2))

    kontakt = []
    if (lead.get("telefon") or "").strip():
        kontakt.append(f"📞 {lead['telefon'].strip()}")
    if (lead.get("email_adresse") or "").strip():
        kontakt.append(f"✉️ {lead['email_adresse'].strip()}")
    if (lead.get("ansprechpartner") or "").strip():
        kontakt.append(f"👤 {lead['ansprechpartner'].strip()}")
    if kontakt:
        lines.append("  ".join(kontakt))

    hook = (lead.get("pitch_hook") or "").strip()
    if hook:
        lines.append(f"💬 {hook}")

    value = "\n".join(lines) if lines else "—"
    return head, value[:1024]


def _build_report(new_count: int, top: list) -> "tuple[str, str, list]":
    """Baut (title, description, fields) für den Discord-Report. Netzwerkfrei/testbar."""
    wort  = "Lead" if new_count == 1 else "Leads"
    title = f"🎯 Stündlicher Lead-Lauf — {new_count} neue {wort} bewertet"
    ts    = datetime.now().strftime("%d.%m.%Y · %H:%M")
    if new_count:
        desc = (f"🕐 {ts}\n{new_count} neu gesammelt & bewertet · "
                f"Top {len(top)} unten.")
    else:
        desc = f"🕐 {ts}\nKeine neuen Leads in diesem Lauf."
    fields = [_fmt_lead(i, l) for i, l in enumerate(top, 1)]
    return title, desc[:4096], fields


# ── Manueller Start während des Sammel-Fensters ───────────────────────────────
# controller.start() ist idempotent — klickt Sir WÄHREND eines Scheduler-Laufs im Dashboard
# auf „Start", wäre das ein No-Op und der Scheduler würde am Fensterende auch den vom Nutzer
# gewollten Dauerlauf wegstoppen. Darum meldet die /api/start-Route jeden manuellen Start
# hierher; fällt er ins laufende Fenster, unterbleibt das Stoppen.
_manual_start_ts = [0.0]

# Live-Status fürs Dashboard (Mein-Status-Tab) — rein informativ, keine Steuerung.
_in_window   = [False]                        # läuft gerade ein Sammel-Fenster?
_window_start = [0.0]
_last_result: dict = {"new_count": None, "ts": 0.0, "top": []}


def note_manual_start() -> None:
    """Von app.py (/api/start) aufgerufen: merkt den Zeitpunkt eines manuellen Starts."""
    _manual_start_ts[0] = time.time()


def status() -> dict:
    """Live-Status des stündlichen Sammlers fürs Dashboard (Mein-Status-Tab): läuft gerade
    ein Fenster, wann kommt das nächste, was hat der letzte Lauf gefunden."""
    last = _last_run()
    interval = _interval()
    now = time.time()
    next_due = (last + interval) if last else now
    return {
        "enabled":          enabled(),
        "interval_seconds": interval,
        "run_seconds":      _run_seconds(),
        "last_run_ts":      last,
        "seconds_to_next":  max(0, int(next_due - now)),
        "due_now":          _due(),
        "in_window":        _in_window[0],
        "window_elapsed":   max(0, int(now - _window_start[0])) if _in_window[0] else 0,
        "last_result":      dict(_last_result),
    }


# ── Zyklus ─────────────────────────────────────────────────────────────────────

def _run_once() -> None:
    """Ein Sammel-Zyklus: (evtl.) starten → sammeln → (evtl.) stoppen → Report posten."""
    import scrapers.controller as controller
    import db_evaluated
    import discord_bot

    fenster_start = time.time()
    _in_window[0] = True
    _window_start[0] = fenster_start
    try:
        manuell  = controller.is_running()         # War der Sammler schon an (Nutzer)?
        snapshot = db_evaluated.max_id()           # id-Stand vor dem Lauf

        selbst_gestartet = False
        if not manuell:
            controller.start()                     # idempotent; wir sind der Starter
            selbst_gestartet = True
            logger.info("LeadCollector", f"Sammel-Lauf gestartet ({_run_seconds()}s).")
        else:
            logger.info("LeadCollector", "Sammler läuft bereits (manuell) — hänge mich nur an.")

        # Unterbrechbares Warten: reagiert sofort auf einen Dashboard-Stop (_stop_event).
        controller._stop_event.wait(_run_seconds())

        if selbst_gestartet:
            if _manual_start_ts[0] >= fenster_start:
                # Sir hat WÄHREND unseres Fensters manuell gestartet → sein Lauf, nicht stoppen.
                logger.info("LeadCollector", "Manueller Start während des Fensters erkannt — "
                                             "Sammler bleibt an.")
            else:
                # Zweistufig statt hartem controller.stop(): erst nur die Scraper stoppen,
                # dann den Evaluator noch den Rest-Backlog abarbeiten lassen (gekappt), ERST
                # DANN auch ihn stoppen. Sonst blieben frisch gesammelte, aber noch nicht
                # bewertete Leads bis zum nächsten Stunden-Lauf als 'pending' liegen — der
                # stündliche Sammler hätte dann Leads gefunden, aber nicht alle bewertet.
                controller.stop_scrapers()         # NUR stoppen, was WIR gestartet haben
                _drain_evaluator_backlog()
                controller.stop_evaluator()
                # Race-Puffer: Alt-Workern Zeit geben, das Stop-Signal zu sehen, bevor gezählt
                # wird. Echtes sleep — _stop_event ist gerade GESETZT, ein wait() darauf wäre
                # ein No-Op und würde sofort zurückkehren.
                time.sleep(_stop_buffer())

        new_count = db_evaluated.count_since(snapshot)
        top       = db_evaluated.get_top(_top_n())
        _last_result["new_count"] = new_count
        _last_result["ts"]        = time.time()
        _last_result["top"]       = top
        title, desc, fields = _build_report(new_count, top)
        posted = discord_bot.post_report(title, desc, fields, 0x00d4ff)
        logger.success("LeadCollector",
                       f"Lauf fertig: {new_count} neue Leads · Report "
                       f"{'in Discord gepostet' if posted else 'lokal protokolliert'}.")
    finally:
        _in_window[0] = False


def _loop() -> None:
    # 90s Boot-Puffer: erst App-Start/DB-Sync/Discord hochfahren lassen, bevor ggf. der erste
    # Sammel-Lauf Browser-Worker + Ollama startet (CPU-Spike direkt beim Boot vermeiden).
    time.sleep(90)
    while True:
        try:
            if enabled() and _due():
                try:
                    _run_once()
                finally:
                    # Latch IMMER setzen — auch wenn der Lauf mittendrin wirft. Sonst würde
                    # der nächste 60s-Poll sofort den NÄCHSTEN vollen 10-Min-Lauf starten
                    # (Dauer-Scraping im Minutentakt bei persistentem Fehler statt stündlich).
                    _mark_ran()
        except Exception as e:
            logger.warn("LeadCollector", f"Zyklus-Fehler: {type(e).__name__}: {str(e)[:120]}")
        time.sleep(60)                         # Poll; der Latch/_due gated den echten Lauf


def start() -> None:
    """Startet den stündlichen Sammler-Loop (idempotent, Daemon-Thread)."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, name="LeadCollector", daemon=True).start()
    logger.info("LeadCollector",
                f"Stündlicher Lead-Sammler aktiv (Intervall {_interval()}s, "
                f"Dauer {_run_seconds()}s, Top {_top_n()}).")
