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

## 2. `leads.db` (DB „Legacy") eliminieren — HIGH  ✅ ERLEDIGT (19.06.2026)
**Umgesetzt:** `db.py` + `scrapers/verifier.py` gelöscht. Scraper schreiben nur noch nach
`db_raw` (Queue); der Feed nutzt die `raw_id` als ID. Die Feed-Modal-Routen
(`/api/lead/<id>/status|email|mockup|competition|website`) lösen `raw_id → db_evaluated`
auf (eindeutig — die Rangliste nutzt eigene Eval-Routen). Dashboard-Zähler kommen aus
`db_raw` (Funde/Quellen/Bundesländer) + `db_evaluated` (Hot/Warm/Cold). `db_evaluated` ist
der kanonische Lead-Store. Verifiziert per Integrationstest (Stats, Status-Persistenz,
Konkurrenz, 404) + 13 grüne Unit-Tests. **Live-Feed-Klick-Test im laufenden Scraping steht
noch aus** (Routen sind grün, aber die End-to-End-UX im Browser nicht von mir testbar).

### (historisch) ursprüngliche Beschreibung
Jeder Scraper schreibt doppelt (db.insert + db_raw.insert_raw). **Bewusst NICHT blind entfernt**,
weil leads.db tiefer verdrahtet ist als es scheint:
- Die Lead-Tab-Modal-Routen `/api/lead/<id>/status|email|mockup|competition` arbeiten mit
  **DB1-leads.db-IDs** (kommen aus dem Live-Feed). Ohne Rewiring auf db_raw/DB2 brechen sie.
- `db.get_stats()` liefert `lead_typ`-basierte Zahlen (Hot/Warm/Cold) aus dem Scraper-Heuristik-
  Score; `db_raw` hat kein `lead_typ` → andere Statistik-Semantik.
→ Sicherer Pfad (eigener, interaktiv getesteter Schritt): Lead-Tab-Modal auf db_raw/DB2 umstellen,
`db.get_stats()` → `db_raw.get_raw_stats()`, dann db.insert aus den Scrapern entfernen, db.py löschen.
Erfordert manuelles Testen des Leads-Tabs (Live-Scraping) — nicht „blind" machbar.

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
## Status

**Umgesetzt + getestet (Durchgang 1 — Features):** Marktplatz-Filter (P4), schreibender
Lead-Zugriff (P2: leads_update), Akquise-Anreicherung (P1: enrich_business), Observability
(P6: metrics + /api/metrics + is_error), Konversions-Tracking + Job-Poll (P3/P5), dauerhafter
Sprach-Gesprächsmodus (VAD), Shop-Workflow (Skill → neuer Ordner → Redesign → git push).

**Umgesetzt + getestet (Durchgang 2 — Architektur):**
- ✅ #1 Kanonischer `leadkey.py` (eine Definition statt drei; Format unverändert).
- ✅ #3 Worker-Health: pro-Worker `alive` in `/api/status` (deckt still gestorbene Worker auf).
- ✅ #4 `busy_timeout=5000` in allen DB-Connections (kein sofortiges „locked").
- ✅ #5 `claim_next_pending` crash-fest: `claimed_at` + 2-Min-Watchdog + Anti-Starvation-Tiebreaker.
- ✅ #6 Erste **Tests** (`tests/test_core.py`, 9 grün) — leadkey, quality, extract_json, _domain, Sicherheit.
- ✅ #7 SSE-Stats auf 1×/Sek gecacht (kein N+1 mehr pro Lead-Event).
- ✅ #8 Claude-History clientseitig auf 40 Einträge begrenzt.

**Offen:** nur noch #2 (`leads.db` eliminieren) — siehe Begründung oben (eigener, interaktiv
getesteter Schritt, nicht blind).
