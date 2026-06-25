"""
Landing-View — rendert die Seite aus content.json (im Projekt-Wurzelverzeichnis).

content.json wird vom JARVIS-Website-Builder mit den echten Lead-Daten gefüllt.
Fehlt sie, greift ein neutraler Fallback, damit die Seite nie crasht.
"""
import json
import os
import re
from pathlib import Path

from django.http import HttpResponse
from django.shortcuts import render

_CONTENT = Path(__file__).resolve().parent.parent / "content.json"

_FALLBACK = {
    "site_name": "Ihre Firma",
    "headline": "Handwerk, auf das Sie sich verlassen können",
    "subline": "Qualität aus Ihrer Region — zuverlässig, sauber, termintreu.",
    "akzent": "#c8102e",
    "branche": "Handwerk",
    "stadt": "",
    "telefon": "",
    "email": "",
    "adresse": "",
    "ueber_titel": "Über uns",
    "ueber_text": "Seit Jahren Ihr verlässlicher Partner in der Region.",
    "leistungen": [],
    "fotos": [],
    "hero_image": "",
    "cta_text": "Jetzt unverbindlich anfragen",
    "seo_title": "Ihre Firma",
    "seo_desc": "Qualität aus Ihrer Region.",
    "jahr": 2026,
    # Team: Inhaber + bis zu 4 Mitarbeiter (Platzhalter, vom Inhaber später ersetzbar).
    "inhaber_name": "",
    "team": [],
    # Rechtstexte (deterministisch von legal_pages befüllt; sonst leer → Hinweis).
    "datenschutz": "",
    "impressum": "",
    "agb": "",
    # „Erstellt von WVM-IT"-Branding (Agentur-Credit im Footer). Defaults gelten auch auf der
    # deployten Kundenseite (Railway), wo die JARVIS_WVM_*-Env NICHT gesetzt ist. Per content.json
    # oder Env überschreibbar. Das Foto liegt in static/img und wird in jeden Build mitkopiert.
    "wvm_name": "WVM-IT",
    "wvm_url": "https://wvm-it.tech",
    "wvm_logo": "",
    "wvm_photo": "/static/img/wvm_person.jpg",
    "wvm_shop": "https://www.pystore.de",
}

# Vier neutrale Mitarbeiter-Platzhalter, falls keine Team-Daten vorliegen.
_TEAM_FALLBACK = [
    {"name": "[Name]", "rolle": "Meister"},
    {"name": "[Name]", "rolle": "Geselle"},
    {"name": "[Name]", "rolle": "Projektleitung"},
    {"name": "[Name]", "rolle": "Büro & Kontakt"},
]


def _whatsapp(tel: str) -> str:
    """Telefonnummer → wa.me-Ziffern (Ländervorwahl 49, ohne 0/+/Leerzeichen). '' = ungültig."""
    digits = re.sub(r"\D", "", tel or "")
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = "49" + digits[1:]
    elif not digits.startswith("49"):
        digits = "49" + digits
    return digits if len(digits) >= 8 else ""


def _content() -> dict:
    data = dict(_FALLBACK)
    try:
        loaded = json.loads(_CONTENT.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data.update(loaded)
    except Exception:
        pass
    # Abgeleitete Felder fürs Template (WhatsApp + Team immer 4 Slots).
    data["whatsapp"] = _whatsapp(data.get("telefon", ""))
    # Karten-Link aus der Adresse (kein API-Key, funktioniert immer; kein leerer Embed).
    adr = (data.get("adresse") or "").strip()
    if adr:
        import urllib.parse
        data["maps_url"] = "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(adr)
    else:
        data["maps_url"] = ""
    team = list(data.get("team") or [])
    if not team:
        team = list(_TEAM_FALLBACK)
    data["team4"] = team[:4]
    # WVM-Branding: Env-Override (zentral, ohne Rebuild) gewinnt über content.json/Default.
    for key, env in (("wvm_name", "JARVIS_WVM_NAME"), ("wvm_url", "JARVIS_WVM_URL"),
                     ("wvm_logo", "JARVIS_WVM_LOGO"), ("wvm_photo", "JARVIS_WVM_PHOTO"),
                     ("wvm_shop", "JARVIS_WVM_SHOP")):
        val = os.environ.get(env, "").strip()
        if val:
            data[key] = val
    return data


def index(request):
    return render(request, "index.html", {"c": _content()})


def health(request):
    return HttpResponse("ok", content_type="text/plain")
