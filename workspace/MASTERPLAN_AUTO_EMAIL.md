# JARVIS LeadHunter — Masterplan: „Auto-Email-Send-Ready"

> Ziel-Definition (Sir, 2026-06): Das System so weit bringen, dass **automatisches
> E-Mail-Versenden** sauber aufgesetzt werden kann. Dafür müssen vier Säulen stehen:
> **(1)** identische Leads auf allen PCs **und** der Railway-Leadsite,
> **(2)** maximal optimierte Lead-Findung,
> **(3)** echte, belastbare Bewertung + tiefere Info-Findung (wo verdienen wir am meisten **und am sichersten**),
> **(4)** korrekte Anzeige der gefundenen Lead-Bilder als öffenbarer Ordner.
>
> Dieses Dokument ist gleichzeitig der **Ausführungs-Prompt** (Abschnitt 0) und die
> **detaillierte TODO-Liste** (Abschnitte 1–6) mit Akzeptanzkriterien.

---

## 0. Der Ausführungs-Prompt (Selbstauftrag)

> **Rolle:** Du bist der leitende Engineer von JARVIS LeadHunter — einem deutschen
> B2B-Lead-Generator (Flask + SQLite + Ollama-Evaluator + Supabase-Sync).
>
> **Auftrag:** Bringe das System „auto-email-send-ready". Arbeite die TODO-Säulen 1–6
> vollständig ab. Halte dich an **diese Gesetze**:
>
> 1. **Funktion vor Design.** Keine bestehende Funktion darf brechen. Nach jeder
>    Python-Änderung `python -m py_compile <datei>` ausführen. Vor jedem Edit die
>    Datei lesen.
> 2. **Additiv statt destruktiv.** Neue Felder = neue DB-Spalten via `migrate()`
>    (idempotent), niemals bestehende Spalten umbenennen/löschen. `lead_key`-Dedup
>    (`md5(name|stadt)`) bleibt unangetastet und in `db_evaluated` **und** `cloud_sync`
>    synchron.
> 3. **Deutsch im Code.** Variablen, Spalten, Logs, Kommentare bleiben deutsch.
> 4. **Keine schweren Deps.** urllib statt requests im Kern, ctypes/subprocess für
>    System, kein psutil. Stil beibehalten.
> 5. **Ollama bleibt optional.** Jede KI-Verfeinerung muss einen deterministischen
>    Fallback haben — fällt Ollama aus, bleibt das Ergebnis gültig.
> 6. **Sicherheit.** `.env` nie committen. `SUPABASE_SERVICE_KEY` / SMTP-Passwörter
>    nie loggen, nie ins Frontend. HTTPS/TLS erzwingen.
> 7. **Design:** Frontend mit Skill `design-pro` auf JARVIS-/Iron-Man-HUD-Niveau heben,
>    ohne IDs/Funktions-Hooks (`onclick`, `id`) zu verändern, die `app.js`/`ranking.js`/
>    `graph.js` brauchen.
>
> **Reihenfolge:** Säule 3 (Bewertung) + Säule 4 (Bilder) zuerst — sie liefern die
> Datenqualität, auf der Auto-Mail steht. Dann Säule 1 (Sync), Säule 2 (Findung),
> Säule 5 (Design), Säule 6 (Auto-Mail-Gerüst). Jeden abgeschlossenen Punkt im
> Live-Feed protokollieren.

---

## 1. Säule — Multi-PC- & Railway-Sync (identische Leads überall)

**Ist-Zustand:** `cloud_sync.py` pusht jeden bewerteten Lead sofort nach Supabase
(`jarvis_leads`, Dedup über `lead_key`) und zieht beim **App-Start** einmal alle remote
Leads in den lokalen Cache (`pull_and_cache`). Batch-Push alle 10 Min als Fallback.

**Lücke:** Der Pull passiert **nur beim Start**. Läuft PC-A weiter, sieht PC-B neue
Leads von PC-A erst nach Neustart. Die Railway-Seite muss direkt aus Supabase lesen.

