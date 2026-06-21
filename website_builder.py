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
            error=job.get("error", ""),
            log=job.get("log", []),
        )
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
        db_websites.create(
            job_id, name=(lead.get("name") or "").strip(),
            stadt=(lead.get("stadt") or "").strip(),
            branche=(lead.get("branche") or "").strip(),
            lead_id=int(lead_id) if lead_id else None)
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


def _unique_dir(slug: str) -> Path:
    base = _SHOP_BASE / f"web_{slug}"
    if not base.exists():
        return base
    for i in range(2, 50):
        cand = _SHOP_BASE / f"web_{slug}-{i}"
        if not cand.exists():
            return cand
    return _SHOP_BASE / f"web_{slug}-{uuid.uuid4().hex[:4]}"


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


def _claude_content(lead: dict, fotos: list) -> dict:
    """Claude textet + wählt Akzentfarbe (design-pro/Skill-Wissen). Fällt sicher zurück."""
    base = _deterministic_content(lead, fotos)
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
        prompt = (
            "Betrieb:\n"
            f"- Name: {lead.get('name','')}\n"
            f"- Branche: {lead.get('branche','')}\n"
            f"- Stadt: {lead.get('stadt','')}\n"
            f"- Bewertung: {lead.get('bewertung','')}\n\n"
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


# ── Worker ────────────────────────────────────────────────────────────────────

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
        (target / "content.json").write_text(
            json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
        _step(job_id, 56, f"Texte & Design erstellt: {content.get('headline','')[:40]}")

        # 3b) Hero-Banner. Higgsfield-Cloud NUR wenn der Nutzer es bestätigt hat
        # (use_higgsfield) UND die Hardware schwach ist UND Guthaben da ist; sonst lokal
        # (GPU=SDXL/FLUX, CPU=SD-Turbo). Best-effort — jeder Fehler fällt auf die nächste
        # Option zurück, der Build bricht NIE ab.
        try:
            import media_engine  # lazy
            hero_path = target / "static" / "img" / "hero.png"
            branche = lead.get("branche", "")
            prompt = (
                f"professional wide hero banner photograph for a German {branche} "
                "business, modern, clean, bright daylight, high quality, no text, "
                "no logo, no watermark"
            )
            schwach = media_engine.hardware_info()["device"] == "cpu"  # keine GPU → lokal langsam

            # 1) Cloud (Higgsfield) — nur auf ausdrücklichen Wunsch + schwache Hardware + Credits
            if use_hf and schwach and media_engine.higgsfield_available():
                bal = media_engine.higgsfield_balance()
                if bal is None or bal >= _HF_HERO_COST:
                    try:
                        _step(job_id, 60, "Hero-Banner wird über Higgsfield (Cloud) erzeugt…")
                        media_engine.generate_image_higgsfield(
                            prompt, output_dir=(target / "static" / "img"),
                            filename="hero.png", width=1280, height=720)
                    except Exception as e:
                        _step(job_id, 60, f"Higgsfield nicht möglich ({type(e).__name__}) — wechsle auf lokal…")
                else:
                    _step(job_id, 60, f"Higgsfield-Guthaben zu niedrig ({bal}) — nutze lokal…")

            # 2) Lokal (Standard, Fallback ODER starke Hardware), falls noch kein Hero da
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

        secret = _django_secret_key()
        repo_full = ""
        repo_url = ""
        live_url = ""

        # 4) GitHub -----------------------------------------------------------
        import agent_github
        if agent_github.is_ready():
            _step(job_id, 74, "GitHub-Repo wird angelegt…")
            repo_name = f"web-{slug}"
            cr = agent_github.create_repo(
                repo_name, description=f"Landing-Page für {name} (JARVIS)", private=True)
            if cr.get("ok"):
                repo_full = cr["full_name"]
                _step(job_id, 78, f"Repo {repo_full} — Code wird hochgeladen…")
                pr = agent_github.push_folder(target, repo_full,
                                              message=f"Landing-Page {name} (JARVIS)")
                if pr.get("ok"):
                    repo_url = cr["html_url"]
                    _set(job_id, repo_url=repo_url)
                    _step(job_id, 83, "Code zu GitHub gepusht ✓")
                else:
                    _step(job_id, 83, f"Push-Hinweis: {pr.get('error','')[:120]}")
            else:
                _step(job_id, 83, f"GitHub-Hinweis: {cr.get('error','')[:120]}")
        else:
            _step(job_id, 83, "GitHub übersprungen (kein Token in .env).")

        # 5) Railway ----------------------------------------------------------
        import agent_railway
        railway_note = ""
        if agent_railway.is_ready() and repo_full:
            _step(job_id, 85, "Railway-Deploy startet…")
            env = {
                "SECRET_KEY": secret, "DEBUG": "False",
                "SITE_NAME": content.get("site_name", name),
            }

            def _rw_step(text: str) -> None:
                with _lock:
                    j = _jobs.get(job_id)
                    cur = (j.get("progress", 85) if j else 85)
                _step(job_id, min(cur + 2, 96), f"Railway: {text}")

            dep = agent_railway.deploy(f"web-{slug}", repo_full, env, on_step=_rw_step)
            if dep.get("ok") and dep.get("url"):
                live_url = dep["url"]
                _set(job_id, live_url=live_url, railway_log=dep.get("log", []))
                _step(job_id, 98, f"Live erreichbar: {live_url}")
            else:
                railway_note = dep.get("error") or "; ".join(dep.get("log", [])[-1:])
                _set(job_id, railway_log=dep.get("log", []))
                _step(job_id, 96, f"Railway-Hinweis: {railway_note[:100]}")
        elif agent_railway.is_ready() and not repo_full:
            railway_note = "Kein GitHub-Repo — Railway übersprungen."
            _step(job_id, 96, railway_note)
        elif not agent_railway.is_ready():
            _step(job_id, 96, "Railway übersprungen (kein Token in .env).")

        # Abschluss -----------------------------------------------------------
        if live_url:
            final_step = f"Fertig & live: {live_url}"
        elif repo_url:
            final_step = "Fertig. Repo gepusht — " + (f"Railway: {railway_note[:120]}" if railway_note
                                                      else "Railway-Deploy angestoßen.")
        else:
            final_step = f"Fertig — lokal gebaut: {target}"
        _set(job_id, status="done", content_preview=content.get("headline", ""))
        _step(job_id, 100, final_step)
    except Exception as e:
        _set(job_id, status="error", error=f"{type(e).__name__}: {str(e)[:200]}")
        _step(job_id, 100, f"Fehlgeschlagen: {type(e).__name__}")
