"""
cleanup_websites.py — löscht ALLE bisher erstellten Webseiten endgültig (Neuanfang).

Entfernt für JEDE Seite in der Webseiten-DB:
  • GitHub-Repo (web-<slug>)         — agent_github.delete_repo
  • Railway-Service (web-<slug>)     — agent_railway.service_delete_by_name
  • lokalen Ordner (nur sichere web_-Ordner)
  • DB-Zeile (db_websites)
  • Cloud-Eintrag (Supabase, best-effort)

Die zugehörigen LEADS werden NICHT archiviert (Default) — so baut der Night-Builder die besten
Leads frisch mit der neuen Pipeline neu (Hero-Vorlagen, 5 lokale Stufen, Claude-Schliff). Mit
`--archive-leads` werden sie stattdessen als erledigt markiert (kein Neubau).

Benutzung (im Projektordner):
    python cleanup_websites.py            # zeigt, was gelöscht würde (Trockenlauf)
    python cleanup_websites.py --yes      # wirklich löschen
    python cleanup_websites.py --yes --archive-leads
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import config  # noqa: F401 — lädt .env in os.environ


def _slug(text: str) -> str:
    import re
    text = (text or "").lower().strip()
    for a, b in {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "&": "und"}.items():
        text = text.replace(a, b)
    return (re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "kunde")[:40]


def _repo_full(row: dict) -> str:
    repo = (row.get("repo_url") or "").strip()
    if repo and "github.com/" in repo:
        return repo.split("github.com/", 1)[-1].strip("/").removesuffix(".git")
    # Kein Repo-Link gespeichert → aus dem Namen ableiten (web-<slug>), Owner aus .env.
    import os
    owner = (os.environ.get("GITHUB_USER") or "").strip()
    name = (row.get("name") or "").strip()
    if owner and name:
        return f"{owner}/web-{_slug(name)}"
    return ""


def _teardown_remote(row: dict) -> list:
    report = []
    full = _repo_full(row)
    if full and "/" in full:
        try:
            import agent_github
            gr = agent_github.delete_repo(full)
            report.append("GitHub ok" if gr.get("ok") else f"GitHub: {str(gr.get('error',''))[:50]}")
        except Exception as e:
            report.append(f"GitHub-Fehler: {type(e).__name__}")
    svc = f"web-{_slug(row.get('name',''))}"
    try:
        import agent_railway
        rr = agent_railway.service_delete_by_name(svc)
        report.append("Railway ok" if rr.get("ok") else f"Railway: {str(rr.get('error',''))[:50]}")
    except Exception as e:
        report.append(f"Railway-Fehler: {type(e).__name__}")
    return report


def _delete_local(row: dict) -> list:
    report = []
    folder = (row.get("folder") or "").strip()
    if folder:
        try:
            p = Path(folder).resolve()
            if p.is_dir() and p.name.lower().startswith("web"):
                try:
                    import website_builder
                    website_builder._clear_readonly(str(p))  # git-Objekte sind read-only unter Windows
                except Exception:
                    pass
                shutil.rmtree(p, ignore_errors=True)
                report.append("Ordner ok")
        except Exception as e:
            report.append(f"Ordner-Fehler: {type(e).__name__}")
    try:
        import cloud_sync_websites
        cloud_sync_websites.delete_remote(row.get("name", ""), row.get("stadt", ""))
    except Exception:
        pass
    try:
        import db_websites
        db_websites.delete(row["id"])
        report.append("DB ok")
    except Exception as e:
        report.append(f"DB-Fehler: {type(e).__name__}")
    return report


def _archive_lead(row: dict) -> None:
    try:
        import db_evaluated
        lid = row.get("lead_id")
        name = (row.get("name") or "").strip()
        target = None
        if lid:
            cand = db_evaluated.get_by_id(int(lid))
            if cand and (cand.get("name") or "").strip().lower() == name.lower():
                target = cand
        if target is None and name:
            from leadkey import lead_key
            lk = lead_key(name, row.get("stadt", ""))
            for r in db_evaluated.get_all(limit=5000):
                if (lk and r.get("lead_key") == lk) or (r.get("name") or "").strip().lower() == name.lower():
                    target = r
                    break
        if target:
            db_evaluated.archive_lead(int(target["id"]), "Cleanup — Altseite gelöscht")
    except Exception:
        pass


def main() -> int:
    do_it = "--yes" in sys.argv or "-y" in sys.argv
    archive = "--archive-leads" in sys.argv
    try:
        import db_websites
        rows = db_websites.get_all(include_archived=True)
    except Exception:
        try:
            import db_websites
            rows = db_websites.get_all()
        except Exception as e:
            print(f"DB nicht lesbar: {e}")
            return 1

    if not rows:
        print("Keine Webseiten in der DB — nichts zu löschen.")
        return 0

    # Windows-Konsole ist oft cp1252 → ASCII-sichere Ausgabe (keine Sonderzeichen, die crashen).
    def _p(s: str) -> None:
        try:
            print(s)
        except Exception:
            print(s.encode("ascii", "replace").decode("ascii"))

    _p(f"\n{'LOESCHE' if do_it else 'TROCKENLAUF - wuerde loeschen'}: {len(rows)} Webseite(n)\n")
    for row in rows:
        name = (row.get("name") or "?").strip()
        if not do_it:
            _p(f"  - {name}  ({row.get('folder','') or 'kein Ordner'})")
            continue
        rep = _teardown_remote(row) + _delete_local(row)
        if archive:
            _archive_lead(row)
            rep.append("Lead archiviert")
        _p(f"  - {name}: {', '.join(rep)}")

    if not do_it:
        _p("\n-> Wirklich loeschen:  python cleanup_websites.py --yes")
        _p("   (Leads bleiben baubar; mit --archive-leads werden sie als erledigt markiert.)")
    else:
        _p(f"\nFertig. {len(rows)} Seite(n) entfernt. "
           + ("Leads archiviert." if archive else "Leads bleiben baubar - Night-Builder baut neu."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
