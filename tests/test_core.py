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
    assert row.get("live", 0) == 0           # neu: verifiziertes live-Flag, Default 0
    # update setzt erlaubte Felder + serialisiert log als Liste zurück
    dbw.update("job-aaa", status="running", progress=42, step="baut", live=1,
               live_url="https://x.up.railway.app", log=[{"p": 42, "t": "baut"}])
    row = dbw.get(wid)
    assert row["status"] == "running" and row["progress"] == 42
    assert row["live_url"].endswith("railway.app") and row["live"] == 1
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


# ── Deploy-Diagnose (ohne Tokens → ehrliche Fehlmeldung, kein Crash) ──────────
def test_github_diagnose_ohne_token(monkeypatch):
    import agent_github
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    d = agent_github.diagnose()
    assert d["ok"] is False and d["present"] is False
    assert "GITHUB_TOKEN" in d["msg"]


def test_railway_diagnose_ohne_token(monkeypatch):
    import agent_railway
    monkeypatch.delenv("RAILWAY_TOKEN", raising=False)
    monkeypatch.delenv("RAILWAY_API_TOKEN", raising=False)
    d = agent_railway.diagnose()
    assert d["ok"] is False and d["present"] is False
    assert "RAILWAY_TOKEN" in d["msg"]


def test_deploy_status_struktur(monkeypatch):
    import website_builder
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("RAILWAY_TOKEN", raising=False)
    s = website_builder.deploy_status()
    assert set(["ready", "git", "github", "railway"]).issubset(s.keys())
    assert s["ready"] is False               # ohne Tokens nie bereit
    txt = website_builder.deploy_status_text()
    assert "GitHub" in txt and "Railway" in txt
    assert txt.isascii()                     # Kunden-Konsole (cp1252) sicher


def test_find_built_sites_ist_liste(tmp_path, monkeypatch):
    import website_builder
    monkeypatch.setattr(website_builder, "_SHOP_BASE", tmp_path)
    # leerer Ordner → leere Liste
    assert website_builder.find_built_sites() == []
    # ein gebauter Ordner (mit content.json) → wird gefunden
    d = tmp_path / "web_demo-gmbh"
    d.mkdir()
    (d / "content.json").write_text('{"site_name": "Demo GmbH"}', encoding="utf-8")
    sites = website_builder.find_built_sites()
    assert len(sites) == 1 and sites[0]["name"] == "Demo GmbH"
    assert sites[0]["slug"] == "web_demo-gmbh"


# ── Webseiten-Verbesserung + Angebots-Mail (reine Helfer) ─────────────────────
def test_improve_premium_template_valides_django():
    # Premium-Template muss als Django-Template kompilieren + alle Sektionen rendern.
    import django
    from django.conf import settings
    if not settings.configured:
        settings.configure(
            TEMPLATES=[{"BACKEND": "django.template.backends.django.DjangoTemplates",
                        "DIRS": [], "APP_DIRS": False, "OPTIONS": {}}],
            INSTALLED_APPS=["django.contrib.staticfiles"], STATIC_URL="/static/")
        django.setup()
    from django.template import engines
    import website_improve
    tpl = engines["django"].from_string(website_improve._PREMIUM_HTML)
    c = {"seo_title": "T", "seo_desc": "D", "akzent": "#123456", "site_name": "Demo",
         "branche": "Elektro", "stadt": "Ulm", "telefon": "1", "email": "a@b.de",
         "adresse": "Str", "headline": "H", "subline": "S", "cta_text": "CTA",
         "kontakt_text": "K", "ueber_titel": "U", "ueber_text": "UT",
         "hero_image": "/h.png", "about_image": "/u.png", "fotos": ["/x", "/y"],
         "usps": ["A", "B"], "leistungen": [{"titel": "L", "text": "t"}],
         "faq": [{"frage": "F?", "antwort": "A"}], "jahr": 2026}
    html = tpl.render({"c": c})
    assert "usp-dot" in html and "faq-item" in html and "about-img" in html


def test_improve_extract_json():
    import website_improve
    assert website_improve._extract_json('vor {"a":1} nach') == {"a": 1}
    assert website_improve._extract_json("kein json") is None


