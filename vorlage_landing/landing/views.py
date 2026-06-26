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
    # Kostenrechner (Hero-Karte). Wird beim Bau/Makeover branchengerecht befüllt; hier nur
    # Platzhalter — der Fallback unten erzeugt immer einen funktionierenden Datensatz.
    "rechner": {},
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
    # Echte eingebettete OSM-Karte + Maps-Link, wenn Koordinaten vorliegen (vom Makeover geocodet).
    # Bereits in content.json gesetzte Werte (map_embed/maps_url) werden NICHT überschrieben —
    # nur wenn sie fehlen, leiten wir sie hier ab (Adress-Suche als letzter Fallback).
    try:
        lat = float(data.get("lat"))
        lng = float(data.get("lng"))
        dlat, dlng = 0.006, 0.010
        if not data.get("map_embed"):
            data["map_embed"] = (
                "https://www.openstreetmap.org/export/embed.html"
                f"?bbox={lng-dlng}%2C{lat-dlat}%2C{lng+dlng}%2C{lat+dlat}"
                f"&layer=mapnik&marker={lat}%2C{lng}")
        if not data.get("maps_url"):
            data["maps_url"] = (
                f"https://www.openstreetmap.org/?mlat={lat}&mlon={lng}#map=16/{lat}/{lng}")
    except (TypeError, ValueError):
        # Keine Koordinaten — Fallback: Google-Maps-Suche über Adresse (kein API-Key nötig).
        if not data.get("maps_url"):
            adr = (data.get("adresse") or "").strip()
            if adr:
                import urllib.parse
                data["maps_url"] = ("https://www.google.com/maps/search/?api=1&query="
                                    + urllib.parse.quote(adr))
        if not data.get("map_embed"):
            data["map_embed"] = ""
    team = list(data.get("team") or [])
    if not team:
        team = list(_TEAM_FALLBACK)
    data["team4"] = team[:4]
    # Kostenrechner: aus content.json nehmen; sonst generischen Datensatz bauen (rendert IMMER).
    rech = data.get("rechner")
    if not (isinstance(rech, dict) and rech.get("posten")):
        leist = [str(l.get("titel", "")).strip() for l in (data.get("leistungen") or [])
                 if isinstance(l, dict) and l.get("titel")]
        if leist:
            posten = [{"name": t, "ab": 150, "bis": 1500} for t in leist[:5]]
        else:
            posten = [
                {"name": "Kleiner Auftrag", "ab": 150, "bis": 600},
                {"name": "Mittleres Projekt", "ab": 600, "bis": 3000},
                {"name": "Großes Projekt", "ab": 3000, "bis": 15000},
            ]
        data["rechner"] = {
            "titel": "Kostenrechner", "untertitel": "Unverbindliche Sofort-Schätzung",
            "posten": posten,
            "hinweis": "Grobe Orientierung — Ihr genaues Angebot ist kostenlos.",
        }
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