### TODO 1.1 — Periodischer Pull (bidirektional)
- [ ] In `cloud_sync.py` einen **Pull-Loop** ergänzen (z. B. alle 5 Min `pull_and_cache()`),
      parallel zum bestehenden Push-Loop. Idempotent, via `lead_key` dedupliziert.
- [ ] `pull_and_cache` so erweitern, dass es nicht nur *neue*, sondern auch *aktualisierte*
      Leads (höherer Score / neuer Status) übernimmt — Konfliktregel: **neueste `bewertet_am`
      gewinnt**, bei Status-Feld **„weiter im Funnel" gewinnt** (verkauft > termin > kontaktiert > neu > tot).
- **Akzeptanz:** PC-A findet Lead X → spätestens nach 5 Min ist X auf PC-B sichtbar, ohne Neustart.

### TODO 1.2 — Status-Sync (beidseitig)
- [ ] `update_status` (DB2) muss den Status auch nach Supabase pushen (aktuell nur lokal).
- [ ] Beim Pull Status-Feld mit der o. g. Funnel-Regel mergen.
- **Akzeptanz:** Markiere Lead auf PC-A als „kontaktiert" → erscheint auf PC-B + Railway als „kontaktiert".

### TODO 1.3 — Railway-Leadsite an Supabase
- [ ] Prüfen/dokumentieren, wie die Railway-Seite Daten bezieht. Soll-Architektur:
      Railway liest **read-only** aus Supabase (anon-Key, RLS: nur SELECT auf `jarvis_leads`).
- [ ] Sicherstellen, dass alle für die Anzeige nötigen Spalten in `_SYNC_COLS` stehen
      (inkl. der neuen Felder aus Säule 3 + 4: `sicherheit`, `erwartungswert_euro`, `foto_urls`).
- **Akzeptanz:** Railway zeigt dieselbe Rangliste wie die lokalen Dashboards.

### TODO 1.4 — Supabase-Schema-Migration
- [ ] SQL-Migration für die neuen Spalten in `jarvis_leads` (siehe Säule 3/4) bereitstellen
      (`workspace/sql/`), via Supabase-MCP oder Dashboard anwendbar.
- **Akzeptanz:** Upsert mit neuen Feldern wirft keinen 400/HTTP-Fehler im CloudSync-Log.

---

## 2. Säule — Lead-Findung maximal optimieren

**Ist:** 6 Worker (Maps, GelbeSeiten, DasÖrtliche, 11880, golocal, AI) teilen ~40.000
Stadt×Branche-Combos disjunkt. Globaler Such-Rate-Limiter (1,3 s) + Engine-Rotation in
`_http.py`. Qualitätsfilter `is_real_business`. Dedup über `schluessel`.

### TODO 2.1 — Combo-Priorisierung statt reinem Zufall
- [ ] Combos nicht nur shuffeln, sondern **High-Value-Branchen** (`regions.HIGH_VALUE`) +
      große Städte zuerst gewichten → früh viele Hot-Leads. Restliche Combos danach.
- **Akzeptanz:** In den ersten 30 Min messbar höherer Hot-Anteil als bei reinem Shuffle.

### TODO 2.2 — Dedup & Abdeckung
- [ ] Cross-Source-Dedup härten: gleicher Betrieb aus Maps + GelbeSeiten darf nur **einmal**
      in DB1 landen (Key über normalisierten Namen + Stadt + ggf. Telefon).
- [ ] „Already scraped"-Gedächtnis: Combos, die zuletzt 0 neue Leads brachten, seltener
      erneut anfahren (Cooldown), damit Worker nicht im Kreis scrapen.
- **Akzeptanz:** Anteil doppelter `schluessel`-Kollisionen sinkt; mehr unique Leads/Stunde.

### TODO 2.3 — Resilienz gegen Blocking
- [ ] Pro Engine Backoff/Disable bei wiederholtem Block; Worker laufen weiter über die
      übrigen Engines. Maps-Browser-Restart bereits vorhanden — Retry-Zähler ergänzen.