def test_offer_email_enthaelt_link_und_preis():
    import app
    betreff, text, html = app._build_offer_email("Müller GmbH", "https://x.up.railway.app",
                                                 "Dachdecker", "Köln")
    assert "Müller GmbH" in betreff               # Name im Betreff (Preis steht im Body)
    assert "https://x.up.railway.app" in text and "https://x.up.railway.app" in html
    assert "350" in text and "350" in html        # Angebot
    assert "Bastian Scherzinger" in text


def test_db_websites_kontakt_email(tmp_path, monkeypatch):
    dbw = _tmp_websites_db(tmp_path, monkeypatch)
    wid = dbw.create("job-mail", name="Foo", kontakt_email="info@foo.de")
    assert dbw.get(wid)["kontakt_email"] == "info@foo.de"
    # idempotenter create füllt die Mail nach, falls vorher leer
    dbw.create("job-mail2", name="Bar")
    dbw.create("job-mail2", name="Bar", kontakt_email="kontakt@bar.de")
    assert dbw.get_by_job("job-mail2")["kontakt_email"] == "kontakt@bar.de"


# ── Cross-PC-Sync der Webseiten ───────────────────────────────────────────────
def test_db_websites_site_key_und_upsert_remote(tmp_path, monkeypatch):
    dbw = _tmp_websites_db(tmp_path, monkeypatch)
    from leadkey import lead_key
    wid = dbw.create("job-sk", name="Demo GmbH", stadt="Ulm")
    sk = lead_key("Demo GmbH", "Ulm")
    assert dbw.get(wid)["site_key"] == sk                  # create berechnet site_key
    # Remote-Upsert einer NEUEN Seite → wird angelegt
    dbw.upsert_remote({"site_key": "rk1", "name": "Remote AG", "stadt": "Köln",
                       "live_url": "https://x.up.railway.app", "live": 1, "status": "done",
                       "images": ["https://cdn/x.png"], "kontakt_email": "a@b.de"})
    r = dbw.get_by_site_key("rk1")
    assert r and r["live_url"].endswith("railway.app") and r["images"] == ["https://cdn/x.png"]
    assert r["live"] == 1 and r["kontakt_email"] == "a@b.de"
    # zweiter Upsert mit gleichem site_key → UPDATE, kein Duplikat
    dbw.upsert_remote({"site_key": "rk1", "name": "Remote AG", "stadt": "Köln",
                       "live_url": "https://neu.up.railway.app", "status": "done"})
    assert len([w for w in dbw.get_all() if w["site_key"] == "rk1"]) == 1
    assert dbw.get_by_site_key("rk1")["live_url"].startswith("https://neu")


def test_locations_aggregiert(monkeypatch, tmp_path):
    # get_locations aggregiert je Stadt mit Typ-Zählung (für den 3D-Globus).
    import db_evaluated
    monkeypatch.setattr(db_evaluated, "DB_PATH", tmp_path / "ev.db")
    db_evaluated.init_db()
    for i, typ in enumerate(("Hot", "Warm", "Warm")):
        db_evaluated.insert_evaluated({"name": f"Betrieb{i}", "stadt": "Ulm",
                                       "bundesland": "Baden-Württemberg", "lead_typ": typ,
                                       "lead_key": f"key-{i}"})
    locs = db_evaluated.get_locations()
    ulm = next((l for l in locs if l["stadt"] == "Ulm"), None)
    assert ulm and ulm["n"] == 3 and ulm["warm"] == 2 and ulm["hot"] == 1


def test_offer_mail_build():
    import offer_mail
    betreff, text, html = offer_mail.build("Müller GmbH", "https://x.up.railway.app", "Dachdecker", "Köln")
    assert "Müller GmbH" in betreff               # Name im Betreff (Preis im Body)
    assert "350" in text and "350" in html
    assert "https://x.up.railway.app" in text and "https://x.up.railway.app" in html


def test_offer_mail_normalisiert_schema():
    # Nackte Railway-Domain ohne Schema → href bekommt https:// (sonst kaputter Link).
    import offer_mail
    assert offer_mail._norm_url("web-x.up.railway.app") == "https://web-x.up.railway.app"
    assert offer_mail._norm_url("https://x.de") == "https://x.de"
    assert offer_mail._norm_url("(Link folgt)") == ""
    assert offer_mail._norm_url("") == ""
    _b, _t, html = offer_mail.build("Foo", "web-foo.up.railway.app", "Maler", "Bonn")
    assert "https://web-foo.up.railway.app" in html
    assert 'href="("' not in html and "(Link folgt)" not in html


