"""
railway_cleanup.py — Railway-Services im Sammel-Projekt aufräumen (Keep-Liste).

Löscht ALLE Services im Railway-Projekt „Generated Websites" AUSSER den angegebenen
(Keep-Liste). Gedacht, wenn sich zu viele Demo-Seiten angesammelt haben und Railway das
Service-/Guthaben-Limit erreicht — dann bauen neue Deploys nicht mehr (Symptom: Seiten
werden gebaut, gehen aber nie live).

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
    found = R._find_project_with_env(tok, R.PROJECT_NAME)
    if not found.get("found"):
        _p(f"Railway-Projekt '{R.PROJECT_NAME}' nicht gefunden.")
        return 1

    svcs = _list_services(tok, found["project_id"])
    if not svcs:
        _p("Keine Services im Projekt (oder Liste nicht lesbar).")
        return 0
    delete = [s for s in svcs if s["name"] not in keep]
    keepers = [s for s in svcs if s["name"] in keep]

    _p(f"\nProjekt '{R.PROJECT_NAME}': {len(svcs)} Services")
    _p(f"BEHALTEN ({len(keepers)}): " + (", ".join(s['name'] for s in keepers) or "—"))
    _p(f"{'LOESCHE' if do_it else 'TROCKENLAUF - wuerde loeschen'} ({len(delete)}):")
    for s in delete:
        _p(f"   - {s['name']}")

    if not do_it:
        _p("\n-> Wirklich loeschen:  python railway_cleanup.py "
           + " ".join(f'--keep {k}' for k in keep) + " --yes")
        return 0

    ok = fail = 0
    for s in delete:
        d = R._gql("mutation($id:String!){ serviceDelete(id:$id) }", {"id": s["id"]}, tok)
        if d.get("ok"):
            ok += 1
        else:
            fail += 1
            _p(f"   [FAIL] {s['name']}: {str(d.get('error',''))[:80]}")
        time.sleep(0.3)
    rest = _list_services(tok, found["project_id"])
    _p(f"\nFertig. Geloescht: {ok} | Fehlgeschlagen: {fail} | Verbleibend: {len(rest)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