- **Akzeptanz:** Block einer Quelle stoppt nicht die Gesamtfindung.

### TODO 2.4 — Mehr Quellen (optional, modular)
- [ ] Branchenspezifische Verzeichnisse (z. B. Handwerkskammer-Suchen, WLW) als weitere
      Scraper-Module nach gleichem `run_continuous(combos, on_lead, stop_event)`-Muster.
- **Akzeptanz:** Neue Quelle integriert sich ohne Controller-Umbau (nur `_spawn`-Zeile).

---

## 3. Säule — Echte Bewertung: „wo am meisten UND am sichersten Geld" ★ Kern

**Ist:** `score_writer.evaluate` baut deterministischen Bedarfs-Score (0–100) aus
Website-Situation, Branche, Erreichbarkeit, Aktivität, Bilder, Firmengröße; Ollama
korrigiert ±15 und liefert Texte/Potenzial. `lead_typ` = Hot/Warm/Cold nach Score.

**Kernproblem:** Der Score misst nur **Bedarf** (wie sehr braucht der Betrieb Webdesign).
Er sagt **nichts über Sicherheit** (wie sicher ist die Datenlage / Abschlusswahrscheinlichkeit)
und nicht über den **Erwartungswert** (Potenzial × Abschlusswahrscheinlichkeit). „Am
sichersten Geld verdienen" braucht beide neuen Dimensionen.

### TODO 3.1 — Neue Kennzahl „Sicherheit" (Confidence 0–100)
- [ ] In `score_writer` aus harten Signalen berechnen (deterministisch):
      - **Erreichbarkeit:** E-Mail gefunden (+stark), Telefon verifiziert (+).
      - **Datenvollständigkeit:** Website eindeutig zugeordnet, Adresse, Branche bekannt.
      - **Zahler-Wahrscheinlichkeit:** Privatzahler/KMU (+), Kette/Konzern (−−).
      - **Verifikationsgüte:** `verifiziert=1`, mehrere Quellen bestätigen den Betrieb.
- [ ] Neue DB2-Spalte `sicherheit INTEGER DEFAULT 0` (via `_NEW_COLUMNS`/`migrate`).
- **Akzeptanz:** Ein Lead ohne E-Mail/Telefon hat niedrige Sicherheit, selbst bei hohem Bedarf.

### TODO 3.2 — Erwartungswert (€) statt nur Potenzial
- [ ] `erwartungswert_euro = round(potenzial_euro × abschluss_wahrscheinlichkeit)`,
      wobei Abschlusswahrscheinlichkeit aus `sicherheit` + Bedarf abgeleitet wird.
- [ ] Neue DB2-Spalte `erwartungswert_euro INTEGER DEFAULT 0`.
- **Akzeptanz:** Rangliste kann nach Erwartungswert sortiert werden → „sicherstes Geld zuerst".

### TODO 3.3 — Kombi-Ranking & Lead-Typ schärfen
- [ ] `lead_typ` Hot nur, wenn Bedarf **und** Sicherheit hoch (z. B. score≥72 **und** sicherheit≥55).
      Hoher Bedarf bei niedriger Sicherheit → „Warm/Unsicher".
- [ ] Optionaler kombinierter Sortier-Score `gesamt = f(score, sicherheit, erwartungswert)`
      für die Default-Sortierung der Rangliste.
- **Akzeptanz:** Top-10 enthält keine „Hot"-Leads ohne Kontaktweg.

### TODO 3.4 — Tiefere Info-Findung (Anreicherung)
- [ ] `web_analyst`: zusätzlich **mehrere** E-Mails + Ansprechpartner aus Impressum/Kontakt
      ziehen (Name, Rolle), nicht nur die erste Adresse.
- [ ] Inhaber-/Geschäftsführer-Erkennung aus Impressum (für persönliche Anrede in der Mail).
- [ ] `social_researcher`: Aktivitäts-Signal (letzter Post / Aktualität) als weiches Signal.
- [ ] Neue Felder: `ansprechpartner TEXT`, `email_alle TEXT(JSON)`.
- **Akzeptanz:** Hot-Leads haben i. d. R. Ansprechpartner + mind. eine valide E-Mail.

