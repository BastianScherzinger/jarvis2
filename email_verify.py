"""
E-Mail-Zustellbarkeits-Prüfung (DNS/MX) — verhindert Bounces an tote Domains.

Der Scraper zieht E-Mails rein syntaktisch per Regex aus HTML (web_analyst._real_emails).
Eine syntaktisch gültige Adresse (info@firma-xy.de) kann trotzdem unzustellbar sein, wenn
die Domain gar nicht (mehr) existiert oder keinen Mailserver hat — jede Mail dorthin bounct
zurück ins eigene Postfach (genau das Symptom, das Sir gemeldet hat). Diese Prüfung schlägt
VOR dem Versand fehl, statt den SMTP-Bounce zu riskieren.

Design — bewusst best-effort mit DREI Zuständen (nie den ganzen Evaluator/Versand crashen):
  True  = Domain kann Mail empfangen (MX-Record ODER wenigstens A/AAAA vorhanden; RFC 5321
          §5.1: fehlt der MX, gilt der A-Record als impliziter Mailserver).
  False = Domain existiert definitiv nicht / hat keine verwertbaren Records (NXDOMAIN,
          HOST_NOT_FOUND, NO_DATA) → Mail würde sicher bouncen → NICHT senden, als
          "keine (zustellbare) E-Mail" werten.
  None  = unklar (DNS-Server nicht erreichbar, Timeout, temporärer Fehler) → NIEMALS
          blockieren, im Zweifel senden. Ein DNS-Ausfall darf weder die Pipeline lahmlegen
          noch gute Leads fälschlich verwerfen.

dnspython (dns.resolver) liefert echte MX-Records und wird bevorzugt, ist aber KEINE
Pflicht-Abhängigkeit: fehlt das Paket, fällt die Prüfung auf socket.getaddrinfo (A-Record)
zurück. Das erkennt den häufigsten realen Fall — die Domain existiert überhaupt nicht mehr —
zuverlässig, ganz ohne neue Abhängigkeit.

Bewusst NICHT geprüft: ob das konkrete Postfach (der local-part) existiert. Das ginge nur
per SMTP-RCPT-Probe, die unzuverlässig ist (Catch-all, Greylisting) und die eigene Absender-
Reputation schädigt. Wir fangen deshalb gezielt den häufigen, sicher erkennbaren Fall ab:
die Domain selbst ist tot.
"""
from __future__ import annotations

import re
import socket
import threading
from typing import Optional

# Adressen/Fragmente, die kein echtes Betriebs-Postfach sind (Substring-Match gegen die
# komplette, kleingeschriebene Adresse) — zentrale Quelle für web_analyst.py und
# contact_finder.py, die beide dieselben Fehlkandidaten (System-/Platzhalter-Adressen)
# aus gescraptem HTML aussortieren müssen.
BAD_LOCAL_PARTS = ("noreply", "no-reply", "donotreply", "postmaster", "abuse", "example",
                   "sentry", "wordpress", "@sentry", "@example", "@test")

# Kurzer Timeout — ein DNS-Lookup ist normalerweise Millisekunden. Bei bis zu 32 parallelen
# Evaluator-Threads darf ein einzelner hängender Lookup nicht sekundenlang blockieren.
_TIMEOUT = 3.0

# Prozessweiter Cache (Domain → True/False/None). Spart bei parallelen Threads und wiederholten
# Sendungen jede Menge identischer Lookups. None (unklar) wird NICHT gecacht — ein späterer
# Versuch soll bei wieder erreichbarem DNS ein echtes Ergebnis bekommen.
_cache: dict[str, Optional[bool]] = {}
_cache_lock = threading.Lock()

# dnspython optional laden — echte MX-Auflösung, aber kein harter Import-Zwang.
try:  # pragma: no cover - abhängig von der Umgebung
    import dns.resolver as _dnsresolver  # type: ignore
    _HAVE_DNS = True
except Exception:  # pragma: no cover
    _dnsresolver = None  # type: ignore
    _HAVE_DNS = False

# gaierror-Codes, die eine Domain DEFINITIV als nicht auflösbar ausweisen (→ False).
# Windows: 11001 WSAHOST_NOT_FOUND, 11004 WSANO_DATA. Unix ergänzt via Konstanten unten.
# Alles andere (z.B. 11002/EAI_AGAIN = temporär) bleibt "unklar" (→ None), damit ein
# vorübergehender Resolver-Hänger keine echte Adresse fälschlich als tot verwirft.
_TOT_CODES = {11001, 11004}
for _nm in ("EAI_NONAME", "EAI_NODATA"):
    _c = getattr(socket, _nm, None)
    if isinstance(_c, int):
        _TOT_CODES.add(_c)


