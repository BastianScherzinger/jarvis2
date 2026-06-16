# Tutorial — Auto-E-Mail-Versand scharf schalten

> Das System ist jetzt **„auto-email-send-ready"**: Versand-Modul (`mailer.py`),
> Queue-/Status-Felder, Opt-out, Rate-Limit, Versand-Route und ein „E-Mail senden"-Button
> im Lead-Modal stehen. **Standardmäßig wird nichts gesendet** (Trockenlauf), bis du den
> Sicherheits-Schalter umlegst. Diese Anleitung führt Schritt für Schritt zum scharfen Auto-Versand.

---

## Voraussetzungen (einmalig)

### 1. Supabase-Schema aktualisieren
Im Supabase SQL-Editor die Migration ausführen:
```
workspace/sql/2026-06_neue_felder.sql
```
Damit kennt die Cloud die neuen Felder (`sicherheit`, `erwartungswert_euro`, `foto_urls`,
`email_alle`, `ansprechpartner`, `email_status`, `email_opt_out`). Sonst lehnt CloudSync den
Upsert mit HTTP 400 ab (sichtbar im Log unter „CloudSync").

### 2. SMTP-Zugang in `.env` eintragen
Trage einen echten Postausgangsserver ein (z. B. der deines Mail-Providers / einer
Transaktions-Mail wie Brevo, Mailjet, Postmark). **`.env` niemals committen.**
```bash
SMTP_HOST=smtp.dein-provider.de
SMTP_PORT=587                      # 587 = STARTTLS (Standard) | 465 = SSL
SMTP_USER=postfach@deine-domain.de
SMTP_PASS=DEIN_APP_PASSWORT        # GEHEIM — wird nie geloggt
SMTP_FROM=Dein Name <kontakt@deine-domain.de>
JARVIS_EMAIL_RATE=20              # max. Mails pro Stunde (Drossel gegen Unfälle)
JARVIS_EMAIL_FOOTER=Dein Name · Deine Firma · Anschrift · Abmeldung jederzeit per Antwort
```
> Tipp Gmail/Google: App-Passwort erstellen (nicht das normale Passwort), `SMTP_HOST=smtp.gmail.com`, Port 587.

### 3. Bereitschaft prüfen (noch ohne Versand)
Server starten (`python start.py`) und im Browser/per curl checken:
```
GET http://localhost:5000/api/email/status
→ {"enabled": false, "configured": true, "rate": 20, "from": "..."}
```
`configured:true` heißt: SMTP-Daten vollständig. `enabled:false` heißt: noch Trockenlauf — gut so.

---

## Manueller Test (ein Lead)

1. Dashboard → Tab **Rangliste** → Lead anklicken → Modal öffnet sich.
2. Hat der Lead eine E-Mail, erscheint **„✉ E-Mail an Lead senden"**.
3. Klick → solange `JARVIS_EMAIL_ENABLED=false`: Meldung *„Trockenlauf — nichts gesendet"*.
   Das bestätigt, dass der Pfad funktioniert, ohne real zu senden.

### Scharf schalten
In `.env`:
```bash
JARVIS_EMAIL_ENABLED=true
```
Server neu starten. Jetzt sendet der Button **echt** — teste zuerst an deine **eigene** Adresse
(einen Lead mit deiner Mail anlegen oder `email_adresse` testweise setzen). Nach Erfolg wechselt
`email_status` auf `gesendet` (wird auch in die Cloud gespiegelt und ist auf allen PCs sichtbar).

---

## Auto-Versand einbauen (der letzte Schritt – bewusst manuell zu aktivieren)

Alles Nötige ist vorhanden; der eigentliche Auto-Loop wird absichtlich **nicht** von selbst aktiv.
So baust du ihn ein (z. B. als neue Datei `auto_mailer.py`, gestartet aus `app.py` analog zu `cloud_sync.start()`):

```python
# auto_mailer.py — sendet gedrosselt an die SICHERSTEN Leads. Default: AUS.
import os, time, threading
import db_evaluated, mailer, logger

def _loop():
    while True:
        if mailer.is_enabled() and os.environ.get("JARVIS_AUTO_MAIL", "false").lower() == "true":
            schwelle = int(os.environ.get("JARVIS_AUTO_MAIL_MIN_SICHERHEIT", "55"))
            # Beste-zuerst: höchster Erwartungswert, nur erreichbar + noch nicht gesendet
            for lead in db_evaluated.get_all(limit=50, sort="erwartungswert"):
                if int(lead.get("email_opt_out") or 0):            continue
                if (lead.get("email_status") or "entwurf") != "entwurf": continue
                if not int(lead.get("email_vorhanden") or 0):      continue
                if int(lead.get("sicherheit") or 0) < schwelle:    continue
                res = mailer.send_to_lead(lead)
                db_evaluated.set_email_status(lead["id"], res.get("status","fehler"), res.get("fehler",""))
                logger.info("AutoMailer", f"{lead.get('name')}: {res.get('status')}")
                time.sleep(5)   # zusätzliche Drossel pro Mail
        time.sleep(120)

def start():
    threading.Thread(target=_loop, name="AutoMailer", daemon=True).start()
```
In `app.py` neben `cloud_sync.start()`:
```python
import auto_mailer
auto_mailer.start()
```
Aktivierung (zwei Schalter, beide nötig):
```bash
JARVIS_EMAIL_ENABLED=true
JARVIS_AUTO_MAIL=true
JARVIS_AUTO_MAIL_MIN_SICHERHEIT=55
```

---

## Sicherheit & Recht (B2B-Kaltakquise per E-Mail)

- **Rechtslage beachten:** E-Mail-Werbung ohne Einwilligung ist in DE i. d. R. nur unter engen
  Voraussetzungen zulässig (§ 7 UWG). Sende nur an Geschäftsadressen mit mutmaßlichem Interesse,
  immer mit Impressum/Absender (`JARVIS_EMAIL_FOOTER`) und einfacher Abmeldemöglichkeit.
- **Opt-out:** Button/Route `POST /api/lead/<id>/opt-out` setzt `email_opt_out=1` → kein Versand mehr.
- **Drossel:** `JARVIS_EMAIL_RATE` begrenzt Mails/Stunde. Niedrig starten.
- **Geheimnisse:** `SMTP_PASS` steht nur in `.env` (gitignored) und wird nie geloggt.
- **Zuerst Trockenlauf,** dann an die eigene Adresse, dann erst echte Leads.

---

## Statusfelder (DB2 `evaluated_leads`)

| Feld | Bedeutung |
|------|-----------|
| `email_status` | `entwurf` → `gesendet` / `fehler` / `opt_out` / `deaktiviert` |
| `email_gesendet_am` | Zeitstempel des Versands |
| `email_fehler` | Fehlertyp (kein Passwort, falscher Host …) |
| `email_opt_out` | 1 = nie wieder anschreiben |

Alle Felder synchronisieren über Supabase auf alle PCs + die Railway-Seite.
