# Makeover-Pipeline, Kostentracking & Overnight-Stopp/Resume

> Stand 2026-06-23. Diese Doku beschreibt drei zusammenhängende Ausbauten:
> (1) das mehrstufige Skill-Makeover, (2) das lückenlose Kostentracking, (3) den
> stopp- und fortsetzbaren Overnight-Modus. Entwickler-Kurzreferenz: `CLAUDE.dev.md`.

---

## 1. Mehrstufiges Skill-Makeover (`overnight_makeover.py`)

Ersetzt das frühere flache „Verbessern" (`website_improve.enrich`), das nur `content.json`-Texte
tweakte und sichtbar **nichts** am Design änderte. Jede gebaute Seite wird jetzt durch **7 Stufen**
gefahren — jede mit einem echten Skill, ausgeführt vom **Headless Claude Code**
(`claude_coder.run_prompt`), der `templates/index.html` + `static/css/style.css` **wirklich** umbaut.

| # | Stufe | Skill |
|---|-------|-------|
| 1 | Hero-Bereich | design-pro (5 KB) |
| 2 | Beschreibung & Dienstleistungen | design-pro |
| 3 | Über uns & Vertrauen | design-pro |
| 4 | Kontakt-Bereich | design-pro |
| 5 | Kontakt-Formular | design-pro |
| 6 | Komplett-Design (taste) | design-taste-frontend (88 KB, nur hier) |
| 7 | QA, Datenschutz, AGB & Impressum | design-pro |

> **Token-Sparsam (seit 24.06.2026):** Statt das 45-KB-`ui-ux-pro-max` in 5 Stufen zu laden,
> nutzen 6 Stufen das kompakte `design-pro` (5 KB, bündelt dieselben Prinzipien); das große
> `taste` (88 KB) lädt nur in der einen Design-Stufe. Skill-Token/Seite ~313 KB → ~118 KB.
> Zusätzlich kein content.json-Dump mehr im Prompt (Claude liest die Datei selbst) → Prompt
> 6262 → 2362 Zeichen, Stufen-Laufzeit ~321 s → ~129 s. Rechtstexte (Impressum/Datenschutz/
> AGB) kommen lokal aus `legal_pages.py` (0 Tokens) und werden nur noch gerendert.

> **Stufen seit 24.06.2026 abschnittsorientiert** (vorher Design-Facetten). Jede Stufe baut
> einen echten Seitenbereich aus; Stufe 6 ist der große Design-Durchgang (taste + ui-ux-pro-max
> + design-pro), Stufe 7 ergänzt die rechtlichen Pflichtseiten + Schluss-QA.

> **Kern-Fix 24.06.2026 — Makeover hing bei „Stufe 1":** Der Stufen-Prompt wird `claude_coder`
> jetzt über **STDIN** übergeben statt als Kommandozeilen-Argument. Über `claude.cmd` (Batch →
> cmd.exe) wurde der lange Prompt (content.json-Dump mit `"` `&` `<` `>` `|`) an Sonderzeichen
> abgeschnitten → der Headless-Claude sah nur einen Prompt-Torso und fragte konversationell
> zurück, statt zu editieren. Folge: 0 Datei-Änderungen → Stufe nie als erledigt markiert →
> jede Seite blieb auf `makeover_stages=[]`. Mit stdin laufen die Stufen real durch (verifiziert:
> Hero-Stufe ~320 s, Dateien geändert, committet, markiert).

**Skills:** Die echten Skills `ui-ux-pro-max` und `design-taste-frontend` (taste) liegen
versioniert im Repo unter `skills/<name>/SKILL.md` und werden beim Start
(`claude_skills.ensure_installed()`, auch in `install.py`) nach `~/.claude/skills/`
gespiegelt — nötig, weil der headless Makeover-Claude im Webseiten-Ordner läuft und dort
nur user-globale Skills sieht. So sind sie auf JEDEM PC nach `git pull` automatisch da.

**Pro Stufe:** Standard-Kontextblock (Fakten zu genau diesem Lead/dieser Seite) + Master-Prompt +
Skill → `claude -p` mit Snapshot + **Render-Gate + Rollback** → Stufe in
`content.json["makeover_stages"]` markieren (**resume-fähig**) → **Git-Commit** (Rollback-Punkt) →
Activity-Feed + Kostentracking. Eine Stufe gilt nur als erledigt, wenn sich **Dateien wirklich
ändern** (Schutz vor leeren Läufen, z.B. bei Session-Limit).

**Deploy:** Commit nach jeder Stufe, **Railway-Deploy einmal am Ende**. Danach Discord-Freigabe.

