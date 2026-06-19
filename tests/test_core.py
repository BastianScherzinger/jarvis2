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
