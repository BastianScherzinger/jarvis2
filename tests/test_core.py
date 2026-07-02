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


# ── Alt-Ordner-Umzug (Desktop/web_* → jarvis_websites/<Datum>/) ───────────────
def test_migrate_legacy_folders_moves_real_website(tmp_path, monkeypatch):
    import website_builder, time
    monkeypatch.setattr(website_builder, "_SHOP_BASE", tmp_path)
    legacy = tmp_path / "web_alte-firma"
    legacy.mkdir()
    (legacy / "content.json").write_text('{"site_name": "Alte Firma"}', encoding="utf-8")

    res = website_builder.migrate_legacy_website_folders()
    assert len(res["moved"]) == 1 and res["errors"] == []
    assert not legacy.exists()                            # aus der flachen Ablage weg
    today = time.strftime("%Y-%m-%d")
    target = tmp_path / "jarvis_websites" / today / "web_alte-firma"
    assert target.is_dir() and (target / "content.json").exists()

    # Idempotent: zweiter Lauf findet nichts mehr
    res2 = website_builder.migrate_legacy_website_folders()
    assert res2["moved"] == [] and res2["errors"] == []


def test_migrate_legacy_folders_ignores_unrelated_dirs(tmp_path, monkeypatch):
    # Ordner die NICHT wie web_* heißen ODER keine JARVIS-Seite sind (kein content.json/
    # manage.py) dürfen NIE angefasst werden — Sicherheitsnetz gegen versehentliches
    # Verschieben fremder Desktop-Ordner.
    import website_builder
    monkeypatch.setattr(website_builder, "_SHOP_BASE", tmp_path)
    unrelated = tmp_path / "Urlaubsfotos"
    unrelated.mkdir()
    (unrelated / "irgendwas.txt").write_text("x", encoding="utf-8")
    fake_web = tmp_path / "web_ohne_inhalt"          # heißt web_* aber KEINE JARVIS-Seite
    fake_web.mkdir()

    res = website_builder.migrate_legacy_website_folders()
    assert res["moved"] == []
    assert unrelated.exists() and fake_web.exists()   # beide unberührt


def test_migrate_legacy_folders_erkennt_unvollstaendigen_bau(tmp_path, monkeypatch):
    # Realer Bugreport (02.07.2026, Kollegen-PC): ein web_*-Ordner mit einem abgebrochenen
    # Bau (kein content.json/manage.py, aber z.B. schon ein requirements.txt vom Scaffold)
    # wurde bisher NIE gefunden -- "keine verstreuten Alt-Ordner gefunden" trotz sichtbarem
    # Ordner. Jetzt reicht IRGENDEIN Bau-Signal.
    import website_builder
    monkeypatch.setattr(website_builder, "_SHOP_BASE", tmp_path)
    partial = tmp_path / "web_volker-werner-physiotherapeut"
    partial.mkdir()
    (partial / "requirements.txt").write_text("Django\n", encoding="utf-8")

    res = website_builder.migrate_legacy_website_folders()
    assert len(res["moved"]) == 1 and res["errors"] == []
    assert not partial.exists()


def test_migrate_legacy_folders_findet_eine_ebene_tiefer(tmp_path, monkeypatch):
    # Realer Fund (02.07.2026): Sir hatte einen Sammelordner "generated websites" von
    # Hand angelegt, DARIN lagen die web_*-Ordner — nicht direkt auf dem Desktop. Der
    # reine Top-Level-Glob fand sie darum nie. Jetzt: eine Unterordner-Ebene tiefer
    # wird ebenfalls durchsucht, fremde Unterordner ohne web_*-Kinder bleiben unberührt.
    import website_builder, time
    monkeypatch.setattr(website_builder, "_SHOP_BASE", tmp_path)
    container = tmp_path / "generated websites"
    container.mkdir()
    legacy = container / "web_tief-verschachtelt"
    legacy.mkdir()
    (legacy / "content.json").write_text('{"site_name": "Tief"}', encoding="utf-8")
    # Fremder Sammelordner OHNE web_*-Kinder — darf nicht durchwühlt/verändert werden.
    fremd = tmp_path / "webseiten buisnes"
    fremd.mkdir()
    (fremd / "irgendein_projekt").mkdir()

    res = website_builder.migrate_legacy_website_folders()
    assert len(res["moved"]) == 1 and res["errors"] == []
    assert not legacy.exists()
    today = time.strftime("%Y-%m-%d")
    target = tmp_path / "jarvis_websites" / today / "web_tief-verschachtelt"
    assert target.is_dir() and (target / "content.json").exists()
    assert (fremd / "irgendein_projekt").exists()          # fremder Ordner unangetastet

    # Idempotent: zweiter Lauf findet nichts mehr (auch nicht im Container)
    res2 = website_builder.migrate_legacy_website_folders()
    assert res2["moved"] == [] and res2["errors"] == []


def test_migrate_legacy_folders_updates_db_folder(tmp_path, monkeypatch):
    import website_builder
    import db_websites
    from pathlib import Path
    monkeypatch.setattr(website_builder, "_SHOP_BASE", tmp_path)
    monkeypatch.setattr(db_websites, "DB_PATH", Path(tmp_path) / "websites.db")
    db_websites.init_db()
    legacy = tmp_path / "web_firma-x"
    legacy.mkdir()
    (legacy / "manage.py").write_text("", encoding="utf-8")
    db_websites.create("job-legacy-1", "Firma X", "Ulm", "Dachdecker")
    db_websites.update("job-legacy-1", folder=str(legacy))

    website_builder.migrate_legacy_website_folders()
    row = db_websites.get_by_job("job-legacy-1")
    assert row["folder"] != str(legacy)
    assert Path(row["folder"]).name == "web_firma-x"
    assert Path(row["folder"]).is_dir()               # DB zeigt auf den neuen, existierenden Ort


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
    assert "Müller GmbH" in betreff               # Name im Betreff
    assert "https://x.up.railway.app" in text and "https://x.up.railway.app" in html
    import offer_mail
    assert "kostenlos" in text.lower()             # KOSTENLOS, kein Festpreis mehr
    assert "fairen preis" in text.lower()          # "sehr fairer Preis" statt fixer Betrag
    assert offer_mail._wvm()["person"] in text     # konfigurierter Absender (WVM-IT)


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
    assert "Müller GmbH" in betreff               # Name im Betreff
    assert "kostenlos" in text.lower() and "kostenlos" in html.lower()   # KOSTENLOS
    assert "fairen preis" in text.lower()         # "sehr fairer Preis", kein fixer Betrag
    assert "pystore.de" in html.lower()           # Referenzen/Kundenerfahrungen
    assert "wvm-it.tech" in html.lower()          # Rechnungs-/Firmen-Domain
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
    import db_websites
    import cost_tracker
    monkeypatch.setattr(auto_builder, "_LOG_PATH", tmp_path / "daily_builds.json")
    # Paid-Boost deterministisch AUS — sonst hinge der Assert unten an der echten
    # data/costs.json bzw. den konfigurierten ANTHROPIC-Keys der Maschine.
    monkeypatch.setattr(cost_tracker, "paid_boost_active", lambda: False)
    assert auto_builder._count_today() == 0
    fa = tmp_path / "web_foo"; fa.mkdir()
    fb = tmp_path / "web_bar"; fb.mkdir()
    auto_builder._record({"name": "Foo GmbH", "stadt": "Ulm", "link": "https://x.de",
                          "email": "info@foo.de", "folder": str(fa)})
    auto_builder._record({"name": "Bar AG", "stadt": "Köln", "link": "", "email": "",
                          "folder": str(fb)})
    # _count_today zählt nur AKTIVE (nicht-archivierte) Seiten → beide Ordner aktiv in der DB.
    monkeypatch.setattr(db_websites, "get_all",
                        lambda *a, **k: [{"folder": str(fa), "archived": 0},
                                         {"folder": str(fb), "archived": 0}])
    assert auto_builder._count_today() == 2
    # Archiviert man eine (nicht mehr in get_all), zählt nur noch die andere → Builder baut nach.
    monkeypatch.setattr(db_websites, "get_all",
                        lambda *a, **k: [{"folder": str(fa), "archived": 0}])
    assert auto_builder._count_today() == 1
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
    assert "kostenlos" in d["html"].lower()         # KOSTENLOSE Webseite (kein Festpreis mehr)


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


