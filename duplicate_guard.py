"""
duplicate_guard.py — Prüft ob ein Lead bereits als Webseite bearbeitet wurde.

Vier Prüfquellen (schnell → langsam):
  1. db_websites  — site_key bereits in der lokalen Webseiten-DB vorhanden
  2. Lokal        — Ordner in JARVIS_SHOP_DIR/jarvis_websites/ enthält Slug-Treffer
  3. GitHub       — Repo 'web-<slug>' existiert bereits (nur wenn GITHUB_TOKEN gesetzt)
  4. Railway      — Projekt mit Slug-Name existiert (nur wenn RAILWAY_TOKEN gesetzt)

API-Checks (3+4) nur vor dem echten Bau (check_apis=True).
Lokale Checks (1+2) für _pick_next_lead() (check_apis=False, schnell).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import logger

_SHOP_BASE = Path(os.environ.get("JARVIS_SHOP_DIR", str(Path.home() / "Desktop")))


def _slug(text: str) -> str:
    text = (text or "").lower().strip()
    for a, b in {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "&": "und"}.items():
        text = text.replace(a, b)
    return (re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "kunde")[:40]


# ── 1. DB-Check ────────────────────────────────────────────────────────────────

def _check_db(lead: dict) -> tuple[bool, str]:
    """Prüft ob der site_key des Leads schon in db_websites ist."""
    try:
        import db_websites
        from leadkey import lead_key as _lk
        sk = _lk((lead.get("name") or "").strip(), lead.get("stadt", ""))
        if not sk:
            return False, ""
        # Gezielter Existenz-Check statt Full-Table-Scan (get_all) je Lead.
        if db_websites.has_site_key(sk):
            return True, f"site_key '{sk}' bereits in db_websites"
    except Exception:
        pass
    return False, ""


# ── 2. Ordner-Check ────────────────────────────────────────────────────────────

def _check_folder(lead: dict) -> tuple[bool, str]:
    """Prüft ob ein lokaler Website-Ordner für diesen Lead bereits existiert."""
    slug = _slug((lead.get("name") or "").strip())
    if not slug or slug == "kunde":
        return False, ""
    websites_root = _SHOP_BASE / "jarvis_websites"
    if not websites_root.exists():
        return False, ""
    for day_dir in websites_root.iterdir():
        if not day_dir.is_dir():
            continue
        for folder in day_dir.iterdir():
            if folder.is_dir() and slug in folder.name.lower():
                return True, f"Lokaler Ordner vorhanden: {folder.name}"
    return False, ""


# ── 3. GitHub-Check ────────────────────────────────────────────────────────────

def _check_github(lead: dict) -> tuple[bool, str]:
    """Prüft ob ein GitHub-Repo 'web-<slug>' bereits existiert."""
    try:
        token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
        owner = (os.environ.get("GITHUB_USER") or "").strip()
        if not token or not owner:
            return False, ""
        import requests
        slug = _slug((lead.get("name") or "").strip())
        repo_name = f"web-{slug}"
        r = requests.get(
            f"https://api.github.com/repos/{owner}/{repo_name}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10,
        )
        if r.status_code == 200:
            return True, f"GitHub-Repo bereits vorhanden: {owner}/{repo_name}"
    except Exception:
        pass
    return False, ""


# ── 4. Railway-Check ───────────────────────────────────────────────────────────

def _check_railway(lead: dict) -> tuple[bool, str]:
    """Prüft ob ein Railway-Projekt mit dem Slug-Namen bereits existiert."""
    try:
        import agent_railway
        if not agent_railway.is_ready():
            return False, ""
        slug = _slug((lead.get("name") or "").strip())
        service_name = f"web-{slug}"
        r = agent_railway.list_projects()
        if not r.get("ok"):
            return False, ""
        for proj in (r.get("projects") or []):
            proj_name = (proj.get("name") or "").lower()
            if service_name.lower() in proj_name or slug in proj_name:
                return True, f"Railway-Projekt bereits vorhanden: {proj.get('name')}"
    except Exception:
        pass
    return False, ""


# ── Haupt-API ──────────────────────────────────────────────────────────────────

def is_already_built(lead: dict, check_apis: bool = True) -> tuple[bool, str]:
    """Prüft alle vier Quellen und gibt (bereits_gebaut, grund) zurück.

    check_apis=False → nur lokale Checks (schnell, für _pick_next_lead).
    check_apis=True  → inkl. GitHub + Railway (einmalig vor dem echten Bau).
    """
    ok, reason = _check_db(lead)
    if ok:
        return True, reason

    ok, reason = _check_folder(lead)
    if ok:
        return True, reason

    if not check_apis:
        return False, ""

    ok, reason = _check_github(lead)
    if ok:
        return True, reason

    ok, reason = _check_railway(lead)
    if ok:
        return True, reason

    return False, ""


def mark_archived(lead: dict, reason: str = "bereits bearbeitet") -> None:
    """Setzt einen Lead in db_evaluated auf 'Archiviert' mit 0 € Erwartungswert.
    Wird aufgerufen wenn is_already_built True zurückgibt — verhindert Doppelarbeit."""
    try:
        import db_evaluated
        # Suche per lead_key (kann auch name+stadt sein)
        from leadkey import lead_key as _lk
        name  = (lead.get("name") or "").strip()
        stadt = (lead.get("stadt") or "").strip()
        lk    = _lk(name, stadt)
        row   = None
        if lead.get("id"):
            row = db_evaluated.get_by_id(int(lead["id"]))
        if row is None and lk:
            # Fallback: alle Leads durchsuchen (selten nötig)
            for r in db_evaluated.get_all(limit=1000):
                if r.get("lead_key") == lk:
                    row = r
                    break
        if row:
            db_evaluated.archive_lead(int(row["id"]), reason[:300])
            logger.info("DuplicateGuard",
                        f"Lead '{name}' als Archiviert markiert: {reason[:80]}")
    except Exception as e:
        logger.warn("DuplicateGuard", f"Archivierung fehlgeschlagen: {type(e).__name__}")
