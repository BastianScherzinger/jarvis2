# JARVIS — Änderungen 21.–22.06.2026 (Webseiten-Pipeline, E-Mail, Cross-PC, Globus)

Wissensstand & Veränderungen dieses Durchgangs. Ergänzt `AENDERUNGEN.md`.

## 1. Webseiten-Bau zuverlässiger
- **Öffentliche Repos** statt privat (`agent_github.create_repo(private=False)`): GitHub-Link
  funktioniert im Browser, Railway kann das Repo klonen/bauen. Keine Secrets im Repo.
- **Ehrlicher Live-Status:** `_url_live()` pollt die Railway-Domain wirklich (bis 3 Min),
  bevor „live" gemeldet wird. Neue Spalte `db_websites.live` (verifiziert erreichbar).
  Badge: **● LIVE / Build läuft / Nicht live / Nur lokal**.
- **Geteiltes Railway-Projekt „Generated Websites"** (alle Seiten als Service darin).
- **Re-Deploy ohne Doppel-Service:** bei bekannter Live-URL nur `git push` → Railway
  baut automatisch neu (`_deploy_folder(redeploy_url=…)`).
- **Hero-Render mit Zeitlimit** (`JARVIS_HERO_TIMEOUT`, Default 180s) — kein 60%-Hänger.

## 2. Neuer „Webseiten"-Reiter (persistent, Cross-PC)
- `db_websites.py` (SQLite) + Reiter: Live-Status, Live-/GitHub-Links, lokaler Ordner,
  Bilder hinzufügen. Bau läuft serverseitig im Hintergrund weiter (wegklickbar).
- **Aktionen je Seite:** ✦ Top verbessern · ⌥ Mit Claude · ✉ Test an mich ·
  ✉ An Kunde senden · 🗑 Löschen.
  - **Top verbessern** (`website_improve.py`): 5-Agenten-Pipeline (Stratege→Texter→
    Bildregie→Designer→QA), Premium-Template (USP-Band, Über-uns-Bild, FAQ), Re-Deploy.
  - **Mit Claude:** Modal-Textfeld → content.json anpassen + neu deployen oder Frage
    beantworten (`website_improve.chat_edit`).
  - **Löschen:** DB + lokaler Ordner + best-effort GitHub-Repo & Railway-Service.

## 3. Cross-PC-Sync der Webseiten (Supabase)
- Tabelle **`jarvis_websites`** (site_key = Lead-Key name|stadt) + öffentlicher Storage-
  Bucket **`website-images`**.
- `cloud_sync_websites.py`: Push bei done/Bild/Löschen, Pull beim Start + alle 5 Min,
  `push_all_local()` schiebt bestehende Seiten hoch. Bilder → Storage (öffentliche URL).
- `db_websites`: Spalten `site_key` (+ Backfill) und `kontakt_email`; `upsert_remote()`.
- Ergebnis: alle PCs zeigen dieselben fertigen Seiten + Links + Bilder.

## 4. E-Mail-Versand (Angebot 350 €)
- **Designte HTML-Angebotsmail** (`app._build_offer_email`): Komplettpreis 350 €, alles
  anpassbar, Live-Link-CTA, auf Name/Branche/Stadt personalisiert.
- Zwei Wege: **Test an Bastian** + **An echte Kontaktadresse** (`mode` test/real;
  `mailer.send_email(bypass_redirect=True)`).
- **Sicherheits-Umleitung** `JARVIS_EMAIL_REDIRECT`: solange gesetzt, geht JEDE Auto-Mail
  an die Test-Adresse (nie versehentlich an echte Betriebe). Leeren = echter Versand.
- **Versand scharf:** `JARVIS_EMAIL_ENABLED=true`. **Wichtig:** Das Gmail-App-Passwort
  muss zum **SMTP_USER** gehören (war Mismatch: Passwort gehörte zu enigmabible1@gmail.com,
  nicht zu …05). Jetzt SMTP_USER=enigmabible1@gmail.com → LOGIN OK, Versand verifiziert.

## 5. Graph: 3D-Globus
- `static/js/globe.js`: schnell ladender Hologramm-Planet (Three.js, keine Texturen),
  Start-Zoom Deutschland, ziehen=drehen, Rad=zoomen, Intro-Animation + Marker-Puls.
- Lead-Standorte je Stadt als kleine farbige Marker (Hot/Warm/Cold). Koordinaten
  clientseitig (Stadt-Lookup + Bundesland-Zentren). `/api/graph/locations`.

## 6. Sprache + Setup
- **Spracheingabe-Fix:** `OPENBLAS_NUM_THREADS=1`/`OMP_NUM_THREADS=1` vor faster-whisper
  (behebt 500 bei der Transkription auf vielkernigen Windows-PCs).
- **install.py:** konfiguriertes Ollama-Modell wird bei Fehlen **automatisch nachgeladen**;
  alle relevanten Keys werden nach `~/.claude/.env` gesynct.

## Neue .env-Variablen
```
JARVIS_EMAIL_ENABLED=true
JARVIS_EMAIL_REDIRECT=<test-empfänger>   # leeren für echten Kundenversand
SMTP_USER / SMTP_PASS                    # App-Passwort MUSS zum SMTP_USER-Konto gehören
JARVIS_HERO_TIMEOUT=180                  # Sek., lokaler Hero-Render
JARVIS_RAILWAY_PROJECT=Generated Websites
```

## Tests/Audit
39 Unit-Tests + 50 Smoke-Audit-Checks grün. Visuell mit Playwright geprüft
(Webseiten-Reiter, Chat-Modal, E-Mail-Versand, 3D-Globus).
