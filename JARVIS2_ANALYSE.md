# JARVIS2 — Vollständige technische Systemanalyse

> **Zweck dieses Dokuments:** Eine maximal genaue, ausführliche Referenz für eine andere KI
> (oder einen neuen Entwickler), damit sie/er das komplette Projekt versteht — Produkt,
> Architektur, jede Pipeline-Stufe, Technologien, Design, und den EHRLICHEN Ist-Zustand
> inklusive bekannter Probleme. Erstellt am **05.07.2026** durch eine tiefe Code-Analyse
> (4 parallele Recherche-Durchläufe + eigene Verifikation der wichtigsten Befunde — keine
> Vermutungen, jede Aussage ist gegen den tatsächlichen Code geprüft).
>
> **Wichtiger Hinweis zur Verlässlichkeit:** Dieses Dokument ist eine Momentaufnahme. Der Code
> entwickelt sich weiter (autonomer Night-Builder läuft z.T. permanent). Vor jeder Aktion auf
> Basis einer hier genannten Zeile/Funktion: kurz gegenprüfen, ob sie noch existiert.

---

## 0. Produktübersicht — Was JARVIS2 ist

**JARVIS2 ("JARVIS LeadHunter")** ist ein selbstgebautes, vollautonomes **B2B-Lead-Generierungs-
und Akquise-System** mit einem Iron-Man-HUD-Dashboard als Bedienoberfläche. Es ist KEIN Chatbot-
Demo, sondern eine laufende Geschäfts-Pipeline, die eigenständig:

1. **Firmen ohne (gute) Website findet** — automatisiertes Scraping deutscher/österreichischer
   Branchenverzeichnisse und Google Maps, rund um die Uhr.
2. **Jeden Fund bewertet** — lokale KI (Ollama) + Heuristiken schätzen Score, "Sicherheit"
   (Vertrauenswürdigkeit der Daten) und Erwartungswert in €.
3. **Für die besten Leads automatisch eine fertige Werbe-Website baut** — Text, Design, Hero-
   Bild, Kostenrechner, Impressum/Datenschutz — und sie live auf Railway deployt.
4. **Die Seite per Claude-Code-CLI feinschleift** ("Makeover") — damit sie nicht wie eine
   08/15-Vorlage aussieht.
5. **Sie sich selbst freigeben lässt** (Discord-Voting-Gate) und dann automatisch per E-Mail
   an den echten Betrieb schickt.
6. **Antworten liest und kategorisiert** (read-only IMAP + lokale KI) und meldet sie.
7. Nebenbei: ein **Werbevideo-Generator** (Website-URL → 9:16-TikTok-Ad), ein **Bild/Video-
   Medien-Studio**, ein **Datenpakete-Verkauf** (rohe Firmendaten als CSV/Excel) und ein
   **werkzeugfähiger Claude-Chat-Tab**, über den der Nutzer ("Sir") das ganze System auch
   manuell/gesprächsweise steuern kann.

**Geschäftsmodell:** Kostenlose Demo-Website als Türöffner, bei Interesse ein bezahltes Paket
(300 € / 450 € / 600 €, siehe Preissystem). Betreiber ist ein Einzelentwickler (Bastian,
angesprochen als "Sir"), das System läuft überwiegend autonom über Nacht ("Night-Builder").

**Ehrlicher Reifegrad (Stand des Projekts, aus `workspace/GELD_WORKFLOW.md`):** Schritte 1–5 und
8 sind fertig und laufen produktiv. Schritt 6 (Versand) ist funktional fertig, aber Zustellbarkeit
(eigene Domain/SPF/DKIM/DMARC) und Recht (UWG/DSGVO) sind der eigentliche Flaschenhals zum
Umsatz. Schritt 7 (Abschluss/Zahlung) ist bewusst manuell (kein CRM/Payment-Automat).

---

## 1. Architektur-Überblick

```
┌─────────────────────────────────────────────────────────────────────────┐
│  start.py  →  app.py (Flask, Port 5000, Werkzeug-Dev-Server oder waitress) │
└─────────────────────────────────────────────────────────────────────────┘
        │
        ├── lead_collector.py ─── stündlicher Scheduler ──► scrapers/controller.py
        │                                                        │
        │                                    ┌───────────────────┴───────────────────┐
        │                                    │  6(+1) parallele Scraper-Worker         │
        │                                    │  Maps · GelbeSeit · DasOertliche ·      │
        │                                    │  Elfacht(11880) · Golocal · AI-Worker · │
        │                                    │  (HeroldAT nur für Österreich)          │
        │                                    └───────────────────┬───────────────────┘
        │                                                        ▼
        │                                              data/leads_raw.db (DB1)
        │                                                        │
        │                                    agents/evaluator/pipeline.py (3 Threads)
        │                                    web_analyst → social_researcher → score_writer
        │                                                        ▼
        │                                          data/leads_evaluated.db (DB2, kanonisch)
        │                                                        │  (fire-and-forget Push)
        │                                                        ▼
        │                                              Supabase `jarvis_leads` (Multi-PC-Sync)
        │
        ├── auto_builder.py ─── Night-Builder-Orchestrator (Tageslimit, Session-Fenster)
        │        │
        │        ├─► website_builder.build(lead)   — Vorlage, Content, Hero, GitHub+Railway-Deploy
        │        ├─► overnight_makeover.run_makeover — Claude-Feinschliff (hybrid: lokal + 1 Politur-Stufe)
        │        ├─► discord_bot.submit_for_review   — Voting-Gate (👍/👎)
        │        └─► discord_bot.send_approved_now    — 12-Uhr-Versand (offer_mail + mailer)
        │
        ├── inbox_reader.py ─── liest Antworten (IMAP read-only, alle 10 Min) → Discord
        │
        ├── claude_chat.py + agent_tools.py ─── ECHTER Dashboard-Chat-Agent (Tab "Claude")
        │        (34 Tools: Browser, Maps, Medien, Leads, build_website, Deploy, …)
        │
        ├── media_engine.py / media_queue.py / website_ad_video.py ─── Bild/Video/Werbevideo
        │
        └── leadpackages/ ─── separates Verkaufs-Feature (rohe Firmendaten als CSV/Excel-Bundle)

Frontend: templates/index.html (Sidebar, 11 Tabs) + static/js/*.js + static/css/style.css
```

**Wichtigste Architektur-Korrektur gegenüber der alten Projekt-Doku (`CLAUDE.md`):**
`agents/ceo.py` + `agents/team.py` (10 Spezialisten) + `agents/tools.py` (19 Tools) — ausführlich
in `CLAUDE.md` Abschnitt 5/10/11 beschrieben — sind **NICHT** Teil des laufenden Web-Dashboards.
`app.py` importiert davon nur `agents.outreach`. Dieses Team-System ist nur über das separate,
interaktive CLI-Menü `python main.py` erreichbar (nie von `start.py` automatisch gestartet).
Der echte Dashboard-Chat-Agent ist `claude_chat.py` + `agent_tools.py` — ein einzelner Agent mit
34 Tools, keine Team-Delegation. `CLAUDE.md` wurde am 05.07.2026 entsprechend korrigiert
(inkl. einer weiteren stillen Übernahme aus einem älteren Schwesterprojekt: eine dort
beschriebene "Satelliten-Ansicht" existiert in jarvis2 nicht und wurde entfernt).

