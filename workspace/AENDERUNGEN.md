# JARVIS LeadHunter — Änderungsprotokoll

> Vollständige Liste aller Umbauten dieser Arbeitsphase. Stand: 19.06.2026.
> Reihenfolge: das neue Feature zuerst, dann die früheren Durchgänge, dann offene Punkte.

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
