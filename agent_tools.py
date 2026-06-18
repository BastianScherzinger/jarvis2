"""
Werkzeugkasten des Claude-Dashboard-Agenten.

Definiert die Anthropic-Tool-Schemas und führt sie aus (Maps, Browser, Medien,
Lead-Datenbank). Wird von claude_chat.py im Tool-Use-Loop genutzt.
"""
from __future__ import annotations

# ── Tool-Schemas (Anthropic Messages API) ─────────────────────────────────────
TOOLS = [
    # — Maps —
    {"name": "maps_search",
     "description": "Suche reale Orte/Betriebe über Google Maps (Name, Adresse, "
                    "Telefon, Website, Bewertung, place_id). Nutze dies für 'finde "
                    "Firmen/Restaurants/Handwerker in X' oder Adress-Recherche.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "Suchanfrage, z.B. 'Dachdecker Aichach'"},
         "limit": {"type": "integer", "description": "max. Treffer (1-10)"}},
         "required": ["query"]}},
    {"name": "maps_geocode",
     "description": "Wandle eine Adresse/einen Ort in Koordinaten + formatierte Adresse um.",
     "input_schema": {"type": "object", "properties": {
         "address": {"type": "string"}}, "required": ["address"]}},
    {"name": "maps_place_details",
     "description": "Details zu einem Ort per place_id (Telefon, Website, Öffnungszeiten).",
     "input_schema": {"type": "object", "properties": {
         "place_id": {"type": "string"}}, "required": ["place_id"]}},
    {"name": "maps_directions",
     "description": "Route zwischen zwei Orten (Distanz, Dauer, Schritte).",
     "input_schema": {"type": "object", "properties": {
         "origin": {"type": "string"}, "destination": {"type": "string"},
         "mode": {"type": "string", "enum": ["driving", "walking", "bicycling", "transit"]}},
         "required": ["origin", "destination"]}},

    # — Browser (echtes Öffnen/Scrollen/Klicken) —
    {"name": "browser_open",
     "description": "Öffne eine URL im echten Browser und lies den sichtbaren Text. "
                    "Start jeder Web-Interaktion. Der Browser bleibt für Folge-Aktionen offen.",
     "input_schema": {"type": "object", "properties": {
         "url": {"type": "string"}}, "required": ["url"]}},
    {"name": "browser_click",
     "description": "Klicke ein Element — per CSS-Selektor (z.B. '.btn', '#login') ODER "
                    "sichtbarem Text (z.B. 'Mehr anzeigen').",
     "input_schema": {"type": "object", "properties": {
         "target": {"type": "string"}}, "required": ["target"]}},
    {"name": "browser_type",
     "description": "Tippe Text in ein Feld (CSS-Selektor oder Label/Platzhalter-Text). "
                    "enter=true sendet danach Enter (z.B. für Suchfelder).",
     "input_schema": {"type": "object", "properties": {
         "target": {"type": "string"}, "text": {"type": "string"},
         "enter": {"type": "boolean"}}, "required": ["target", "text"]}},
    {"name": "browser_scroll",
     "description": "Scrolle die Seite. Richtung: down, up, top, bottom.",
     "input_schema": {"type": "object", "properties": {
         "direction": {"type": "string", "enum": ["down", "up", "top", "bottom"]}}}},
    {"name": "browser_read",
     "description": "Lies den aktuellen sichtbaren Seitentext (mehr als beim Öffnen).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "browser_links",
     "description": "Liste die Links der aktuellen Seite (optional gefiltert).",
     "input_schema": {"type": "object", "properties": {
         "filter": {"type": "string", "description": "optionaler Filtertext"}}}},
    {"name": "browser_back",
     "description": "Gehe im Browser eine Seite zurück.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "browser_screenshot",
     "description": "Mache einen Screenshot der aktuellen Seite (im Bilder-Ordner gespeichert).",
     "input_schema": {"type": "object", "properties": {}}},

    # — Medien —
    {"name": "generate_image",
     "description": "Erzeuge ein Bild aus einem Text-Prompt (lokale Diffusers-Modelle). "
                    "Läuft asynchron, erscheint im Bilder-Tab.",
     "input_schema": {"type": "object", "properties": {
         "prompt": {"type": "string"}}, "required": ["prompt"]}},
    {"name": "generate_video",
     "description": "Erzeuge ein Video aus einem Prompt. backend 'local' oder 'higgsfield' "
                    "(Higgsfield braucht HIGGSFIELD_API_KEY).",
     "input_schema": {"type": "object", "properties": {
         "prompt": {"type": "string"},
         "backend": {"type": "string", "enum": ["local", "higgsfield"]}}, "required": ["prompt"]}},
    {"name": "media_job_status",
     "description": "Status eines Bild-/Video-Jobs per Job-ID abfragen.",
     "input_schema": {"type": "object", "properties": {
         "job_id": {"type": "string"}}, "required": ["job_id"]}},

    # — Eigene Lead-Datenbank —
    {"name": "leads_top",
     "description": "Die besten bewerteten Leads des LeadHunters (nach Erwartungswert). "
                    "Nutze dies für Fragen zu 'unseren Leads / besten Kunden / Pipeline'.",
     "input_schema": {"type": "object", "properties": {
         "limit": {"type": "integer", "description": "Anzahl (1-20)"}}}},
    {"name": "leads_search",
     "description": "Durchsuche die bewerteten Leads nach Name/Stadt/Branche.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string"}}, "required": ["query"]}},
]


