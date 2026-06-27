# JARVIS LeadHunter — Projektabschluss & Betriebshandbuch

> Stand 27.06.2026 — finale Testphase abgeschlossen. Diese Datei ist die Übergabe:
> wie man das System einfach laufen lässt, was automatisch passiert und was (nur Env)
> manuell bleibt.

---

## 1. Starten

```powershell
python start.py          # install.py (git pull, pip, Checks) → app.py (Flask :5000)
```

Dashboard: http://localhost:5000 · Server-/Dauerbetrieb: `python serve.py` (waitress).

Beim Start laufen automatisch an:
- **Auto-Builder** (wenn vorher aktiv → setzt fort; sonst per Dashboard „Start").
- **Live-Watcher / Heal-Mode** (immer): prüft alle ~120 s jede Seite per HTTP, setzt das
  live-Flag ehrlich und deployt kaputte lokale Seiten automatisch neu (eine nach der anderen,
  600 s Cooldown). **Redeploy und Makeover schließen sich über denselben Lock aus** → keine
  Git-Kollision; ein Deploy während eines Makeovers wird sauber verschoben und später erneut
  versucht.
- **Discord-Bot** (wenn Token/Kanal gesetzt): Freigabe-Voting + 12-Uhr-Versand.
- **Demo-Teardown**: nicht verkaufte Demos nach `JARVIS_DEMO_TEARDOWN_DAYS` (7) ab.

Die **Home-Seite** zeigt jetzt alles auf einen Blick: Testphasen-Banner mit Reifegrad-Balken
und „Fortschritt aktualisieren"-Button, ein Fähigkeits-Grid („Was jetzt alles gebaut ist",
mit Icons), die Live-Pipeline-Grafik und den 7-Schritt-Workflow mit Status.

---

## 2. Was automatisch passiert (Tagesrhythmus)

1. **3 Bau-Sessions/Tag** (Fenster `0,12,18`), je **5 Seiten** → **15/Tag** (10–20 bei
   Limit-Erschöpfung). Eigene-Marke-Seiten zählen mit.
2. Pro Lead: bester Lead ohne Website → **bauen → 7-Stufen-Makeover → deployen → live**.
   Kontakt-E-Mail wird schon **beim Bau** aktiv gesucht (Impressum/Kontakt/mailto,
   info@/kontakt@ bevorzugt; Domain-Schätzung als letzter Ausweg).
3. **Discord-Freigabe**: fertige Seite wird gepostet → **1× 👍** gibt frei, **1× 👎** = Veto.
4. **12 Uhr**: alle freigegebenen Seiten gehen an die **echten Kunden**; ein **einmaliger,
   schöner Report** im Discord listet pro Seite Name + Live-Link + „verschickt an".
5. Danach: bestehende Seiten weiter verbessern, bis alles auf 7/7 ist → ehrliche
   Verabschiedung (trennt „makeovert" von „versendet/wartet auf Freigabe").

---

## 3. Die Angebotsmail (seriös, individuell)

Junger Entwickler der Firma **WVM-IT** baut eine fertige, **kostenlose** Seite. Die Mail
betont jetzt klar:
- **Alles selbst von Hand gebaut** — Design, Farben und Bilder eigens erstellt
  (kein Baukasten, keine Vorlage, keine Stockfotos).
- **Lebendig & modern** — auf Wunsch hochwertige, dezente **Animationen**.
- **Jederzeit erweiterbar und voll anpassbar** — Texte, Farben, Bilder, Funktionen, Domain.
- **Laufende Betreuung** — Pflege, technische Wartung, Änderungen; fester Ansprechpartner.
- Referenzen auf pystore.de, Abrechnung über WVM-IT, rechtssicherer Footer
  (Impressum + Ein-Klick-Abmeldung).

---

## 4. Stellschrauben (.env)

| Variable | Default | Wirkung |
|---|---|---|
| `JARVIS_DAILY_SITES` | 5 | Seiten **pro Session** |
| `JARVIS_SESSIONS_PER_DAY` | 3 | Bau-Sessions/Tag → 3×5 = 15 |
| `JARVIS_SESSION_HOURS` | 0,12,18 | Startstunden der Sessions |
| `JARVIS_LOCAL_CONCURRENCY` | 0 | lokale-KI-Parallelität (0 = aus Hardware) |
| `DISCORD_SEND_HOUR` | 12 | Uhrzeit des Kundenversands |
| `DISCORD_APPROVALS_NEEDED` | 1 | 👍 nötig für Freigabe |
| `JARVIS_DEMO_TEARDOWN_DAYS` | 7 | Abbau nicht verkaufter Demos |

`GET /api/auto-build/scaling` zeigt aktiv vs. hardware-empfohlen (Hochskalieren).

---

## 5. Nur noch manuell (kein Code — einmalige Env-Konfiguration)

Diese Punkte kann nur Sir setzen; danach läuft alles autonom:

- [ ] **Echter Kundenversand:** `JARVIS_EMAIL_REDIRECT` in der `.env` leeren (sonst
      Test → Bastian). Versand ist sonst scharf.
- [ ] **SMTP scharf:** `JARVIS_EMAIL_ENABLED=true` + `SMTP_USER`/`SMTP_PASS`
      (Gmail-App-Passwort) am jeweiligen PC.
- [ ] **Öffentliche URL:** `JARVIS_PUBLIC_URL` für den Ein-Klick-Abmeldelink.
- [ ] **2. PC:** `python update.py` → `python start.py`; gleiche `.env`-Secrets
      (wird nicht über Git geteilt).
- [ ] **GitHub `delete_repo`-Scope** (nur falls Repos automatisch gelöscht werden sollen)
      und einmalig **Railway↔GitHub** verbinden (railway.app → GitHub).

---

## 6. Qualität / Verifikation

- `python -m pytest tests/test_core.py -q` → **101 Tests grün**.
- compile-all über alle Module → OK.
- `GET /api/qa` → compile + Security-Scan + Dependencies.

---

## 7. Offene Ideen (nicht beauftragt, kein Blocker)

- Kontakt-Finder auch im Lead-Reiter (Anreicherung ohne Bau).
- Globus: Marker-Klick → Stadt-Detail/Heatmap.
- Globus-Texturen für Offline-Betrieb lokal bündeln.

**Fazit:** Das System ist betriebsbereit. Nach Setzen der Env-Secrets (Abschnitt 5)
einfach `python start.py` und im Dashboard „Auto-Builder Start" — der Rest läuft autonom.
