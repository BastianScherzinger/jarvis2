"""
JARVIS LeadHunter — E-Mail-Versand (Auto-Mail-Gerüst).

SICHERHEITS-SCHALTER: Echter Versand passiert NUR, wenn JARVIS_EMAIL_ENABLED=true
in der .env steht. Ohne Flag ist send_email() ein Trockenlauf (status='deaktiviert').
So kann das System komplett vorbereitet werden, ohne versehentlich Mails zu senden.

Konfiguration (.env):
  JARVIS_EMAIL_ENABLED=false        # true = echter Versand scharf
  SMTP_HOST=smtp.example.com
  SMTP_PORT=587                     # 587 = STARTTLS | 465 = SSL
  SMTP_USER=postfach@example.com
  SMTP_PASS=...                     # GEHEIM — nie committen, wird nie geloggt
  SMTP_FROM=Mein Name <ich@example.com>
  JARVIS_EMAIL_RATE=20              # max. Mails pro Stunde (Drossel)
  JARVIS_EMAIL_FOOTER=...           # Impressum/Signatur — Pflicht für seriöse B2B-Akquise
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage

import logger

_lock     = threading.Lock()
_sent_ts: list[float] = []   # Zeitstempel der letzten Sendungen (für das Stundenlimit)


def is_enabled() -> bool:
    """True nur wenn der scharfe Versand explizit eingeschaltet ist."""
    return os.environ.get("JARVIS_EMAIL_ENABLED", "false").strip().lower() == "true"


def is_configured() -> bool:
    """Sind alle SMTP-Pflichtfelder gesetzt?"""
    return all(os.environ.get(k) for k in
               ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "SMTP_FROM"))


def _rate_ok() -> bool:
    """Stundenlimit gegen versehentliches Massen-Senden — NUR prüfen (Slot wird erst nach
    erfolgreichem Versand via _note_sent verbraucht, damit Fehlschläge kein Budget kosten)."""
    try:
        limit = int(os.environ.get("JARVIS_EMAIL_RATE", "20") or 20)
    except Exception:
        limit = 20
    now = time.time()
    with _lock:
        _sent_ts[:] = [t for t in _sent_ts if now - t < 3600]
        return len(_sent_ts) < limit


def _note_sent() -> None:
    """Verbucht eine ERFOLGREICH gesendete Mail fürs Stundenlimit."""
    with _lock:
        _sent_ts.append(time.time())


def status() -> dict:
    """Für das Dashboard: ist der Versand bereit/scharf?"""
    return {
        "enabled":    is_enabled(),
        "configured": is_configured(),
        "rate":       int(os.environ.get("JARVIS_EMAIL_RATE", "20") or 20),
        "from":       os.environ.get("SMTP_FROM", ""),
        "redirect":   os.environ.get("JARVIS_EMAIL_REDIRECT", "").strip(),
    }


def send_email(to: str, betreff: str, text: str, *, html: str | None = None,
               bypass_redirect: bool = False) -> dict:
    """
    Versendet eine E-Mail. Gibt {ok, status, fehler} zurück.
    Kein echter Versand, wenn JARVIS_EMAIL_ENABLED != true (Trockenlauf).

    bypass_redirect=True: ignoriert JARVIS_EMAIL_REDIRECT und sendet an die echte
    Adresse — für bewusste, vom Nutzer ausgelöste Sendungen (z.B. Angebot an Kunde).
    """
    to = (to or "").strip()
    # SICHERHEITS-UMLEITUNG (Testmodus): ist JARVIS_EMAIL_REDIRECT gesetzt, geht
    # JEDE Mail an diese Adresse — egal an wen sie eigentlich gerichtet war. So
    # landet im Testbetrieb nichts versehentlich bei echten Betrieben. Den
    # Original-Empfänger vermerken wir im Betreff. bypass_redirect hebt das auf.
    redirect = os.environ.get("JARVIS_EMAIL_REDIRECT", "").strip()
    if redirect and "@" in redirect and not bypass_redirect:
        if to and to.lower() != redirect.lower():
            betreff = f"[Test → {to}] {betreff or ''}"
        to = redirect
    if "@" not in to:
        return {"ok": False, "status": "fehler", "fehler": "keine gültige Empfänger-Adresse"}
    # ABMELDUNG/OPT-OUT respektieren (UWG/DSGVO) — gilt auch für bypass_redirect, also für
    # bewusste Kunden-Sendungen. Wer sich abgemeldet hat, bekommt nie wieder eine Mail.
    try:
        import email_suppress
        if email_suppress.is_suppressed(to):
            logger.info("Mailer", f"Versand unterdrückt (Abmeldung aktiv): {to}")
            return {"ok": False, "status": "opt_out", "fehler": "Empfänger hat sich abgemeldet"}
    except Exception:
        pass
    if not is_enabled():
        return {"ok": False, "status": "deaktiviert",
                "fehler": "JARVIS_EMAIL_ENABLED=false — Trockenlauf, nichts gesendet"}
    if not is_configured():
        return {"ok": False, "status": "fehler", "fehler": "SMTP-Konfiguration unvollständig (.env)"}
    if not _rate_ok():
        return {"ok": False, "status": "fehler", "fehler": "Stundenlimit erreicht (JARVIS_EMAIL_RATE)"}

    footer = os.environ.get("JARVIS_EMAIL_FOOTER", "").strip()
    body   = text + (("\n\n" + footer) if footer else "")

    msg = EmailMessage()
    msg["From"]    = os.environ["SMTP_FROM"]
    msg["To"]      = to
    msg["Subject"] = betreff or "(kein Betreff)"
    # List-Unsubscribe (RFC 2369/8058): erlaubt ein-Klick-Abmeldung in seriösen Mail-Clients
    # und verbessert die Zustellbarkeit. mailto funktioniert IMMER (ohne öffentlichen Webhost);
    # die URL zusätzlich, wenn JARVIS_PUBLIC_URL gesetzt ist.
    try:
        unsub_targets = []
        base = (os.environ.get("JARVIS_PUBLIC_URL") or "").strip().rstrip("/")
        mailto = (os.environ.get("JARVIS_UNSUB_MAILTO") or os.environ.get("SMTP_USER") or "").strip()
        if base:
            import email_suppress
            import urllib.parse
            q = urllib.parse.urlencode({"e": to, "t": email_suppress.token_for(to)})
            unsub_targets.append(f"<{base}/abmelden?{q}>")
        if mailto and "@" in mailto:
            unsub_targets.append(f"<mailto:{mailto}?subject=unsubscribe>")
        if unsub_targets:
            msg["List-Unsubscribe"] = ", ".join(unsub_targets)
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    except Exception:
        pass
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587") or 587)
    user = os.environ["SMTP_USER"]
    pw   = os.environ["SMTP_PASS"]
    ctx  = ssl.create_default_context()

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=30, context=ctx) as s:
                s.login(user, pw)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.ehlo(); s.starttls(context=ctx); s.ehlo()
                s.login(user, pw)
                s.send_message(msg)
        _note_sent()                               # Slot erst jetzt (nach Erfolg) verbrauchen
        logger.success("Mailer", f"Mail gesendet an {to}")
        return {"ok": True, "status": "gesendet", "fehler": ""}
    except Exception as e:
        # Passwort/Postfach NIE loggen — nur Fehlertyp
        logger.error("Mailer", f"Versand fehlgeschlagen: {type(e).__name__}")
        return {"ok": False, "status": "fehler", "fehler": f"{type(e).__name__}"}


def send_to_lead(lead: dict) -> dict:
    """
    Baut die Mail aus dem gespeicherten Entwurf (oder generiert via outreach) und
    versendet an die Lead-E-Mail. Respektiert Opt-out. Personalisiert die Anrede,
    wenn ein Ansprechpartner bekannt ist.
    """
    if int(lead.get("email_opt_out") or 0):
        return {"ok": False, "status": "opt_out", "fehler": "Lead hat Opt-out gesetzt"}

    to = (lead.get("email_adresse") or "").strip()
    if "@" not in to:
        return {"ok": False, "status": "fehler", "fehler": "keine E-Mail-Adresse vorhanden"}

    betreff = text = ""
    try:
        entwurf = json.loads(lead.get("email_entwurf") or "{}")
        betreff = (entwurf.get("betreff") or "").strip()
        text    = (entwurf.get("text") or "").strip()
    except Exception:
        pass

    if not text:                       # Fallback: on-demand über outreach (Ollama)
        try:
            from agents import outreach
            # persist=False: lead ist eine DB2-Zeile, deren id NICHT zu db.py gehört.
            res     = outreach.generate_email(lead, persist=False)
            betreff = (res.get("betreff") or betreff).strip()
            text    = (res.get("text") or "").strip()
        except Exception:
            pass

    if not text:
        return {"ok": False, "status": "fehler", "fehler": "kein E-Mail-Text vorhanden"}

    # Persönliche Anrede, wenn Ansprechpartner bekannt und noch keine Anrede im Text
    ap = (lead.get("ansprechpartner") or "").strip()
    if ap and not text.lower().startswith(("sehr geehrte", "hallo", "guten tag", "liebe")):
        text = f"Sehr geehrte/r {ap},\n\n{text}"

    return send_email(to, betreff, text)
