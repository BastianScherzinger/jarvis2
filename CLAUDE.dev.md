# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Hinweis für Claude Code:** `CLAUDE.md` im selben Verzeichnis ist der **Laufzeit-System-Prompt**
> der JARVIS-Persönlichkeit (wird von der App beim Start geladen) — NICHT anfassen.
> Diese Datei (`CLAUDE.dev.md`) ist die **Entwickler-Referenz** für Claude Code. Beide lesen.

---

## Was dieses Projekt ist

**JARVIS LeadHunter** — ein Deutschland-weiter **B2B-Lead-Generator**. Scraper finden lokale
Unternehmen, ein lokales KI-Team (Ollama) bewertet sie, das Ergebnis landet in einer Rangliste
und wird per Supabase über mehrere PCs synchronisiert. Flask-Dashboard auf `http://localhost:5000`,
SSE-Live-Updates. Vollständig lokal lauffähig (keine Cloud-KI nötig).

---

## Befehle

```powershell
python start.py        # Hauptstart: Boot-Screen (Hardware-Erkennung + Ollama-Profil-Wahl),
                       # installiert Deps, startet app.py als Subprozess, öffnet Browser :5000
python app.py          # Nur Flask (ohne Boot-Screen / ohne Auto-Install)
python serve.py        # Produktionsmodus: waitress WSGI-Server, kein Browser-Autostart
python update.py       # Update von GitHub ziehen + neue Pakete installieren (Kunden-Befehl)
python main.py         # Legacy: interaktives Agenten-Team-Menü (vom LeadHunter entkoppelt)
```

```powershell
# Dev-Tools (in pyproject.toml als uv dev-dependencies)
uv run ruff check .            # Linting
uv run ruff format .           # Formatierung
uv run mypy .                  # Type-Checking
uv run pytest                  # Tests (tests/test_core.py)

# Syntax-Check einer einzelnen Datei (Projekt-Konvention)
python -m py_compile pfad/zur/datei.py
```

- Python **>= 3.11**. Windows-zentriert (PowerShell, UTF-8-Reconfigure in `start.py`).
- Externe Voraussetzung: **Ollama** auf `127.0.0.1:11434`. Optional: Playwright-Chromium
  (auto-installiert), ffmpeg, NVIDIA-GPU.
- `update.py` macht `git pull origin main --ff-only` + ruft `install.run()` auf. Dieses
  Skript ist der einzige Update-Kanal für Kunden-PCs.

---

## Architektur — die Lead-Pipeline (großes Bild)

Der Datenfluss läuft durch **drei SQLite-DBs** in `data/` und endet in Supabase:

```
         ┌──────────────────────────────────────────────────────────────┐
         │  scrapers/controller.py  — start() spawnt 6 Worker parallel  │
         └──────────────────────────────────────────────────────────────┘
ALLE_REGIONEN × BRANCHEN  →  gemischt, in 6 disjunkte Chunks geteilt
   ├─ Worker maps          (Google Maps, persistenter Playwright-Browser)
   ├─ Worker gelbe_seiten  ┐
   ├─ Worker dasoertliche  │  HTML-Scraper über scrapers/_http.py
   ├─ Worker elfacht       │  (11880)
   ├─ Worker golocal       ┘
   └─ Worker ai_worker     (Ollama recherchiert via Websuche)
        ↓ schreiben Roh-Leads in
   ┌──────────────────────┐
   │ db_raw.py            │  DB1 — Pending-Queue für den Evaluator
   │ leads_raw.db         │  claim_next_pending() ist atomar (pending→running)
   └──────────┬───────────┘
              ↓
   ┌──────────────────────────────────────────────────────────────────┐
   │ agents/evaluator/pipeline.py  — N Threads (JARVIS_EVAL_THREADS)  │
   │   1. web_analyst.analyze(lead)       → Website finden + prüfen   │
   │   2. social_researcher.research(...) → Social + Firmengröße      │
   │   3. score_writer.evaluate(...)      → Score 0-100 + Pitch       │
   └──────────┬───────────────────────────────────────────────────────┘
              ↓ insert_evaluated()
   ┌──────────────────────┐
   │ db_evaluated.py      │  DB2 — kanonische Rangliste (Score absteigend)
   │ leads_evaluated.db   │  Frontend liest NUR hier (/api/evaluated/*)
   └──────────┬───────────┘
              ↓ push_lead() fire-and-forget  +  Batch-Sync alle 10 Min
   ┌──────────────────────┐
   │ cloud_sync.py        │  Supabase (Tabelle jarvis_leads)
   └──────────────────────┘
```

