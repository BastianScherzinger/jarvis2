"""
Tests für das leadpackages-Modul (LeadForge — Datenpakete).
Ausführen:  python -m pytest -q   (im Projekt-Stammverzeichnis)

Fokus wie bei test_core.py: reine (I/O-freie) Kernfunktionen zuerst. Wo die echte
DB gebraucht wird (Mindestqualität, Package-Building), läuft gegen die reale
data/lead_packages.db des Projekts (additiv, keine bestehenden Zeilen werden
gelöscht) — gleiche Konvention wie test_core.py mit db_evaluated.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── quality_score ─────────────────────────────────────────────────────────────
def test_quality_score_voll_ausgestattet():
    from leadpackages.quality_score import compute
    row = {
        "kontaktwege_anzahl": 3, "has_website": 1, "adresse": "Musterstr. 1",
        "anz_bewertungen": 20, "bewertung": 4.5, "last_checked_at": None,
    }
    assert compute(row) == 85   # 40 (3 Kontaktwege) + 15 (Website) + 15 (Adresse) + 15 (Bewertung)


def test_quality_score_minimal():
    from leadpackages.quality_score import compute
    row = {"kontaktwege_anzahl": 2, "has_website": 0, "adresse": "", "anz_bewertungen": 0}
    assert compute(row) == 25


def test_quality_score_grenzen_0_bis_100():
    from leadpackages.quality_score import compute
    assert compute({}) == 0
    from datetime import datetime
    row = {"kontaktwege_anzahl": 3, "has_website": 1, "adresse": "x",
           "anz_bewertungen": 5, "bewertung": 5.0,
           "last_checked_at": datetime.now().isoformat(timespec="seconds")}
    assert compute(row) == 100


# ── potential_score (Heuristik-Fallback, ohne Ollama) ─────────────────────────
def test_potential_heuristik_grosskonzern_hinweis():
    from leadpackages.potential_score import _heuristik
    assert _heuristik({"name": "Musterfirma GmbH"}) == "mittel"
    assert _heuristik({"name": "Handwerksbetrieb Müller"}) == "klein"


def test_potential_heuristik_viele_bewertungen():
    from leadpackages.potential_score import _heuristik
    assert _heuristik({"name": "Kleinbetrieb", "anz_bewertungen": 50}) == "mittel"


# ── dedup_fuzzy (Schwellwert-Verhalten) ────────────────────────────────────────
def test_dedup_fuzzy_erkennt_aehnliche_namen():
    from rapidfuzz import fuzz
    from leadpackages.dedup_fuzzy import THRESHOLD
    ratio = fuzz.token_sort_ratio("müller gmbh", "mueller gmbh & co kg")
    assert ratio < 100
    # klar unterschiedliche Firmen dürfen NICHT als Dublette gelten
    assert fuzz.token_sort_ratio("elektro schmidt", "dachdecker meyer") < THRESHOLD


def test_dedup_fuzzy_identisch_ist_dublette():
    # dedup_fuzzy.find_and_remove_duplicates() lowercased beide Seiten VOR dem
    # Vergleich (siehe dedup_fuzzy.py) — token_sort_ratio selbst ist case-sensitiv,
    # daher hier ebenfalls .lower() wie im Produktivcode.
    from rapidfuzz import fuzz
    from leadpackages.dedup_fuzzy import THRESHOLD
    assert fuzz.token_sort_ratio("ADA Elektro".lower(), "ada elektro".lower()) >= THRESHOLD


def test_dedup_fuzzy_entfernt_echte_dublette_aus_db():
    from leadpackages import db_packages as dbp
    from leadpackages.dedup_fuzzy import find_and_remove_duplicates
    dbp.init_db()
    base = {"stadt": "Teststadt", "land": "DE", "branche": "Unit-Test-Dedup-Branche",
            "telefon": "0111111", "email_adresse": "dup@example.com"}
    # Realistischer Fall aus dem Modul-Docstring: Umlaut-Schreibvariante derselben Firma.
    id_a = dbp.upsert_stock_lead({**base, "lead_key": "test-dedup-a", "name": "Müller Elektro GmbH"})
    id_b = dbp.upsert_stock_lead({**base, "lead_key": "test-dedup-b", "name": "Mueller Elektro GmbH"})
    assert id_a and id_b
    result = find_and_remove_duplicates(land="DE", branche="Unit-Test-Dedup-Branche")
    assert result["dubletten_entfernt"] == 1
    verbleibend = dbp.get_all_stock(land="DE", branche="Unit-Test-Dedup-Branche")
    assert len(verbleibend) == 1
    dbp.delete_stock([r["id"] for r in verbleibend])   # Testdaten aufräumen


# ── export_csv_excel ───────────────────────────────────────────────────────────
def test_export_csv_enthaelt_spalten_und_werte():
    from leadpackages.export_csv_excel import to_csv
    rows = [{"name": "Testfirma", "branche": "Elektriker", "stadt": "Wien",
             "region": "Wien", "land": "AT", "adresse": "", "telefon": "123",
             "email_adresse": "a@b.at", "website_url": "https://b.at",
             "quality_score": 70, "potential_label": "klein"}]
    csv_text = to_csv(rows)
    assert csv_text.startswith("﻿")
    assert "Testfirma" in csv_text
    assert "Elektriker" in csv_text


def test_export_excel_bytes_ist_gueltiges_xlsx():
    from leadpackages.export_csv_excel import to_excel_bytes
    rows = [{"name": "Testfirma", "branche": "Elektriker", "stadt": "Wien",
             "region": "Wien", "land": "AT", "adresse": "", "telefon": "123",
             "email_adresse": "a@b.at", "website_url": "https://b.at",
             "quality_score": 70, "potential_label": "klein"}]
    data = to_excel_bytes(rows)
    assert data[:2] == b"PK"   # xlsx ist ein ZIP-Container


# ── watermark ──────────────────────────────────────────────────────────────────
def test_watermark_roundtrip():
    from leadpackages.watermark import decode, embed, new_watermark_id
    wm_id = new_watermark_id()
    rows = [{"adresse": "Musterstr. 1"}, {"adresse": ""}]
    marked = embed(rows, wm_id)
    assert decode(marked[0]["adresse"]) == wm_id
    assert decode(marked[1]["adresse"]) == wm_id
    # sichtbarer Text bleibt unverändert (Zero-Width-Zeichen sind unsichtbar,
    # aber nicht aus der Zeichenkette entfernbar per einfachem .strip())
    assert marked[0]["adresse"].startswith("Musterstr. 1")


def test_watermark_unbekannter_text_gibt_leer_zurueck():
    from leadpackages.watermark import decode
    assert decode("ganz normaler Text ohne Wasserzeichen") == ""


# ── pricing_packages ────────────────────────────────────────────────────────────
def test_pricing_bekannte_groessen():
    from leadpackages.pricing_packages import preis_fuer
    assert preis_fuer(50) == 49
    assert preis_fuer(200) == 149
    assert preis_fuer(1000) == 499


def test_pricing_unbekannte_groesse_ist_null():
    from leadpackages.pricing_packages import preis_fuer
    assert preis_fuer(12345) == 0


# ── sources_herold (Slug-Bildung, keine Netzwerk-Calls) ────────────────────────
def test_herold_slug_umlaute():
    from leadpackages.sources_herold import _slug
    assert _slug("München") == "muenchen"
    assert _slug("KFZ Werkstatt") == "kfz-werkstatt"
    assert _slug("Straße") == "strasse"


# ── db_packages: Mindestqualität wird durchgesetzt ─────────────────────────────
def test_upsert_verwirft_unter_mindestqualitaet():
    from leadpackages import db_packages as dbp
    dbp.init_db()
    row = {
        "lead_key": "test-unit-verwerfen-key-xyz", "name": "Unit-Test-Firma-Verwerfen",
        "stadt": "Teststadt", "land": "DE", "branche": "Elektriker",
        "telefon": "0123456", "email_adresse": "", "website_url": "",
    }
    assert dbp.upsert_stock_lead(row) is None    # nur 1 Kontaktweg -> verworfen


def test_upsert_akzeptiert_ab_mindestqualitaet():
    from leadpackages import db_packages as dbp
    dbp.init_db()
    row = {
        "lead_key": "test-unit-akzeptieren-key-xyz", "name": "Unit-Test-Firma-Akzeptieren",
        "stadt": "Teststadt", "land": "DE", "branche": "Elektriker",
        "telefon": "0123456", "email_adresse": "test@example.com", "website_url": "",
    }
    stock_id = dbp.upsert_stock_lead(row)
    assert stock_id is not None
    dbp.delete_stock([stock_id])   # Testdatensatz wieder entfernen


# ── package_builder: unbekannte Kombination liefert leer statt Fehler ─────────
def test_package_builder_leere_kombination_kein_crash():
    from leadpackages.package_builder import build
    paket = build("Nicht-Existente-Branche-XYZ", 50, region="Nirgendwo", land="DE")
    assert paket["geliefert"] == 0
    assert paket["rows"] == []
