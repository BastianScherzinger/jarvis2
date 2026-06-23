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
| 1 | Inhalt & Struktur | design-pro |
| 2 | Layout & Hierarchie | design-pro |
| 3 | Typografie | design-pro |
| 4 | Farbe & Theming | design-pro |
| 5 | Politur | taste |
| 6 | Motion & Interaktion | frontend-design |
| 7 | Responsive & QA | design-pro |

**Pro Stufe:** Standard-Kontextblock (Fakten zu genau diesem Lead/dieser Seite) + Master-Prompt +
Skill → `claude -p` mit Snapshot + **Render-Gate + Rollback** → Stufe in
`content.json["makeover_stages"]` markieren (**resume-fähig**) → **Git-Commit** (Rollback-Punkt) →
Activity-Feed + Kostentracking. Eine Stufe gilt nur als erledigt, wenn sich **Dateien wirklich
ändern** (Schutz vor leeren Läufen, z.B. bei Session-Limit).

**Deploy:** Commit nach jeder Stufe, **Railway-Deploy einmal am Ende**. Danach Discord-Freigabe.

**Discord-Gate:** **1× 👍 = Kunden-Mail (12 Uhr) · 1× 👎 = verworfen**
(`DISCORD_APPROVALS_NEEDED` Default jetzt `1`). Ohne Discord → Vorschau-Mail an
`JARVIS_FALLBACK_EMAIL`.

**Auslöser:** Night-Builder (jede der 10 Seiten) **und** der „Webseiten verbessern"-Button
(`/api/websites/<id>/improve`).

**Wichtig:** `claude_coder` gibt `--append-system-prompt` mit, damit ein im Zielordner gefundenes
`CLAUDE.md` (JARVIS-Persona) den Headless-Lauf nicht in einen Chat verwandelt. Modell via
`JARVIS_MAKEOVER_MODEL` (Default `sonnet`). Eine Stufe dauert ~1–15 Min; läuft über das
Claude-Code-Abo → bei erschöpftem Session-Limit pausiert das Makeover und setzt später fort.

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
