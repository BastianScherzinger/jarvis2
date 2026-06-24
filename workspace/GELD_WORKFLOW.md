# JARVIS — Geld-Workflow, Status & Wert (Stand 24.06.2026)

> Vollständige Durchsicht des Programms: wie automatisch Geld entsteht (vom Lead-Finden
> bis der Kunde auf die E-Mail antwortet und zahlt), was schon fertig ist, was noch fehlt,
> der Wert jedes Bausteins (jetzt → fertig) und eine ehrliche Einschätzung.
> Diese Doku ist die Langfassung der neuen **Home-Seite** im Dashboard.

---

## Kurz: Was JARVIS ist
Eine Maschine, die vollautomatisch lokale Betriebe ohne (gute) Webseite findet, sie mit
lokaler KI bewertet, jedem eine echte live-geschaltete Premium-Webseite als unverbindliches
Demo baut und ein Angebot per E-Mail verschickt — bei nahezu null Stückkosten.

## Ehrliche Einschätzung — lohnt sich das?
**Ja, mit Vorbehalt.** Der echte Vorteil: Leads finden + Webseiten bauen kostet praktisch
nichts (lokale Scraper + lokale KI + Higgsfield-Abo) und skaliert deutschlandweit. Für echtes
Geld zählen vier Hebel:
1. **Zustellbarkeit & Recht (wichtigster Punkt):** Kalt-Mails an Betriebe sind in DE rechtlich
   heikel (UWG §7, DSGVO) und landen schnell im Spam. Ohne saubere Zustellung + Rechtsrahmen
   kommt nichts an.
2. **Conversion:** realistisch 0,5–2 % → braucht Volumen (das macht JARVIS billig).
3. **Qualität:** die Demo muss agenturnah aussehen (7-Stufen-Makeover).
4. **Hosting-Kosten:** Live-Demos kosten Hosting → nicht verkaufte automatisch abbauen.

**Beispiel:** 1.000 Mails × 1 % × 350 € = 3.500 € bei ~null Grenzkosten. Nicht garantiert,
aber als skalierbares Nebengeschäft plausibel, sobald Schritt 6 (Zustellbarkeit/Recht) steht.

---

## Der Geld-Workflow — Schritt für Schritt

| # | Schritt | Status | Wert jetzt | Wert fertig |
|---|---------|--------|-----------:|------------:|
| 1 | Leads finden (lokal, kostenlos) | ✅ Fertig | 300 € | 800 € |
| 2 | Bewerten & Preis (lokale KI) | ✅ Fertig | 250 € | 700 € |
| 3 | Webseite bauen + live schalten | ✅ Fertig | 500 € | 1.500 € |
| 4 | Premium-Makeover (7 Stufen) | ✅ Fertig | 400 € | 1.200 € |
| 5 | Qualitäts-Freigabe (Discord) | ✅ Fertig | 100 € | 250 € |
| 6 | Angebots-E-Mail an Kunden | 🟡 Teilweise | 150 € | 900 € |
| 7 | Antwort → Abschluss & Zahlung | ❌ Offen | 0 € | 500 € |
| 8 | Dashboard, Medien & Kosten | ✅ Fertig | 350 € | 800 € |
| | **Gesamt (ehrlich, Einzelnutzer-Werkzeug)** | | **~2.000 €** | **~6.500 €** |

> **Ehrlich eingeordnet:** mit Claude (KI) gebautes Solo-Projekt eines Einsteigers — kein
> verkaufsfertiges Produkt, kein Agentur-Wiederaufbaupreis. Die Zahlen schätzen, was ein
> Freelancer für den Nachbau dieser *funktionierenden* Bausteine etwa nehmen würde. Der echte
> Wert ist nicht der Code, sondern was das System einbringt — und das hängt an Schritt 6
> (Zustellbarkeit/Recht) + der Conversion, nicht an diesen Beträgen.

### 1 · Leads finden — ✅ Fertig, kostenlos
- **Jetzt:** `scrapers/controller.py` mit 6 Workern (Google Maps via Playwright-Browser — NICHT
  die bezahlte Places-API; Gelbe Seiten, Das Örtliche, 11880, golocal, KI-Worker) → `leads_raw.db`
  (Name/Adresse/Telefon/Bilder/Branche), deutschlandweit, dedupliziert.
- **Noch:** Dubletten-Feinschliff, Stadt-/Branchen-Priorisierung tunen.

### 2 · Bewerten & Preis — ✅ Fertig, kostenlos
- **Jetzt:** Evaluator-Threads (= CPU-Kerne) → `web_analyst` (Website/URL/Bilder via DuckDuckGo+
  urllib) + `social_researcher` + `score_writer` (Ollama: Score, Preis-Tier, Beschreibung, Pitch,
  Mail-Entwurf) → `leads_evaluated.db`. Preis mehrfaktoriell (Branche+Bedarf+Bewertungen+Größe+
  Upgrade-Motiv+Rating).
- **Noch:** Preis-Tiers an reale Abschlüsse kalibrieren.

