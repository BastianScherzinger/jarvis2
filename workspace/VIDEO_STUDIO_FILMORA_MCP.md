# Video-Studio-Tab (Filmora MCP) + TODO-Aufräumen + .env-Doku (2026-07-02)

## Auftrag (Sir)
1. Offene TODOs prüfen und abarbeiten.
2. Neuer Dashboard-Reiter „Video-Studio": Login zu „Filmora MCP", Chat unten, ein
   Prompt-Feld das lokal per KI verbessert wird, YouTube-Videos per Link bearbeiten.
3. `.env` auf fehlende Dokumentation prüfen.
4. Alles selbst umsetzen, mit Debugging verdrahtet, final pushen.

## Rechercheergebnis (kritisch für die Architektur)
Es gibt **keine dokumentierte, feste "Filmora-MCP"-REST-API**. Real existiert nur eine
viaSocket-Landingpage (`viasocket.com/mcp/filmora`) ohne technische Doku — sie sagt nur:
Login unter `app.mushroom.viasocket.com/login` liefert eine **persönliche MCP-URL**
("Get Your MCP URL for Free"). Keine dokumentierten Tool-Namen, kein OAuth (Auth steckt
in der URL selbst). Eine 7 Tage alte Projekt-Erinnerung bestätigt: ein fast identisches
Vorhaben wurde bewusst NICHT blind gebaut, mangels Zugangsdaten.

**Lösung:** Der Client spricht **Standard-MCP-JSON-RPC** (initialize → tools/list →
tools/call) gegen die vom Nutzer eingefügte URL und entdeckt Tool-Namen zur **Laufzeit**
statt sie zu erraten. Ist beim Bearbeiten kein eindeutig passendes Tool zu finden, wird
KEIN Job angelegt — der Nutzer wählt im Dashboard manuell aus einer Kandidatenliste.
Bis eine URL eingefügt ist, ist der Tab vollständig nutzbar (klare Anleitung, nichts crasht).

## Umsetzung

### `filmora_mcp.py` (neu) — generischer viaSocket-MCP-Client
Transport-Kern adaptiert aus `higgsfield_mcp.py` (`_parse`/`_headers`/`_ensure_session`/
`_result_payload`/`call_tool`), aber **ohne** dessen OAuth/PKCE-Teil.
- `set_url`/`get_status`/`clear`/`is_configured` — URL-Speicherung in
  `data/filmora_mcp_auth.json` (gitignored).
- `list_tools(force=False)` — `tools/list`-Discovery, 24h-Cache, behält bei Fehler den
  alten Cache (UI bleibt nutzbar).
- **Tool-Matching** (`resolve_edit_tool`/`resolve_manual`): Keyword-Scoring in Name+
  Beschreibung. Eindeutiger Sieger → automatisch. Mehrdeutig/kein Treffer →
  `tool_unclear` mit Kandidatenliste — Frontend zeigt einen Picker.
  `_build_arguments` mappt auf echte Schema-Feldnamen (Regex auf `url|link|source`
  bzw. `prompt|instruction|edit`), Fallback-Superset falls kein Schema.
- `run_edit_job` — ruft das Tool auf; liefert es direkt ein Ergebnis, ist der Job
  sofort fertig; liefert es eine Job-ID, wird ein per Keyword gefundenes Status-Tool
  gepollt (harte 600s-Obergrenze). `_finalize` versucht Download nach
  `workspace/media/videos/`, fällt bei jedem Fehler auf den externen Link zurück.

