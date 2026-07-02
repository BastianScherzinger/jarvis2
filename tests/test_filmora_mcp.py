"""
Tests für filmora_mcp.py + video_prompt.py — netzwerkfrei (tmp_path/monkeypatch),
keine echten HTTP-Calls gegen viaSocket.
"""
import pytest


# ── URL-Speicherung / Status ────────────────────────────────────────────────────

def test_set_url_status_clear_roundtrip(tmp_path, monkeypatch):
    import filmora_mcp as fm
    monkeypatch.setattr(fm, "_AUTH_PATH", tmp_path / "filmora_mcp_auth.json")
    assert fm.is_configured() is False
    assert fm.get_status()["url_set"] is False

    r = fm.set_url("https://app.mushroom.viasocket.com/mcp/abc123")
    assert r["ok"] is True
    assert fm.is_configured() is True
    st = fm.get_status()
    assert st["url_set"] is True
    assert st["connected"] is False          # noch kein connect_test gelaufen

    r2 = fm.clear()
    assert r2["ok"] is True
    assert fm.is_configured() is False
    assert fm.get_status()["url_set"] is False


def test_set_url_rejects_invalid(tmp_path, monkeypatch):
    import filmora_mcp as fm
    monkeypatch.setattr(fm, "_AUTH_PATH", tmp_path / "filmora_mcp_auth.json")
    r = fm.set_url("not-a-url")
    assert r["ok"] is False and r["reason"] == "invalid_url"
    assert fm.is_configured() is False


# ── Tool-Discovery-Cache ─────────────────────────────────────────────────────────

def test_list_tools_not_connected(tmp_path, monkeypatch):
    import filmora_mcp as fm
    monkeypatch.setattr(fm, "_AUTH_PATH", tmp_path / "filmora_mcp_auth.json")
    r = fm.list_tools()
    assert r["ok"] is False and r["reason"] == "not_connected" and r["tools"] == []


def test_list_tools_cache_hit(tmp_path, monkeypatch):
    import filmora_mcp as fm
    monkeypatch.setattr(fm, "_AUTH_PATH", tmp_path / "filmora_mcp_auth.json")
    fm.set_url("https://example.com/mcp/x")
    calls = {"n": 0}
    def _fake_fetch():
        calls["n"] += 1
        return [{"name": "video_edit", "description": "Edit a video"}]
    monkeypatch.setattr(fm, "_fetch_tools_remote", _fake_fetch)

    r1 = fm.list_tools()
    r2 = fm.list_tools()
    assert calls["n"] == 1                    # zweiter Call nutzt den Cache
    assert r1["ok"] and r2["ok"] and r2["cached"] is True

    r3 = fm.list_tools(force=True)
    assert calls["n"] == 2 and r3["cached"] is False


def test_list_tools_keeps_old_cache_on_error(tmp_path, monkeypatch):
    import filmora_mcp as fm
    monkeypatch.setattr(fm, "_AUTH_PATH", tmp_path / "filmora_mcp_auth.json")
    fm.set_url("https://example.com/mcp/x")
    good_tools = [{"name": "video_edit", "description": "Edit a video"}]
    monkeypatch.setattr(fm, "_fetch_tools_remote", lambda: good_tools)
    fm.list_tools(force=True)                 # Cache füllen

    def _boom():
        raise RuntimeError("MCP 500")
    monkeypatch.setattr(fm, "_fetch_tools_remote", _boom)
    r = fm.list_tools(force=True)
    assert r["ok"] is False
    assert r["tools"] == good_tools            # alter Cache bleibt erhalten


# ── Tool-Matching ────────────────────────────────────────────────────────────────

def test_resolve_edit_tool_auto_pick(tmp_path, monkeypatch):
    import filmora_mcp as fm
    monkeypatch.setattr(fm, "_AUTH_PATH", tmp_path / "filmora_mcp_auth.json")
    fm.set_url("https://example.com/mcp/x")
    tools = [
        {"name": "youtube_video_edit", "description": "Edit a video from a YouTube URL",
         "inputSchema": {"properties": {"source_url": {}, "edit_prompt": {}}}},
        {"name": "list_projects", "description": "List Filmora projects"},
    ]
    monkeypatch.setattr(fm, "_fetch_tools_remote", lambda: tools)
    fm.list_tools(force=True)

    res = fm.resolve_edit_tool("https://youtube.com/watch?v=abc", "Intro kürzen")
    assert res["ok"] is True
    assert res["tool"] == "youtube_video_edit"
    assert res["auto"] is True


