"""
filmora_mcp.py — JARVIS-Client für Video-Bearbeitung über einen viaSocket-"Filmora
MCP"-Server (https://viasocket.com/mcp/filmora).

WARUM anders als higgsfield_mcp.py: Es gibt KEINE dokumentierte, feste Filmora-REST-API
und KEIN OAuth. viaSocket gibt jedem angemeldeten Nutzer eine PERSÖNLICHE MCP-URL
("Get Your MCP URL for Free" unter app.mushroom.viasocket.com/login) — die Auth steckt
schon in dieser URL. JARVIS braucht daher keinen Login-Flow, sondern nur die URL.

Ebenfalls unbekannt sind die Tool-Namen des Servers — darum entdeckt dieser Client sie
zur LAUFZEIT per Standard-MCP `tools/list`, statt Namen zu raten. Ist beim Bearbeiten
eines Videos kein eindeutig passendes Tool zu finden, wird KEIN Job angelegt, sondern
eine Liste von Kandidaten zurückgegeben — der Nutzer wählt dann im Dashboard manuell.

Transport (JSON-RPC über streamable HTTP) ist adaptiert aus higgsfield_mcp.py:
  initialize → notifications/initialized → tools/list / tools/call

Öffentliche API:
  set_url(url) · get_status() · clear() · is_configured() · available()
  list_tools(force=False) · connect_test(url=None)
  resolve_edit_tool(youtube_url, instruction) · resolve_manual(tool_name, youtube_url, instruction)
  run_edit_job(job_id, tool_name, arguments, poll_timeout=600)
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

from jsonstate import atomic_write_json

try:
    import httpx
    _HAS_HTTPX = True
except Exception:
    _HAS_HTTPX = False

_BASE = Path(__file__).parent
_AUTH_PATH = _BASE / "data" / "filmora_mcp_auth.json"
_VIDEOS_DIR = _BASE / "workspace" / "media" / "videos"

_PROTOCOL = "2025-06-18"
_TOOLS_TTL = 24 * 3600     # Tool-Discovery 24h gecacht
_SESSION_TTL = 300         # MCP-Session-ID 5 Min wiederverwenden (kein Handshake je Call)
_AMBIGUITY_MARGIN = 2      # Score-Abstand unter dem zwei Tool-Kandidaten als gleichwertig gelten
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_lock = threading.Lock()

# MCP-Session-ID pro URL kurz gecacht — ohne das würde ein 600s-Polling-Loop (5s-Takt)
# bis zu ~120 volle initialize-Handshakes für EINEN Job machen (Rate-Limit-Risiko beim
# Server). Session-Cache-Zugriff ist unter _lock, der eigentliche HTTP-Call nicht.
_session_cache: dict = {}   # {url: {"id": sid, "ts": float}}


def _log(level: str, msg: str) -> None:
    try:
        import logger as _lg
        getattr(_lg, level, _lg.info)("VideoStudio", msg)
    except Exception:
        pass


# ── Speicher (URL statt OAuth-Tokens) ───────────────────────────────────────────

def _load() -> dict:
    try:
        return json.loads(_AUTH_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        atomic_write_json(_AUTH_PATH, data, indent=2)
    except Exception as e:
        _log("warn", f"Speichern fehlgeschlagen: {type(e).__name__}")


def _url_from_env() -> str:
    """Optionaler Startwert, falls noch keine data/filmora_mcp_auth.json existiert.
    Überschreibt NIE eine bereits über die UI gesetzte URL."""
    return (os.environ.get("JARVIS_FILMORA_MCP_URL") or "").strip()


def is_configured() -> bool:
    a = _load()
    return bool(a.get("url") or _url_from_env())


def available() -> bool:
    return _HAS_HTTPX and is_configured()


def set_url(url: str) -> dict:
    url = (url or "").strip()
    if not url or not url.startswith(("http://", "https://")):
        return {"ok": False, "reason": "invalid_url"}
    with _lock:
        a = _load()
        a["url"] = url
        a["saved"] = time.time()
        # neue URL → alter Tool-Cache ist ungültig, Neuentdeckung erzwingen
        a.pop("tools", None)
        a.pop("tools_ts", None)
        a["last_error"] = ""
        _save(a)
    _session_cache.clear()
    return {"ok": True}


def clear() -> dict:
    try:
        _AUTH_PATH.unlink(missing_ok=True)
    except Exception:
        pass
    _session_cache.clear()
    return {"ok": True}


def _current_url() -> str:
    a = _load()
    return (a.get("url") or "").strip() or _url_from_env()


def get_status() -> dict:
    """Nie werfend — sicherer Status für die UI."""
    a = _load()
    url = _current_url()
    tools = a.get("tools") or []
    return {
        "connected":     bool(url) and bool(a.get("last_connect_ok")),
        "url_set":       bool(url),
        "tool_count":    len(tools),
        "tools":         [t.get("name", "") for t in tools if isinstance(t, dict)],
        "last_error":    a.get("last_error", ""),
        "last_checked":  a.get("tools_ts"),
        "httpx":         _HAS_HTTPX,
    }


# ── MCP-JSON-RPC über streamable HTTP (adaptiert aus higgsfield_mcp.py, ohne Auth) ──

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


def _headers(session_id: str = "") -> dict:
    h = {"Content-Type": "application/json",
         "Accept": "application/json, text/event-stream",
         "MCP-Protocol-Version": _PROTOCOL, "User-Agent": _UA}
    if session_id:
        h["Mcp-Session-Id"] = session_id
    return h


def _ensure_session(client: "httpx.Client", url: str) -> str:
    """Initialisiert eine MCP-Session und gibt die Session-ID zurück (best-effort)."""
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": _PROTOCOL, "capabilities": {},
        "clientInfo": {"name": "JARVIS", "version": "1.0"}}}
    r = client.post(url, headers=_headers(), json=init)
    sid = r.headers.get("mcp-session-id") or r.headers.get("Mcp-Session-Id") or ""
    try:
        client.post(url, headers=_headers(sid),
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    except Exception:
        pass
    return sid


def _get_session(client: "httpx.Client", url: str) -> str:
    """Wiederverwendet eine gecachte Session-ID (_SESSION_TTL) statt bei JEDEM Call
    einen vollen initialize-Handshake zu machen — wichtig für run_edit_job's
    Polling-Loop (sonst bis zu ~120 Handshakes für einen einzigen Job)."""
    with _lock:
        c = _session_cache.get(url)
        if c and time.time() - c["ts"] < _SESSION_TTL:
            return c["id"]
    sid = _ensure_session(client, url)
    with _lock:
        _session_cache[url] = {"id": sid, "ts": time.time()}
    return sid


def _invalidate_session(url: str) -> None:
    with _lock:
        _session_cache.pop(url, None)


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
    if not _HAS_HTTPX:
        raise RuntimeError("httpx fehlt (pip install httpx).")
    url = _current_url()
    if not url:
        raise RuntimeError("Filmora-MCP nicht verbunden — bitte persönliche MCP-URL einfügen.")
    with httpx.Client(timeout=timeout, headers={"User-Agent": _UA}) as client:
        sid = _get_session(client, url)
        req_id = secrets.randbelow(1_000_000) + 2
        body = {"jsonrpc": "2.0", "id": req_id, "method": "tools/call",
                "params": {"name": name, "arguments": arguments}}
        r = client.post(url, headers=_headers(sid), json=body)
        if r.status_code in (401, 403):
            _invalidate_session(url)
            raise RuntimeError("Filmora-MCP: Zugriff verweigert — persönliche URL evtl. "
                               "abgelaufen, bitte neu unter app.mushroom.viasocket.com/login holen.")
        if r.status_code >= 400:
            raise RuntimeError(f"Filmora-MCP {r.status_code}: {r.text[:200]}")
        return _result_payload(_parse(r), req_id)


def _fetch_tools_remote() -> list:
    """Standard-MCP tools/list gegen die konfigurierte URL."""
    if not _HAS_HTTPX:
        raise RuntimeError("httpx fehlt (pip install httpx).")
    url = _current_url()
    if not url:
        raise RuntimeError("Filmora-MCP nicht verbunden.")
    with httpx.Client(timeout=30, headers={"User-Agent": _UA}) as client:
        sid = _get_session(client, url)
        req_id = secrets.randbelow(1_000_000) + 2
        body = {"jsonrpc": "2.0", "id": req_id, "method": "tools/list", "params": {}}
        r = client.post(url, headers=_headers(sid), json=body)
        if r.status_code in (401, 403):
            _invalidate_session(url)
            raise RuntimeError("Filmora-MCP: Zugriff verweigert — URL evtl. abgelaufen.")
        if r.status_code >= 400:
            raise RuntimeError(f"Filmora-MCP {r.status_code}: {r.text[:200]}")
        for m in _parse(r):
            if m.get("id") == req_id and "result" in m:
                tools = (m["result"] or {}).get("tools") or []
                return [t for t in tools if isinstance(t, dict) and t.get("name")]
            if m.get("id") == req_id and "error" in m:
                raise RuntimeError(f"MCP-Fehler: {str(m['error'])[:200]}")
        return []


# ── Tool-Discovery (Cache, überlebt Fehler) ─────────────────────────────────────

def list_tools(force: bool = False) -> dict:
    """Gibt die zuletzt entdeckten Tools zurück; entdeckt neu, wenn Cache älter als
    _TOOLS_TTL ist oder force=True. Behält bei Fehler den ALTEN Cache (UI bleibt
    nutzbar), statt eine leere Liste zurückzugeben."""
    with _lock:
        a = _load()
        if not (a.get("url") or _url_from_env()):
            return {"ok": False, "reason": "not_connected", "tools": []}
        fresh = bool(a.get("tools")) and (time.time() - float(a.get("tools_ts", 0)) < _TOOLS_TTL)
        if fresh and not force:
            return {"ok": True, "tools": a["tools"], "cached": True}
    # Der Netzwerk-Call bleibt AUSSERHALB des Locks (kann Sekunden dauern) — nur das
    # Lesen/Schreiben der Datei ist atomar, damit zwei gleichzeitige Aufrufe (z.B. ein
    # frisches set_url() während eine alte list_tools()-Anfrage noch läuft) sich nicht
    # gegenseitig überschreiben.
    try:
        tools = _fetch_tools_remote()
        with _lock:
            a = _load()
            a["tools"] = tools
            a["tools_ts"] = time.time()
            a["last_error"] = ""
            _save(a)
        return {"ok": True, "tools": tools, "cached": False}
    except Exception as e:
        with _lock:
            a = _load()
            a["last_error"] = f"{type(e).__name__}: {e}"
            _save(a)
            cached_tools = a.get("tools", [])
        return {"ok": False, "reason": str(e), "tools": cached_tools}


def connect_test(url: "str | None" = None) -> dict:
    """Button-Handler: URL (optional) setzen + tools/list erzwingen."""
    if url:
        r = set_url(url)
        if not r.get("ok"):
            return r
    res = list_tools(force=True)
    with _lock:
        a = _load()
        a["last_connect_ok"] = bool(res.get("ok"))
        _save(a)
    if res.get("ok"):
        _log("success", f"Filmora-MCP verbunden — {len(res['tools'])} Tools entdeckt.")
        return {"ok": True, "tool_count": len(res["tools"]),
                "tools": [t.get("name", "") for t in res["tools"]]}
    return {"ok": False, "reason": res.get("reason", "unbekannter Fehler")}


# ── Tool-Matching (Anti-Blindflug: Keyword-Scoring statt geratener Namen) ───────

_EDIT_KEYWORDS = {"edit": 3, "video": 2, "youtube": 3, "import": 1, "download": 1,
                  "url": 1, "render": 1, "export": 1, "process": 1, "clip": 1,
                  "trim": 1, "cut": 1}
_STATUS_KEYWORDS = {"status": 3, "poll": 3, "progress": 2, "check": 2,
                    "result": 1, "job": 1, "task": 1}


def _score_tool(tool: dict, keywords: dict) -> int:
    text = f"{tool.get('name', '')} {tool.get('description', '')}".lower()
    return sum(w for kw, w in keywords.items() if kw in text)


def _build_arguments(tool: dict, youtube_url: str, instruction: str) -> dict:
    props = ((tool.get("inputSchema") or {}).get("properties")) or {}
    args: dict = {}
    if props:
        url_key = next((k for k in props
                        if re.search(r"url|link|source|youtube|video_?id", k, re.I)), None)
        text_key = next((k for k in props
                         if re.search(r"prompt|instruction|edit|description|task|command|text", k, re.I)), None)
        if url_key:
            args[url_key] = youtube_url
        if text_key:
            args[text_key] = instruction
    if not args:
        # Kein/leeres Schema → best-effort generischer Superset, deckt gängige Feldnamen ab.
        args = {"url": youtube_url, "video_url": youtube_url,
                "instruction": instruction, "prompt": instruction}
    return args


def resolve_edit_tool(youtube_url: str, instruction: str) -> dict:
    """Findet automatisch das passende Filmora-Tool für eine Bearbeitung. Eindeutig →
    {"ok": True, "tool", "arguments", "auto": True}. Mehrdeutig/kein Treffer →
    {"ok": False, "reason": "tool_unclear", "tools": [...]} — Frontend lässt manuell wählen."""
    res = list_tools()
    tools = res.get("tools") or []
    if not res.get("ok") and not tools:
        return {"ok": False, "reason": res.get("reason") or "not_connected"}
    scored = sorted(((_score_tool(t, _EDIT_KEYWORDS), t) for t in tools),
                    key=lambda x: -x[0])
    scored = [x for x in scored if x[0] > 0]
    if not scored:
        return {"ok": False, "reason": "tool_unclear", "tools": tools}
    best_score, best = scored[0]
    rivals = [t for s, t in scored[1:] if best_score - s < _AMBIGUITY_MARGIN]
    if rivals:
        return {"ok": False, "reason": "tool_unclear", "tools": [best] + rivals}
    args = _build_arguments(best, youtube_url, instruction)
    return {"ok": True, "tool": best["name"], "arguments": args, "auto": True}


def resolve_manual(tool_name: str, youtube_url: str, instruction: str) -> dict:
    """Wenn der Nutzer im Ambiguitäts-Picker manuell ein Tool wählt."""
    res = list_tools()
    tools = res.get("tools") or []
    tool = next((t for t in tools if t.get("name") == tool_name), None)
    if not tool:
        return {"ok": False, "reason": "tool_not_found"}
    args = _build_arguments(tool, youtube_url, instruction)
    return {"ok": True, "tool": tool["name"], "arguments": args, "auto": False}


def _find_status_tool() -> "dict | None":
    res = list_tools()
    tools = res.get("tools") or []
    scored = sorted(((_score_tool(t, _STATUS_KEYWORDS), t) for t in tools), key=lambda x: -x[0])
    scored = [x for x in scored if x[0] > 0]
    return scored[0][1] if scored else None


def _guess_id_key(tool: dict) -> str:
    props = ((tool.get("inputSchema") or {}).get("properties")) or {}
    key = next((k for k in props if re.search(r"id|job|task", k, re.I)), None)
    return key or "job_id"


def _extract_status(d: dict) -> str:
    if not isinstance(d, dict):
        return ""
    return str(d.get("status") or d.get("state") or "").lower()


def _extract_result_url(d: dict) -> str:
    if not isinstance(d, dict):
        return ""
    for key in ("result_url", "url", "video_url", "output_url", "download_url", "min_result_url"):
        v = d.get(key)
        if v:
            return str(v)
    for key in ("results", "outputs"):
        outs = d.get(key)
        if outs and isinstance(outs, list) and isinstance(outs[0], dict):
            for key2 in ("url", "result_url", "video_url"):
                v = outs[0].get(key2)
                if v:
                    return str(v)
    return ""


# ── Job-Ausführung (vom media_queue-Worker aufgerufen) ──────────────────────────

def _finalize(job_id: str, url: str, raw: dict) -> dict:
    """Download-Hedge: versucht das Ergebnis lokal zu speichern, fällt bei JEDEM
    Fehler auf den externen Link zurück statt den Job scheitern zu lassen."""
    if not url:
        return {"ok": True, "result_url": "", "raw": raw,
                "warning": "Kein Ergebnis-URL im Tool-Response gefunden."}
    try:
        _VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        out = _VIDEOS_DIR / f"filmora_{job_id}.mp4"
        with httpx.Client(timeout=180, headers={"User-Agent": _UA}) as c:
            resp = c.get(url)
            # Status prüfen, BEVOR gespeichert wird — ein abgelaufener/fehlerhafter
            # Ergebnis-Link liefert sonst eine HTML-Fehlerseite, die still als .mp4
            # gespeichert und als "fertig" gemeldet würde.
            if resp.status_code >= 400:
                raise RuntimeError(f"Download {resp.status_code}")
            out.write_bytes(resp.content)
        return {"ok": True, "result_url": f"/workspace/media/videos/{out.name}",
                "source_url": url, "raw": raw}
    except Exception:
        return {"ok": True, "result_url": url, "raw": raw}


def run_edit_job(job_id: str, tool_name: str, arguments: dict,
                 poll_timeout: int = 600) -> dict:
    """Ruft das Tool auf; liefert es direkt ein Ergebnis, ist der Job sofort fertig.
    Liefert es eine Job-ID, wird ein per Keyword gefundenes Status-Tool gepollt."""
    if not tool_name:
        raise RuntimeError("Kein Filmora-Tool angegeben.")
    res = call_tool(tool_name, arguments, timeout=90)
    job_ref = (res.get("job_id") or res.get("jobId") or res.get("id")
              or res.get("task_id") or res.get("taskId"))
    if not job_ref:
        return _finalize(job_id, _extract_result_url(res), res)

    status_tool = _find_status_tool()
    if status_tool is None:
        return {"ok": True, "result_url": _extract_result_url(res), "raw": res,
                "warning": "Kein Status-Tool gefunden — Ergebnis evtl. noch nicht fertig."}

    id_key = _guess_id_key(status_tool)
    end = time.time() + poll_timeout
    while time.time() < end:
        st = call_tool(status_tool["name"], {id_key: job_ref})
        s = _extract_status(st)
        if s in ("completed", "succeeded", "success", "done", "finished"):
            return _finalize(job_id, _extract_result_url(st), st)
        if s in ("failed", "error", "cancelled"):
            raise RuntimeError(f"Filmora-Job-Status: {s}")
        time.sleep(float(st.get("poll_after_seconds") or 5) if isinstance(st, dict) else 5)
    raise TimeoutError("Filmora-MCP: Timeout beim Warten auf das bearbeitete Video.")


# ── CLI: Verbindungstest ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "connect" and len(sys.argv) > 2:
        print(json.dumps(connect_test(sys.argv[2]), ensure_ascii=False))
    elif cmd == "tools":
        print(json.dumps(list_tools(force=True), ensure_ascii=False))
    else:
        print(json.dumps(get_status(), ensure_ascii=False))