---

## 2. Boot-Prozess & Server

**`start.py`** (Launcher, für den Alltagsgebrauch):
1. Erzwingt UTF-8-Konsole (wichtig für Umlaute in Kundendaten/-mails).
2. `_boot_screen()` — Hardware-Erkennung (`hardware.py`), interaktive Wahl eines lokalen
   Ollama-Profils (Enter = Empfehlung), schreibt `JARVIS_EVAL_MODEL`/`JARVIS_AI_MODE=local`.
3. `_install_deps()` — stellt Kern-Pakete + Playwright-Chromium sicher, installiert die
   Claude-Code-CLI (`claude_coder.ensure_cli()`, nötig für das Makeover) und spiegelt Design-
   Skills nach `~/.claude/skills` (`claude_skills.ensure_installed()`).
4. Öffnet den Browser auf `localhost:5000` nach 2,5s.
5. Startet `app.py` als Subprozess, pipet dessen Ausgabe live durch.

**`install.py`** ist der separate, umfassendere Installer (git pull, vollständiges
`pip install -r requirements.txt`, Ollama-Modellwahl mit 6 Hardware-Stufen, optionaler
Media-KI-Stack [torch/diffusers, CUDA-Erkennung via `nvidia-smi`], Discord-/MCP-Setup,
Schlüssel-Sync nach `~/.claude/.env`). Wird **nicht** automatisch von `start.py` aufgerufen —
eigenständig oder über `update.py` genutzt.

**`startup_check.py`** — non-interaktive Selbstdiagnose (Python-Version, DB-Init, Node/Claude-
CLI, Ollama erreichbar, Deploy-Bereitschaft GitHub/Railway, Higgsfield-MCP-Login, ffmpeg,
Playwright+Chromium …). Blockiert den Start **nie**, nur Warnungen.

**Server-Wahl** (`app.py::server_config()`):
```python
host    = JARVIS_HOST (Default "0.0.0.0")
port    = JARVIS_PORT / PORT (Default 5000)
threads = JARVIS_THREADS (Default min(32, max(8, cpu_count()*2)))
prod    = JARVIS_SERVER / JARVIS_PROD in ("1","true","yes","on","prod","production")
```
Bei `prod=True` → `waitress.serve(...)`; sonst Flask-Dev-Server (`app.run(debug=False,
threaded=True)`). **Ohne explizites Flag läuft also standardmäßig der Werkzeug-Dev-Server** —
für ein dauerhaft lokal laufendes Dashboard unkritisch, aber offiziell nicht produktionsreif
(siehe Backlog, Punkt B6).

Beim Modul-Import initialisiert `app.py` sofort `db_raw.init_db()`, `db_evaluated.init_db()`,
`db_websites.init_db()`, `leadpackages_db.init_db()` und registriert das
`leadpackages_routes`-Blueprint.

---

## 3. Lead-Generierung — Scraping

### 3.1 Orchestrierung

**`lead_collector.py`** — der "stündliche Lead-Sammler": Daemon-Thread, gestartet beim
Flask-Boot (`app.py` → `_start_lead_collector()`), Default AN (`JARVIS_LEAD_COLLECTOR=0` zum
Abschalten). Nach 90s Boot-Puffer läuft eine Endlosschleife (60s-Poll), die alle
`JARVIS_LEAD_INTERVAL` Sekunden (Default 3600, min. 300) für `JARVIS_LEAD_RUN_SECONDS`
(Default 600) Scraper + Evaluator startet, dann sauber zweistufig stoppt (erst Scraper, dann
— nach Leerlaufen der Evaluator-Warteschlange — den Evaluator). Ein Discord-Report
(Top-N, Default 3) folgt danach. Zustand übersteht Neustarts (`data/lead_collector_state.json`).

**`scrapers/controller.py`** — der eigentliche Scraper/Evaluator-Manager:
- Startet **6 unabhängige DE+AT-Worker** parallel + **1 zusätzlichen Worker (herold.at)** nur
  für Österreich, wenn AT-Combos vorhanden sind (praktisch immer): Maps, GelbeSeit,
  DasOertliche, Elfacht (11880), Golocal, AI-Worker (lokale KI + Websuche), HeroldAT.
- ~40.000 DE-Kombinationen (1000 Städte × 43 Branchen aus `scrapers/regions.py`), gemischt und
  in 6 nach High-Value-Branche/Stadtgröße priorisierte Chunks verteilt — kein doppeltes Scrapen.
- Startet separat den **Evaluator** (`agents/evaluator/pipeline.run_continuous`, Default
  `min(32, max(4, cpu_count()))` Threads, `JARVIS_EVAL_THREADS` überschreibbar) und den
  **Maps-Enrichment-Pool** (2 dedizierte Playwright-Worker-Threads).
- Ein Watchdog (alle 120s) setzt hängende `running`-Leads zurück.
- UI-Start/Stop: `/api/start` und `/api/stop` in `app.py`.

### 3.2 Die Scraper-Quellen im Detail

| Quelle | Datei | Technik | Länder | Anti-Block |
|---|---|---|---|---|
| Google Maps | `scrapers/maps.py` + `maps_common.py` | Playwright, persistenter Browser, verstecktes `webdriver`-Flag | DE+AT | Browser-Neuaufbau bei Crash |
| Gelbe Seiten | `scrapers/gelbe_seiten.py` | `urllib`+BeautifulSoup | nur DE | `sleep(1.0-1.2s)` |
| Das Örtliche | `scrapers/dasoertliche.py` | wie oben | nur DE | `sleep`, 5s Start-Delay |
| 11880 | `scrapers/elfacht.py` | wie oben | nur DE | `sleep`, 7s Start-Delay |
| golocal | `scrapers/golocal.py` | wie oben | nur DE | `sleep`, 9s Start-Delay |
| herold.at | `scrapers/herold_worker.py` → `leadpackages/sources_herold.py` (`scrapling`+`curl_cffi`) | Browser-Impersonation | **nur AT** | eigenes Rate-Limit 2,5s |
| KI-Recherche | `agents/ai_worker.py` | DuckDuckGo/Mojeek/Bing-Rotation + Ollama-JSON-Extraktion | DE+AT | globales Limit 1,3s |

Jeder Scraper ruft **inline im eigenen Thread** `agents.quality.is_real_business()` +
`agents.scorer.score()` + `db_raw.insert_raw()` auf — keine separate Ingest-Queue.

Gemeinsame Helfer: `scrapers/_http.py` (Ollama-Aufrufe, DDG-Suche mit 3-Engine-Rotation),
`scrapers/website_checker.py` (HTTP-Exists + WHOIS-Alter, mit hartem Thread-Timeout gegen
hängende WHOIS-Server), `scrapers/regions.py` (16 Bundesländer, ~1000 Städte, 43 Branchen).

### 3.3 Dedup — `leadkey.py`

