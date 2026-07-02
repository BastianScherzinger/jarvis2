# Stündlicher Lead-Sammler + Code-Audit + Paid-Boost (2026-07-02)

## Auftrag (Sir)
1. Den ganzen Code mit Spezialisten-Agenten (Architekt, Explorer, Reviewer) scannen und
   optimieren — vor allem den lokalen Lead-Finden-&-Bewerten-Teil.
2. Lead-Sammler automatisieren: **jede Stunde 10 Minuten sammeln**, Ergebnis + **Top-3-Leads
   in Discord** anzeigen.
3. Kosten-Modus: erkennen, wenn **bezahlte Extra-Tokens** benutzt werden (statt Abo/lokal) —
   und wenn ja, **doppelt so viele Webseiten** bauen.
4. Alles fixen, dokumentieren, final pushen.

## Vorgehen
3 Explore-Agenten (Subsystem-Karte, Scheduling-/Discord-Muster, Bug-Sweep) + 1 Plan-Agent
(Architektur) → genehmigter Plan → Umsetzung → Tests → Review → Push.

---

## Teil A — Stündlicher Lead-Sammler (`lead_collector.py`, NEU)

- Daemon-Thread `LeadCollector` (Start in `app.py` neben dem Discord-Bot-Start).
- **Latch** `data/lead_collector_state.json` (`last_run`-Timestamp) → überlebt Neustarts,
  feuert höchstens einmal pro `JARVIS_LEAD_INTERVAL` (Default 3600 s).
- **Zyklus** (`_run_once`):
  1. `controller.is_running()` prüfen — lief der Sammler **manuell**, wird er NIE gestoppt
     (der Scheduler hängt sich nur an und meldet).
  2. `db_evaluated.max_id()`-Snapshot → nach dem Lauf zählt `count_since(snapshot)` exakt
     die neu bewerteten Leads (1 Query statt der teuren `get_stats()`-Runde).
  3. `controller.start()` → `_stop_event.wait(JARVIS_LEAD_RUN_SECONDS)` (unterbrechbar —
     ein Dashboard-Stop beendet das Sammeln sofort) → `controller.stop()` + 20 s Race-Puffer.
  4. `db_evaluated.get_top(JARVIS_LEAD_TOP_N)` → Discord-Embed via neuem
     `discord_bot.post_report(title, description, fields)` (Feld je Lead: Score, Ort/Branche,
     Typ/Sicherheit/€, Kontakt, Pitch-Hook; Discord-Limits per Truncation eingehalten).
- Fehler killen den Loop nie (try/except je Zyklus); Discord offline verhindert das
  Sammeln nicht (Report best-effort).
- Flags: `JARVIS_LEAD_COLLECTOR` (Default AN), `JARVIS_LEAD_INTERVAL=3600`,
  `JARVIS_LEAD_RUN_SECONDS=600`, `JARVIS_LEAD_TOP_N=3`, `JARVIS_LEAD_STOP_BUFFER=20`.

### Neue Helfer
- `db_evaluated.max_id()` / `count_since(min_id)` — schlanke Snapshot-Zählung.
- `discord_bot.post_report(...)` + `_post_report_embed(...)` — thread-sicherer Embed
  mit Feldern (analog `notify()`), wirft nie.

## Teil B — Paid-Boost: doppeltes Bau-Limit bei bezahlten Tokens

Normal läuft der Builder **kostenlos**: headless `claude -p` über die Abo-Anmeldung +
lokale Ollama-Modelle. Bezahlte Tokens fließen nur in zwei Fällen — genau die erkennt
`cost_tracker.paid_tokens_detected()`:
1. **Heute echte API-Kosten gebucht** (`api_eur > 0` in `data/costs.json` — Anthropic-API
   des Dashboard-Agenten, OpenAI-Bilder).
2. **Mehrere ANTHROPIC-Keys konfiguriert** (`claude_keys.count() > 1`) — dann laufen die
   headless-Builder-Läufe über `ANTHROPIC_API_KEY` (claude_coder.py) = bezahlt pro Token.