def test_resolve_edit_tool_ambiguous(tmp_path, monkeypatch):
    import filmora_mcp as fm
    monkeypatch.setattr(fm, "_AUTH_PATH", tmp_path / "filmora_mcp_auth.json")
    fm.set_url("https://example.com/mcp/x")
    tools = [
        {"name": "video_import", "description": "Import a video"},
        {"name": "video_export", "description": "Export a video"},
    ]
    monkeypatch.setattr(fm, "_fetch_tools_remote", lambda: tools)
    fm.list_tools(force=True)

    res = fm.resolve_edit_tool("https://youtube.com/watch?v=abc", "irgendwas")
    assert res["ok"] is False
    assert res["reason"] == "tool_unclear"
    assert len(res["tools"]) == 2


def test_resolve_edit_tool_no_candidates(tmp_path, monkeypatch):
    import filmora_mcp as fm
    monkeypatch.setattr(fm, "_AUTH_PATH", tmp_path / "filmora_mcp_auth.json")
    fm.set_url("https://example.com/mcp/x")
    tools = [{"name": "list_projects", "description": "List projects"}]
    monkeypatch.setattr(fm, "_fetch_tools_remote", lambda: tools)
    fm.list_tools(force=True)

    res = fm.resolve_edit_tool("https://youtube.com/watch?v=abc", "irgendwas")
    assert res["ok"] is False and res["reason"] == "tool_unclear"
    assert res["tools"] == tools


def test_resolve_edit_tool_not_connected(tmp_path, monkeypatch):
    import filmora_mcp as fm
    monkeypatch.setattr(fm, "_AUTH_PATH", tmp_path / "filmora_mcp_auth.json")
    res = fm.resolve_edit_tool("https://youtube.com/watch?v=abc", "irgendwas")
    assert res["ok"] is False
    assert res["reason"] == "not_connected"


def test_resolve_manual(tmp_path, monkeypatch):
    import filmora_mcp as fm
    monkeypatch.setattr(fm, "_AUTH_PATH", tmp_path / "filmora_mcp_auth.json")
    fm.set_url("https://example.com/mcp/x")
    tools = [{"name": "video_import", "description": "Import a video",
             "inputSchema": {"properties": {"url": {}, "prompt": {}}}}]
    monkeypatch.setattr(fm, "_fetch_tools_remote", lambda: tools)
    fm.list_tools(force=True)

    ok = fm.resolve_manual("video_import", "https://youtube.com/x", "trim it")
    assert ok["ok"] is True and ok["tool"] == "video_import" and ok["auto"] is False

    bad = fm.resolve_manual("does_not_exist", "https://youtube.com/x", "trim it")
    assert bad["ok"] is False and bad["reason"] == "tool_not_found"


# ── Argument-Mapping ─────────────────────────────────────────────────────────────

def test_build_arguments_schema_mapping():
    import filmora_mcp as fm
    tool = {"name": "x", "inputSchema": {"properties": {"source_url": {}, "edit_prompt": {}}}}
    args = fm._build_arguments(tool, "https://yt/x", "kürzen")
    assert args == {"source_url": "https://yt/x", "edit_prompt": "kürzen"}


def test_build_arguments_no_schema_fallback():
    import filmora_mcp as fm
    args = fm._build_arguments({"name": "x"}, "https://yt/x", "kürzen")
    assert args["url"] == "https://yt/x" and args["video_url"] == "https://yt/x"
    assert args["instruction"] == "kürzen" and args["prompt"] == "kürzen"


# ── Ergebnis-URL-Extraktion ──────────────────────────────────────────────────────

def test_extract_result_url_common_keys():
    import filmora_mcp as fm
    assert fm._extract_result_url({"result_url": "https://a"}) == "https://a"
    assert fm._extract_result_url({"outputs": [{"url": "https://b"}]}) == "https://b"
    assert fm._extract_result_url({"nothing": True}) == ""
    assert fm._extract_result_url({}) == ""


def test_extract_status_and_id_key():
    import filmora_mcp as fm
    assert fm._extract_status({"status": "Completed"}) == "completed"
    assert fm._extract_status({"state": "FAILED"}) == "failed"
    assert fm._extract_status({}) == ""
    assert fm._guess_id_key({"inputSchema": {"properties": {"jobId": {}}}}) == "jobId"
    assert fm._guess_id_key({"inputSchema": {"properties": {}}}) == "job_id"


# ── run_edit_job: synchrones Tool (kein Job-Ref) ─────────────────────────────────