### Kernkonzepte, die mehrere Dateien verbinden

- **Zwei DBs, klare Rollen:** `db_raw.py` (`leads_raw.db`) = Pending-Queue für den Evaluator.
  `db_evaluated.py` (`leads_evaluated.db`) = kanonische Rangliste + einzige Frontend-Quelle.
  Die alte `leads.db`/`db.py` + `verifier.py` wurden entfernt (Konsolidierung 21.06.).
  Feed-Modal-IDs sind `raw_id`s; das Modal löst `raw_id → db_evaluated` auf.
  Beide DBs: WAL, `check_same_thread=False`, `_lock`, `busy_timeout`, `init_db()` mit
  Spalten-Migration via `_NEW_COLUMNS`.

- **Globaler Dedup-Key:** `lead_key = md5(lower(name)|lower(stadt))` — **EINE** Definition
  in `leadkey.py`, importiert von `db_evaluated` + `cloud_sync`. Supabase hat
  `UNIQUE(lead_key)`, Upsert nutzt `?on_conflict=lead_key`. `raw_id` ist lokal, wird
  NICHT in die Cloud gesynct.

- **Ollama-Zugang zentralisiert** in `scrapers/_http.py`: `ask_ollama`, `best_chat_model`,
  `warmup_ollama`, `ollama_models`. Eine `Semaphore(2)` begrenzt parallele Calls
  (GPU serialisiert → sonst Timeout-Kaskade). Timeout 180s wegen Kaltstart (30–120s).
  Websuche hat `_SEARCH_MIN_INTERVAL` (1.3s) + Engine-Rotation gegen Rate-Limits.

- **Hardware-adaptive KI:** `hardware.py` erkennt RAM/VRAM (ctypes / `nvidia-smi`),
  empfiehlt Ollama-`PROFILES`-Modell. `start.py` zeigt Boot-Screen + setzt
  `JARVIS_EVAL_MODEL`. `hardware_profile.py` skaliert Parallelität (Server vs. Low-RAM).

- **Controller-Lebenszyklus:** `controller.start()` startet Scraper UND Evaluator.
  `ensure_evaluator_running()` / `reevaluate_all()` starten den Evaluator ohne Scraper.
  Bewertung startet **nicht automatisch** beim Boot — erst via Start-Button (`/api/start`).
  Worker schreiben über Queue → `controller._on_lead` → `_lead_queue` → SSE.

- **Medien-Generierung** (separater Strang): `media_queue.py` (Job-Queue) +
  `media_engine.py` (Diffusers hardware-adaptiv: GPU→SDXL/FLUX, CPU→SD-Turbo via
  `best_image_model`/`hero_image_params`; Higgsfield-API für Cloud-Fallback) +
  `ad_prompts.py`. Routes `/api/media/*`.

- **Webseiten-Bau** (`website_builder.py`): Lead → Landing aus `vorlage_landing/`
  (Claude-Text + Fotos + Hero-Banner) → `agent_github.py` (Repo+Push) →
  `agent_railway.py` (Projekt+Domain+Env). Async-Job mit Schritt-Log. Routes
  `/api/lead/<id>/website` + `/api/website/job/<id>`.
  `agent_railway._find_service()` sucht bei Re-Builds den bestehenden Service und
  übernimmt die Domain, statt mit einem Fehler abzubrechen.

- **Eigene-Marke-Modus** (`custom_build.py`): Manueller Build — Name, Logo, Hero und
  Beschreibung von Sir vorgegeben. Nutzt dieselbe `website_builder`-Engine + 7-Pass-
  Improve + Discord-Freigabe-Gate → Versand an 11+ Empfänger. Uploads landen in
  `workspace/custom_uploads/<slug>/`. Routes `/api/custom-build` + `/api/custom-build/status/<id>`.

