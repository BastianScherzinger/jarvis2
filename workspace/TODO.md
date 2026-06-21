# JARVIS — TODO / Offene Punkte (Stand 22.06.2026)

## Für Sir (manuell, nicht im Code lösbar)
- [ ] **Kunden-PC aktualisieren:** dort `python update.py` → `python start.py`.
      DB migriert automatisch; Cross-PC-Sync + Globus laufen sofort.
- [ ] **E-Mail am Kunden-PC:** dessen `.env` braucht dieselben `SMTP_USER`/`SMTP_PASS`
      (enigmabible1@gmail.com + App-Passwort) — `.env` wird nicht per Git geteilt.
- [ ] **Echter Kundenversand:** wenn Mails an echte Betriebe gehen sollen, in der `.env`
      die Zeile `JARVIS_EMAIL_REDIRECT=…` leeren/entfernen (aktuell Test → Bastian).
- [ ] **GitHub-Repo-Löschung:** funktioniert nur, wenn das `GITHUB_TOKEN` den Scope
      `delete_repo` hat (sonst bleibt das Repo, Rest wird gelöscht).
- [ ] **Railway-GitHub-App** einmalig verbinden (railway.app → GitHub), falls ein Deploy
      trotz gültiger Tokens nicht baut. Diagnose: im Claude-Reiter „der Deploy klappt nicht".

## Bekannte Einschränkungen / später
- [ ] **Higgsfield-Bildpfad** ist nach Doku gebaut, aber ungetestet (kein Key gesetzt).
- [ ] **Globus-Koordinaten:** Stadt-Lookup deckt ~75 Städte ab; unbekannte landen am
      Bundesland-Zentrum (mit Jitter). Bei Bedarf Liste in `globe.js` erweitern.
- [ ] **„An Kunde senden" verschickt echte Werbe-Mails** — bewusst hinter Bestätigung.
      Rechtliches (Impressum/Opt-out) vor breitem Echtversand prüfen.
- [ ] **window._gb** ist als Debug-Global in `globe.js` belassen (harmlos) — bei Bedarf
      entfernen.

## Ideen (nicht beauftragt)
- [ ] Bestehende Webseiten beim ersten Sync rückwirkend mit `kontakt_email` füllen
      (aktuell nur bei Neubau gesetzt).
- [ ] Globus: Klick auf Marker → Stadt-Detail/Filter; Heatmap-Modus.