Ein globaler Schlüssel für das ganze System:
```python
def lead_key(name, stadt):
    return md5(f"{name.strip().lower()}|{stadt.strip().lower()}")
```
Genutzt in `db_evaluated.py` (UNIQUE-Index, `INSERT OR REPLACE`), `cloud_sync.py` (Supabase-
Upsert `on_conflict=lead_key`), `leadpackages/sources_herold.py`. **DB1 (`db_raw`) dedupliziert
separat** über einen ungeindexten `LOWER(name)=LOWER(?) AND LOWER(stadt)=LOWER(?)`-Scan — zwei
verschiedene Mechanismen für DB1 vs. DB2/Cloud (siehe Backlog B7).

### 3.4 Qualitätsfilter — `agents/quality.py`

`is_real_business(lead)` verwirft: zu kurze Namen, exakte Treffer in einer Generisch-Liste
("ergebnisse", "google maps", "impressum" …), Substring-Treffer gegen ~25 Portal-/Marken-Domains
(Wikipedia, 11880, myhammer, check24, handwerkskammer, aroundhome …), wortgrenzen-genaue Treffer
gegen generische Wörter (suche, vergleich, verzeichnis …), reine Großbuchstaben-Werbe-Header,
und Einträge ganz ohne Kontaktdaten. `agents/scorer.py::score()` vergibt zusätzlich einen
Ketten-Malus (-25) für Franchise-Marken.

### 3.5 Speicherung

- **DB1** `data/leads_raw.db` (SQLite) — reine Scraper-Rohdaten, `eval_status`
  (`pending`/`running`/`done`/`failed`), `claim_next_pending()` priorisiert
  `has_website ASC, bewertung DESC, gefunden_am ASC`.
- **DB2** `data/leads_evaluated.db` (SQLite, kanonisch) — s. Abschnitt 4.
- **Supabase `jarvis_leads`** — Multi-PC-Sync (Push sofort nach Bewertung, Pull alle 300s,
  Batch-Fallback alle 600s). Quota-Schutz über `supabase_quota.py` (10-Min-Pause nach HTTP 402).

### 3.6 Maps-Anreicherung (für ALLE Quellen)

`agents/evaluator/web_analyst.py` ruft `maps_enrichment.enrich(lead)` auf, wenn Fotos fehlen —
unabhängig davon, welcher Scraper den Lead gefunden hat. Läuft über einen eigenen
Playwright-Worker-Pool (2 Threads), ergänzt **additiv** (überschreibt nie) Foto-URLs,
Telefon, Adresse, Bewertungen aus Google Maps. Timeout 20s, liefert `None` statt Exception.

---

## 4. Lead-Bewertung — Evaluator-Pipeline

3 Worker-Threads ziehen atomar den nächsten Lead aus DB1 und laufen drei Agenten durch:

**Agent 1 — `web_analyst.analyze()`:** findet die echte Firmenwebsite per DDG-Suche (mit harter
Blockliste gegen Verzeichnis-/Social-Domains, ~50 Einträge), akzeptiert eine Zuordnung nur bei
Namens-Übereinstimmung. Prüft Telefon-Plausibilität, lädt die Seite, extrahiert E-Mails
(gefiltert, optional DNS/MX-geprüft via `email_verify.py`, optional SMTP-RCPT-Probe). Bestimmt
Website-Alter (Copyright-Jahr-Regex/WHOIS) und "veraltet" (≥4 Jahre oder Legacy-Technik wie
Tabellen-Layout/Flash/`<marquee>`). Ruft die Maps-Anreicherung auf.

**Agent 2 — `social_researcher.research()`:** findet Social-Media-Profile aus denselben
Suchtreffern (spart eine zweite Suche — **seit heute per Flag zusätzlich abgesichert, siehe
Fixes**), leitet einen Firmengrößen-Hinweis ab (Kette/10-50/3-10/1-2 Personen).

**Agent 3 — `score_writer.evaluate()`:** deterministischer Basis-Score 0-100 (Website-Situation
größter Faktor: keine Präsenz 42 Punkte, nur Social 36, veraltete Website 30 …), Ollama
verfeinert (±15, Preis-Tier, Texte/Pitch), fällt bei Ollama-Ausfall auf den deterministischen
Score zurück. **Preis-Tiers:** feste Pakete 0/200/350/550/850/1200 €. **Sicherheit** (Confidence
0-100): E-Mail bestätigt 35, Telefon verifiziert 20, aktiver Betrieb 12, Kette-Malus -45.
**Lead-Typ:** `preis==0` → Archiviert; `score≥72 ∧ sicherheit≥50` → **Hot**; `score≥48` → Warm;
sonst Cold.

**DB2** (`db_evaluated.py`, `data/leads_evaluated.db`, WAL) — ~65 Spalten: Score, Sicherheit,
Erwartungswert-€, Pitch-Hook, E-Mail-Entwurf, Social-Media-JSON, Status-Funnel,
Konversions-Tracking (`kontaktiert_am`, `termin_am`, `verkauft_am`, `verkauft_euro` — Feedback-
Daten, aber **nicht automatisch ins Scoring zurückgespeist**, siehe Backlog B9). Archivierte
Leads (gute Website vorhanden) werden sofort `status='archiviert'`, damit sie nie gebaut werden.

---

## 5. Webseiten-Bau — `website_builder.py`

`build(lead, deploy=False)`:
1. Django-Landing-Vorlage (`vorlage_landing/`) nach `<Desktop>/jarvis_websites/<Datum>/web_<slug>` kopieren.
2. Bis zu 6 Lead-Fotos herunterladen, lokal bewerten/einordnen (Logos/Karten aussortieren,
   bestes Querformat → Hero, bestes Hochformat → Über-uns, Rest → Galerie).
3. **Content-Generierung:** zuerst lokal via Ollama (`_ollama_content`, spart API-Kosten),
   Fallback Claude API (`_claude_content`, Modell `JARVIS_CLAUDE_MODEL`/Default
   `claude-opus-4-8`, mit Prompt-Caching), letzter Fallback deterministische Templates.
   Branchengerechte Akzentfarbe (~60 Branchen-Regeln) + Kostenrechner-Datensatz (~25 Branchen).
4. **Hero-Bild**, Fallback-Kette: Lead-Foto → **Hero-Vorlage** (`hero_templates.py`, 0
   Cloud-Tokens, 11 vorgenerierte Branchen-Bilder) → Cloud-Engine (Higgsfield/OpenAI, Timeout
   180s) → lokale Diffusers-Generierung → Farbverlauf als letzter Ausweg. Nie ein Hänger.
5. `ref_images.ensure_placeholders` füllt leere Bild-Slots mit SVG-Platzhaltern.
6. `design_tokens.apply` — lokale "Taste"-Stufe: harmonische Farbwelt (HSL-Mathe, WCAG-AA-
   geprüft) + kuratiertes Google-Font-Pairing je Branche → `static/css/tokens.css`, 0 Tokens.
7. Bei `deploy=False` (Standardpfad des Auto-Builders) endet der Job hier lokal fertig — der
   eigentliche Deploy passiert **einmal** am Ende des Makeovers (verhindert mehrfache
   Railway-Builds/sichtbare 404-Phasen).

**Deploy** (`_deploy_folder`): GitHub-Repo `web-<slug>` (öffentlich, sonst sieht Railway es
u.U. nicht) anlegen, `agent_railway.deploy()`. `_url_live()` pollt bis HTTP <400 (ein 404 zählt
NICHT als live). Re-Deploys pushen nur — Railway rebuildet automatisch, keine doppelten Services.

