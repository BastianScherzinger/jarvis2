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


def get(job_id: str) -> "dict | None":
    with _lock:
        j = _jobs.get(job_id)
        return {k: v for k, v in j.items() if not k.startswith("_")} if j else None


def build(lead: dict) -> str:
    """Startet einen Bau-Job für einen Lead. Gibt die job_id zurück."""
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {
            "id": job_id, "status": "queued", "progress": 0, "step": "In Warteschlange…",
            "folder": "", "repo_url": "", "live_url": "", "error": "",
            "created": time.time(), "_lead": dict(lead or {}),
        }
    threading.Thread(target=_run, args=(job_id,), name=f"website-{job_id}", daemon=True).start()
    return job_id


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


def _download_photos(urls: list, target: Path) -> list:
    """Lädt bis zu 6 Fotos nach static/img/lead/ und gibt /static/-Pfade zurück."""
    import urllib.request
    out: list[str] = []
    dest = target / "static" / "img" / "lead"
    dest.mkdir(parents=True, exist_ok=True)
    for i, url in enumerate(urls[:6]):
        url = (url or "").strip()
        if not url.startswith("http"):
            continue
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
        "akzent": akz, "fotos": fotos,
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
        lead = dict(_jobs[job_id].get("_lead") or {})
    name = (lead.get("name") or "Kunde").strip()
    try:
        if not _VORLAGE.exists():
            raise RuntimeError("vorlage_landing/ fehlt im Projekt.")

        # 1) Vorlage kopieren -------------------------------------------------
        _set(job_id, status="running", progress=8, step="Vorlage wird kopiert…")
        slug = _slug(name)
        target = _unique_dir(slug)
        shutil.copytree(_VORLAGE, target, ignore=shutil.ignore_patterns(
            "staticfiles", "__pycache__", "*.pyc", ".git"))
        _set(job_id, folder=str(target))

        # 2) Fotos laden ------------------------------------------------------
        _set(job_id, progress=24, step="Gefundene Fotos werden eingebaut…")
        raw_fotos = lead.get("foto_urls") or []
        if isinstance(raw_fotos, str):
            try:
                raw_fotos = json.loads(raw_fotos)
            except Exception:
                raw_fotos = [raw_fotos] if raw_fotos.startswith("http") else []
        fotos = _download_photos(list(raw_fotos), target)

        # 3) Claude textet + designt -----------------------------------------
        _set(job_id, progress=44, step="Claude textet & gestaltet die Seite…")
        content = _claude_content(lead, fotos)
        (target / "content.json").write_text(
            json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
        _set(job_id, progress=54, step="Seite geschrieben.")

        secret = _django_secret_key()
        repo_full = ""
        repo_url = ""
        live_url = ""

        # 4) GitHub -----------------------------------------------------------
        import agent_github
        if agent_github.is_ready():
            _set(job_id, progress=64, step="GitHub-Repo wird erstellt & gepusht…")
            repo_name = f"web-{slug}"
            cr = agent_github.create_repo(
                repo_name, description=f"Landing-Page für {name} (JARVIS)", private=True)
            if cr.get("ok"):
                repo_full = cr["full_name"]
                pr = agent_github.push_folder(target, repo_full,
                                              message=f"Landing-Page {name} (JARVIS)")
                if pr.get("ok"):
                    repo_url = cr["html_url"]
                    _set(job_id, repo_url=repo_url, step="Repo gepusht.")
                else:
                    _set(job_id, step=f"Push-Hinweis: {pr.get('error','')[:120]}")
            else:
                _set(job_id, step=f"GitHub-Hinweis: {cr.get('error','')[:120]}")

        # 5) Railway ----------------------------------------------------------
        import agent_railway
        if agent_railway.is_ready() and repo_full:
            _set(job_id, progress=82, step="Railway-Deploy läuft (Projekt, Domain, Variablen)…")
            env = {
                "SECRET_KEY": secret, "DEBUG": "False",
                "SITE_NAME": content.get("site_name", name),
            }
            dep = agent_railway.deploy(f"web-{slug}", repo_full, env)
            if dep.get("ok") and dep.get("url"):
                live_url = dep["url"]
                _set(job_id, live_url=live_url)
            elif not dep.get("ok"):
                _set(job_id, step=f"Railway-Hinweis: {dep.get('error','')[:140]}")
        elif agent_railway.is_ready() and not repo_full:
            _set(job_id, step="Railway übersprungen (kein GitHub-Repo).")

        # Abschluss -----------------------------------------------------------
        if live_url:
            final_step = f"Fertig & live: {live_url}"
        elif repo_url:
            final_step = "Fertig. Repo gepusht — Railway-Deploy per Token aktivierbar."
        else:
            final_step = f"Lokal gebaut: {target}"
        _set(job_id, status="done", progress=100, step=final_step,
             content_preview=content.get("headline", ""))
    except Exception as e:
        _set(job_id, status="error", progress=100,
             error=f"{type(e).__name__}: {str(e)[:200]}", step="Fehlgeschlagen.")
