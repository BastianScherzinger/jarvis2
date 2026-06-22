# Discord-Freigabe-Bot + Mail-/Restarbeiten (23.06.2026)

Ein Voting-Gate zwischen "Webseite fertig gebaut" und "E-Mail geht an echten Kunden".
Niemand bekommt ungeprüft eine Mail — erst nach **2× Daumen hoch** in Discord.

## 1. Ablauf (End-to-End)
```
Auto-Builder baut + verbessert Seite
        │  (Discord-Bot aktiv?)
        ├─ JA  → review_queue.add(...) → discord_bot postet Embed mit Live-Link
        │         + Buttons 👍 / 👎  (Status: 🕓 Abstimmung läuft)
        │         • 2× 👍 ohne 👎  → ✅ Freigegeben
        │         • irgendein 👎    → ❌ Abgelehnt (Veto, kein Versand)
        │         • täglich 12 Uhr → alle ✅ gehen an die ECHTE Kundenadresse
        └─ NEIN → alter Weg: Vorschau-Mail an Bastian (kein echter Versand)
```

## 2. Neue/geänderte Dateien
| Datei | Zweck |
|-------|-------|
| `review_queue.py` (neu) | Persistente Freigabe-Warteschlange `data/reviews.json`. Voting-Logik (Schwelle, Veto), `approved_unsent()`, `mark_sent()`. Thread-sicher, Standardbibliothek. |
| `discord_bot.py` (neu) | discord.py-Bot in eigenem Thread/Event-Loop. Persistente Buttons (`DynamicItem` → überleben Neustart). 12-Uhr-Scheduler (`tasks.loop`). **Import-sicher**: ohne Library/Token = No-op. `send_approved_now()` für Sofort-Versand. |
| `auto_builder.py` | `_build_and_email` → postet bei aktivem Bot zur Discord-Freigabe statt sofort zu mailen; sonst Fallback (Bastian). Tages-Historie merkt `review`-Flag. |
| `offer_mail.py` | **Bessere, variierende Betreffzeilen** (`_subject`, deterministisch pro Betrieb, ohne Spam-Trigger). Preis 350 € steht im Body, nicht im Betreff. |
| `app.py` | Bot-Start beim Boot (falls konfiguriert) + Routen `/api/discord/status`, `/api/discord/send-now`, `/api/reviews`. |
| `mcp_bridge.py` (neu) | **MCP-Brücke für lokale KIs** (Plan PLAN_MCP_LOCAL_AI.md umgesetzt, P0–P2). Ollama-Tool-Calling über SiteTools + optional echte MCP-Server. Render-Gate + Snapshot/Rollback. Mode `JARVIS_NIGHTLY_DEEP=mcp`. Import-sicher (ohne `ollama` = Fallback auf local_coder). |
| `media_engine.py` | Higgsfield-Auth robuster: liest `HIGGSFIELD_ID` separat; Regexes auf Zeilenanfang verankert (ignorieren `.env`-Kommentare). |
| `static/js/globe.js` | Erd-Texturen **anisotrop geschärft** (Kontinente/Standorte klarer), höhere Sphere-Auflösung. Echter **GLB-Hook**: lädt eine Erd-GLB aus `window.JARVIS_EARTH_GLB` / `<meta name="earth-glb">` und überlagert die Textur-Erde. |
| `.env` | Higgsfield-Key als kombiniertes `ID:SECRET`; kaputte Umlaut-Kommentare bereinigt; Discord- + Nightly-Variablen ergänzt. |

## 3. Setup (einmalig, durch Sir)
1. **Bot anlegen:** https://discord.com/developers/applications → *New Application* → Tab *Bot* → Token kopieren.
2. **Einladen:** Tab *OAuth2 → URL Generator* → Scope `bot`, Rechte *Send Messages* + *Embed Links* → Link öffnen, Server wählen.
3. **Kanal-ID:** Discord → Einstellungen → *Erweitert* → Entwicklermodus an → Rechtsklick auf den Kanal → *ID kopieren*.
4. **.env füllen:**
   ```
   DISCORD_BOT_TOKEN=...        # aus Schritt 1
   DISCORD_CHANNEL_ID=...       # aus Schritt 3
   DISCORD_APPROVALS_NEEDED=2   # so viele 👍 nötig
   DISCORD_OWNER_IDS=           # optional: nur diese User-IDs dürfen stimmen
   DISCORD_SEND_HOUR=12         # Versand-Uhrzeit
   ```
5. `python start.py` → der Bot meldet sich im Log ("Bot online als …").

Ohne diese Werte läuft alles wie bisher (Vorschau an Bastian) — nichts bricht.

## 4. Wichtig: echter Kundenversand
- Der 12-Uhr-Versand der freigegebenen Seiten umgeht **bewusst** `JARVIS_EMAIL_REDIRECT`
  (das 2-Personen-Voting IST die Sicherung) und geht an die echte `kontakt_email`.
- Fehlt eine Adresse, sucht der Versand sie via `contact_finder` nach; klappt das nicht,
  wird die Seite übersprungen (Status ⏭️) und im Kanal gemeldet — keine Blind-Sendung.
- `SMTP_USER`/`SMTP_PASS` müssen am sendenden PC gesetzt sein (enigmabible1@gmail.com).

## 5. Tests / QA
- 6 neue Tests (Voting-Schwelle, Veto, Doppelstimme, Owner-Whitelist, Bot-Import-Safe,
  MCP-Schema, Betreff-Variation) → **77 Tests grün**.
- `smoke_audit.py` 51/51, `qa_security.py`: Compile OK, 0 HIGH/MEDIUM/LOW.
- `data/reviews.json` ist gitignored (enthält Kundenadressen) — wird nie committet.
