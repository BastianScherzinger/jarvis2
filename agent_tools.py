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
     "description": "Status eines Bild-/Video-Jobs per Job-ID abfragen. wait=true wartet "
                    "bis zu 25s auf die Fertigstellung (für schnelle Jobs).",
     "input_schema": {"type": "object", "properties": {
         "job_id": {"type": "string"}, "wait": {"type": "boolean"}}, "required": ["job_id"]}},

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
    {"name": "leads_update",
     "description": "Schreibe in einen Lead: Status setzen (neu/kontaktiert/termin/verkauft/tot) "
                    "und/oder eine Notiz hinzufügen. Lead per id ODER name. Nutze dies, wenn Sir "
                    "sagt 'markiere X als kontaktiert' oder 'notiere bei Y …'.",
     "input_schema": {"type": "object", "properties": {
         "id": {"type": "integer"}, "name": {"type": "string"},
         "status": {"type": "string", "enum": ["neu", "kontaktiert", "termin", "verkauft", "tot"]},
         "notiz": {"type": "string"},
         "verkauft_euro": {"type": "integer", "description": "realisierter Umsatz bei Abschluss"}}}},
    {"name": "leads_conversion_stats",
     "description": "Konversions-Statistik: was wird tatsächlich zu Kunden (nach Status, "
                    "Branche, Score-Band) + Umsatz. Realitäts-Abgleich fürs Scoring.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "enrich_business",
     "description": "Bewerte einen BELIEBIGEN Betrieb sofort auf Akquise-Tauglichkeit: findet "
                    "die Website, prüft Qualität/Alter/Mängel, Social, und berechnet Score, "
                    "Sicherheit und Erwartungswert — wie die Lead-Pipeline, aber on demand. "
                    "Nutze dies für 'wie akquise-tauglich ist Betrieb X in Stadt Y'.",
     "input_schema": {"type": "object", "properties": {
         "name": {"type": "string"}, "stadt": {"type": "string"}, "branche": {"type": "string"}},
         "required": ["name"]}},

    # — Shop / Django-Seite bauen —
    {"name": "shop_skill",
     "description": "Lade die Anleitung zum Bauen einer Railway-ready Django-Shop-Seite "
                    "(Workflow + Vorlagen-Struktur). Lies dies ZUERST, bevor du einen Shop baust.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "shop_new",
     "description": "Erstelle ein neues Shop-Projekt aus der Vorlage (kopiert shop_vorlage "
                    "nach Desktop/<name>). Danach mit shop_read/shop_write anpassen.",
     "input_schema": {"type": "object", "properties": {
         "name": {"type": "string", "description": "Projekt-/Ordnername"}}, "required": ["name"]}},
    {"name": "shop_list",
     "description": "Dateien/Ordner eines Shop-Projekts auflisten (Pfad relativ zum Desktop).",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string"}}}},
    {"name": "shop_read",
     "description": "Eine Projekt-Datei lesen (Pfad relativ zum Desktop, z.B. 'meinshop/config/settings.py').",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string"}}, "required": ["path"]}},
    {"name": "shop_write",
     "description": "Eine Projekt-Datei schreiben/überschreiben (Pfad relativ zum Desktop). "
                    ".sh-Dateien werden automatisch mit LF gespeichert.",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string"}, "content": {"type": "string"}},
         "required": ["path", "content"]}},
    {"name": "shop_git",
     "description": "git init + commit + push eines fertigen Shop-Projekts nach GitHub. "
                    "Frag Sir ZUERST nach der Repo-URL, dann pushen. Letzter Schritt.",
     "input_schema": {"type": "object", "properties": {
         "name": {"type": "string"}, "repo_url": {"type": "string"},
         "message": {"type": "string"}}, "required": ["name", "repo_url"]}},
]


# ── Ausführung ────────────────────────────────────────────────────────────────