def test_offer_mail_ohne_link_kein_kaputter_button():
    # Ohne gültigen Live-Link wird KEIN kaputter „Webseite ansehen"-Button gerendert.
    import offer_mail
    _b, text, html = offer_mail.build("Ohne Link", "", "Maler", "Bonn")
    assert "(Link folgt)" not in html and 'href=""' not in html
    assert "🌐 Webseite ansehen" not in html
    assert "Live-Link" in text


def test_offer_mail_persoenliche_anrede():
    import offer_mail
    _b, text, _h = offer_mail.build("Foo", "https://x.de", "Maler", "Bonn", "Max Mustermann")
    assert "Guten Tag Max Mustermann" in text
    _b2, text2, _h2 = offer_mail.build("Foo", "https://x.de", "Maler", "Bonn")
    assert "Guten Tag," in text2


def test_website_improve_sanitize_haertet_typen():
    # Falsch typisierte Felder dürfen das Django-Template nicht crashen lassen.
    import website_improve as wi
    clean = wi._sanitize_content({
        "site_name": "Demo", "leistungen": "kein-array", "usps": [None, "Schnell", ""],
        "faq": [{"frage": "F?", "antwort": "A"}, "kaputt"], "fotos": "nope",
        "akzent": "rot", "jahr": "2026"})
    assert clean["leistungen"] == [] and clean["fotos"] == []
    assert clean["usps"] == ["Schnell"]
    assert clean["faq"] == [{"frage": "F?", "antwort": "A"}]
    assert clean["akzent"] == "#c8102e" and clean["jahr"] == 2026


def test_website_improve_render_check(tmp_path):
    # Render-QA muss eine gehärtete content.json fehlerfrei durch das Template rendern.
    import website_improve as wi
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "index.html").write_text(wi._PREMIUM_HTML, encoding="utf-8")
    content = wi._sanitize_content({"site_name": "Demo", "branche": "Elektro",
                                    "stadt": "Ulm", "headline": "H", "cta_text": "CTA"})
    ok, err = wi._render_check(tmp_path, content)
    assert ok, err


def test_db_websites_set_contact(tmp_path, monkeypatch):
    dbw = _tmp_websites_db(tmp_path, monkeypatch)
    wid = dbw.create("job-c", name="Foo", stadt="Ulm")
    dbw.set_contact(wid, "info@foo.de", "Max Muster")
    row = dbw.get(wid)
    assert row["kontakt_email"] == "info@foo.de" and row["ansprechpartner"] == "Max Muster"
    # leere Werte überschreiben Vorhandenes NICHT
    dbw.set_contact(wid, "", "")
    row2 = dbw.get(wid)
    assert row2["kontakt_email"] == "info@foo.de" and row2["ansprechpartner"] == "Max Muster"


def test_contact_finder_graceful_ohne_treffer(monkeypatch):
    # Findet web_analyst nichts, liefert contact_finder ein sauberes leeres Ergebnis
    # (Places-Fallback gemockt → kein Netzwerk-Call im Test).
    import contact_finder
    import agents.evaluator.web_analyst as wa
    import agent_maps
    monkeypatch.setattr(wa, "analyze", lambda lead: {
        "email_adresse": "", "email_alle": [], "ansprechpartner": "", "discovered_website": ""})
    monkeypatch.setattr(agent_maps, "place_contact", lambda name, stadt="": {})
    res = contact_finder.find("Irgendein Betrieb", "Ulm", "Maler")
    assert res["ok"] is False and res["email"] == "" and res["email_alle"] == []


def test_hardware_profile():
    import hardware_profile as hp
    p = hp.profile()
    assert p["tier"] in ("server", "workstation", "desktop", "laptop", "low")
    for k in ("image_steps", "improve_images", "media_parallel", "nightly_improve_per_cycle"):
        assert isinstance(p[k], int) and p[k] >= 1
    assert isinstance(hp.summary(), str) and hp.summary().isascii()   # cp1252-sicher
    assert hp.get("improve_images") == p["improve_images"]


def test_hardware_profile_tier_override(monkeypatch):
    import hardware_profile as hp
    monkeypatch.setenv("JARVIS_PERF_TIER", "server")
    assert hp.tier() == "server"
    assert hp.profile()["improve_images"] == 6 and hp.profile()["media_parallel"] == 4


