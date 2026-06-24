# Webseiten-Verbessern (Makeover) — vollständige Doku

> Der „Webseiten verbessern"-Prozess: aus einer frisch gebauten Standard-Landingpage wird
> über **7 Skill-Stufen** (headless Claude Code) eine Premium-Seite auf Agentur-Niveau.
> Diese Datei dokumentiert den kompletten Durchgang, das Logging, die Parallelitäts-Sperre
> und die offenen Punkte.

## Überblick des Ablaufs

```
makeover_existing(folder, name, stop)              website_builder.py
  └─ _start_folder_job → Thread → _run_makeover    (1 globaler Lock: nur EINE Seite!)
       ├─ run_makeover(folder, meta, …)            overnight_makeover.py
       │    ├─ _reset_dirty           (sauberer Resume, uncommittete Halbstufe verwerfen)
       │    ├─ _ensure_hero           (Hero-Bild via Higgsfield-Abo, einmal je Seite)
       │    ├─ _ensure_legal          (Impressum/Datenschutz/AGB deterministisch, 0 Tokens)
       │    ├─ ref_images.ensure_placeholders  (leere Bild-Slots → SVG-Platzhalter)
       │    └─ für jede der 7 STAGES:
       │         claude_coder.run_prompt(folder, stage-prompt, model)   claude_coder.py
       │           └─ headless `claude -p --output-format stream-json`  (editiert Dateien)
       │         → Fingerprint-Check (nur „erledigt", wenn Dateien WIRKLICH geändert)
       │         → _git_commit (Rollback-Punkt) + on_stage_done → SOFORT live pushen
       └─ Deploy am Ende + Discord-Freigabe (wenn alle 7 durch)
```

## Die 7 Stufen (overnight_makeover.STAGES)

| # | key | Label | Skill | Modell |
|---|-----|-------|-------|--------|
| 1 | hero | Hero-Bereich | design-pro (5 KB) | sonnet |
| 2 | leistungen | Beschreibung & Dienstleistungen | design-pro | sonnet |
| 3 | ueber | Über uns & Vertrauen | design-pro | sonnet |
| 4 | kontakt | Kontakt-Bereich | design-pro | sonnet |
| 5 | formular | Kontakt-Formular | design-pro | **haiku** (mechanisch) |
| 6 | design | Komplett-Design | **design-taste-frontend** (88 KB) | sonnet |
| 7 | qa_recht | QA, Datenschutz, AGB & Impressum | design-pro | **haiku** (mechanisch) |

- Jeder Stufen-Prompt (`_build_stage_prompt`) referenziert das Skill explizit und weist
  Claude an, `content.json` + `templates/index.html` + `static/css/style.css` **direkt aus
  dem Ordner zu lesen und WIRKLICH zu editieren** (kein content.json-Dump im Prompt → spart
  ~3,5 KB/Stufe). Resume-fähig über `content.json["makeover_stages"]`.
- **Skills liegen versioniert im Repo** unter `skills/<name>/SKILL.md` und werden von
  `claude_skills.ensure_installed()` (App-Start + install.py) nach `~/.claude/skills/`
  gespiegelt — nötig, weil der headless Makeover-Claude IM Seiten-Ordner läuft und dort nur
  user-globale Skills sieht. `design-pro` ist user-global (Sirs ~/.claude).

## Logging — lückenlos durch den ganzen Durchgang (Tag `[Makeover]` in der CMD)

**claude_coder.run_prompt** (jede einzelne Stufe):
- `▶ Claude-Code startet · <task> · Modell <m> · <ordner> · Prompt N Zeichen`
- pro Tool-Einsatz: `  <ordner> · Edit/Write/Bash …` (DEBUG)
- Claude-Result mit Fehler → WARN mit subtype + Text
- Abbruch (Watchdog/Timeout): `✕ … Hänger/Zeitlimit nach Ns — abgebrochen & zurückgerollt` **+ stderr-Auszug**
- Render-Fehler: `✕ … Render-Fehler → zurückgerollt: <grund>`
- Erfolg: `✓ … fertig in Ns · X Tools, Y Edits · <summary>`

