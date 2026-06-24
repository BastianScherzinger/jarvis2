# Token-Sparplan — JARVIS Webseiten-Pipeline

> Ziel: Claude-Session-Tokens drastisch senken, **ohne Qualität zu verlieren** — indem
> die starke lokale GPU (RTX 4090 Laptop, später Server) so viel wie möglich übernimmt
> und Claude nur noch für das eingesetzt wird, was lokal nicht in Top-Qualität geht.

Der einzige große Claude-Token-Verbraucher ist das **7-Stufen-Makeover** (`overnight_makeover.py`
über `claude_coder.py` / headless `claude`-CLI). Build-Texte, Hero-Prompts und Rechtstexte
laufen bereits lokal bzw. deterministisch (0 Claude-Tokens).

---

## Bereits umgesetzt (Stand 24.06.2026)

| Maßnahme | Ersparnis | Datei |
|----------|-----------|-------|
| `design-pro` (5 KB) statt `ui-ux-pro-max` (45 KB) für 6/7 Stufen | ~318 KB → ~118 KB Skill-Last/Seite | `overnight_makeover.STAGES` |
| `taste` (88 KB) nur in der EINEN großen Design-Stufe | s.o. | `_TASTE` nur bei `design` |
| Kein content.json-Dump im Prompt (Claude liest die Datei selbst) | Prompt 6262 → 2362 Zeichen/Stufe | `_build_stage_prompt` |
| Build-Texte via Ollama statt Claude | komplette Bau-Phase 0 Claude-Tokens | `website_builder._ollama_content` (`JARVIS_BUILD_CONTENT_LOCAL`) |
| Rechtstexte deterministisch (`legal_pages.py`) | Impressum/DS/AGB 0 Claude-Tokens | `_ensure_legal` |
| Hero-Prompts via Ollama verfeinert | Prompt-Engineering 0 Claude-Tokens | `media_engine.hero_prompt_smart` |
| Hero-/Galeriebilder via Higgsfield-Abo / lokale Diffusers, sonst SVG-Platzhalter | Bilder 0 Claude-Tokens | `media_engine`, `ref_images.py` |
| **Mechanische Stufen `qa_recht` + `formular` auf günstigem Modell (haiku)** | ~2/7 der Makeover-Tokens | `_MODEL_LITE`, Stufen `qa_recht`/`formular` |
| **Claude-Limit-Lernen**: Makeover startet in der 4-h-Sperre gar nicht erst (`should_try_now`) | spart vergebliche Läufe am vollen Limit | `claude_limit.py`, Gate in `run_makeover` |

---

## Roadmap — weitere Token-Senkung (priorisiert, sicher → mutig)

### Stufe 1 — sofort, null Qualitätsrisiko
1. **Modell-Tiers pro Stufe ausweiten** *(Infrastruktur steht: `stage["model"]`)*.
   Mechanische Stufen → `haiku`, design-kritische → `sonnet`. Aktuell nur `qa_recht`.
   Kandidaten zum Nachziehen nach Sichtprüfung: `formular`, `kontakt` (überwiegend
   strukturell). Umschalten via `JARVIS_MAKEOVER_MODEL_LITE` + `model`-Feld der Stufe.
2. **Prompt-Caching nutzen**: Skill + Systemteil sind je Stufe identisch — die `claude`-CLI
   cached den stabilen Prefix automatisch. Reihenfolge der Stufen so lassen, dass derselbe
   Skill aufeinanderfolgt (alle `design-pro`-Stufen am Stück → Cache bleibt warm).
3. **`--max-turns` knapper** halten (aktuell 80). Saubere Stufen brauchen ~10–20 Runden;
   ein niedrigeres Limit kappt Ausreißer-Schleifen, die unbemerkt Tokens fressen.

### Stufe 2 — lokale Vorarbeit auf der GPU (Claude nur noch als Veredler)
4. **„Lokal baut Rohfassung → Claude poliert"** je Stufe: Ollama (`qwen2.5:14b`/`32b` auf
   der 4090) erzeugt den Sektions-Entwurf (HTML/CSS-Skelett, Texte, Struktur), Claude
   bekommt nur noch den Diff zum Veredeln statt von Null zu bauen. Spart die teure
   Generierungs-Phase; Claude-Anteil sinkt auf Feinschliff. Risiko: mittel → erst an einer
   Stufe (z. B. `leistungen`) erproben, Render-Gate + Sichtprüfung.
5. **Mechanische Stufen ganz lokal**: `qa_recht` (Rechtstexte rendern, Links, Responsive-QA)
   und `formular` (Felder, csrf, tel/mailto) sind deterministisch genug für ein lokales
   Coder-Modell (`qwen2.5-coder`). Bei Erfolg = diese Stufen 0 Claude-Tokens.
6. **Lokaler Render-/Lint-Vorlauf** statt Claude-Selbstkontrolle: `python manage.py check`
   + ein HTML/CSS-Linter laufen lokal vor dem Commit; Claude muss nicht selbst verifizieren.

### Stufe 3 — wenn der Server da ist (große lokale Modelle)
7. **Makeover-Engine umschaltbar** (`JARVIS_MAKEOVER_ENGINE = claude | local | hybrid`):
   Auf dem Server mit `qwen2.5:32b`/`llama3.3:70b` laufen die meisten Stufen lokal,
   Claude nur noch für die große `taste`-Design-Stufe (wo die Anti-Slop-Tiefe zählt).
   Ziel-Aufteilung: **1 Claude-Stufe + 6 lokale Stufen** statt 7 Claude-Stufen.
8. **Batch-Nacht**: alle Seiten eines Tages in einem lokalen Lauf, Claude-Stufe gebündelt
   am Ende — minimiert Kontext-Wiederaufbau.

---

## Skills, die Tokens sparen (ohne Qualitätsverlust)

- **`design-pro`** (≈5 KB) — destilliertes Bündel aus ui-ux-pro-max / impeccable-design /
  taste / frontend-pro / shadcn. Liefert ~90 % der Design-Qualität bei ~1/9 der Token-Last
  von `taste` (88 KB). **Bereits Standard für 6/7 Stufen.** → Das ist der zentrale Spar-Skill.
- **`design-taste-frontend`** (`taste`, 88 KB) — nur dort einsetzen, wo die Tiefe den Preis
  wert ist (große Design-Stufe). Nicht breiter streuen.
- Grundsatz: **headless Claude lädt jeden referenzierten Skill KOMPLETT in den Kontext** →
  immer den kompaktesten passenden Skill nennen, große Skills gezielt.

---

## Sichtbares Zeichen bei vollem Limit (umgesetzt 24.06.2026)

`claude_limit.py` ist die Single Source of Truth. Das Makeover meldet ein erkanntes
Session-Limit (`mark`), eine wieder durchlaufende Stufe hebt es auf (`clear`). Das Dashboard
(`/api/status` → `claude_limit`) zeigt direkt ein **Banner über den Webseiten** + ein
**Badge auf der betroffenen Karte** („⏳ Limit voll · pausiert") — so ist sofort sichtbar,
dass nicht der Code hängt, sondern Claudes Kontingent erschöpft ist (läuft autom. weiter).
