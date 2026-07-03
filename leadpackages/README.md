# LeadForge — Datenpakete-Modul

Isoliertes Modul in Jarvis2: recherchiert, bewertet und bündelt DACH-weite
Firmendaten zu verkaufsfertigen CSV/Excel-Paketen. Läuft neben der bestehenden
Website-Verkaufs-Pipeline (`scrapers/`, `agents/`, `db_raw.py`, `db_evaluated.py`)
her, ohne sie zu verändern. Vollständiger Bauplan inkl. aller Entscheidungen und
Recherche-Ergebnisse: `leadforge/MASTER_PLAN.md` im Desktop-Ordner.

## Kurzüberblick

- **Datenquellen:** DE aus der bestehenden `evaluated_leads`-DB (nur gelesen, per
  `db_packages.migrate_from_evaluated()` re-importiert), AT über `sources_herold.py`
  (herold.at, aktuell nur Stadt **Wien** validiert — siehe Einschränkung unten).
  CH ist zurückgestellt (robots.txt von local.ch/search.ch verbietet die Suchpfade).
- **Mindestqualität:** ein Datensatz braucht mindestens 2 von 3 Kontaktwegen
  (Telefon/E-Mail/Website), sonst wird er gar nicht erst gespeichert
  (`db_packages.MIN_KONTAKTWEGE`).
- **Scoring:** eigener `quality_score` (0–100, rein arithmetisch) + optionales
  `potential_label` (klein/mittel/groß, per Ollama mit Heuristik-Fallback).
- **Pakete:** feste Bundle-Größen 50/200/1000 (`pricing_packages.py`), bestes
  Material zuerst (`package_builder.py`).
- **Export:** CSV + Excel, mit unsichtbarem Käufer-Wasserzeichen (`watermark.py`)
  gegen Weiterverbreitung.
- **Verkauf:** manuell — kein Payment-Provider. Der Dashboard-Tab erzeugt die
  Datei direkt, Bezahlung läuft außerhalb des Tools.

## Betrieb

- Der Tab "📦 Datenpakete" ist im laufenden Jarvis2-Dashboard sofort nutzbar
  (`python start.py`, dann im Browser den Tab öffnen).
- Der Hintergrund-Scheduler (`scheduler.py`) ist gebaut, aber **noch nicht
  automatisch gestartet** — dafür in `app.py` ergänzen:
  ```python
  from leadpackages import scheduler as leadpackages_scheduler
  leadpackages_scheduler.start()
  ```
  Ohne das läuft der Vorrat nur über das On-Demand-Nachscrapen beim Bestellen
  (`scheduler.ensure_stock()`, wird automatisch von der Bestell-Route aufgerufen).
- Abschaltbar per `JARVIS_LEADPACKAGES_SCHEDULER=0` in `.env`.

## Bekannte Einschränkungen (bewusst dokumentiert, keine stillen Lücken)

1. **herold.at-Kategorieseiten funktionieren zuverlässig nur für Wien.** Andere
   Städte (Graz, Linz, Innsbruck getestet) liefern 404 auf dem geratenen
   URL-Schema — vermutlich sind Kategorie-Listings nur für Städte mit genug
   Einträgen statisch vorgeneriert. Firmen-Detailseiten existieren für alle
   Städte laut Sitemap, nur die Übersichtsseite pro Branche+Stadt nicht.
   Folgeschritt: das echte Such-URL-Schema von herold.at reverse-engineeren
   (bewusst nicht in dieser Runde gemacht, um kein Overengineering einer
   undokumentierten Schnittstelle zu betreiben).
2. **Schweiz (CH) ist nicht angebunden.** local.ch und search.ch verbieten ihre
   Suchpfade per robots.txt. Zefix (offizielles Handelsregister) wäre die
   sauberste Alternative, liefert aber keine Telefon/E-Mail — bräuchte eine
   zusätzliche Kontakt-Anreicherung (analog `contact_finder.py`).
3. **KI-Funktionen (Paketbeschreibung, Potenzial-Label) brauchen laufendes
   Ollama.** Ohne Ollama greift automatisch ein deterministischer Fallback-Text
   bzw. eine regelbasierte Heuristik — die Endpunkte sind über
   `_ollama_bounded.py` hart auf 6s Wartezeit begrenzt, damit ein Dashboard-
   Button nie lange hängt.
4. **Preise (`pricing_packages.py`) sind Startwerte** (50 Leads/49€,
   200/149€, 1000/499€) — im Code anpassbar, noch keine UI dafür.

## Wichtige Dateien

| Datei | Zweck |
|---|---|
| `db_packages.py` | Eigene SQLite-DB (`data/lead_packages.db`): `stock_leads`, `packages`, `orders` |
| `sources_dach.py` | AT/CH-Regionen+Städte (DE wiederverwendet aus `scrapers/regions.py`) |
| `scrapling_engine.py` | Dünner Scrapling-Wrapper (plain/stealth/dynamic Fetcher) |
| `sources_herold.py` | herold.at-Scraper (aktuell: Wien) |
| `quality_score.py` / `potential_score.py` | Bewertung (arithmetisch / KI+Heuristik) |
| `dedup_fuzzy.py` | Zusätzliche Fuzzy-Dublettenerkennung (rapidfuzz) |
| `package_builder.py` / `pricing_packages.py` | Paket-Zusammenstellung + Preise |
| `export_csv_excel.py` / `watermark.py` / `ollama_summary.py` | Export-Pipeline |
| `scheduler.py` | Hybrid-Vorrat (Hintergrund) + On-Demand-Nachscrapen |
| `routes.py` | Alle `/api/leadpackages/*`-Endpunkte |
| `_ollama_bounded.py` | Harte 6s-Zeitschranke für Ollama-Aufrufe aus Web-Requests |

Tests: `tests/test_leadpackages.py` (`python -m pytest tests/test_leadpackages.py -v`).