`cost_tracker.paid_boost_active()` = Erkennung UND Schalter `JARVIS_PAID_BOOST` (Default AN).
`auto_builder._daily_limit()` liefert dann `JARVIS_DAILY_SITES × 2` — wer pro Token zahlt,
hängt nicht am Abo-Session-Limit und baut doppelt. Umgestellt auf die dynamische Funktion:
Bau-Schleife (Phase-1-Gate), Session-Log, Status (`daily_limit` + neues Feld `paid_boost`),
`scaling_info()`, `daily_log()`, Pause-Text. Boost-Aktivierung wird einmalig geloggt
(„💳 Paid-Boost aktiv … 5 → 10").

## Teil C — Audit-Fixes (lokaler Lead-Teil)

| # | Datei | Fix |
|---|-------|-----|
| 1 | `scrapers/website_checker.py` | `whois()` (python-whois, KEIN eigenes Timeout) in Daemon-Thread mit `join(5s)` — ein träger WHOIS-Server friert keinen Scraper-Worker mehr ein |
| 3+4 | `scrapers/_http.py` `ask_ollama` | Unerwartete Fehler werden geloggt statt still `""`; 1 Retry mit 0,8 s Backoff bei Timeout (nicht bei „Ollama aus") |
| 7 | `duplicate_guard.py` | `db_websites.has_site_key(sk)` (SELECT 1, neu) statt `get_all()`-Full-Table-Scan pro Lead |
| 8 | `geo_cache.py` | `db_evaluated.get_for_globe()` (6 Spalten, neu) statt `get_all(limit=5000)` mit 60+ Spalten bei jedem Globus-Poll |
| 11 | `scrapers/controller.py` | `_evaluator_started=False` in `stop()` unter `_eval_lock` — kein Doppel-Evaluator bei stop→start |
| 12 | `scrapers/maps.py` | `ctx.close()` im Browser-Rebuild-Fehlerpfad (Chromium-Context-Leak) |
| 13 | `scrapers/_http.py` | Lock um `_BEST_MODEL`-Cache (parallele Evaluator-Threads) |
| 14 | `geo_cache.py` | `_busy=False` im `finally` unter `_lock` |
| 15 | `agents/ai_worker.py` | Leere KI-Antwort → Treffer überspringen statt Suchtitel als Firmenname (keine Pseudo-Leads mehr) |
| 16 | `scrapers/_http.py` | `nvidia-smi`-Abfrage für `num_gpu` lazy + gecacht (kein Subprozess mehr beim Import) |

## Teil D — Multi-Agent-Code-Review über das Diff (8 Finder-Angles) + Nachbesserungen

Der Review (5 parallele Finder-Agenten: line-by-line, removed-behavior, cross-file,
Reuse/Simplify/Efficiency, Altitude/Conventions) fand 6 bestätigte Probleme im frischen
Code — alle behoben:

| Fund | Fix |
|------|-----|
| `lead_collector`: 20s-Race-Puffer war ein No-Op (`_stop_event.wait()` auf gerade GESETZTEM Event kehrt sofort zurück) | echtes `time.sleep(_stop_buffer())` |
| `lead_collector`: `_mark_ran()` nur im Erfolgspfad → bei persistentem Fehler Dauer-Scraping alle ~11 Min statt stündlich | Latch im `finally` — auch ein fehlgeschlagener Lauf zählt als Lauf |
| `lead_collector`: manueller Dashboard-Start WÄHREND des 10-Min-Fensters wäre am Fensterende weggestoppt worden | neues `note_manual_start()` (von `/api/start` gemeldet) — fällt ein manueller Start ins Fenster, unterbleibt das Stoppen |
| `cost_tracker`: OpenAI-Hero-Bilder buchen in `api_eur` → Boost wäre an Bau-Tagen fälschlich aktiv gewesen, obwohl das Claude-Session-Limit der Engpass bleibt | Erkennung auf echte API-**Tokens** (`tokens_in/out > 0`) umgestellt |
| `cost_tracker.paid_boost_active` im Hot-Path (Dashboard-Poll alle ~5s, Builder-Loop) las jedes Mal die komplette wachsende `data/costs.json` | 60s-TTL-Cache (Muster `_BEST_MODEL`) |
| `_http.py`: `_OLLAMA_PARALLEL` machte trotz Lazy-Fix weiter einen `nvidia-smi`-Call beim Import; Retry-Backoff schlief IM Semaphor; funktionslokaler `import logger` (CLAUDE.md-Regel) | GPU-Hint aus der einen Import-Abfrage wiederverwendet (1 statt 2 Calls), Backoff außerhalb des Slots, Import top-level |

Zusätzlich: bestehender Test `test_auto_builder_daily_log` hing über `daily_log()["daily_limit"]`
an der echten `costs.json`/Key-Konfiguration der Maschine → Paid-Boost im Test gestubbt.
Erster Sammel-Lauf startet jetzt 90 s (statt 30 s) nach App-Boot (kein Browser-/Ollama-Spike
beim Hochfahren). Boot-Delay + Latch machen den Start planbar.

### Bewusst so gelassen (Review-Funde, dokumentierte Entscheidung)
- `count_since` zählt bei `INSERT OR REPLACE` (Re-Bewertung derselben Firma im Fenster) die
  Ersetzung als „neu" — selten (db_raw dedupliziert), Impact = leicht überhöhte Report-Zahl;
  im Docstring vermerkt.
- `duplicate_guard`/`has_site_key` wertet jetzt auch ARCHIVIERTE Seiten als „bereits gebaut"
  (das alte `get_all()` filterte sie heraus) — gewollt: abgebaute Demos (kein Kauf) sollen
  nicht erneut gebaut werden.
- `lead_collector._int_env` ist eine bewusste 6-Zeilen-Kopie von `_http._int_env`: ein Import
  von `scrapers._http` beim Modul-Load würde den bewusst leichten Import (nur stdlib+logger)
  von `lead_collector` zerstören.
- `ask_ollama`-Retry behält den vollen Timeout im 2. Versuch (Worst-Case 2×180 s je Call) —
  akzeptiert; der Slot wird zwischen den Versuchen freigegeben.

## Backlog — bewusst NICHT in diesem Durchlauf (hohes Regressionsrisiko, je eigener PR)

- **Fix 2**: Website-Prüfung (`check_website` = HTTP+WHOIS) aus allen 5 Scrapern in den
  Evaluator ziehen (Scraper setzt nur `has_website`) — halbiert die Latenz pro Fund,
  aber Scoring-Regressionsrisiko (`website_alter` fließt evtl. ins Scoring). Löst Fix 1 endgültig.
- **Fix 6**: 4× byte-identisches `_parse_rating` + `_get`/`_HEADERS` (gelbe_seiten,
  dasoertliche, elfacht, golocal) nach `scrapers/_http.py` bündeln — vor Zusammenlegung diffen.
- **Fix 5**: Zweite DDG-Suche in `agents/evaluator/social_researcher.py:76` (verletzt das
  „keine 2. Suche"-Design, Such-Budget/Block-Risiko) hinter Flag legen, Default AUS.
- **Fix 9**: Thread-lokale SQLite-Connection statt Connection+PRAGMAs pro Aufruf
  (`db_raw._conn`, `db_evaluated._conn`) — Transaktions-/WAL-Semantik sorgfältig testen.
- **Fix 10**: `db_raw.insert_raw` Dup-Check: normalisierte Spalte + UNIQUE-Index statt
  `LOWER()`-Scan ohne Index — Schema-Migration + Backfill nötig.
- **Generationen-Event im controller**: `stop()→start()` teilt sich EIN `_stop_event`; ein
  sofortiger `start()` cleart es, bevor langsame Alt-Threads es sehen (Doppel-Worker-Rest-
  risiko). Sauber: pro `start()` ein frisches Event, Worker halten ihre Generation.
- **WHOIS-Thread-Akkumulation**: `_whois_age` lässt bei hängenden WHOIS-Servern Daemon-Threads
  zurück (je Lead-mit-Website einer). Endgültige Lösung ist Fix 2 (WHOIS ganz aus den Scrapern).
- **`_bool_env`-Helfer**: das `not in ("0","false","no","off","")`-Idiom existiert inzwischen
  4× (app.py, discord_bot, lead_collector, cost_tracker) — bei Gelegenheit bündeln.

## Tests
17 neue Tests (alle netzwerkfrei): Lead-Collector (Flag, Latch, Report-Format,
`_run_once` manuell/selbstverwaltet), `max_id`/`count_since`, `get_for_globe`,
`has_site_key`, Paid-Detection (Kosten + Mehrfach-Keys + Schalter), `_daily_limit`-Boost,
`ask_ollama`-Fehlerpfad. Komplette Suite grün.
