"""
railway_cleanup.py — Railway-Services in ALLEN rotierten Sammel-Projekten aufräumen
(Keep-Liste).

Löscht ALLE Services in „Generated Websites" UND seinen rotierten Folgeprojekten
(„Generated Websites 2", „… 3", …, siehe agent_railway._target_project_name/Rotation)
AUSSER den angegebenen (Keep-Liste). Gedacht, wenn sich zu viele Demo-Seiten angesammelt
haben und ein Sammel-Projekt das Service-/Guthaben-Limit erreicht — dann bauen neue
Deploys in DIESEM Projekt nicht mehr (Symptom: Seiten werden gebaut, gehen aber nie live).
Seit der automatischen Projekt-Rotation (02.07.2026) rotiert deploy() zwar selbst in ein
neues Projekt statt zu blockieren, aber altes Aufräumen bleibt sinnvoll (Guthaben, Übersicht).

Arbeitet DIREKT über die Railway-API (unabhängig von der lokalen Webseiten-DB) — deshalb
erfasst es auch Services, die auf einem ANDEREN PC gebaut und nur zu Railway gepusht wurden.

Benutzung (im Projektordner):
    python railway_cleanup.py                                  # Trockenlauf: nur anzeigen
    python railway_cleanup.py --keep web-... --keep wvm-it     # mehrere behalten
    python railway_cleanup.py --keep web-... --yes             # wirklich löschen

Der Service-Name folgt dem Schema web-<slug> (bzw. „wvm-it" für die eigene Firmenseite).
"""
from __future__ import annotations

import sys
import time

import config  # noqa: F401 — lädt .env in os.environ
import agent_railway as R


def _keep_from_args(argv: list[str]) -> set[str]:
    keep: set[str] = set()
    for i, a in enumerate(argv):
        if a == "--keep" and i + 1 < len(argv):
            keep.add(argv[i + 1].strip())
        elif a.startswith("--keep="):
            keep.add(a.split("=", 1)[1].strip())
    return {k for k in keep if k}


def _list_services(tok: str, project_id: str) -> list[dict]:
    q = "query($id:String!){ project(id:$id){ services{ edges{ node{ id name } } } } }"
    r = R._gql(q, {"id": project_id}, tok)
    if not r["ok"]:
        return []
    return [e["node"] for e in (((r["data"].get("project") or {}).get("services") or {}).get("edges") or [])]


def main() -> int:
    do_it = "--yes" in sys.argv or "-y" in sys.argv
    keep = _keep_from_args(sys.argv)

    def _p(s: str) -> None:
        try:
            print(s)
        except Exception:
            print(s.encode("ascii", "replace").decode("ascii"))

    tok = R._token()
    if not tok:
        _p("RAILWAY_TOKEN fehlt in der .env.")
        return 1
    projects = R.all_generated_projects(tok)
    if not projects:
        _p(f"Kein Railway-Projekt '{R.PROJECT_NAME}*' gefunden.")
        return 1

    total_ok = total_fail = total_kept = 0
    for proj in projects:
        svcs = _list_services(tok, proj["id"])
        if not svcs:
            _p(f"\nProjekt '{proj['name']}': keine Services (oder Liste nicht lesbar).")
            continue
        delete = [s for s in svcs if s["name"] not in keep]
        keepers = [s for s in svcs if s["name"] in keep]
        total_kept += len(keepers)

        _p(f"\nProjekt '{proj['name']}': {len(svcs)} Services")
        _p(f"BEHALTEN ({len(keepers)}): " + (", ".join(s['name'] for s in keepers) or "—"))
        _p(f"{'LOESCHE' if do_it else 'TROCKENLAUF - wuerde loeschen'} ({len(delete)}):")
        for s in delete:
            _p(f"   - {s['name']}")

        if not do_it:
            continue

        for s in delete:
            d = R._gql("mutation($id:String!){ serviceDelete(id:$id) }", {"id": s["id"]}, tok)
            if d.get("ok"):
                total_ok += 1
            else:
                total_fail += 1
                _p(f"   [FAIL] {s['name']}: {str(d.get('error',''))[:80]}")
            time.sleep(0.3)

    if not do_it:
        _p("\n-> Wirklich loeschen:  python railway_cleanup.py "
           + " ".join(f'--keep {k}' for k in keep) + " --yes")
        return 0

    _p(f"\nFertig ({len(projects)} Projekt(e)). "
       f"Geloescht: {total_ok} | Fehlgeschlagen: {total_fail} | Behalten: {total_kept}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
