# Referenz-Seiten — Beispiele für die lokale KI

Echte, von JARVIS gebaute Landing-Pages als **Vorbild** für den Nightly-Improver
und den lokalen Coder. Die KI lädt sie über `local_tools.read_reference(name)` und
baut neue/verbesserte Seiten in **ähnlicher Qualität und Struktur**.

## Enthaltene Beispiele
- `braun-elektrotechnik-gmbh/` — Elektro/Heizung (Akzent Orange)
- `umzuege-s-klein-gmbh-und-co-kg/` — Umzugsunternehmen
- `brillen-de/` — Optiker

Jede Referenz: `content.json` (die Daten) + `templates/index.html` (das gerenderte
Premium-Template) + `static/css/style.css`.

## Das Muster (so baut die KI)
1. **`content.json` ist die Wahrheit.** Die Seite wird komplett daraus gerendert —
   Texte, Akzentfarbe, Bilder, Leistungen, USPs, FAQ. Die KI ändert i.d.R. die
   `content.json`, nicht das Template.
   Schema (Kernfelder):
   ```json
   {
     "site_name": "…", "branche": "…", "stadt": "…",
     "telefon": "…", "email": "…", "adresse": "…",
     "akzent": "#RRGGBB",
     "hero_image": "/static/img/hero.png", "about_image": "…", "fotos": ["…"],
     "headline": "…", "subline": "…",
     "ueber_titel": "…", "ueber_text": "…",
     "leistungen": [{"titel": "…", "text": "…"}],
     "usps": ["…"], "faq": [{"frage": "…", "antwort": "…"}],
     "cta_text": "…", "kontakt_text": "…",
     "seo_title": "…", "seo_desc": "…", "jahr": 2026
   }
   ```
2. **Design-Prinzipien (design-pro):** eine Akzentfarbe konsequent, großzügiger
   Weißraum, klare Hierarchie, EIN primärer CTA, Vertrauenssignale, keine Effekt-
   Häufung. Deutsch, konkret, kein KI-Geschwurbel.
3. **Neue Features** kommen als zusätzliche `content.json`-Felder + passende
   Template-Sektion (z.B. `oeffnungszeiten`, `bewertungen`, `referenzen`) — immer
   so, dass bestehende Felder/Funktion unangetastet bleiben.
4. **Vor „fertig" IMMER** `render_check` (Django-Template muss fehlerfrei rendern)
   und `compile_check` (falls Python geändert). Bei Fehler: zurückrollen.

## Wichtig
Diese Beispiele sind **statische Referenzen** (kein lauffähiges Projekt hier — der
volle Django-Build entsteht je Lead aus `vorlage_landing/`). Sie zeigen Stil,
Struktur und Tonalität, an denen sich die lokale KI orientiert.