**overnight_makeover.run_makeover** (der Gesamt-Durchgang):
- Start: `━━ Start: <name> · X/7 bereits fertig · N offen: <labels>`
- pro Stufe Start: `→ <name> · Stufe i/7: <label> (Skill <skill>, Modell <m>)`
- pro Stufe Ende: `✓ <name> · Stufe i/7 <label> fertig (Ns) · X/7 gesamt`
- Fehlschlag: `✕ <name> · Stufe '<label>' fehlgeschlagen nach Ns: <grund>`
- ohne Datei-Änderung: `⊘ <name> · Stufe '<label>' ohne Datei-Änderung — nicht markiert`
- Lauf-Ende: `━━ <name>: KOMPLETT` bzw. `Lauf-Ende +X Stufen · noch offen: …`

**website_builder._run_makeover** (Job-Ebene): Slot belegt/frei (`🔒`/`🔓`), Fehler + **Traceback**.
**Global:** `@app.errorhandler(Exception)` in app.py loggt jede unbehandelte Route-Exception
mit Traceback; alle vier Hintergrund-Job-Runner loggen ihren Fehler + Traceback in die CMD.

## Parallelität — IMMER NUR EINE Seite gleichzeitig

`website_builder._makeover_gate` (threading.Lock) garantiert es:
- `_run_makeover` holt den Lock **non-blocking**. Bekommt er ihn nicht (eine andere Seite
  läuft schon), wird der Job **sauber abgewiesen** (Status done + Hinweis „Übersprungen — es
  wird gerade '<X>' verbessert"), ohne eine zweite Claude-Pipeline zu starten.
- `finally` gibt den Slot **immer** frei (auch bei frühem return/Fehler).
- `makeover_busy()` / `makeover_current()` als öffentliche Statusabfrage.
- Der **Auto-Builder** (`_improve_existing_once`) prüft `makeover_busy()` VORHER und überspringt
  die Runde (5 s warten), statt die Seite fälschlich als „stuck" zu markieren.
- Der Auto-Builder ist ohnehin in sich sequenziell (wartet via `_wait_job`); die echte Gefahr
  war ein manueller „Verbessern"-Klick während des Auto-Laufs oder ein Doppelklick — beides
  ist jetzt abgefangen.

## Limit- & Budget-Anbindung (siehe claude_limit.py / TOKEN_PLAN.md)

- Kommt das Claude-Session-Limit, setzt `run_makeover` `claude_limit.mark()` → Banner + Karten-
  Badge; eine durchgelaufene Stufe ruft `clear()`.
- Retry-Plan: erster Wiederversuch nach 4 h, danach stündlich; in der Sperrzeit startet
  `run_makeover` gar nicht erst (Gate `should_try_now`, spart Token).
- Token sparen: 6/7 Stufen nutzen `design-pro` (5 KB) statt `taste` (88 KB); `formular`+`qa_recht`
  laufen auf `haiku`.

## Offene Punkte / To-Do

- [ ] **Live über viele Seiten verifizieren**, dass alle 7 Stufen real durchlaufen (das Logging
      macht Fehler jetzt sichtbar — bei Bedarf gezielt nachschärfen).
- [ ] Optional: `_build_and_email` (Auto-Build → Makeover) ebenfalls auf `makeover_busy()` warten
      lassen, statt die frisch gebaute Seite erst im späteren improve-Pfad nachzuholen.
- [ ] Token Stufe 2: „lokal baut Rohfassung (Ollama qwen2.5:14b/32b auf RTX 4090) → Claude poliert
      nur den Diff" — größter weiterer Spar-Hebel (siehe TOKEN_PLAN.md, Stufe 2/3).
- [ ] Optional: Vorschau-Screenshot statt nur Link in der Discord-Freigabe.
- [ ] Stufen-Qualität stichprobenartig prüfen; ggf. `kontakt` ebenfalls auf `haiku` testen.
