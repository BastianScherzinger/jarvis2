---
name: premium-landing
description: >
  Kompakter, token-armer Premium-Skill zum Bauen UND Umgestalten von verkaufsstarken
  Local-Business-Landingpages (Handwerk, Dienstleister, Gastro, Praxen). Destilliert
  taste / design-pro / ui-ux-pro-max auf EIN konkretes, immer gleiches Seiten-Rezept mit
  festen Design-Tokens, Font-Pairings, Spacing-Skala und Sektions-Bauplan. Nutze ihn für
  jede Hero-, Leistungs-, Über-uns-, Kontakt-, Formular- oder Gesamt-Design-Aufgabe an
  einer Django-Landingpage, die aus content.json über templates/index.html +
  static/css/style.css rendert. Ziel: sieht aus wie von einer Agentur, nicht templated.
---

# Premium Local-Business Landing — der eine richtige Bauplan

Du gestaltest die Verkaufs-Landingpage eines echten lokalen Betriebs. Sie soll einen Kunden
in 5 Sekunden überzeugen und seriös, aber **farbig-schlicht** wirken — nie „KI-generiert",
nie templated, nie überladen. **Weniger, aber besser.** Funktion vor Effekt.

Arbeite **effizient**: wenige, gezielte Edits, jede Datei höchstens einmal lesen, keine
Endlos-Iterationen. Baue immer auf dem vorhandenen Stand auf (minimaler Diff).

---

## 1. Design-Tokens (immer als CSS-Variablen in :root)