- **Logo-Generator** (`website_improve._make_logo`): Deterministisches SVG-Monogramm
  (Initialen + Akzentfarbe) als Fallback wenn kein Logo hochgeladen. `_initials()`
  filtert Rechtsform-Zusätze (GmbH, KG etc.). Asset-Preservation im QA-Pass verhindert
  dass hero_image/logo_image durch Claude-Rewrite verloren gehen.

- **Score-Robustheit:** `score_writer` liefert immer einen deterministischen Basis-Score;
  Ollama ist nur Feinschliff. Fällt Ollama aus, bleibt die Bewertung gültig.
  Diese Garantie **nicht brechen**.

### Flask-API (`app.py`, Port 5000)

- Steuerung: `/api/start`, `/api/stop`, `/api/status`, `/api/clear`
- Rangliste (DB2): `/api/evaluated/all` (Filter/Sort/Suche), `/api/evaluated/top`,
  `/api/evaluated/reeval`, `/api/export/csv`
- Live: `/api/stream` (SSE — Lead-/Stats-/Evaluated-Events, Keepalive alle 20s)
- Lead-Aktionen: `/api/lead/<id>/status|email|mockup|competition|website|send-email`
- Webseiten: `/api/websites`, `/api/websites/<id>/improve|chat|integrate|offer-email`
- Cloud/Graph/Logs/Medien: `/api/sync`, `/api/graph/*`, `/api/logs`, `/api/media/*`
- Auto-Builder: `/api/auto-build/start|stop|status|daily`
- Discord-Freigabe: `/api/discord/status|send-now`, `/api/reviews`

---

## Konventionen & Stolperfallen

- **Code-Sprache ist Deutsch** — Variablennamen, Spalten, Log-Texte, Kommentare. Beibehalten.
- **Keine schweren Abhängigkeiten** für System-Tasks: RAM/GPU via `ctypes`/`subprocess`,
  HTTP/Ollama/Supabase via `urllib` (kein `requests` im Kern, kein `psutil`). Stil beibehalten.
- **`.env` niemals committen** (gitignored). Geheim: `ANTHROPIC_KEY`, `SUPABASE_SERVICE_KEY`,
  `SMTP_PASS`, `HIGGSFIELD_API_KEY`. `cloud_sync` erzwingt HTTPS und loggt Keys nie.
- **Wichtige Env-Variablen:** `JARVIS_AI_MODE` (`local`), `JARVIS_EVAL_MODEL`,
  `JARVIS_EVAL_THREADS` (Default 4), `JARVIS_BROWSER_HEADLESS`, `SUPABASE_URL`,
  `SUPABASE_SERVICE_KEY`, `HF_TOKEN` (nur für gated FLUX-Modell), `JARVIS_EMAIL_ENABLED`
  (Default `false` = Trockenlauf!), `SMTP_USER`, `SMTP_PASS`.
- **Worker schreiben über Queue, nie direkt ins Frontend:** alles geht über
  `controller._on_lead` → `_lead_queue` → SSE. Neue Worker diesem Muster folgen.
- **`lead_key` stabil halten:** Er basiert auf dem **deterministischen** (nicht KI-gereinigten)
  Rohnamen aus DB1. KI-Feinschliff (`name_clean`) nur für die Anzeige (`disp_name`).
  Den Key selbst nie mit KI-Output erzeugen — bricht Multi-PC-Dedup in Supabase.
- **`data/` ist gitignored** — SQLite-DBs werden lokal angelegt, nie committed.
  `obsidian_brain/` ist commitiert (wächst mit dem System).

---

## update.py — Kunden-Update-Skript

`python update.py` ist der einzige Update-Kanal für Kunden-PCs:
1. Prüft ob `git` installiert ist
2. Zeigt lokale Änderungen an (überschreibt sie NICHT)
3. `git fetch origin` + vergleicht Commits
4. `git pull origin main --ff-only` (mit `--force`-Flag: `git reset --hard origin/main`)
5. Ruft `install.run()` auf (neue Pakete + Playwright)
6. Zeigt Deploy-Status (GitHub + Railway)

Das Skript muss im Projektordner liegen und mit `python update.py` ausführbar sein.
Neue Abhängigkeiten immer in `requirements.txt` eintragen — `install.py` liest diese Datei.
