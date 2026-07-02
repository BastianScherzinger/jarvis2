# Code-Audit & Log-Analyse — 2026-07-02

Grundlage: Dauertest-Logs `log.txt` (28.–29. Jun) und `Downloads/log2-txt.txt` (01. Jul),
plus Vollscan aller 101 Projekt-Python-Dateien.

---

## A. Log-Analyse — was der Dauertest zeigt

**Positiv (Pipeline trägt):**
- Seiten werden gebaut, per Claude-`taste`-Skill poliert, live auf Railway deployt und
  per Discord freigegeben (Versand 12:00). Beispiele der Nacht: Konrad Bühler, Siems
  Nils Elger, Horst Bittner, Oskar Knab.
- CloudSync (Supabase) läuft stabil im 5-Min-Takt hoch/runter (6060 lokal / 6078 gesamt).
- **Erste echte Kundenantwort eingegangen** → Home-Seite entsprechend aktualisiert.

**Auffälligkeiten (im Log messbar):**
1. **LiveWatch-Endlosschleife (ECHTER BUG — gefixt).** Dieselben ~5 Seiten
   (`Bauer Konrad GmbH`, `Gabriele Hornung`, `ZAR …`, `Stefan Richter …`,
   `Gemeinschaftspraxis Schnorbach`) werden die **ganze Nacht alle 10 Min** neu deployt
   und kommen nie live. In *beiden* Logs (28.6. + 1.7.) identisch → dauerhaft kaputte
   Seiten (Railway-Build schlägt reproduzierbar fehl), aber LiveWatch hatte **kein
   Fehler-Limit** und hämmerte unbegrenzt weiter.