---

## 6. Claude-Makeover & Overnight/Night-Builder

### 6.1 Makeover-Engine (`overnight_makeover.py`)

`JARVIS_MAKEOVER_ENGINE` Default **`hybrid`** — **2 Stufen** (nicht 7, ältere Doku war hier
veraltet und wurde korrigiert):
- **`lokal`** (0 Claude-Tokens): Templates aus content.json rendern, Farben/Fonts via
  `design_tokens.py`, Bilder lokal bewertet.
- **`politur`** (optional): EIN dünner Claude-Code-Lauf (`claude_coder.run_prompt`, Skill
  `design-taste-frontend`, max. 22 Turns, 720s Timeout) für Feinschliff — blockiert die
  Discord-Freigabe NIE (`optional=True`).

Ältere Varianten (`STAGES_MULTI`: 3 Stufen; `STAGES_ONEPASS`: kompletter Ein-Pass) existieren
noch für `JARVIS_MAKEOVER_ENGINE=claude`, sind aber nicht Standard. `_MAKEOVER_VERSION = 7` —
ein Versions-Gate, das ältere Seiten komplett neu durch den aktuellen Plan laufen lässt.

Deterministische Vorbereitungsschritte (0 Tokens): Hero-Vorlage/Cloud-Refresh, Impressum/
Datenschutz/AGB (`legal_pages.py`), Geocoding, Foto-Bewertung, Akzentfarbe, Kostenrechner.

**Claude-Session-Limit-Erkennung:** `_looks_limited(text)` sucht Phrasen wie "session limit",
"usage limit", "weekly limit", "spend limit", "resets", "quota" (siehe Fehlerhistorie: "spend
limit" fehlte zunächst → eine unpolierte Seite ging automatisch an einen echten Kunden raus,
inzwischen gefixt). `claude_limit.py` bucht Token-Verbrauch je 5h-Fenster, lernt die Schwelle
und plant den Retry.

### 6.2 Night-Builder (`auto_builder.py`)

3 Sessions/Tag × Tageslimit (Default 5, Paid-Boost verdoppelt bei erkannter echter API-Nutzung)
= bis zu 15 Seiten/Tag. `_pick_next_lead()` wählt den besten unbebauten Lead (nach
Erwartungswert, Duplikat-Check). Bei Claude-Limit-Erschöpfung: erst versuchen, OHNE Claude
Fortschritt zu machen (Cloud-Hero erneuern), sonst stoppen + Neustart-Timer (gelernte Wartezeit
aus `claude_limit.py`, Fallback 3600s). Transiente Netzwerkfehler (Timeout, 502/503) pausieren
NICHT stundenlang wie echte Limits.

### 6.3 Railway-Deployment & Rotation

Ein zentrales Sammelprojekt ("Generated Websites") hostet alle Services, jede Website hat ein
eigenes öffentliches GitHub-Repo. **Rotation:** ab Default 50 Services im aktuellen Projekt wird
automatisch ein Folgeprojekt angelegt (`agent_railway._target_project_name()`, lebt komplett aus
der Railway-API, kein lokaler State). **Erzwungene Rotation** (Live-Watch-getriggert): wenn ≥3
Seiten gleichzeitig offline sind UND die eigene Internetverbindung nachweislich okay ist.

### 6.4 Live-Watch

Läuft immer (alle 120s), auch ohne Night-Builder: prüft jede aktive Seite per HTTP, redeployt
nicht erreichbare Seiten mit Cooldown (600s). Nach 3 erfolglosen Versuchen: langer Backoff (4h)
statt endlosem Neuversuch alle paar Minuten (war ein realer, bereits behobener Bug).

---

## 7. Versand & Kommunikation

### 7.1 E-Mail-Erstkontakt (`offer_mail.py` + `mailer.py`)

`offer_mail.build()` erzeugt Betreff (rotiert deterministisch per Hash, keine Spam-Trigger
wie `€`/`!!!`) + Text/HTML. **Wichtig:** nennt **keinen Festpreis** mehr, nur "sehr fairer
Preis" (ältere 350-€-Hardcodierung ist bereits entfernt — die Projekt-Doku dazu war veraltet
und wurde heute korrigiert). Rechtssicherer Footer (`legal_pages.build_email_footer`).

`mailer.py` — reines `smtplib`, Trockenlauf ohne `JARVIS_EMAIL_ENABLED=true`, Stundenlimit
(Default 20/h, nur erfolgreiche Sends verbrauchen Budget), `JARVIS_EMAIL_REDIRECT` als
Test-Sicherung (alle Mails an eine Test-Adresse — der Discord-Kundenversand hebt das gezielt
auf, das Voting-Gate gilt dort als Sicherung), Opt-out-Check (`email_suppress.py`), List-
Unsubscribe-Header. Zustellbarkeit vor Versand: `email_verify.is_deliverable()` (MX/A-Record,
optional dnspython, blockiert nur bei **definitivem** Nein, nie bei Unklarheit).

### 7.2 Discord-Freigabe-Gate (`discord_bot.py`)

Auto-Send Default **AN** (`JARVIS_AUTO_SEND=1`) — Reviews werden direkt als `APPROVED` angelegt,
kein 👍 nötig, der Discord-Post ist nur zusätzliche Sichtbarkeit. **👎 = Veto**, unabhängig vom
Modus, sofort `REJECTED`. Persistente Buttons (`discord.ui.DynamicItem`) überleben Bot-Neustarts.
**12-Uhr-Versand:** zwei redundante Auslöser (discord.py `tasks.loop` + ein unabhängiger
Watchdog-Thread, der auch bei totem Discord-Client greift) — bewusst doppelt abgesichert nach
einem früheren Vorfall ("Versand hörte nach 2 Tagen auf"). Vor Versand: Live-Check des Links.

### 7.3 Antwort-Analyse (`inbox_reader.py`)

Read-only IMAP (`BODY.PEEK`, nie gelöscht/verändert), Poll alle 10 Min. Kategorisiert per
Ollama (interesse/absage/rueckfrage/preisfrage/termin/neutral) + baut bei erkannter Kategorie
automatisch einen Antwort-Entwurf (`reply_templates.suggest()`). **Jede** Kategorie (auch
Absagen) löst eine Discord-Meldung aus UND markiert die Seite als "replied" — das schützt sie
dauerhaft vor dem automatischen Demo-Teardown, unabhängig vom Ausgang des Gesprächs.

### 7.4 Preissystem

`pricing.py`: drei feste Pakete Starter 300 € / Standard 450 € (empfohlen) / Premium 600 €,
plus additive Feature-Aufpreise (Unterseiten, Terminanfrage, Shop …). `reply_templates.py`
nutzt diese Tiers nur in der **Antwort auf eine konkrete Preisfrage** — der Erstkontakt nennt
bewusst keinen Preis (siehe 7.1). Zwei unterschiedliche Preis-Kommunikationsstrategien je
Gesprächsphase, keine Inkonsistenz.

---

## 8. Geld-Workflow (8 Schritte)