def domain_of(email: str) -> str:
    """Extrahiert die (kleingeschriebene, www-bereinigte) Domain aus einer E-Mail. "" wenn
    keine plausible Adresse."""
    email = (email or "").strip().lower()
    if email.count("@") != 1:
        return ""
    dom = email.rsplit("@", 1)[1].strip().strip(".")
    dom = dom[4:] if dom.startswith("www.") else dom
    # nur Zeichen die in einer Domain vorkommen dürfen — schützt vor Regex-Müll im HTML
    if not dom or not re.fullmatch(r"[a-z0-9.\-]+", dom) or "." not in dom:
        return ""
    return dom


def _lookup(domain: str, timeout: float) -> Optional[bool]:
    """Reiner Lookup (ohne Cache/Timeout-Wrapper). True/False/None wie im Modul-Docstring."""
    # 1) Echter MX-Lookup, wenn dnspython vorhanden ist.
    if _HAVE_DNS:
        try:
            res = _dnsresolver.Resolver()
            res.timeout = timeout
            res.lifetime = timeout
            answers = res.resolve(domain, "MX")
            if answers:
                return True
        except _dnsresolver.NXDOMAIN:
            return False                       # Domain existiert gar nicht → sicher tot
        except _dnsresolver.NoAnswer:
            pass                               # kein MX → A-Record als impliziten MX prüfen
        except _dnsresolver.NoNameservers:
            return None                        # Resolver-Problem → unklar, nicht blockieren
        except Exception:
            pass                               # Timeout o.ä. → A-Record-Fallback versuchen

    # 2) Fallback / impliziter MX: löst die Domain überhaupt auf eine IP auf?
    try:
        socket.getaddrinfo(domain, None)
        return True
    except socket.gaierror as e:
        return False if e.errno in _TOT_CODES else None
    except Exception:
        return None


def has_mx(domain: str, timeout: float = _TIMEOUT) -> Optional[bool]:
    """True/False/None, ob die Domain Mail empfangen kann (siehe Modul-Docstring).

    Der eigentliche Lookup läuft in einem Daemon-Thread mit hartem join-Timeout — so ist die
    Wartezeit garantiert begrenzt, auch wenn der System-Resolver (getaddrinfo kennt selbst
    keinen Timeout-Parameter) hängt. Ein Timeout gilt als "unklar" (None), nicht als "tot"."""
    domain = (domain or "").strip().strip(".").lower()
    if not domain or "." not in domain:
        return False                           # keine echte Mail-Domain
    with _cache_lock:
        if domain in _cache:
            return _cache[domain]

    box: list[Optional[bool]] = [None]
    done = threading.Event()

    def _worker() -> None:
        try:
            box[0] = _lookup(domain, timeout)
        except Exception:
            box[0] = None
        finally:
            done.set()

    threading.Thread(target=_worker, daemon=True).start()
    if not done.wait(timeout + 1.0):
        return None                            # Lookup hängt → unklar, NICHT cachen
    res = box[0]
    if res is not None:                        # nur eindeutige Ergebnisse cachen
        with _cache_lock:
            _cache[domain] = res
    return res


def is_deliverable(email: str, timeout: float = _TIMEOUT) -> Optional[bool]:
    """Zustellbarkeit einer konkreten Adresse: syntaktische Domain-Prüfung + DNS/MX.
    False nur bei ungültiger oder definitiv toter Domain, sonst True/None."""
    dom = domain_of(email)
    if not dom:
        return False
    return has_mx(dom, timeout)


# ── Optionale zweite Stufe: SMTP-RCPT-Probe (kein DATA/Versand) ────────────────────────
#
# is_deliverable()/has_mx() prüft nur, ob die DOMAIN Mail annehmen kann — nicht, ob das
# konkrete Postfach existiert. Genau das ist die wahrscheinlichste Ursache für "konnte
# nicht zugestellt werden"-Bounces: Domain lebt, aber eine bestimmte, aus dem Impressum
# gescrapte Adresse ist tot/falsch. probe_mailbox() prüft das zusätzlich per SMTP
# (HELO/MAIL FROM/RCPT TO — OHNE DATA, es wird nie tatsächlich etwas verschickt).
#
# Bewusst Default AUS (JARVIS_SMTP_RCPT_CHECK): ausgehender Port 25 ist bei den meisten
# Heim-/Cloud-Anschlüssen geblockt (Anti-Spam-Relay-Schutz der Provider) — dann liefert
# diese Prüfung nur Timeouts (None) und kostet Zeit ohne Nutzen. Einmal gezielt auf
# JARVIS_SMTP_RCPT_CHECK=1 setzen und in den Logs beobachten, ob echte Antworten kommen.
import secrets
import smtplib

