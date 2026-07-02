"""
Railway-Client für den JARVIS-Website-Builder (GraphQL Public API).

Erstellt aus einem GitHub-Repo automatisch: Projekt → Service → öffentliche Domain →
Umgebungsvariablen (SECRET_KEY, DEBUG, ALLOWED_HOSTS, …) und stößt einen Deploy an.
Tokengesteuert aus der .env (RAILWAY_TOKEN). Token wird nie geloggt.

Hinweis: Damit Railway aus einem GitHub-Repo bauen kann, muss die Railway-GitHub-App
einmalig Zugriff auf den Account/das Repo haben (Standard-Einmal-Setup im Railway-UI).
Schlägt ein Schritt fehl, liefert deploy() einen ehrlichen Log statt zu crashen.
"""
from __future__ import annotations

import os
import re

import requests

import config  # noqa: F401 — lädt die .env in os.environ (sonst Token evtl. nicht sichtbar)

ENDPOINT = "https://backboard.railway.com/graphql/v2"

# Alle generierten Seiten landen als Services im Sammel-Projekt. Name via .env
# überschreibbar. Läuft EIN Sammel-Projekt voll (Railway-Service-/Guthabenlimit,
# Default 50), rotiert deploy() automatisch in ein nummeriertes Folgeprojekt
# ("<Name> 2", "<Name> 3", …) — siehe _target_project_name(). PROJECT_NAME bleibt
# der Basisname für Anzeige/Suche/Cleanup.
PROJECT_NAME = (os.environ.get("JARVIS_RAILWAY_PROJECT") or "Generated Websites").strip()


def _rotate_at() -> int:
    """Service-Zahl, ab der ein neues Folgeprojekt angelegt wird (Default 50, min. 5)."""
    try:
        return max(5, int(os.environ.get("JARVIS_RAILWAY_ROTATE_AT", "50") or "50"))
    except (ValueError, TypeError):
        return 50


def _project_name_for_suffix(suffix: int) -> str:
    return PROJECT_NAME if suffix <= 1 else f"{PROJECT_NAME} {suffix}"


def all_generated_projects(token: str) -> list[dict]:
    """Alle Sammel-Projekte dieser Rotation (Basis-Name + '<Name> 2', '<Name> 3', …),
    aufsteigend nach Suffix sortiert. Lebt komplett aus der Railway-API (kein lokaler
    State nötig) — funktioniert darum unverändert über mehrere PCs hinweg, die
    denselben Railway-Account nutzen."""
    lp = list_projects()
    if not lp.get("ok"):
        return []
    base = PROJECT_NAME.strip().lower()
    pat = re.compile(r"^" + re.escape(base) + r"(?: (\d+))?$")
    out = []
    for p in lp["projects"]:
        m = pat.match((p.get("name") or "").strip().lower())
        if m:
            suffix = int(m.group(1)) if m.group(1) else 1
            out.append({"id": p["id"], "name": p["name"], "suffix": suffix})
    out.sort(key=lambda x: x["suffix"])
    return out


def _target_project_name(token: str) -> str:
    """Wählt den Namen des aktuell aktiven Sammel-Projekts für den nächsten Deploy.
    Ist das JÜNGSTE bekannte Projekt bereits voll (>= _rotate_at() Services), wird
    der NÄCHSTE Name zurückgegeben — deploy()s bestehender find-or-create-Pfad legt
    ihn dann automatisch neu an. So blockiert ein volles Sammel-Projekt nie wieder
    neue Deploys (Ursache für „Seiten werden gebaut, gehen aber nie live")."""
    projects = all_generated_projects(token)
    if not projects:
        return PROJECT_NAME
    newest = projects[-1]
    try:
        n_svc = _service_count(token, newest["id"])
    except Exception:
        n_svc = -1
    if n_svc >= _rotate_at():
        return _project_name_for_suffix(newest["suffix"] + 1)
    return newest["name"]