# ── Ausführung ────────────────────────────────────────────────────────────────

def execute(name: str, args: dict) -> str:
    """Führt ein Tool aus und gibt ein Text-Ergebnis zurück (nie eine Exception)."""
    try:
        return _dispatch(name, args or {})
    except Exception as e:
        return f"Tool-Fehler in {name}: {type(e).__name__}: {str(e)[:200]}"


def _dispatch(name: str, a: dict) -> str:
    if name.startswith("maps_"):
        import agent_maps
        if name == "maps_search":
            return agent_maps.search_places(a.get("query", ""), int(a.get("limit", 6) or 6))
        if name == "maps_geocode":
            return agent_maps.geocode(a.get("address", ""))
        if name == "maps_place_details":
            return agent_maps.place_details(a.get("place_id", ""))
        if name == "maps_directions":
            return agent_maps.directions(a.get("origin", ""), a.get("destination", ""),
                                         a.get("mode", "driving"))

    if name.startswith("browser_"):
        import agent_browser
        act = name[len("browser_"):]
        return agent_browser.do(act, url=a.get("url", ""), target=a.get("target", ""),
                                text=a.get("text", ""), enter=bool(a.get("enter")),
                                direction=a.get("direction", "down"), filter=a.get("filter", ""))

    if name in ("generate_image", "generate_video", "media_job_status"):
        import agent_media
        if name == "generate_image":
            return agent_media.generate_image(a.get("prompt", ""))
        if name == "generate_video":
            return agent_media.generate_video(a.get("prompt", ""), a.get("backend", "local"))
        return agent_media.job_status(a.get("job_id", ""))

    if name == "leads_top":
        import db_evaluated
        rows = db_evaluated.get_all(limit=int(a.get("limit", 10) or 10), sort="erwartungswert")
        return _fmt_leads(rows)
    if name == "leads_search":
        import db_evaluated
        rows = db_evaluated.get_all(limit=10, suche=a.get("query", ""), sort="erwartungswert")
        return _fmt_leads(rows)

    return f"Unbekanntes Tool: {name}"


def _fmt_leads(rows: list[dict]) -> str:
    if not rows:
        return "Keine passenden Leads gefunden."
    out = []
    for l in rows:
        ew  = l.get("erwartungswert_euro") or 0
        out.append(f"- {l.get('name','?')} ({l.get('stadt','')}, {l.get('branche','')}) | "
                   f"Score {l.get('score',0)} · Sicherheit {l.get('sicherheit',0)} · "
                   f"EW {ew}€ · {l.get('lead_typ','')}"
                   + (f" · Tel {l.get('telefon')}" if l.get('telefon') else "")
                   + (f" · {l.get('email_adresse')}" if l.get('email_adresse') else ""))
    return "\n".join(out)