| # | Schritt | Code | Status |
|---|---|---|---|
| 1 | Leads finden | `scrapers/controller.py` | ✅ Fertig |
| 2 | Bewerten & Preis | `agents/evaluator/` | ✅ Fertig |
| 3 | Webseite bauen + live | `website_builder.py` | ✅ Fertig |
| 4 | Makeover (hybrid: lokal+Politur) | `overnight_makeover.py` | ✅ Fertig |
| 5 | Qualitäts-Freigabe | `discord_bot.py` (Voting) | ✅ Fertig |
| 6 | Angebots-E-Mail | `offer_mail.py`/`mailer.py` | 🟡 Teilweise (Zustellbarkeit/Recht offen) |
| 7 | Antwort → Abschluss & Zahlung | `inbox_reader.py` (liest), Rest manuell | ❌ Offen (bewusst) |
| 8 | Dashboard, Medien & Kosten | Dashboard, `cost_tracker.py` | ✅ Fertig |

Home-/Mein-Status-Tab (`app.py::api_home_stats`/`api_mystatus`) aggregiert alle Zahlen live in
je einem API-Aufruf. Geschätzter Systemwert laut interner Doku: ~2.000 € jetzt → ~6.500 € fertig
ausgebaut (Einzelnutzer-Werkzeug, ehrlich eingeordnet als Solo-Projekt, kein Enterprise-SaaS).

---

## 9. Medien-Engine — Bild/Video/Werbevideo

### 9.1 `media_engine.py` — Bild- und Video-KI

- **Lokale Bildmodelle** (Diffusers, hardware-adaptiv via `best_image_model()`): SD-Turbo
  (CPU/schwache GPU, 2-4 Steps), SDXL (GPU≥6GB/Apple-MPS, 1024×1024), FLUX.1-Schnell
  (GPU≥12GB+HF-Token, beste Qualität, gated).
- **Lokales Videomodell:** Wan 2.1 T2V 1.3B (480p, nur GPU — auf reiner CPU wird sofort auf
  Cloud umgeschaltet, kein stundenlanger Hänger).
- **Higgsfield Cloud:** Bild (Soul, 1080p) + Video (Dop Lite/Preview/Turbo, 3/6/9 Credits) —
  entweder über Abo-Credits via `higgsfield_mcp.py` (OAuth, bevorzugt) oder Platform-API-Key
  (separater Credit-Topf!). Cloudflare-1010-Fix über echten Browser-User-Agent.
- **OpenAI (ChatGPT) Bilder:** `gpt-image-1`, mit hartem Tageslimit (`JARVIS_OPENAI_IMAGE_DAILY_MAX`).
- Alles läuft über `media_queue.py` — EIN serieller Worker für lokale (GPU-gebundene) Jobs,
  mehrere parallele Worker für Cloud-Jobs (`_CLOUD_KINDS`: higgsfield*, openai_image,
  filmora_edit, **website_ad_video** — braucht keine GPU, läuft daher im Cloud-Pool mit).

### 9.2 Werbevideo-Tab — `website_ad_video.py` (NEU, 05.07.2026)

Anders als das KI-generierte Werbevideo (Text-Prompt → Wan/Higgsfield) nimmt dieser Weg die
**echte Website** eines Kunden per Playwright auf und schneidet daraus einen fertigen 9:16-Clip
— kein GPU/Cloud-Credit nötig, komplett lokal:
1. **Playwright** (headless Chromium): Seite laden (3 Versuche), Cookie-Banner schließen,
   Lazy-Load per Scroll vortriggern, Hero-Screenshot + Vollseiten-Screenshot (1080px Basis,
   `device_scale_factor=2`).
2. **PIL/numpy-Kontrast-Heuristik:** wählt die 3 visuell auffälligsten 1080×1920-Fenster der
   Seite (höchste Helligkeits-Standardabweichung) als Detail-Cuts — ohne eigenes KI-Modell.
3. **ffmpeg** (Binary aus `imageio_ffmpeg`, kein System-ffmpeg nötig): Hook-Zoom (1,5s) →
   Scroll-Pan über die Gesamtseite (5s) → 3 Detail-Zoom-Cuts (2,5s) → CTA-Karte (1s) + ein
   offline-synthetisierter Ambient-Ton (zwei Sinustöne, Fade-in/out — bewusster Fallback ohne
   Lizenzfragen, da kein echter Beat eingebunden ist).
4. **QS-Check** über `ffmpeg -i`-Stderr-Parsing (kein ffprobe gebündelt): Dauer/Auflösung/
   Codec/Ton/Größe, Auto-Re-Encode bei >12MB.
5. Ausgabe: `workspace/media/ads/ad_<domain>_<timestamp>.mp4` + Caption/Hashtag-Vorschlag.

**Gefundener + gefixter ffmpeg-Bug (in dieser Session):** `-t <dauer>` muss eine **Output**-
Option sein (nach `-vf`), nicht vor `-i`. Als Input-Option begrenzte sie nur die (bei `-loop 1`
mit 25fps-Default) eingelesenen Quell-Frames — `zoompan` vervielfachte aber jeden davon erneut
um `d` Frames, ein 1,5s-Clip brauchte dadurch ~55s Ziellänge und mehrere Minuten CPU (im Test:
962 CPU-Sekunden, nie fertig) statt <1s. Nach dem Fix: exakt 10,0s, 1080×1920, H.264, Ton
vorhanden, 0,51 MB, end-to-end gegen eine echte Website verifiziert.

---

## 10. Der Dashboard-Chat-Agent — was WIRKLICH läuft

**`claude_chat.py`** (Backend) + **`agent_tools.py`** (34 Tool-Definitionen) versorgen den Tab
"Claude" **und** das globale, auf jeder Seite ausklappbare Chat-Popup (`chatdock.js`) — beide
nutzen dasselbe `/api/claude/chat`-Backend. Ein einzelner, agentischer Tool-Use-Loop
(`anthropic.messages.stream()`, max. `JARVIS_CLAUDE_MAX_ROUNDS` Runden, Default 16), Modell
`JARVIS_CLAUDE_MODEL`/Default `claude-opus-4-8`. Unterstützt optional natives Denken
(`thinking`) und Claude-natives Web-Search-Tool.

**Tool-Kategorien:** Maps (4), Browser/Playwright (8), Medien (3), Leads/eigene DB (5,
inkl. `leads_update` als echter Schreibzugriff), eigener Shop-Sonderfall (6, NUR für einen
ausdrücklich gewünschten From-Scratch-Shop), Webseiten-Bau/Deploy (7, u.a. **`build_website`**
als Standardweg für "bau dem Lead X eine Webseite" — EIN Tool-Call macht alles: Vorlage,
Texte/Design, Hero, GitHub-Repo, Railway-Deploy), Auto-Builder-Steuerung (1).

