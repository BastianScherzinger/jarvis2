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

import requests

import config  # noqa: F401 — lädt die .env in os.environ (sonst Token evtl. nicht sichtbar)

ENDPOINT = "https://backboard.railway.com/graphql/v2"

# Alle generierten Seiten landen als Services in EINEM geteilten Sammel-Projekt.
# Existiert es noch nicht, wird es einmalig angelegt. Name via .env überschreibbar.
PROJECT_NAME = (os.environ.get("JARVIS_RAILWAY_PROJECT") or "Generated Websites").strip()


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
    (Re-Build derselben Seite) — so kommt trotzdem ein Live-Link zurück."""
    q = ("query($id:String!){ project(id:$id){ services{ edges{ node{ id name "
         "serviceInstances{ edges{ node{ domains{ serviceDomains{ domain } } } } } } } } } }")
    r = _gql(q, {"id": project_id}, token)
    if not r["ok"]:
        return {"found": False}
    edges = (((r["data"].get("project") or {}).get("services") or {}).get("edges") or [])
    for e in edges:
        node = e.get("node") or {}
        if (node.get("name") or "").strip().lower() != name.strip().lower():
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


def project_delete(project_id: str) -> dict:
    """Löscht ein Railway-Projekt unwiderruflich. Gibt {ok} oder {ok:False,error}."""
    token = _token()
    if not token:
        return {"ok": False, "error": "RAILWAY_TOKEN fehlt in .env"}
    r = _gql("mutation($id:String!){ projectDelete(id:$id) }", {"id": project_id}, token)
    return {"ok": r["ok"], "error": r.get("error", "")}


def service_delete_by_name(service_name: str) -> dict:
    """Löscht den Service mit diesem Namen im Sammel-Projekt 'Generated Websites'
    (best-effort). Gibt {ok, error}."""
    token = _token()
    if not token:
        return {"ok": False, "error": "RAILWAY_TOKEN fehlt"}
    found = _find_project_with_env(token, PROJECT_NAME)
    if not found.get("found"):
        return {"ok": False, "error": f"Projekt '{PROJECT_NAME}' nicht gefunden"}
    pid = found["project_id"]
    q = ("query($id:String!){ project(id:$id){ services { edges { node { id name } } } } }")
    r = _gql(q, {"id": pid}, token)
    if not r["ok"]:
        return {"ok": False, "error": r["error"]}
    edges = (((r["data"].get("project") or {}).get("services") or {}).get("edges") or [])
    sid = next((e["node"]["id"] for e in edges
                if (e["node"].get("name") or "").strip() == service_name.strip()), "")
    if not sid:
        return {"ok": True, "error": "Service nicht gefunden (bereits gelöscht?)"}
    d = _gql("mutation($id:String!){ serviceDelete(id:$id) }", {"id": sid}, token)
    return {"ok": d["ok"], "error": d.get("error", "")}


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

    # 1) Geteiltes Sammel-Projekt "Generated Websites" finden ODER anlegen ----
    found = _find_project_with_env(token, PROJECT_NAME)
    if found.get("found") and found.get("env_id"):
        project_id = found["project_id"]
        env_id = found["env_id"]
        _say(f"Projekt „{PROJECT_NAME}“ gefunden — Seite kommt als neuer Service hinein")
    else:
        q_proj = """
        mutation($name:String!){ projectCreate(input:{name:$name}){
          id environments{edges{node{id name}}} } }"""
        r = _gql(q_proj, {"name": PROJECT_NAME[:60]}, token)
        if not r["ok"]:
            return {"ok": False, "error": f"projectCreate: {r['error']}", "log": log}
        proj = r["data"]["projectCreate"]
        project_id = proj["id"]
        envs = [e["node"] for e in proj.get("environments", {}).get("edges", [])]
        env_id = next((e["id"] for e in envs if e.get("name") == "production"),
                      envs[0]["id"] if envs else None)
        if not env_id:
            return {"ok": False, "error": "Keine Environment-ID erhalten.", "log": log}
        _say(f"Sammel-Projekt „{PROJECT_NAME}“ neu angelegt")

    # 2) Service aus dem GitHub-Repo anlegen (startet Auto-Deploy) ------------
    # Jede Seite ist ein eigener, benannter Service IM Sammel-Projekt.
    q_svc = """
    mutation($projectId:String!,$repo:String!,$branch:String!,$name:String!){
      serviceCreate(input:{projectId:$projectId, name:$name, branch:$branch,
        source:{repo:$repo}}){ id } }"""
    r = _gql(q_svc, {"projectId": project_id, "repo": repo_full_name,
                     "branch": branch, "name": name[:60]}, token)
    domain = ""
    if not r["ok"]:
        # Service existiert vermutlich schon (Re-Build derselben Seite) → den
        # bestehenden Service wiederverwenden, damit trotzdem ein Live-Link kommt.
        existing = _find_service(token, project_id, name[:60])
        if existing.get("found"):
            service_id = existing["service_id"]
            domain = existing.get("domain", "")
            _say(f"Service „{name[:60]}“ existiert bereits — wird wiederverwendet"
                 + (f" (Domain {domain})" if domain else ""))
        else:
            return {"ok": False, "error": f"serviceCreate: {r['error']}",
                    "project_id": project_id, "log": log}
    else:
        service_id = r["data"]["serviceCreate"]["id"]
        _say(f"Service „{name[:60]}“ aus GitHub-Repo verbunden")

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
