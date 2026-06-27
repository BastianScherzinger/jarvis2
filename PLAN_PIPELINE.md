# JARVIS — Webseiten-Pipeline (Geld-Modus)

> Sirs Vorgabe (26.06.2026). Ziel: pro Tag **5 verkaufsfertige Seiten**, möglichst **lokal & token-arm**,
> Claude nur im letzten Schliff. Diese Datei ist der verbindliche Bauplan.

---

## 0. Grundprinzipien

- **3 × 5 = 15 Seiten/Tag.** 3 Bau-Sessions über den Tag verteilt (Default-Fenster `0,12,18`),
  jede mit frischem Limit von 5. Ist das Limit erschöpft, füllt die nächste Session wieder auf
  → 10–20 Seiten/Tag (untere Grenze bei Claude-Limit). Eigene-Marke-Seiten zählen mit.
  Knöpfe: `JARVIS_SESSIONS_PER_DAY`, `JARVIS_DAILY_SITES`, `JARVIS_SESSION_HOURS`,
  `JARVIS_LOCAL_CONCURRENCY` (0 = automatisch aus der Hardware).
- **Dauer-Live-Check.** Jede Seite wird laufend geprüft, ob sie wirklich antwortet (HTTP 200,
  **kein 404**). 404/nicht erreichbar → automatisch neu deployen (Selbstheilung).
- **Stufen-Pipeline pro Seite.** Stufe 1–4 laufen **lokal** (0 Claude-Tokens), Stufe 5 ist der
  **eine Claude-Pass** (taste + design). Jede Stufe wird **einzeln committet + live gepusht**;
  erst wenn die letzte Stufe durch ist, ist die Seite „fertig" → Discord-Freigabe → Versand.
- **Eine Seite nach der anderen** (globaler Makeover-Lock). Erst Seite A bis Stufe 5 fertig,
  dann Seite B.

---

## 1. Start-Knopf → Lead-Aufbereitung (Phase „Sammeln")

Beim Start sammelt der Builder die **5 besten Leads** (Erwartungswert, ohne Website, nicht
archiviert) und reichert je Lead VOLLSTÄNDIG an — **lokal + Recherche, 0 Claude**:

1. **Basis aus der Lead-DB**: Name, Branche, Stadt, Adresse, Telefon, E-Mail, Bewertung,
   Beschreibung.
2. **Kontakt-Recherche** (`contact_finder`): fehlende E-Mail/Ansprechpartner via DDG→Impressum /
   Google Places nachziehen.
3. **Bilder-Recherche** (`scrapers/maps.py`, hochauflösend): echte Fotos, Logo, Team-/Objektbilder
   → lokal bewertet (`lead_images.py`: Logos/Karten/unscharfe verwerfen, Rollen zuordnen).
4. **Inhalte lokal verfassen** (Ollama `qwen2.5:14b/32b`): Leistungen, Über-uns, FAQ, Trust,
   Rechner-Posten — betriebsgenau, deutsch (`website_builder._ollama_content` +
   `overnight_makeover._prefill_content_local`).
5. **Geo** (`agent_maps.geocode_latlng`): lat/lng → echte eingebettete Karte.
6. **Rechtstexte** deterministisch (`legal_pages.py`): Impressum/Datenschutz/AGB.

Ergebnis: ein vollständig befülltes `content.json`, bevor irgendeine Design-Stufe läuft.

---

## 2. Die 5 Stufen pro Seite

> Basis: die fertige Django-Vorlage `vorlage_landing/` rendert ALLE Blöcke deterministisch aus
> `content.json`. Die Stufen **arrangieren + gestalten**, sie erfinden keine Struktur neu.

### Stufe 1 — Hero (lokal, 0 Tokens) — **läuft als Erstes, sofort**
- **Hero-Bild = vorgenerierte Branchen-Vorlage** aus `hero_templates/` (Higgsfield, ultrarealistisch,
  ohne Text). Wird per Branche gematcht und als `static/img/hero.png` in den Build **kopiert**
  (kein Higgsfield-Call zur Bauzeit → Budget geschont). Echtes gutes Lead-Querformat schlägt die
  Vorlage (falls vorhanden).
- **Lokales Design der Hero-Sektion** (`design_tokens.py`): branchengerechte Farbpalette (HSL,
  WCAG-AA) + passendes Google-Font-Pairing → `static/css/tokens.css`.
