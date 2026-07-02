"""
Prüft ob eine gefundene Website existiert + wie alt sie ist (WHOIS).
Schnell und ohne externen API-Key.
"""
import socket
import threading
import urllib.request
import urllib.error
import re
import datetime


def check_website(url: str) -> dict:
    """
    Gibt {exists: bool, alter_jahre: int, status_code: int} zurück.
    alter_jahre = -1 wenn unbekannt.
    """
    if not url:
        return {"exists": False, "alter_jahre": -1, "status_code": 0}

    if not url.startswith("http"):
        url = "https://" + url

    result = {"exists": False, "alter_jahre": -1, "status_code": 0}
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; LeadBot/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            result["status_code"] = resp.status
            result["exists"]      = resp.status < 400
    except urllib.error.HTTPError as e:
        result["status_code"] = e.code
        result["exists"]      = e.code < 500
    except Exception:
        result["exists"] = False

    # WHOIS-Alter (Fallback: 0)
    if result["exists"]:
        result["alter_jahre"] = _whois_age(url)

    return result


def _whois_age(url: str, timeout: float = 5.0) -> int:
    """Schätzt Website-Alter via WHOIS creation_date. -1 = unbekannt.

    python-whois macht eine WHOIS-Netzabfrage OHNE eigenes Timeout — ein träger WHOIS-Server
    kann den aufrufenden Worker-Thread beliebig lange einfrieren. Darum läuft die Abfrage in
    einem Daemon-Thread mit hartem join(timeout): antwortet der Server nicht in `timeout`
    Sekunden, kehrt der Aufrufer mit -1 zurück (der Daemon läuft im Hintergrund aus)."""
    result = [-1]

    def _work():
        try:
            import whois as _w  # python-whois
            domain = re.sub(r"https?://", "", url).split("/")[0].split(":")[0]
            w = _w.whois(domain)
            cd = w.creation_date
            if isinstance(cd, list):
                cd = cd[0]
            if cd:
                delta = datetime.date.today() - cd.date()
                result[0] = max(0, delta.days // 365)
        except Exception:
            pass

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    t.join(timeout)
    return result[0]
