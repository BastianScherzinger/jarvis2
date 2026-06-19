"""
Landing-View — rendert die Seite aus content.json (im Projekt-Wurzelverzeichnis).

content.json wird vom JARVIS-Website-Builder mit den echten Lead-Daten gefüllt.
Fehlt sie, greift ein neutraler Fallback, damit die Seite nie crasht.
"""
import json
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
}


def _content() -> dict:
    try:
        data = json.loads(_CONTENT.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {**_FALLBACK, **data}
    except Exception:
        pass
    return dict(_FALLBACK)


def index(request):
    return render(request, "index.html", {"c": _content()})


def health(request):
    return HttpResponse("ok", content_type="text/plain")
