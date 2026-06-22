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

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def _clean_email(addr: str) -> str:
    addr = (addr or "").strip().strip(".,;:<>\"'()[] ")
    return addr if _EMAIL_RE.fullmatch(addr) else ""


def find(name: str, stadt: str = "", branche: str = "",
         known_url: str = "") -> dict:
    """Sucht Kontaktdaten für einen Betrieb. Gibt immer ein dict:
       {ok, email, email_alle, ansprechpartner, website, quelle}."""
    out = {"ok": False, "email": "", "email_alle": [],
           "ansprechpartner": "", "website": "", "quelle": ""}
    name = (name or "").strip()
    if not name:
        return out

    lead = {"name": name, "stadt": (stadt or "").strip(),
            "branche": (branche or "").strip()}
    if known_url:
        lead["website_url"] = known_url.strip()

    # 1) Volle Website-Analyse (DDG → Website → Impressum → E-Mail/Ansprechpartner)
    try:
        from agents.evaluator.web_analyst import analyze
        web = analyze(lead) or {}
        email = _clean_email(web.get("email_adresse", ""))
        alle = [e for e in (_clean_email(x) for x in (web.get("email_alle") or [])) if e]
        if email and email not in alle:
            alle.insert(0, email)
        out["website"] = (web.get("discovered_website") or web.get("website_url") or "").strip()
        out["ansprechpartner"] = (web.get("ansprechpartner") or "").strip()
        if alle:
            out["email"] = alle[0]
            out["email_alle"] = alle[:8]
            out["ok"] = True
            out["quelle"] = "website"
            return out
    except Exception:
        pass

    # 2) Fallback: Google-Places-Detail → offizielle Website → erneuter Scan
    try:
        from agent_maps import place_contact   # optional, falls vorhanden
        pc = place_contact(name, stadt) or {}
        url = (pc.get("website") or "").strip()
        if url and url != known_url:
            return find(name, stadt, branche, known_url=url)
    except Exception:
        pass

    return out