def test_qa_security_clean():
    import qa_security
    r = qa_security.run_all()
    assert r["summary"]["compile_ok"] is True
    # Die Security-Hinweise INNERHALB der Agenten-Prompts (team.py) dürfen NICHT
    # als echte Findings durchschlagen (kein False-Positive).
    assert r["summary"]["high"] == 0
    assert isinstance(qa_security.report_text(), str)


def test_tts_local_only(monkeypatch):
    import tts
    monkeypatch.setenv("JARVIS_TTS_LOCAL", "1")
    assert tts._local_only() is True
    assert "lokal" in tts.backend_name().lower()
    monkeypatch.delenv("JARVIS_TTS_LOCAL", raising=False)
    assert tts._local_only() is False


def test_media_queue_cloud_routing():
    import media_queue
    assert "higgsfield" in media_queue._CLOUD_KINDS
    assert "higgsfield_image" in media_queue._CLOUD_KINDS
    assert "image" not in media_queue._CLOUD_KINDS and "video" not in media_queue._CLOUD_KINDS


def test_perf_and_qa_routes():
    import app
    c = app.app.test_client()
    rp = c.get("/api/perf").get_json()
    assert rp["ok"] and rp["profile"]["tier"]
    rq = c.get("/api/qa").get_json()
    assert rq["ok"] and rq["summary"]["compile_ok"] is True


def test_feature_backlog():
    import feature_backlog as fb
    feats = fb.features_for("Dachdecker Müller")
    keys = [f["key"] for f in feats]
    assert "notdienst" in keys and "faq" in keys          # branche + generisch
    content = {}
    f1 = fb.next_feature("Dachdecker", content)
    assert f1 and f1["key"] == feats[0]["key"]
    fb.mark_done(content, f1["key"])
    f2 = fb.next_feature("Dachdecker", content)
    assert f2 and f2["key"] != f1["key"]
    # unbekannte Branche → nur generische Features
    assert all(f["key"] in {g["key"] for g in fb._GENERIC}
               for f in fb.features_for("Irgendwas"))


def _mk_site(tmp_path):
    import website_improve
    (tmp_path / "templates").mkdir()
    (tmp_path / "static" / "css").mkdir(parents=True)
    (tmp_path / "templates" / "index.html").write_text(website_improve._PREMIUM_HTML, encoding="utf-8")
    (tmp_path / "static" / "css" / "style.css").write_text("body{}", encoding="utf-8")
    import json as _j
    (tmp_path / "content.json").write_text(_j.dumps({"site_name": "Demo", "branche": "Elektro",
        "stadt": "Ulm", "headline": "H", "cta_text": "CTA", "akzent": "#123456", "jahr": 2026}),
        encoding="utf-8")
    return tmp_path


def test_local_tools_sandbox_und_ops(tmp_path):
    import local_tools
    _mk_site(tmp_path)
    t = local_tools.SiteTools(tmp_path)
    assert "content.json" in t.list_dir("")
    assert "Demo" in t.read_content()
    # Path-Traversal wird blockiert
    assert "[Fehler]" in t.read_file("../../etc/passwd")
    assert "[Fehler]" in t.write_file("../escape.txt", "x")
    # write + replace
    assert "[OK]" in t.write_file("static/css/extra.css", ".x{}")
    assert "[OK]" in t.replace_in_file("static/css/extra.css", ".x{}", ".x{color:red}")
    assert "color:red" in t.read_file("static/css/extra.css")
    # render_check rendert das Premium-Template
    assert "[OK]" in t.render_check()
    # dispatch + unbekanntes Tool
    assert "[Fehler] unbekanntes Tool" in t.dispatch("nope", {})


def test_local_tools_snapshot_restore(tmp_path):
    import local_tools, json as _j
    _mk_site(tmp_path)
    t = local_tools.SiteTools(tmp_path)
    snap = t.snapshot()
    assert "content.json" in snap
    t.write_content({"site_name": "Kaputt"})       # Änderung
    assert "Kaputt" in t.read_content()
    t.restore(snap)                                  # zurück
    assert "Demo" in t.read_content() and "Kaputt" not in t.read_content()


def test_local_coder_plan_fallback(monkeypatch, tmp_path):
    import local_coder, config
    _mk_site(tmp_path)
    monkeypatch.setattr(config, "get_api_key", lambda: "")   # kein Key → generische Spec
    spec = local_coder.plan_feature(str(tmp_path), {"label": "FAQ", "spec": "Baue FAQ-Sektion."}, "Elektro")
    assert spec == "Baue FAQ-Sektion."
    assert local_coder._extract_json('x {"a":1} y') == {"a": 1}