def test_run_edit_job_synchronous_result(tmp_path, monkeypatch):
    import filmora_mcp as fm
    monkeypatch.setattr(fm, "_VIDEOS_DIR", tmp_path / "videos")
    monkeypatch.setattr(fm, "call_tool",
                        lambda name, args, timeout=60: {"result_url": "https://done/video.mp4"})
    # Deterministisch KEIN echter Netzwerk-Call: httpx.Client durch einen Fake ersetzt,
    # der garantiert (ohne DNS/Netz) fehlschlägt → _finalize fällt auf den externen Link zurück.
    class _FailingClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **k): raise RuntimeError("kein Netzwerk in Tests")
    fake_httpx = type("FakeHttpx", (), {"Client": _FailingClient})
    monkeypatch.setattr(fm, "httpx", fake_httpx)

    res = fm.run_edit_job("job1", "edit_video", {"url": "x"})
    assert res["ok"] is True
    assert res["result_url"] == "https://done/video.mp4"


def test_finalize_rejects_error_response_falls_back_to_link(tmp_path, monkeypatch):
    # Ein abgelaufener/fehlerhafter Ergebnis-Link liefert eine HTML-Fehlerseite (Status
    # >=400) — die darf NICHT als gültiges Video gespeichert werden, sondern muss auf
    # den externen Link zurückfallen.
    import filmora_mcp as fm
    monkeypatch.setattr(fm, "_VIDEOS_DIR", tmp_path / "videos")

    class _FakeResp:
        status_code = 404
        content = b"<html>not found</html>"

    class _FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **k): return _FakeResp()

    monkeypatch.setattr(fm, "httpx", type("FakeHttpx", (), {"Client": _FakeClient}))
    res = fm._finalize("job1", "https://expired/video.mp4", {})
    assert res["ok"] is True
    assert res["result_url"] == "https://expired/video.mp4"     # Fallback, kein lokaler Pfad
    assert not (tmp_path / "videos" / "filmora_job1.mp4").exists()


def test_run_edit_job_no_tool_name_raises(tmp_path, monkeypatch):
    import filmora_mcp as fm
    with pytest.raises(RuntimeError):
        fm.run_edit_job("job1", "", {})


# ── Session-Caching (verhindert Handshake-Spam im Polling-Loop) ──────────────────

def test_get_session_reused_within_ttl(tmp_path, monkeypatch):
    import filmora_mcp as fm
    monkeypatch.setattr(fm, "_AUTH_PATH", tmp_path / "filmora_mcp_auth.json")
    fm._session_cache.clear()
    calls = {"n": 0}
    def _fake_ensure(client, url):
        calls["n"] += 1
        return "sid-123"
    monkeypatch.setattr(fm, "_ensure_session", _fake_ensure)

    sid1 = fm._get_session(None, "https://x/mcp")
    sid2 = fm._get_session(None, "https://x/mcp")
    assert sid1 == sid2 == "sid-123"
    assert calls["n"] == 1                     # zweiter Aufruf nutzt den Cache

    fm._invalidate_session("https://x/mcp")
    fm._get_session(None, "https://x/mcp")
    assert calls["n"] == 2                     # nach Invalidierung neuer Handshake


# ── video_prompt.py ──────────────────────────────────────────────────────────────

def test_improve_instruction_fallback_without_ollama(monkeypatch):
    import video_prompt as vp
    import scrapers._http as http
    def _boom(*a, **k):
        raise RuntimeError("Ollama offline")
    monkeypatch.setattr(http, "ask_ollama", _boom)
    r = vp.improve_instruction("  schneid mal das intro raus bitte  ")
    assert r["ok"] is True and r["source"] == "fallback"
    assert r["improved"].startswith("Schneid") and r["improved"].endswith(".")


def test_improve_instruction_uses_ollama(monkeypatch):
    import video_prompt as vp
    import scrapers._http as http
    monkeypatch.setattr(http, "ask_ollama", lambda *a, **k: "Entferne die ersten 5 Sekunden.")
    r = vp.improve_instruction("intro weg")
    assert r["ok"] is True and r["source"] == "ollama"
    assert r["improved"] == "Entferne die ersten 5 Sekunden."


def test_improve_instruction_empty():
    import video_prompt as vp
    assert vp.improve_instruction("")["ok"] is False


def test_chat_reply_never_crashes_without_ollama(monkeypatch):
    import video_prompt as vp
    import scrapers._http as http
    def _boom(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(http, "ask_ollama", _boom)
    r = vp.chat_reply("Wie schneide ich ein YouTube-Video?")
    assert r["ok"] is True and r["source"] == "fallback" and r["looks_like_edit"] is True


def test_chat_reply_uses_ollama(monkeypatch):
    import video_prompt as vp
    import scrapers._http as http
    monkeypatch.setattr(http, "ask_ollama", lambda *a, **k: "Fügen Sie den Link oben ein.")
    r = vp.chat_reply("Wie geht das?")
    assert r["ok"] is True and r["source"] == "ollama"