# ── Video-Studio: direkte Werkzeug-Steuerung (jedes Filmora-Tool manuell) ───────
def test_vs_run_tool_route(monkeypatch):
    import app, media_queue, filmora_mcp
    monkeypatch.setattr(filmora_mcp, "is_configured", lambda: True)
    cap = {}
    monkeypatch.setattr(media_queue, "submit",
                        lambda kind, params: (cap.update(kind=kind, params=params), "jid")[1])
    c = app.app.test_client()
    r = c.post("/api/video-studio/run-tool",
               json={"tool_name": "edit_video", "arguments": {"url": "https://youtu.be/x"}})
    d = r.get_json()
    assert d.get("ok") is True and d.get("job_id") == "jid"
    assert cap["kind"] == "filmora_edit"
    assert cap["params"] == {"tool_name": "edit_video", "arguments": {"url": "https://youtu.be/x"}}


def test_vs_run_tool_route_validates_input(monkeypatch):
    import app, filmora_mcp
    monkeypatch.setattr(filmora_mcp, "is_configured", lambda: True)
    c = app.app.test_client()
    # tool_name fehlt
    r1 = c.post("/api/video-studio/run-tool", json={"arguments": {}})
    assert r1.status_code == 400
    # arguments ist kein Objekt
    r2 = c.post("/api/video-studio/run-tool", json={"tool_name": "x", "arguments": "nope"})
    assert r2.status_code == 400
    # nicht verbunden
    monkeypatch.setattr(filmora_mcp, "is_configured", lambda: False)
    r3 = c.post("/api/video-studio/run-tool", json={"tool_name": "x", "arguments": {}})
    assert r3.get_json().get("reason") == "not_connected"


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


def test_deploy_respects_makeover_gate(tmp_path, monkeypatch):
    # Heal-Redeploy darf NICHT gleichzeitig mit einem Makeover am selben Git-Repo laufen:
    # ist der Makeover-Gate belegt, verschiebt _run_deploy sauber (kein _deploy_folder-Aufruf).
    import website_builder as wb
    folder = tmp_path / "web_x"; folder.mkdir()
    (folder / "content.json").write_text('{"site_name":"X"}', encoding="utf-8")
    calls = {"deploy": 0}
    monkeypatch.setattr(wb, "_deploy_folder",
                        lambda *a, **k: (calls.__setitem__("deploy", calls["deploy"] + 1) or
                                         {"railway_log": "", "repo_url": "", "live_url": "",
                                          "live_ok": False, "railway_note": "ok"}))
    monkeypatch.setattr(wb, "_sync_push", lambda *a, **k: None)
    monkeypatch.setattr(wb, "_persist", lambda *a, **k: None)
    monkeypatch.setattr(wb, "_django_secret_key", lambda: "k")
    jid = "testdeploygate"
    wb._jobs[jid] = {"id": jid, "status": "queued", "progress": 0, "step": ""}
    try:
        assert wb._makeover_gate.acquire(blocking=False)      # „Makeover läuft"
        try:
            wb._run_deploy(jid, str(folder), "X")
        finally:
            wb._makeover_gate.release()
        assert calls["deploy"] == 0
        assert "verschoben" in wb._jobs[jid].get("step", "").lower()
        # Gate frei → Deploy läuft normal durch.
        wb._run_deploy(jid, str(folder), "X")
        assert calls["deploy"] == 1
        assert not wb._makeover_gate.locked()                 # Gate sauber freigegeben
    finally:
        wb._jobs.pop(jid, None)


def test_auto_builder_sessions(monkeypatch):
    import auto_builder
    # Explizite Session-Fenster gewinnen und werden sortiert.
    monkeypatch.setenv("JARVIS_SESSION_HOURS", "0,12,18")
    assert auto_builder._session_hours() == [0, 12, 18]
    # Ohne Override: gleichmäßige Verteilung aus _SESSIONS_PER_DAY.
    monkeypatch.delenv("JARVIS_SESSION_HOURS", raising=False)
    monkeypatch.setattr(auto_builder, "_SESSIONS_PER_DAY", 3)
    assert auto_builder._session_hours() == [0, 8, 16]
    # Session-Key trägt das '_s{n}'-Suffix.
    monkeypatch.setenv("JARVIS_SESSION_HOURS", "0,12,18")
    assert "_s" in auto_builder._session()


def test_auto_builder_keys_for_date():
    import auto_builder
    log = {"2026-06-27": [1], "2026-06-27_s1": [2], "2026-06-27_pm": [3],
           "2026-06-26_s2": [4]}
    keys = set(auto_builder._keys_for_date(log, "2026-06-27"))
    assert keys == {"2026-06-27", "2026-06-27_s1", "2026-06-27_pm"}


def test_auto_builder_record_custom(tmp_path, monkeypatch):
    import auto_builder, db_websites
    monkeypatch.setattr(auto_builder, "_LOG_PATH", tmp_path / "daily_builds.json")
    fa = tmp_path / "web_marke"; fa.mkdir()
    auto_builder.record_custom("Meine Marke", "Ulm", "Maler",
                               "https://marke.de", "info@marke.de", str(fa))
    # Erneuter Aufruf mit gleichem Ordner darf NICHT doppelt zählen (idempotent).
    auto_builder.record_custom("Meine Marke", "Ulm", "Maler",
                               "https://marke.de", "info@marke.de", str(fa))
    monkeypatch.setattr(db_websites, "get_all",
                        lambda *a, **k: [{"folder": str(fa), "archived": 0}])
    assert auto_builder._count_today() == 1
    names = [s["name"] for d in auto_builder.daily_log()["days"] for s in d["sites"]]
    assert names.count("Meine Marke") == 1


def test_contact_finder_ranking_und_filter():
    import contact_finder
    # noreply/postmaster werden gefiltert; info@ wird vor chef@ bevorzugt.
    ranked = contact_finder._rank_emails(
        ["noreply@x.de", "chef@x.de", "INFO@x.de", "postmaster@x.de"])
    assert ranked == ["info@x.de", "chef@x.de"]
    assert contact_finder._domain_of("https://www.Betrieb.de/impressum") == "betrieb.de"


def test_contact_finder_domain_schaetzung(monkeypatch):
    import contact_finder
    import agents.evaluator.web_analyst as wa
    # web_analyst findet Website aber KEINE E-Mail; Seiten-Scan liefert nichts →
    # letzter Ausweg: info@<domain> als markierte Schätzung.
    monkeypatch.setattr(wa, "analyze", lambda lead: {
        "email_adresse": "", "email_alle": [], "discovered_website": "https://betrieb.de"})
    monkeypatch.setattr(contact_finder, "_scan_pages", lambda url, limit=4: [])
    res = contact_finder.find("Betrieb", "Ulm", "Maler")
    assert res["ok"] and res["email"] == "info@betrieb.de" and res["geraten"] is True


def test_discord_noon_latch(tmp_path, monkeypatch):
    import discord_bot
    monkeypatch.setattr(discord_bot, "_NOON_STATE", tmp_path / "noon_state.json")
    assert discord_bot._noon_ran_today() is False
    discord_bot._mark_noon_ran()
    assert discord_bot._noon_ran_today() is True


