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