EINE Akzentfarbe (kommt aus `content.json.akzent`) + leicht **getönte** Neutrals (nie reines
#000/#fff). Definiere und benutze konsequent diese Tokens — keine verstreuten Hex-Werte:

```css
:root{
  --accent:        /* aus content.json.akzent */;
  --accent-ink:    /* dunklere Variante des Akzents für Text-auf-hell */;
  --bg:            #fbfaf8;   /* warm getöntes Off-White */
  --surface:       #ffffff;   /* Karten */
  --ink:           #15171c;   /* fast-schwarz, leicht blau/warm getönt */
  --muted:         #5c616b;   /* Sekundärtext */
  --line:          #e7e4df;   /* Rahmen/Trenner */
  --ring:          color-mix(in srgb, var(--accent) 45%, transparent);
  --radius:        14px;
  --shadow-sm:     0 1px 2px rgba(20,23,28,.06), 0 1px 1px rgba(20,23,28,.04);
  --shadow-md:     0 8px 24px -12px rgba(20,23,28,.18);
  --shadow-lg:     0 24px 60px -24px rgba(20,23,28,.28);
}
```

- Kontrast immer WCAG-AA (Text auf Akzent prüfen; bei hellem Akzent dunkleren `--accent-ink`
  für Text benutzen, Buttons mit weißer Schrift nur bei dunklem Akzent).
- Akzent **sparsam**: CTAs, aktive Zustände, kleine Marker — nicht großflächig fluten.

## 2. Typografie

- Display/Headlines: charakterstarker Serif **oder** geometrischer Sans (Google Fonts), z. B.
  `Fraunces`, `Bricolage Grotesque`, `Sora`, `Clash`-Alternative `Space Grotesque`.
- Body: ruhiger, gut lesbarer Sans (`Inter`, `Instrument Sans`).
- Genau **zwei** Familien. Fluide Skala mit `clamp()`:
  `h1 clamp(2.1rem,5vw,3.6rem)`, `h2 clamp(1.5rem,3vw,2.2rem)`, body `1.0625rem`,
  line-height 1.15 (Headlines) / 1.6 (Body). Headlines `letter-spacing:-.02em`.

## 3. Spacing & Layout

- Spacing-Skala fest: 4 / 8 / 12 / 16 / 24 / 32 / 48 / 72 / 112 px.
- Container `.wrap`: `max-width:1120px; margin-inline:auto; padding-inline:clamp(20px,5vw,40px)`.
- Sektions-Abstand `padding-block:clamp(64px,9vw,112px)`. Großzügiger, rhythmischer Weißraum.
- Abwechselnde Sektions-Hintergründe (`--bg` / `--surface` / leicht getönt) für Rhythmus.

## 4. Komponenten

**Buttons** (Touch-Ziel ≥ 44px, `border-radius:10px`, `font-weight:600`, `transition:.18s ease`):
- `.btn` primär: `background:var(--accent); color:#fff` (oder ink bei hellem Akzent),
  `box-shadow:var(--shadow-md)`, hover `translateY(-1px)` + dunkler.
- `.btn-ghost`: transparent, `border:1px solid var(--line)`, hover `border-color:var(--accent)`.
- `.btn-wa` (WhatsApp): `background:#25D366; color:#0b3d2c` mit Inline-SVG-WhatsApp-Icon.
- Voll sichtbare Zustände: `:hover :focus-visible :active`, `focus-visible` mit `outline:2px
  solid var(--ring); outline-offset:2px`.

**Karten** (`.card`): `background:var(--surface); border:1px solid var(--line);
border-radius:var(--radius); padding:24px; box-shadow:var(--shadow-sm)`, hover `shadow-md` +
`translateY(-2px)`. Konsistente **Inline-SVG-Icons** (1.5px stroke, `currentColor`) — **nie Emojis**.

**Bilder/Platzhalter**: jeder fehlende Bild-Slot wird als sauberer Platzhalter gebaut —
`aspect-ratio` gesetzt, getönter Hintergrund, zentriertes dezentes Icon + kleiner Label-Text
(z. B. „Foto folgt"). Niemals ein gebrochenes `<img>`. Platzhalter behalten dasselbe Layout
wie das spätere echte Bild.

**Motion**: nur `transform`/`opacity`, 150–400 ms, `ease-out`; dezentes Reveal beim Scrollen
optional. `@media (prefers-reduced-motion:reduce)` respektieren (alles abschalten).

## 5. Der Sektions-Bauplan (genau diese Reihenfolge)

1. **Sticky-Header**: Logo/Name links, Anker-Nav mittig (Leistungen · Über uns · Kontakt),
   rechts ein kleiner primärer CTA. Auf Mobil eingeklappt; unten ein **Sticky-Anruf-/WhatsApp-Balken**.
2. **Hero** (above the fold): Higgsfield-Bild als Hintergrund (`content.json.hero_image`).
   **Das Bild selbst enthält NIEMALS Text/Logos/Wörter** — Headline & Co. sind ausschließlich
   HTML-Text in einem `.hero-copy`-Overlay. Lesbarkeit über Scrim/Gradient
   (`linear-gradient` über dem Bild) sicherstellen. Inhalt: Eyebrow (Branche · Stadt),
   kraftvolle betriebsgenaue **Headline** mit Nutzenversprechen, eine **Subline**, dann eine
   Button-Reihe: **WhatsApp** (`https://wa.me/<nummer ohne +/Leerzeichen>?text=…`), **E-Mail**
   (`mailto:`), **Anrufen** (`tel:`) — primärer CTA dominant, Rest leiser. Darunter dezente
   Vertrauenssignale (Bewertung/Region/Jahre/Erreichbarkeit).
3. **Leistungen**: Einleitungssatz + 4–6 **branchenspezifische** Leistungskarten (Titel,
   Nutzen-Text, SVG-Icon) im sauberen Grid. Ein Platzhalterbild/Mockup dezent integrierbar.
4. **Kontakt-Band** (zwischen Leistungen und Über uns): schmaler Streifen in Akzent-Tönung mit
   einer klaren Zeile + WhatsApp- und Anruf-Button (zweiter Conversion-Punkt).
5. **Über uns**: glaubwürdige Geschichte (Region, Erfahrung, Werte). Links/oben ein
   **Platzhalter für das Foto des Inhabers** (Label „Inhaber"), darunter ein **Team-Grid mit 4
   Mitarbeiter-Platzhaltern** (rundes Avatar-Placeholder + Name/Rolle als „[Name]"). Daneben
   eine USP-/Trust-Liste (Garantien, Referenzen, Erreichbarkeit).
6. **Kontaktformular**: Name, E-Mail, Telefon, Nachricht, Einwilligungs-Checkbox →
   Datenschutz. `method="post"`, `{% csrf_token %}`, korrekte input-Typen, `required`,
   sichtbare Labels, `focus-visible`, klare Erfolgs-/Fehlerstelle. Daneben Kontaktdaten +
   (falls Adresse vorhanden) eingebettete **OpenStreetMap** (iframe, kein API-Key).
7. **Footer**: **unten links** gut sichtbar die Rechts-Links — **Datenschutz, Impressum, AGB**
   — plus © Jahr, Name, Branche · Stadt, kurze Kontaktzeile. Rechtstexte stehen fertig in
   content.json (`datenschutz`, `impressum`, `agb`) → als eigene Abschnitte/Unterseiten rendern,
   Absätze erhalten.

## 6. Qualitäts-Gate (immer prüfen)

- Mobil perfekt: echte Breakpoints (≤640 / ≤960), keine horizontalen Überläufe, kein CLS,
  Touch-Ziele ≥ 44px, Sticky-Anruf/WhatsApp auf Mobil.
- Alle Links/Buttons/Anker funktionieren; `tel:`/`mailto:`/`wa.me` korrekt formatiert.
- SEO-Grundgerüst: `<title>`, meta description, eine `<h1>`, saubere Überschriften-Hierarchie,
  `alt`-Texte, `loading="lazy"` bei Bildern.
- content.json bleibt valides JSON; bestehende Keys (`hero_image`, `logo_image`, `fotos`,
  Rechtstexte) NICHT löschen. Am Ende MUSS das Template fehlerfrei rendern.

## 7. Anti-Slop (weglassen)

Keine generischen Stockfloskeln, keine Emoji-Icons, keine Glow-/Neon-Schatten, keine drei
konkurrierenden Akzentfarben, keine sinnlosen Animationen, keine leeren „Lorem"-Texte, keine
gebrochenen Bilder. Texte sind betriebsgenau aus den Lead-Daten — nichts erfinden, kein Geschwurbel.