def test_auto_builder_pick_next_lead(monkeypatch):
    import db_evaluated, db_websites, auto_builder
    from leadkey import lead_key
    leads = [
        {"name": "MitWeb GmbH", "stadt": "Ulm", "has_website": 1, "erwartungswert_euro": 9000},
        {"name": "OhneWeb GmbH", "stadt": "Köln", "has_website": 0, "erwartungswert_euro": 5000},
    ]
    monkeypatch.setattr(db_evaluated, "get_all", lambda **k: leads)
    monkeypatch.setattr(db_websites, "get_all", lambda: [])
    monkeypatch.setattr(db_websites, "has_site_key", lambda sk: False)
    # Lead MIT Website wird übersprungen → der ohne Website wird gewählt
    assert auto_builder._pick_next_lead()["name"] == "OhneWeb GmbH"
    # schon gebaut (site_key in db_websites) → übersprungen → None
    built = {lead_key("OhneWeb GmbH", "Köln")}
    monkeypatch.setattr(db_websites, "has_site_key", lambda sk: sk in built)
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


def test_review_queue_promote_pending(tmp_path, monkeypatch):
    # Auto-Send: promote_pending() hebt offene Reviews auf approved — ein 👎-Veto (REJECTED)
    # bleibt ausgeschlossen, damit abgelehnte Seiten NICHT rausgehen.
    import review_queue as rq
    monkeypatch.setattr(rq, "_PATH", tmp_path / "reviews.json")
    a = rq.add("Alpha", "Berlin", "Dachdecker", "https://a")
    b = rq.add("Beta", "Köln", "Friseur", "https://b")
    rq.vote(b["id"], "u1", False)                 # Beta wird per 👎 abgelehnt
    assert rq.get(b["id"])["status"] == rq.REJECTED
    n = rq.promote_pending()
    assert n == 1                                  # nur Alpha war pending
    assert rq.get(a["id"])["status"] == rq.APPROVED
    assert rq.get(b["id"])["status"] == rq.REJECTED   # Veto bleibt bestehen
    assert len(rq.approved_unsent()) == 1


def test_review_queue_latest_for_site(tmp_path, monkeypatch):
    import review_queue as rq
    monkeypatch.setattr(rq, "_PATH", tmp_path / "reviews.json")
    assert rq.latest_for_site("Gibt", "Nicht") is None
    r = rq.add("Firma X", "Ulm", "Elektriker", "https://x")
    found = rq.latest_for_site("  firma x ", "ULM")   # Case/Whitespace-robust
    assert found and found["id"] == r["id"]


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


def test_discord_bot_import_safe(monkeypatch):
    # Ohne Token/Library muss der Bot ein No-op sein und das System nie blockieren.
    # Token/Kanal aus der Umgebung (z.B. echte .env) für diesen Test leeren.
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_CHANNEL_ID", raising=False)
    monkeypatch.setenv("JARVIS_AUTO_SEND", "0")   # klassisches 👍-Gate für diesen Fall
    import discord_bot
    assert discord_bot.enabled() is False
    st = discord_bot.status()
    assert "enabled" in st and "send_hour" in st and "auto_send" in st
    # Ohne Auto-Send UND ohne laufenden Bot liefert submit_for_review None (kein Crash).
    assert discord_bot.submit_for_review("X", "Y", "Z", "https://x") is None


def test_discord_auto_send_queues_without_bot(tmp_path, monkeypatch):
    # Auto-Send (Default AN): eine fertige Seite muss auch OHNE verbundenen Bot in die
    # Versand-Queue wandern und direkt 'approved' sein — sonst ginge sie nie raus.
    import review_queue as rq
    import discord_bot
    monkeypatch.setattr(rq, "_PATH", tmp_path / "reviews.json")
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_CHANNEL_ID", raising=False)
    monkeypatch.setenv("JARVIS_AUTO_SEND", "1")
    assert discord_bot.enabled() is False          # Bot bewusst offline
    r = discord_bot.submit_for_review("Firma X", "Stadt", "Dachdecker",
                                      "https://x.up.railway.app", email="kunde@example.de")
    assert r is not None and r["status"] == rq.APPROVED
    assert len(rq.approved_unsent()) == 1          # steht wirklich zum Versand bereit


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


# ── Eigene Marke (Custom-Build) ───────────────────────────────────────────────
def test_custom_build_lead_struktur():
    import custom_build
    lead, rec = custom_build._build_lead({
        "name": " Müller Dachtechnik GmbH ", "branche": "Dachdecker", "stadt": "Freiburg",
        "beschreibung": "Familienbetrieb seit 1990", "telefon": "0761 1",
        "hero_prompt": "cinematic roof", "logo_path": "x.png",
        "recipients": ["a@b.de", "ungueltig", "c@d.de"]})
    assert lead["name"] == "Müller Dachtechnik GmbH"
    assert lead["beschreibung"] == "Familienbetrieb seit 1990"
    assert lead["_custom"]["hero_prompt"] == "cinematic roof"
    assert lead["_custom"]["logo_path"] == "x.png"
    assert rec == ["a@b.de", "c@d.de"]              # ungültige Adresse rausgefiltert


def test_custom_build_start_braucht_name():
    import custom_build
    assert custom_build.start({"name": "  "})["ok"] is False


def test_custom_slugify():
    import custom_build
    assert custom_build._slugify("Müller & Co. GmbH") == "mueller-und-co-gmbh"


# ── Review-Empfänger (11+) ────────────────────────────────────────────────────
def test_review_queue_recipients(tmp_path, monkeypatch):
    import review_queue as rq
    monkeypatch.setattr(rq, "_PATH", tmp_path / "reviews.json")
    r = rq.add("B", "S", "Br", "https://x", recipients=["a@b.de", "bad", "c@d.de", ""])
    assert r["recipients"] == ["a@b.de", "c@d.de"]


def test_discord_send_recipients_loop(monkeypatch):
    import discord_bot, mailer, offer_mail
    sent = []
    monkeypatch.setattr(offer_mail, "build", lambda *a, **k: ("B", "T", "<b>"))
    monkeypatch.setattr(mailer, "send_email",
                        lambda to, *a, **k: sent.append(to) or {"ok": True, "status": "gesendet"})
    ok, info = discord_bot._send_one_real(
        {"name": "X", "link": "https://x", "branche": "", "stadt": "",
         "recipients": ["a@b.de", "c@d.de", "e@f.de"]})
    assert ok and sent == ["a@b.de", "c@d.de", "e@f.de"] and "3/3" in info


def test_auto_send_versendet_altbestand_pending(tmp_path, monkeypatch):
    # Kernwunsch: bereits gebaute, aber noch nicht versendete (pending) Seiten müssen im
    # Auto-Send-Modus beim Versand automatisch mit rausgehen — ohne 👍.
    import review_queue as rq
    import discord_bot
    monkeypatch.setattr(rq, "_PATH", tmp_path / "reviews.json")
    monkeypatch.setenv("JARVIS_AUTO_SEND", "1")
    # Altbestand: eine Seite steht noch auf pending (vor Auto-Send angelegt).
    old = rq.add("Alt Firma", "Bremen", "Dachdecker", "https://alt.up.railway.app",
                 email="kunde@alt.de", status=rq.PENDING)
    assert old["status"] == rq.PENDING
    # DB-Nachqueue in diesem Unit-Test ausklammern (kein echtes db_websites nötig).
    monkeypatch.setattr(discord_bot, "enqueue_unsent_websites", lambda: 0)
    real_send = []
    monkeypatch.setattr(discord_bot, "_send_one_real",
                        lambda r: real_send.append(r["name"]) or (True, "gesendet"))
    res = discord_bot.send_approved_now()
    assert res["sent"] == 1 and real_send == ["Alt Firma"]
    assert rq.get(old["id"])["status"] == rq.SENT      # sauber als versendet markiert