### 3 · Webseite bauen + live — ✅ Fertig
- **Jetzt:** `website_builder.build` → Django-Landingpage, Texte (Ollama/Claude), Hero über
  Higgsfield (Abo), Deploy auf Railway → echter Live-Link.
- **Noch:** Eigene Domain je Demo (statt railway.app); Live-Demos automatisch abbauen, wenn nicht
  verkauft (Hosting-Kosten deckeln).

### 4 · Premium-Makeover — ✅ Fertig (gerade gefixt)
- **Jetzt:** `overnight_makeover` 7 Stufen (Hero, Leistungen, Über uns, Kontakt, Formular,
  Voll-Design „taste", QA + Impressum/Datenschutz/AGB), token-sparsam, Status je Stufe gespeichert.
- **Noch:** Live über viele Seiten verifizieren, Qualität stichprobenartig prüfen.

### 5 · Qualitäts-Freigabe (Discord) — ✅ Fertig
- **Jetzt:** Fertige Seite → Discord-Abstimmung, 👍 gibt frei / 👎 verwirft. Qualitäts-Gate vor
  echtem Kundenkontakt.
- **Noch:** optional Vorschau-Screenshot statt nur Link.

### 6 · Angebots-E-Mail — 🟡 Teilweise (Schlüssel zum Geld)
- **Jetzt:** `offer_mail` baut designte Mail mit Live-Link; freigegebene Seiten gehen
  `DISCORD_SEND_HOUR` (12 Uhr) automatisch raus; Trockenlauf-Schalter `JARVIS_EMAIL_ENABLED`
  schützt vor versehentlichem Versand.
- **Noch:** SMTP einrichten + scharf schalten; **Zustellbarkeit** (eigene Domain, SPF/DKIM/DMARC,
  Aufwärmen, Spam vermeiden); **Recht** (UWG/DSGVO, Abmelde-Link, Impressum); **Preis dynamisch**
  statt fix 350 € (aktuell hardcodiert in `offer_mail.build` — sollte an `erwartungswert_euro`
  des Leads koppeln).

### 7 · Antwort → Abschluss & Zahlung — ❌ Offen (bewusst manuell)
- **Jetzt:** Antworten kommen ins Postfach; Abschluss/Rechnung/Übergabe manuell.
- **Noch:** leichtes CRM (Antwort-Status), Zahlungslink/Rechnung (z.B. Stripe), Übergabe-Checkliste.
  Für einen 350-€-Verkauf ist ein menschlicher Abschluss aber sogar von Vorteil (höhere Conversion).

### 8 · Dashboard, Medien & Kosten — ✅ Fertig
- **Jetzt:** Iron-Man-Dashboard, Medien-Studio (Bild/Video, Higgsfield/ChatGPT), Live-Kostentracking,
  Auto-Builder mit Stopp/Resume + Limit-Resilienz, neue Home-Übersicht.
- **Noch:** Conversion-/Umsatz-Auswertung, A/B-Test der Betreffzeilen.

---

## Prioritäten — damit echtes Geld rauskommt
1. **E-Mail-Zustellung & Recht lösen** (Schritt 6) — eigene Versand-Domain + SPF/DKIM/DMARC,
   langsames Aufwärmen, Abmelde-Link, UWG/DSGVO-Rahmen. **Ohne das kein Umsatz.**
2. **Angebotspreis = bewerteter Tier** statt fix 350 € (`offer_mail`).
3. **Volumen hochfahren** — Auto-Builder dauerhaft, Qualität stichprobenartig prüfen.
4. **Demos abbauen**, die nach X Tagen nicht konvertieren (Hosting-Kosten).
5. **Conversion messen** — Antworten/Abschlüsse pro 100 Mails sichtbar machen.

---

## Was in diesem Durchgang gemacht wurde
- Komplette Programm-Durchsicht + dieser Geld-Workflow dokumentiert.
- **Home-Seite ersetzt:** statt Webseiten-Grid jetzt die Programm-Übersicht (Intro, ehrliche
  Einschätzung, 8-Schritt-Workflow mit Status + Wert je Schritt, Gesamtwert, Prioritäten) —
  `templates/index.html` (`.ov*`-Block), `static/css/style.css` (`.ov*`-Styles). Live-Stats-Strip
  oben + Aktivitäts-Panel unten bleiben. Verifiziert (Playwright): rendert, 0 relevante Fehler.
- Das Webseiten-Grid bleibt unverändert im **Webseiten-Reiter** erreichbar (keine Funktion verloren).
- **Werte realistisch korrigiert** (Einzelnutzer-Werkzeug, mit KI gebaut): gesamt ~2.000 → ~6.500 €.
- **Grafische Darstellungen ergänzt:** Pipeline-Flussdiagramm (7 Knoten, farbcodiert nach Status),
  zwei Fortschritts-Anzeigen (Technik ~80 % / Umsatz-bereit ~45 %) und ein Wert-Balkendiagramm
  (jetzt vs. fertig je Baustein) — alles pure HTML/CSS im HUD-Stil.