def force_rotate(reason: str = "") -> dict:
    """Erzwingt SOFORT ein neues Sammel-Projekt für KOMMENDE Deploys, unabhängig vom
    Service-Zähler (_rotate_at()). Für den Live-Watcher: sieht er mehrere Seiten
    gleichzeitig offline (typisches Symptom eines vollen/blockierten Projekts — die
    historische Ursache für „Seiten werden gebaut, gehen aber nie live"), soll nicht
    erst der nächste normale Deploy zufällig auf die Rotation stoßen.

    Repariert NICHT die aktuell toten Seiten (die laufen weiter über den bestehenden
    Redeploy-Pfad in ihrem bisherigen Projekt) — legt nur das nächste, leere
    Sammel-Projekt an, damit NEUE Seiten dort landen. Da _target_project_name() das
    "jüngste" Projekt immer live über die Railway-API neu bestimmt (kein lokaler
    State), reicht das alleinige Anlegen — der nächste deploy() sieht es automatisch.

    Gibt {"ok": True, "project": name, "already": bool} oder {"ok": False, "error"}."""
    token = _token()
    if not token:
        return {"ok": False, "error": "RAILWAY_TOKEN fehlt in .env"}
    projects = all_generated_projects(token)
    next_suffix = (projects[-1]["suffix"] + 1) if projects else 1
    next_name = _project_name_for_suffix(next_suffix)
    # Bereits vorhanden (Race mit einem parallelen deploy(), oder schon rotiert)?
    found = _find_project_with_env(token, next_name)
    if found.get("found"):
        return {"ok": True, "project": next_name, "already": True}
    q_proj = """
    mutation($name:String!){ projectCreate(input:{name:$name}){
      id environments{edges{node{id name}}} } }"""
    r = _gql(q_proj, {"name": next_name[:60]}, token)
    if not r["ok"]:
        return {"ok": False, "error": f"projectCreate: {r['error']}"}
    try:
        import logger
        logger.warn("Railway", f"Erzwungene Rotation -> Projekt „{next_name}“ angelegt"
                                + (f" ({reason})" if reason else ""))
    except Exception:
        pass
    return {"ok": True, "project": next_name, "already": False}


def _token() -> str:
    return (os.environ.get("RAILWAY_TOKEN") or os.environ.get("RAILWAY_API_TOKEN") or "").strip()


def is_ready() -> bool:
    return bool(_token())


def _gql(query: str, variables: dict, token: str) -> dict:
    """Führt eine GraphQL-Anfrage aus. Gibt {ok, data|error}."""
    try:
        r = requests.post(
            ENDPOINT,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"query": query, "variables": variables},
            timeout=45,
        )
    except Exception as e:
        return {"ok": False, "error": f"Railway nicht erreichbar: {type(e).__name__}"}
    try:
        body = r.json()
    except Exception:
        return {"ok": False, "error": f"Railway {r.status_code}: {r.text[:160]}"}
    if body.get("errors"):
        msg = "; ".join(e.get("message", "") for e in body["errors"])[:240]
        return {"ok": False, "error": msg or f"Railway {r.status_code}"}
    return {"ok": True, "data": body.get("data") or {}}


def list_projects() -> dict:
    """Listet alle Railway-Projekte des Tokens. Gibt {ok, projects:[{id,name}]}."""
    token = _token()
    if not token:
        return {"ok": False, "error": "RAILWAY_TOKEN fehlt in .env", "projects": []}
    q = "query{ me { projects { edges { node { id name } } } } }"
    r = _gql(q, {}, token)
    if not r["ok"]:
        # Fallback: manche Tokens liefern Projekte unter 'projects' statt 'me'
        r2 = _gql("query{ projects { edges { node { id name } } } }", {}, token)
        if not r2["ok"]:
            return {"ok": False, "error": r["error"], "projects": []}
        edges = r2["data"].get("projects", {}).get("edges", [])
    else:
        edges = r["data"].get("me", {}).get("projects", {}).get("edges", [])
    return {"ok": True, "projects": [e["node"] for e in edges]}