def test_claude_coder_basics():
    import claude_coder
    assert isinstance(claude_coder.is_available(), bool)
    p = claude_coder.build_prompt("Baue eine Öffnungszeiten-Box.", "Friseur")
    assert "Öffnungszeiten" in p and "content.json" in p


def test_auto_builder_deep_step_off(monkeypatch):
    import auto_builder
    monkeypatch.setattr(auto_builder, "_NIGHTLY_DEEP", "off")
    assert auto_builder._deep_step("x", "y", "z") == {"ok": False, "reason": "off"}


def test_auto_builder_daily_log(tmp_path, monkeypatch):
    import auto_builder
    monkeypatch.setattr(auto_builder, "_LOG_PATH", tmp_path / "daily_builds.json")
    assert auto_builder._count_today() == 0
    auto_builder._record({"name": "Foo GmbH", "stadt": "Ulm", "link": "https://x.de",
                          "email": "info@foo.de"})
    auto_builder._record({"name": "Bar AG", "stadt": "Köln", "link": "", "email": ""})
    assert auto_builder._count_today() == 2
    dl = auto_builder.daily_log()
    assert dl["daily_limit"] == auto_builder._DAILY_LIMIT
    today = auto_builder._today()
    sites = next(d["sites"] for d in dl["days"] if d["date"] == today)
    assert [s["name"] for s in sites] == ["Foo GmbH", "Bar AG"]
    assert sites[0]["email"] == "info@foo.de"


def test_auto_builder_cutoff_and_status(monkeypatch):
    import auto_builder
    # _before_cutoff vergleicht mit der Cutoff-Stunde
    monkeypatch.setattr(auto_builder, "_IMPROVE_UNTIL", 24)
    assert auto_builder._before_cutoff() is True
    monkeypatch.setattr(auto_builder, "_IMPROVE_UNTIL", 0)
    assert auto_builder._before_cutoff() is False
    s = auto_builder.status()
    for k in ("running", "today_count", "daily_limit", "phase"):
        assert k in s


def test_website_builder_tagesordner():
    import website_builder, time
    d = website_builder._unique_dir("test-betrieb")
    # …/jarvis_websites/<JJJJ-MM-TT>/web_test-betrieb
    assert d.name.startswith("web_test-betrieb")
    assert d.parent.name == time.strftime("%Y-%m-%d")
    assert d.parent.parent.name == "jarvis_websites"


def test_offer_email_preview_route(monkeypatch):
    import app, db_websites
    monkeypatch.setattr(db_websites, "get", lambda wid: {
        "id": wid, "name": "Müller GmbH", "branche": "Dachdecker", "stadt": "Köln",
        "live_url": "", "kontakt_email": "info@m.de", "ansprechpartner": ""})
    c = app.app.test_client()
    r = c.get("/api/websites/1/offer-email/preview")
    d = r.get_json()
    # leerer Live-Link → kein Netzwerk-Call, link="", link_ok False, aber Vorschau ok
    assert d["ok"] and d["to"] == "info@m.de" and d["link"] == "" and d["link_ok"] is False
    assert "350" in d["html"]


def test_media_hardware_info_hat_ram():
    import media_engine
    hw = media_engine.hardware_info()
    assert "ram_gb" in hw and isinstance(hw["ram_gb"], (int, float))
    assert hw["device"] in ("cpu", "cuda", "mps")
    s = media_engine.get_status()
    assert "ram_gb" in s and "video_local_ok" in s and s.get("empfehlung")


def test_media_resolve_image_model(monkeypatch):
    import media_engine
    # Explizite, bekannte Angabe gewinnt immer.
    assert media_engine._resolve_image_model("sdxl") == "sdxl"
    # Leere Angabe -> hardware-bestes Modell (Auto = Default), liegt in IMAGE_MODELS.
    auto = media_engine._resolve_image_model("")
    assert auto in media_engine.IMAGE_MODELS
    # JARVIS_IMAGE_AUTO=0 -> statt Auto das .env-Modell (get_active_image_model).
    monkeypatch.setattr(media_engine, "_env", lambda k, d="": "0" if k == "JARVIS_IMAGE_AUTO" else d)
    monkeypatch.setattr(media_engine, "get_active_image_model", lambda: "sdxl")
    assert media_engine._resolve_image_model("") == "sdxl"