**Verabschiedung + Tages-Übersicht (seit 24.06.2026):** Der Night-Builder fährt nach der
Bau-Phase ALLE bestehenden Seiten durch den 7-Stufen-Weg, bis jede auf 7/7 ist. Ist dann
nichts mehr zu bauen/verbessern, postet `auto_builder._farewell_if_done()` EINMAL eine
Discord-Abschlussnachricht via `discord_bot.notify()` — **inklusive aller HEUTE gebauten
Seiten als klickbare Markdown-Links zum Bewerten** (`_today_links()` aus
`data/daily_builds.json`, dedupliziert, unter dem Embed-Limit von 4096 Zeichen). Latch
`_farewell_sent`; reset bei Start, Tageswechsel und sobald wieder eine Seite offene Stufen hat.
Die per-Seite-Freigabe (1× 👍 = Kunden-Mail) bleibt davon unberührt — die Übersicht kommt
zusätzlich.

**Discord-Gate:** **1× 👍 = Kunden-Mail (12 Uhr) · 1× 👎 = verworfen**
(`DISCORD_APPROVALS_NEEDED` Default jetzt `1`). Ohne Discord → Vorschau-Mail an
`JARVIS_FALLBACK_EMAIL`.

**Auslöser:** Night-Builder (jede der 10 Seiten) **und** der „Webseiten verbessern"-Button
(`/api/websites/<id>/improve`).

**Wichtig:** `claude_coder` gibt `--append-system-prompt` mit, damit ein im Zielordner gefundenes
`CLAUDE.md` (JARVIS-Persona) den Headless-Lauf nicht in einen Chat verwandelt. Modell via
`JARVIS_MAKEOVER_MODEL` (Default `sonnet`). Eine Stufe dauert ~1–15 Min; läuft über das
Claude-Code-Abo.

**Session-Limit → warten & wiederholen:** Erkennt das Makeover ein Claude-Usage-/Session-Limit,
**wartet es 1 Stunde und versucht dieselbe Stufe erneut — bis zu 7 Mal** (`JARVIS_MAKEOVER_LIMIT_WAIT`
= 3600 s, `JARVIS_MAKEOVER_LIMIT_RETRIES` = 7; Wartezeit per Stop unterbrechbar). Erst danach
pausiert es und setzt beim nächsten Lauf fort. Das Builder-Warte-Limit `JARVIS_MAKEOVER_WAIT`
ist deshalb auf 10 h erhöht.

---

## 2. Overnight-Modus: stoppen & fortsetzen (auch nach Programm-Neustart)

- **Persistenz:** An/Aus-Status in `data/overnight_state.json` (gitignored). `start()`/`stop()`
  schreiben ihn; `app.run_server()` ruft beim Serverstart `auto_builder.resume_if_needed()` →
  war der Builder beim Schließen an, **läuft er automatisch wieder an**.
- **Stopp wirkt zwischen den Stufen:** `stop()` setzt `running=False`; der Callback
  `stop=lambda: not is_running()` wird bis in die Makeover-Schleife durchgereicht. Eine laufende
  Stufe läuft noch zu Ende (bzw. bis Timeout), dann hält die Pipeline an. Bei Stopp wird **nicht**
  deployt — der committete Fortschritt bleibt.
- **Genau-da-weiter:** erledigte Stufen stehen in `content.json["makeover_stages"]` und werden
  übersprungen. `overnight_makeover._reset_dirty()` verwirft beim Resume eine abgebrochene
  (uncommittete) Halbstufe via `git reset --hard` → sauberer Wiedereinstieg.
- **Bedienung:** Auto-Builder-Button im Dashboard (`/api/auto-build/start|stop|status`).
- **Konfig:** `JARVIS_DAILY_SITES` (10), `JARVIS_MAKEOVER_WAIT` (9000 s Warte-Limit je Seite),
  `JARVIS_IMPROVE_RESPECT_CUTOFF` (0 = jederzeit verbessern).

---

## 3. Lückenloses Kostentracking (`cost_tracker.py`)

Jede kostenverursachende Aktion wird erfasst und im **Kosten-Tab** angezeigt (Tageskosten,
14/30/90-Tage-Chart, Pro-Projekt-Aufschlüsselung, CSV-Export, Live-Aktivitätslog).

| Aktion | Quelle | getrackt über |
|--------|--------|---------------|
| Claude-Chat, Agenten, Webseiten-Bau/-Verbessern, Makeover | API-Tokens | `track_api`/`track_message` an allen 6 Anthropic-Call-Sites + Headless-Claude-Usage |
| Higgsfield Bild **und** Video | Credits | `track_higgsfield` |
| Lokale Bilder/Videos | Compute (Strom) | `track_compute` (echte Laufzeit) |
| Lead-Bewertung | Compute | `track_compute` (echte Laufzeit) |

Persistenz: `data/costs.json` (täglich aggregiert, gitignored). Routen: `/api/costs/today`,
`/api/costs/history`, `/api/costs/export`, `/api/activity/recent`, `/api/home/stats`.

**Hinweis:** Higgsfield-Bild-Credits sind als `1` geschätzt (`JARVIS_HF_IMAGE_CREDITS` justierbar);
der Render-Gate-Check (`website_improve._render_check`) überspringt sauber, wenn kein Django
installiert ist.
