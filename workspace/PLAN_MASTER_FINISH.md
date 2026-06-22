# Plan 1 — Master Finish: alles fertig & ready

Ziel: Programm bugfrei & ready; ab Start baut es tagsüber, **morgen 9 Uhr** stehen 10
fertige, ausgebaute & geprüfte Webseiten zum Versand an 10 Kunden. Auto-adaptiv auf
CPU/GPU — auf einem starken Server skaliert alles hoch.

## A. Auto-Adapt CPU/GPU (umgesetzt — `hardware_profile.py`)
Eine Quelle der Wahrheit: erkennt Kerne/RAM/GPU/VRAM → Leistungsstufe
`server | workstation | desktop | laptop | low` (override: `JARVIS_PERF_TIER`).
Skaliert automatisch:
| Stufe | Bild-Schritte | Bilder/Verbesserung | Cloud-parallel | Nightly/Runde |
|-------|:---:|:---:|:---:|:---:|
| server | 40 | 6 | 4 | 3 |
| workstation | 32 | 5 | 3 | 2 |
| desktop | 26 | 4 | 2 | 1 |
| laptop | 4 | 3 | 2 | 1 |
| low | 2 | 2 | 1 | 1 |
Verdrahtet: `media_queue` (paralleler Cloud-Worker-Pool für Higgsfield — lokale GPU
bleibt seriell), `website_improve` (Bildanzahl), `media_engine.get_status` (perf_tier/
summary), Routen `/api/perf`. Lokale Bild-Auto-Wahl (CPU→SD-Turbo, GPU→SDXL/FLUX) bleibt.

## B. Tägliche 10 Seiten + Versand 9 Uhr (vorhanden, geprüft)
`auto_builder`: ab Start/0 Uhr bis `JARVIS_DAILY_SITES` (10) bauen → deployen →
verbessern → E-Mail an Bastian; Tages-Historie `data/daily_builds.json`
(`/api/auto-build/daily`); Tagesordner `jarvis_websites/<datum>/`. Danach Nightly-
Verbesserung bis `JARVIS_IMPROVE_UNTIL_HOUR` (10:00). E-Mail mit **funktionierendem
Live-Link** (normalisiert + Erreichbarkeits-Check, Vorschau im Webseiten-Tab).
> Für **echten Kundenversand 9 Uhr** statt Test-an-Bastian: in `.env`
> `JARVIS_EMAIL_REDIRECT` leeren; pro Seite „Kontakt finden" füllt die echte Adresse.

## C. Verbesserungs-/Bau-Pipeline-Upgrade (umgesetzt)
- Bildanzahl der Verbesserung jetzt hardware-skaliert (2…6).
- Tiefenmodus `JARVIS_NIGHTLY_DEEP=local|claude` baut echte Features (mit Render-Gate +
  Rollback) — Seiten werden „richtig ausgebaut".
- 7-Pass-Verbesserung (Stratege→Texter→UX→Bilder→Design-Pro→Taste→QA) + Render-QA.

## D. Lokale Sprache (umgesetzt — `tts.py`)
`JARVIS_TTS_LOCAL=1` erzwingt pyttsx3 (offline, Server-tauglich); STT lokal via
faster-whisper. Ohne Flag: edge-tts (Neural) mit pyttsx3-Fallback.

## E. Globus / Satellit (umgesetzt — `globe.js`, Agenten-Team)
Realistische Textur-Erde + Fresnel-Atmosphäre, bessere Standort-Marker (Größe/Helligkeit
∝ Lead-Anzahl, Farbe nach Typ, Light-Beams, Ping-Ringe), Stadt-Labels (Top-Städte),
cinematischer Intro-Zoom auf Deutschland, Hologramm-Scanlines, GLTFLoader optional mit
Fallback, Low-Power-Drosselung, kein Memory-Leak, WebGL-Fallback.

## F. Hintergrund-Szene (umgesetzt — Wiring)
Route `POST /api/media/generate/background` erzeugt ein stimmiges HUD-Szene-Bild
(lokal/Higgsfield) → `static/img/bg_custom.png`; Frontend wendet es automatisch an
(`_applyCustomBg`). **Szene-Prompt** (für ein krasses Hintergrund-Video im Video-Tab):
> „cinematic slow flythrough of a futuristic JARVIS command center, dark control room,
> floating holographic blue data panels and a glowing 3D earth, arc-reactor light,
> volumetric haze, 4k, no text" (Higgsfield Dop Turbo).

## G. Design-Politur (umgesetzt — `style.css`)
Additive design-pro-Schicht: weiche mehrschichtige Schatten, ruhige Hover/Übergänge,
konsistente Fokus-Ringe (a11y), dezenter Tab-Einblendeffekt, schlanke Scrollbars —
`prefers-reduced-motion` respektiert, bestehende Funktion unangetastet.

## H. Komplett-Check
Tests (Suite) + `smoke_audit.py` + **separates QA-/Security-Verfahren** (`qa_security.py`,
siehe Plan 2) grün. Alle Module kompilieren, importieren, Daily-Flow verifiziert.

## Offen / nächster Ausbau
- Echte Erd-GLB als primäres Asset (aktuell Textur-Erde, GLB optional/Fallback).
- MCP-Bridge für lokale KIs (siehe `PLAN_MCP_LOCAL_AI.md`).
- Higgsfield-Key als `ID:SECRET` (aktuell nur ein Token ohne `:` → Cloud-Bild/Video
  authentifiziert sonst nicht).
