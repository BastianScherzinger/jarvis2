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

---

## F. Runde 3 — restliche offene Punkte abgeschlossen

### F-1 — Deploy-Rettung ohne No-Op-Makeover  ✅ (`auto_builder.py`)  [war C-3]
Reine Deploy-Rettung (Seite fertig, 0 offene Stufen, nur nicht live) ruft jetzt **direkt
`deploy_existing`** statt die ganze Makeover-Pipeline für einen No-Op hochzufahren. Spart
Claude/Ollama-Overhead und beseitigt das „KOMPLETT 0.0s"-Log-Rauschen.

### F-2 — Frontend-Polling gedrosselt  ✅  [war C-4]
- `websites.js`: `/api/websites/grouped` 2,5 s → **7 s** (seiten-gated).
- `app.js`: `/api/auto-build/status` 3 s → **6 s**; Log-Konsole 2 s → **5 s**.
- `ranking.js`: Rangliste 3 s → **7 s** (tab-gated).
Zusammen mit dem Access-Log-Filter (E-1) ist das Log jetzt ruhig und lesbar.

### F-3 — Session-Reset über 5 Uhr bestätigbar  ✅ (`auto_builder.py`)  [war C-2]
Wiederaufnahme-Kette verifiziert: `_claude_limited` → `_handle_exhaustion` →
`_schedule_restart(seconds_to_retry())` → Timer → `start(_resume=True)`. Da `seconds_to_retry`
nun die **exakte Reset-Zeit** (E-4) liefert, landet der Neustart genau auf dem Reset.
Log jetzt eindeutig: Pause meldet **„pausiert bis HH:MM Uhr"**, Wiederaufnahme meldet als
SUCCESS **„Reset-Zeit erreicht (HH:MM) — setze fort"**. Der nächste Dauertest über 5 Uhr
hinaus zeigt beide Zeilen sauber → Reset bestätigt. (Reines Beobachten, kein Code mehr offen.)

### Geänderte Dateien (Runde 3)
- `auto_builder.py` — Deploy-Rettung direkt (F-1), klare Pause/Resume-Logs mit Uhrzeit (F-3).
- `static/js/websites.js`, `static/js/app.js`, `static/js/ranking.js` — Poll-Intervalle gedrosselt (F-2).

**Status: alle Punkte aus A–F abgeschlossen. Keine offenen Code-Punkte mehr —
verbleibt nur die Laufzeit-Beobachtung des nächsten Nachtlaufs (F-3).**

---

## G. Runde 4 — 12-Uhr-Versand-Stopp + Gmail-Antwort-Analyse

### G-1 — Warum der 12-Uhr-Versand „nach 2 Tagen" aufhörte  ✅ GEFIXT (`discord_bot.py`)
**Root Cause:** Der Tagesversand ist ein discord.py `tasks.loop(time=12:00)`. Der Loop-Rumpf rief
`send_approved_now()` **ohne `try/except`** auf. In discord.py **stoppt eine unbehandelte Exception
eine `tasks.loop` DAUERHAFT** — es gab weder `error`- noch Neustart-Handler. Ein einziger
schiefgelaufener Versand (SMTP-Aussetzer, Netz-Blip, ein defekter Review) killte den Loop für
immer → ab dann kam nie wieder etwas um 12 Uhr. Zusätzlich hing der ganze Versand allein an der
Discord-Verbindung.

**Fix:**
- `_noon_loop`-Rumpf vollständig gekapselt (kann nicht mehr sterben); Tages-Latch erst **nach**
  erfolgreichem Versand (ein Crash verbrennt den Tag nicht mehr).
- `@_noon_loop.before_loop` (`wait_until_ready`) + `@_noon_loop.error` mit `restart()`.
- **Neuer `NoonWatchdog`-Thread**, unabhängig von Discord: prüft jede Minute, ob die Versandstunde
  erreicht und heute noch nichts raus ist → holt den Versand nach (Mailer hängt nicht an Discord).
  Fängt auch „PC war um 12 Uhr aus" ab (Nachversand, sobald die App an dem Tag läuft).

### G-2 — Gmail-Antwort-Analyse mit lokaler KI  ✅ NEU (`inbox_reader.py`)
Schritt 7 automatisiert: liest per **IMAP (read-only)** die Antworten auf die Angebots-Mails,
ordnet sie über die Absenderadresse dem versendeten Angebot zu und lässt sie von **Ollama lokal**
einordnen (Interesse/Absage/Rückfrage/Preisfrage + Zusammenfassung/Dringlichkeit/Empfehlung).
Ergebnisse → `data/replies.json`, Aktivitäts-Feed (Home) und Discord-Ping bei heißen Leads.
- Opt-in: `JARVIS_INBOX_ENABLED=true` + IMAP-Zugang (Gmail-App-Passwort). Standard aus.
- Read-only (`BODY.PEEK`, `select(readonly=True)`) — nichts wird gelöscht/verschickt/beantwortet.
- 100 % lokal → keine Cloud-Kosten. MCP/Internet-Anreicherung ist als nächster Schritt andockbar
  (Firma recherchieren + Antwort-Entwurf) — die Analyse-Pipeline ist dafür vorbereitet.
- API: `GET /api/inbox/replies`, `POST /api/inbox/check`. Start beim Boot in `app.py`.

### Geänderte/neue Dateien (Runde 4)
- `discord_bot.py` — 12-Uhr-Loop gehärtet + NoonWatchdog (G-1).
- `inbox_reader.py` (neu) — IMAP-Antwort-Analyse mit Ollama (G-2).
- `app.py` — `inbox_reader.start()` beim Boot + `/api/inbox/*`-Endpunkte (G-2).
- `.env.example` — IMAP-/Inbox-Variablen dokumentiert (G-2).
- `templates/index.html` — Schritt 7 um die Antwort-Analyse ergänzt (G-2).