_MAILBOX_TIMEOUT = 5.0
_mailbox_cache: dict[str, Optional[bool]] = {}
_mailbox_cache_lock = threading.Lock()
_catchall_cache: dict[str, bool] = {}
_catchall_cache_lock = threading.Lock()


def rcpt_check_enabled() -> bool:
    """SMTP-RCPT-Probe aktiv? Default AUS — siehe Modul-Kommentar oben (Port 25 oft geblockt)."""
    import os
    return os.environ.get("JARVIS_SMTP_RCPT_CHECK", "0").strip().lower() in ("1", "true", "yes", "on")


def _mx_host(domain: str, timeout: float) -> str:
    """Bestpriorisierter Mailserver-Hostname, sonst die Domain selbst (impliziter A-Record-MX)."""
    if _HAVE_DNS:
        try:
            res = _dnsresolver.Resolver()
            res.timeout = timeout
            res.lifetime = timeout
            answers = res.resolve(domain, "MX")
            if answers:
                best = min(answers, key=lambda r: r.preference)
                return str(best.exchange).rstrip(".")
        except Exception:
            pass
    return domain


def _rcpt_probe(domain: str, email: str, timeout: float) -> Optional[bool]:
    import os
    host = _mx_host(domain, timeout)
    helo_domain = (os.environ.get("JARVIS_SMTP_HELO_DOMAIN") or "").strip() or "localhost"
    sender = f"probe@{helo_domain}"
    smtp: Optional[smtplib.SMTP] = None
    try:
        smtp = smtplib.SMTP(timeout=timeout)
        smtp.connect(host, 25)
        smtp.helo(helo_domain)
        smtp.mail(sender)
        code, _msg = smtp.rcpt(email)

        # Catch-All-Erkennung: akzeptiert die Domain auch eine garantiert nicht existente
        # Zufalls-Adresse, ist das RCPT-Ergebnis für die echte Adresse wertlos (jede Adresse
        # würde "akzeptiert"). Pro Domain gecacht — spart die Zusatz-Probe bei weiteren
        # Adressen derselben Domain.
        with _catchall_cache_lock:
            catchall = _catchall_cache.get(domain)
        if catchall is None:
            fake = f"nichtexistent-{secrets.token_hex(6)}@{domain}"
            code2, _msg2 = smtp.rcpt(fake)
            catchall = 200 <= code2 < 300
            with _catchall_cache_lock:
                _catchall_cache[domain] = catchall

        if catchall:
            return None                        # Domain nimmt alles an → keine verlässliche Aussage
        if 200 <= code < 300:
            return True
        if 500 <= code < 600:
            return False                       # definitiv abgelehnt (550/551/553 = Postfach unbekannt)
        return None                            # 4xx (Greylisting etc.) → unklar, nicht blockieren
    except (smtplib.SMTPException, OSError):
        return None
    except Exception:
        return None
    finally:
        try:
            if smtp:
                smtp.quit()
        except Exception:
            pass


def probe_mailbox(email: str, timeout: float = _MAILBOX_TIMEOUT) -> Optional[bool]:
    """Zusätzliche SMTP-RCPT-Prüfung EINER konkreten Adresse — nur sinnvoll aufzurufen,
    wenn is_deliverable()/has_mx() für die Domain bereits True ist (spart Verbindungen zu
    Domains, die ohnehin schon als tot gelten). Gecacht pro Adresse. Blockiert NIE länger
    als `timeout` (Daemon-Thread + hartes join-Timeout, analog has_mx())."""
    e = (email or "").strip().lower()
    dom = domain_of(e)
    if not dom:
        return False
    with _mailbox_cache_lock:
        if e in _mailbox_cache:
            return _mailbox_cache[e]

    box: list[Optional[bool]] = [None]
    done = threading.Event()

    def _worker() -> None:
        try:
            box[0] = _rcpt_probe(dom, e, timeout)
        except Exception:
            box[0] = None
        finally:
            done.set()

    threading.Thread(target=_worker, daemon=True).start()
    if not done.wait(timeout + 1.0):
        return None                            # Probe hängt → unklar, NICHT cachen
    res = box[0]
    if res is not None:
        with _mailbox_cache_lock:
            _mailbox_cache[e] = res
    return res
