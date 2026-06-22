# JARVIS — Änderungen 22.06.2026 (Kontakt-Finder, E-Mail-Links, Render-QA)

Folgedurchgang zu `AENDERUNGEN_2206.md`. Behebt zwei gemeldete Bugs + härtet die
Verbesserungs-Pipeline.

## 1. „Keine Kontaktinfo" → aktiver Kontakt-Finder
**Ursache:** Von 4669 Leads haben nur 159 eine E-Mail. Gerade Leads OHNE Website
haben fast nie eine gespeicherte Adresse (sie wird sonst aus deren Impressum gezogen).
Der „An Kunde senden"-Button war also korrekt deaktiviert — es fehlte die Adresse.

**Fix — `contact_finder.py` (neu):** sucht die Adresse on demand.
- Stufe 1: `web_analyst.analyze()` (DDG-Suche → echte Website → Impressum-Scan →
  E-Mail + Ansprechpartner). Findet auch bei `has_website=0`.
- Stufe 2: `agent_maps.place_contact()` (Google Places → offizielle Website) → erneuter Scan.

**Verdrahtung:**
- `website_builder._enrich_contact()` läuft nach jedem Bau (best-effort) und füllt
  `kontakt_email` + `ansprechpartner` in `db_websites`.
- Neue Route `POST /api/websites/<id>/find-contact` + Frontend-Button **„🔎 Kontakt finden"**
  (erscheint, wenn keine Adresse da ist; wird nach Fund zu „✉ An Kunde senden").
- `offer-email`-Route (mode=real): findet bei fehlender Adresse jetzt aktiv eine, statt
  nur abzulehnen.
- `db_websites`: neue Spalte `ansprechpartner` (+ Migration) + `set_contact()`-Helfer.

## 2. „Links in den E-Mails klappen nicht"
**Ursache:** `offer_mail` rendert bei leerem Link `href="(Link folgt)"` (kaputt) und
nutzte als Fallback den GitHub-Repo-Link als „Webseite" (kein ansehbares Ziel).

**Fix — `offer_mail.py`:**
- `_norm_url()` erzwingt `https://` (nackte Railway-Domain → klickbar) und gibt bei
  Unsinn `""` zurück.
- Ohne gültigen Live-Link wird **kein kaputter Button** gerendert — stattdessen
  ehrlicher Hinweis „Link auf Anfrage".
- Persönliche Anrede mit Ansprechpartner („Guten Tag {Name},").
- Route + Auto-Builder nutzen nur noch `live_url` (kein Repo-Link) als Webseiten-CTA.
- Alle dynamischen Werte HTML-escaped.

## 3. Verbesserungs-Pipeline gehärtet (`website_improve.py`)
- **`_sanitize_content()`** erzwingt die vom Premium-Template erwarteten Typen
  (leistungen/usps/faq/fotos = Listen, akzent = gültiger Hex, jahr = int) → eine von
  Claude unsauber gelieferte content.json kann die Live-Seite nicht mehr zum 500er machen.
- **`_render_check()`** rendert das echte Django-Template mit der finalen content.json
  VOR dem Deploy (fängt strukturelle Fehler ab).
- **`_wire_contact()`** übernimmt eine gefundene Kontakt-E-Mail in die Seite → der
  `mailto:`-Button auf der Live-Seite funktioniert.

## 4. Tests/Audit
- `tests/test_core.py`: 41 → **49** Tests (offer_mail Schema/ohne-Link/Anrede, sanitize,
  render-check, set_contact, contact_finder mit/ohne Treffer). Alle grün.
- `smoke_audit.py`: 51/51 grün.
