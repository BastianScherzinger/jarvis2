# JARVIS LeadHunter — Änderungsprotokoll

> Vollständige Liste aller Umbauten dieser Arbeitsphase. Stand: 19.06.2026.
> Reihenfolge: das neue Feature zuerst, dann die früheren Durchgänge, dann offene Punkte.

---

# Durchgang 21.06.2026 — Webseiten-Bau live, Datenqualität, Cloud-Fix, UX

## A. Lead → Webseite → live (komplett, getestet & live)
- Vorlage `vorlage_landing/` (schlanke, DB-freie Django-Landing) + `website_builder.py`
  (Job-Orchestrator) + `agent_github.py` + `agent_railway.py`. Lead anklicken →
  „Webseite bauen" → Claude textet/gestaltet, Fotos werden eingebaut, GitHub-Repo +
  Railway-Deploy mit öffentlicher Domain. **Echt getestet & live** (Lead „Umzüge S. Klein").
- Dabei zwei Railway-API-Bugs gefixt: Variablen-Mutation (`EnvironmentVariables!` statt
  `JSON!`) + Status-Reporting; `list_projects()`/`project_delete()` für Aufräumen.

## B. Lead-Namen mit lokaler KI säubern
- `agents/name_clean.py`: `quick_clean` (deterministisch — SEO-Codes wie „F0507", Wort-
  Wiederholungen, Marketing-Spam) schon beim Fund in `db_raw.insert_raw` (Feed + DB +
  `lead_key` nutzen denselben sauberen Namen). `ai_clean` (Ollama, 12-s-Timeout) als
  Feinschliff im Evaluator — **`lead_key` bleibt stabil** aus dem deterministischen Namen
  (kein Cloud-Dedup-Bruch).

## C. Hero-Banner (lokale KI) + hardware-abhängige Modellwahl
- Jede gebaute Seite bekommt einen Hero-Banner. `media_engine.hardware_info/best_image_model/
  hero_image_params`: **GPU → SDXL/FLUX (1280×720), CPU → SD-Turbo (768×512, ~90 s)**.
- BUG gefixt: `generate_image` crashte bei `output_dir` außerhalb des Workspace (Hero-Fall).
- **Higgsfield-Cloud als Fallback** für schwache Hardware — aber **nur auf Rückfrage**
  („Hero über Higgsfield-Cloud?"), Default bleibt lokal. `generate_image_higgsfield` +
  `higgsfield_balance` (best-effort, untestbar ohne Key, fällt immer auf lokal zurück).
  Template/CSS: Hero-Bild > Foto > Gradient-Fallback.

## D. Genauer Lade-Fortschritt beim Webseiten-Bauen
- `website_builder._step` mit monotonem Fortschritt + **Schritt-Log**; granulare Schritte
  (Projekt, Foto X/N, Claude, Hero mit Modell, GitHub anlegen/pushen, **jeder Railway-
  Teilschritt** via `agent_railway.deploy(on_step=…)`). Frontend zeigt Prozent + Log mit
  Haken/Spinner. Funktion unverändert.

## E. „Webseite bauen"-Button in der Rangliste
- `openRankDetail` hat den Button (neben der Bilder-Galerie) → `_startWebsiteBuild`
  (gemeinsam mit dem Feed). **Grün wenn Claude bereit, rot/deaktiviert wenn ANTHROPIC_KEY
  fehlt** (über `/api/claude/status`).

## F. Token-Budget im Claude-Reiter
- `metrics.budget_status()` + `/api/claude/status` liefern Tokens used/budget/remaining +
  **„reicht für ~N Webseiten"**. Anzeige im Claude-Tab, Update nach jeder Antwort + jedem
  Bau; rot bei ≤ 3 Webseiten. Budget via `JARVIS_SESSION_TOKENS` (Default 2 Mio.) +
  `JARVIS_TOKENS_PER_WEBSITE` (2500) konfigurierbar.

## G. `leads.db` (DB1) eliminiert — ein kanonischer Lead-Store
- `db.py` + `scrapers/verifier.py` gelöscht. Scraper schreiben nur noch `db_raw`; Feed nutzt
  die `raw_id`, Modal löst `raw_id → db_evaluated` auf. Dashboard-Zähler aus `db_raw`
  (Funde/Quellen) + `db_evaluated` (Hot/Warm/Cold). Verifiziert per Integrationstest.

## H. CloudSync-Fehler (HTTP 400 / 23502) behoben
- Supabase: `raw_id` → **nullable** (war NOT NULL, blockierte Multi-PC-Leads); 145 leere
  `lead_key` per `md5(lower(name)|lower(stadt))` nachgefüllt; **`UNIQUE(lead_key)`** ergänzt.
- `cloud_sync.py`: Upsert mit **`?on_conflict=lead_key`** (echtes Update statt Doppel/Fehler);
  `raw_id` aus dem Sync entfernt (lokale ID). Multi-PC-Sync ist jetzt sauber.

## I. Start & Claude-Tab
- **Bewertung startet nicht mehr beim Boot** — erst auf den Start-Button (`/api/start`).
- Claude-Tab lädt sofort (Chat/Mic zuerst, Spline-3D verzögert + abgesichert).
- **Mikrofon repariert**: Mic wird immer verdrahtet; Klartext-Hinweis bei unsicherem
  Kontext (LAN-IP statt localhost). Voice-Backend (PyAV + faster-whisper) verifiziert.

## J. Lokale Bildgenerierung + Datenqualität
- SD-Turbo ergänzt (CPU-tauglich, ~7× schneller als SDXL). Mockup nutzt es ebenfalls.
- **Datenqualitäts-Bug**: WebAnalyst akzeptierte DuckDuckGo/Bing-Werbe-Redirects
  (`duckduckgo.com/y.js?ad_domain=…`) als „eigene Website" → ausgefiltert (+ Test).

## K. .env-BOM-Fix
- Mein PowerShell-Schreiben hatte ein UTF-8-BOM in die `.env` gesetzt → `ANTHROPIC_KEY`
  wurde als `﻿ANTHROPIC_KEY` gelesen, Claude-Status rot. `.env` BOM-frei neu geschrieben.

## L. Cross-PC / Setup
- **`requests` in `requirements.txt`** ergänzt (agent_github/railway nutzen es; kam vorher
  nur transitiv). Skill `shop-bauen` global unter `~/.claude/skills/`.
- Verifiziert: 41 Module importieren, **24 Unit-Tests** grün, `smoke_audit.py` (alle
  GET-Routen + Kernmodule) 41/41 grün, keine hartcodierten Pfade.

## Neue/relevante .env-Variablen (alle optional, sauberes Degradieren)
```
GITHUB_TOKEN, GITHUB_USER, RAILWAY_TOKEN   # Webseiten-Deploy
HIGGSFIELD_API_KEY                         # Cloud-Hero (Format KEY_ID:KEY_SECRET)
JARVIS_SESSION_TOKENS=2000000              # Token-Budget der Session (Claude-Tab)
JARVIS_TOKENS_PER_WEBSITE=2500             # Schätzung Tokens je Webseiten-Build
JARVIS_HF_HERO_COST / JARVIS_HF_IMAGE_SIZE / JARVIS_HF_IMAGE_QUALITY
JARVIS_SHOP_DIR                            # Zielordner gebauter Seiten (Default Desktop)
```

---

## 0. NEU — Lead → Webseite → live (automatischer Website-Builder)

**Ziel:** Im Dashboard einen gefundenen Lead anklicken, „🌐 Webseite bauen" drücken — und
JARVIS baut dem Kunden vollautomatisch eine Landing-Page mit den **gefundenen Fotos**,
erstellt ein **GitHub-Repo** und **deployt auf Railway** mit öffentlicher Domain. Die
Live-URL erscheint im Modal und lässt sich dem Kunden schicken.

### Neue Bausteine
| Datei | Zweck |
|-------|-------|
| `vorlage_landing/` | Schlanke, **datenbankfreie** Django-Landing-Page (kein Login, kein DB-Plugin nötig). Gesamter Inhalt in **`content.json`**. Railway-ready (Procfile, railway.json, Whitenoise). |
| `website_builder.py` | Orchestrator + eigene Job-Registry. Kopiert die Vorlage → Kundenordner, lädt die Lead-Fotos nach `static/img/lead/`, lässt **Claude** texten/gestalten (`content.json`), generiert den Django-`SECRET_KEY`, ruft GitHub + Railway auf. |
| `agent_github.py` | GitHub-API-Client: Repo anlegen + token-authentifizierter Push. Token nur im Remote-URL, **nie geloggt**, danach token-freie Remote-URL. |
| `agent_railway.py` | Railway-GraphQL-Client: Projekt → Service aus dem Repo → öffentliche Domain → alle Env-Variablen → Redeploy. Ehrlicher Log statt Crash, wenn ein Schritt scheitert. |

### Verdrahtung
- **Backend:** `POST /api/lead/<id>/website` (startet Job, nimmt die besten Daten aus
  `db_evaluated` + Modal-Body), `GET /api/website/job/<id>` (Fortschritt pollen).
- **Frontend:** Button im Lead-Modal + Fortschrittsbalken + Live-/Repo-Link
  (`buildWebsite` / `_pollWebsite` in `static/js/app.js`, Styles in `style.css`).
- **Claude-Agent:** zwei neue Tools `build_website` + `build_website_status` — der Chat-Agent
  kann auf Zuruf („bau dem Lead X eine Webseite") dasselbe auslösen.
- **Skill:** `~/.claude/skills/shop-bauen/SKILL.md` — der Skill ist jetzt **global**
  invozierbar (`/shop-bauen`), nicht nur projektintern.

### Aktivierung (durch Sir — einmalig)
In die `.env` (bereits als leere Platzhalter eingetragen):
```
GITHUB_TOKEN=<PAT mit Scope 'repo'>      # github.com/settings/tokens
GITHUB_USER=<dein GitHub-Login>
RAILWAY_TOKEN=<API-Token>                 # railway.app/account/tokens
```
**Ohne Tokens** baut JARVIS die Seite trotzdem **lokal** (Ordner auf dem Desktop) und
überspringt Repo/Deploy sauber — die Schritte aktivieren sich automatisch, sobald die
Tokens gesetzt sind. Railways erster Repo-Deploy benötigt einmalig die Railway-GitHub-App
(Standard-Setup im Railway-UI).

### Getestet
- `vorlage_landing` rendert (Django-`check` 0 issues, `/` → 200, `/health` → 200).
- End-to-End-Bau im Temp-Ordner: Kopie + `content.json` + branchengerechte Akzentfarbe,
  GitHub/Railway ohne Token sauber übersprungen.
- Gebaute Seite enthält die injizierten Lead-Daten (Name, Stadt, Telefon, Akzentfarbe).
- 4 neue Unit-Tests (Slug, Akzent-Heuristik, JSON-Extraktion, Token-loses Degradieren).

### ECHTER Live-Test bestanden (20.06.2026)
Mit echten Tokens (GitHub + Railway) am Top-Lead **„Umzüge S. Klein GmbH & Co. KG"**
(Wuppertal, Score 94) durchgeführt:
- GitHub-Repo erstellt + gepusht: `github.com/BastianScherzinger/web-umzuege-s-klein-gmbh-und-co-kg`
- Railway: Projekt + Service + **öffentliche Domain** + Variablen (SECRET_KEY/DEBUG/
  ALLOWED_HOSTS/CSRF) + Deploy.
- **Live & erreichbar (HTTP 200, Firmenname im HTML):**
  `web-umzuege-s-klein-gmbh-und-co-kg-production-f685.up.railway.app`
- Dabei gefixt: Railway-Variablen-Mutation (`EnvironmentVariables!` statt `JSON!`) und
  ehrliches Status-Reporting (Railway-Meldung wird nicht mehr vom Schlusstext überschrieben).
- **Test-Reste zum Aufräumen:** 1 GitHub-Repo, einige Railway-Projekte (mehrfacher
  Verifikations-Deploy), 1 lokaler Ordner `Desktop/web_umzuege-...`.

---

## 1. Auto-E-Mail-Reife & Scoring (Durchgang Features)

- **`agents/evaluator/score_writer.py`:** neue Kennzahlen **Sicherheit** (Erreichbarkeit/
  Seriosität) und **Erwartungswert €** = `Potenzial × Score/100 × Sicherheit/100`; Hot-Leads
  zusätzlich an eine Mindest-Sicherheit gekoppelt.
- **`agents/evaluator/web_analyst.py`:** mehrere Fotos (`foto_urls`), alle E-Mails
  (`email_alle`), Ansprechpartner aus dem Impressum; **`_domain`-Bug gefixt** (führendes „w"
  wurde fälschlich abgeschnitten); erweiterte Portal-/Marktplatz-Ausschlussliste.
- **`agents/quality.py`:** Marktplätze/Portale (MyHammer, Handwerkskammer, Check24,
  Blauarbeit, wlw …) als Substring **und** wortgenau gefiltert.
- **`mailer.py` (neu):** SMTP-Versand mit Killswitch `JARVIS_EMAIL_ENABLED` (Default **aus**),
  Rate-Limit, Opt-out. E-Mail bleibt deaktiviert, bis Sir scharf schaltet.
- **Multi-PC-Sync:** `cloud_sync.py` mit periodischem Pull (alle 5 Min), Funnel-Merge
  (kein Status-Rückfall), Retry-Backoff. Supabase ist primärer Lead-Speicher.

## 2. „Claude"-Dashboard-Tab + Sprache

- **`claude_chat.py`:** echter werkzeugfähiger Claude-Agent (Anthropic Tool-Use-Loop,
  Streaming) mit JARVIS-Persönlichkeit.
- **`agent_tools.py` + Module:** Maps, Browser (Playwright), Medien, Lead-DB (lesen **und**
  schreiben), `enrich_business`, Shop-Bau — jetzt **+ Website-Builder**.
- **Sprache (`voice_web.py`):** faster-whisper (STT) + edge-tts (TTS), dauerhafter
  Freisprech-Modus (VAD) im Claude-Tab. Whisper-Basis-Modell wird beim Start geladen.
- **Fix:** abgeschnittener Composer im Claude-Tab (Seitenhöhe + `min-height:0`).

## 3. Observability + Architektur (Durchgang Refactoring)

- **`metrics.py` (neu) + `/api/metrics`:** Tool-Latenzen, Fehlerquoten, Claude-Token.
- **`leadkey.py` (neu):** **eine** kanonische Dedup-Definition (vorher drei), genutzt von
  `db_evaluated` + `cloud_sync`. Format unverändert → bestehende Keys matchen weiter.
- **Worker-Health** pro Worker in `/api/status`; **Watchdog** setzt hängende „running"-Leads
  zurück (`claimed_at` + `reset_stale_running`); **`busy_timeout`** in allen 3 SQLite-Modulen;
  **SSE-Stats** auf 1×/Sek gecacht; Claude-History clientseitig auf 40 Einträge begrenzt.
- **Tests:** `tests/test_core.py` (jetzt **13 grün**) + `pytest.ini` (Sammlung auf `tests/`).

## 4. Behobene Bugs (Auswahl)

| Bug | Fix |
|-----|-----|
| Falsches Supabase-Projekt migriert | Auf das in `.env` hinterlegte Projekt korrigiert. |
| `.env` durch verirrtes Passwort kaputt | Saubere `SMTP_*`-Konfiguration. |
| `_domain` schnitt „w" ab | Korrekte `www.`-Prüfung. |
| Ollama-Score immer +0 | `extract_json` mit Klammer-Balancierung neu geschrieben. |
| XSS in `onclick`-JSON | `_jattr`-Escaper. |
| Composer im Claude-Tab abgeschnitten | Seitenhöhe + `min-height:0`. |

---

## 5. Gesamt-TODO — was noch offen ist

1. **`leads.db` (Legacy-DB) eliminieren** — bewusst eigener, interaktiv getesteter Schritt:
   die Lead-Modal-Routen (`/api/lead/<id>/...`) und `get_stats()` hängen an DB1.
   Pfad dokumentiert in `workspace/ARCHITEKTUR_ROADMAP.md`.
2. **GitHub-/Railway-Tokens eintragen** (Sir), damit der Website-Builder live deployt.
3. **Railway-Deploy real gegentesten** — der GraphQL-Pfad ist nach dokumentiertem Schema
   gebaut, aber ohne Live-Token nicht end-to-end getestet; erster Lauf braucht ggf. die
   einmalige Railway-GitHub-App-Freigabe.

---

## 6. Neue/relevante Umgebungsvariablen

```
GITHUB_TOKEN, GITHUB_USER     # Website-Builder: Repo anlegen + pushen
RAILWAY_TOKEN                 # Website-Builder: Deploy + Domain + Variablen
JARVIS_SHOP_DIR               # Zielordner für gebaute Seiten (Default: Desktop)
JARVIS_EMAIL_ENABLED=false    # E-Mail-Killswitch (bleibt aus, bis scharf geschaltet)
```
`.env` ist gitignored — Tokens/Keys werden nie committet oder geloggt.
