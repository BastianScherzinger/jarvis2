"""
GitHub-Client für den JARVIS-Website-Builder.

Erstellt ein Repository über die GitHub-API und pusht einen lokalen Ordner —
tokengesteuert aus der .env (GITHUB_TOKEN, GITHUB_USER). Das Token wird NIE
geloggt oder in Rückgaben eingebettet.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import requests

import config  # noqa: F401 — lädt die .env in os.environ (sonst Token evtl. nicht sichtbar)

API = "https://api.github.com"


def _token() -> str:
    return (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()


def is_ready() -> bool:
    return bool(_token())


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _whoami(token: str) -> str:
    try:
        r = requests.get(f"{API}/user", headers=_headers(token), timeout=20)
        if r.ok:
            return r.json().get("login", "")
    except Exception:
        pass
    return (os.environ.get("GITHUB_USER") or "").strip()


def diagnose() -> dict:
    """Prüft live, ob das GitHub-Token einsatzbereit ist (für die Deploy-Diagnose).
    Gibt {ok, present, valid, login, scopes, msg} — verrät das Token nie."""
    token = _token()
    if not token:
        return {"ok": False, "present": False, "valid": False,
                "msg": "GITHUB_TOKEN fehlt in der .env."}
    try:
        r = requests.get(f"{API}/user", headers=_headers(token), timeout=20)
    except Exception as e:
        return {"ok": False, "present": True, "valid": False,
                "msg": f"GitHub nicht erreichbar: {type(e).__name__}"}
    if r.status_code == 401:
        return {"ok": False, "present": True, "valid": False,
                "msg": "GitHub-Token ungültig (401) — neues Token mit Scope 'repo' erstellen."}
    if not r.ok:
        return {"ok": False, "present": True, "valid": False,
                "msg": f"GitHub antwortet {r.status_code}."}
    login  = (r.json() or {}).get("login", "")
    scopes = r.headers.get("X-OAuth-Scopes", "")
    scope_list = [s.strip() for s in scopes.split(",") if s.strip()]
    # Klassischer PAT: braucht 'repo'. Fine-grained PAT: leeres Scope-Header.
    if scopes and not ("repo" in scope_list or "public_repo" in scope_list):
        return {"ok": False, "present": True, "valid": True, "login": login, "scopes": scopes,
                "msg": f"Token gültig (User {login}), aber Scope 'repo' fehlt — "
                       "Repo-Erstellung schlägt fehl. Token mit 'repo' neu erstellen."}
    if not scopes:
        return {"ok": True, "present": True, "valid": True, "login": login, "scopes": "",
                "msg": f"OK — angemeldet als {login} (Fine-grained Token; es braucht "
                       "Repository-Rechte 'Administration: Read & write' + 'Contents: Read & write')."}
    return {"ok": True, "present": True, "valid": True, "login": login, "scopes": scopes,
            "msg": f"OK — angemeldet als {login}, Scope 'repo' vorhanden."}


def create_repo(name: str, description: str = "", private: bool = True) -> dict:
    """
    Legt ein Repo unter dem Account des Tokens an. Existiert es schon, wird es
    wiederverwendet. Gibt {ok, full_name, clone_url, html_url, owner, existed}.
    """
    token = _token()
    if not token:
        return {"ok": False, "error": "GITHUB_TOKEN fehlt in .env"}
    name = (name or "").strip().strip("/")
    if not name:
        return {"ok": False, "error": "Kein Repo-Name."}

    try:
        r = requests.post(
            f"{API}/user/repos",
            headers=_headers(token),
            json={"name": name, "description": description[:300],
                  "private": bool(private), "auto_init": False,
                  "has_issues": False, "has_wiki": False, "has_projects": False},
            timeout=30,
        )
    except Exception as e:
        return {"ok": False, "error": f"GitHub nicht erreichbar: {type(e).__name__}"}

    if r.status_code == 201:
        d = r.json()
        return {"ok": True, "full_name": d["full_name"], "clone_url": d["clone_url"],
                "html_url": d["html_url"], "owner": d["owner"]["login"], "existed": False}

    if r.status_code == 422:  # existiert bereits → bestehendes Repo holen
        owner = _whoami(token)
        try:
            gr = requests.get(f"{API}/repos/{owner}/{name}", headers=_headers(token), timeout=20)
            if gr.ok:
                d = gr.json()
                return {"ok": True, "full_name": d["full_name"], "clone_url": d["clone_url"],
                        "html_url": d["html_url"], "owner": d["owner"]["login"], "existed": True}
        except Exception:
            pass
        return {"ok": False, "error": "Repo-Name bereits vergeben (und nicht lesbar)."}

    if r.status_code == 401:
        return {"ok": False, "error": "GitHub-Token ungültig (401) — Scope 'repo' nötig."}
    return {"ok": False, "error": f"GitHub {r.status_code}: {r.text[:160]}"}


def push_folder(folder: "str | Path", full_name: str, branch: str = "main",
                message: str = "Initiale Website (JARVIS)") -> dict:
    """git init/add/commit + token-authentifizierter Push nach github.com/<full_name>."""
    token = _token()
    if not token:
        return {"ok": False, "error": "GITHUB_TOKEN fehlt in .env"}
    target = Path(folder)
    if not target.is_dir():
        return {"ok": False, "error": "Projektordner nicht gefunden."}

    # Token nur im Remote-URL, nie in Logs/Rückgabe. x-access-token = PAT-Schema.
    remote = f"https://x-access-token:{token}@github.com/{full_name}.git"
    safe_remote = f"https://github.com/{full_name}.git"

    def _run(args: list, **kw) -> "subprocess.CompletedProcess":
        return subprocess.run(["git", *args], cwd=str(target),
                              capture_output=True, text=True, timeout=240, **kw)

    try:
        (target / ".gitattributes").write_text("* text=auto\n*.sh text eol=lf\n", encoding="utf-8")
        if not (target / ".git").exists():
            _run(["init"])
            _run(["branch", "-M", branch])
        _run(["add", "-A"])
        # Commit nur wenn es etwas zu committen gibt (sonst non-zero, egal).
        _run(["-c", "user.email=jarvis@local", "-c", "user.name=JARVIS", "commit", "-m", message])
        if _run(["remote", "add", "origin", remote]).returncode != 0:
            _run(["remote", "set-url", "origin", remote])
        push = _run(["push", "-u", "origin", branch, "--force"])
        # Remote nach dem Push auf die token-freie URL zurücksetzen (kein Klartext-Token im .git/config).
        _run(["remote", "set-url", "origin", safe_remote])
        if push.returncode == 0:
            return {"ok": True, "remote": safe_remote}
        err = (push.stderr or push.stdout or "").replace(token, "***")[:240]
        return {"ok": False, "error": f"Push fehlgeschlagen: {err}"}
    except Exception as e:
        return {"ok": False, "error": f"Git-Fehler: {type(e).__name__}: {str(e)[:160]}"}
