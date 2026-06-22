# Werkzeuge & Skills für die lokale Coding-KI

> Leitfaden für eine lokale Ollama-KI (z.B. `qwen2.5-coder`), die in einer Agent-Schleife eine bestehende Django-Landing-Page (`content.json` + `templates/index.html` + `static/css/style.css` + `static/img/`) eigenständig verbessert und neue Features einbaut. (Erstellt vom Agenten-Team.)

---

## 1. Tool-Design-Prinzipien für schwächere lokale Modelle

Lokale Modelle scheitern selten am Code, fast immer am **Tool-Protokoll**. Darum: maximale Vorhersehbarkeit, minimaler Freiheitsgrad.

- **Sprechende, verbgeführte Namen** — `read_file`, `write_file`, `replace_in_file`. Kein `proc`, `exec`, `do`.
- **Klein und atomar** — ein Tool = eine Aktion.
- **Ein Tool pro Schritt** — pro Agent-Turn genau **ein** Tool-Call, nie Batches.
- **Strikte, flache JSON-Schemas** — nur string/integer/boolean, keine verschachtelten Objekte.
- **Schreiben via Diff, nicht Voll-Datei** — `replace_in_file` zwingt zu kleinen, prüfbaren Änderungen.
- **Fehlertolerante, sprechende Rückgaben** — immer mit `hint` als Self-Repair-Quelle.
- **Idempotenz & Vorschau** — `replace_in_file` meldet, wenn `find` 0× oder >1× vorkommt.
- **Token-sparsame Outputs** — große Dateien nie komplett zurückgeben.
- **Eingebaute Guardrails** — `render_check`/`compile_check` mit Zeilennummer.

## 2. System-Prompt-Vorlage (lokaler Coder)
Rolle CODER, ReAct-Schleife (EIN Gedanke, EINE Action, dann Observation). Eiserne Regeln:
1. IMMER read_file vor replace_in_file. 2. content.json: nur Werte, NIE Struktur brechen.
3. Vor "FERTIG" IMMER render_check(). 4. Nach .py-Änderung compile_check(). 5. Eine
kleine Änderung pro Schritt. 6. design-pro. 7. Bei Unsicherheit lesen statt raten.
Antwortformat: striktes JSON `{"thought":...,"action":{"tool":...,"args":{...}}}`,
zum Abschluss `{"thought":...,"done":true,"summary":...}`.

## 3. Eingebettete Skills (komprimiert)

### design-pro — Kernprinzipien
- Spacing-System (4/8/16/24/32/64), großzügiger Weißraum, ein Rhythmus.
- Typo-Hierarchie: max. 2 Schriften, klare Skala, line-height ~1.6, Zeilen ≤70 Zeichen.
- Farbe diszipliniert: 1 Markenfarbe + 1 Akzent + Neutrals; Akzent nur für CTAs; Kontrast AA.
- Tiefe sparsam: weiche große Schatten, konsistente Radien, keine harten Linien überall.
- Anti-KI-Look: keine Lila-Gradienten-Defaults, keine zentrierten Textwüsten, echte Bilder.
- Mobile-first & Hover/Fokus-States, alles responsiv (clamp/Grid/Flex).

### Conversion-UX
- Eine klare Aktion pro Sektion; primärer CTA above the fold im Akzent, mit Verb.
- Vertrauen sofort: Bewertungen, Jahre Erfahrung, echte Fotos, Siegel weit oben.
- Reibung senken: kurze Formulare, Telefon klickbar (tel:).
- Scannbarkeit: Nutzen vor Features, Bulletpoints, klare Headlines.
- Lokale Signale: Ort/Region im Hero & Title, Karte, Einzugsgebiet.
- Sticky-CTA mobil ("Anrufen/Anfragen").

### Deutsche Web-Texter-Regeln
- Sie-Form konsequent, seriös, kein Denglisch/Floskeln.
- Nutzen statt Selbstlob; kurze Sätze, aktive Verben, konkrete Zahlen.
- CTAs handlungsstark (Imperativ + Vorteil).
- Vertrauensvokabular: Festpreis, kostenlos & unverbindlich, Meisterbetrieb.
- SEO lokal: Leistung + Ort in H1/Title/Alt.

## 4. Feature-Backlog je Branche
(In `feature_backlog.py` kodiert.) Dachdecker, Elektriker, KFZ, Friseur, Restaurant,
Umzug, Arzt/Praxis — je 4-6 klein umsetzbare Features (Angebotsformular, Öffnungszeiten-
Box, Referenzen-Slider, FAQ-Akkordeon, Google-Maps, Bewertungs-Sterne, Notdienst-Banner,
Preisliste, Team-Sektion, Kostenrechner, Ablauf-Stepper …).

## 5. Qualitäts-Checkliste (nach jedem Feature)
render_check ok · compile_check ok · content.json intakt · keine toten Referenzen ·
responsiv (≤375px) · CTA/Funktion korrekt · design-pro · Texte deutsch/sauber ·
a11y-Minimum (alt/label/Kontrast) · keine Regression · Diff minimal · kurzes Summary.