### `video_prompt.py` (neu) — lokale KI-Prompt-Verbesserung + Mini-Chat
Muster wie `custom_build.suggest()`: deterministischer Fallback zuerst, dann
`ask_ollama()`, nie werfend. `improve_instruction(raw)` für die Anweisungs-Verbesserung,
`chat_reply(message)` für den synchronen Hilfschat im Tab (kein SSE nötig, Ollama
antwortet in Sekunden; erkennt per Keyword, ob die Nachricht wie eine Bearbeitungs-
anweisung aussieht → „In Anweisungsfeld übernehmen"-Button im Frontend).

### `media_queue.py` — 2 punktuelle Ergänzungen
`filmora_edit` als neuer Cloud-Job-Kind (`_CLOUD_KINDS`) + `_worker()`-Zweig, der
`filmora_mcp.run_edit_job(...)` aufruft. Nutzt den bestehenden Job-Store/Polling-Fluss
1:1 weiter (inkl. dem bereits vorhandenen generischen `/api/media/job/<id>`).

### `app.py` — 7 neue Routen
`/api/video-studio/{status,connect,disconnect,tools,improve-prompt,submit-edit,chat}` —
alle nach Projekt-Konvention (Lazy-Import, `jsonify({"ok": False, ...})` bei Fehlern).

### Frontend — neuer Tab „Video-Studio"
- `templates/index.html`: Nav-Button, Panel mit Connect-Karte (Status-Badge, URL-Feld,
  Link zu viaSocket-Login), Edit-Formular (YouTube-Link, Instruktion, „Prompt
  verbessern" mit Vorher/Nachher, Ambiguitäts-Picker), Job-Status-Karte
  (`.job-card`-Stil), Debug-Panel, Chat unten (Struktur aus `claude-page` übernommen).
- `static/js/video_studio.js` (neu): `initVideoStudio`, `vsConnect`/`vsDisconnect`,
  `vsImprovePrompt`, `vsSubmitEdit` (inkl. Picker), Job-Polling nutzt das **bereits
  globale** `pollJob(jobId, 'vs')`/`_showJob()` — keine eigene Polling-Logik nötig.
  Chat: `vsChatSend`/`vsAppendBubble` (Muster `claude.js`, synchron statt SSE).
- `static/css/style.css`: neuer Abschnitt, maximale Wiederverwendung bestehender
  Klassen (`.job-card`, `.claude-chat`, `.claude-composer`, `.cb-suggest`, `.adform`/
  `.af-field`, `.start-btn`), nur wenige neue kleine Klassen (`.vs-badge`, `.vs-tool-chip`, …).

## Multi-Agent-Code-Review (3 parallele Finder-Agenten) — 6 Funde behoben

| # | Fund | Schwere | Fix |
|---|------|---------|-----|
| 1 | **XSS**: Tool-Name vom externen MCP-Server wurde per String-Interpolation in ein `onclick`-Attribut eingebettet (`\`-Escaping fehlte) | KRITISCH | Picker komplett auf DOM-Konstruktion + `addEventListener`-Closures umgestellt — keine String-in-JS-Injektion mehr möglich |
| 2 | Race Condition: `list_tools()`/`connect_test()` lasen/schrieben `data/filmora_mcp_auth.json` ohne Lock (nur `set_url` war gesichert) | Bestätigt | Read-Modify-Write jetzt unter `_lock`, Netzwerk-Call bewusst außerhalb (blockiert den Lock nicht) |
| 3 | `_finalize()` prüfte den HTTP-Status des Downloads nicht — eine abgelaufene Ergebnis-URL hätte eine HTML-Fehlerseite als `.mp4` gespeichert und „fertig" gemeldet | Bestätigt | Status-Check vor dem Speichern, Fehler → Fallback auf externen Link |
| 4 | Test `test_run_edit_job_synchronous_result` verließ sich auf einen ECHTEN (nur zufällig fehlschlagenden) Netzwerk-Call trotz „netzwerkfrei"-Anspruch | Plausibel | Deterministischer Fake-`httpx.Client` statt echtem Netzwerk |
| 5 | Kein Session-Caching: der 600s-Polling-Loop (5s-Takt) hätte bis zu ~120 volle `initialize`-Handshakes für EINEN Job gemacht — Rate-Limit-Risiko | Plausibel | `_get_session()` mit 5-Min-TTL-Cache, Invalidierung bei 401/403 |
| 6 | Magic Numbers (`2` Ambiguitäts-Marge, `8` Mindestlänge) | Stil (CLAUDE.md-Regel) | Als `_AMBIGUITY_MARGIN`/`_MIN_IMPROVED_LEN` benannt |

**Bewusst nicht verändert** (dokumentierte Architektur-Entscheidungen, im Review geprüft):
- `api_vs_submit_edit` löst das Tool synchron im Request aus (nicht im Worker) — Absicht
  laut Plan: Mehrdeutigkeit soll VOR dem Anlegen eines Jobs erkannt werden, nicht danach.
  Blockierungsdauer ist durch Timeouts begrenzt (≤30s bei kaltem Cache) und entspricht
  bestehenden synchronen Routen im Projekt (z.B. `custom_build.suggest()`, `ask_ollama`
  bis 60s).
- `filmora_edit` teilt sich den kleinen Cloud-Worker-Pool mit Higgsfield-Jobs und kann
  ihn bis zu 10 Min blockieren — entspricht dem bereits bestehenden Higgsfield-Video-
  Muster (`poll_timeout=360`), keine neue Charakteristik.
- `_parse`/`_headers`/`_ensure_session`/`_result_payload` sind bewusste Duplikate zu
  `higgsfield_mcp.py` (dessen OAuth-Kopplung eine echte Trennung nötig macht) — eine
  gemeinsame `mcp_transport.py`-Extraktion ist als Backlog-Idee vermerkt, kein Blocker.

## Teil A — Offene TODOs

Alle Punkte aus `CODE_AUDIT_2026-07-02.md` (Runden A–G) waren bereits abgeschlossen —
kein offener Code-Punkt. Verbleibend sind ausschließlich Handgriffe, die nur Sir selbst
tun kann (siehe Abschlussbericht im Chat): Gmail-2FA + App-Passwort, GitHub-Token-Scope
`delete_repo`, Railway-GitHub-App verbinden, 2.-PC-Update.

## Teil A — `.env.example`-Lücken geschlossen
37 aktive `.env`-Variablen waren undokumentiert. Ergänzt (nach Code-Verifikation, welche
davon tatsächlich noch fehlten — viele waren durch frühere Sessions bereits dokumentiert):
lokale Modell-Overrides (`JARVIS_LOCAL_MODEL`/`_IMAGE_MODEL`/`_VIDEO_MODEL`/
`_LOCAL_CONCURRENCY`), GitHub/Railway-Tokens, `GOOGLE_MAPS_API_KEY`,
`JARVIS_EMAIL_REDIRECT` (Sicherheitsumleitung), Session-Fenster
(`JARVIS_IMPROVE_UNTIL_HOUR`/`_SESSION_HOURS`/`_SESSIONS_PER_DAY`/`_NIGHTLY_DEEP`),
`JARVIS_FILMORA_MCP_URL`. `JARVIS_WVM_SHOP` wurde geprüft und ist bereits über den
bestehenden WVM-Block dokumentiert (in `offer_mail.py` verifiziert, kein Code-Fund
ergab einen fehlenden weiteren Verweis).

## Tests
23 neue Tests in `tests/test_filmora_mcp.py` (netzwerkfrei): URL-Roundtrip, Tool-Cache
(Hit/Fehlerresistenz), Matching (eindeutig/mehrdeutig/nicht-verbunden/manuell),
Argument-Schema-Mapping, Ergebnis-URL-Extraktion, Status-Check in `_finalize`,
Session-Caching, Prompt-Verbesserung + Chat (mit/ohne Ollama). **Gesamte Suite:
146/146 grün.** Flask-App importiert sauber, alle 7 neuen Routen registriert
(manuell verifiziert).

---

# Nachtrag (2026-07-02, später Durchlauf): .env-Vollständigkeit + Webseiten-Ordner-Umzug

## .env-Vollständigkeitsprüfung
Vollständiger Abgleich `.env` (aktive Werte) gegen `.env.example` (auch auskommentierte
Dokumentation zählt): **einzige echte Lücke war `JARVIS_WVM_SHOP`** (Referenz-Domain für
die Angebots-Mail, `offer_mail.py:81`) — ergänzt im WVM-Block. Alles andere bereits
korrekt dokumentiert. `JARVIS_TOOL_MODEL`/`JARVIS_BROWSER_HEADLESS` stehen zwar mit
Default-Wert in `.env.example`, fehlen aber in der echten `.env` — unkritisch, beide
haben passende Code-Defaults (kein Handlungsbedarf).

## Webseiten-Ordner-Konsolidierung (`website_builder.migrate_legacy_website_folders()`)

**Hintergrund:** `find_built_sites()` kannte bereits zwei Ablage-Formen: die alte flache
`Desktop/web_*`-Struktur (vor Einführung der Tagesordner) und die aktuelle
`Desktop/jarvis_websites/<Datum>/web_*`-Struktur. Neue Seiten landen **schon immer**
ausschließlich in Letzterer (`_unique_dir`/`_day_dir`, einziger Bau-Pfad im ganzen
Projekt — auch `custom_build.py` läuft über `website_builder.build()`). Auf einem
zweiten PC mit älterem Stand können aber noch Alt-Ordner lose auf dem Desktop liegen.

**Neue Funktion** (`website_builder.py`, direkt vor `find_built_sites`):
`migrate_legacy_website_folders()` — scannt `Desktop/web_*` (nur die oberste Ebene,
NICHT die bereits einsortierten `jarvis_websites/<Datum>/web_*`), verschiebt nur
Ordner, die zusätzlich zum Namen auch `content.json` ODER `manage.py` enthalten
(dieselbe Prüfung wie `find_built_sites` — verhindert, dass fremde Desktop-Ordner
angefasst werden), in `jarvis_websites/<Datum-aus-Ordner-mtime>/`. Kollisionen werden
wie bei `_unique_dir` durchnummeriert. Passende `db_websites`-Zeilen (`folder`-Spalte)
werden auf den neuen Pfad aktualisiert, damit das Dashboard weiter funktioniert.
Wirft nie, ein einzelner fehlgeschlagener Ordner bricht den Rest nicht ab, idempotent
(zweiter Lauf findet nichts mehr).

**Zwei Auslöser** (Redundanz-Muster wie beim Demo-Teardown „täglich + bei jedem Start"):
1. **Primär: `update.py`** — neuer Schritt nach der Abhängigkeitsprüfung, druckt eine
   Zusammenfassung (umgezogene Ordner, Fehler), bricht das Update nie ab.
2. **Sicherheitsnetz: `app._startup_cleanup()`** — läuft still beim App-Start, falls
   Sir die App ohne vorheriges `update.py` startet.

**Bewusst NICHT live ausgeführt** in dieser Session (nur gegen `tmp_path` getestet) —
die Funktion verschiebt echte Dateien auf dem Desktop; sie soll laut Auftrag erst beim
nächsten `update.py`/Start auf dem betroffenen (zweiten) PC greifen, nicht sofort hier.

### Tests
3 neue Tests: echter Umzug + Idempotenz, Sicherheitsnetz gegen fremde/unvollständige
Ordner (`Urlaubsfotos`, `web_*` ohne Inhalt bleiben unberührt), DB-Pfad-Aktualisierung.
**Gesamt-Suite: 149/149 grün** (148 + 1 vorbestehend flakiger Test, der isoliert immer
grün ist — bestätigt schon vor diesem Durchlauf vorhanden, siehe Git-Historie).