# ── Logo + Template-Slot + Render ─────────────────────────────────────────────
def test_improve_logo_und_initialen(tmp_path):
    import website_improve as wi
    assert wi._initials("Müller Dachtechnik GmbH") == "MD"
    assert wi._initials("Findeisen") == "FI"
    p = wi._make_logo(tmp_path, "Test GmbH", "#1e8eff")
    assert p == "/static/img/logo.svg"
    svg = (tmp_path / "static" / "img" / "logo.svg").read_text(encoding="utf-8")
    assert "<svg" in svg and ">TE<" in svg.replace(" ", "")


def test_premium_template_hat_logo_slot():
    import website_improve as wi
    assert "c.logo_image" in wi._PREMIUM_HTML
    # Vorlage ebenso
    from pathlib import Path
    tpl = (Path(__file__).resolve().parents[1] / "vorlage_landing" / "templates" / "index.html").read_text(encoding="utf-8")
    assert "c.logo_image" in tpl


def test_premium_render_mit_logo(tmp_path):
    import website_improve as wi
    c = {"site_name": "Test GmbH", "akzent": "#1e8eff", "logo_image": "/static/img/logo.svg",
         "hero_image": "/static/img/hero.png", "headline": "H", "subline": "S",
         "leistungen": [{"titel": "A", "text": "B"}], "usps": ["x"],
         "faq": [{"frage": "q", "antwort": "a"}], "jahr": 2026}
    ok, err = wi._render_check(tmp_path, c)
    assert ok, err


def test_improve_qa_behaelt_assets():
    # Der QA-Pass darf Bild-/Logo-Pfade nicht verlieren (Asset-Sicherung).
    import website_improve as wi
    src = wi._PREMIUM_HTML
    assert 'src="{{ c.logo_image }}"' in src and "c.hero_image" in src


# ── Lokale Lead-Foto-Bewertung (Logos raus, Rollen sinnvoll) ──────────────────
def _mk_img(path, w, h, *, gray=False):
    """Hilfsfunktion: synthetisches Testbild schreiben (bunt-scharf oder grau-flach)."""
    import numpy as np
    from PIL import Image
    if gray:
        arr = np.full((h, w, 3), 200, "uint8"); arr[h//3:2*h//3, w//3:2*w//3] = 30
    else:
        arr = (np.random.rand(h, w, 3) * 255).astype("uint8")
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr).save(path, quality=90)


def test_lead_images_verwirft_logo_und_ordnet_rollen(tmp_path):
    import lead_images
    lead = tmp_path / "static" / "img" / "lead"
    _mk_img(lead / "1.jpg", 1600, 900)            # gut, quer  → Hero
    _mk_img(lead / "2.png", 120, 120, gray=True)  # winziges Logo → verworfen
    _mk_img(lead / "3.jpg", 700, 1200)            # gut, hoch  → Über-uns
    arr = lead_images.evaluate_and_arrange(
        ["/static/img/lead/1.jpg", "/static/img/lead/2.png", "/static/img/lead/3.jpg"],
        tmp_path, "maler")
    by = {r["path"]: r for r in arr["evaluated"]}
    assert by["/static/img/lead/2.png"]["ok"] is False         # Logo erkannt
    assert by["/static/img/lead/1.jpg"]["ok"] is True
    assert arr["hero"] == "/static/img/lead/1.jpg"             # Querformat → Hero
    assert arr["about"] == "/static/img/lead/3.jpg"            # Hochformat → Über-uns
    assert "/static/img/lead/2.png" not in arr["gallery"]      # verworfen, nicht in Galerie


def test_lead_images_robust_ohne_dateien(tmp_path):
    # Keine echten Dateien → Eingaben unverändert als Galerie, kein Crash.
    import lead_images
    arr = lead_images.evaluate_and_arrange(["/static/img/lead/x.jpg"], tmp_path, "kfz")
    assert arr["hero"] == "" and arr["gallery"] == ["/static/img/lead/x.jpg"]
    # SVG-Platzhalter werden nie als Lead-Foto bewertet
    assert lead_images._to_fs("/static/img/hero_ph.svg", tmp_path) is None


# ── Railway: bestehenden Service wiederverwenden (Link trotzdem zeigen) ────────
def test_railway_find_service_parst_domain(monkeypatch):
    import agent_railway as ar
    fake = {"ok": True, "data": {"project": {"services": {"edges": [
        {"node": {"id": "svc1", "name": "web-test", "serviceInstances": {"edges": [
            {"node": {"domains": {"serviceDomains": [{"domain": "web-test.up.railway.app"}]}}}]}}}]}}}}
    monkeypatch.setattr(ar, "_gql", lambda *a, **k: fake)
    res = ar._find_service("tok", "proj", "web-test")
    assert res["found"] and res["domain"] == "web-test.up.railway.app" and res["service_id"] == "svc1"


def test_railway_find_service_nicht_gefunden(monkeypatch):
    import agent_railway as ar
    monkeypatch.setattr(ar, "_gql", lambda *a, **k:
                        {"ok": True, "data": {"project": {"services": {"edges": []}}}})
    assert ar._find_service("tok", "proj", "web-x") == {"found": False}


# ── Railway: Projekt-Rotation ab Service-Limit (02.07.2026) ────────────────────
def test_railway_all_generated_projects_filters_and_sorts(monkeypatch):
    import agent_railway as ar
    monkeypatch.setattr(ar, "list_projects", lambda: {"ok": True, "projects": [
        {"id": "x1", "name": "Generated Websites 3"},
        {"id": "x2", "name": "Some Other Project"},          # kein Treffer
        {"id": "x3", "name": "Generated Websites"},
        {"id": "x4", "name": "Generated Websites 2"},
    ]})
    out = ar.all_generated_projects("tok")
    assert [p["name"] for p in out] == \
        ["Generated Websites", "Generated Websites 2", "Generated Websites 3"]
    assert [p["suffix"] for p in out] == [1, 2, 3]


def test_railway_target_project_name_rotates_when_full(monkeypatch):
    import agent_railway as ar
    monkeypatch.setattr(ar, "all_generated_projects",
                        lambda tok: [{"id": "p1", "name": "Generated Websites", "suffix": 1}])
    monkeypatch.setattr(ar, "_service_count", lambda tok, pid: 55)
    monkeypatch.setenv("JARVIS_RAILWAY_ROTATE_AT", "50")
    assert ar._target_project_name("tok") == "Generated Websites 2"


def test_railway_target_project_name_stays_when_not_full(monkeypatch):
    import agent_railway as ar
    monkeypatch.setattr(ar, "all_generated_projects",
                        lambda tok: [{"id": "p2", "name": "Generated Websites 2", "suffix": 2}])
    monkeypatch.setattr(ar, "_service_count", lambda tok, pid: 10)
    monkeypatch.setenv("JARVIS_RAILWAY_ROTATE_AT", "50")
    assert ar._target_project_name("tok") == "Generated Websites 2"