def diagnose() -> dict:
    """Prüft live, ob das Railway-Token einsatzbereit ist (für die Deploy-Diagnose).
    Gibt {ok, present, valid, account, msg} — verrät das Token nie."""
    token = _token()
    if not token:
        return {"ok": False, "present": False, "valid": False,
                "msg": "RAILWAY_TOKEN fehlt in der .env."}
    r = _gql("query{ me { email name } }", {}, token)
    if r["ok"]:
        me = r["data"].get("me") or {}
        who = me.get("email") or me.get("name") or "verbunden"
        return {"ok": True, "present": True, "valid": True, "account": who,
                "msg": f"OK — Account {who}. Hinweis: Railway muss die GitHub-App "
                       "einmalig mit dem Account verbunden haben (railway.app → GitHub)."}
    # me{} verweigert → evtl. Projekt-Token: über Projekt-Query gegenprüfen.
    r2 = _gql("query{ projects { edges { node { id } } } }", {}, token)
    if r2["ok"]:
        return {"ok": True, "present": True, "valid": True, "account": "Projekt-Token",
                "msg": "OK — Projekt-Token gültig (Account-Abfrage eingeschränkt)."}
    return {"ok": False, "present": True, "valid": False,
            "msg": f"Railway-Token ungültig oder ohne Rechte: {str(r.get('error',''))[:120]}"}


def _find_project_with_env(token: str, name: str) -> dict:
    """Sucht ein Projekt nach Name (inkl. production-Environment-ID).
    Gibt {found, project_id, env_id}."""
    q = ("query{ me { projects { edges { node { id name "
         "environments { edges { node { id name } } } } } } } }")
    r = _gql(q, {}, token)
    if r["ok"]:
        edges = r["data"].get("me", {}).get("projects", {}).get("edges", [])
    else:
        q2 = ("query{ projects { edges { node { id name "
              "environments { edges { node { id name } } } } } } }")
        r2 = _gql(q2, {}, token)
        edges = r2["data"].get("projects", {}).get("edges", []) if r2["ok"] else []
    for e in edges:
        node = e.get("node") or {}
        if (node.get("name") or "").strip().lower() == name.strip().lower():
            envs = [x["node"] for x in node.get("environments", {}).get("edges", [])]
            env_id = next((x["id"] for x in envs if x.get("name") == "production"),
                          envs[0]["id"] if envs else None)
            return {"found": True, "project_id": node["id"], "env_id": env_id}
    return {"found": False}


def _find_service(token: str, project_id: str, name: str) -> dict:
    """Sucht im Projekt einen Service nach Name und liest dessen bestehende Domain.
    Gibt {found, service_id, domain}. Für den Fall, dass der Service schon existiert
    (Re-Build derselben Seite) — so kommt trotzdem ein Live-Link zurück.

    Robust: scheitert die ausführliche Query (Domain mit), wird auf eine einfache
    Service-Liste (nur id+name) zurückgegriffen, damit der Service IMMER gefunden wird,
    wenn er existiert (sonst käme fälschlich „serviceCreate: already exists" durch)."""
    want = (name or "").strip().lower()
    q = ("query($id:String!){ project(id:$id){ services{ edges{ node{ id name "
         "serviceInstances{ edges{ node{ domains{ serviceDomains{ domain } } } } } } } } } }")
    r = _gql(q, {"id": project_id}, token)
    if r["ok"]:
        edges = (((r["data"].get("project") or {}).get("services") or {}).get("edges") or [])
        for e in edges:
            node = e.get("node") or {}
            if (node.get("name") or "").strip().lower() != want:
                continue
            domain = ""
            for si in ((node.get("serviceInstances") or {}).get("edges") or []):
                for sd in (((si.get("node") or {}).get("domains") or {}).get("serviceDomains") or []):
                    if sd.get("domain"):
                        domain = sd["domain"]
                        break
                if domain:
                    break
            return {"found": True, "service_id": node["id"], "domain": domain}
        return {"found": False}
    # Ausführliche Query scheiterte (Schema-Änderung o.ä.) → einfache Liste als Fallback.
    r2 = _gql("query($id:String!){ project(id:$id){ services{ edges{ node{ id name } } } } }",
              {"id": project_id}, token)
    if r2["ok"]:
        for e in (((r2["data"].get("project") or {}).get("services") or {}).get("edges") or []):
            node = e.get("node") or {}
            if (node.get("name") or "").strip().lower() == want:
                return {"found": True, "service_id": node["id"], "domain": ""}
    return {"found": False}


