"""Agent 1 — Analysiert Website + extrahiert E-Mail aus Impressum."""
import re
import datetime
from urllib.parse import urljoin

from scrapers._http import get as http_get

_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
_BAD_DOMAINS = ['example', 'test', 'sentry', 'wix', 'google', 'schema']


def _real_emails(html: str) -> list[str]:
    emails = _EMAIL_RE.findall(html or "")
    return [e for e in emails if not any(b in e.lower() for b in _BAD_DOMAINS)]


def analyze(lead: dict) -> dict:
    """
    Gibt zurück: {email_vorhanden, email_adresse, telefon_verifiziert,
                  website_veraltet, website_alter_jahre, website_probleme: []}
    """
    result = {
        "email_vorhanden": 0, "email_adresse": "",
        "telefon_verifiziert": 0,
        "website_veraltet": 0, "website_alter_jahre": -1,
        "website_probleme": [],
    }

    # Telefon-Format-Check (deutsch: +49, 0XXX...)
    tel = (lead.get("telefon") or "").strip()
    if tel and len(tel) >= 6:
        if re.search(r'[\d\s\-\+\(\)]{6,}', tel):
            result["telefon_verifiziert"] = 1

    url = (lead.get("website_url") or "").strip()
    if not url or not lead.get("has_website"):
        return result

    # Website laden (timeout 8s)
    html = http_get(url, timeout=8)
    if not html:
        result["website_probleme"].append("Website nicht erreichbar")
        result["website_veraltet"] = 1
        return result

    # E-Mail aus HTML extrahieren
    real = _real_emails(html)
    if real:
        result["email_vorhanden"] = 1
        result["email_adresse"] = real[0][:100]

    # Falls keine E-Mail: Impressum-Seite probieren
    if not result["email_vorhanden"]:
        imp_match = re.search(r'href=["\']([^"\']*impressum[^"\']*)["\']', html, re.I)
        if imp_match:
            imp_url = imp_match.group(1)
            if not imp_url.startswith('http'):
                imp_url = urljoin(url, imp_url)
            imp_html = http_get(imp_url, timeout=6)
            if imp_html:
                real_imp = _real_emails(imp_html)
                if real_imp:
                    result["email_vorhanden"] = 1
                    result["email_adresse"] = real_imp[0][:100]

    # Website-Probleme analysieren
    issues = []

    # HTTPS
    if not url.startswith("https://"):
        issues.append("Kein HTTPS")

    # Mobile viewport
    if 'viewport' not in html.lower():
        issues.append("Kein Mobile-Viewport (nicht mobil-freundlich)")

    # Copyright-Jahr
    years = re.findall(r'(?:©|copyright|Copyright)\s*(?:\d{4}\s*[-–]\s*)?(20\d{2})', html)
    if years:
        max_year = max(int(y) for y in years)
        current = datetime.date.today().year
        age = current - max_year
        result["website_alter_jahre"] = age
        if age >= 4:
            issues.append(f"Copyright {max_year} — {age} Jahre alt")
            result["website_veraltet"] = 1

    # Veraltete Technik
    veraltet_patterns = [
        (r'<table[^>]+(?:width|cellpadding|cellspacing)', "Tabellen-Layout (veraltet)"),
        (r'<font\s', "Font-Tags (veraltet)"),
        (r'\.swf["\']', "Flash-Inhalte"),
        (r'<marquee', "Marquee-Tag"),
        (r'<frameset', "Frames-Layout"),
    ]
    for pattern, label in veraltet_patterns:
        if re.search(pattern, html, re.I):
            issues.append(label)
            result["website_veraltet"] = 1

    # Kein Impressum
    if 'impressum' not in html.lower() and 'imprint' not in html.lower():
        issues.append("Kein Impressum erkennbar")

    result["website_probleme"] = issues[:6]  # max 6 Probleme
    if issues:
        result["website_veraltet"] = 1

    # WHOIS-Alter wenn noch nicht gesetzt
    if result["website_alter_jahre"] == -1:
        try:
            from scrapers.website_checker import _whois_age
            result["website_alter_jahre"] = _whois_age(url)
        except Exception:
            pass

    return result