def test_railway_deploy_resumes_existing_service_across_rotated_projects(monkeypatch):
    # Ein Service, der VOR einer Rotation angelegt wurde, darf bei einem Redeploy NICHT
    # doppelt im (jetzt aktiven) neuen Projekt angelegt werden — er muss im alten
    # Projekt gefunden und dort wiederverwendet werden.
    import agent_railway as ar
    monkeypatch.setattr(ar, "_token", lambda: "tok")
    monkeypatch.setattr(ar, "all_generated_projects", lambda tok: [
        {"id": "p1", "name": "Generated Websites", "suffix": 1},
        {"id": "p2", "name": "Generated Websites 2", "suffix": 2},
    ])

    def fake_find_service(tok, project_id, name):
        if project_id == "p1" and name == "web-old":
            return {"found": True, "service_id": "svc-old", "domain": "old.up.railway.app"}
        return {"found": False}
    monkeypatch.setattr(ar, "_find_service", fake_find_service)
    monkeypatch.setattr(ar, "_find_project_with_env", lambda tok, name:
                        {"found": True, "project_id": "p1", "env_id": "e1"}
                        if name == "Generated Websites" else {"found": False})

    calls = {"project_create": 0, "service_create": 0}

    def fake_gql(query, variables, tok):
        if "projectCreate" in query:
            calls["project_create"] += 1
            return {"ok": True, "data": {}}
        if "serviceCreate(input" in query:
            calls["service_create"] += 1
            return {"ok": True, "data": {"serviceCreate": {"id": "new"}}}
        return {"ok": True, "data": {}}
    monkeypatch.setattr(ar, "_gql", fake_gql)

    res = ar.deploy("web-old", "user/repo", {})
    assert res["ok"] is True
    assert res["project_id"] == "p1" and res["service_id"] == "svc-old"
    assert calls["project_create"] == 0 and calls["service_create"] == 0   # kein Duplikat


# ── Railway: erzwungene Rotation (Live-Watch-Symptom-Trigger, 02.07.2026) ──────
def test_railway_force_rotate_creates_next_project(monkeypatch):
    import agent_railway as ar
    monkeypatch.setattr(ar, "_token", lambda: "tok")
    monkeypatch.setattr(ar, "all_generated_projects",
                        lambda tok: [{"id": "p1", "name": "Generated Websites", "suffix": 1}])
    monkeypatch.setattr(ar, "_find_project_with_env", lambda tok, name: {"found": False})
    calls = {"create": 0}

    def fake_gql(query, variables, tok):
        if "projectCreate" in query:
            calls["create"] += 1
            return {"ok": True, "data": {}}
        return {"ok": True, "data": {}}
    monkeypatch.setattr(ar, "_gql", fake_gql)

    res = ar.force_rotate(reason="3 Seiten offline")
    assert res == {"ok": True, "project": "Generated Websites 2", "already": False}
    assert calls["create"] == 1


def test_railway_force_rotate_already_exists_no_duplicate_create(monkeypatch):
    import agent_railway as ar
    monkeypatch.setattr(ar, "_token", lambda: "tok")
    monkeypatch.setattr(ar, "all_generated_projects",
                        lambda tok: [{"id": "p1", "name": "Generated Websites", "suffix": 1}])
    monkeypatch.setattr(ar, "_find_project_with_env", lambda tok, name:
                        {"found": True, "project_id": "p2", "env_id": "e2"})

    def fail_gql(*a, **k):
        raise AssertionError("projectCreate haette hier nicht aufgerufen werden duerfen")
    monkeypatch.setattr(ar, "_gql", fail_gql)

    res = ar.force_rotate()
    assert res == {"ok": True, "project": "Generated Websites 2", "already": True}


def test_railway_force_rotate_no_token(monkeypatch):
    import agent_railway as ar
    monkeypatch.setattr(ar, "_token", lambda: "")
    assert ar.force_rotate()["ok"] is False


# ── Live-Watch: mehrere tote Seiten erzwingen sofort eine Railway-Rotation ─────
def test_live_check_triggers_rotation_when_multiple_down(monkeypatch):
    import auto_builder as ab
    import db_websites
    import types, sys
    sites = [{"job_id": f"j{i}", "name": f"Site{i}", "folder": "", "live_url": f"https://s{i}.example",
              "live": 0, "step": ""} for i in range(3)]
    monkeypatch.setattr(db_websites, "get_all", lambda: sites)
    monkeypatch.setitem(sys.modules, "discord_bot",
                        types.SimpleNamespace(link_is_live=lambda u, timeout=8: False))
    calls = []
    monkeypatch.setattr(ab, "_maybe_force_rotation", lambda n: calls.append(n))
    monkeypatch.setattr(ab, "_LIVE_ROTATE_THRESHOLD", 3)
    ab._live_check_once()
    assert calls == [3]


def test_live_check_no_rotation_below_threshold(monkeypatch):
    import auto_builder as ab
    import db_websites
    import types, sys
    sites = [{"job_id": "j0", "name": "Site0", "folder": "", "live_url": "https://s0.example",
              "live": 0, "step": ""}]
    monkeypatch.setattr(db_websites, "get_all", lambda: sites)
    monkeypatch.setitem(sys.modules, "discord_bot",
                        types.SimpleNamespace(link_is_live=lambda u, timeout=8: False))
    calls = []
    monkeypatch.setattr(ab, "_maybe_force_rotation", lambda n: calls.append(n))
    monkeypatch.setattr(ab, "_LIVE_ROTATE_THRESHOLD", 3)
    ab._live_check_once()
    assert calls == []


def test_maybe_force_rotation_calls_railway_and_notifies(monkeypatch):
    import auto_builder as ab
    import agent_railway, discord_bot
    monkeypatch.setattr(ab, "_live_last_forced_rotation", [0.0])
    monkeypatch.setattr(agent_railway, "is_ready", lambda: True)
    monkeypatch.setattr(agent_railway, "force_rotate", lambda reason="":
                        {"ok": True, "project": "Generated Websites 2", "already": False})
    calls = []
    monkeypatch.setattr(discord_bot, "notify", lambda *a, **k: calls.append(a) or True)
    ab._maybe_force_rotation(4)
    assert len(calls) == 1 and "Generated Websites 2" in calls[0][1]


def test_maybe_force_rotation_respects_cooldown(monkeypatch):
    import auto_builder as ab
    import agent_railway
    import time as _t
    monkeypatch.setattr(ab, "_live_last_forced_rotation", [_t.time()])   # gerade eben ausgelöst
    monkeypatch.setattr(ab, "_LIVE_ROTATE_COOLDOWN", 21600)
    fr_calls = []
    monkeypatch.setattr(agent_railway, "is_ready", lambda: True)
    monkeypatch.setattr(agent_railway, "force_rotate",
                        lambda reason="": fr_calls.append(1) or {"ok": True})
    ab._maybe_force_rotation(5)
    assert fr_calls == []


def test_maybe_force_rotation_no_duplicate_notify_when_already(monkeypatch):
    import auto_builder as ab
    import agent_railway, discord_bot
    monkeypatch.setattr(ab, "_live_last_forced_rotation", [0.0])
    monkeypatch.setattr(agent_railway, "is_ready", lambda: True)
    monkeypatch.setattr(agent_railway, "force_rotate", lambda reason="":
                        {"ok": True, "project": "Generated Websites 2", "already": True})
    calls = []
    monkeypatch.setattr(discord_bot, "notify", lambda *a, **k: calls.append(a) or True)
    ab._maybe_force_rotation(3)
    assert calls == []


# ── db_websites: Kundenantwort schützt vor Alt-Demo-Teardown ───────────────────
def test_db_websites_mark_replied(tmp_path, monkeypatch):
    import db_websites
    monkeypatch.setattr(db_websites, "DB_PATH", tmp_path / "w.db")
    db_websites.init_db()
    db_websites.create("job-1", "Firma X", "Ulm", "Dachdecker")
    assert db_websites.mark_replied("Firma X", "Ulm") is True
    row = db_websites.get_by_job("job-1")
    assert row["replied"] == 1
    assert db_websites.mark_replied("Unbekannt", "Nirgendwo") is False   # wirft nicht