def _service_count(token: str, project_id: str) -> int:
    """Anzahl der Services im Projekt (für die Limit-Frühwarnung). -1 wenn nicht lesbar."""
    q = "query($id:String!){ project(id:$id){ services{ edges{ node{ id } } } } }"
    r = _gql(q, {"id": project_id}, token)
    if not r["ok"]:
        return -1
    return len((((r["data"].get("project") or {}).get("services") or {}).get("edges") or []))


def _service_domain(token: str, service_id: str) -> str:
    """Liest die bestehende öffentliche Domain eines Service (best-effort, '' wenn keine)."""
    q = ("query($id:String!){ service(id:$id){ serviceInstances{ edges{ node{ "
         "domains{ serviceDomains{ domain } } } } } } }")
    r = _gql(q, {"id": service_id}, token)
    if not r["ok"]:
        return ""
    for si in ((((r["data"].get("service") or {}).get("serviceInstances") or {}).get("edges")) or []):
        for sd in (((si.get("node") or {}).get("domains") or {}).get("serviceDomains") or []):
            if sd.get("domain"):
                return sd["domain"]
    return ""


def project_delete(project_id: str) -> dict:
    """Löscht ein Railway-Projekt unwiderruflich. Gibt {ok} oder {ok:False,error}."""
    token = _token()
    if not token:
        return {"ok": False, "error": "RAILWAY_TOKEN fehlt in .env"}
    r = _gql("mutation($id:String!){ projectDelete(id:$id) }", {"id": project_id}, token)
    return {"ok": r["ok"], "error": r.get("error", "")}


def service_delete_by_name(service_name: str) -> dict:
    """Löscht den Service mit diesem Namen (best-effort). Sucht über ALLE rotierten
    Sammel-Projekte ('Generated Websites', '… 2', '… 3', …), da eine Seite je nach
    Baudatum in einem beliebigen davon liegen kann. Gibt {ok, error}."""
    token = _token()
    if not token:
        return {"ok": False, "error": "RAILWAY_TOKEN fehlt"}
    projects = all_generated_projects(token)
    if not projects:
        return {"ok": False, "error": f"Kein Sammel-Projekt '{PROJECT_NAME}*' gefunden"}
    want = service_name.strip()
    for proj in projects:
        q = ("query($id:String!){ project(id:$id){ services { edges { node { id name } } } } }")
        r = _gql(q, {"id": proj["id"]}, token)
        if not r["ok"]:
            continue
        edges = (((r["data"].get("project") or {}).get("services") or {}).get("edges") or [])
        sid = next((e["node"]["id"] for e in edges
                    if (e["node"].get("name") or "").strip() == want), "")
        if sid:
            d = _gql("mutation($id:String!){ serviceDelete(id:$id) }", {"id": sid}, token)
            return {"ok": d["ok"], "error": d.get("error", "")}
    return {"ok": True, "error": "Service nicht gefunden (bereits gelöscht?)"}


