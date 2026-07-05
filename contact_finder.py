"""
contact_finder.py — findet aktiv die Kontaktdaten eines Betriebs.

Hintergrund: Leads OHNE eigene Website haben in der DB fast nie eine E-Mail
(die wird sonst aus deren Impressum gezogen). Damit die „An Kunde senden"-Mail
trotzdem eine echte Adresse bekommt, sucht dieser Finder on demand:

  1. echte Website über DDG-Suche (web_analyst.analyze findet sie auch bei
     has_website=0) → Impressum-Scan → E-Mail + Ansprechpartner.
  2. Fallback: Google-Places-Detail (Telefon/Website), dann Website-Scan.

Bewusst best-effort und mit kurzen Timeouts (analyze nutzt 6-8s pro Fetch) —
blockiert nie lange. Gibt ein dict mit email/email_alle/ansprechpartner/website.
"""
from __future__ import annotations

import re

from email_verify import BAD_LOCAL_PARTS as _BAD_LOCAL

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
# Bevorzugte Postfächer (in dieser Reihenfolge) bei mehreren Treffern.
_PREFER   = ("info@", "kontakt@", "office@", "mail@", "hallo@", "service@", "anfrage@")
# Kontaktseiten, die zusätzlich zur Startseite nach E-Mails durchsucht werden.
_CONTACT_PATHS = ("", "impressum", "kontakt", "datenschutz", "impressum.html",
                  "kontakt.html", "ueber-uns", "about")


def _clean_email(addr: str) -> str:
    addr = (addr or "").strip().strip(".,;:<>\"'()[] ").lower()
    if not _EMAIL_RE.fullmatch(addr):
        return ""
    if any(b in addr for b in _BAD_LOCAL):
        return ""
    return addr


def _rank_emails(cands: list) -> list:
    """Dedupliziert + sortiert E-Mail-Kandidaten: bevorzugte Postfächer (info@/kontakt@) zuerst."""
    seen, out = set(), []
    for e in cands:
        e = _clean_email(e)
        if e and e not in seen:
            seen.add(e)
            out.append(e)

    def _score(e: str) -> int:
        for i, p in enumerate(_PREFER):
            if e.startswith(p):
                return i
        return len(_PREFER)
    return sorted(out, key=_score)


def _domain_of(url: str) -> str:
    """Registrierbare Domain aus einer URL (ohne www, ohne Pfad)."""
    try:
        from urllib.parse import urlparse
        host = (urlparse(url if "://" in url else "http://" + url).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _scan_pages(base_url: str, limit: int = 4) -> list:
    """Lädt Startseite + typische Kontaktseiten und liest alle E-Mails (inkl. mailto:) aus.
    Best-effort mit kurzen Timeouts — blockiert nie lange."""
    import urllib.request
    found: list = []
    dom = _domain_of(base_url)
    root = f"https://{dom}" if dom else base_url.rstrip("/")
    tried = 0
    for path in _CONTACT_PATHS:
        if tried >= limit or not dom:
            break
        url = root if not path else f"{root}/{path}"
        tried += 1
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 JARVIS-ContactFinder"})
            with urllib.request.urlopen(req, timeout=6) as r:
                html = r.read(400_000).decode("utf-8", "replace")
        except Exception:
            continue
        # mailto:-Links zuerst (am verlässlichsten), dann freier Text.
        for m in re.findall(r'mailto:([^"\'>\s?]+)', html):
            found.append(m)
        for m in _EMAIL_RE.findall(html):
            found.append(m)
        if any(_clean_email(e) for e in found):
            break                                    # eine gute Seite reicht
    return found


def find(name: str, stadt: str = "", branche: str = "",
         known_url: str = "") -> dict:
    """Sucht Kontaktdaten für einen Betrieb. Gibt immer ein dict:
       {ok, email, email_alle, ansprechpartner, website, quelle}."""
    out = {"ok": False, "email": "", "email_alle": [],
           "ansprechpartner": "", "website": "", "quelle": "", "geraten": False}
    name = (name or "").strip()
    if not name:
        return out

    lead = {"name": name, "stadt": (stadt or "").strip(),
            "branche": (branche or "").strip()}
    if known_url:
        lead["website_url"] = known_url.strip()

    website = (known_url or "").strip()

    # 1) Volle Website-Analyse (DDG → Website → Impressum → E-Mail/Ansprechpartner)
    try:
        from agents.evaluator.web_analyst import analyze
        web = analyze(lead) or {}
        alle = _rank_emails([web.get("email_adresse", "")] + list(web.get("email_alle") or []))
        website = (web.get("discovered_website") or web.get("website_url") or website).strip()
        out["website"] = website
        out["ansprechpartner"] = (web.get("ansprechpartner") or "").strip()
        if alle:
            out["email"] = alle[0]
            out["email_alle"] = alle[:8]
            out["ok"] = True
            out["quelle"] = "website"
            return out
    except Exception:
        pass

    # 2) Direkter Kontaktseiten-Scan (Startseite + /impressum + /kontakt + mailto:)
    if website:
        try:
            alle = _rank_emails(_scan_pages(website))
            if alle:
                out["website"] = website
                out["email"] = alle[0]
                out["email_alle"] = alle[:8]
                out["ok"] = True
                out["quelle"] = "kontaktseite"
                return out
        except Exception:
            pass

    # 3) Google-Places-Detail → offizielle Website → erneuter Scan
    if not website:
        try:
            from agent_maps import place_contact   # optional, falls vorhanden
            pc = place_contact(name, stadt) or {}
            url = (pc.get("website") or "").strip()
            if url and url != known_url:
                return find(name, stadt, branche, known_url=url)
        except Exception:
            pass

    # 4) Letzter Ausweg: aus der Domain ein Standard-Postfach ableiten (markiert als Schätzung).
    dom = _domain_of(website)
    if dom and "." in dom:
        out["website"] = website
        out["email"] = f"info@{dom}"
        out["email_alle"] = [f"info@{dom}"]
        out["ok"] = True
        out["geraten"] = True
        out["quelle"] = "domain-schätzung"

    return out