def test_server_config(monkeypatch):
    import app
    for k in ("JARVIS_HOST", "JARVIS_PORT", "PORT", "JARVIS_THREADS", "JARVIS_SERVER", "JARVIS_PROD"):
        monkeypatch.delenv(k, raising=False)
    cfg = app.server_config()
    assert cfg["host"] == "0.0.0.0" and cfg["port"] == 5000 and cfg["prod"] is False
    assert 8 <= cfg["threads"] <= 32
    monkeypatch.setenv("JARVIS_PORT", "8080")
    monkeypatch.setenv("JARVIS_THREADS", "16")
    monkeypatch.setenv("JARVIS_SERVER", "1")
    cfg2 = app.server_config()
    assert cfg2["port"] == 8080 and cfg2["threads"] == 16 and cfg2["prod"] is True


def test_ad_prompts_video_prompt():
    import ad_prompts
    vp = ad_prompts.build_video_prompt({"branche": "Dachdecker", "stil": "cinematisch",
                                        "betrieb": "Müller GmbH"})
    assert "prompt" in vp and "summary" in vp and len(vp["prompt"]) > 30
    assert "Werbevideo" in vp["summary"] and "Müller GmbH" in vp["summary"]
    assert "no text" in vp["prompt"].lower()


def test_media_image_higgsfield_backend(monkeypatch):
    # backend=higgsfield -> Queue-Job 'higgsfield_image' (kein lokaler Diffusers-Lauf).
    import app, media_queue
    cap = {}
    monkeypatch.setattr(media_queue, "submit",
                        lambda kind, params: (cap.update(kind=kind, params=params), "jid")[1])
    c = app.app.test_client()
    r = c.post("/api/media/generate/image", json={"prompt": "ein haus", "backend": "higgsfield"})
    assert r.get_json().get("ok") and cap["kind"] == "higgsfield_image"
    # backend=local -> normaler image-Job
    c.post("/api/media/generate/image", json={"prompt": "ein haus", "backend": "local"})
    assert cap["kind"] == "image"


def test_media_ad_video_route(monkeypatch):
    import app, media_queue
    cap = {}
    monkeypatch.setattr(media_queue, "submit",
                        lambda kind, params: (cap.update(kind=kind, params=params), "jid")[1])
    c = app.app.test_client()
    r = c.post("/api/media/generate/ad-video", json={"branche": "Dachdecker", "backend": "local"})
    d = r.get_json()
    assert d.get("ok") and d.get("prompt") and cap["kind"] == "video"
    # higgsfield-Backend -> higgsfield-Video-Job
    c.post("/api/media/generate/ad-video", json={"betrieb": "Foo", "backend": "higgsfield"})
    assert cap["kind"] == "higgsfield"
    # ohne jeden Brief -> 400
    r2 = c.post("/api/media/generate/ad-video", json={})
    assert r2.status_code == 400


def test_contact_finder_extrahiert_email(monkeypatch):
    # web_analyst liefert E-Mail + Ansprechpartner → contact_finder reicht sie sauber durch.
    import contact_finder
    import agents.evaluator.web_analyst as wa
    monkeypatch.setattr(wa, "analyze", lambda lead: {
        "email_adresse": "info@betrieb.de", "email_alle": ["info@betrieb.de", "chef@betrieb.de"],
        "ansprechpartner": "Anna Beispiel", "discovered_website": "https://betrieb.de"})
    res = contact_finder.find("Betrieb", "Ulm", "Maler")
    assert res["ok"] and res["email"] == "info@betrieb.de"
    assert "chef@betrieb.de" in res["email_alle"]
    assert res["ansprechpartner"] == "Anna Beispiel" and res["website"] == "https://betrieb.de"


def test_auto_builder_pick_next_lead(monkeypatch):
    import db_evaluated, db_websites, auto_builder
    from leadkey import lead_key
    leads = [
        {"name": "MitWeb GmbH", "stadt": "Ulm", "has_website": 1, "erwartungswert_euro": 9000},
        {"name": "OhneWeb GmbH", "stadt": "Köln", "has_website": 0, "erwartungswert_euro": 5000},
    ]
    monkeypatch.setattr(db_evaluated, "get_all", lambda **k: leads)
    monkeypatch.setattr(db_websites, "get_all", lambda: [])
    # Lead MIT Website wird übersprungen → der ohne Website wird gewählt
    assert auto_builder._pick_next_lead()["name"] == "OhneWeb GmbH"
    # schon gebaut (site_key in db_websites) → übersprungen → None
    monkeypatch.setattr(db_websites, "get_all",
                        lambda: [{"site_key": lead_key("OhneWeb GmbH", "Köln")}])
    assert auto_builder._pick_next_lead() is None


