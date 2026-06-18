"""
Maps-Tool für den Claude-Dashboard-Agenten — Google Places API (New) + Routes API.

Nutzt GOOGLE_MAPS_API_KEY aus der .env. Die modernen Endpunkte (places.googleapis.com,
routes.googleapis.com) ersetzen die abgekündigten Legacy-APIs. Im Google-Cloud-Projekt
müssen "Places API (New)" und (für Routen) "Routes API" aktiviert sein.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

_TIMEOUT = 15


def _key() -> str:
    return os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()


def is_available() -> bool:
    return bool(_key())


def _post(url: str, body: dict, field_mask: str) -> tuple[dict, str]:
    """POST mit API-Key + FieldMask. Gibt (json, fehler) zurück."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type":      "application/json",
        "X-Goog-Api-Key":    _key(),
        "X-Goog-FieldMask":  field_mask,
    })
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return json.loads(r.read()), ""
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", errors="replace")
        try:
            msg = json.loads(body_txt)["error"]["message"]
        except Exception:
            msg = body_txt[:200]
        return {}, f"Maps-Fehler (HTTP {e.code}): {msg}"
    except Exception as e:
        return {}, f"Maps-Fehler: {type(e).__name__}"


def _get(url: str, field_mask: str) -> tuple[dict, str]:
    req = urllib.request.Request(url, headers={
        "X-Goog-Api-Key":   _key(),
        "X-Goog-FieldMask": field_mask,
    })
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return json.loads(r.read()), ""
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", errors="replace")
        try:
            msg = json.loads(body_txt)["error"]["message"]
        except Exception:
            msg = body_txt[:200]
        return {}, f"Maps-Fehler (HTTP {e.code}): {msg}"
    except Exception as e:
        return {}, f"Maps-Fehler: {type(e).__name__}"


def _fmt_place(p: dict, idx: int | None = None) -> str:
    name   = (p.get("displayName") or {}).get("text", "?")
    addr   = p.get("formattedAddress", "")
    rating = f" · {p['rating']}★ ({p.get('userRatingCount',0)})" if p.get("rating") else ""
    offen  = ""
    oh = p.get("currentOpeningHours") or p.get("regularOpeningHours")
    if isinstance(oh, dict) and "openNow" in oh:
        offen = " · geöffnet" if oh["openNow"] else " · geschlossen"
    head = (f"{idx}. " if idx else "") + f"{name}{rating}{offen}"
    lines = [head]
    if addr:                       lines.append(f"   {addr}")
    if p.get("nationalPhoneNumber"): lines.append(f"   Tel: {p['nationalPhoneNumber']}")
    if p.get("websiteUri"):        lines.append(f"   Web: {p['websiteUri']}")
    if p.get("id"):                lines.append(f"   place_id: {p['id']}")
    return "\n".join(lines)


# ── Orte suchen ───────────────────────────────────────────────────────────────

def search_places(query: str, limit: int = 6) -> str:
    if not _key():
        return "GOOGLE_MAPS_API_KEY fehlt in der .env."
    mask = ("places.displayName,places.formattedAddress,places.location,places.rating,"
            "places.userRatingCount,places.id,places.nationalPhoneNumber,"
            "places.websiteUri,places.currentOpeningHours.openNow")
    data, err = _post("https://places.googleapis.com/v1/places:searchText",
                      {"textQuery": query, "languageCode": "de",
                       "maxResultCount": max(1, min(limit, 10))}, mask)
    if err:
        return err
    places = data.get("places", [])
    if not places:
        return f"Keine Treffer für '{query}'."
    return "\n".join(_fmt_place(p, i) for i, p in enumerate(places, 1))


# ── Geocoding (über Text-Suche) ───────────────────────────────────────────────

def geocode(address: str) -> str:
    if not _key():
        return "GOOGLE_MAPS_API_KEY fehlt in der .env."
    mask = "places.formattedAddress,places.location,places.id,places.displayName"
    data, err = _post("https://places.googleapis.com/v1/places:searchText",
                      {"textQuery": address, "languageCode": "de", "maxResultCount": 1}, mask)
    if err:
        return err
    places = data.get("places", [])
    if not places:
        return f"Keine Koordinaten für '{address}'."
    p = places[0]
    loc = p.get("location", {})
    return (f"{p.get('formattedAddress','')}\n"
            f"Koordinaten: {loc.get('latitude')}, {loc.get('longitude')}\n"
            f"place_id: {p.get('id','')}")


# ── Details zu einem Ort ──────────────────────────────────────────────────────

def place_details(place_id: str) -> str:
    if not _key():
        return "GOOGLE_MAPS_API_KEY fehlt in der .env."
    mask = ("displayName,formattedAddress,nationalPhoneNumber,websiteUri,rating,"
            "userRatingCount,regularOpeningHours,googleMapsUri")
    data, err = _get(f"https://places.googleapis.com/v1/places/{place_id}", mask)
    if err:
        return err
    out = _fmt_place(data)
    oh = data.get("regularOpeningHours")
    if isinstance(oh, dict) and oh.get("weekdayDescriptions"):
        out += "\n   Öffnungszeiten:\n     " + "\n     ".join(oh["weekdayDescriptions"])
    if data.get("googleMapsUri"):
        out += f"\n   Maps: {data['googleMapsUri']}"
    return out


# ── Route (Routes API) ────────────────────────────────────────────────────────

def directions(origin: str, destination: str, mode: str = "driving") -> str:
    if not _key():
        return "GOOGLE_MAPS_API_KEY fehlt in der .env."
    travel = {"driving": "DRIVE", "walking": "WALK", "bicycling": "BICYCLE",
              "transit": "TRANSIT"}.get(mode, "DRIVE")
    mask = "routes.duration,routes.distanceMeters,routes.legs.steps.navigationInstruction"
    data, err = _post("https://routes.googleapis.com/directions/v2:computeRoutes",
                      {"origin": {"address": origin}, "destination": {"address": destination},
                       "travelMode": travel, "languageCode": "de"}, mask)
    if err:
        return err
    routes = data.get("routes", [])
    if not routes:
        return f"Keine Route von '{origin}' nach '{destination}'."
    r = routes[0]
    dist_km = round(r.get("distanceMeters", 0) / 1000, 1)
    dur = r.get("duration", "0s")
    sec = int(re.sub(r"[^0-9]", "", dur) or 0)
    dauer = f"{sec // 3600}h {sec % 3600 // 60}min" if sec >= 3600 else f"{sec // 60} min"
    schritte = []
    for leg in r.get("legs", []):
        for s in leg.get("steps", [])[:15]:
            instr = (s.get("navigationInstruction") or {}).get("instructions", "")
            if instr:
                schritte.append(f"  • {instr}")
    return (f"Route ({mode}): {origin} → {destination}\n"
            f"Distanz: {dist_km} km · Dauer: {dauer}\n" + "\n".join(schritte))
