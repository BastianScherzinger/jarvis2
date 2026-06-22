# Nightly-Tiefenmodus — Seiten nachts mit echten Features verbessern

Vollständiger Plan + umgesetzte Architektur. Der Auto-Builder baut tagsüber 10 Seiten
und verbessert nachts bestehende Seiten — wahlweise nur Inhalte/Design **oder** echte
Code-Features (Variante A: Claude Code; Variante B: Claude plant, lokale Mega-KI baut).

## Schalter (.env)
```
JARVIS_NIGHTLY_DEEP=off        # off | local | claude
JARVIS_DAILY_SITES=10
JARVIS_IMPROVE_UNTIL_HOUR=10   # bis 10:00 verbessern
# Variante B (lokal):
JARVIS_IMPROVE_LOCAL=1         # Inhalts-Pässe lokal (Ollama)
JARVIS_CODER_MODEL=qwen2.5-coder:32b   # oder qwen2.5:32b-instruct (Tool-Caller)
JARVIS_CODER_STEPS=14          # max. Agent-Schritte je Feature
# Variante A (Claude Code):
JARVIS_CLAUDE_PERMISSION=acceptEdits   # Edits ohne Rückfrage, keine Shell
JARVIS_CLAUDE_TIMEOUT=900
```

## Ablauf (auto_builder._improve_existing_once)
```
nightly-Schleife (Phase 2, bis Cutoff-Stunde)
  ├─ _pick_improve_target()        ältestes 'updated', live
  ├─ JARVIS_NIGHTLY_DEEP=local|claude?
  │     ├─ feature_backlog.next_feature(branche, content)   nächstes offenes Feature
  │     ├─ local : Claude schreibt Spec → Ollama baut via local_tools (ReAct)
  │     │           local_coder.build_feature()  (Snapshot→Render-Gate→Rollback)
  │     ├─ claude: claude_coder.run_feature()  (claude -p, acceptEdits, Render-Gate→Rollback)
  │     ├─ Feature in content.json["features_added"] markieren + JARVIS_CHANGELOG.md
  │     └─ deploy_existing()  (Push → Railway rebaut)
  └─ sonst: website_builder.improve_existing()  (Inhalts-/Design-Pass)
```

## Variante A — Claude Code headless (`claude_coder.py`)
- `claude -p "<Feature-Spec + Regeln>" --output-format json --permission-mode acceptEdits`
  im Projektordner der Seite. Claude editiert die Dateien selbst (echte Code-Arbeit).
- Danach Render-Check; bei Bug **Rollback** aus dem Snapshot (content.json + Templates + CSS).
- `is_available()` prüft das `claude`-CLI (Windows: claude.cmd). Fehlt es → sauberer Skip.

## Variante B — Claude plant, lokale Mega-KI baut (`local_coder.py`)
1. **plan_feature()** — Claude (klein, günstig) liest die Seite und schreibt die
   PRÄZISE, seitenspezifische Bau-Spec. Ohne API-Key: generische Backlog-Spec.
2. **build_with_local()** — die lokale Ollama-KI baut die Spec in einer **ReAct-Schleife**
   mit `local_tools` (read/write/replace/render_check, sandboxed auf den Ordner).
   Snapshot vorher, Render-Gate + Rollback bei Regression, Step-Budget.
3. Skills (design-pro, Conversion-UX, deutsche Texter-Regeln) sind in den System-Prompt
   eingebettet (`workspace/SKILLS_LOCAL_AI.md`).

## Werkzeuge der lokalen KI (`local_tools.py`)
Sandboxed auf den Seitenordner: `list_dir, read_file, write_file, replace_in_file,
read_content, write_content, compile_check, render_check, read_reference` + `snapshot/
restore`. Pfad-Traversal wird hart geblockt. `read_reference` lädt die Beispiel-Seiten.

## Referenz-Seiten (`reference_sites/`)
Echte gebaute Seiten (Braun Elektro, Umzüge Klein, Brillen.de) als Vorbild — die KI
lädt sie über `read_reference` und baut in ähnlicher Qualität/Struktur. Siehe
`reference_sites/README.md` (content.json-Schema + Muster).

## Feature-Backlog (`feature_backlog.py`)
Pro Branche (Dachdecker, Elektriker, KFZ, Friseur, Restaurant, Umzug, Arzt) + universell
(Öffnungszeiten, FAQ, Bewertungen, Kontaktformular, Karte, Sticky-CTA). Jede Seite bekommt
Nacht für Nacht ein weiteres Feature, bis der Backlog leer ist.

## Sicherheit
- Jeder Tiefen-Schritt **muss** durch den Render-Check; bei Fehler vollständiger Rollback.
- Sandbox: alle lokalen Tools sind auf den Seitenordner beschränkt.
- Variante A: nur `acceptEdits` (Datei-Edits), keine beliebige Shell ans Modell.
- Cutoff strikt: ab `JARVIS_IMPROVE_UNTIL_HOUR` keine neuen Tiefen-Jobs.

## Extras (umgesetzt)
- **Per-Seite-Changelog** `JARVIS_CHANGELOG.md` (was wurde wann nachts eingebaut).
- **Tages-Historie** `data/daily_builds.json` + `/api/auto-build/daily`.
- Status (`/api/auto-build/status`) zeigt `nightly_deep` + `last_feature`.

## Nächster Ausbau (Plan, noch offen)
- **MCP für lokale KIs** — `workspace/PLAN_MCP_LOCAL_AI.md` (mcp_bridge.py: Ollama-tool_calls
  ⇄ MCP `call_tool`; Filesystem/Playwright/Git-MCP; deterministische Gates). Two-Model-Split:
  `qwen2.5:32b-instruct` orchestriert, `qwen2.5-coder:32b` generiert Code (Coder hat kein
  natives Ollama-Tools-Badge).
- Visuelle QA per Playwright-Screenshot; design-pro-MCP-Server (FastMCP).
