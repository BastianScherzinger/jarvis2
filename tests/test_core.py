"""
Erste Unit-Tests für die reinen (I/O-freien) Kernfunktionen.
Ausführen:  python -m pytest -q   (im Projekt-Stammverzeichnis)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Dedup-Schlüssel ───────────────────────────────────────────────────────────
def test_leadkey_stabil_und_case_insensitiv():
    from leadkey import lead_key
    assert lead_key("Dachdecker Müller", "Berlin") == lead_key("dachdecker müller", "berlin")
    assert lead_key(" Müller ", " Berlin ") == lead_key("Müller", "Berlin")
    assert lead_key("A", "X") != lead_key("B", "X")
    assert len(lead_key("x", "y")) == 32  # md5-hex


def test_leadkey_eine_quelle():
    # db_evaluated + cloud_sync delegieren an dieselbe Definition
    from leadkey import lead_key
    import db_evaluated, cloud_sync
    assert db_evaluated._compute_lead_key("Schmidt", "Köln") == lead_key("Schmidt", "Köln")
    assert cloud_sync.make_lead_key("Schmidt", "Köln") == lead_key("Schmidt", "Köln")


# ── Qualitätsfilter (Marktplätze raus, echte Betriebe rein) ───────────────────
def test_quality_marktplaetze_gefiltert():
    from agents.quality import is_real_business
    for portal in ["MyHammer Handwerker", "Handwerkskammer Berlin", "Check24 Vergleich",
                   "Blauarbeit Profi", "wlw Eintrag"]:
        ok, _ = is_real_business({"name": portal, "telefon": "030 1"})
        assert not ok, portal


def test_quality_echte_betriebe_durch():
    from agents.quality import is_real_business
    for name in ["Dachdeckerei Müller GmbH", "Listemann GmbH", "Findeisen Elektro"]:
        ok, grund = is_real_business({"name": name, "telefon": "030 1"})
        assert ok, f"{name}: {grund}"


def test_quality_generisch_und_kurz():
    from agents.quality import is_real_business
    assert not is_real_business({"name": "Ergebnisse", "telefon": "030"})[0]
    assert not is_real_business({"name": "AB", "telefon": "030"})[0]
    assert not is_real_business({"name": "Echte Firma"})[0]  # keine Kontaktdaten


# ── JSON-Extraktion (robust gegen abgeschnittenes/verrauschtes Ollama-JSON) ───
def test_extract_json():
    from scrapers._http import extract_json
    assert extract_json('{"anpassung": 5}') == {"anpassung": 5}
    assert extract_json('Text {"a": 7, "b": 80} Ende {"x":1}') == {"a": 7, "b": 80}
    assert extract_json('{"text":"nutze {var}","a":2}') == {"text": "nutze {var}", "a": 2}
    assert extract_json('{"a": 5, "abgeschnitten') == {}   # kaputt → {}
    assert extract_json("") == {}


# ── Website-Helfer ────────────────────────────────────────────────────────────
def test_domain_kein_lstrip_bug():
    from agents.evaluator.web_analyst import _domain
    assert _domain("https://www.wuermtal-bau.de/x") == "wuermtal-bau.de"
    assert _domain("https://web-mueller.de") == "web-mueller.de"   # 'w' nicht abgeschnitten


def test_website_lehnt_ad_redirects_ab():
    # DDG/Bing-Werbe-Redirects sind KEINE eigene Website (Datenqualitäts-Bug)
    from agents.evaluator.web_analyst import _ist_eigene_domain, _pick_website
    ad = "https://duckduckgo.com/y.js?ad_domain=3t-motors.de&ad_provider=bingv7aa"
    assert _ist_eigene_domain(ad) is False
    assert _ist_eigene_domain("https://www.bing.com/aclick?ld=abc") is False
    # echte Seite kommt durch
    assert _ist_eigene_domain("https://www.ruth-bauelemente.de/") is True
    # _pick_website überspringt den Ad-Treffer und nimmt die echte Seite
    hits = [{"url": ad}, {"url": "https://ruth-bauelemente.de/"}]
    assert _pick_website({"name": "Ruth Bauelemente", "stadt": "Lingen"}, hits) == "https://ruth-bauelemente.de/"


def test_ansprechpartner_aus_impressum():
    from agents.evaluator.web_analyst import _ansprechpartner
    assert _ansprechpartner("<p>Geschäftsführer: Max Mustermann</p>") == "Max Mustermann"
    assert _ansprechpartner("kein Name hier") == ""


# ── Website-Builder (reine Helfer, ohne Netz/I/O) ─────────────────────────────
def test_website_slug():
    from website_builder import _slug
    assert _slug("Müller & Söhne GmbH") == "mueller-und-soehne-gmbh"
    assert _slug("  Dachdecker  Aichach ") == "dachdecker-aichach"
    assert _slug("") == "kunde"


def test_website_content_akzent_nach_branche():
    from website_builder import _deterministic_content
    c = _deterministic_content({"name": "X", "branche": "Elektro Meier", "stadt": "Ulm"}, [])
    assert c["akzent"] == "#d98a00"          # Elektro-Heuristik
    assert c["site_name"] == "X"
    assert len(c["leistungen"]) == 3
    assert c["fotos"] == []


def test_website_extract_json_balanciert():
    from website_builder import _extract_json
    assert _extract_json('vor {"a":1,"b":"x"} nach') == {"a": 1, "b": "x"}
    assert _extract_json("kein json") is None
    assert _extract_json('{"t":"mit }klammer"}') == {"t": "mit }klammer"}


def test_deploy_clients_ohne_token(monkeypatch):
    # Ohne Tokens müssen die Clients sauber 'nicht bereit' melden, nichts werfen.
    import agent_github, agent_railway
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("RAILWAY_TOKEN", raising=False)
    monkeypatch.delenv("RAILWAY_API_TOKEN", raising=False)
    assert agent_github.is_ready() is False
    assert agent_railway.is_ready() is False
    assert agent_github.create_repo("x")["ok"] is False
    assert agent_railway.deploy("x", "u/r", {})["ok"] is False


# ── Hardware-abhängige Bildmodell-Wahl ────────────────────────────────────────
def test_hardware_aware_image_model():
    import media_engine as me
    hw = me.hardware_info()
    assert hw["device"] in ("cuda", "mps", "cpu")
    hp = me.hero_image_params()
    assert hp["model_key"] in me.IMAGE_MODELS
    assert hp["steps"] >= 1 and hp["width"] >= 256 and hp["height"] >= 256
    # ohne GPU MUSS das schnelle Modell gewählt werden (kein SDXL-Minutenlauf auf CPU)
    if hw["device"] == "cpu":
        assert me.best_image_model() == "sd-turbo"
        assert hp["model_key"] == "sd-turbo"


# ── Higgsfield-Cloud-Fallback (reine Helfer, ohne Netz) ───────────────────────
def test_higgsfield_helpers():
    import media_engine as me
    # Auth-Format-Erkennung: KEY_ID:KEY_SECRET → 'Key …', sonst 'Bearer …'
    assert me._hf_headers("abc:def")["Authorization"] == "Key abc:def"
    assert me._hf_headers("sk-tok")["Authorization"] == "Bearer sk-tok"
    # Bild-URL aus verschiedenen Antwortformen
    assert me._hf_extract_image_url(
        {"jobs": [{"results": {"raw": {"url": "http://x/i.png"}}}]}) == "http://x/i.png"
    assert me._hf_extract_image_url({"outputs": ["http://y/o.png"]}) == "http://y/o.png"
    assert me._hf_extract_image_url({}) == ""
    # Ohne Key wirft die Cloud-Generierung → Aufrufer fällt auf lokal zurück.
    # Nur prüfen, wenn wirklich kein Key gesetzt ist (sonst echter API-Call).
    if not me._hf_key():
        import pytest
        with pytest.raises(Exception):
            me.generate_image_higgsfield("test")


# ── Sicherheits-Score (deterministisch, ohne Ollama) ──────────────────────────
def test_sicherheit_erreichbar_vs_kette():
    from agents.evaluator.score_writer import _sicherheit
    erreichbar, _ = _sicherheit(
        {"adresse": "Hauptstr 1"}, {"email_vorhanden": 1, "telefon_verifiziert": 1, "has_website": 1},
        {}, rev=20, ist_privat=1, firmengroesse="1-2 Personen")
    kette, _ = _sicherheit(
        {"adresse": ""}, {"email_vorhanden": 0, "telefon_verifiziert": 0, "has_website": 0},
        {}, rev=0, ist_privat=0, firmengroesse="Kette")
    assert erreichbar >= 70
    assert kette == 0   # Kette-Malus zieht auf 0 (geclampt)


# ── Firmennamen-Säuberung (quick_clean, deterministisch, ohne Netz/KI) ────────
def test_nameclean_rolladen_spam_kuerzer_und_ohne_wiederholung():
    from agents.name_clean import quick_clean
    roh = ("C.W Service Hamburg Tag & Nacht Rolladen Reparatur "
           "Service Rolladenreparatur")
    out = quick_clean(roh)
    assert len(out) < len(roh)                 # deutlich kürzer
    assert out.lower().count("service") == 1   # keine Service-Wiederholung
    assert out.lower().count("rolladen") == 1  # kein Rolladen-Stamm doppelt
    assert out.startswith("C.W Service Hamburg")  # Kern bleibt erhalten


def test_nameclean_fuehrender_code_entfernt():
    from agents.name_clean import quick_clean
    assert quick_clean("F0507 Robin Look GmbH") == "Robin Look GmbH"
    assert quick_clean("A1234 Beispiel GmbH") == "Beispiel GmbH"
    assert quick_clean("B-123 Muster AG") == "Muster AG"


def test_nameclean_gute_namen_unveraendert():
    from agents.name_clean import quick_clean
    for name in ["Umzüge S. Klein GmbH & Co. KG",
                 "Dachdeckerei Müller GmbH",
                 "Listemann GmbH"]:
        assert quick_clean(name) == name


def test_nameclean_marketing_anhaengsel_abgeschnitten():
    from agents.name_clean import quick_clean
    out = quick_clean("Dachdecker Schmidt - Ihr Partner seit 1990")
    assert out == "Dachdecker Schmidt"


def test_nameclean_case_normalisierung():
    from agents.name_clean import quick_clean
    assert quick_clean("MUELLER GMBH") == "Mueller Gmbh"     # komplett groß
    assert quick_clean("dachdecker mueller") == "Dachdecker Mueller"  # komplett klein


def test_nameclean_nie_leer():
    from agents.name_clean import quick_clean
    assert quick_clean("   ") == ""        # echtes Leer bleibt leer
    assert quick_clean("X GmbH") != ""


def test_nameclean_whitespace_gefaltet():
    from agents.name_clean import quick_clean
    # gemischte Schreibweise bleibt erhalten (GmbH wird NICHT zu Gmbh)
    assert quick_clean("  Mehrere    Leerzeichen  GmbH ") == "Mehrere Leerzeichen GmbH"


def test_nameclean_idempotent():
    from agents.name_clean import quick_clean
    beispiele = [
        "C.W Service Hamburg Tag & Nacht Rolladen Reparatur Service Rolladenreparatur",
        "F0507 Robin Look GmbH",
        "Umzüge S. Klein GmbH & Co. KG",
        "Dachdeckerei Müller GmbH",
        "MUELLER GMBH",
        "Dachdecker Schmidt - Ihr Partner seit 1990",
        "  Mehrere    Leerzeichen  GmbH ",
    ]
    for x in beispiele:
        once = quick_clean(x)
        assert quick_clean(once) == once, x


# ── Webseiten-Persistenz (db_websites, temporäre DB) ──────────────────────────
def _tmp_websites_db(tmp_path, monkeypatch):
    import db_websites
    from pathlib import Path
    monkeypatch.setattr(db_websites, "DB_PATH", Path(tmp_path) / "websites.db")
    db_websites.init_db()
    return db_websites


def test_db_websites_create_get_update(tmp_path, monkeypatch):
    dbw = _tmp_websites_db(tmp_path, monkeypatch)
    wid = dbw.create("job-aaa", name="Foo GmbH", stadt="Ulm", branche="Elektro", lead_id=7)
    assert isinstance(wid, int) and wid > 0
    # idempotent: gleicher job_id legt KEINE zweite Zeile an
    assert dbw.create("job-aaa", name="Foo GmbH") == wid
    row = dbw.get_by_job("job-aaa")
    assert row["name"] == "Foo GmbH" and row["status"] == "queued" and row["lead_id"] == 7
    assert row["images"] == [] and row["log"] == []
    # update setzt erlaubte Felder + serialisiert log als Liste zurück
    dbw.update("job-aaa", status="running", progress=42, step="baut",
               live_url="https://x.up.railway.app", log=[{"p": 42, "t": "baut"}])
    row = dbw.get(wid)
    assert row["status"] == "running" and row["progress"] == 42
    assert row["live_url"].endswith("railway.app")
    assert row["log"] == [{"p": 42, "t": "baut"}]


def test_db_websites_update_ignoriert_fremde_spalten(tmp_path, monkeypatch):
    dbw = _tmp_websites_db(tmp_path, monkeypatch)
    dbw.create("job-bbb", name="Bar")
    # nicht-erlaubte Spalte wird stillschweigend ignoriert (kein Crash, keine Wirkung)
    dbw.update("job-bbb", name="GEHACKT", status="done")
    row = dbw.get_by_job("job-bbb")
    assert row["name"] == "Bar" and row["status"] == "done"


def test_db_websites_add_image_dedup(tmp_path, monkeypatch):
    dbw = _tmp_websites_db(tmp_path, monkeypatch)
    wid = dbw.create("job-ccc", name="Baz")
    dbw.add_image(wid, "a.png")
    dbw.add_image(wid, "a.png")   # Duplikat → nur einmal
    dbw.add_image(wid, "b.png")
    assert dbw.get(wid)["images"] == ["a.png", "b.png"]


def test_db_websites_get_all_neueste_zuerst(tmp_path, monkeypatch):
    dbw = _tmp_websites_db(tmp_path, monkeypatch)
    import time
    dbw.create("job-1", name="Erste")
    time.sleep(0.01)
    dbw.create("job-2", name="Zweite")
    namen = [w["name"] for w in dbw.get_all()]
    assert namen[:2] == ["Zweite", "Erste"]