2. **Claude-Session-Limit ~00:53** („Session-Limit nach 0 Wartezyklen — pausiert").
   Danach baute der Night-Builder nichts mehr. `_LIMIT_RETRIES=0` ist **beabsichtigt**
   (der Auto-Builder plant den Neustart per Cooldown-Timer, Reset ~5 Uhr) — kein Bug,
   aber siehe C-2 zur Verifikation.
3. **Deploy-Rettung als No-Op-Schleife.** Seiten mit 0 offenen Stufen, die nicht live
   sind, lassen `makeover_existing` je Runde komplett durchlaufen (Log: „KOMPLETT … 0.0s"),
   nur um danach erneut zu deployen — bis `_RESCUE_MAX=4`. Ist gekappt, aber unnötig teuer.
4. **Sehr hohe Polling-Frequenz.** `/api/websites/grouped` (~alle 2 s) und
   `/api/auto-build/status` (~alle 4 s) erzeugen 95 % des Log-Volumens. Kein Fehler,
   aber Log-Rauschen + unnötige Last.

---

## B. Statischer Code-Scan — Ergebnis

| Prüfung | Ergebnis |
|---|---|
| `py_compile` über 101 Dateien | **0 Syntaxfehler** |
| Mutable Default Arguments (`def f(x=[])`) | **0** im Produktivcode |
| Bare `except:` | nur 3× in `agents/tools.py` (Alt-JARVIS, nicht im LeadHunter-Pfad) |
| Kern-Logik (auto_builder / website_builder / overnight_makeover / claude_limit) | sauber, gut gekapselt (`except Exception`, Best-Effort-Muster) |

Die Codebasis ist in gutem Zustand. Der einzige produktionsrelevante Defekt war A-1.

---

## C. Fixes & Empfehlungen

### C-1 — LiveWatch-Fehlerlimit + Backoff  ✅ GEFIXT (`auto_builder.py`)
- Neuer Zähler `_live_fail_count[folder]` + `_live_gaveup`-Set.
- Nach `JARVIS_LIVE_MAX_FAILS` (Default **3**) erfolglosen Re-Deploys gilt eine Seite als
  dauerhaft kaputt → Backoff auf `JARVIS_LIVE_GIVEUP_COOLDOWN` (Default **4 h**) statt 10 Min.
  Einmalige WARN „…weiterhin tot — Railway-Build-Log prüfen".
- Zähler wird zurückgesetzt, sobald die Seite wieder live ist, sowie bei Tageswechsel
  (falls sich die Infrastruktur über Nacht erholt).
- Effekt: keine endlosen Railway-Builds mehr für tote Seiten; Log wird ruhig.

### C-2 — Session-Limit-Neustart verifizieren  ⏳ OFFEN (Beobachtung)
Prüfen, ob der Night-Builder nach dem 5-Uhr-Reset tatsächlich automatisch weiterläuft
(`_schedule_restart` → `start(_resume=True)`). Im Log endet die Nacht vor 5 Uhr, daher
nicht bestätigt. Nächster Dauertest: Log über 5 Uhr hinaus prüfen.

### C-3 — Deploy-Rettung ohne No-Op-Makeover  ⏳ EMPFEHLUNG (nicht geändert)
Für Seiten mit 0 offenen Stufen sollte die Rettung direkt `deploy_existing` aufrufen statt
`makeover_existing` komplett zu durchlaufen. Bewusst nicht angefasst (gekappt + Risiko an
der funktionierenden Ziel-Auswahl). Nur umsetzen, wenn C-1 das Problem nicht schon entschärft.

### C-4 — Polling entschärfen  ⏳ EMPFEHLUNG (nicht geändert)
Frontend-Poll-Intervalle für `websites/grouped` und `auto-build/status` erhöhen (z.B. 5–10 s)
oder auf SSE umstellen. Rein kosmetisch/Last, kein Funktionsfehler.

---

## D. Geänderte Dateien (Runde 1)
- `auto_builder.py` — LiveWatch-Fehlerlimit + Backoff + Tages-Reset (C-1).
- `templates/index.html` — Testphasen-Ergebnis + erste Kundenantwort, Schritt 7 aktualisiert.
- `static/css/style.css` — Styling für den Ergebnis-Streifen (`.tp-result`).

---

## E. Runde 2 — Logs entrümpeln + Session-Limit-Lernen (auf Sirs Wunsch)

### E-1 — HTTP-Log-Spam gefiltert  ✅ (`app.py`)
Werkzeug-Log-Filter: **erfolgreiche** (200/304) Polling-Requests auf Status-Endpunkte
(`/api/status`, `/api/auto-build/status`, `/api/websites/grouped`, `/api/top`, `/api/logs` …)
werden verworfen — **Fehler (4xx/5xx) und alle anderen Requests bleiben sichtbar**.
Das war ~95 % des Log-Volumens. Abschaltbar via `JARVIS_QUIET_ACCESS_LOG=0`.

### E-2 — Schönere Log-Anzeige  ✅ (`logger.py`)
Worker-Name auf feste Spaltenbreite (13) — Meldungen stehen sauber untereinander statt zu zerfransen.

### E-3 — Bessere Debug-Zeilen an Problemstellen  ✅ (`auto_builder.py`, `overnight_makeover.py`)
- LiveWatch loggt Zustandswechsel **explizit**: „wieder live ✓" nach N Re-Deploys / „offline geworden".
  Re-Deploy-Fehler enthalten jetzt URL + Fehlertext.
- Am Session-Limit: DEBUG-Zeile mit gelerntem Token-Fenster, Beobachtungszahl, Retry-Quelle und
  exakter nächster Versuchszeit.

### E-4 — Session-Limit-Lernen verbessert  ✅ (`claude_limit.py`)
- **Reset-Zeit aus der Meldung**: „resets 5am (Europe/Vienna)" wird geparst → der Retry wird
  EXAKT auf den Reset gelegt (statt blind 4 h). Fallback bleibt der gelernte Cooldown.
- **Robustes Lernen**: Median der letzten 10 Limit-Beobachtungen statt jumpiger EMA, geklemmt auf
  200k–30M Token (Ausreißer-Schutz). EMA bleibt als Sekundär-/Trendwert erhalten.
- Neue Statusfelder: `reset_at`, `retry_source`, `obs_count`, `learned_ema`, `typical_minutes`.
- Frontend-Banner zeigt jetzt die **exakte Uhrzeit** („läuft um 05:00 Uhr weiter").

> Damit ist auch **C-2** entschärft: der Neustart hängt nicht mehr an einem blinden 4-h-Timer,
> sondern trifft den echten Reset-Zeitpunkt.

### Geänderte Dateien (Runde 2)
- `app.py` — Werkzeug-Access-Log-Filter (E-1).
- `logger.py` — feste Worker-Spaltenbreite (E-2).
- `auto_builder.py` — LiveWatch-Zustandslogs + URL im Fehler (E-3).
- `overnight_makeover.py` — Reset-Hinweis an `claude_limit.mark` + Debug-Zeile (E-3/E-4).
- `claude_limit.py` — Reset-Parsing, Median-Lernen, neue Statusfelder (E-4).
- `static/js/app.js` — exakte Reset-Uhrzeit im Limit-Banner (E-4).
