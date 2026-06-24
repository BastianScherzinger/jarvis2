"""
website_builder.py — baut aus einem Lead automatisch eine Landing-Page und bringt sie live.

Ablauf (eigener Hintergrund-Job, unabhängig von der Medien-Queue):
  1. Vorlage vorlage_landing/ → neuer Kundenordner auf dem Desktop.
  2. Gefundene Lead-Fotos herunterladen und in static/img/lead/ einbauen.
  3. Claude textet + designt die Seite (Skill-Wissen) → content.json.
  4. Optional GitHub: Repo anlegen + pushen (wenn GITHUB_TOKEN gesetzt).
  5. Optional Railway: Projekt + Domain + Env-Variablen (wenn RAILWAY_TOKEN gesetzt).

Jobs sind über get(job_id) pollbar (gleiche Form wie media_queue: status/progress/…).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

_jobs: dict[str, dict] = {}
_lock = threading.Lock()

_BASE = Path(__file__).parent
_VORLAGE = _BASE / "vorlage_landing"
_SHOP_BASE = Path(os.environ.get("JARVIS_SHOP_DIR", str(Path.home() / "Desktop")))

MODEL = os.environ.get("JARVIS_CLAUDE_MODEL", "claude-opus-4-8")

# Mindest-Guthaben (Higgsfield-Credits) für einen Cloud-Hero. Überschreibbar via .env,
# da die echten Soul-Kosten je nach Qualität variieren.
_HF_HERO_COST = int(os.environ.get("JARVIS_HF_HERO_COST", "1") or "1")

# Hartes Zeitlimit für den lokalen Hero-Render. Auf der CPU kann sd-turbo hängen
# bleiben (kam vor → Job blieb ewig bei 60 %). Reißt der Render das Limit, wird er
# aufgegeben und die Seite nutzt den Farbverlauf-Hero — der Build steht NIE still.
_HERO_TIMEOUT = int(os.environ.get("JARVIS_HERO_TIMEOUT", "180") or "180")

_AKZENT = {  # Branchen-Heuristik für die Akzentfarbe (Claude darf überschreiben)
    "dachdecker": "#b23a23", "maler": "#1f6f54", "elektr": "#d98a00",
    "sanitär": "#1565a6", "heizung": "#c0392b", "garten": "#2e7d32",
    "kfz": "#37474f", "auto": "#37474f", "friseur": "#a83279",
    "bau": "#6d4c2b", "tischler": "#7a4a23", "schreiner": "#7a4a23",
    "gastro": "#a3361f", "restaurant": "#a3361f", "reinigung": "#0d8a8a",
}


def is_available() -> bool:
    return _VORLAGE.exists()


# ── Job-Registry ──────────────────────────────────────────────────────────────

def _set(job_id: str, **fields) -> None:
    with _lock:
        j = _jobs.get(job_id)
        if j is not None:
            j.update(fields)
    _persist(job_id)


def get(job_id: str) -> "dict | None":
    with _lock:
        j = _jobs.get(job_id)
        return {k: v for k, v in j.items() if not k.startswith("_")} if j else None


def _persist(job_id: str) -> None:
    """Spiegelt den aktuellen Job-Stand in die persistente DB (db_websites), damit
    der 'Webseiten'-Reiter ihn auch nach Wegklicken/Neustart zeigt. Persistenz-
    Fehler dürfen den Bau NIE stoppen. WICHTIG: außerhalb von `with _lock` aufrufen
    (get() nimmt selbst das Lock — threading.Lock ist nicht reentrant)."""
    try:
        job = get(job_id)
        if not job:
            return
        import db_websites
        db_websites.update(
            job_id,
            status=job.get("status", ""),
            progress=int(job.get("progress", 0) or 0),
            step=job.get("step", ""),
            folder=job.get("folder", ""),
            repo_url=job.get("repo_url", ""),
            live_url=job.get("live_url", ""),
            live=int(job.get("live", 0) or 0),
            error=job.get("error", ""),
            log=job.get("log", []),
        )
    except Exception:
        pass


def _enrich_contact(job_id: str, lead: dict) -> None:
    """Sucht nach dem Bau aktiv die Kontakt-E-Mail (DDG→Impressum / Google Places),
    falls für die Zeile noch keine gespeichert ist. Best-effort — nie blockierend
    für den Bau-Erfolg. Persistiert kontakt_email + ansprechpartner."""
    try:
        import db_websites
        row = db_websites.get_by_job(job_id)
        if not row or (row.get("kontakt_email") or "").strip():
            return                       # schon vorhanden → nichts tun
        import contact_finder
        res = contact_finder.find(
            row.get("name") or lead.get("name", ""),
            row.get("stadt") or lead.get("stadt", ""),
            row.get("branche") or lead.get("branche", ""),
            known_url=(lead.get("website_url") or lead.get("discovered_website") or ""))
        if res.get("ok") and res.get("email"):
            db_websites.set_contact(int(row["id"]), res["email"], res.get("ansprechpartner", ""))
    except Exception:
        pass


def _sync_push(job_id: str) -> None:
    """Pusht die fertige Webseiten-Zeile nach Supabase (Cross-PC). Best-effort."""
    try:
        import cloud_sync_websites
        import db_websites
        row = db_websites.get_by_job(job_id)
        if row:
            cloud_sync_websites.push(row)
    except Exception:
        pass


def build(lead: dict, use_higgsfield: bool = False) -> str:
    """Startet einen Bau-Job für einen Lead. Gibt die job_id zurück.

    use_higgsfield: nur wenn True (vom Nutzer bestätigt) wird der Hero-Banner bei
    schwacher Hardware über die Higgsfield-Cloud versucht. Standard = lokal (bewährt)."""
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {
            "id": job_id, "status": "queued", "progress": 0, "step": "In Warteschlange…",
            "folder": "", "repo_url": "", "live_url": "", "error": "", "log": [],
            "created": time.time(), "_lead": dict(lead or {}),
            "_use_higgsfield": bool(use_higgsfield),
        }
    # Persistenten Eintrag anlegen (überlebt Wegklicken/Neustart) — Fehler ignorieren.
    try:
        import db_websites
        lead_id = lead.get("id") or lead.get("raw_id")
        kontakt = (lead.get("email") or lead.get("email_adresse")
                   or lead.get("email_alle") or "").strip()
        if kontakt.startswith("["):          # email_alle ist evtl. JSON-Liste
            try:
                arr = json.loads(kontakt)
                kontakt = (arr[0] if arr else "").strip()
            except Exception:
                kontakt = ""
        db_websites.create(
            job_id, name=(lead.get("name") or "").strip(),
            stadt=(lead.get("stadt") or "").strip(),
            branche=(lead.get("branche") or "").strip(),
            lead_id=int(lead_id) if lead_id else None,
            kontakt_email=kontakt if "@" in kontakt else "")
    except Exception:
        pass
    threading.Thread(target=_run, args=(job_id,), name=f"website-{job_id}", daemon=True).start()
    return job_id


def _step(job_id: str, progress: "int | None" = None, text: "str | None" = None) -> None:
    """Setzt Fortschritt (monoton, springt nie zurück) + Schritt-Text und hängt den
    Schritt an ein Log an — so sieht der Nutzer im Dashboard genau, was passiert."""
    with _lock:
        j = _jobs.get(job_id)
        if not j:
            return
        if progress is not None:
            j["progress"] = max(int(j.get("progress", 0)), int(progress))
        if text is not None:
            j["step"] = text
            log = j.setdefault("log", [])
            log.append({"p": j.get("progress", 0), "t": text})
            if len(log) > 50:
                del log[:-50]
    _persist(job_id)


# ── Helfer ────────────────────────────────────────────────────────────────────

def _slug(text: str) -> str:
    text = (text or "").lower().strip()
    repl = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "&": "und"}
    for a, b in repl.items():
        text = text.replace(a, b)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (text or "kunde")[:40]


def _day_dir() -> Path:
    """Tagesordner: <base>/jarvis_websites/<JJJJ-MM-TT>/ — Seiten werden pro Tag
    sortiert abgelegt."""
    d = _SHOP_BASE / "jarvis_websites" / time.strftime("%Y-%m-%d")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _unique_dir(slug: str) -> Path:
    day = _day_dir()
    base = day / f"web_{slug}"
    if not base.exists():
        return base
    for i in range(2, 50):
        cand = day / f"web_{slug}-{i}"
        if not cand.exists():
            return cand
    return day / f"web_{slug}-{uuid.uuid4().hex[:4]}"


def _download_photos(urls: list, target: Path, on_progress=None) -> list:
    """Lädt bis zu 6 Fotos nach static/img/lead/ und gibt /static/-Pfade zurück.
    on_progress(geladen, gesamt) wird nach jedem Foto aufgerufen (für die Anzeige)."""
    import urllib.request
    out: list[str] = []
    dest = target / "static" / "img" / "lead"
    dest.mkdir(parents=True, exist_ok=True)
    todo = [u for u in urls[:6] if (u or "").strip().startswith("http")]
    total = len(todo)
    for i, url in enumerate(todo):
        url = url.strip()
        if callable(on_progress):
            on_progress(i + 1, total)
        ext = ".jpg"
        for e in (".jpg", ".jpeg", ".png", ".webp"):
            if e in url.lower():
                ext = ".png" if e == ".png" else (".webp" if e == ".webp" else ".jpg")
                break
        fn = f"{i+1}{ext}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 JARVIS"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read(8_000_000)  # max 8 MB
            if len(data) < 1200:             # zu klein → vermutlich Platzhalter
                continue
            (dest / fn).write_bytes(data)
            out.append(f"/static/img/lead/{fn}")
        except Exception:
            continue
    return out


def _deterministic_content(lead: dict, fotos: list) -> dict:
    name = (lead.get("name") or "Ihr Betrieb").strip()
    branche = (lead.get("branche") or "Handwerk").strip()
    stadt = (lead.get("stadt") or "").strip()
    akz = "#c8102e"
    low = branche.lower()
    for k, v in _AKZENT.items():
        if k in low:
            akz = v
            break
    return {
        "site_name": name, "branche": branche, "stadt": stadt,
        "telefon": (lead.get("telefon") or "").strip(),
        "email": (lead.get("email") or lead.get("email_adresse") or "").strip(),
        "adresse": (lead.get("adresse") or "").strip(),
        "akzent": akz, "fotos": fotos, "hero_image": "",
        "headline": f"{branche} aus {stadt}".strip(" aus") if stadt else f"Ihr {branche}-Betrieb",
        "subline": "Qualität aus Ihrer Region — zuverlässig, sauber und termintreu.",
        "ueber_titel": "Über uns",
        "ueber_text": f"{name} ist Ihr verlässlicher Partner für {branche}"
                      + (f" in {stadt}" if stadt else "") + ". Persönlich, gründlich und termintreu.",
        "leistungen": [
            {"titel": "Beratung", "text": "Persönlich und auf Ihr Projekt zugeschnitten."},
            {"titel": "Ausführung", "text": "Saubere, termintreue Arbeit mit Liebe zum Detail."},
            {"titel": "Service", "text": "Auch nach Abschluss für Sie da."},
        ],
        "cta_text": "Jetzt unverbindlich anfragen",
        "seo_title": f"{name}" + (f" — {branche} {stadt}" if stadt else ""),
        "seo_desc": f"{branche} aus {stadt}. ".strip() + "Jetzt anfragen.",
        "jahr": time.localtime().tm_year,
    }


def _extract_json(text: str) -> "dict | None":
    """Holt das erste balancierte JSON-Objekt aus einem Text."""
    s = text.find("{")
    if s < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(s, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[s:i + 1])
                    except Exception:
                        return None
    return None


def _ollama_content(lead: dict, base: dict) -> bool:
    """Erzeugt die Landing-Page-Texte LOKAL via Ollama (qwen2.5) — spart Claude-API-Kosten,
    nutzt die 32-GB-Maschine. Merged direkt in `base`. Gibt True bei Erfolg (Kernfelder
    gesetzt), sonst False → Aufrufer nutzt Claude-API/Deterministik."""
    try:
        from scrapers._http import ask_ollama
    except Exception:
        return False
    beschr = (lead.get("beschreibung") or "").strip()
    beschr_block = f"- Beschreibung vom Inhaber (verbindlich): {beschr}\n" if beschr else ""
    sys = ("Du bist Senior-Webdesigner & Texter (design-pro). Seriöse, conversion-starke "
           "Landing-Page-Texte für einen lokalen Betrieb — deutsch, konkret, kein Fülltext. "
           "Antworte AUSSCHLIESSLICH mit einem JSON-Objekt.")
    prompt = (
        f"Betrieb:\n- Name: {lead.get('name','')}\n- Branche: {lead.get('branche','')}\n"
        f"- Stadt: {lead.get('stadt','')}\n- Bewertung: {lead.get('bewertung','')}\n{beschr_block}\n"
        "Erzeuge JSON mit GENAU diesen Feldern:\n{\n"
        '  "headline": "starke Hero-Headline (max 7 Wörter)",\n'
        '  "subline": "1 Satz Nutzenversprechen",\n'
        '  "ueber_titel": "kurze Überschrift",\n'
        '  "ueber_text": "2-3 Sätze über den Betrieb, vertrauenswürdig",\n'
        '  "leistungen": [{"titel":"…","text":"…"} (3-4 zur Branche passende)],\n'
        '  "cta_text": "konkreter Call-to-Action",\n'
        '  "akzent": "#RRGGBB passend zur Branche",\n'
        '  "seo_title": "Titel-Tag", "seo_desc": "Meta-Description (max 150 Zeichen)"\n}\n'
        "Nur das JSON."
    )
    try:
        text = ask_ollama(prompt, system=sys, timeout=120)
    except Exception:
        return False
    data = _extract_json(text or "")
    if not isinstance(data, dict):
        return False
    for k in ("headline", "subline", "ueber_titel", "ueber_text", "cta_text",
              "akzent", "seo_title", "seo_desc"):
        if isinstance(data.get(k), str) and data[k].strip():
            base[k] = data[k].strip()
    if isinstance(data.get("leistungen"), list) and data["leistungen"]:
        clean = [{"titel": str(x.get("titel", "")).strip(), "text": str(x.get("text", "")).strip()}
                 for x in data["leistungen"][:4] if isinstance(x, dict) and x.get("titel")]
        if clean:
            base["leistungen"] = clean
    if re.fullmatch(r"#[0-9a-fA-F]{6}", base.get("akzent", "")) is None:
        base["akzent"] = _deterministic_content(lead, fotos=[])["akzent"]
    # Erfolg nur, wenn die Kernfelder wirklich befüllt wurden.
    return bool(base.get("headline") and base.get("ueber_text") and base.get("leistungen"))


def _claude_content(lead: dict, fotos: list) -> dict:
    """Texte + Akzentfarbe. Reihenfolge: LOKAL (Ollama, spart API-Kosten) → Claude-API →
    Deterministik. Per JARVIS_BUILD_CONTENT_LOCAL=0 wird Ollama übersprungen."""
    base = _deterministic_content(lead, fotos)
    # 1) Lokal via Ollama zuerst (Kostenersparnis, nutzt die 32-GB-Maschine).
    if os.environ.get("JARVIS_BUILD_CONTENT_LOCAL", "1") != "0":
        try:
            if _ollama_content(lead, base):
                return base
        except Exception:
            pass
    # 2) Claude-API als Fallback (oder wenn lokal deaktiviert/leer).
    try:
        import anthropic
        import config
        key = config.get_api_key()
        if not key:
            return base
        client = anthropic.Anthropic(api_key=key)
        sys = (
            "Du bist ein Senior-Webdesigner & Texter (design-pro). Du schreibst die Inhalte "
            "für eine seriöse, conversion-starke Landing-Page eines lokalen Betriebs — kein "
            "KI-Geschwurbel, kein Fülltext, deutsch, konkret und vertrauenswürdig. "
            "Antworte AUSSCHLIESSLICH mit einem JSON-Objekt."
        )
        beschr = (lead.get("beschreibung") or "").strip()
        beschr_block = f"- Beschreibung vom Inhaber (verbindlich nutzen): {beschr}\n" if beschr else ""
        prompt = (
            "Betrieb:\n"
            f"- Name: {lead.get('name','')}\n"
            f"- Branche: {lead.get('branche','')}\n"
            f"- Stadt: {lead.get('stadt','')}\n"
            f"- Bewertung: {lead.get('bewertung','')}\n"
            f"{beschr_block}\n"
            "Erzeuge JSON mit GENAU diesen Feldern:\n"
            "{\n"
            '  "headline": "starke, kurze Hero-Headline (max 7 Wörter)",\n'
            '  "subline": "1 Satz Nutzenversprechen",\n'
            '  "ueber_titel": "kurze Überschrift",\n'
            '  "ueber_text": "2-3 Sätze über den Betrieb, vertrauenswürdig",\n'
            '  "leistungen": [{"titel":"…","text":"…"}, …  (3-4 zur Branche passende Leistungen)],\n'
            '  "cta_text": "konkreter Call-to-Action",\n'
            '  "akzent": "#RRGGBB passend zur Branche",\n'
            '  "seo_title": "Titel-Tag", "seo_desc": "Meta-Description (max 150 Zeichen)"\n'
            "}\n"
            "Nur das JSON, sonst nichts."
        )
        msg = client.messages.create(
            model=MODEL, max_tokens=1400, system=sys,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            import cost_tracker
            cost_tracker.track_message(MODEL, msg, "website_build", lead.get("name", ""))
        except Exception:
            pass
        text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
        data = _extract_json(text)
        if isinstance(data, dict):
            for k in ("headline", "subline", "ueber_titel", "ueber_text", "cta_text",
                      "akzent", "seo_title", "seo_desc"):
                if isinstance(data.get(k), str) and data[k].strip():
                    base[k] = data[k].strip()
            if isinstance(data.get("leistungen"), list) and data["leistungen"]:
                clean = [{"titel": str(x.get("titel", "")).strip(),
                          "text": str(x.get("text", "")).strip()}
                         for x in data["leistungen"][:4]
                         if isinstance(x, dict) and x.get("titel")]
                if clean:
                    base["leistungen"] = clean
            if re.fullmatch(r"#[0-9a-fA-F]{6}", base.get("akzent", "")) is None:
                base["akzent"] = _deterministic_content(lead, fotos)["akzent"]
    except Exception:
        return base
    return base


def _generate_hero_local_timed(media_engine, prompt: str, out_dir: Path,
                               params: dict, timeout: int) -> bool:
    """Erzeugt das Hero-Bild lokal mit hartem Zeitlimit. Hängt der CPU-Render,
    wird er (als Daemon) aufgegeben und es wird False zurückgegeben — der Build
    läuft dann mit Farbverlauf-Hero weiter statt ewig bei 60 % zu stehen."""
    done = {"ok": False}

    def _work() -> None:
        try:
            media_engine.generate_image(prompt, output_dir=out_dir,
                                        filename="hero.png", **params)
            done["ok"] = True
        except Exception:
            done["ok"] = False

    t = threading.Thread(target=_work, name="hero-render", daemon=True)
    t.start()
    t.join(timeout)
    return (not t.is_alive()) and done["ok"]


def _django_secret_key() -> str:
    try:
        from django.core.management.utils import get_random_secret_key
        return get_random_secret_key()
    except Exception:
        import secrets
        import string
        alpha = string.ascii_letters + string.digits + "!@#$%^&*(-_=+)"
        return "".join(secrets.choice(alpha) for _ in range(50))


# ── Deploy (GitHub + Railway) — geteilt von _run und deploy_existing ──────────

def _url_live(url: str, on_tick=None, timeout: int = 180) -> bool:
    """Pollt eine URL, bis sie wirklich antwortet (Status < 500). Railway erzeugt
    die Domain sofort, der Container-Build dauert aber 1-2 Min — erst danach ist die
    Seite erreichbar. Gibt True, sobald sie antwortet, sonst False nach timeout."""
    import urllib.error
    import urllib.request
    if not url:
        return False
    start = time.time()
    versuch = 0
    while time.time() - start < timeout:
        versuch += 1
        try:
            req = urllib.request.Request(url, method="GET",
                                         headers={"User-Agent": "JARVIS-LiveCheck"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status < 500:
                    return True
        except urllib.error.HTTPError as e:
            if e.code < 500:          # 200/301/302/404 = App läuft (antwortet)
                return True
        except Exception:
            pass                       # 502/503/Timeout/Reset → Build noch nicht fertig
        if callable(on_tick):
            on_tick(f"Railway: Build läuft… ({int(time.time() - start)}s)")
        time.sleep(8)
    return False


def _deploy_folder(target: "Path", slug: str, name: str, secret: str,
                   site_name: str, say, redeploy_url: str = "", wait_live: bool = True) -> dict:
    """Legt ein GitHub-Repo an, pusht den Ordner und deployt auf Railway.
    say(progress|None, text) meldet jeden Schritt. Gibt
    {repo_full, repo_url, live_url, live_ok, railway_note, railway_log}.

    redeploy_url: ist die Seite schon einmal deployt (Live-URL bekannt), wird NUR
    gepusht — Railway baut bei git-push automatisch neu. So entstehen bei
    'verbessern'/'mit Claude' keine doppelten Railway-Services.
    wait_live: False = nach dem Push NICHT auf die Erreichbarkeit warten (für den
    schnellen Per-Stufe-Push im Makeover — Railway rebuildet im Hintergrund)."""
    import agent_github
    import agent_railway
    repo_full = repo_url = live_url = railway_note = ""
    railway_log: list = []
    live_ok = False

    # GitHub --------------------------------------------------------------
    if agent_github.is_ready():
        say(74, "GitHub-Repo wird angelegt…")
        # ÖFFENTLICH: (1) der Repo-Link funktioniert im Browser ohne Login,
        # (2) Railway kann ein öffentliches Repo zuverlässig klonen/bauen (ein
        # frisch per API erstelltes PRIVATES Repo ist für Railway oft nicht
        # sichtbar → Build scheitert, Domain liefert 502). Keine Geheimnisse im
        # Repo — SECRET_KEY kommt als Railway-Env-Variable.
        cr = agent_github.create_repo(
            f"web-{slug}", description=f"Landing-Page für {name} (JARVIS)", private=False)
        if cr.get("ok"):
            repo_full = cr["full_name"]
            say(78, f"Repo {repo_full} — Code wird hochgeladen…")
            pr = agent_github.push_folder(target, repo_full,
                                          message=f"Landing-Page {name} (JARVIS)")
            if pr.get("ok"):
                repo_url = cr["html_url"]
                say(83, "Code zu GitHub gepusht ✓")
            else:
                railway_note = pr.get("error", "")[:200]
                say(83, f"Push-Hinweis: {railway_note[:120]}")
        else:
            railway_note = cr.get("error", "")[:200]
            say(83, f"GitHub-Hinweis: {railway_note[:120]}")
    else:
        railway_note = "GITHUB_TOKEN fehlt in der .env."
        say(83, "GitHub übersprungen (kein GITHUB_TOKEN in .env).")

    # Re-Deploy: Seite existiert schon → nur Push, Railway baut automatisch neu.
    if redeploy_url and repo_full:
        live_url = redeploy_url
        if not wait_live:
            # Schneller Per-Stufe-Push: nur pushen, Railway rebuildet im Hintergrund.
            say(None, "Stufe live-gepusht — Railway rebuildet im Hintergrund.")
            _deploy_activity(site_name or name, live_url, True)
            return {"repo_full": repo_full, "repo_url": repo_url, "live_url": live_url,
                    "live_ok": True, "railway_note": "", "railway_log": railway_log}
        say(90, "Push löst Railway-Rebuild aus — warte auf Erreichbarkeit (bis 3 Min)…")
        if _url_live(redeploy_url, lambda s: say(None, s), timeout=180):
            live_ok = True
            say(98, f"Live erreichbar: {live_url}")
        else:
            railway_note = (f"Rebuild läuft ({redeploy_url}) — in 1-2 Min erneut öffnen. "
                            "Falls dauerhaft 502: Railway-Build-Log prüfen.")
            say(96, "Rebuild läuft — noch nicht erreichbar.")
        _deploy_activity(site_name or name, live_url, live_ok)
        return {"repo_full": repo_full, "repo_url": repo_url, "live_url": live_url,
                "live_ok": live_ok, "railway_note": railway_note, "railway_log": railway_log}

    # Railway -------------------------------------------------------------
    if agent_railway.is_ready() and repo_full:
        say(85, "Railway-Deploy startet…")
        env = {"SECRET_KEY": secret, "DEBUG": "False", "SITE_NAME": site_name}
        dep = agent_railway.deploy(f"web-{slug}", repo_full, env,
                                   on_step=lambda t: say(None, f"Railway: {t}"))
        railway_log = dep.get("log", [])
        if dep.get("ok") and dep.get("url"):
            domain_url = dep["url"]
            # Domain existiert sofort — der Container-Build dauert aber 1-2 Min.
            # Erst als 'live' melden, wenn die Seite WIRKLICH antwortet.
            say(90, "Railway baut den Container — warte auf Erreichbarkeit (bis 3 Min)…")
            live_url = domain_url       # Link immer mitgeben (Build kann noch laufen)
            if _url_live(domain_url, lambda s: say(None, s), timeout=180):
                live_ok = True
                say(98, f"Live erreichbar: {live_url}")
            else:
                # Domain da, aber Build nicht erreichbar → ehrlich melden + echten Grund.
                railway_note = (
                    f"Domain steht ({domain_url}), aber der Build ist nach 3 Min noch "
                    "nicht erreichbar. Häufigste Ursachen: (1) Build läuft noch — in "
                    "1-2 Min nochmal öffnen; (2) Railway ist nicht mit GitHub verbunden "
                    "(railway.app → Account → GitHub verbinden); (3) Build-Fehler im "
                    "Railway-Dashboard prüfen.")
                say(96, "Domain erstellt — Build noch nicht erreichbar (siehe Hinweis).")
        else:
            railway_note = dep.get("error") or "; ".join(dep.get("log", [])[-1:]) or railway_note
            say(96, f"Railway-Hinweis: {str(railway_note)[:120]}")
    elif agent_railway.is_ready() and not repo_full:
        railway_note = railway_note or "Kein GitHub-Repo — Railway übersprungen."
        say(96, str(railway_note)[:120])
    elif not agent_railway.is_ready():
        railway_note = railway_note or "RAILWAY_TOKEN fehlt in der .env."
        say(96, "Railway übersprungen (kein RAILWAY_TOKEN in .env).")

    _deploy_activity(site_name or name, live_url, live_ok)
    return {"repo_full": repo_full, "repo_url": repo_url, "live_url": live_url,
            "live_ok": live_ok, "railway_note": railway_note, "railway_log": railway_log}


def _deploy_activity(name: str, live_url: str, live_ok: bool) -> None:
    """Schreibt einen Deploy-Eintrag in den Aktivitäts-Feed (Home/Kosten-Tab).
    Nur wenn überhaupt eine Domain entstand. Silent."""
    if not live_url:
        return
    try:
        import logger
        logger.activity(
            "WebsiteBuilder",
            "Webseite live" if live_ok else "Deploy angestoßen",
            f"{name} · {live_url}", "🚀", "deploy",
        )
    except Exception:
        pass


# ── Worker ────────────────────────────────────────────────────────────────────

def _apply_custom_assets(target: Path, content: dict, lead: dict) -> None:
    """Custom-Modus: vom Inhaber gelieferte Assets übernehmen.
      - logo_path  → static/img/logo.png  (+ content['logo_image'])
      - hero_path  → static/img/hero.png  (Generierung wird dann übersprungen)
    Best-effort, wirft nie — fehlende/ungültige Pfade werden ignoriert."""
    custom = lead.get("_custom") or {}
    img_dir = target / "static" / "img"
    try:
        img_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return
    logo = (custom.get("logo_path") or "").strip()
    if logo and os.path.isfile(logo):
        try:
            shutil.copyfile(logo, img_dir / "logo.png")
            content["logo_image"] = "/static/img/logo.png"
        except Exception:
            pass
    hero = (custom.get("hero_path") or "").strip()
    if hero and os.path.isfile(hero):
        try:
            shutil.copyfile(hero, img_dir / "hero.png")
            content["hero_image"] = "/static/img/hero.png"
        except Exception:
            pass


def _run(job_id: str) -> None:
    with _lock:
        j0 = _jobs[job_id]
        lead = dict(j0.get("_lead") or {})
        use_hf = bool(j0.get("_use_higgsfield"))
    name = (lead.get("name") or "Kunde").strip()
    try:
        if not _VORLAGE.exists():
            raise RuntimeError("vorlage_landing/ fehlt im Projekt.")

        # 1) Vorlage kopieren -------------------------------------------------
        _set(job_id, status="running")
        _step(job_id, 3, f"Projekt für {name} wird angelegt…")
        slug = _slug(name)
        target = _unique_dir(slug)
        shutil.copytree(_VORLAGE, target, ignore=shutil.ignore_patterns(
            "staticfiles", "__pycache__", "*.pyc", ".git"))
        _set(job_id, folder=str(target))
        _step(job_id, 8, f"Vorlage kopiert → {target.name}")

        # 2) Fotos laden ------------------------------------------------------
        raw_fotos = lead.get("foto_urls") or []
        if isinstance(raw_fotos, str):
            try:
                raw_fotos = json.loads(raw_fotos)
            except Exception:
                raw_fotos = [raw_fotos] if raw_fotos.startswith("http") else []
        anz_fotos = len([u for u in list(raw_fotos)[:6] if (u or '').strip().startswith('http')])
        if anz_fotos:
            _step(job_id, 12, f"Lade {anz_fotos} gefundene Fotos…")
        else:
            _step(job_id, 12, "Keine Fotos gefunden — Hero-Banner wird generiert.")

        def _foto_fortschritt(geladen, gesamt):
            p = 12 + int((geladen / max(gesamt, 1)) * 18)   # 12 → 30
            _step(job_id, p, f"Foto {geladen}/{gesamt} eingebaut…")
        fotos = _download_photos(list(raw_fotos), target, on_progress=_foto_fortschritt)
        _step(job_id, 32, f"{len(fotos)} Foto(s) eingebaut.")

        # 3) Claude textet + designt -----------------------------------------
        _step(job_id, 38, "Claude schreibt Texte & wählt das Design…")
        content = _claude_content(lead, fotos)
        # Custom-Modus: vom Inhaber gelieferte Kontaktdaten direkt übernehmen.
        for k in ("telefon", "email", "adresse"):
            if (lead.get(k) or "").strip():
                content[k] = str(lead[k]).strip()
        _apply_custom_assets(target, content, lead)      # Logo + ggf. hochgeladenes Hero
        (target / "content.json").write_text(
            json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
        _step(job_id, 56, f"Texte & Design erstellt: {content.get('headline','')[:40]}")

        # 3b) Hero-Banner. STANDARD: Cloud-Engine über JARVIS_HERO_ENGINE (Default Higgsfield
        # = Sirs Abo; OpenAI nur wenn explizit gewählt, kostet extra). Fällt auf lokal
        # (GPU=SDXL/FLUX, CPU=SD-Turbo) und zuletzt auf einen Farbverlauf zurück. Best-effort —
        # jeder Fehler fällt auf die nächste Option zurück, der Build bricht NIE ab.
        try:
            import media_engine  # lazy
            hero_path = target / "static" / "img" / "hero.png"
            branche = lead.get("branche", "")
            # Custom-Modus: eigener Hero-Prompt schlägt den Standard; ein hochgeladenes
            # Hero (von _apply_custom_assets bereits als hero.png abgelegt) existiert hier
            # schon → die Generierung wird automatisch übersprungen.
            custom_prompt = (lead.get("_custom") or {}).get("hero_prompt", "").strip()
            # Präziser, lead-angepasster Master-Prompt (Claude/Ollama plant → Bild-KI baut).
            master_prompt = custom_prompt or media_engine.hero_prompt_smart(
                branche=branche, name=lead.get("name", ""), stadt=lead.get("stadt", ""),
                beschreibung=(content.get("ueber_text") or content.get("beschreibung")
                              or lead.get("beschreibung", "")),
                akzent=content.get("akzent", ""), leistungen=content.get("leistungen"))
            # Knapper Prompt für die lokale Diffusers-Generierung (Fallback).
            prompt = custom_prompt or (
                f"professional wide hero banner photograph for a German {branche} "
                "business, modern, clean, bright daylight, high quality, no text, "
                "no logo, no watermark"
            )
            schwach = media_engine.hardware_info()["device"] == "cpu"  # keine GPU → lokal langsam

            # 0) Cloud-Hero über die konfigurierte Engine (Default Higgsfield = Abo).
            if not hero_path.exists():
                try:
                    _step(job_id, 60, f"Hero-Banner wird erzeugt ({media_engine.hero_engine()})…")
                    res = media_engine.generate_hero_cloud(
                        master_prompt, output_dir=(target / "static" / "img"),
                        filename="hero.png", width=1536, height=1024, name=lead.get("name", ""))
                    content["hero_source"] = res.get("engine", "")
                except Exception as e:
                    _step(job_id, 60, f"Cloud-Hero nicht möglich ({type(e).__name__}) — Fallback lokal…")

            # 2) Lokal (Fallback ODER starke Hardware), falls noch kein Hero da
            if not hero_path.exists() and media_engine.get_status().get("diffusers_ok"):
                hp = media_engine.hero_image_params()
                modell = hp.get("model_key", "lokal")
                tempo = f" (max {_HERO_TIMEOUT}s, sonst Farbverlauf)" if schwach else ""
                _step(job_id, 60, f"Hero-Banner wird lokal erzeugt ({modell}){tempo}…")
                ok = _generate_hero_local_timed(
                    media_engine, prompt, (target / "static" / "img"), hp, _HERO_TIMEOUT)
                if not ok and not hero_path.exists():
                    _step(job_id, 68, "Hero-Render zu langsam — Seite nutzt einen Farbverlauf.")

            if hero_path.exists():
                content["hero_image"] = "/static/img/hero.png"
                (target / "content.json").write_text(
                    json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
                _step(job_id, 70, "Hero-Banner fertig.")
            else:
                _step(job_id, 70, "Ohne Hero-Bild — Seite nutzt einen Farbverlauf.")
        except Exception:
            content.setdefault("hero_image", "")
            _step(job_id, 70, "Hero-Banner übersprungen.")

        # 3c) Referenz-Platzhalter: leere Bild-Slots (Hero/Über-uns/Galerie) mit
        # branchengetönten SVG-Platzhaltern füllen, damit die Seite NIE leer/unfertig
        # wirkt, falls keine echte Bildquelle verfügbar war. Echte Bilder bleiben.
        try:
            import ref_images
            content = ref_images.ensure_placeholders(target, content, branche)
            (target / "content.json").write_text(
                json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
            if content.get("placeholder_images"):
                _step(job_id, 72, "Referenzbilder als Platzhalter eingebaut (Seite vollständig).")
        except Exception:
            pass

        secret = _django_secret_key()

        # 4+5) GitHub + Railway — gemeinsame Logik (auch von deploy_existing genutzt)
        def _say(p: "int | None", t: str) -> None:
            if p is None:                       # Railway-Substep → Fortschritt leicht anheben
                with _lock:
                    j = _jobs.get(job_id)
                    cur = (j.get("progress", 85) if j else 85)
                _step(job_id, min(cur + 2, 96), t)
            else:
                _step(job_id, p, t)

        dep = _deploy_folder(target, slug, name, secret, content.get("site_name", name), _say)
        repo_url     = dep["repo_url"]
        live_url     = dep["live_url"]
        live_ok      = bool(dep.get("live_ok"))
        railway_note = dep["railway_note"]
        if dep.get("railway_log"):
            _set(job_id, railway_log=dep["railway_log"])
        if repo_url:
            _set(job_id, repo_url=repo_url)
        _set(job_id, live_url=live_url, live=1 if live_ok else 0)

        # Abschluss — ehrlicher Status (deployt & erreichbar vs. Build offen) -
        if live_ok and live_url:
            final_step = f"Fertig & live: {live_url}"
        elif live_url:
            final_step = f"Deploy läuft — Build noch nicht erreichbar. Domain: {live_url}"
        elif repo_url:
            final_step = "Repo gepusht — " + (f"Railway: {railway_note[:120]}" if railway_note
                                              else "Railway-Deploy angestoßen.")
        else:
            final_step = f"Lokal gebaut: {target}"
        _set(job_id, status="done", content_preview=content.get("headline", ""))
        _step(job_id, 100, final_step)
        _enrich_contact(job_id, lead)        # Kontaktadresse aktiv suchen (best-effort)
        _sync_push(job_id)
    except Exception as e:
        import traceback
        _set(job_id, status="error", error=f"{type(e).__name__}: {str(e)[:200]}")
        _step(job_id, 100, f"Fehlgeschlagen: {type(e).__name__}")
        try:
            import logger
            logger.error("Webseite", f"✕ Bau abgebrochen: {type(e).__name__}: {str(e)[:180]}")
            logger.error("Webseite", "Traceback: " + traceback.format_exc().strip().replace("\n", " | ")[-500:])
        except Exception:
            pass


# ── Bereits gebaute Seiten finden + nachträglich deployen ─────────────────────

def find_built_sites() -> list[dict]:
    """Findet bereits gebaute Landing-Ordner (web_*) unter JARVIS_SHOP_DIR.
    Gibt je Ordner {folder, name, slug, live_url} (live_url falls schon deployt)."""
    out: list[dict] = []
    base = _SHOP_BASE
    if not base.exists():
        return out
    # bereits bekannte Live-URLs aus der DB (Ordner → live_url)
    bekannt: dict = {}
    try:
        import db_websites
        for w in db_websites.get_all():
            if w.get("folder"):
                bekannt[w["folder"]] = w.get("live_url") or bekannt.get(w["folder"], "")
    except Exception:
        pass
    # Alte flache Ablage (base/web_*) + neue Tagesordner (base/jarvis_websites/<tag>/web_*)
    kandidaten = list(base.glob("web_*"))
    nested = base / "jarvis_websites"
    if nested.exists():
        kandidaten += list(nested.glob("*/web_*"))
    for d in sorted(set(kandidaten)):
        if not d.is_dir():
            continue
        if not (d / "content.json").exists() and not (d / "manage.py").exists():
            continue
        name = d.name
        try:
            c = json.loads((d / "content.json").read_text(encoding="utf-8"))
            name = (c.get("site_name") or name).strip()
        except Exception:
            pass
        out.append({"folder": str(d), "name": name, "slug": d.name,
                    "live_url": bekannt.get(str(d), "")})
    return out


def _run_deploy(job_id: str, folder: str, name: str) -> None:
    try:
        target = Path(folder)
        if not target.is_dir():
            raise RuntimeError("Ordner nicht gefunden.")
        content = {}
        try:
            content = json.loads((target / "content.json").read_text(encoding="utf-8"))
        except Exception:
            pass
        _set(job_id, status="running", folder=str(target))
        _step(job_id, 70, f"Deploy für {name} startet…")
        slug = _slug(name)

        def _say(p, t):
            if p is None:
                with _lock:
                    j = _jobs.get(job_id)
                    cur = (j.get("progress", 85) if j else 85)
                _step(job_id, min(cur + 2, 96), t)
            else:
                _step(job_id, p, t)

        prev = get(job_id) or {}
        dep = _deploy_folder(target, slug, name, _django_secret_key(),
                             content.get("site_name", name), _say,
                             redeploy_url=prev.get("live_url", ""))
        if dep.get("railway_log"):
            _set(job_id, railway_log=dep["railway_log"])
        if dep["repo_url"]:
            _set(job_id, repo_url=dep["repo_url"])
        _set(job_id, live_url=dep["live_url"], live=1 if dep.get("live_ok") else 0)
        if dep.get("live_ok") and dep["live_url"]:
            final = f"Fertig & live: {dep['live_url']}"
        elif dep["live_url"]:
            final = f"Deploy läuft — Build noch nicht erreichbar. Domain: {dep['live_url']}"
        elif dep["repo_url"]:
            final = "Repo gepusht — " + (f"Railway: {str(dep['railway_note'])[:120]}"
                                         if dep["railway_note"] else "Railway-Deploy angestoßen.")
        else:
            final = f"Deploy nicht möglich: {str(dep['railway_note'])[:160]}"
        _set(job_id, status="done")
        _step(job_id, 100, final)
        _sync_push(job_id)
    except Exception as e:
        import traceback
        _set(job_id, status="error", error=f"{type(e).__name__}: {str(e)[:200]}")
        _step(job_id, 100, f"Fehlgeschlagen: {type(e).__name__}")
        try:
            import logger
            logger.error("Webseite", f"✕ Job '{name}' abgebrochen: {type(e).__name__}: {str(e)[:180]}")
            logger.error("Webseite", "Traceback: " + traceback.format_exc().strip().replace("\n", " | ")[-500:])
        except Exception:
            pass


def _folder_name(folder: Path, name: "str | None") -> str:
    if name:
        return name
    try:
        c = json.loads((folder / "content.json").read_text(encoding="utf-8"))
        if (c.get("site_name") or "").strip():
            return c["site_name"].strip()
    except Exception:
        pass
    return folder.name.replace("web_", "").replace("-", " ").strip() or "Webseite"


def _start_folder_job(folder: str, name: str, runner, first_step: str) -> str:
    """Startet einen Hintergrund-Job für einen vorhandenen Ordner. Existiert für den
    Ordner schon eine Webseiten-Zeile, wird DEREN job_id wiederverwendet (die Karte
    aktualisiert sich an Ort und Stelle, statt zu duplizieren)."""
    folder = str(folder)
    job_id = ""
    stadt = branche = ""
    seed_repo = seed_live = ""
    seed_liveflag = 0
    try:
        import db_websites
        row = db_websites.get_by_folder(folder)
        if row:
            job_id = row.get("job_id") or ""
            stadt, branche = row.get("stadt", ""), row.get("branche", "")
            # Vorhandene Live-/Repo-URL übernehmen → _persist überschreibt sie nicht
            # mit leer, und der Runner erkennt ein Re-Deploy (nur Push statt neuer Service).
            seed_repo, seed_live = row.get("repo_url", ""), row.get("live_url", "")
            seed_liveflag = int(row.get("live", 0) or 0)
    except Exception:
        pass
    if not job_id:
        job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {
            "id": job_id, "status": "queued", "progress": 0, "step": first_step,
            "folder": folder, "repo_url": seed_repo, "live_url": seed_live, "live": seed_liveflag,
            "error": "", "log": [], "created": time.time(), "_lead": {"name": name},
        }
    try:
        import db_websites
        if not db_websites.get_by_job(job_id):
            db_websites.create(job_id, name=name, stadt=stadt, branche=branche, lead_id=None)
        db_websites.update(job_id, folder=folder, status="queued", error="")
    except Exception:
        pass
    threading.Thread(target=runner, args=(job_id, folder, name),
                     name=f"job-{job_id}", daemon=True).start()
    return job_id


def deploy_existing(folder: str, name: "str | None" = None) -> str:
    """Deployt einen BEREITS gebauten Seiten-Ordner zu GitHub + Railway (ohne neu
    zu bauen). Verfolgbar im Webseiten-Reiter. Gibt die job_id zurück."""
    target = Path(folder)
    nm = _folder_name(target, name)
    return _start_folder_job(str(target), nm, _run_deploy, "Deploy in Warteschlange…")


def improve_existing(folder: str, name: "str | None" = None) -> str:
    """'Top verbessern': 5-Agenten-Pipeline (Design/Texte/Bilder/Struktur/QA) +
    Re-Deploy. Verfolgbar im Webseiten-Reiter. Gibt die job_id zurück."""
    target = Path(folder)
    nm = _folder_name(target, name)
    return _start_folder_job(str(target), nm, _run_improve, "Verbesserung in Warteschlange…")


def _run_improve(job_id: str, folder: str, name: str) -> None:
    try:
        target = Path(folder)
        if not target.is_dir():
            raise RuntimeError("Ordner nicht gefunden.")
        _set(job_id, status="running", folder=str(target), live=0)
        _step(job_id, 5, f"Top-Verbesserung für {name} startet…")
        lead = {"name": name}
        existing_live = ""
        try:
            import db_websites
            row = db_websites.get_by_job(job_id) or db_websites.get_by_folder(str(target))
            if row:
                lead = {"name": row.get("name") or name, "stadt": row.get("stadt", ""),
                        "branche": row.get("branche", "")}
                existing_live = (row.get("live_url") or "").strip()
        except Exception:
            pass

        import website_improve
        content = website_improve.enrich(target, lead, lambda p, t: _step(job_id, p, t))

        # Re-Deploy der verbesserten Seite
        slug = _slug(name)

        def _say(p, t):
            if p is None:
                with _lock:
                    j = _jobs.get(job_id)
                    cur = (j.get("progress", 95) if j else 95)
                _step(job_id, min(cur + 1, 99), t)
            else:
                _step(job_id, max(p, 95), t)   # nach der Verbesserung nie zurückspringen

        prev = get(job_id) or {}
        dep = _deploy_folder(target, slug, name, _django_secret_key(),
                             content.get("site_name", name), _say,
                             redeploy_url=(prev.get("live_url") or existing_live))
        if dep.get("railway_log"):
            _set(job_id, railway_log=dep["railway_log"])
        if dep["repo_url"]:
            _set(job_id, repo_url=dep["repo_url"])
        _set(job_id, live_url=dep["live_url"], live=1 if dep.get("live_ok") else 0)
        if dep.get("live_ok") and dep["live_url"]:
            final = f"Verbessert & live: {dep['live_url']}"
        elif dep["live_url"]:
            final = f"Verbessert — Build läuft noch. Domain: {dep['live_url']}"
        elif dep["repo_url"]:
            final = "Verbessert & gepusht — " + (f"Railway: {str(dep['railway_note'])[:120]}"
                                                 if dep["railway_note"] else "Deploy angestoßen.")
        else:
            final = "Verbessert (lokal). Deploy nicht möglich: " + str(dep.get("railway_note", ""))[:140]
        _set(job_id, status="done")
        _step(job_id, 100, final)
        _sync_push(job_id)
    except Exception as e:
        import traceback
        _set(job_id, status="error", error=f"{type(e).__name__}: {str(e)[:200]}")
        _step(job_id, 100, f"Fehlgeschlagen: {type(e).__name__}")
        try:
            import logger
            logger.error("Webseite", f"✕ Job '{name}' abgebrochen: {type(e).__name__}: {str(e)[:180]}")
            logger.error("Webseite", "Traceback: " + traceback.format_exc().strip().replace("\n", " | ")[-500:])
        except Exception:
            pass


def makeover_existing(folder: str, name: "str | None" = None, stop=None) -> str:
    """Mehrstufiges Skill-Makeover (7 Stufen, design-pro/taste/frontend-design) für eine
    bereits gebaute Seite: Commit je Stufe, Deploy am Ende, Discord-Freigabe wenn komplett.
    stop(): optionaler Callback — gibt er True zurück, hält die Pipeline ZWISCHEN den Stufen
    an (für den stoppbaren Night-Builder). Verfolgbar im Webseiten-Reiter. Gibt die job_id zurück."""
    target = Path(folder)
    nm = _folder_name(target, name)
    runner = (_run_makeover if stop is None
              else (lambda jid, f, n: _run_makeover(jid, f, n, stop=stop)))
    return _start_folder_job(str(target), nm, runner, "Makeover in Warteschlange…")


def _run_makeover(job_id: str, folder: str, name: str, stop=None) -> None:
    try:
        target = Path(folder)
        if not target.is_dir():
            raise RuntimeError("Ordner nicht gefunden.")
        _set(job_id, status="running", folder=str(target), live=0)
        _step(job_id, 4, f"Makeover für {name} startet…")

        meta = {"name": name}
        existing_live = ""
        try:
            import db_websites
            row = db_websites.get_by_job(job_id) or db_websites.get_by_folder(str(target))
            if row:
                meta = {"name": row.get("name") or name, "stadt": row.get("stadt", ""),
                        "branche": row.get("branche", ""),
                        "email": row.get("kontakt_email", ""),
                        "ansprechpartner": row.get("ansprechpartner", "")}
                existing_live = (row.get("live_url") or "").strip()
        except Exception:
            pass

        import overnight_makeover

        # Per-Stufe-Push: jede fertige Skill-Stufe sofort live deployen („pushen jeweils").
        # So geht jeder Skill einzeln live; bremst eine spätere Stufe (Abo-Rate-Limit), sind
        # die fertigen Stufen schon deployt — die Seite hängt nicht mehr unsichtbar bei „Stufe 1".
        slug_ps = _slug(name)
        secret_ps = _django_secret_key()
        site_name_ps = overnight_makeover._read_content(target).get("site_name") or name

        def _stage_push(key: str, label: str, n_done: int) -> None:
            live = (get(job_id) or {}).get("live_url") or existing_live
            if not live:
                return                       # noch keine Live-URL (Repo/Deploy fehlt) → später
            cur = (get(job_id) or {}).get("progress", 8)
            _step(job_id, cur, f"Stufe '{label}' fertig → live pushen…")
            dep = _deploy_folder(
                target, slug_ps, name, secret_ps, site_name_ps,
                lambda p, t: _step(job_id, p if p is not None else (get(job_id) or {}).get("progress", 8), t),
                redeploy_url=live, wait_live=False)
            if dep.get("repo_url"):
                _set(job_id, repo_url=dep["repo_url"])
            if dep.get("live_url"):
                _set(job_id, live_url=dep["live_url"], live=1)
            _sync_push(job_id)

        result = overnight_makeover.run_makeover(
            target, meta, say=lambda p, t: _step(job_id, p, t), stop=stop,
            on_stage_done=_stage_push)

        # Nichts Neues gebaut (alle Stufen bereits erledigt oder CLI fehlt) → kein Re-Deploy.
        if not result.get("stages_done"):
            _set(job_id, status="done")
            reason = result.get("reason") or "Alle Makeover-Stufen bereits erledigt."
            _step(job_id, 100, reason)
            return

        # Vom Nutzer gestoppt, bevor alle Stufen durch waren → nicht deployen, Fortschritt
        # ist committet und wird beim Fortsetzen genau hier weitergeführt.
        if stop and stop() and not result.get("all_done"):
            _set(job_id, status="done")
            _step(job_id, 100, "Makeover pausiert (gestoppt) — Fortschritt gesichert, fortsetzbar.")
            return

        # Deploy einmal am Ende — die Stufen-Commits werden mitgepusht.
        slug = _slug(name)

        def _say(p, t):
            if p is None:
                with _lock:
                    j = _jobs.get(job_id)
                    cur = (j.get("progress", 92) if j else 92)
                _step(job_id, min(cur + 1, 99), t)
            else:
                _step(job_id, max(p, 92), t)

        prev = get(job_id) or {}
        site_name = overnight_makeover._read_content(target).get("site_name") or name
        dep = _deploy_folder(target, slug, name, _django_secret_key(), site_name, _say,
                             redeploy_url=(prev.get("live_url") or existing_live))
        if dep.get("railway_log"):
            _set(job_id, railway_log=dep["railway_log"])
        if dep["repo_url"]:
            _set(job_id, repo_url=dep["repo_url"])
        _set(job_id, live_url=dep["live_url"], live=1 if dep.get("live_ok") else 0)
        live = dep.get("live_url") or existing_live

        # Discord-Freigabe NUR wenn alle 7 Stufen durch sind (1× 👍 = Mail, 1× 👎 = verwerfen).
        if result.get("all_done") and live:
            overnight_makeover.finalize_review(meta, live, str(target))
            final = f"Makeover komplett & zur Freigabe gepostet: {live}"
        elif dep.get("live_ok") and live:
            final = f"Makeover-Fortschritt live: {live}"
        elif live:
            final = f"Makeover gepusht — Build läuft. {live}"
        else:
            final = "Makeover lokal — Deploy nicht möglich: " + str(dep.get("railway_note", ""))[:120]
        _set(job_id, status="done")
        _step(job_id, 100, final)
        _sync_push(job_id)
    except Exception as e:
        import traceback
        _set(job_id, status="error", error=f"{type(e).__name__}: {str(e)[:200]}")
        _step(job_id, 100, f"Fehlgeschlagen: {type(e).__name__}")
        try:
            import logger
            logger.error("Webseite", f"✕ Job '{name}' abgebrochen: {type(e).__name__}: {str(e)[:180]}")
            logger.error("Webseite", "Traceback: " + traceback.format_exc().strip().replace("\n", " | ")[-500:])
        except Exception:
            pass


# ── Deploy-Bereitschaft (Diagnose für 'klappt nicht'-Fälle) ───────────────────

def deploy_status() -> dict:
    """Aggregierter Bereitschaftscheck für den Webseiten-Deploy."""
    import shutil
    import agent_github
    import agent_railway
    gh = agent_github.diagnose()
    rw = agent_railway.diagnose()
    git_ok = bool(shutil.which("git"))
    return {"ready": bool(gh.get("ok") and rw.get("ok") and git_ok),
            "git": git_ok, "github": gh, "railway": rw}


def deploy_status_text() -> str:
    """Menschlich lesbarer Deploy-Bereitschaftsbericht (für Claude-Tab + update.py).
    Bewusst ASCII-only — wird auch in der Kunden-Konsole (evtl. cp1252) gedruckt."""
    s = deploy_status()
    def _mark(ok): return "[OK]" if ok else "[!] "
    lines = [
        f"{_mark(s['github'].get('ok'))} GitHub:  {s['github'].get('msg','')}",
        f"{_mark(s['railway'].get('ok'))} Railway: {s['railway'].get('msg','')}",
        f"{_mark(s['git'])} Git:     " + ("installiert" if s["git"]
                                          else "NICHT installiert -> https://git-scm.com/download/win"),
    ]
    kopf = ("Deploy bereit - Webseiten koennen live gestellt werden."
            if s["ready"] else "Deploy NICHT bereit - Details unten:")
    return kopf + "\n" + "\n".join(lines)
