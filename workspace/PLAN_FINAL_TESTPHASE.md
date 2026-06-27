# PLAN — Finale Testphase (großes Update)

Auftrag von Sir, übersetzt in konkrete Bausteine.

## 1. Bau-Sessions: 3 × 5 = 15/Tag (statt 2 × 5)
- `auto_builder`: `JARVIS_SESSIONS_PER_DAY` (Default **3**), pro Session weiterhin
  `JARVIS_DAILY_SITES` (=5). Session-Fenster über `JARVIS_SESSION_HOURS`
  (Default `0,12,18`). Session-Key `{datum}_s{n}`.
- „Limit voll → in nächster Session wieder 5" ergibt 10–20 Seiten/Tag.
- Abwärtskompatibel: alte `_am`/`_pm`-Keys werden weiter eingelesen/gruppiert.

## 2. Eigene-Marke-Builds zählen mit
- `custom_build._watch_build` meldet die fertige Seite an
  `auto_builder.record_custom(...)` → erscheint in Tages-Historie + Mittags-Report
  und zählt zum Session-Kontingent (kein Doppel-Overload).

## 3. Mittags-Report (12 Uhr) — einmalig + schön + „verschickt"
- `discord_bot`: Tages-Latch (`data/noon_state.json`) → Report nur **einmal pro Tag**
  (überlebt Neustart um 12 Uhr).
- Schönes Embed: pro Seite `✅ [Name](Live-Link) → kunde@mail` — man sieht direkt,
  was verschickt wurde, mit Name + Link.
- Verabschiedungs-/Mittagsnachricht ehrlich: trennt „makeovert" von „freigegeben/
  versendet" und zeigt offene Freigaben.

## 4. Bessere E-Mail-Findung (Anfang + Ende)
- `contact_finder`: zusätzlich Kontaktseiten (`/impressum`, `/kontakt`,
  `/datenschutz`) scannen, `mailto:` auslesen, beste Adresse wählen
  (info@/kontakt@ bevorzugt, `noreply` meiden). Letzter Ausweg:
  `info@<domain>` als markierte Schätzung. Greift bei Lead-Findung **und** vor Versand.

## 5. Hochskalieren bereit (lokale KI + Seitenzahl)
- Hardware-basierte Empfehlung (`auto_builder.scaling_info()` über `system_profile`):
  schlägt Sessions/Seiten + lokale Parallelität vor. Knöpfe:
  `JARVIS_SESSIONS_PER_DAY`, `JARVIS_DAILY_SITES`, `JARVIS_SESSION_HOURS`,
  `JARVIS_LOCAL_CONCURRENCY`. Start-Log nennt die aktive Konfiguration.

## 6. Tests + Doku
- Tests für Session-Logik, Tages-Gruppierung, contact_finder-Fallback,
  Noon-Latch. CLAUDE.md/Env-Doku ergänzt. Volllauf `pytest`. Dann Commit + Push.
