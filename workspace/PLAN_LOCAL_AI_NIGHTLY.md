# Plan — Lokale KI / Claude Code: Seiten den ganzen Tag verbessern (GPU)

Ziel: Der GPU-PC baut pro Tag 10 Seiten und verbessert danach bestehende Seiten
**lokal** weiter — bis 9–10 Uhr — sodass sie immer besser werden und mehr Features
bekommen. Stand: Fundament umgesetzt, Claude-Code-Tiefenmodus als Plan + Schalter.

## 1. Was bereits umgesetzt ist (läuft)
- **Täglicher Rhythmus** (`auto_builder.py`): ab Start und ab 0 Uhr → Phase 1 baut bis
  `JARVIS_DAILY_SITES` (10) neue Seiten; Phase 2 verbessert bestehende Seiten rundlaufend
  bis `JARVIS_IMPROVE_UNTIL_HOUR` (10 = 10:00); Phase 3 Pause bis Mitternacht.
- **Tages-Historie** `data/daily_builds.json` (+ Route `/api/auto-build/daily`): welche
  Seiten an welchem Tag gebaut wurden (Name, Stadt, Link, E-Mail, Ordner).
- **Tagesordner** `…/jarvis_websites/<JJJJ-MM-TT>/web_<name>/` — sortiert pro Tag.
- **Lokaler Verbesserungs-Modus** (`JARVIS_IMPROVE_LOCAL=1`): die Verbesserungs-Pässe
  (`website_improve`) laufen über das lokale **Ollama-Modell** statt der Claude-API —
  kein API-Verbrauch, volle GPU-Auslastung. Bilder kommen ohnehin lokal aus Diffusers
  (SDXL/FLUX auf der GPU). Claude greift nur als Fallback, falls lokal kein JSON kam.

### So aktiviert man den lokalen GPU-Dauerbetrieb
`.env`:
```
JARVIS_DAILY_SITES=10
JARVIS_IMPROVE_UNTIL_HOUR=10      # bis 10:00 verbessern
JARVIS_IMPROVE_LOCAL=1            # Verbesserung lokal (Ollama auf GPU)
JARVIS_TOOL_MODEL=qwen2.5:14b    # oder größer, je nach VRAM
JARVIS_IMAGE_AUTO=1              # Bilder hardware-bestes Modell (GPU→SDXL/FLUX)
```
Dann im Dashboard den **Auto-Builder** starten. Er baut 10 Seiten und verbessert danach
durchgehend weiter bis 10 Uhr — alles lokal.

## 2. Architektur des Nightly-Loops
```
auto_builder._loop()  (1 Thread, läuft bis Stop)
  ├─ Phase 1  _pick_next_lead() → website_builder.build()
  │             → improve_existing()  → _email(Bastian)  → _record(daily_builds.json)
  ├─ Phase 2  _pick_improve_target()  (ältestes 'updated', live)
  │             → website_builder.improve_existing()
  │                 → website_improve.enrich()   ← JARVIS_IMPROVE_LOCAL=1 ⇒ Ollama
  │                 → _deploy_folder(redeploy_url=…)  (nur Push → Railway rebaut)
  └─ Phase 3  idle bis 0 Uhr
```
Round-Robin über `updated` sorgt dafür, dass jede Seite drankommt und über die Tage
schrittweise besser wird (mehr Sektionen, bessere Texte, frische Bilder, Effekte).

## 3. Claude-Code-Tiefenmodus (Plan — optional, für echte Feature-Arbeit am Code)
Ollama verbessert Inhalte/Design über `content.json` + Premium-Template gut. Für **echte
neue Features im Code** (z.B. Buchungsformular, Galerie-Lightbox, Preisrechner) ist ein
Coding-Agent stärker. Anbindung lokal:

### Variante A — Claude Code headless (`claude -p`)
- Pro Seite ein Auftrag: `claude -p "<Aufgabe>" --output-format json` im Projektordner
  der Seite (jeder Build ist ein eigenständiges Django-Projekt).
- JARVIS ruft das als Subprozess auf (neues Modul `claude_coder.py`), übergibt die
  Aufgabe („Füge eine barrierearme Lightbox-Galerie hinzu, ändere sonst nichts kaputt"),
  wartet auf Ergebnis, dann `deploy_existing()` (Push → Railway rebuild).
- Vorteil: voller Werkzeugkasten (Dateien lesen/schreiben, Tests). Nachteil: nutzt Claude
  (nicht 100% lokal) und braucht das `claude`-CLI auf dem GPU-PC.

### Variante B — Lokaler Coding-Agent (100% lokal, GPU)
- Ein lokales Code-Modell über Ollama (z.B. `qwen2.5-coder:14b/32b`) in einer kleinen
  Agent-Schleife: Datei lesen → Änderung vorschlagen → schreiben → `py_compile`/Django-
  Render-Check (`website_improve._render_check`) → bei Fehler zurückrollen.
- Vorteil: komplett lokal, kostenlos. Nachteil: schwächer als Claude bei komplexen Features.

### Empfohlener Hybrid (Schalter)
```
JARVIS_NIGHTLY_DEEP=off | local | claude
```
- `off`     → nur die bestehenden Inhalts-/Design-Pässe (Standard, sicher).
- `local`   → zusätzlich lokaler Coding-Agent (Variante B) für kleine Feature-Schritte.
- `claude`  → Claude-Code-Subprozess (Variante A) für anspruchsvolle Features.
Jeder Tiefen-Schritt MUSS durch den Render-/Compile-Check, sonst Rollback — eine
Nachtschicht darf nie eine Live-Seite zerschießen.

### Sicherheits-/Betriebsregeln (für Variante A/B)
- Immer auf einer Kopie/Branch arbeiten, erst nach grünem Check deployen.
- Pro Seite/Nacht ein Feature-Inkrement (klein, testbar) statt großer Umbau.
- Live-URL nie ohne erfolgreichen `_url_live`-Check als „live" markieren.
- Cutoff strikt: ab `JARVIS_IMPROVE_UNTIL_HOUR` keine neuen Tiefen-Jobs starten.

## 4. Nächste Schritte (wenn Tiefenmodus gewünscht)
1. `claude_coder.py` (Subprozess-Wrapper für `claude -p`, Variante A) ODER
   `local_coder.py` (Ollama-Agent, Variante B) — hinter `JARVIS_NIGHTLY_DEEP`.
2. In `auto_builder._improve_existing_once()` nach dem Inhalts-Pass optional einen
   Tiefen-Schritt einklinken (mit Render-Check + Rollback).
3. Feature-Backlog je Branche (z.B. Handwerk: Angebotsformular, Referenzen-Slider,
   Öffnungszeiten, Karte) — der Agent arbeitet ihn Schritt für Schritt ab.

## 5. Status der Tests
`tests/test_core.py` deckt Tageslogik + E-Mail-Link + Auto-Modellwahl ab. Der lokale
Improve-Pfad ist best-effort (fällt sauber zurück), der Render-Check schützt vor Bugs.
