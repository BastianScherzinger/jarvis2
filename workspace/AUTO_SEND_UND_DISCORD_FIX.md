# Auto-Send + Discord-Notification-Fix (2026-07-02)

## Auftrag (Sir)
1. Discord-Benachrichtigungen reparieren („Webseiten sind live, aber die Discord-Nachrichten nicht").
2. Webseiten **ohne Bestätigung** (ohne 👍) automatisch versenden.

## Diagnose
- `discord.py` 2.7.1 installiert, `DISCORD_*` in `.env` vollständig → der Bot verbindet sich
  und postet Start-/Abschluss-Embeds. Die Grundverbindung war also NICHT das Problem.
- **Kern-Schwachpunkt:** `discord_bot.submit_for_review()` legte einen Review **nur** an, wenn
  in genau diesem Moment `enabled() AND _started AND _loop` galt. War der Bot kurz nicht
  verbunden (Neustart-Race, Netz-Aussetzer), wurde die fertige Seite **weder in die Queue
  gelegt noch versendet** — sie fiel still in die Vorschau-Mail an Bastian. Ergebnis aus
  Sicht des Nutzers: „keine Nachricht, nichts geht raus".
- **Freigabe-Gate:** Seiten blieben auf `pending`, bis jemand 👍 klickte (29 hingen fest) →
  ohne Klick ging nie etwas an die Kunden.

## Umsetzung

### 1. `review_queue.py`
- `add(...)` bekam Parameter `status` (Default `PENDING`). Seiten können jetzt direkt
  `APPROVED` angelegt werden. Dedup/Persistenz unverändert.

### 2. `discord_bot.py`
- **Neuer Schalter** `auto_send()` → `JARVIS_AUTO_SEND` (Default **AN**;
  aus mit `0/false/no/off`).
- `submit_for_review()` grundlegend entkoppelt:
  - Legt den Review **immer** in die Queue (auch wenn der Bot offline ist).
  - Im Auto-Send-Modus mit Status `APPROVED` → geht ohne 👍 beim Tagesversand raus.
  - Discord-Post nur noch **Best-Effort**; Bot-Ausfall verhindert den Versand nicht mehr.
  - Gibt den Review zurück (nur `None`, wenn weder Auto-Send noch Bot aktiv → Fallback-Mail).
- `status()` meldet zusätzlich `auto_send`.
- Embed-/Footer-Texte spiegeln den Modus (Start-Embed, Review-Embed, 12-Uhr-Report):
  „Auto-Send AN — Versand HH:00 ohne Bestätigung", Review-Footer „✅ Automatisch freigegeben …
  👎 stoppt den Versand". 👎-Veto bleibt in beiden Modi wirksam (`approved_unsent` filtert
  `APPROVED`, ein 👎 setzt `REJECTED` → wird nicht versendet).

### 3. `overnight_makeover.py`
- `finalize_review()` reicht bei **Auto-Send ODER verbundenem Bot** ein (vorher nur bei
  verbundenem Bot). Vorschau-Mail-Fallback greift nur noch, wenn beides fehlt.

### 4. `auto_builder.py`
- Abschluss-Verabschiedung zeigt im Auto-Send-Modus „⚙️ N gehen um HH:00 automatisch an die
  Kunden" statt der irreführenden „warten auf deine Freigabe (👍)"-Zeile.

### 5. Doku/Config
- `.env.example`: neuer Discord-/Auto-Send-Block (alle `DISCORD_*` + `JARVIS_AUTO_SEND`).
- `CLAUDE.dev.md`: Makeover→Versand-Kette auf Auto-Send aktualisiert.

## Tests
- Neu: `test_discord_auto_send_queues_without_bot` — Seite landet ohne Bot als `approved`
  in der Queue und ist versandbereit.
- Angepasst: `test_discord_bot_import_safe` (mit `JARVIS_AUTO_SEND=0`) prüft weiter den
  No-op-Pfad + neues `auto_send`-Statusfeld.
- **Gesamt: 103/103 Tests grün.**

## Nachtrag (2026-07-02, 2. Runde): Altbestand geht auch raus

Frage von Sir: „Gehen auch die noch nicht abgesendeten, aber existierenden Webseiten raus?"
Antwort war: **nein** — der Versand nahm nur `approved` mit. Behoben:

### `review_queue.py`
- `promote_pending()` — hebt alle offenen (`pending`) Reviews auf `approved` (👎-Vetos =
  `REJECTED` bleiben ausgeschlossen).
- `latest_for_site(name, stadt)` — neuester Review zu einer Seite (case-/whitespace-robust),
  für den Abgleich mit bereits gebauten Seiten.

### `discord_bot.py`
- `enqueue_unsent_websites()` — Auto-Send-Abgleich: scannt `db_websites` nach Seiten, die
  **live** sind, **noch nicht versendet** (`email_sent==0`) und **review-ready**, aber KEINEN
  offenen Review haben (z.B. früher in die Vorschau-Mail gefallen, weil Discord offline war).
  Holt sie nachträglich in die Queue. Strikt ausgeschlossen: `SENT`, `REJECTED` und bereits
  eingereihte (`PENDING`/`APPROVED`).
- `prepare_queue_for_auto_send()` — bündelt Promote + Nachqueue.
- **`send_approved_now()` ruft `prepare_queue_for_auto_send()` als ersten Schritt auf** →
  der einzige Chokepoint (12-Uhr-Loop, Watchdog, manuelles `/api/discord/send-now`) nimmt so
  IMMER den kompletten Altbestand mit. Zusätzlich läuft die Aufbereitung einmalig bei Bot-Start
  (`on_ready`).

### Tests (jetzt 106/106 grün)
- `test_review_queue_promote_pending` (Veto bleibt außen vor)
- `test_review_queue_latest_for_site`
- `test_auto_send_versendet_altbestand_pending` (pending → wird versendet + als SENT markiert)
- End-to-End manuell verifiziert: gebaute/live/unsent Seite ohne Review wird nachgequeued und
  versendet; bereits versendete Seite wird übersprungen.

### Bewusste Grenze
Die alten Discord-Embeds der bereits geposteten `pending`-Reviews werden beim Promoten NICHT
neu gerendert (Status wird still auf `approved` gesetzt) — rein kosmetisch, der Versand stimmt.
Ist Discord komplett unkonfiguriert (kein Token), läuft der 12-Uhr-Watchdog nicht (er hängt am
`start()` des Bots); mit konfiguriertem Discord (aktueller Zustand) ist alles abgedeckt.

## Standardverhalten danach
Seite fertig makeovert → sofort `approved` in der Queue → **Versand automatisch um
`DISCORD_SEND_HOUR` (12:00)** an den echten Kunden, ganz ohne 👍. Discord postet weiterhin
jede Seite als Info-Embed (wenn verbunden); der Versand ist davon nun unabhängig.
Zurück zum manuellen Gate: `JARVIS_AUTO_SEND=0` in die `.env`.
