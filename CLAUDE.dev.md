# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> Hinweis: `CLAUDE.md` ist der **Laufzeit-System-Prompt** der JARVIS-Persönlichkeit und
> wird beim App-Start als Prompt geladen — nicht anfassen. Diese Datei (`CLAUDE.dev.md`)
> ist die **Entwickler-Referenz** für Claude Code und beschreibt die *echte* Architektur.
> Sie wird von Claude Code nicht automatisch geladen; bei Bedarf gezielt lesen.

---

## Was dieses Projekt ist

**JARVIS LeadHunter** — ein Deutschland-weiter **B2B-Lead-Generator**. Mehrere Scraper finden
lokale Unternehmen, ein lokales KI-Team (Ollama) reichert sie an und bewertet sie, das Ergebnis
landet in einer Rangliste und wird per Supabase über mehrere PCs synchronisiert. Flask-Dashboard
auf `http://localhost:5000`, SSE-Live-Updates. Vollständig lokal lauffähig (keine Cloud-KI nötig).

> Achtung Drift: `cloud.md` und die Technik-Abschnitte (5–15) der `CLAUDE.md` beschreiben ein
> **älteres** Multi-Agent-Claude-Dashboard und sind **veraltet**. Maßgeblich ist der Code.

---

## Befehle

```powershell
python start.py        # Hauptstart: Boot-Screen (Hardware-Erkennung + Ollama-Profil-Wahl),
                       # installiert Deps, startet app.py als Subprozess, öffnet Browser :5000
python app.py          # Nur Flask (ohne Boot-Screen / ohne Auto-Install)
```

```powershell
# Dev-Tools (in pyproject.toml als uv dev-dependencies deklariert)
uv run ruff check .            # Linting
uv run ruff format .           # Formatierung
uv run mypy .                  # Type-Checking
uv run pytest                  # Tests (derzeit keine Test-Suite im Repo vorhanden)

# Syntax-Check einer einzelnen Datei (Projekt-Konvention statt Tests)
python -m py_compile pfad/zur/datei.py
```

- Python **>= 3.11**. Windows-zentriert (PowerShell, UTF-8-Reconfigure in `start.py`).
- Externe Voraussetzung: **Ollama** läuft auf `127.0.0.1:11434`. Optional: Playwright-Chromium
  (von `start.py` auto-installiert), ffmpeg, NVIDIA-GPU.
- Legacy-CLI: `python main.py` startet das **alte** Agenten-Team-Menü (`agents/team.py`,
  `orchestrator.py`, `ceo.py`, `tools.py`) — vom LeadHunter entkoppelt, nicht der Haupt-Einstieg.

---

## Architektur — die Lead-Pipeline (großes Bild)

Der Datenfluss durchläuft **drei SQLite-DBs** in `data/` und endet in Supabase. Das zu verstehen
erfordert das Zusammenspiel von `scrapers/controller.py`, den drei `db*.py` und `agents/evaluator/`.

```
            ┌─────────────────────────────────────────────────────────────┐
            │  scrapers/controller.py  — start() spawnt 6 Worker parallel  │
            └─────────────────────────────────────────────────────────────┘
ALLE_REGIONEN × BRANCHEN (~40.000 Combos)  →  gemischt, in 6 disjunkte Chunks geteilt
   │
   ├─ Worker maps          (Google Maps, persistenter Playwright-Browser)
   ├─ Worker gelbe_seiten  ┐
   ├─ Worker dasoertliche  │  HTML-Scraper über scrapers/_http.py
   ├─ Worker elfacht       │  (11880)
   ├─ Worker golocal       ┘
   └─ Worker ai_worker     (Ollama recherchiert via Websuche)
        │
        ▼ schreiben Roh-Leads in
   ┌───────────────┐
   │ db_raw.py     │  "DB1" — Pending-Queue für den Evaluator. Der Feed nutzt die
   │ leads_raw.db  │  raw_id als Lead-ID; das Modal löst raw_id → db_evaluated auf.
   │ (Pending-Queue│  (Die alte leads.db/db.py + verifier.py wurden ENTFERNT.)
   │  für Evaluator│
   └───────┬───────┘
           │  claim_next_pending()  (atomar, status pending→running)
           ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │ agents/evaluator/pipeline.py  — N Threads (JARVIS_EVAL_THREADS=4)    │
   │   1. web_analyst.analyze(lead)        → Website finden + tief prüfen │
   │   2. social_researcher.research(...)  → Social + Firmengröße         │
   │   3. score_writer.evaluate(...)       → Score 0-100 + Pitch + Potenzial│
   │      (deterministischer Basis-Score, Ollama nur Feinschliff)         │
   └───────┬─────────────────────────────────────────────────────────────┘
           ▼ insert_evaluated()
   ┌──────────────────────┐
   │ db_evaluated.py      │  "DB2" — kanonische Rangliste (Score absteigend)
   │ leads_evaluated.db   │  Frontend liest NUR hier (/api/evaluated/*, /api/top)
   └───────┬──────────────┘
           ▼ push_lead() fire-and-forget   +   Batch-Sync alle 10 Min
   ┌──────────────────────┐
   │ cloud_sync.py        │  Supabase (Tabelle jarvis_leads) = primärer Multi-PC-Speicher
   │                      │  Start: pull_and_cache() zieht remote Leads in DB2 lokal
   └──────────────────────┘
```

### Kernkonzepte, die mehrere Dateien verbinden