**Klar getrennt davon:** `agents/ceo.py` + `agents/team.py` (10 Spezialisten: LibraryScout,
ResearchBot, SeniorPy, UXCrafter, ReviewMaster, DebugHunter, BugSlayer, BugWizard, SpeedDemon,
SecureGuard) + `agents/tools.py` (19 Tools: PC/Browser/Ollama/Agent-Delegation) sind ein
**eigenständiges CLI-Tool** (`python main.py`, interaktives `input()`-Menü: Einzelagent
befragen, Full-Code-Review-Pipeline, Debug&Fix-Pipeline, Feature-Pipeline). Wird von
`start.py`/`install.py` nie gestartet, hat keinen Web-Zugriff, wird von den Tests nicht
berührt. Vermutlich Altcode aus einem Vorgänger-Projekt (dessen `CLAUDE.md`-Doku beschrieb
noch das Arbeitsverzeichnis `...\jarvis\` ohne die "2").

---

## 11. Datenpakete / LeadForge (`leadpackages/`)

Eigenständiges Verkaufs-Feature, getrennt vom Akquise-Funnel: verkauft **rohe** Firmendaten
(nicht KI-bewertete Akquise-Leads) als CSV/Excel-Bundles. Eigene Quellen (`sources_dach.py`,
`sources_herold.py`), eigener `scrapling`-Wrapper mit 3 Eskalationsstufen (`scrapling_engine.py`),
eigenes Fuzzy-Dedup (`dedup_fuzzy.py`, `rapidfuzz`), eigene Qualitäts-/Potenzial-Bewertung
(getrennt von `agents/scorer.py`), eigene SQLite-DB. Feste Bundle-Preise: 50 Datensätze = 49 €,
200 = 149 €, 1000 = 499 €. Export als CSV oder `.xlsx`. **Kein Payment-Provider** — eine
Bestellung erzeugt sofort die Datei zum Download (bewusst manueller Verkaufsprozess, kein
Endkunden-Self-Service).

---

## 12. Frontend-Architektur

**Sidebar-Navigation** (kein Top-Tab-Bar), `templates/index.html`, 5 Gruppen, 11 Tabs:

| `data-page` | Gruppe | Inhalt |
|---|---|---|
| `home` | Übersicht | Live-Stats, Auto-Builder-Status, Reifegrad-Banner |
| `leads` ("Mein Status") | Akquise | Haupt-Dashboard: Kosten/Session, Bau-Fortschritt, Top-25-Rangliste, Live-Log |
| `ranking` | Akquise | Vollständige DB2-Rangliste, Pipeline-Wert |
| `graph` | Akquise | 3D-Globus (Lead-Standorte) + D3-Force-Graph + Balkendiagramm |
| `websites` | Produktion | Alle gebauten Seiten, Stufen-Status, Discord-Versand-Status |
| `custom` ("Eigene Marke") | Produktion | Manueller Bau für eigene Marke/Kunde |
| `media` ("Medien") | Produktion | Bild/Video-Generierung (lokal/Higgsfield/ChatGPT), Asset-Sets |
| `video-studio` | Produktion | Filmora-MCP-Anbindung (YouTube-Editing) |
| `ad-video` ("Werbevideo") | Produktion | Website-URL → 9:16-TikTok-Ad (siehe Abschnitt 9.2) |
| `leadpackages` ("Datenpakete") | Daten | LeadForge-Verkauf |
| `claude` | System | Werkzeugfähiger Chat-Tab (Spline-3D-Robot) |

**JS-Module** (`static/js/`): `app.js` (Kern: Routing, Chat, Voice, SSE, Mein-Status-Polling),
`graph.js`/`globe.js` (D3/Three.js Lead-Visualisierung), `ranking.js`, `websites.js`,
`claude.js`, `chatdock.js` (globales Popup), `video_studio.js`, `leadpackages.js`,
`ad_video.js`, `brain.js` (Knowledge-Sphere aus `obsidian_brain/`), `vault.js`.

**Design-System** (`static/css/style.css`, CSS-Custom-Properties): `--bg/--bg2/--bg3/--bg4`
(dunkle Blautöne), `--c` (Cyan `#00d4ff`, Akzent), `--g/--r/--y/--b/--pu` (Status-Farben),
`--hot/--warm/--cold` (Lead-Temperatur), `--fh` (Orbitron, Headings), `--fu` (Inter),
`--fm` (JetBrains Mono). Iron-Man-HUD-Look über Scanline-Overlay + Glassmorphismus
(`backdrop-filter`, 12+ Stellen).

---

## 13. Cloud-Sync & Datenhaltung

**Lokale Quelle der Wahrheit:** drei getrennte SQLite-DBs unter `data/` (WAL-Modus,
`check_same_thread=False`, `busy_timeout=5000`): `leads_raw.db`, `leads_evaluated.db`,
`websites.db`.

**Supabase — je nach Datentyp unterschiedliche Rolle:**
- **Leads** (`cloud_sync.py`, Tabelle `jarvis_leads`): bewusst als primärer Multi-PC-Sync-Store
  behandelt. Push sofort (fire-and-forget), Pull beim Start + alle 300s, Batch-Fallback alle
  600s. Merge-Logik: Funnel-Rang entscheidet den Sieger, ein `archiviert`-Status ist "sticky"
  (verhindert PC-übergreifendes erneutes Bauen bereits gelöschter/archivierter Seiten).
- **Webseiten** (`cloud_sync_websites.py`, Tabelle `jarvis_websites`): Push immer aktiv
  (inkl. Bild-Upload in einen Storage-Bucket), **Pull standardmäßig AUS**
  (`JARVIS_SYNC_WEBSITES_PULL=0`) — Webseiten sind lokale Ordner-Artefakte, ein anderer PC
  kann sie weder reparieren noch deployen; ungefiltertes Pull würde nur fremde 404-Karten
  zeigen. Dient primär als Feed für die separate Railway-Leadsite (`/versand/`-Seite).
- **`supabase_quota.py`:** gemeinsamer Schutz — ein HTTP 402 blockiert für 600s ALLE weiteren
  Pushes beider Module (verhindert Log-Flut bei 32 parallelen Evaluator-Threads).

---

## 14. Kosten-Tracking & Hardware-Profile

**`cost_tracker.py`** — tagesaggregiert in `data/costs.json`: Anthropic-Tokenpreise pro Modell,
Higgsfield-Credits (~0,04 €/Credit geschätzt), OpenAI-Bildpreise, Stromkosten (CPU/GPU-Watt ×
Strompreis). **Paid-Boost-Erkennung:** erkennt echte bezahlte API-Nutzung und verdoppelt dann
das Auto-Builder-Tageslimit. **Verbrauchs-Badge** (`extra_usage_month()`/`higgsfield_month()`):
ersetzt eine alte Kosten-Seite, resettet sich automatisch zum Monatswechsel (kein eigener
Reset-State nötig, da nur Events mit passendem `YYYY-MM`-Präfix gezählt werden).

**Zwei unabhängige Hardware-Erkennungspfade** (Redundanz, siehe Backlog B8):
`hardware.py` (RAM/GPU für die Wahl des lokalen Ollama-Modells, 6 Profile mini→max) und
`hardware_profile.py` (separates, medien-pipeline-spezifisches Profil: Bildschritte,
Parallelität, Nightly-Batch-Größe).

---

## 15. Konfiguration — `.env`

**Pflicht:** `ANTHROPIC_KEY` (oder `ANTHROPIC_API_KEY`) — ohne diese ist der Claude-Chat-Tab
und der komplette Makeover-Pfad tot. Praktisch **jede andere Variable hat einen sinnvollen
Code-Default** — nichts sonst ist hart erforderlich, damit der Server startet.

Wichtigste Gruppen (vollständige Liste im Repo-Grep, hier nur die Kern-Schalter):

| Bereich | Wichtigste Variablen |
|---|---|
| Server | `JARVIS_HOST`, `JARVIS_PORT`, `JARVIS_THREADS`, `JARVIS_SERVER`/`JARVIS_PROD` |
| Lokale KI | `JARVIS_AI_MODE`, `JARVIS_LOCAL_MODEL`, `JARVIS_EVAL_MODEL`, `JARVIS_PERF_TIER` |
| Medien | `JARVIS_IMAGE_MODEL`, `JARVIS_VIDEO_MODEL`, `JARVIS_VIDEO_BACKEND`, `HIGGSFIELD_API_KEY` |
| Cloud/Deploy | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `GITHUB_TOKEN`, `RAILWAY_TOKEN`, `JARVIS_RAILWAY_ROTATE_AT` |
| E-Mail | `JARVIS_EMAIL_ENABLED`, `JARVIS_EMAIL_RATE`, `SMTP_*`, `JARVIS_EMAIL_REDIRECT`, `IMAP_*`, `JARVIS_INBOX_ENABLED` |
| Discord | `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`, `DISCORD_SEND_HOUR`, `DISCORD_APPROVALS_NEEDED` (Default **1**), `JARVIS_AUTO_SEND` |
| Night-Builder | `JARVIS_DAILY_SITES`, `JARVIS_SESSIONS_PER_DAY`, `JARVIS_LIVE_WATCH_INTERVAL`, `JARVIS_LIVE_ROTATE_THRESHOLD` |
| Makeover | `JARVIS_MAKEOVER_ENGINE` (Default `hybrid`), `JARVIS_MAKEOVER_MODEL`, `JARVIS_POLITUR_SKILL` |

---

## 16. Testabdeckung

`tests/test_core.py` — Stand nach dieser Session: **184 Tests, alle grün** (Laufzeit ~167s,
inkl. einiger netzwerk-/thread-lastiger Integrationstests, die die App real hochfahren).
Bekannter, seltener Flake: `test_deploy_respects_makeover_gate` (Cross-Test-Thread-Kollision,
kein echter Bug, isoliert immer grün).

---

## 17. Heute durchgeführte Fixes (05.07.2026)

Bei der Analyse gefundene, **sicher und gering riskant behebbare** Probleme wurden direkt
gefixt (keine reinen Beobachtungen — echte Code-/Doku-Änderungen):

1. **`agents/evaluator/social_researcher.py`** — die zweite DDG-Suche (verletzte das
   dokumentierte "keine 2. Suche"-Design, Such-Budget-/Block-Risiko) ist jetzt hinter
   `JARVIS_SOCIAL_SECOND_SEARCH` (Default AUS) gelegt — exakt wie im eigenen Audit-Dokument
   (`workspace/LEAD_COLLECTOR_UND_AUDIT.md`, "Fix 5") als Plan festgehalten, aber nie umgesetzt.
2. **`discord_bot.py`** — Docstring korrigiert: `DISCORD_APPROVALS_NEEDED` Default ist **1**,
   nicht 2 (Code war schon immer korrekt, nur der Kommentar log).
3. **`scrapers/controller.py`** — Docstring + Log-Meldung korrigiert: 6 Kern-Worker + 1
   AT-spezifischer (herold.at), vorher stand überall "6" bzw. ein hartcodiertes `{7}` im Log,
   das bei fehlenden AT-Combos falsch gewesen wäre.
4. **`db_evaluated.py::get_stats()`** — redundante Doppel-Query entfernt (`ohne_web`/
   `ohne_web_e` liefen exakt dieselbe SQL-Abfrage zweimal); beide öffentlichen Kennzahlen
   (`ohne_website`, `ohne_website_echt`) bleiben erhalten, nur einmal berechnet.
5. **`workspace/GELD_WORKFLOW.md`** — zwei Stellen korrigiert, die noch von einem
   "hardcodierten 350-€-Festpreis in `offer_mail.build`" sprachen; dieser wurde bereits vorher
   entfernt (siehe Punkt 7.1), die Doku hinkte hinterher.
6. **`CLAUDE.md`** (die "absolute Gesetz"-Systemdoku, wird bei jeder Session geladen) — größte
   Korrektur: Abschnitt 5 (Architektur) beschrieb ein anderes, älteres Schwesterprojekt
   (`...\jarvis\`, 3-Spalten-Layout, `/api/chat`, "Satelliten-Ansicht") statt jarvis2. Neu
   geschrieben mit der echten Architektur (siehe Abschnitt 1/2 hier). Abschnitt 6: fiktive
   "Satelliten-Ansicht" entfernt (kein Leaflet/Nominatim im Code verifizierbar). Abschnitt 10+11:
   klargestellt, dass `agents/team.py`+`agents/tools.py` ein separates CLI-Tool (`main.py`) sind,
   NICHT der Dashboard-Chat — plus vollständige Dokumentation des echten `agent_tools.py`
   (34 Tools). Diese Korrektur ist wichtig, weil `CLAUDE.md` bei jeder künftigen Session
   automatisch als System-Prompt geladen wird — falsche Architektur-Annahmen hätten sich sonst
   dauerhaft fortgepflanzt.
7. **Eigenes Memory-System aktualisiert** (`~/.claude/projects/.../memory/`): Hero-Vorlagen-
   Anzahl im Index korrigiert (6→11, der Detail-Eintrag selbst war schon korrekt), Makeover-
   Stufenzahl-Klarstellung ergänzt (Default ist 2 Stufen seit 26.06., nicht 7 — mehrere spätere
   Einträge sagten noch locker "7 Stufen").

Alle Fixes sind **rückwärtskompatibel** (neue Flags defaulten auf das bisherige Verhalten außer
bei Fix 1, der bewusst das bisherige — versehentliche — Verhalten auf den ursprünglich
geplanten Zustand zurücksetzt) und durch die volle Testsuite (184 Tests) sowie einen gezielten
Syntax-/Importcheck abgesichert.

---

## 18. Offener Backlog — bewusst NICHT automatisch gefixt (mit Plan)

Diese Punkte sind real, aber zu riskant für einen automatischen Fix in einem laufenden,
Umsatz-relevanten System ohne Rücksprache — hier als priorisierter Plan festgehalten:

**B1 — Website-Check-Duplikat über 5 Scraper statt zentral im Evaluator**
(`check_website()`/WHOIS läuft in jedem Scraper einzeln). *Plan:* aus den Scrapern entfernen,
nur `has_website` roh setzen lassen; Alter/WHOIS zentral einmal im Evaluator prüfen. *Risiko:*
Scoring-Regression möglich, da `website_alter` heute z.T. schon früh vorliegt — vor Umsetzung
A/B mit Score-Vergleich auf einer Kopie der DB fahren. *Aufwand:* mittel (5 Dateien).

**B2 — 4× Code-Duplikat** (`_parse_rating`, `_get`, `_HEADERS`) in `gelbe_seiten.py`,
`dasoertliche.py`, `elfacht.py`, `golocal.py`. *Plan:* nach `scrapers/_http.py` verschieben,
vorher Diff der vier Implementierungen ziehen (könnten leicht divergiert sein). *Risiko:*
niedrig, aber Regressionstest je Quelle nötig, da diese live scrapen. *Aufwand:* klein.

**B3 — Thread-lokale SQLite-Connections statt Connection+PRAGMA pro Aufruf**
(`db_raw._conn`/`db_evaluated._conn`). *Plan:* `threading.local()`-Pool einführen. *Risiko:*
WAL-/Transaktions-Semantik muss sorgfältig mit `check_same_thread=False` gegengetestet werden,
da 32+ Threads gleichzeitig schreiben — Umsetzung nur mit dediziertem Lasttest. *Aufwand:* mittel.

**B4 — DB1-Dedup ohne Index** (`insert_raw()` scannt `LOWER(name)=LOWER(?)` ungeindext).
*Plan:* normalisierte Spalte (`name_norm`) + UNIQUE-Index ergänzen, bestehende Zeilen einmalig
migrieren. *Risiko:* niedrig, reine Performance-Maßnahme. *Aufwand:* klein.

**B5 — `herold_worker.py` stirbt dauerhaft bei fehlendem `curl_cffi`** (kein Recovery außer
Neustart). *Plan:* periodischen Recheck (z.B. alle 30 Min erneut `import`-Versuch) statt
einmaligem Thread-Ende. *Risiko:* niedrig. *Aufwand:* klein.

**B6 — Flask-Dev-Server ist De-facto-Standard** (kein automatisches `JARVIS_SERVER=1`).
*Plan:* `start.py` könnte `JARVIS_SERVER=1` als Default setzen, wenn nicht explizit anders
konfiguriert. *Risiko:* `waitress`-Verhalten (Timeouts, SSE-Streaming) vor Umstellung gegen die
aktuellen SSE-/Streaming-Routen testen (Chat-Streaming, Job-Polling). *Aufwand:* klein, aber
Testaufwand für SSE-Kompatibilität nicht trivial.

**B7 — Zwei getrennte Dedup-Mechanismen** (DB1 case-insensitiver Scan vs. DB2/Cloud
`lead_key`-Hash). *Plan:* langfristig auf einen einzigen Mechanismus (den Hash) vereinheitlichen,
sobald B4 den nötigen Index liefert. *Aufwand:* mittel, hängt an B4.

**B8 — Zwei unabhängige Hardware-Erkennungspfade** (`hardware.py` vs. `hardware_profile.py`).
*Plan:* auf eine gemeinsame Erkennungsfunktion konsolidieren, beide Profile darauf aufbauen
lassen. *Risiko:* beide haben leicht unterschiedliche Schwellenwerte/Zwecke (Ollama-Modellwahl
vs. Medien-Pipeline-Tuning) — vor dem Merge genau die Schwellenwerte vergleichen. *Aufwand:* mittel.

**B9 — Konversions-Feedback fließt nicht automatisch ins Scoring zurück**
(`get_conversion_stats()` liefert Daten, aber `score_writer.py`s Gewichte werden nur manuell
angepasst). *Plan:* periodischer Kalibrierungs-Job, der Gewichte anhand tatsächlicher
Konversionsraten pro Branche/Score-Band nachjustiert (mit Ober-/Untergrenzen, damit die
Heuristik nicht wegdriftet). *Risiko:* mittel-hoch — falsche Kalibrierung verschlechtert die
Lead-Priorisierung live. *Aufwand:* groß, braucht vorher genug Konversionsdaten.

**B10 — `_looks_limited()`-Erkennung ist string-/sprachbasiert** (englische Phrasen, bereits
einmal an einer neuen Formulierung vorbeigelaufen). *Plan:* zusätzlich zu Text-Mustern auch
API-Fehlercodes/HTTP-Status auswerten, falls Anthropic strukturierte Fehler statt Freitext
liefert (aktuell nicht der Fall, daher als Beobachtungspunkt vermerkt statt sofort umgesetzt).
*Aufwand:* offen, abhängig von Anthropic-API-Struktur.

**B11 — Kein Payment-Provider bei `leadpackages`**. *Plan (falls gewünscht):* Stripe-Checkout
vor Datei-Auslieferung schalten. *Aufwand:* mittel, aber bewusste Produktentscheidung von Sir
nötig (aktuell Vertrauensbasis für einen einzelnen wiederkehrenden Käufer gedacht) — daher
nicht ungefragt umgesetzt.

---

## 19. Datei-Index — wichtigste Module (Schnellreferenz)

```
Boot/Infra:        start.py, install.py, startup_check.py, config.py, app.py, hardware.py,
                   hardware_profile.py, cost_tracker.py, supabase_quota.py
Scraping:          lead_collector.py, scrapers/{controller,maps,maps_common,gelbe_seiten,
                   dasoertliche,elfacht,golocal,herold_worker,website_checker,regions,_http,
                   synonyme}.py, agents/{quality,scorer,ai_worker,outreach,name_clean}.py,
                   leadkey.py, db_raw.py
Bewertung:         agents/evaluator/{pipeline,web_analyst,social_researcher,score_writer,
                   maps_enrichment}.py, db_evaluated.py, email_verify.py
Webseiten-Bau:     website_builder.py, hero_templates.py, design_tokens.py, ref_images.py,
                   legal_pages.py, contact_finder.py, agent_github.py, agent_railway.py,
                   railway_cleanup.py, db_websites.py, cloud_sync_websites.py
Makeover/Night:     overnight_makeover.py, claude_coder.py, claude_limit.py, auto_builder.py,
                   duplicate_guard.py, cleanup_websites.py
Versand:           offer_mail.py, mailer.py, email_suppress.py, discord_bot.py, review_queue.py,
                   inbox_reader.py, pricing.py, reply_templates.py
Medien:            media_engine.py, media_queue.py, website_ad_video.py, agent_browser.py,
                   higgsfield_mcp.py, filmora_mcp.py, video_prompt.py
Dashboard-Chat:    claude_chat.py, agent_tools.py   (ECHT, live)
CLI-Team (main.py): agents/{ceo,team,tools,orchestrator,base_agent,llm_adapter}.py, main.py
                   (separat, NICHT live im Dashboard)
Datenpakete:       leadpackages/{routes,package_builder,pricing_packages,export_csv_excel,
                   scrapling_engine,dedup_fuzzy,quality_score,potential_score,db_packages,
                   sources_dach,sources_herold,ollama_summary,scheduler,watermark}.py
Cloud/Sync:        cloud_sync.py, cloud_sync_websites.py
Frontend:          templates/index.html, static/js/{app,graph,globe,ranking,websites,claude,
                   chatdock,video_studio,leadpackages,ad_video,brain,vault}.js,
                   static/css/style.css
Tests/Doku:        tests/test_core.py, CLAUDE.md, workspace/*.md (Audit-/Architektur-Docs)
```

---

*Erstellt durch eine vierfach-parallele Tiefen-Code-Analyse + eigene Verifikation der
wichtigsten Befunde (insbesondere der Dead-Code-Entdeckung in Abschnitt 10). Bei Widersprüchen
zwischen diesem Dokument und dem tatsächlichen Code gilt immer der Code — Software entwickelt
sich weiter, dieses Dokument ist eine Momentaufnahme vom 05.07.2026.*
