"""
test_pipeline.py — sichert die „5-Seiten-Builder + nach Löschen neu bauen"-Invariante ab
sowie die Hero-Vorlagen-Logik. Reine Logik-Tests (kein Netz, kein echtes Deploy).
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Hero-Vorlagen ──────────────────────────────────────────────────────────────

def test_hero_template_pick_branche():
    import hero_templates as ht
    assert ht.pick("Zahnarzt").name == "zahnarzt.jpg"
    assert ht.pick("KFZ Werkstatt").name == "kfz.jpg"
    assert ht.pick("Physiotherapeut").name == "physio.jpg"
    assert ht.pick("Umzugsunternehmen").name == "umzug.jpg"
    assert ht.pick("Heizungsbauer").name == "sanitaer.jpg"
    assert ht.pick("Elektriker").name == "elektriker.jpg"
    # keine Vorlage → None (Fallback auf bisherige Hero-Logik)
    assert ht.pick("Rechtsanwalt") is None
    assert ht.pick("") is None


def test_hero_template_apply_und_respektiert_leadfoto(tmp_path):
    import hero_templates as ht
    folder = Path(tmp_path)
    (folder / "static" / "img").mkdir(parents=True)
    # Branche mit Vorlage → kopiert + setzt hero_source
    content = {"branche": "Zahnarzt"}
    assert ht.apply(folder, "Zahnarzt", content) is True
    assert (folder / "static" / "img" / "hero.png").is_file()
    assert content["hero_source"] == "template"
    assert content["hero_template"] == "zahnarzt.jpg"
    # Lead-Foto-Hero wird NICHT überschrieben
    assert ht.apply(folder, "Zahnarzt", {"hero_source": "lead_foto"}) is False
    # hochgeladenes Hero wird NICHT überschrieben
    assert ht.apply(folder, "Zahnarzt", {"hero_custom": True}) is False
    # Branche ohne Vorlage → nichts passiert
    assert ht.apply(folder, "Rechtsanwalt", {}) is False


# ── Night-Builder: nach Löschen wird wieder aufgefüllt (Kern-Invariante) ────────

def test_count_today_zaehlt_nur_existierende(tmp_path, monkeypatch):
    """daily_builds zählt 5 Seiten heute, aber 3 Ordner sind gelöscht und keine DB-Zeile →
    _count_today() liefert nur die 2 verbliebenen → der Builder baut wieder auf 5 auf."""
    import auto_builder as ab

    # 5 Seiten heute „gebaut" — 2 Ordner existieren, 3 wurden gelöscht.
    bleibt1 = tmp_path / "web_a"; bleibt1.mkdir()
    bleibt2 = tmp_path / "web_b"; bleibt2.mkdir()
    entries = [
        {"name": "A", "folder": str(bleibt1)},
        {"name": "B", "folder": str(bleibt2)},
        {"name": "C", "folder": str(tmp_path / "web_c_geloescht")},
        {"name": "D", "folder": str(tmp_path / "web_d_geloescht")},
        {"name": "E", "folder": str(tmp_path / "web_e_geloescht")},
    ]
    log_path = tmp_path / "daily_builds.json"
    log_path.write_text(json.dumps({ab._today(): entries}), encoding="utf-8")
    monkeypatch.setattr(ab, "_LOG_PATH", log_path)
    # Keine aktiven Webseiten-Zeilen (gelöschte sind weg).
    import db_websites
    monkeypatch.setattr(db_websites, "get_all", lambda *a, **k: [])

    assert ab._count_today() == 2          # nur die 2 existierenden zählen
    # 5er-Limit: es sind also wieder 3 Plätze frei → Builder baut nach.
    assert ab._count_today() < ab._DAILY_LIMIT


def test_count_today_zaehlt_db_zeile_ohne_ordner(tmp_path, monkeypatch):
    """Eine heute gebaute Seite, deren Ordner (noch) nicht da ist, aber eine aktive DB-Zeile
    hat, zählt trotzdem (nicht doppelt bauen)."""
    import auto_builder as ab
    f = tmp_path / "web_db_only"          # Ordner existiert NICHT
    entries = [{"name": "X", "folder": str(f)}]
    log_path = tmp_path / "daily_builds.json"
    log_path.write_text(json.dumps({ab._today(): entries}), encoding="utf-8")
    monkeypatch.setattr(ab, "_LOG_PATH", log_path)
    import db_websites
    monkeypatch.setattr(db_websites, "get_all",
                        lambda *a, **k: [{"folder": str(f), "archived": 0}])
    assert ab._count_today() == 1


# ── Rettung: unterbrochene/nicht-live Seiten werden erkannt ─────────────────────

def test_needs_rescue():
    import auto_builder as ab
    # fertig + live → keine Rettung
    assert ab._needs_rescue({"status": "done", "live": 1, "live_url": "https://x.up.railway.app"}) is False
    # nicht fertig → Rettung
    assert ab._needs_rescue({"status": "error", "live": 1, "live_url": "https://x"}) is True
    # fertig, aber nicht live → Rettung
    assert ab._needs_rescue({"status": "done", "live": 0, "live_url": ""}) is True
    assert ab._needs_rescue({"status": "done", "live": 1, "live_url": ""}) is True
