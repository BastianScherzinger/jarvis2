# JARVIS — TODO / Offene Punkte (Stand 23.06.2026)

## Erledigt 23.06. (Discord-Freigabe-Bot + Mails + Restbrocken)
- [x] **Discord-Freigabe-Bot** (`discord_bot.py` + `review_queue.py`): fertige Seiten
      gehen zur Abstimmung (👍/👎), 2× 👍 ohne Veto → Versand um 12 Uhr an echte
      Kunden. Persistente Buttons, import-sicher, Routen `/api/discord/*` + `/api/reviews`.
      Doku: `workspace/DISCORD_FREIGABE.md`.
- [x] **Bessere E-Mails/Betreffzeilen** (`offer_mail._subject`): variierend pro Betrieb,
      ohne Spam-Trigger; Preis im Body.
- [x] **Higgsfield-Key** in `.env` als kombiniertes `ID:SECRET` gesetzt + Auth robuster
      (`HIGGSFIELD_ID`-Fallback, Kommentare ignoriert). → Cloud-Bild/Video nutzbar.
- [x] **MCP-Brücke** `mcp_bridge.py` (Plan PLAN_MCP_LOCAL_AI.md, P0–P2): Ollama-Tool-
      Calling über SiteTools + optional echte MCP-Server, Render-Gate/Rollback.
      Aktivierung `JARVIS_NIGHTLY_DEEP=mcp`.
- [x] **Erde schärfer** (`globe.js`): anisotrope Filterung (Standorte klarer) + echter
      GLB-Hook (`window.JARVIS_EARTH_GLB`/Meta-Tag) überlagert die Textur-Erde.
- [x] **.env aufgeräumt**: kaputte Umlaut-Kommentare ersetzt, Nightly-/Discord-Variablen
      dokumentiert.


## Erledigt 23.06. (Auto-Adapt + QA/Security + Globus + lokale Sprache + Design)
- [x] **Auto-Adapt CPU/GPU** `hardware_profile.py` (Stufen server…low) → Bildanzahl,
      Cloud-Parallelität, Schritte. Verdrahtet in media_queue (paralleler Cloud-Pool),
      website_improve, media_engine. Route `/api/perf`. Skaliert auf Server hoch.
- [x] **QA/Security/Upgrade-Verfahren** `qa_security.py` (separat) + `/api/qa` —
      compile-all + Security-Scan (0 Findings) + Dependency-Check. Plan 2.
- [x] **Lokale Sprache** `JARVIS_TTS_LOCAL=1` (pyttsx3 offline) + STT lokal.
- [x] **Globus** krasser (globe.js): Fresnel-Atmosphäre, skalierte Marker, Labels,
      Intro-Zoom, Hologramm-Scanlines, GLB optional/Fallback. node --check OK.
- [x] **Hintergrund-Szene** `/api/media/generate/background` → static/img/bg_custom.png +
      Frontend-Hook. **Design-Politur** (additive design-pro-Schicht in style.css).
- [x] **Pläne:** `PLAN_MASTER_FINISH.md` (1) + `PLAN_QA_SECURITY_UPGRADE.md` (2).

## Für Sir (manuell, nicht im Code lösbar)
- [ ] **Echter Kundenversand 9 Uhr:** `JARVIS_EMAIL_REDIRECT` in der .env leeren (sonst
      Test → Bastian); pro Seite „Kontakt finden" füllt die echte Adresse.
- [x] **Higgsfield-Key eingetragen** (23.06.): `.env` → `HIGGSFIELD_API_KEY=ID:SECRET`
      (enigmabible1-Account). Bild-/Video-Cloud nutzt diesen Account.
- [ ] **Kunden-PC aktualisieren:** dort `python update.py` → `python start.py`.
      DB migriert automatisch; Cross-PC-Sync + Globus laufen sofort.
- [ ] **E-Mail am Kunden-PC:** dessen `.env` braucht dieselben `SMTP_USER`/`SMTP_PASS`
      (enigmabible1@gmail.com + App-Passwort) — `.env` wird nicht per Git geteilt.
- [ ] **Echter Kundenversand:** wenn Mails an echte Betriebe gehen sollen, in der `.env`
      die Zeile `JARVIS_EMAIL_REDIRECT=…` leeren/entfernen (aktuell Test → Bastian).
- [ ] **GitHub-Repo-Löschung:** funktioniert nur, wenn das `GITHUB_TOKEN` den Scope
      `delete_repo` hat (sonst bleibt das Repo, Rest wird gelöscht).
- [ ] **Railway-GitHub-App** einmalig verbinden (railway.app → GitHub), falls ein Deploy
      trotz gültiger Tokens nicht baut. Diagnose: im Claude-Reiter „der Deploy klappt nicht".

## Erledigt 22.06. (täglicher 10-Seiten-Builder + Nightly-Improve)
- [x] **10 Seiten/Tag** ab 0 Uhr/Start (`JARVIS_DAILY_SITES`), Reset um Mitternacht,
      kein Stopp bei keine-Leads. Danach **Nightly-Improve** bestehender Seiten bis
      `JARVIS_IMPROVE_UNTIL_HOUR` (10:00).
