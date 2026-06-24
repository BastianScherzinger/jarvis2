# JARVIS LeadHunter — Änderungsprotokoll

> Vollständige Liste aller Umbauten dieser Arbeitsphase. Stand: 24.06.2026.
> Reihenfolge: das neue Feature zuerst, dann die früheren Durchgänge, dann offene Punkte.

---

# Durchgang 24.06.2026 (7) — Lead-Generierung: kostenlos bestätigt, max Threads, echtere Preise

> Sir: Lead-Gen kostenlos + parallel (max Threads), erst Daten sammeln/speichern, dann lokale
> KI bewertet, realistischere Preise — sauber & günstig.

## Kostenlos — bestätigt (keine Änderung nötig)
Die gesamte Lead-Pipeline ist bereits **gratis**: Stufe 1 Scraper (`scrapers/maps.py` via
Playwright-Browser — NICHT die bezahlte Places-API; gelbe_seiten/dasoertliche/elfacht/golocal
= Verzeichnis-Scraper) → `leads_raw.db`. Stufe 2 Evaluator (`web_analyst` via DuckDuckGo+urllib,
`social_researcher`, `score_writer` + `name_clean` via **Ollama**) → `leads_evaluated.db`.
Claude/OpenAI werden NUR im Chat-Agenten genutzt, nicht in der Lead-Gen. (`agent_maps.py` mit
Google-Places-API ist nur das Claude-Tool, nicht die Pipeline.)

## Zwei-Stufen-Fluss (bestätigt)
Genau wie gewünscht: Scraper findet Adresse/Bilder/URL/Daten und **speichert** sie (db_raw,
Status pending) → Evaluator-Thread holt den nächsten Lead, lokale KI findet Website/Bilder +
**bewertet + Beschreibung/Pitch** → schreibt db_evaluated → nächster Lead.

## Maximale Threads
`scrapers/controller.py`: Evaluator-Threads default = **CPU-Kerne** des PCs
(`min(32, max(4, os.cpu_count()))`, vorher fix 4); per `JARVIS_EVAL_THREADS` überschreibbar.
Die Ollama-Parallelität ist jetzt per `JARVIS_OLLAMA_PARALLEL` (Default 2, schützt das Modell)
konfigurierbar — so parallelisiert die Bewertung maximal, ohne das Modell zu überlasten.

## Realistischere Preisbewertung (`score_writer._preis_tier`)
Statt nur an einer Score-Schwelle zu hängen, bildet die Heuristik (Fallback, wenn Ollama keinen
Tier liefert) jetzt einen **mehrfaktoriellen Wert-Index**: Branchen-Zahlkraft + Bedarf (Score) +
Etabliertheit (Bewertungen ≥20/≥80) + Firmengröße + Upgrade-Motiv (veraltete Website) + gutes
Rating → realistischer Tier (0/200/350/550/850/1200 €). Beispiele: Zahnarzt o. Website/40 Bew.→
850 €, Mini-Kiosk→200 €, alter Dachdecker-Betrieb m. 50 Bew.→850 €, gute aktuelle Website→0 €.

---

# Durchgang 24.06.2026 (6) — Higgsfield als Standard-Hero-Engine (Abo), OpenAI bleibt optional