def test_cloud_sync_websites_helpers():
    import cloud_sync_websites as cw
    from leadkey import lead_key
    assert cw.site_key("Müller GmbH", "Berlin") == lead_key("Müller GmbH", "Berlin")
    rr = cw._remote_row({"name": "X", "stadt": "Y", "branche": "Z", "live_url": "u",
                         "live": 1, "images": ["a"], "kontakt_email": "k@l.de"})
    assert rr["site_key"] == lead_key("X", "Y") and rr["images"] == ["a"] and rr["live"] == 1


# ── Discord-Freigabe: Voting-Gate (Daumen hoch/runter) ────────────────────────
def test_review_queue_voting(tmp_path, monkeypatch):
    import review_queue as rq
    monkeypatch.setattr(rq, "_PATH", tmp_path / "reviews.json")
    monkeypatch.setenv("DISCORD_APPROVALS_NEEDED", "2")
    r = rq.add("Betrieb", "Berlin", "Dachdecker", "https://x.up.railway.app", "a@b.de")
    assert r["status"] == rq.PENDING
    # eine Stimme reicht noch nicht
    assert rq.vote(r["id"], "u1", True)["status"] == rq.PENDING
    # zweite Stimme gibt frei
    assert rq.vote(r["id"], "u2", True)["status"] == rq.APPROVED
    assert len(rq.approved_unsent()) == 1
    # ein Daumen-runter ist ein Veto
    assert rq.vote(r["id"], "u3", False)["status"] == rq.REJECTED
    assert rq.approved_unsent() == []


def test_review_queue_doppelstimme_zaehlt_einmal(tmp_path, monkeypatch):
    import review_queue as rq
    monkeypatch.setattr(rq, "_PATH", tmp_path / "reviews.json")
    monkeypatch.setenv("DISCORD_APPROVALS_NEEDED", "2")
    r = rq.add("B", "S", "Br", "https://x")
    rq.vote(r["id"], "u1", True)
    res = rq.vote(r["id"], "u1", True)         # derselbe User nochmal
    assert len(res["votes_up"]) == 1 and res["status"] == rq.PENDING


def test_review_queue_owner_whitelist(tmp_path, monkeypatch):
    import review_queue as rq
    monkeypatch.setattr(rq, "_PATH", tmp_path / "reviews.json")
    r = rq.add("B", "S", "Br", "https://x")
    assert rq.vote(r["id"], "fremd", True, owners=["1", "2"]) == {"error": "not_owner"}


def test_discord_bot_import_safe():
    # Ohne Token/Library muss der Bot ein No-op sein und das System nie blockieren.
    import discord_bot
    assert discord_bot.enabled() is False
    st = discord_bot.status()
    assert "enabled" in st and "send_hour" in st
    # submit_for_review darf ohne laufenden Bot einfach None liefern (kein Crash)
    assert discord_bot.submit_for_review("X", "Y", "Z", "https://x") is None


def test_mcp_bridge_schema_und_safe():
    import mcp_bridge
    info = mcp_bridge.selftest()
    namen = info["tools"]
    assert "write_file" in namen and "render_check" in namen
    # available() darf nie crashen (ollama optional)
    assert isinstance(mcp_bridge.available(), bool)


# ── Angebots-Mail: bessere, variierende Betreffzeilen ─────────────────────────
def test_offer_mail_betreff_variiert_und_ohne_spam():
    import offer_mail
    b1, _, _ = offer_mail.build("Alpha GmbH", "https://a.up.railway.app", "Dachdecker", "Berlin")
    b2, _, _ = offer_mail.build("Beta KG", "https://b.up.railway.app", "Friseur", "Köln")
    assert b1 and b2 and "\n" not in b1
    # kein Spam-Trigger im Betreff (kein €, kein !!!)
    assert "€" not in b1 and "!!!" not in b1
    # ohne Live-Link greift der andere Betreff-Pool
    b3, _, _ = offer_mail.build("Gamma", "", "Elektriker", "")
    assert b3 and "€" not in b3