- **Layout fix in der Vorlage**: links Eyebrow/Headline/Subline/CTAs (linksbündig), rechts der
  Kostenrechner mit Kategorien (`kostenrechner.js` + `content.rechner`).
- **Sofort deployen** (Repo + Railway + Domain) → Seite ist nach Stufe 1 **live**.
- Befehl/Funktion: `build_stage1_hero(folder)` — fehlerfrei, deterministisch.

### Stufen 2–4 — Sektionen (lokal, 0 Tokens)
Bauen den Rest aus `content.json` + den **Lead-Bildern** ein, je eine committet + gepusht:
- **Stufe 2 — Leistungen & FAQ**: Karten-Grid (Inline-SVG-Icons), FAQ-Akkordeon, Kontakt-Band.
- **Stufe 3 — Über uns & Team**: Über-Text + Trust; **Lead-Logo** und **Team-/Inhaberfoto**
  (aus `lead_images`) einbauen, sonst saubere Platzhalter; Galerie aus weiteren Lead-Fotos.
- **Stufe 4 — Kontakt, Recht & QA**: Kontaktdaten (tel/wa.me/mailto), echte OSM-Karte, Formular
  (csrf, Einwilligung→Datenschutz), Footer mit Impressum/Datenschutz/AGB, mobiler Sticky-Bar,
  Responsive-/Link-Check, `manage.py check`.
- Jede Stufe: lokales Coder-Modell/Template-Logik, **kein Claude**, Render-Gate + Commit + Push.

### Stufe 5 — Claude-Veredelung (der EINE Claude-Pass)
- Headless Claude Code mit **taste + design-pro** geht über die fertige Seite: Feinschliff von
  Komposition, Rhythmus, Typo-Details, Politur — **kein Neuaufbau**, knappes Budget.
- Danach finaler Deploy (**Push original**) + Discord-Freigabe (1× 👍 → Angebots-Mail).

**Engine-Schalter** (`overnight_makeover.JARVIS_MAKEOVER_ENGINE`): `hybrid` = Stufen lokal +
Stufe 5 Claude (Standard). `lokal` = ganz ohne Claude.

---

## 3. Hero-Vorlagen (`hero_templates/`)

- 6 vorgenerierte Higgsfield-Bilder (16:9, ohne Text, ultrarealistisch, links Headline-Raum,
  rechts ruhig für die Rechner-Karte) für die Top-Branchen:
  **Zahnarzt, KFZ-Werkstatt, Physiotherapeut, Umzug, Sanitär/Heizung, Elektriker.**
- `hero_templates/manifest.json`: Branchen-Keywords → Bilddatei (+ generischer Fallback).
- `hero_templates.py`: `pick(branche)` → Pfad; `apply(folder, branche)` kopiert die Vorlage als
  Hero. Erweiterbar — weitere Branchen jederzeit nachgenerieren.

---

## 4. Dauerbetrieb & Hygiene

- **Live-Watcher**: prüft die 5 Tagesseiten regelmäßig (HTTP 200). 404/down → Re-Deploy
  (nutzt den vorhandenen Rescue-Pfad im Night-Builder).
- **Auto-Refill**: `_count_today()` zählt nur real existierende Seiten → nach Löschen wird
  nachgebaut bis 5.
- **Cleanup-Befehl** `cleanup_websites.py`: löscht ALLE bisher erstellten Seiten endgültig aus
  **GitHub + Railway + Dashboard-DB** (Neuanfang). Einmalig vor dem Scharfschalten.
- **Doppel-Schutz**: gelöschte Leads werden archiviert (lokal + Cross-PC sticky).

---

## 5. Umsetzungs-Reihenfolge (Status)

- [x] 6 Hero-Vorlagen generieren (Higgsfield) → `hero_templates/`
- [x] `design_tokens.py` (lokale Farb-/Font-Stufe) — bereits vorhanden
- [ ] `hero_templates.py` + Manifest, in `website_builder._run` einhängen (Stufe 1)
- [ ] Stufen 2–4 als lokale Schritte sauber trennen (heute: 1 lokale Stufe — aufteilen)
- [ ] `cleanup_websites.py` (alle Altseiten löschen)
- [ ] Live-Watcher (periodischer 404-Check der Tagesseiten)
- [ ] Tests grün, pushen

> Token-Disziplin bleibt: Stufen 1–4 lokal (Ollama/Templates), nur Stufe 5 Claude.
> Verwandt: `TOKEN_PLAN.md`, `MAKEOVER.md`.