- **Zwei DBs, klare Rollen** (die alte `leads.db`/`db.py` + `verifier.py` wurden ENTFERNT —
  Konsolidierung 21.06.): `db_raw.py` (`leads_raw.db`) ist die **Pending-Queue** für den
  Evaluator (Feed nutzt die `raw_id` als Lead-ID, Modal löst `raw_id → db_evaluated` auf).
  `db_evaluated.py` (`leads_evaluated.db`) ist die **kanonische Rangliste** + einzige Quelle
  fürs Frontend. Beide: WAL, `check_same_thread=False`, `_lock`, `busy_timeout`, `init_db()`
  mit Spalten-Migration (`_NEW_COLUMNS`). Dashboard-Zähler: `db_raw` (Funde/Quellen) +
  `db_evaluated` (Hot/Warm/Cold).

- **Globaler Dedup-Key:** `lead_key = md5(lower(name)|lower(stadt))` — **EINE** Definition in
  `leadkey.py`, importiert von `db_evaluated` + `cloud_sync`. Supabase hat `UNIQUE(lead_key)`,
  der Upsert nutzt `?on_conflict=lead_key` (echtes Update statt Doppel). `raw_id` ist lokal und
  wird NICHT in die Cloud gesynct.

- **Ollama-Zugang zentralisiert** in `scrapers/_http.py`: `ask_ollama`, `best_chat_model`,
  `warmup_ollama`, `ollama_models`. Eine `Semaphore(2)` begrenzt parallele Ollama-Calls
  (Ollama serialisiert auf der GPU → sonst Timeout-Kaskade). Timeout 180s wegen Kaltstart (30–120s).
  Websuche dort hat einen **globalen Rate-Limiter** (`_SEARCH_MIN_INTERVAL` 1.3s) + Engine-Rotation,
  weil freie Suchmaschinen parallele Server-Requests schnell blocken.

- **Hardware-adaptive KI:** `hardware.py` erkennt RAM/VRAM (ctypes / `nvidia-smi`) und empfiehlt
  ein Ollama-`PROFILES`-Modell (`llama3.2:1b` … `llama3.3:70b`). `start.py` zeigt die Auswahl im
  Boot-Screen und setzt `JARVIS_EVAL_MODEL`.

- **Controller-Lebenszyklus:** `controller.start()` startet Scraper **und** Evaluator;
  `ensure_evaluator_running()` / `reevaluate_all()` starten den Evaluator auch **ohne** Scraper.
  Die Bewertung startet **nicht mehr automatisch** beim Boot — erst über den Start-Button (`/api/start`).

- **Medien-Generierung** (separater Strang): `media_queue.py` (Job-Queue) + `media_engine.py`
  (Diffusers **hardware-adaptiv**: GPU→SDXL/FLUX, CPU→SD-Turbo via `best_image_model`/
  `hero_image_params`; Higgsfield-API für Bild+Video als Cloud-Fallback) + `ad_prompts.py`.
  Routes `/api/media/*`.

- **Webseiten-Bau** (`website_builder.py`): Lead → Landing aus `vorlage_landing/` (Claude-Text +
  Fotos + Hero-Banner) → `agent_github.py` (Repo+Push) → `agent_railway.py` (Projekt+Domain+Env).
  Async-Job mit Schritt-Log; Routes `/api/lead/<id>/website` + `/api/website/job/<id>`.
  Higgsfield-Cloud-Hero nur auf Rückfrage (`use_higgsfield`).

### Flask-API (`app.py`, Port 5000)

- Steuerung: `/api/start`, `/api/stop`, `/api/status`, `/api/clear` (leert db_raw + db_evaluated).
- Rangliste (DB2): `/api/evaluated/all` (Filter/Sort/Suche), `/api/evaluated/top`,
  `/api/evaluated/reeval`, `/api/export/csv` (Semikolon + BOM für deutsches Excel).
- Live: `/api/stream` (SSE — Lead-/Stats-/Evaluated-Events, Keepalive alle 20s).
- Lead-Aktionen: `/api/lead/<id>/status|email|mockup|competition`.
- Cloud/Graph/Logs/Medien: `/api/sync`, `/api/graph/*`, `/api/logs`, `/api/media/*`.

---

## Konventionen & Stolperfallen

- **Code-Sprache ist Deutsch** — Variablennamen, Spalten, Log-Texte, Kommentare. Beibehalten.
- **Keine schweren Abhängigkeiten** für System-Tasks: RAM/GPU via `ctypes`/`subprocess`,
  HTTP/Ollama/Supabase via `urllib` (kein `requests` im Kern, kein `psutil`). Stil beibehalten.
- **`.env` niemals committen** (gitignored). Geheim: `ANTHROPIC_KEY`, `SUPABASE_SERVICE_KEY`.
  `cloud_sync` erzwingt HTTPS und loggt Keys nie.
- **Wichtige Env-Variablen:** `JARVIS_AI_MODE` (`local`), `JARVIS_EVAL_MODEL`,
  `JARVIS_EVAL_THREADS` (Default 4), `JARVIS_VERIFIER_THREADS` (Default 0 = alter Verifier aus),
  `JARVIS_VERIFIER_MODEL`, `JARVIS_BROWSER_HEADLESS`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
  `HF_TOKEN` (nur für gated Bildmodelle wie FLUX).
- **Worker schreiben über Queue, nie direkt ins Frontend:** alles geht über `controller._on_lead`
  → `_lead_queue` → SSE. Neue Worker diesem Muster folgen lassen.
- **Score-Robustheit:** `score_writer` liefert immer einen deterministischen Basis-Score; Ollama
  ist nur Feinschliff. Fällt Ollama aus, bleibt die Bewertung gültig — diese Garantie nicht brechen.
