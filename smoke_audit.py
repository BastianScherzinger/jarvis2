"""
Einmaliger Selbsttest: hittet alle ungefährlichen GET-Routen + prüft Kernmodule.
Destruktive/teure Routen (clear, start, reeval, media-generate, chat) bewusst ausgespart.
Lauf:  python smoke_audit.py
"""
import json
import traceback

PASS, FAIL = [], []


def check(name, fn):
    try:
        fn()
        PASS.append(name)
    except Exception as e:
        FAIL.append((name, f"{type(e).__name__}: {e}"))


import app  # noqa: E402  (bootet DBs + Routen)
import db_raw, db_evaluated  # noqa: E402

c = app.app.test_client()

# Synthetischer Lead für ID-abhängige Routen
db_raw.init_db(); db_evaluated.init_db()
_rid = db_raw.insert_raw({"name": "Audit Testbetrieb", "stadt": "ZZAUDIT", "branche": "Test",
                          "bundesland": "Bayern", "finder": "maps", "has_website": 0})


def get_ok(path, allowed=(200,)):
    def _():
        r = c.get(path)
        assert r.status_code in allowed, f"{path} -> {r.status_code}"
    return _


# ── GET-Routen ────────────────────────────────────────────────────────────────
for path in ["/", "/api/claude/status", "/api/email/status", "/api/evaluated/all",
             "/api/evaluated/stats", "/api/evaluated/top", "/api/export/csv",
             "/api/graph/nodes", "/api/graph/stats", "/api/logs", "/api/media/gallery",
             "/api/media/jobs", "/api/media/models", "/api/media/status", "/api/metrics",
             "/api/status", "/api/top", "/api/voice/status", "/api/websites", "/favicon.ico"]:
    check(f"GET {path}", get_ok(path, allowed=(200, 204)))

check("GET /api/lead/<id>/competition", get_ok(f"/api/lead/{_rid}/competition"))
check("GET /api/website/job/unknown -> 404", get_ok("/api/website/job/nope", allowed=(404,)))
check("GET /api/verifier/model", get_ok("/api/verifier/model"))   # ruft ollama_models (tolerant)

# ── Kernmodule ────────────────────────────────────────────────────────────────
check("leadkey", lambda: __import__("leadkey").lead_key("X", "Y"))
check("name_clean.quick_clean", lambda: __import__("agents.name_clean", fromlist=["x"]).quick_clean("F0507 Test GmbH GmbH"))
check("quality.is_real_business", lambda: __import__("agents.quality", fromlist=["x"]).is_real_business({"name": "Müller GmbH", "telefon": "030 1"}))
check("db_raw.get_dashboard_stats", lambda: db_raw.get_dashboard_stats())
check("db_raw.get_competition", lambda: db_raw.get_competition("ZZAUDIT", "Test"))
check("db_raw.get_by_id", lambda: db_raw.get_by_id(_rid))
check("db_evaluated.get_stats", lambda: db_evaluated.get_stats())
check("db_evaluated.get_typ_counts", lambda: db_evaluated.get_typ_counts())
check("db_evaluated.get_top", lambda: db_evaluated.get_top(3))
check("agent_github.is_ready", lambda: __import__("agent_github").is_ready())
check("agent_railway.is_ready", lambda: __import__("agent_railway").is_ready())
check("agent_shop.is_available", lambda: __import__("agent_shop").is_available())
check("website_builder.is_available", lambda: __import__("website_builder").is_available())
check("db_websites.get_all", lambda: __import__("db_websites").get_all())
check("website_builder.find_built_sites", lambda: __import__("website_builder").find_built_sites())
check("website_improve premium template", lambda: (_ for _ in ()).throw(AssertionError("leer"))
      if not __import__("website_improve")._PREMIUM_HTML.strip() else None)
check("app._build_offer_email", lambda: __import__("app")._build_offer_email("X", "https://y")[0])
check("agent_github.diagnose", lambda: __import__("agent_github").diagnose())
check("agent_railway.diagnose", lambda: __import__("agent_railway").diagnose())
check("metrics snapshot", lambda: __import__("metrics").snapshot())
check("voice_web.status", lambda: __import__("voice_web").status())
check("config.get_api_key", lambda: bool(__import__("config").get_api_key()))
check("media_engine.get_status", lambda: __import__("media_engine").get_status())
check("cloud_sync.make_lead_key", lambda: __import__("cloud_sync").make_lead_key("A", "B"))

# agent_tools: Schema-Validität + ein DB-lesendes Tool
def _tools():
    import agent_tools
    assert isinstance(agent_tools.TOOLS, list) and len(agent_tools.TOOLS) >= 10
    for t in agent_tools.TOOLS:
        assert t.get("name") and t.get("input_schema"), t.get("name")
    r = agent_tools.run("leads_top", {"limit": 3})
    assert "text" in r and "ok" in r
check("agent_tools.TOOLS + run(leads_top)", _tools)

# ── Aufräumen ────────────────────────────────────────────────────────────────
import sqlite3
for p, tbl in [("data/leads_raw.db", "raw_leads"), ("data/leads_evaluated.db", "evaluated_leads")]:
    try:
        cx = sqlite3.connect(p); cx.execute(f"DELETE FROM {tbl} WHERE stadt='ZZAUDIT'"); cx.commit(); cx.close()
    except Exception:
        pass

# ── Report ───────────────────────────────────────────────────────────────────
print("\n================ AUDIT-ERGEBNIS ================")
print(f"PASS: {len(PASS)}   FAIL: {len(FAIL)}")
if FAIL:
    print("\n--- FEHLER ---")
    for name, err in FAIL:
        print(f"  ✗ {name}: {err}")
else:
    print("Alle Checks grün.")