- [x] **Tages-Historie** `data/daily_builds.json` + `/api/auto-build/daily`.
- [x] **Tagesordner** `…/jarvis_websites/<datum>/web_<slug>/`.
- [x] **E-Mail sichtbar** auf der Webseiten-Karte + „E-Mail ansehen" (Vorschau mit
      klickbarem Live-Link + Erreichbarkeits-Check).
- [x] **Lokaler Improve-Modus** `JARVIS_IMPROVE_LOCAL=1` (Ollama auf GPU statt API).
- [x] **Tiefenmodus umgesetzt** (`JARVIS_NIGHTLY_DEEP=local|claude`): Variante A
      `claude_coder.py` (claude -p, Render-Gate+Rollback), Variante B `local_coder.py`
      (Claude plant → Ollama baut via `local_tools.py` ReAct), `feature_backlog.py`,
      `reference_sites/` als Vorbild, per-Seite `JARVIS_CHANGELOG.md`. Plan:
      `workspace/PLAN_NIGHTLY_DEEP.md`.
- [x] **MCP für lokale KIs** (23.06.): `mcp_bridge.py` umgesetzt (P0–P2) — Ollama-Tool-
      Calling über SiteTools + optional echte MCP-Server, Render-Gate/Rollback.
      Aktivierung `JARVIS_NIGHTLY_DEEP=mcp`. Echte MCP-Server (Filesystem/Playwright via
      Node) als P3+ optional. Plan: `workspace/PLAN_MCP_LOCAL_AI.md`.

## Erledigt 22.06. (32GB-Optimierung + server-fertig)
- [x] **Medien lokal-first + 32GB/CPU:** Auto-Modellwahl (CPU→SD-Turbo schnell),
      CPU-Thread-Tuning, attention-slicing/vae-tiling; `get_status` zeigt RAM+Empfehlung.
- [x] **Server-fertig:** `serve.py` (waitress), `app.server_config()`/`run_server()`,
      HOST/PORT/THREADS via env, `SERVER.md`. Lokales Video braucht GPU (CPU-Guard).

## Bekannte Einschränkungen / später
- [ ] **Higgsfield-Bildpfad** ist nach Doku gebaut, aber ungetestet (kein Key gesetzt).
- [ ] **Globus-Koordinaten:** Stadt-Lookup deckt ~75 Städte ab; unbekannte landen am
      Bundesland-Zentrum (mit Jitter). Bei Bedarf Liste in `globe.js` erweitern.
- [ ] **„An Kunde senden" verschickt echte Werbe-Mails** — bewusst hinter Bestätigung.
      Rechtliches (Impressum/Opt-out) vor breitem Echtversand prüfen.
- [ ] **window._gb** ist als Debug-Global in `globe.js` belassen (harmlos) — bei Bedarf
      entfernen.

## Auto-Builder / neue Features (Stand 22.06.)
- [ ] **Auto-Builder** baut ECHTE Seiten + deployt + mailt — vor Dauerbetrieb prüfen:
      genug GitHub/Railway-Kontingent, Higgsfield/Claude-Token, rechtliches (Opt-out).
- [ ] **E-Mail-Versand** muss am jeweiligen PC scharf sein (JARVIS_EMAIL_ENABLED=true,
      SMTP-Konto). Auto-Builder mailt immer an Bastian.
- [ ] **Erd-Globus-Texturen** kommen vom jsDelivr-CDN (three.js) — bei Offline-Betrieb
      ggf. Texturen lokal in static/img bündeln.
- [ ] **Lead-Findung/Bewertung:** Final-Check grün (alle Module/Tests/Audit). Tiefere
      Scoring-/Scraper-Optimierung bei Bedarf separat (kein Blind-Rewrite gemacht).

## Erledigt 22.06. (Kontakt-Finder / E-Mail-Links / Render-QA)
- [x] **Kontakt-Finder** (`contact_finder.py`): findet E-Mail+Ansprechpartner aktiv
      (DDG→Impressum / Google Places). Verdrahtet: Build-Zeit-Enrichment, Button
      „🔎 Kontakt finden", `offer-email` sucht bei Bedarf selbst. → löst die alte Idee
      „Webseiten rückwirkend mit kontakt_email füllen" on-demand.
- [x] **E-Mail-Links repariert:** `offer_mail._norm_url()` erzwingt https, kein kaputter
      Button ohne Live-Link, nur Live-URL (kein Repo-Link) als CTA, persönliche Anrede.
- [x] **Verbesserungs-Pipeline gehärtet:** `_sanitize_content` + `_render_check` (echtes
      Django-Render vor Deploy) + `_wire_contact`.

## Ideen (nicht beauftragt)
- [ ] Kontakt-Finder auch im Lead-Reiter anbieten (E-Mail-Anreicherung für Leads ohne Bau).
- [ ] Globus: Klick auf Marker → Stadt-Detail/Filter; Heatmap-Modus.
