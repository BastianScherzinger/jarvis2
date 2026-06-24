"""
higgsfield_mcp.py — JARVIS-Client für den offiziellen Higgsfield-MCP-Server.

WARUM: Der Higgsfield-Platform-API-Key (platform.higgsfield.ai) hängt an einem eigenen,
leeren API-Credit-Topf. Die echten ABO-Credits (Soul/Plus) sind nur über den MCP-Server
`mcp.higgsfield.ai` nutzbar — der per OAuth am Higgsfield-Konto angemeldet wird (kein
API-Key). Dieser Client meldet JARVIS EINMALIG per Browser an (Authorization-Code + PKCE,
dynamische Client-Registrierung), cached die Token und erneuert sie per refresh_token.
Danach erzeugt JARVIS Bilder headless über die Abo-Credits.

Flow (verifiziert 24.06.2026):
  tools/call generate_image {params:{model, prompt, aspect_ratio, count}}  → results[0].id
  tools/call job_status {jobId, sync:true, raw_data:true}                  → raw_data.result_url
  Download result_url → Datei.

Öffentliche API:
  is_authorized() · login(on_url=None) · logout() · status()
  generate_image(prompt, out_path, aspect_ratio, model) -> dict
  available() (= authorized)
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

try:
    import httpx
    _HAS_HTTPX = True
except Exception:
    _HAS_HTTPX = False

_BASE = Path(__file__).parent
_AUTH_PATH = _BASE / "data" / "higgsfield_mcp_auth.json"

_MCP_URL   = os.environ.get("JARVIS_HF_MCP_URL", "https://mcp.higgsfield.ai/mcp")
_ISSUER    = "https://mcp.higgsfield.ai"
_SCOPE     = "openid email offline_access"
_PROTOCOL  = "2025-06-18"
_MODEL_DEF = os.environ.get("JARVIS_HF_MCP_MODEL", "soul_2")
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_disc_cache: dict = {}
_session_cache: dict = {}     # {"id": session_id, "ts": ...}
_lock = threading.Lock()


def _log(level: str, msg: str) -> None:
    try:
        import logger as _lg
        getattr(_lg, level, _lg.info)("HiggsfieldMCP", msg)
    except Exception:
        pass


# ── OAuth-Discovery + Token-Speicher ─────────────────────────────────────────

def _discover() -> dict:
    """OAuth-Authorization-Server-Metadaten (authorize/token/register-Endpunkte)."""
    if _disc_cache:
        return _disc_cache
    url = f"{_ISSUER}/.well-known/oauth-authorization-server"
    with httpx.Client(timeout=15, headers={"User-Agent": _UA}) as c:
        d = c.get(url).json()
    _disc_cache.update({
        "authorization_endpoint": d.get("authorization_endpoint", f"{_ISSUER}/oauth2/authorize"),
        "token_endpoint":         d.get("token_endpoint", f"{_ISSUER}/oauth2/token"),
        "registration_endpoint":  d.get("registration_endpoint", f"{_ISSUER}/oauth2/register"),
    })
    return _disc_cache


def _load() -> dict:
    try:
        return json.loads(_AUTH_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        _AUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
        _AUTH_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        _log("warn", f"Token-Speichern fehlgeschlagen: {type(e).__name__}")


def is_authorized() -> bool:
    """True, wenn ein Login vorliegt (Refresh-Token zum headless Erneuern vorhanden)."""
    a = _load()
    return bool(a.get("refresh_token") or a.get("access_token"))


def available() -> bool:
    return _HAS_HTTPX and is_authorized()


# ── Login (Authorization-Code + PKCE, dynamische Registrierung) ──────────────

class _CallbackHandler(BaseHTTPRequestHandler):
    code_holder: dict = {}

    def do_GET(self):                     # noqa: N802
        q = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(q)
        _CallbackHandler.code_holder["code"] = (params.get("code") or [""])[0]
        _CallbackHandler.code_holder["state"] = (params.get("state") or [""])[0]
        _CallbackHandler.code_holder["error"] = (params.get("error") or [""])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        ok = bool(_CallbackHandler.code_holder.get("code"))
        body = ("<h2>JARVIS · Higgsfield verbunden ✓</h2><p>Sie können dieses Fenster "
                "schließen, Sir.</p>" if ok else
                "<h2>Anmeldung fehlgeschlagen</h2><p>Bitte erneut versuchen.</p>")
        self.wfile.write(f"<html><body style='font-family:sans-serif;padding:40px'>{body}</body></html>"
                         .encode("utf-8"))

    def log_message(self, *a):            # Server-Logs unterdrücken
        return


def _register(redirect_uri: str) -> dict:
    """Dynamische Client-Registrierung (RFC 7591). Gibt {client_id, client_secret?}."""
    disc = _discover()
    payload = {
        "client_name": "JARVIS",
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": _SCOPE,
    }
    with httpx.Client(timeout=20, headers={"User-Agent": _UA}) as c:
        r = c.post(disc["registration_endpoint"], json=payload)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Client-Registrierung {r.status_code}: {r.text[:200]}")
        d = r.json()
    return {"client_id": d.get("client_id"), "client_secret": d.get("client_secret", "")}


def _pkce() -> tuple:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def login(on_url=None, open_browser: bool = True, port_range=range(8765, 8780),
          wait_timeout: int = 300) -> dict:
    """Einmaliger Browser-Login. on_url(url): Callback, dem die Anmelde-URL übergeben wird
    (für Dashboard/Discord); sonst wird der Browser geöffnet. Gibt {ok, error?}."""
    if not _HAS_HTTPX:
        return {"ok": False, "error": "httpx fehlt (pip install httpx)."}
    try:
        disc = _discover()
    except Exception as e:
        return {"ok": False, "error": f"OAuth-Discovery fehlgeschlagen: {type(e).__name__}: {e}"}

    # Lokalen Callback-Server starten (erster freier Port).
    httpd = None
    redirect_uri = ""
    for port in port_range:
        try:
            _CallbackHandler.code_holder = {}
            httpd = HTTPServer(("127.0.0.1", port), _CallbackHandler)
            redirect_uri = f"http://localhost:{port}/callback"
            break
        except OSError:
            continue
    if httpd is None:
        return {"ok": False, "error": "Kein freier lokaler Port für den Login-Callback."}

    try:
        reg = _register(redirect_uri)
        if not reg.get("client_id"):
            return {"ok": False, "error": "Keine client_id von Higgsfield erhalten."}
        verifier, challenge = _pkce()
        state = secrets.token_urlsafe(16)
        auth_url = disc["authorization_endpoint"] + "?" + urllib.parse.urlencode({
            "response_type": "code", "client_id": reg["client_id"],
            "redirect_uri": redirect_uri, "scope": _SCOPE, "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256",
        })

        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        _log("info", "Higgsfield-Login gestartet — Browser-Bestätigung nötig.")
        if callable(on_url):
            try:
                on_url(auth_url)
            except Exception:
                pass
        if open_browser:
            try:
                webbrowser.open(auth_url)
            except Exception:
                pass

        end = time.time() + wait_timeout
        while time.time() < end:
            if _CallbackHandler.code_holder.get("code") or _CallbackHandler.code_holder.get("error"):
                break
            time.sleep(0.5)
        code = _CallbackHandler.code_holder.get("code", "")
        err  = _CallbackHandler.code_holder.get("error", "")
        got_state = _CallbackHandler.code_holder.get("state", "")
    finally:
        try:
            httpd.shutdown()
        except Exception:
            pass

    if err:
        return {"ok": False, "error": f"Higgsfield meldete: {err}"}
    if not code:
        return {"ok": False, "error": "Zeitüberschreitung — kein Anmelde-Code erhalten."}
    if got_state and got_state != state:
        return {"ok": False, "error": "State-Mismatch (Sicherheitsabbruch)."}

    # Code → Token tauschen.
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": reg["client_id"], "code_verifier": verifier}
    if reg.get("client_secret"):
        form["client_secret"] = reg["client_secret"]
    try:
        with httpx.Client(timeout=25, headers={"User-Agent": _UA}) as c:
            r = c.post(disc["token_endpoint"], data=form)
            if r.status_code != 200:
                return {"ok": False, "error": f"Token-Tausch {r.status_code}: {r.text[:200]}"}
            tok = r.json()
    except Exception as e:
        return {"ok": False, "error": f"Token-Tausch fehlgeschlagen: {type(e).__name__}: {e}"}

    _save({
        "client_id": reg["client_id"], "client_secret": reg.get("client_secret", ""),
        "access_token": tok.get("access_token", ""),
        "refresh_token": tok.get("refresh_token", ""),
        "expires_at": time.time() + int(tok.get("expires_in", 3600)) - 60,
        "token_endpoint": disc["token_endpoint"], "saved": time.time(),
    })
    _log("success", "Higgsfield-MCP verbunden — Abo-Credits jetzt für JARVIS nutzbar.")
    return {"ok": True}


def logout() -> dict:
    try:
        _AUTH_PATH.unlink(missing_ok=True)
    except Exception:
        pass
    _session_cache.clear()
    return {"ok": True}


# Nicht-blockierender Login für das Dashboard: Thread startet den Flow, die Anmelde-URL
# wird sofort zurückgegeben; der Token-Tausch passiert im Hintergrund nach der Bestätigung.
_login_state: dict = {"running": False, "url": "", "result": None}


def login_async(open_browser: bool = True) -> dict:
    """Startet den Login in einem Thread und gibt sofort die Anmelde-URL zurück.
    Fortschritt via login_status(). Mehrfachaufruf während eines laufenden Logins ist sicher."""
    with _lock:
        if _login_state["running"]:
            return {"ok": True, "running": True, "url": _login_state.get("url", "")}
        _login_state.update({"running": True, "url": "", "result": None})

    def _on_url(u):
        with _lock:
            _login_state["url"] = u

    def _work():
        res = login(on_url=_on_url, open_browser=open_browser)
        with _lock:
            _login_state["result"] = res
            _login_state["running"] = False

    threading.Thread(target=_work, name="hf-mcp-login", daemon=True).start()
    for _ in range(60):                 # kurz auf die URL warten (Registrierung ~1 s)
        with _lock:
            if _login_state["url"] or not _login_state["running"]:
                break
        time.sleep(0.25)
    with _lock:
        return {"ok": True, "running": _login_state["running"], "url": _login_state.get("url", "")}


def login_status() -> dict:
    with _lock:
        return {"running": _login_state["running"], "url": _login_state.get("url", ""),
                "result": _login_state.get("result"), "authorized": is_authorized()}


def _autologin_enabled() -> bool:
    return os.environ.get("JARVIS_HF_MCP_AUTOLOGIN", "1").strip().lower() not in (
        "0", "false", "no", "nein", "off")


def ensure_ready(open_browser: bool = True) -> dict:
    """Beim JARVIS-Start aufrufen. Macht die Higgsfield-Abo-Anbindung „ready":
      - schon angemeldet  → Token still erneuern (headless, kein Browser) → state 'ready'
      - nicht angemeldet  → wenn Autologin an (JARVIS_HF_MCP_AUTOLOGIN, Default an), den
                            EINMALIGEN Browser-Login anstoßen + Login-URL prominent ausgeben.
    So ist auf einem NEUEN PC nach einer Browser-Bestätigung alles bereit; danach läuft es
    bei jedem Start automatisch (refresh_token). Gibt {state, url?}."""
    if not _HAS_HTTPX:
        _log("warn", "httpx fehlt — Higgsfield-MCP nicht nutzbar (pip install httpx).")
        return {"state": "no_httpx"}

    if is_authorized():
        try:
            _valid_token()                       # erneuert bei Bedarf via refresh_token
            _log("success", "Higgsfield-MCP bereit — Abo-Credits nutzbar (Token gültig).")
            return {"state": "ready"}
        except Exception as e:
            _log("warn", f"Higgsfield-MCP-Token nicht erneuerbar ({type(e).__name__}) — "
                         "neuer Login nötig.")
            # weiter unten wie 'nicht angemeldet' behandeln

    if not _autologin_enabled():
        _log("info", "Higgsfield-MCP nicht angemeldet (Autologin aus) — "
                     "'python higgsfield_mcp.py login' oder Dashboard-Button.")
        return {"state": "unauth_noauto"}

    res = login_async(open_browser=open_browser)
    url = res.get("url", "")
    try:
        bar = "=" * 66
        print("\n" + bar)
        print("  HIGGSFIELD-LOGIN (einmalig) — danach nutzt JARVIS deine Abo-Credits")
        print("  fuer Hero-Bilder. Bitte im Browser mit dem Higgsfield-Konto bestaetigen.")
        if url:
            print("  Falls sich kein Browser oeffnet, diese URL aufrufen:")
            print("   " + url)
        print(bar + "\n", flush=True)
    except Exception:
        pass
    return {"state": "login_started", "url": url}


# ── Token gültig halten ──────────────────────────────────────────────────────

def _valid_token() -> str:
    a = _load()
    if not a:
        raise RuntimeError("Higgsfield-MCP nicht angemeldet — bitte 'login' ausführen.")
    if a.get("access_token") and time.time() < float(a.get("expires_at", 0)):
        return a["access_token"]
    rt = a.get("refresh_token")
    if not rt:
        raise RuntimeError("Token abgelaufen und kein Refresh-Token — bitte erneut 'login'.")
    form = {"grant_type": "refresh_token", "refresh_token": rt, "client_id": a.get("client_id", "")}
    if a.get("client_secret"):
        form["client_secret"] = a["client_secret"]
    with httpx.Client(timeout=25, headers={"User-Agent": _UA}) as c:
        r = c.post(a.get("token_endpoint") or _discover()["token_endpoint"], data=form)
    if r.status_code != 200:
        raise RuntimeError(f"Token-Refresh {r.status_code}: {r.text[:160]}")
    tok = r.json()
    a["access_token"]  = tok.get("access_token", "")
    a["expires_at"]    = time.time() + int(tok.get("expires_in", 3600)) - 60
    if tok.get("refresh_token"):
        a["refresh_token"] = tok["refresh_token"]      # Rotation unterstützen
    _save(a)
    return a["access_token"]


# ── MCP-JSON-RPC über streamable HTTP ────────────────────────────────────────

def _parse(resp) -> list:
    """Antwort (JSON oder SSE) in eine Liste von JSON-RPC-Nachrichten zerlegen."""
    ct = resp.headers.get("content-type", "")
    txt = resp.text
    if "text/event-stream" in ct:
        out = []
        for line in txt.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload and payload != "[DONE]":
                    try:
                        out.append(json.loads(payload))
                    except Exception:
                        pass
        return out
    try:
        j = json.loads(txt)
        return j if isinstance(j, list) else [j]
    except Exception:
        return []


def _headers(token: str, session_id: str = "") -> dict:
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
         "Accept": "application/json, text/event-stream",
         "MCP-Protocol-Version": _PROTOCOL, "User-Agent": _UA}
    if session_id:
        h["Mcp-Session-Id"] = session_id
    return h


def _ensure_session(client: "httpx.Client", token: str) -> str:
    """Initialisiert eine MCP-Session und gibt die Session-ID zurück (best-effort)."""
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": _PROTOCOL, "capabilities": {},
        "clientInfo": {"name": "JARVIS", "version": "1.0"}}}
    r = client.post(_MCP_URL, headers=_headers(token), json=init)
    sid = r.headers.get("mcp-session-id") or r.headers.get("Mcp-Session-Id") or ""
    # initialized-Notification (manche Server verlangen sie vor tools/call).
    try:
        client.post(_MCP_URL, headers=_headers(token, sid),
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    except Exception:
        pass
    return sid


def _result_payload(messages: list, req_id: int) -> dict:
    """Holt das 'result' der Antwort mit passender id; entpackt MCP-tools/call-Inhalt
    (structuredContent ODER content[].text als JSON)."""
    for m in messages:
        if m.get("id") == req_id and "result" in m:
            res = m["result"]
            if isinstance(res, dict):
                if isinstance(res.get("structuredContent"), dict):
                    return res["structuredContent"]
                for blk in (res.get("content") or []):
                    if blk.get("type") == "text":
                        try:
                            return json.loads(blk.get("text", ""))
                        except Exception:
                            continue
                return res
        if m.get("id") == req_id and "error" in m:
            raise RuntimeError(f"MCP-Fehler: {str(m['error'])[:200]}")
    return {}


def call_tool(name: str, arguments: dict, timeout: int = 60) -> dict:
    """Ruft ein MCP-Tool auf und gibt den entpackten Ergebnis-Payload zurück."""
    token = _valid_token()
    with httpx.Client(timeout=timeout, headers={"User-Agent": _UA}) as client:
        sid = _ensure_session(client, token)
        req_id = secrets.randbelow(1_000_000) + 2
        body = {"jsonrpc": "2.0", "id": req_id, "method": "tools/call",
                "params": {"name": name, "arguments": arguments}}
        r = client.post(_MCP_URL, headers=_headers(token, sid), json=body)
        if r.status_code == 401:
            raise RuntimeError("MCP 401 — Token ungültig, bitte erneut 'login'.")
        if r.status_code >= 400:
            raise RuntimeError(f"MCP {r.status_code}: {r.text[:200]}")
        return _result_payload(_parse(r), req_id)


# ── Bildgenerierung über die Abo-Credits ─────────────────────────────────────

def _aspect_for(width: int, height: int) -> str:
    r = (width or 1) / (height or 1)
    if r >= 1.6:
        return "16:9"
    if r >= 1.2:
        return "3:2"
    if r <= 0.62:
        return "9:16"
    if r <= 0.83:
        return "2:3"
    return "1:1"


def generate_image(prompt: str, out_path: "str | Path", aspect_ratio: str = "16:9",
                   model: str = "", poll_timeout: int = 180) -> dict:
    """Erzeugt EIN Bild über den Higgsfield-MCP (Abo-Credits) und speichert es nach out_path.
    Gibt {ok, path, url, model, engine}. Wirft bei Fehler (Aufrufer fällt dann zurück)."""
    if not _HAS_HTTPX:
        raise RuntimeError("httpx fehlt (pip install httpx).")
    if not is_authorized():
        raise RuntimeError("Higgsfield-MCP nicht angemeldet — 'python higgsfield_mcp.py login'.")
    mdl = model or _MODEL_DEF
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sub = call_tool("generate_image", {"params": {
        "model": mdl, "prompt": prompt, "aspect_ratio": aspect_ratio, "count": 1}})
    results = sub.get("results") or []
    job_id = (results[0].get("id") if results and isinstance(results[0], dict) else "") or sub.get("id")
    if not job_id:
        raise RuntimeError(f"Keine Job-ID in MCP-Antwort: {str(sub)[:200]}")

    url = ""
    end = time.time() + poll_timeout
    while time.time() < end:
        st = call_tool("job_status", {"jobId": job_id, "sync": True, "raw_data": True})
        raw = st.get("raw_data") if isinstance(st.get("raw_data"), dict) else st
        status = (raw.get("status") or "").lower()
        if status in ("completed", "succeeded", "success", "done"):
            url = raw.get("result_url") or raw.get("min_result_url") or ""
            if not url:
                outs = raw.get("results") or raw.get("outputs") or []
                if outs and isinstance(outs[0], dict):
                    url = outs[0].get("url") or outs[0].get("result_url") or ""
            break
        if status in ("failed", "error", "cancelled", "nsfw"):
            raise RuntimeError(f"Higgsfield-MCP Job-Status: {status}")
        time.sleep(float(raw.get("poll_after_seconds") or 3))
    if not url:
        raise TimeoutError("Higgsfield-MCP: kein Ergebnis-URL (Timeout).")

    with httpx.Client(timeout=120, headers={"User-Agent": _UA}) as c:
        data = c.get(url).content
    out_path.write_bytes(data)
    try:
        import logger as _lg
        _lg.activity("Higgsfield", "Bild generiert (MCP/Abo)", f"{mdl} · {prompt[:50]}", "🖼", "image")
    except Exception:
        pass
    return {"ok": True, "path": str(out_path), "url": url, "model": mdl, "engine": "higgsfield_mcp"}


def status() -> dict:
    a = _load()
    return {"authorized": is_authorized(), "has_refresh": bool(a.get("refresh_token")),
            "expires_at": a.get("expires_at"), "model": _MODEL_DEF, "httpx": _HAS_HTTPX}


# ── CLI: einmaliger Login + Selbsttest ───────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "login":
        print("Öffne Browser zur Higgsfield-Anmeldung… (bestätigen, dann zurückkommen)")
        print(json.dumps(login(), ensure_ascii=False))
    elif cmd == "logout":
        print(json.dumps(logout(), ensure_ascii=False))
    elif cmd == "test":
        out = _BASE / "workspace" / "media" / "images" / "mcp_test.png"
        print(json.dumps(generate_image(
            "Ultra-realistic hero banner photo of a clean modern German workshop, daylight, no text",
            out, aspect_ratio="16:9"), ensure_ascii=False))
    else:
        print(json.dumps(status(), ensure_ascii=False))
