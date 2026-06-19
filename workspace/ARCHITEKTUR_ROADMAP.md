# Architektur-Roadmap — verbleibende große Hebel

Aus dem frischen Architektur-Audit. Die folgenden Punkte sind **strukturelle Refactorings**
mit hohem Wert, aber auch hohem Risiko/Aufwand — bewusst getrennt vom laufenden Betrieb,
damit die funktionierende Pipeline nicht in einem Zug umgebaut wird. Empfohlene Reihenfolge:

## 1. Kanonischer Dedup-Schlüssel (Wurzel vieler Inkonsistenzen) — HIGH
Heute drei Varianten: DB1 `name=stadt` exakt, DB2/Cloud `md5(lower(name)|stadt)`, Legacy exakt.
**Bereits gemildert:** DB1-Dup-Check ist jetzt case-insensitiv. **Offen:** ein gemeinsames
`leadkey.py` (Normalisierung: lower, Whitespace-Collapse, Rechtsform-Stripping, optional Straße),
importiert von db_raw, db_evaluated, cloud_sync. Adresse in den Key aufnehmen (zwei Betriebe
gleichen Namens/Stadt kollidieren sonst).

## 2. `leads.db` (DB „Legacy") eliminieren — HIGH
Jeder Scraper schreibt doppelt (db.insert + db_raw.insert_raw). Das Frontend liest DB2; der
Verifier auf leads.db ist deaktiviert. Nur `db.get_stats()` (SSE/Status) hängt noch dran.
→ Stats aus db_raw/db_evaluated ziehen, db.py entfernen. Halbiert Schreiblast + Lock-Contention,
beseitigt eine divergierende Dedup-Logik.

## 3. Worker-Supervisor + Heartbeat — HIGH
Worker sind nackte Daemon-Threads; stirbt einer außerhalb der inneren try, meldet `is_running()`
weiter „läuft". → Registry mit `last_heartbeat`, Restart-Backoff, `/api/status` pro Worker
(`alive, leads_total, errors, last_ts`). (Observability-Basis `metrics.py` existiert bereits.)

## 4. DB-Connections: thread-lokal statt pro Call — MEDIUM
Jeder Call öffnet eine neue Connection + setzt WAL neu, alles serialisiert über einen globalen
Lock (macht WAL nutzlos). → `threading.local`-Connections, `busy_timeout`, Lock nur für Writes,
Reads parallel über WAL.

## 5. `claim_next_pending` crash-fest — MEDIUM
Stirbt ein Evaluator während `analyze()`, bleibt der Lead dauerhaft `running` (nur Voll-Neustart
räumt auf). → `claimed_at`-Spalte + Watchdog, der `running` älter als N Min auf `pending` setzt.
Tie-Breaker `gefunden_am ASC` gegen Starvation.

## 6. Scoring testbar machen + erste Tests — MEDIUM
`score_writer.evaluate` ruft Ollama mitten in der Scoring-Funktion → deterministischer Pfad nicht
ohne Ollama testbar. `pipeline.build_row` mischt Mapping + I/O + Push. → reine Funktionen
ausgliedern, `tests/` anlegen (quality.is_real_business, lead_key, deterministischer Score,
extract_json). Aktuell **keine** Testdatei im Repo.

## 7. SSE-Stats throttlen — MEDIUM
Jedes Lead-Event triggert ein volles `get_stats()` (mehrere COUNTs) gegen die Legacy-DB.
→ Stats max. 1×/Sek cachen; im Lead-Event nur Delta-Counter; Quelle DB2/DB1 statt leads.db.

## 8. Prompt-Caching + History-Trimming im Claude-Agent — LOW/MEDIUM
System-Prompt ist klein (unter Opus-Cache-Minimum), aber die clientseitige `_claudeHistory`
wächst unbegrenzt → steigende Kosten/Context. → History clientseitig auf letzte N Runden trimmen.

---
**Bereits in diesem Durchgang umgesetzt:** Marktplatz-Filter (P4), schreibender Lead-Zugriff
(P2: leads_update), Akquise-Anreicherung on demand (P1: enrich_business), Observability
(P6: metrics + /api/metrics + is_error), Konversions-Tracking + Job-Poll (P3/P5), dauerhafter
Sprach-Gesprächsmodus (VAD), Shop-Workflow (immer Skill → neuer Ordner → Redesign → git push),
case-insensitives DB1-Dedup.