> Sir: OpenAI-API kostet extra, nicht nötig — drin lassen, aber Bilder standardmäßig über
> Higgsfield (Abo). (Teil „viaSocket/Filora-MCP" offen — Rückfrage gestellt.)

- `media_engine.hero_engine()` (`JARVIS_HERO_ENGINE`, Default **higgsfield** | openai | local | auto)
  + `media_engine.generate_hero_cloud()` — zentrale Cloud-Hero-Quelle mit Fallback-Kette;
  OpenAI nur, wenn ausdrücklich gewählt.
- `website_builder.build`: Hero-Block nutzt jetzt `generate_hero_cloud` (Default Higgsfield) →
  lokal → Farbverlauf. (Vorher war OpenAI Quelle 0.)
- `overnight_makeover`: `_ensure_openai_hero` → `_ensure_hero` (Engine-agnostisch, Default
  Higgsfield); `content["hero_source"]` = genutzte Engine; Skip, wenn schon `higgsfield`/`openai`.
- `auto_builder`: Limit-Fallback `_openai_only_progress` → `_cloud_hero_progress` (Higgsfield-Default).
- OpenAI bleibt vollständig erhalten: im Medien-Reiter manuell wählbar + als Engine-Option.

---

# Durchgang 24.06.2026 (5) — Medien-Studio (1 Reiter), ChatGPT-Bilder, Video-1010-Fix, Limit-Resilienz

## 1. Bilder + Video zu EINEM Reiter „Medien" zusammengefasst
- Navigation: statt „Bilder" + „Videos" jetzt **ein** Button „Medien" (`data-page="media"`).
- `templates/index.html`: ein `<main data-page="media">` mit **Modus-Umschalter** (🖼 Bild / 🎬 Video),
  zwei Panels `#media-mode-image` / `#media-mode-video` (alte Inhalte + IDs übernommen).
- `app.js`: `setMediaMode()`, `_PAGES` (images/videos → media), `showPage('media')` lädt Modelle/
  Galerien/Leads + beide Backends. CSS: `.media-mode-switch`/`.mode-btn` (segmentierter Toggle).
- Verifiziert (Playwright): Umschalten Bild⇄Video, beide Galerien, keine relevanten Konsolenfehler.

## 2. ChatGPT (OpenAI) als wählbare Bild-Engine
- Bild- UND Werbe-Set-Backend-Dropdown haben jetzt **ChatGPT (OpenAI · gpt-image-1)**.
- `app.py` Route `/api/media/generate/image` → Backend `openai` → `media_queue.submit("openai_image")`.
- `media_queue`: `openai_image` als Cloud-Kind + Worker-Zweig → `media_engine.generate_image_openai`;
  Asset-Set unterstützt `backend=openai`. `onImgBackend()` blendet Modellwahl aus + zeigt Hinweis;
  ohne Key wird die Option ausgegraut und auf „lokal" zurückgestellt.
- Verifiziert: Job-Typ `openai_image` läuft, Billing-Fehler sauber als Job-Error.

## 3. Video-Fehler „Higgsfield 1010" behoben (Cloudflare-Block)
- Ursache: Cloudflare-Error **1010** („browser signature banned") — die urllib-Requests hatten
  keinen Browser-User-Agent. Trifft auch „lokal", weil das auf CPU automatisch auf Higgsfield
  umschaltet.
- Fix in `media_engine`: konstanter **Browser-User-Agent** + Origin/Referer/Accept in `_hf_headers`,
  Browser-UA bei allen Poll-/Download-Requests (Bild + Video). Neuer `_hf_error_hint()` erklärt
  1010 / 401-403 / 402-credits / 404 in Klartext. Logging via `_mlog` (`JARVIS_MEDIA_DEBUG=1`).
- Lokales Video: klares Log, dass auf CPU automatisch die Higgsfield-Cloud genutzt wird.
- **Caveat:** die LIVE-Higgsfield-Calls brauchen gültigen Key + Credits zur Endbestätigung — der
  1010/Header-Fix ist eingebaut, der eigentliche Generierungslauf ist mit Sirs Key zu prüfen.

## 4. Claude-/ChatGPT-Limit-Resilienz im Night-Builder
- Makeover meldet ein Claude-Session-Limit jetzt SCHNELL zurück (`JARVIS_MAKEOVER_LIMIT_RETRIES`
  Default **0** statt 7) — `auto_builder` orchestriert:
  - **Claude-Limit erkannt** (`_note_job_limit`) → `_handle_exhaustion()`:
    erst „ein bisschen ChatGPT" (`_openai_only_progress` erneuert Hero-Bilder via OpenAI = echter
    Fortschritt ohne Claude).
  - **Beide leer** (Claude-Limit + kein/erschöpftes OpenAI) → `stop()` + `_schedule_restart()`
    (Timer): nach `JARVIS_EXHAUST_WAIT` (Default 1 h) automatischer Neustart/Re-Test.
  - Bei Limit wird die Seite NICHT als „stuck" markiert (nach Neustart wieder dran).

---

# Durchgang 24.06.2026 (4) — Token-Sparmaßnahmen: Makeover lief Session-Limit leer

> Symptom: „die meisten Seiten hängen bei ~100 % nach dem ersten Schritt, Token-Limit zu
> schnell voll." Ursache war massiver Token-Verbrauch pro Stufe. Komplett überarbeitet.

## Ursache
Jede der 7 Stufen wies den headless Makeover-Claude an, ein Skill **komplett** zu laden:
`ui-ux-pro-max` = **45 KB**, `taste` = **88 KB**. Stufen 1–4 + 7 luden je das 45-KB-Skill,
Stufe 6 das 88-KB-Skill → **~313 KB Skill-Text pro Seite**, das in jeder der ~32 Tool-Runden
im Kontext mitlief. Dazu der volle content.json-Dump (3,5 KB) in JEDEM Stufen-Prompt. Das
Claude-Code-Session-Limit war nach 1–2 Stufen leer → Pipeline pausierte (sah aus wie „hängt").

## Maßnahmen
- **Kompaktes Skill:** 6 Stufen nutzen jetzt `design-pro` (**5 KB**, bündelt ui-ux-pro-max/
  impeccable/taste/frontend-pro/shadcn) statt `ui-ux-pro-max` (45 KB). Das große `taste`
  (88 KB) lädt nur noch EINMAL — in der dedizierten Design-Stufe. → ~313 KB → **~118 KB/Seite**.
- **Kein content.json-Dump mehr im Prompt:** Claude liest content.json selbst aus dem Ordner.
  Stufen-Prompt **6262 → 2362 Zeichen** (−62 %).
- **Stufen-Laufzeit** dadurch ~321 s → **~129 s** (verifiziert, Stufe Hero) — Proxy für ~60 %
  weniger Tokens. Mehr Stufen passen ins selbe Session-Budget.
- **Status sichern:** unverändert je Stufe `makeover_stages` + Git-Commit (resume-fähig).
- **Limit-Anzeige gefixt:** Beim Session-Limit-Warten zeigt der Balken den AKTUELLEN
  Stufen-Fortschritt statt auf 95/100 zu springen (kein falsches „fertig").

## Lokal ausgelagert (32-GB-Maschine sinnvoll genutzt)
- **Build-Texte via Ollama:** `website_builder._ollama_content` erzeugt Headline/Subline/
  Über-uns/Leistungen/SEO LOKAL (qwen2.5) zuerst; Claude-API nur noch Fallback, dann
  Deterministik. Spart API-€. Schalter `JARVIS_BUILD_CONTENT_LOCAL=0` deaktiviert.
- **Rechtstexte lokal (0 Tokens):** neues `legal_pages.py` erzeugt Impressum (§5 DDG),
  Datenschutz (DSGVO) und AGB deterministisch aus den Betriebsdaten. `overnight_makeover.
  _ensure_legal` schreibt sie in content.json (impressum/datenschutz/agb). Die QA-Stufe
  **rendert + verlinkt** sie nur noch (erzeugt sie nicht) → deutlich weniger Claude-Arbeit.

## OpenAI-Hinweis (aus dem Live-Test)
Der OpenAI-Key ist gesetzt, aber die API meldet **„Billing hard limit has been reached"** →
ChatGPT-Hero wird sauber übersprungen (Makeover läuft weiter), `hero_source` bleibt offen und
wird beim nächsten Lauf erneut versucht. **To-do Sir:** OpenAI-Guthaben/Ausgabenlimit erhöhen
(platform.openai.com → Settings → Limits/Billing).

---

# Durchgang 24.06.2026 (3) — ChatGPT-Hero-Bilder (gpt-image-1) mit Tageslimit

> Hero-Bilder kommen jetzt standardmäßig von **OpenAI gpt-image-1** (ChatGPT) — hochwertig,
> fotorealistisch, lead-angepasst, hardware-unabhängig. Kostengedeckelt über ein Tageslimit.

## Was Sir tun muss (Setup)
1. OpenAI-API-Key erstellen: https://platform.openai.com/api-keys (Billing/Guthaben aktiv).
2. In die `.env` eintragen: `OPENAI_API_KEY=sk-...`
3. Optional: `JARVIS_OPENAI_IMAGE_DAILY_MAX=30` (Kostendeckel/Tag, 0 = aus),
   `JARVIS_OPENAI_IMAGE_QUALITY=medium` (low|medium|high).
4. Auf dem Bau-PC `git pull` + Programm neu starten.
Ohne Key passiert nichts Schlimmes — es wird automatisch auf Higgsfield/lokal/Farbverlauf
zurückgefallen.

## Implementierung
- **`media_engine.py`** — neuer OpenAI-Backend: `openai_available()`, `generate_image_openai()`
  (gpt-image-1, Landscape 1536×1024, b64→PNG), `hero_master_prompt()` (ausführlicher,
  branchen-/lead-angepasster Master-Prompt, kein Text/Logo), Tageszähler in
  `data/openai_image_usage.json` (`openai_quota_left()`, `openai_daily_max()`), Status-Felder
  in `get_status()`.
- **`cost_tracker.py`** — `track_openai_image(quality)` bucht die Bildkosten (Schätzung nach
  Qualität) ins Tages-Tracking (api_eur + images_generated).
- **`website_builder.py`** — beim Bau ist OpenAI jetzt **Quelle 0** (vor Higgsfield/lokal):
  Master-Prompt aus Lead-Daten, `content["hero_source"]="openai"`. Custom-Hero-Prompt schlägt
  weiterhin den Standard; ein hochgeladenes Hero wird nie überschrieben.
- **`overnight_makeover.py`** — `_ensure_openai_hero()` ersetzt das Hero-Bild zu Beginn des
  Makeovers EINMAL durch ein frisches ChatGPT-Bild (nur wenn noch nicht `hero_source=openai`
  und Tageslimit frei) → die Design-Stufen bauen darauf auf. So werden bestehende Seiten beim
  Night-Build auf aktuelle ChatGPT-Bilder gehoben.
- **`auto_builder.py`** — `_pick_improve_target` zieht bei Gleichstand jetzt die **neueste**
  Seite zuerst (statt der ältesten), damit die neusten Seiten zuerst aufgewertet werden.

## „Es hat sich nichts geändert" — Erklärung
Die bestehenden Seiten standen alle auf `makeover_stages=[]` und wurden vom alten (kaputten)
Makeover nie verbessert (siehe Durchgang 2, Prompt-Verstümmelung). Mit dem stdin-Fix laufen
die Stufen jetzt real (verifiziert). Da die Stufen-Keys neu sind, zeigen alle Seiten mit
lokalem Ordner `open=7` → der Night-Build zieht sie automatisch komplett neu durch (neue
Skills + ChatGPT-Hero). **Wirksam wird das erst nach `git pull` + Neustart auf dem Bau-PC.**

---

# Durchgang 24.06.2026 (2) — Makeover-Hänger gefixt + Abschnitts-Stufen + Tages-Links

> Detail-Referenz: `workspace/MAKEOVER_PIPELINE.md`. Auslöser: Seiten wurden gebaut, blieben
> aber im Standard-Design; die Makeover-Prozesse „hingen bei Stufe 1" — keine Seite wurde je
> verbessert (alle auf `makeover_stages=[]`).

## 0. Root-Cause: Prompt-Verstümmelung über cmd.exe (KERN-FIX)
Der Headless-Makeover gab `claude_coder.run_prompt` den langen Stufen-Prompt (~6300 Zeichen,
mit content.json-Dump voller `"` `&` `<` `>` `|`) als **Kommandozeilen-Argument** mit. `claude`
ist auf Windows `claude.cmd` (Batch) → der Prompt lief durch cmd.exe und wurde am ersten
Sonderzeichen **abgeschnitten**. Claude sah nur einen Prompt-Torso (ohne die eigentliche
Aufgabe) und antwortete **konversationell mit einem Menü** statt zu editieren → 0 Datei-
Änderungen → Stufe nie als erledigt markiert → ewig „Stufe 1".
**Fix:** `claude_coder.run_prompt` übergibt den Prompt jetzt über **STDIN** (`subprocess.run(...,
input=prompt)`), nicht als argv. Diagnostisch bestätigt: via argv → vage Rückfrage, 0 Änderungen;
via stdin → 32 Tool-Turns, Dateien geändert, Stufe sauber abgeschlossen.
- `JARVIS_CLAUDE_TIMEOUT` Default 900 → **1200 s** (die schwere Design-Stufe braucht länger).
- End-to-end verifiziert: `run_makeover` Stufe „Hero" ~320 s, content.json `makeover_stages=['hero']`,
  Git-Commit gesetzt.

## 1. Die 7 Stufen sind jetzt ABSCHNITTS-orientiert (`overnight_makeover.STAGES`)
Statt Design-Facetten baut jede Stufe einen echten Seitenbereich aus — exakt nach Vorgabe:
1. **Hero-Bereich** (ui-ux-pro-max) — Premium-Hero, Nutzenversprechen, 1 primärer CTA, Vertrauen.
2. **Beschreibung & Dienstleistungen** (ui-ux-pro-max) — Leistungs-Grid, FAQ, betriebsgenau.
3. **Über uns & Vertrauen** (ui-ux-pro-max) — Story, Referenzen, USPs, about_image.
4. **Kontakt-Bereich** (ui-ux-pro-max) — tel/mailto, Adresse, Öffnungszeiten, OSM-Karte.
5. **Kontakt-Formular** (design-pro) — funktionsfähiges Form (csrf, required, Einwilligung).
6. **Komplett-Design (taste)** (design-taste-frontend) — großer Design-Durchgang über die
   ganze Seite: Tokens/Farbe, Typo, Spacing, Schatten, Motion, Anti-Slop.
7. **QA, Datenschutz, AGB & Impressum** (ui-ux-pro-max) — rechtliche Pflichtseiten (DSGVO/DDG,
   fehlende Daten als `[bitte ergänzen]` statt erfunden) + Schluss-QA + Responsive.

Alte Keys (`inhalt/layout/...`) entfallen; alle Seiten standen ohnehin auf `[]` (keine Migration nötig).

## 2. Deploy + „erledigt" + nächste Seite
Unverändert korrekt: `website_builder._run_makeover` deployt **einmal am Ende** (alle Stufen-
Commits gepusht), setzt den Job auf `done`; `open_stages==0` markiert die Seite als fertig
makeovert. Der Night-Builder zieht über `_pick_improve_target()` (meiste offene Stufen zuerst)
Seite für Seite, bis alle auf 7/7 sind.

## 3. Abschluss-Discord mit allen heutigen Links zum Bewerten (`auto_builder`)
Neu `_today_links()` (aus `data/daily_builds.json`, dedupliziert). `_farewell_if_done()` postet
jetzt EINE Discord-Nachricht mit **allen heute gebauten Seiten als klickbare Markdown-Links**
(`[Name](url)` im Embed) zum Bewerten — sicher unter dem 4096-Zeichen-Embed-Limit. Die
per-Seite-Freigabe (1× 👍 = Kunden-Mail) bleibt zusätzlich bestehen (Funktion vor Design).

---

# Durchgang 24.06.2026 — Eigene-Marke-Builder, echte Skills, robustes Makeover

> Detail-Referenz: `workspace/MAKEOVER_PIPELINE.md` + `CLAUDE.dev.md`.

## A. „Eigene Marke"-Reiter = echter Zwei-Schritt-Builder (`custom_build.py`, `app.js`)
- Aufgeteilt in **Schritt 1 `start()`** (nur bauen + deployen) und **Schritt 2 `improve()`**
  (7-Stufen-Skill-Makeover, beliebig oft wiederholbar) — kein Auto-Pilot mehr.
- **KI-Vorschläge** (`suggest()`): lokal via Ollama (`ask_ollama`) mit deterministischem
  Fallback → füllt Branche/Beschreibung/Tagline/Hero-Prompt/Leistungen.
- **Persistenz:** Formular + aktiver Job in `localStorage` (`jarvis.cb.*`) → überleben Reload;
  unbekannter Job nach Server-Neustart wird im Poll erkannt und das Panel zurückgesetzt.
- Tab ist jetzt **scrollbar** (`.custom-page` Scroll-Container). Formular-Empfänger werden in
  `content.json["custom_recipients"]` gesichert und von `finalize_review` an Discord gereicht.
- Neue Routen: `/api/custom-build/improve`, `/api/custom-build/suggest`.

## B. Webseiten-Reiter repariert (vom anderen PC eingeschleppte Bugs)
- **Typografische Anführungszeichen** (U+201D) als Attribut-Delimiter im gesamten
  Webseiten-Block → `class="websites-page"`/`data-page="websites"` griffen nicht, Reiter tot.
  Alle Attribut-Quotes auf gerade ASCII korrigiert.
- **CSS-Kollision** `.ws-bar` (Toolbar UND 6px-Fortschrittsbalken) → Toolbar gestaucht.
  Toolbar in `.ws-toolbar` umbenannt.

## C. Echte Design-Skills ins Projekt (`skills/`, `claude_skills.py`)
- `ui-ux-pro-max` (nextlevelbuilder) und `design-taste-frontend` (Leonxlnx/taste-skill) von
  GitHub ins Repo unter `skills/<name>/SKILL.md` vendored → auf jedem PC nach `git pull` da.
- `claude_skills.ensure_installed()` spiegelt `skills/` → `~/.claude/skills/` (App-Start +
  `start.py` + `install.py`) — nötig, weil der headless Makeover-Claude im Webseiten-Ordner
  läuft und dort nur user-globale Skills sieht. (Früher referenzierten Stufen 5/6 die nicht
  existierenden Skills `taste`/`frontend-design` → liefen ohne Skill.)

## D. Makeover-Stufen optimiert (`overnight_makeover.py`)
- Stufen je mit dem stärksten echten Skill: Inhalt/Layout/Typografie/Farbe/Responsive =
  `ui-ux-pro-max`, Politur = `design-taste-frontend`, Motion = `design-pro`.
- `_context_block` reichert JEDEN Prompt mit den dokumentierten Lead-Details an
  (`beschreibung`, `pitch_hook`, `firmengroesse`, `potenzial_begruendung`, Adresse/Telefon/
  Ansprechpartner aus db_evaluated über `lead_id`) + volle content.json. Prompt nennt
  Premium-Ziel + Schritt N/7 und weist an, das Skill AKTIV via Skill-Tool zu nutzen.

## E. Night-Builder: alle Seiten fertigstellen + Verabschiedung (`auto_builder.py`)
- Phase 2 fährt nach der Bauphase ALLE bestehenden Seiten durch den 7-Stufen-Weg, bis jede
  auf 7/7 ist. Sind dann alle fertig: EINMALIGE Discord-Verabschiedung via neuem
  `discord_bot.notify()` (Latch `_farewell_sent`; reset bei Start/Tageswechsel/neuer Arbeit).
  Neue Helfer `_all_sites_complete` / `_farewell_if_done`.

## F. Robustheit bei Claude-Session-Limit (`overnight_makeover.py`)
- Erkennt `run_makeover` ein Usage-/Session-Limit, **wartet es 1 h und versucht dieselbe
  Stufe erneut — bis zu 7×** (`JARVIS_MAKEOVER_LIMIT_WAIT`=3600, `_RETRIES`=7; Wartezeit per
  `stop()` unterbrechbar). Erst danach pausiert es (Resume später). Builder-Warte-Limit
  `JARVIS_MAKEOVER_WAIT` darum auf 36000 s/10 h erhöht.

## G. Startup-Setup abgesichert (`start.py`, `app.py`, `install.py`, `claude_coder.py`)
- `claude_coder.ensure_cli()`: best-effort `npm i -g @anthropic-ai/claude-code`, falls die
  claude-CLI fehlt (ohne sie kein Makeover). Beim Boot sichtbar in `start.py`; App-Startthread
  und `install.py` sichern Skills + CLI zusätzlich ab. Hinweis: CLI auf neuem PC einmal
  anmelden (`claude`), Node.js + Ollama nötig.

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
