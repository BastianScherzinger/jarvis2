# Plan — "Eigene Marke"-Modus (manueller Custom-Build)

> Ziel: Ein Modus wie der Auto-Builder, aber Sir gibt **Name, Logo, Hero-Hintergrund und
> Beschreibung selbst** vor. Die Seite wird mit allen Skills + lokalen KIs + JARVIS
> gebaut, über Nacht verbessert und am Ende an **11+ E-Mail-Empfänger** geschickt —
> über denselben Discord-Freigabe-Gate.

## A. Eingaben (Dashboard-Tab "Eigene Marke")
Firmenname · Branche · Stadt · Beschreibung (Freitext) · Telefon/E-Mail/Adresse (optional)
· Logo (Upload, optional) · Hero-Hintergrund (generieren via Prompt | hochladen | keiner)
· Empfänger-Liste (eine E-Mail pro Zeile, 11+ möglich).

## B. Bau-Pipeline (wiederverwendet, nicht neu erfunden)
`custom_build.start(data)` →
1. Uploads sicher unter `workspace/custom_uploads/<slug>/` ablegen.
2. Lead-Dict bauen: `name/branche/stadt/beschreibung/telefon/email/adresse` +
   `_custom = {logo_path, hero_path, hero_prompt}`.
3. `website_builder.build(lead)` — dieselbe Engine:
   - `_claude_content` nimmt **Beschreibung** als zusätzlichen Kontext (design-pro-Prompt).
   - `_run` honoriert `_custom`: Logo → `static/img/logo.png` (+ `content.logo_image`),
     hochgeladenes Hero → `static/img/hero.png` (Generierung übersprungen), sonst
     `hero_prompt` als Generierungs-Prompt (lokal/Higgsfield, hardware-adaptiv).
4. Watcher-Thread: Build fertig → `improve_existing` (7-Pass + Render-Gate) → Discord-Review.

## C. Versand an 11+ Empfänger
- `review_queue.add(..., recipients=[...])` speichert die Empfängerliste.
- Nach **2× 👍** (kein 👎): um 12 Uhr sendet `discord_bot.send_approved_now()` das
  Angebot an **jede** Empfängeradresse (bypass_redirect, echter Versand). Ohne Liste
  greift die Einzeladresse wie gehabt. Drossel `JARVIS_EMAIL_RATE` (20/h) deckt 11+ ab.

## D. Über-Nacht-Verbesserung
Custom-Seiten sind normale `db_websites`-Zeilen → der Nightly-Improver (`_pick_improve_target`)
nimmt sie automatisch mit (Inhalt/Design oder Tiefen-Feature je `JARVIS_NIGHTLY_DEEP`).

## E. Template (rückwärtskompatibel)
`vorlage_landing/templates/index.html`: Marke zeigt `c.logo_image` als Bild, sonst
`c.site_name` (Text). Hero nutzt bereits `c.hero_image`. Keine bestehende Seite bricht.

## F. Zweiter PC / Auto-Install
`install.py` macht `pip install -r requirements.txt` → `discord.py` (neu in requirements)
wird automatisch mitinstalliert. Keys werden nach `~/.claude/.env` gesynct. `update.py`
zieht den Code per `git pull`. Nichts manuell nötig außer Discord-Token in `.env`.

## G. Tests / QA
Neue Tests: custom-Lead-Aufbau, recipients-Versand-Schleife, Template-Logo-Slot.
Danach `pytest` + `smoke_audit.py` + `qa_security.py` grün, dann Push.