### TODO 3.5 — Score-Kalibrierung „für uns"
- [ ] Gewichte als benannte Konstanten oben in `score_writer` bündeln (`GEWICHTE = {...}`),
      damit Sir sie an die eigene Verkaufsrealität anpassen kann (z. B. „E-Mail wichtiger
      als Bilder"). Dokumentieren, welcher Wert was bewirkt.
- **Akzeptanz:** Eine Gewichts-Änderung an einer Stelle verschiebt die Rangliste nachvollziehbar.

---

## 4. Säule — Lead-Bilder als öffenbarer Ordner ★

**Ist:** Pro Lead wird **eine** `foto_url` gespeichert (Maps-Hero **oder** Website-og:image).
Modal zeigt dieses eine Bild oben. Kein Mehrbild-Ordner.

### TODO 4.1 — Mehrere Bilder sammeln
- [ ] `maps.py`: aus dem Maps-Foto-Karussell **mehrere** Bild-URLs ziehen (nicht nur Hero),
      bis ~8 Stück.
- [ ] `web_analyst`: zusätzlich Bild-`<img>`/`srcset`/`og:image` der Website sammeln,
      absolut machen, Tracking-Pixel/Logos heuristisch aussortieren.
- [ ] Speichern als JSON-Liste `foto_urls TEXT` (neue DB1+DB2-Spalte). `foto_url`
      (Einzel) bleibt als Vorschau-Cover erhalten (Abwärtskompatibilität).
- **Akzeptanz:** Hot-Leads mit Online-Präsenz haben mehrere Bild-URLs.

### TODO 4.2 — Optionaler lokaler Bild-Cache (Ordner)
- [ ] Beim Bewerten Bilder optional nach `workspace/media/leads/<lead_key>/` herunterladen
      (Flag `JARVIS_CACHE_LEAD_IMAGES`, Default aus — spart Platz/Bandbreite). Route
      `/workspace/media/leads/<lead_key>/<file>` zum Ausliefern (Path-Traversal-sicher).
- **Akzeptanz:** Bei aktivem Flag liegt pro Lead ein echter Bilder-Ordner auf der Platte.

### TODO 4.3 — Frontend: Galerie im Modal
- [ ] In `ranking.js openRankDetail`: aus `foto_urls` eine **klickbare Bild-Galerie**
      rendern (Thumbnails → Klick öffnet Lightbox/größer). Sektion „Bilder des Betriebs".
      Lazy-Loading, `onerror`-Ausblenden defekter URLs.
- [ ] Einstiegspunkt: Lead anklicken → Modal → Sektion „Bilder" → Bild anklicken → groß.
- **Akzeptanz:** Lead anklicken zeigt den Bilder-Ordner; einzelne Bilder öffnen sich groß.

### TODO 4.4 — Sync der Bilder
- [ ] `foto_urls` in `_SYNC_COLS` aufnehmen → Bilder erscheinen auch auf anderen PCs + Railway.
- **Akzeptanz:** Galerie identisch auf allen Clients.

---

## 5. Säule — Design: JARVIS-/Iron-Man-HUD (Skill `design-pro`)

**Ist:** Funktionsfähiges Dark-Dashboard (Orbitron/Inter/JetBrains Mono, Three.js-Sphere,
D3-Graph, Rangliste). Wirkt teils generisch.

### TODO 5.1 — Visuelles System härten (ohne Funktionsbruch)
- [ ] `design-pro` anwenden: kohärente Farb-Token (Arc-Reactor-Cyan, Gold-Akzent, tiefe
      Blautöne), Typo-Skala, Spacing-Raster, Glassmorphismus/Glow sparsam & konsistent.
- [ ] HUD-Details: animierte Arc-Reactor-Brand, feine Grid/Scanline-Texturen, Status-LEDs,
      Mikro-Interaktionen (Hover/Active), saubere Tabellen-/Karten-Hierarchie.
- [ ] **Keine** `id`/`onclick`/`data-*`-Hooks ändern, die JS braucht. Nur CSS + ggf.
      additive Markup-Hüllen. Nach Umbau alle 5 Tabs + Modal + Log-Drawer testen.
- **Akzeptanz:** Sieht aus „wie aus Tony Starks Labor", alle Buttons/Tabs/Modals funktionieren unverändert.

---

## 6. Säule — Auto-E-Mail-Gerüst (ready-to-arm)

**Ist:** `score_writer` erzeugt `email_entwurf` (Betreff+Text als JSON), `outreach.py`
generiert on-demand Mails. Kein Versand, kein Status, keine Compliance.

> Hinweis: Den **scharfen Auto-Versand** baut Sir final selbst ein — JARVIS macht alles
> *davor* ready (Daten, Entwürfe, Versand-Funktion, Queue, Status, Opt-out). Details +
> Schritt-für-Schritt im separaten **TUTORIAL_AUTO_EMAIL.md**.

### TODO 6.1 — Versand-Modul (deaktiviert per Default)
- [ ] `mailer.py`: SMTP-Versand via `smtplib`/`ssl` (STARTTLS), Konfiguration aus `.env`
      (`SMTP_HOST/PORT/USER/PASS/FROM`). `JARVIS_EMAIL_ENABLED=false` als Sicherheits-Schalter.
- **Akzeptanz:** Test-Mail an eigene Adresse versendbar, wenn Flag an + .env gesetzt.

### TODO 6.2 — Versand-Queue + Status
- [ ] DB2-Felder `email_status` (`entwurf|geplant|gesendet|fehler|geantwortet|opt_out`),
      `email_gesendet_am`, `email_fehler`. Queue analog `media_queue`.
- [ ] Route `/api/lead/<id>/send-email` (manuell, ein Lead) als sichere Vorstufe zum Auto-Versand.
- **Akzeptanz:** Ein Lead lässt sich manuell anmailen; Status wechselt auf „gesendet".

### TODO 6.3 — Compliance-Grundlage
- [ ] Opt-out/Blocklist (`email_opt_out`), Impressums-/B2B-Bezug-Pflicht, Rate-Limit
      (max N Mails/Stunde), Absender-Signatur/Impressum im Footer.
- **Akzeptanz:** Kein Versand an opt-out; Rate-Limit greift.

### TODO 6.4 — Auto-Versand-Hook (Aus-Schalter scharf)
- [ ] Optionaler Loop: nimmt Top-Leads mit `email_status=geplant` + valider E-Mail +
      `sicherheit≥Schwelle` und sendet gedrosselt. **Default aus.**
- **Akzeptanz:** Mit einem Flag + Bestätigung versendet das System eigenständig an die sichersten Leads.

---

## Reihenfolge der Ausführung (Definition of Done)

1. **Bewertung** (Säule 3) — Sicherheit + Erwartungswert + tiefere Infos.
2. **Bilder** (Säule 4) — Mehrbild-Sammlung + Galerie-Modal.
3. **Sync** (Säule 1) — periodischer Pull + Status-Sync + neue Felder in `_SYNC_COLS` + Supabase-Migration.
4. **Findung** (Säule 2) — Priorisierung + Dedup + Resilienz.
5. **Design** (Säule 5) — `design-pro`-Politur ohne Funktionsbruch.
6. **Auto-Mail** (Säule 6) — Mailer + Queue + Status + Compliance (deaktiviert), Tutorial.

**Global Done, wenn:** Auf zwei PCs + Railway identische Leads; Rangliste sortiert nach
echtem Erwartungswert mit Sicherheits-Kennzahl; Lead-Bilder als öffenbare Galerie; Design
auf HUD-Niveau; `mailer.py`+Queue+Status stehen, sodass Sir nur noch `JARVIS_EMAIL_ENABLED=true`
setzen + Schwellen wählen muss.