_ERR_PREFIXES = ("tool-fehler", "browser-fehler", "maps-fehler", "schreibfehler",
                 "lesefehler", "unbekanntes tool", "unbekannte aktion", "ungültig")


def run(name: str, args: dict) -> dict:
    """Führt ein Tool aus, misst Latenz + Fehler (metrics). Gibt {'text','ok'} zurück."""
    import time
    t0 = time.perf_counter()
    ok = True
    try:
        out = _dispatch(name, args or {})
        low = (out or "").lstrip().lower()
        if any(low.startswith(p) for p in _ERR_PREFIXES) or "fehlgeschlagen" in low[:60]:
            ok = False
    except Exception as e:
        ok = False
        out = f"Tool-Fehler in {name}: {type(e).__name__}: {str(e)[:200]}"
    ms = (time.perf_counter() - t0) * 1000
    try:
        import metrics
        metrics.record_tool(name, ms, ok)
    except Exception:
        pass
    return {"text": out or "", "ok": ok}


def execute(name: str, args: dict) -> str:
    """Rückwärtskompatibel — gibt nur den Ergebnistext zurück (nie eine Exception)."""
    return run(name, args)["text"]


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
        return agent_media.job_status(a.get("job_id", ""), bool(a.get("wait")))

    if name == "leads_top":
        import db_evaluated
        rows = db_evaluated.get_all(limit=int(a.get("limit", 10) or 10), sort="erwartungswert")
        return _fmt_leads(rows)
    if name == "leads_search":
        import db_evaluated
        rows = db_evaluated.get_all(limit=10, suche=a.get("query", ""), sort="erwartungswert")
        return _fmt_leads(rows)

    if name == "leads_update":
        import db_evaluated
        lead = None
        if a.get("id"):
            try:
                lead = db_evaluated.get_by_id(int(a["id"]))
            except Exception:
                lead = None
        if lead is None and a.get("name"):
            rows = db_evaluated.get_all(limit=1, suche=a["name"])
            lead = rows[0] if rows else None
        if not lead:
            return "Lead nicht gefunden — gib id oder name an."
        eid = lead["id"]
        done = []
        st = a.get("status")
        if st in ("neu", "kontaktiert", "termin", "verkauft", "tot"):
            db_evaluated.update_status(eid, st)
            done.append(f"Status={st}")
        if (a.get("notiz") or "").strip():
            db_evaluated.set_notiz(eid, a["notiz"].strip())
            done.append("Notiz gespeichert")
        if a.get("verkauft_euro") is not None:
            try:
                db_evaluated.set_verkauft_euro(eid, int(a["verkauft_euro"]))
                done.append(f"Umsatz={int(a['verkauft_euro'])}€")
            except (TypeError, ValueError):
                pass
        return (f"Aktualisiert: {lead.get('name')} ({lead.get('stadt','')}) — "
                + (", ".join(done) or "nichts geändert (status/notiz/umsatz fehlt)"))

    if name == "leads_conversion_stats":
        import db_evaluated, json as _j
        return _j.dumps(db_evaluated.get_conversion_stats(), ensure_ascii=False, indent=2)

    if name == "enrich_business":
        import agent_enrich
        return agent_enrich.enrich(a.get("name", ""), a.get("stadt", ""), a.get("branche", ""))

    if name.startswith("shop_"):
        import agent_shop
        if name == "shop_skill":  return agent_shop.skill()
        if name == "shop_new":    return agent_shop.shop_new(a.get("name", ""))
        if name == "shop_list":   return agent_shop.fs_list(a.get("path", ""))
        if name == "shop_read":   return agent_shop.fs_read(a.get("path", ""))
        if name == "shop_write":  return agent_shop.fs_write(a.get("path", ""), a.get("content", ""))
        if name == "shop_git":    return agent_shop.git_push(a.get("name", ""), a.get("repo_url", ""),
                                                             a.get("message", "Initiales Shop-Projekt"))

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
