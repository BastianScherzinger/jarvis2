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

ENDPOINT = "https://backboard.railway.com/graphql/v2"


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


def deploy(name: str, repo_full_name: str, env: dict, branch: str = "main") -> dict:
    """
    Vollständiger Deploy aus einem GitHub-Repo. Gibt
    {ok, url, project_id, service_id, log:[...]} oder {ok:False, error, log}.
    """
    token = _token()
    log: list[str] = []
    if not token:
        return {"ok": False, "error": "RAILWAY_TOKEN fehlt in .env", "log": log}
    if not repo_full_name:
        return {"ok": False, "error": "Kein GitHub-Repo für den Deploy.", "log": log}

    # 1) Projekt anlegen ------------------------------------------------------
    q_proj = """
    mutation($name:String!){ projectCreate(input:{name:$name}){
      id environments{edges{node{id name}}} } }"""
    r = _gql(q_proj, {"name": name[:60]}, token)
    if not r["ok"]:
        return {"ok": False, "error": f"projectCreate: {r['error']}", "log": log}
    proj = r["data"]["projectCreate"]
    project_id = proj["id"]
    envs = [e["node"] for e in proj.get("environments", {}).get("edges", [])]
    env_id = next((e["id"] for e in envs if e.get("name") == "production"),
                  envs[0]["id"] if envs else None)
    if not env_id:
        return {"ok": False, "error": "Keine Environment-ID erhalten.", "log": log}
    log.append(f"Projekt erstellt ({project_id[:8]}…), Environment ok")

    # 2) Service aus dem GitHub-Repo anlegen (startet Auto-Deploy) ------------
    q_svc = """
    mutation($projectId:String!,$repo:String!,$branch:String!){
      serviceCreate(input:{projectId:$projectId, branch:$branch, source:{repo:$repo}}){ id } }"""
    r = _gql(q_svc, {"projectId": project_id, "repo": repo_full_name, "branch": branch}, token)
    if not r["ok"]:
        return {"ok": False, "error": f"serviceCreate: {r['error']}",
                "project_id": project_id, "log": log}
    service_id = r["data"]["serviceCreate"]["id"]
    log.append(f"Service aus {repo_full_name} verbunden ({service_id[:8]}…)")

    # 3) Öffentliche Domain erzeugen -----------------------------------------
    domain = ""
    q_dom = """
    mutation($environmentId:String!,$serviceId:String!){
      serviceDomainCreate(input:{environmentId:$environmentId, serviceId:$serviceId}){ domain } }"""
    r = _gql(q_dom, {"environmentId": env_id, "serviceId": service_id}, token)
    if r["ok"]:
        domain = r["data"]["serviceDomainCreate"]["domain"]
        log.append(f"Domain: {domain}")
    else:
        log.append(f"Domain-Erstellung fehlgeschlagen: {r['error']}")

    # 4) Umgebungsvariablen setzen (inkl. der frisch erzeugten Domain) --------
    final_env = dict(env or {})
    if domain:
        final_env["ALLOWED_HOSTS"] = domain
        final_env["CSRF_TRUSTED_ORIGINS"] = f"https://{domain}"
        final_env["SITE_URL"] = f"https://{domain}"
    q_vars = """
    mutation($projectId:String!,$environmentId:String!,$serviceId:String!,$variables:JSON!){
      variableCollectionUpsert(input:{projectId:$projectId, environmentId:$environmentId,
        serviceId:$serviceId, variables:$variables}) }"""
    r = _gql(q_vars, {"projectId": project_id, "environmentId": env_id,
                      "serviceId": service_id, "variables": final_env}, token)
    log.append("Variablen gesetzt" if r["ok"] else f"Variablen-Fehler: {r['error']}")

    # 5) Redeploy anstoßen, damit Variablen + Domain greifen ------------------
    q_redeploy = """
    mutation($environmentId:String!,$serviceId:String!){
      serviceInstanceRedeploy(environmentId:$environmentId, serviceId:$serviceId) }"""
    r = _gql(q_redeploy, {"environmentId": env_id, "serviceId": service_id}, token)
    log.append("Deploy angestoßen" if r["ok"] else f"Redeploy-Hinweis: {r['error']}")

    url = f"https://{domain}" if domain else ""
    return {"ok": True, "url": url, "domain": domain,
            "project_id": project_id, "service_id": service_id, "log": log}