def test_teardown_stale_demos_skips_replied_and_converted(tmp_path, monkeypatch):
    import time
    import auto_builder as ab
    import db_websites
    import agent_railway
    monkeypatch.setattr(db_websites, "DB_PATH", tmp_path / "w.db")
    db_websites.init_db()

    def _age(job_id, days):
        with db_websites._lock, db_websites._conn() as c:
            c.execute("UPDATE websites SET created=? WHERE job_id=?",
                      (time.time() - days * 86400, job_id))
            c.commit()

    db_websites.create("job-replied", "Beantwortet GmbH", "Ulm", "x")
    db_websites.update("job-replied", live_url="https://a.example", live=1, replied=1)
    _age("job-replied", 10)

    db_websites.create("job-stale", "Alt GmbH", "Ulm", "x")
    db_websites.update("job-stale", live_url="https://b.example", live=1)
    _age("job-stale", 10)

    db_websites.create("job-fresh", "Frisch GmbH", "Ulm", "x")
    db_websites.update("job-fresh", live_url="https://c.example", live=1)
    _age("job-fresh", 1)

    monkeypatch.setattr(agent_railway, "is_ready", lambda: True)
    monkeypatch.setattr(agent_railway, "service_delete_by_name",
                        lambda name: {"ok": True, "error": ""})
    monkeypatch.setattr(ab, "_lead_converted", lambda lid: False)

    n = ab.teardown_stale_demos(max_age_days=5)
    assert n == 1
    rows = {r["name"]: r for r in db_websites.get_all(include_archived=True)}
    assert rows["Beantwortet GmbH"]["archived"] == 0     # Antwort erkannt -> geschützt
    assert rows["Alt GmbH"]["archived"] == 1              # weder Antwort noch verkauft -> abgebaut
    assert rows["Frisch GmbH"]["archived"] == 0           # zu jung


# ── inbox_reader: JEDE erkannte Antwort geht nach Discord (nicht nur "heiße") ──
def test_inbox_announce_notifies_discord_fuer_jede_kategorie(monkeypatch):
    import inbox_reader as ir
    import discord_bot
    calls = []
    monkeypatch.setattr(discord_bot, "notify",
                        lambda *a, **k: calls.append((a, k)) or True)
    monkeypatch.setattr(ir.logger, "activity", lambda *a, **k: None)
    for kat in ("interesse", "rueckfrage", "preisfrage", "termin", "absage", "neutral"):
        calls.clear()
        ir._announce({"name": "Testfirma", "from": "test@example.de",
                      "zusammenfassung": "x", "empfehlung": "y", "dringlichkeit": "niedrig",
                      "kategorie": kat, "suggested_reply": {}})
        assert len(calls) == 1, f"Kategorie '{kat}' hat NICHT nach Discord gemeldet"
        assert calls[0][1].get("color") == ir._COLOR[kat]