def deploy(name: str, repo_full_name: str, env: dict, branch: str = "main",
           on_step=None) -> dict:
    """
    Vollständiger Deploy aus einem GitHub-Repo. Gibt
    {ok, url, project_id, service_id, log:[...]} oder {ok:False, error, log}.

    on_step(text): optionaler Callback, der bei jedem Teilschritt aufgerufen wird
    (für eine genaue Fortschrittsanzeige im Dashboard).
    """
    token = _token()
    log: list[str] = []

    def _say(text: str) -> None:
        log.append(text)
        if callable(on_step):
            try:
                on_step(text)
            except Exception:
                pass
    if not token:
        return {"ok": False, "error": "RAILWAY_TOKEN fehlt in .env", "log": log}
    if not repo_full_name:
        return {"ok": False, "error": "Kein GitHub-Repo für den Deploy.", "log": log}

    svc_name = name[:60]
    domain = ""
    service_id = ""
    project_id = ""
    env_id = ""

    # 0) Resume-Check: existiert dieser Service SCHON in irgendeinem rotierten Sammel-
    # Projekt (Re-Build/Redeploy einer älteren Seite)? Dann dort wiederverwenden — sonst
    # würde eine spätere Rotation denselben Service doppelt in einem NEUEN Projekt anlegen
    # und das Original verwaist zurücklassen.
    for proj in all_generated_projects(token):
        again = _find_service(token, proj["id"], svc_name)
        if again.get("found"):
            resume = _find_project_with_env(token, proj["name"])
            if resume.get("found") and resume.get("env_id"):
                project_id = resume["project_id"]
                env_id = resume["env_id"]
                service_id = again["service_id"]
                domain = again.get("domain", "")
                _say(f"Service „{svc_name}“ existiert bereits in „{proj['name']}“ — wird wiederverwendet"
                     + (f" (Domain {domain})" if domain else ""))
            break

    # 1) Kein Resume-Treffer → aktives Sammel-Projekt finden ODER anlegen (rotiert
    #    automatisch in ein Folgeprojekt, sobald das jüngste bekannte Projekt voll ist) --
    if not project_id:
        target_name = _target_project_name(token)
        found = _find_project_with_env(token, target_name)
        if found.get("found") and found.get("env_id"):
            project_id = found["project_id"]
            env_id = found["env_id"]
            _say(f"Projekt „{target_name}“ gefunden — Seite kommt als neuer Service hinein")
        else:
            q_proj = """
            mutation($name:String!){ projectCreate(input:{name:$name}){
              id environments{edges{node{id name}}} } }"""
            r = _gql(q_proj, {"name": target_name[:60]}, token)
            if not r["ok"]:
                return {"ok": False, "error": f"projectCreate: {r['error']}", "log": log}
            proj = r["data"]["projectCreate"]
            project_id = proj["id"]
            envs = [e["node"] for e in proj.get("environments", {}).get("edges", [])]
            env_id = next((e["id"] for e in envs if e.get("name") == "production"),
                          envs[0]["id"] if envs else None)
            if not env_id:
                return {"ok": False, "error": "Keine Environment-ID erhalten.", "log": log}
            _say(f"Sammel-Projekt „{target_name}“ neu angelegt"
                 + (" (Rotation — voriges Projekt war voll)" if target_name != PROJECT_NAME else ""))

        # Limit-Frühwarnung: Railway limitiert Services/Guthaben pro Projekt. Ab _rotate_at()
        # (Default 50) rotiert der NÄCHSTE Deploy automatisch in ein neues Projekt (oben) —
        # hier nur noch eine frühe Textwarnung, wenn es sich schon abzeichnet (Default 40).
        try:
            n_svc = _service_count(token, project_id)
            warn_at = int(os.environ.get("JARVIS_RAILWAY_MAX_SERVICES", "40") or "40")
            if n_svc >= warn_at:
                _say(f"⚠ {n_svc} Services im Projekt „{target_name}“ — nähert sich der "
                     f"Rotationsgrenze ({_rotate_at()}). Alte Demos abbauen: "
                     "python railway_cleanup.py --keep <name> --yes")
        except Exception:
            pass

    # 2) Service: bestehenden (aus Schritt 0) WIEDERVERWENDEN, sonst neu anlegen.
    # Jede Seite ist ein eigener, benannter Service IM Sammel-Projekt.
    if service_id:
        pass
    else:
        q_svc = """
        mutation($projectId:String!,$repo:String!,$branch:String!,$name:String!){
          serviceCreate(input:{projectId:$projectId, name:$name, branch:$branch,
            source:{repo:$repo}}){ id } }"""
        r = _gql(q_svc, {"projectId": project_id, "repo": repo_full_name,
                         "branch": branch, "name": svc_name}, token)
        if r["ok"]:
            service_id = r["data"]["serviceCreate"]["id"]
            _say(f"Service „{svc_name}“ aus GitHub-Repo verbunden")
        else:
            # Race/Konflikt (zwischen Suche und Anlegen entstanden, oder „already exists") →
            # nochmal gezielt suchen und wiederverwenden, NIE als harten Fehler durchreichen.
            again = _find_service(token, project_id, svc_name)
            if again.get("found"):
                service_id = again["service_id"]
                domain = again.get("domain", "")
                _say(f"Service „{svc_name}“ existierte bereits — wiederverwendet"
                     + (f" (Domain {domain})" if domain else ""))
            else:
                return {"ok": False, "error": f"serviceCreate: {r['error']}",
                        "project_id": project_id, "log": log}
    # Domain eines wiederverwendeten Service ggf. nachladen (falls oben nicht mitgekommen).
    if service_id and not domain:
        domain = _service_domain(token, service_id)

    # 3) Öffentliche Domain erzeugen (nur falls der Service noch keine hat) ----
    if not domain:
        q_dom = """
        mutation($environmentId:String!,$serviceId:String!){
          serviceDomainCreate(input:{environmentId:$environmentId, serviceId:$serviceId}){ domain } }"""
        r = _gql(q_dom, {"environmentId": env_id, "serviceId": service_id}, token)
        if r["ok"]:
            domain = r["data"]["serviceDomainCreate"]["domain"]
            _say(f"Öffentliche Domain erstellt: {domain}")
        else:
            # Domain evtl. schon vorhanden → nochmal gezielt nachschlagen.
            again = _find_service(token, project_id, name[:60])
            if again.get("domain"):
                domain = again["domain"]
                _say(f"Bestehende Domain übernommen: {domain}")
            else:
                _say(f"Domain-Erstellung fehlgeschlagen: {r['error']}")

    # 4) Umgebungsvariablen setzen (inkl. der frisch erzeugten Domain) --------
    final_env = dict(env or {})
    if domain:
        final_env["ALLOWED_HOSTS"] = domain
        final_env["CSRF_TRUSTED_ORIGINS"] = f"https://{domain}"
        final_env["SITE_URL"] = f"https://{domain}"
    q_vars = """
    mutation($projectId:String!,$environmentId:String!,$serviceId:String!,$variables:EnvironmentVariables!){
      variableCollectionUpsert(input:{projectId:$projectId, environmentId:$environmentId,
        serviceId:$serviceId, variables:$variables}) }"""
    r = _gql(q_vars, {"projectId": project_id, "environmentId": env_id,
                      "serviceId": service_id, "variables": final_env}, token)
    _say("Umgebungsvariablen gesetzt (SECRET_KEY, ALLOWED_HOSTS …)"
         if r["ok"] else f"Variablen-Fehler: {r['error']}")

    # 5) Redeploy anstoßen, damit Variablen + Domain greifen ------------------
    q_redeploy = """
    mutation($environmentId:String!,$serviceId:String!){
      serviceInstanceRedeploy(environmentId:$environmentId, serviceId:$serviceId) }"""
    r = _gql(q_redeploy, {"environmentId": env_id, "serviceId": service_id}, token)
    _say("Deploy angestoßen — Container wird gebaut" if r["ok"]
         else f"Redeploy-Hinweis: {r['error']}")

    url = f"https://{domain}" if domain else ""
    return {"ok": True, "url": url, "domain": domain,
            "project_id": project_id, "service_id": service_id, "log": log}