def test_inbox_announce_draft_hint_nur_wenn_entwurf_vorhanden(monkeypatch):
    import inbox_reader as ir
    import discord_bot
    monkeypatch.setattr(ir.logger, "activity", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(discord_bot, "notify", lambda *a, **k: calls.append(a) or True)
    ir._announce({"name": "Testfirma", "kategorie": "preisfrage",
                  "suggested_reply": {"text": "Hallo"}})
    assert "Antwort-Entwurf liegt bereit" in calls[0][1]
    calls.clear()
    ir._announce({"name": "Testfirma", "kategorie": "neutral", "suggested_reply": {}})
    assert "Antwort-Entwurf liegt bereit" not in calls[0][1]


# ── Video: CPU faellt automatisch auf Higgsfield-Cloud (kein GPU-Fehler mehr) ──
def test_video_cpu_faellt_auf_higgsfield(monkeypatch):
    import media_engine as me
    monkeypatch.setattr(me, "hardware_info", lambda: {"device": "cpu"})
    monkeypatch.setattr(me, "higgsfield_available", lambda: True)
    seen = {}
    monkeypatch.setattr(me, "generate_video_higgsfield",
                        lambda prompt, **k: (seen.update(p=prompt),
                        {"path": "x", "web_url": "/w", "model": "dop-lite",
                         "prompt": prompt, "elapsed": 1.0})[1])
    monkeypatch.setenv("JARVIS_VIDEO_BACKEND", "auto")
    res = me.generate_video("ein werbeclip")
    assert seen["p"] == "ein werbeclip" and res["web_url"] == "/w"


def test_video_cpu_ohne_key_klare_meldung(monkeypatch):
    import media_engine as me
    import higgsfield_mcp
    import pytest
    monkeypatch.setattr(me, "hardware_info", lambda: {"device": "cpu"})
    monkeypatch.setattr(me, "higgsfield_available", lambda: False)
    # Kein Higgsfield-Zugang: weder Platform-API-Key noch angemeldeter Abo-MCP.
    monkeypatch.setattr(higgsfield_mcp, "available", lambda: False)
    monkeypatch.setenv("JARVIS_VIDEO_BACKEND", "auto")
    with pytest.raises(RuntimeError) as e:
        me.generate_video("x")
    msg = str(e.value)
    assert "HIGGSFIELD_API_KEY" in msg and "Stunden" not in msg   # neue, lösbare Meldung


def test_video_backend_higgsfield_explizit(monkeypatch):
    import media_engine as me
    monkeypatch.setattr(me, "hardware_info", lambda: {"device": "cuda"})  # sogar mit GPU
    monkeypatch.setattr(me, "higgsfield_available", lambda: True)
    seen = {}
    monkeypatch.setattr(me, "generate_video_higgsfield",
                        lambda prompt, **k: (seen.update(p=prompt), {"web_url": "/c"})[1])
    monkeypatch.setenv("JARVIS_VIDEO_BACKEND", "higgsfield")
    assert me.generate_video("y")["web_url"] == "/c" and seen["p"] == "y"


# ── Kostenrechner: branchengerechte Posten + Vorlage-Einbau ───────────────────
def test_rechner_for_branche_und_fallback():
    import website_builder as wb
    r = wb.rechner_for("Dachdeckermeisterbetrieb", [])
    namen = [p["name"] for p in r["posten"]]
    assert r["posten"] and any("Dach" in n for n in namen)
    assert all("ab" in p and "bis" in p and p["bis"] >= p["ab"] for p in r["posten"])
    # unbekannte Branche → generische 3-Stufen-Schätzung
    g = wb.rechner_for("Etwas Exotisches ohne Match", [])
    assert len(g["posten"]) == 3 and g["posten"][0]["ab"] == 150


def test_vorlage_hero_rechner_und_headline_links():
    from pathlib import Path
    base = Path(__file__).resolve().parents[1] / "vorlage_landing"
    tpl = (base / "templates" / "index.html").read_text(encoding="utf-8")
    assert "hero-rechner" in tpl                      # Kostenrechner-Karte im Hero
    assert 'json_script:"rechner-data"' in tpl        # Daten für die JS
    assert "kostenrechner.js" in tpl                  # JS eingebunden
    assert (base / "static" / "js" / "kostenrechner.js").is_file()
    css = (base / "static" / "css" / "style.css").read_text(encoding="utf-8")
    assert ".hero h1{" in css and "text-align:left" in css   # Headline linksbündig, nicht zentriert


# ── Stündlicher Lead-Sammler (lead_collector.py) ──────────────────────────────
def test_lead_collector_enabled_flag(monkeypatch):
    import lead_collector as lc
    monkeypatch.setenv("JARVIS_LEAD_COLLECTOR", "0")
    assert lc.enabled() is False
    monkeypatch.setenv("JARVIS_LEAD_COLLECTOR", "off")
    assert lc.enabled() is False
    monkeypatch.setenv("JARVIS_LEAD_COLLECTOR", "1")
    assert lc.enabled() is True
    monkeypatch.delenv("JARVIS_LEAD_COLLECTOR", raising=False)
    assert lc.enabled() is True                       # Default AN


def test_lead_collector_latch(tmp_path, monkeypatch):
    import lead_collector as lc
    monkeypatch.setattr(lc, "_LATCH", tmp_path / "lead_state.json")
    monkeypatch.setenv("JARVIS_LEAD_INTERVAL", "3600")
    assert lc._due() is True                          # nie gelaufen → sofort fällig
    lc._mark_ran()
    assert lc._due() is False                         # gerade gelaufen → nicht fällig
    # Intervall-Grenze: last_run künstlich in die Vergangenheit schieben
    import json as _j, time as _t
    (tmp_path / "lead_state.json").write_text(
        _j.dumps({"last_run": _t.time() - 4000}), encoding="utf-8")
    assert lc._due() is True                          # 4000s > 3600s → wieder fällig


def test_lead_collector_report_format():
    import lead_collector as lc
    top = [
        {"name": "Alpha Dach GmbH", "score": 91, "stadt": "Ulm", "bundesland": "BW",
         "branche": "Dachdecker", "lead_typ": "Hot", "sicherheit": 80,
         "erwartungswert_euro": 550, "telefon": "0731 1", "email_adresse": "a@b.de",
         "ansprechpartner": "Herr Alpha", "pitch_hook": "Keine Website, viele Bewertungen."},
        {"name": "Beta", "score": 70},                # minimal — leere Felder weglassen
    ]
    title, desc, fields = lc._build_report(5, top)
    assert "5" in title and len(fields) == 2
    assert fields[0][0].startswith("#1 · Alpha Dach GmbH")
    assert "📞 0731 1" in fields[0][1] and "💶 550 €" in fields[0][1]
    assert all(len(v) <= 1024 for _, v in fields)     # Discord-Feld-Limit
    # Lead ohne Details → keine leeren Zeilen, aber gültiger Wert
    assert fields[1][1] == "—" or "📍" not in fields[1][1]
    # 0 neue Leads → klarer Text, keine Felder
    t0, d0, f0 = lc._build_report(0, [])
    assert "0" in t0 and "Keine neuen" in d0 and f0 == []


def _lc_stub_env(monkeypatch, running: bool, pending: int = 0):
    """Stubbt controller/db/discord für _run_once-Tests (kein Netzwerk, kein Warten)."""
    import lead_collector as lc
    import types, threading
    calls = {"start": 0, "stop_scrapers": 0, "stop_evaluator": 0, "report": [], "count_arg": None}
    ev = threading.Event()
    ev.set()                                          # .wait() kehrt sofort zurück
    ctrl = types.SimpleNamespace(
        is_running=lambda: running,
        start=lambda: calls.__setitem__("start", calls["start"] + 1),
        stop_scrapers=lambda: calls.__setitem__("stop_scrapers", calls["stop_scrapers"] + 1),
        stop_evaluator=lambda: calls.__setitem__("stop_evaluator", calls["stop_evaluator"] + 1),
        _stop_event=ev)
    dbe = types.SimpleNamespace(
        max_id=lambda: 42,
        count_since=lambda mid: (calls.__setitem__("count_arg", mid), 7)[1],
        get_top=lambda n: [{"name": "X", "score": 50}])
    # count_pending() liefert sofort 0 → _drain_evaluator_backlog() kehrt ohne Warten zurück.
    draw = types.SimpleNamespace(count_pending=lambda: pending)
    disc = types.SimpleNamespace(
        post_report=lambda *a, **k: calls["report"].append(a) or True)
    import sys
    monkeypatch.setitem(sys.modules, "scrapers.controller", ctrl)
    # WICHTIG: `import scrapers.controller as controller` löst über das PACKAGE-ATTRIBUT auf,
    # wenn das echte Modul schon importiert wurde (voller Suite-Lauf) — sonst startet der
    # Test den ECHTEN Scraper und wartet echte 600s. Darum beide Wege stubben.
    import scrapers
    monkeypatch.setattr(scrapers, "controller", ctrl, raising=False)
    monkeypatch.setitem(sys.modules, "db_evaluated", dbe)
    monkeypatch.setitem(sys.modules, "db_raw", draw)
    monkeypatch.setitem(sys.modules, "discord_bot", disc)
    monkeypatch.setenv("JARVIS_LEAD_STOP_BUFFER", "0")
    return lc, calls


def test_lead_collector_run_once_self_managed(monkeypatch):
    # Sammler war AUS → Scheduler startet, sammelt, stoppt Scraper+Evaluator und meldet.
    lc, calls = _lc_stub_env(monkeypatch, running=False)
    lc._run_once()
    assert calls["start"] == 1
    assert calls["stop_scrapers"] == 1 and calls["stop_evaluator"] == 1
    assert calls["count_arg"] == 42                   # Snapshot aus max_id()
    assert len(calls["report"]) == 1
    assert "7" in calls["report"][0][0]               # new_count im Titel


def test_lead_collector_run_once_respects_manual(monkeypatch):
    # Sammler lief MANUELL → Scheduler darf weder starten noch stoppen, meldet aber.
    lc, calls = _lc_stub_env(monkeypatch, running=True)
    lc._run_once()
    assert calls["start"] == 0
    assert calls["stop_scrapers"] == 0 and calls["stop_evaluator"] == 0
    assert len(calls["report"]) == 1


def test_lead_collector_drains_backlog_before_stopping_evaluator(monkeypatch):
    # Rest-Backlog leert sich nach dem ersten Poll → Drain kehrt zurück, Evaluator wird
    # danach trotzdem gestoppt (nicht endlos weiterlaufen lassen).
    lc, calls = _lc_stub_env(monkeypatch, running=False, pending=0)
    monkeypatch.setenv("JARVIS_LEAD_DRAIN_MAX", "30")
    lc._run_once()
    assert calls["stop_scrapers"] == 1 and calls["stop_evaluator"] == 1


def test_lead_collector_drain_caps_wait(monkeypatch):
    # Backlog leert sich NIE → Drain darf nicht ewig (echte 30s) warten, Zeitlimit greift.
    import time as _t
    lc, calls = _lc_stub_env(monkeypatch, running=False, pending=3)
    monkeypatch.setenv("JARVIS_LEAD_DRAIN_MAX", "30")     # min. erlaubt
    clock = [0.0]
    def _fake_time():
        clock[0] += 6                                      # springt je Aufruf weiter als ein Poll
        return clock[0]
    monkeypatch.setattr(_t, "time", _fake_time)
    monkeypatch.setattr(_t, "sleep", lambda s: None)       # Poll-Sleeps überspringen
    lc._drain_evaluator_backlog()                          # darf nicht hängen (endliche Fake-Zeit)
    assert clock[0] >= 30                                  # Schleife lief bis zum Limit durch


# ── db_evaluated: schlanke Zähl-/Globus-Helfer ────────────────────────────────
def test_db_evaluated_max_id_und_count_since(tmp_path, monkeypatch):
    import db_evaluated
    monkeypatch.setattr(db_evaluated, "DB_PATH", tmp_path / "ev.db")
    db_evaluated.init_db()
    assert db_evaluated.max_id() == 0                 # leere Tabelle
    db_evaluated.insert_evaluated({"name": "A", "stadt": "Ulm", "lead_key": "k-a"})
    db_evaluated.insert_evaluated({"name": "B", "stadt": "Ulm", "lead_key": "k-b"})
    snap = db_evaluated.max_id()
    assert snap >= 2 and db_evaluated.count_since(snap) == 0
    db_evaluated.insert_evaluated({"name": "C", "stadt": "Ulm", "lead_key": "k-c"})
    assert db_evaluated.count_since(snap) == 1        # genau der neue Lead


def test_db_evaluated_get_for_globe(tmp_path, monkeypatch):
    import db_evaluated
    monkeypatch.setattr(db_evaluated, "DB_PATH", tmp_path / "ev.db")
    db_evaluated.init_db()
    db_evaluated.insert_evaluated({"name": "MitStadt", "stadt": "Ulm", "lead_key": "k1",
                                   "erwartungswert_euro": 500, "lead_typ": "Hot"})
    db_evaluated.insert_evaluated({"name": "OhneStadt", "stadt": "", "lead_key": "k2"})
    rows = db_evaluated.get_for_globe()
    assert len(rows) == 1 and rows[0]["name"] == "MitStadt"
    assert set(rows[0].keys()) == {"name", "stadt", "branche", "lead_typ",
                                   "adresse", "erwartungswert_euro"}


def test_db_websites_has_site_key(tmp_path, monkeypatch):
    import db_websites
    from pathlib import Path
    monkeypatch.setattr(db_websites, "DB_PATH", Path(tmp_path) / "websites.db")
    assert db_websites.has_site_key("") is False
    assert db_websites.has_site_key("nix-da") is False    # ohne Tabelle → False, kein Crash
    db_websites.init_db()
    jid = "job-test-1"
    db_websites.create(jid, "Test GmbH", "Ulm", "Dachdecker")   # setzt site_key automatisch
    row = db_websites.get_by_job(jid)
    assert row and row.get("site_key")
    assert db_websites.has_site_key(row["site_key"]) is True


# ── Paid-Boost: bezahlte Extra-Tokens erkennen → doppeltes Bau-Limit ──────────
def test_paid_tokens_detected_und_boost(tmp_path, monkeypatch):
    import cost_tracker as ct
    import claude_keys
    monkeypatch.setattr(ct, "_DB_PATH", tmp_path / "costs.json")
    monkeypatch.setattr(claude_keys, "count", lambda: 1)
    monkeypatch.setattr(ct, "_PAID_CACHE", [None, 0.0])   # TTL-Cache isolieren
    monkeypatch.setenv("JARVIS_PAID_BOOST", "1")
    # Keine Kosten + 1 Key → kein Paid-Modus
    d = ct.paid_tokens_detected()
    assert d["paid"] is False and ct.paid_boost_active() is False
    # OpenAI-Bild bucht zwar api_eur, aber KEINE Tokens → kein Boost (das Claude-
    # Session-Limit bleibt der Engpass, Hero-Bilder heben es nicht auf).
    ct.track_openai_image("medium", task="image_gen")
    assert ct.paid_tokens_detected()["paid"] is False
    # Echte API-TOKENS gebucht → Paid-Modus erkannt
    ct.track_api("claude-sonnet-5", 1000, 500, task="test")
    d = ct.paid_tokens_detected()
    assert d["paid"] is True and d["api_eur_today"] > 0
    monkeypatch.setattr(ct, "_PAID_CACHE", [None, 0.0])   # Cache invalidieren → neu erkennen
    assert ct.paid_boost_active() is True
    # Schalter aus → kein Boost trotz Kosten
    monkeypatch.setenv("JARVIS_PAID_BOOST", "0")
    assert ct.paid_boost_active() is False


def test_paid_boost_mehrere_keys(tmp_path, monkeypatch):
    import cost_tracker as ct
    import claude_keys
    monkeypatch.setattr(ct, "_DB_PATH", tmp_path / "costs.json")
    monkeypatch.setenv("JARVIS_PAID_BOOST", "1")
    monkeypatch.setattr(claude_keys, "count", lambda: 3)   # 3 Keys → API-Key-Modus
    d = ct.paid_tokens_detected()
    assert d["paid"] is True and "Keys" in d["reason"]


def test_auto_builder_daily_limit_boost(monkeypatch):
    import auto_builder as ab
    import cost_tracker as ct
    monkeypatch.setattr(ab, "_boost_logged", [True])   # Log-Latch neutralisieren
    monkeypatch.setattr(ct, "paid_boost_active", lambda: False)
    base = ab._DAILY_LIMIT
    assert ab._daily_limit() == base                   # ohne Paid-Modus: Basis-Limit
    monkeypatch.setattr(ct, "paid_boost_active", lambda: True)
    assert ab._daily_limit() == base * 2               # Paid-Boost: doppelt
    st = ab.status()
    assert st["daily_limit"] == base * 2 and st["paid_boost"] is True


# ── Extra-Nutzungs-Check (5-Min-Herzschlag ab Start, sofortige Meldung) ────────
def test_extra_usage_check_once_activates_and_notifies(tmp_path, monkeypatch):
    import extra_usage_watch as eu
    import cost_tracker, discord_bot
    monkeypatch.setattr(eu, "_LATCH", tmp_path / "extra_usage_state.json")
    monkeypatch.setattr(cost_tracker, "paid_boost_active", lambda: True)
    monkeypatch.setattr(cost_tracker, "paid_tokens_detected",
                        lambda: {"paid": True, "reason": "heute 1.000 API-Tokens gebucht"})
    calls = []
    monkeypatch.setattr(discord_bot, "notify", lambda *a, **k: calls.append(a) or True)
    res = eu.check_once()
    assert res == {"active": True, "changed": True}
    assert eu.status()["active"] is True
    assert len(calls) == 1 and "Extra-Modus" in calls[0][0]


def test_extra_usage_check_once_no_repeat_notify(tmp_path, monkeypatch):
    import extra_usage_watch as eu
    import cost_tracker, discord_bot
    monkeypatch.setattr(eu, "_LATCH", tmp_path / "extra_usage_state.json")
    monkeypatch.setattr(cost_tracker, "paid_boost_active", lambda: True)
    monkeypatch.setattr(cost_tracker, "paid_tokens_detected", lambda: {"paid": True, "reason": ""})
    calls = []
    monkeypatch.setattr(discord_bot, "notify", lambda *a, **k: calls.append(a) or True)
    eu.check_once()
    res2 = eu.check_once()                      # weiter aktiv -> KEIN erneuter Ping
    assert res2 == {"active": True, "changed": False}
    assert len(calls) == 1


def test_extra_usage_check_once_detects_deactivation(tmp_path, monkeypatch):
    import extra_usage_watch as eu
    import cost_tracker
    monkeypatch.setattr(eu, "_LATCH", tmp_path / "extra_usage_state.json")
    monkeypatch.setattr(cost_tracker, "paid_boost_active", lambda: True)
    monkeypatch.setattr(cost_tracker, "paid_tokens_detected", lambda: {"paid": True, "reason": ""})
    eu.check_once()
    monkeypatch.setattr(cost_tracker, "paid_boost_active", lambda: False)
    res = eu.check_once()
    assert res == {"active": False, "changed": True}
    assert eu.status()["active"] is False


def test_extra_usage_interval_env(monkeypatch):
    import extra_usage_watch as eu
    monkeypatch.delenv("JARVIS_EXTRA_USAGE_POLL", raising=False)
    assert eu._interval() == 300                # Default 5 Min
    monkeypatch.setenv("JARVIS_EXTRA_USAGE_POLL", "30")
    assert eu._interval() == 60                  # hart-minimiert
    monkeypatch.setenv("JARVIS_EXTRA_USAGE_POLL", "600")
    assert eu._interval() == 600


# ── ask_ollama: Fehler loggen statt still verschlucken ────────────────────────
def test_ask_ollama_unerwarteter_fehler_gibt_leer(monkeypatch):
    from scrapers import _http
    def _boom(*a, **k):
        raise ValueError("kaputtes JSON")
    monkeypatch.setattr(_http.urllib.request, "urlopen", _boom)
    assert _http.ask_ollama("test", model="x") == ""   # kein Crash, leerer Fallback
