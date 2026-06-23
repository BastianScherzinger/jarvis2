"""
DB2 — KI-angereicherte Lead-Bewertungen. Wird vom Evaluator-Team befüllt.
"""
import hashlib
import sqlite3
import threading
from pathlib import Path


def _compute_lead_key(name: str, stadt: str) -> str:
    """Globaler Dedup-Schlüssel — zentrale Definition in leadkey.py."""
    from leadkey import lead_key
    return lead_key(name, stadt)

DB_PATH = Path(__file__).parent / "data" / "leads_evaluated.db"
_lock   = threading.Lock()

# Alle bekannten Spalten — fremde Keys werden beim Insert gefiltert.
_COLUMNS = [
    "raw_id", "lead_key", "schluessel", "name", "adresse", "stadt", "bundesland", "branche",
    "telefon", "email_vorhanden", "email_adresse", "email_alle", "ansprechpartner",
    "telefon_verifiziert",
    "has_website", "website_url", "discovered_website", "website_veraltet",
    "website_alter_jahre", "website_probleme", "fotos_in_maps", "bilder_vorhanden",
    "foto_url", "foto_urls", "social_media", "hat_nur_social",
    "beschreibung", "ist_privat_zahler", "firmengroesse", "potenzial_euro",
    "erwartungswert_euro", "sicherheit", "sicherheit_breakdown",
    "potenzial_begruendung", "pitch_hook", "score", "lead_typ", "email_entwurf",
    "email_status", "email_gesendet_am", "email_fehler", "email_opt_out",
    "notiz", "kontaktiert_am", "termin_am", "verkauft_am", "verkauft_euro",
    "score_breakdown", "verify_log", "verifiziert", "status", "bewertet_am",
    "finder", "mockup_url",
]

# Neue Spalten (Name → SQL-Definition) für die Migration bestehender DBs.
_NEW_COLUMNS = {
    "discovered_website":  "TEXT",
    "bilder_vorhanden":    "INTEGER DEFAULT 0",
    "foto_url":            "TEXT",
    "foto_urls":           "TEXT",            # JSON-Liste aller gefundenen Bild-URLs
    "score_breakdown":     "TEXT",
    "verify_log":          "TEXT",
    "verifiziert":         "INTEGER DEFAULT 1",
    "lead_key":            "TEXT",
    # Säule 3 — echte Bewertung
    "sicherheit":          "INTEGER DEFAULT 0",
    "erwartungswert_euro": "INTEGER DEFAULT 0",
    "sicherheit_breakdown":"TEXT",
    # Säule 3 — tiefere Info-Findung
    "email_alle":          "TEXT",            # JSON-Liste aller gefundenen E-Mails
    "ansprechpartner":     "TEXT",            # Inhaber/GF aus Impressum
    # Säule 6 — Auto-E-Mail (Gerüst, Versand vorerst deaktiviert)
    "email_status":        "TEXT DEFAULT 'entwurf'",
    "email_gesendet_am":   "TEXT",
    "email_fehler":        "TEXT",
    "email_opt_out":       "INTEGER DEFAULT 0",
    "notiz":               "TEXT",            # freie CRM-Notiz (vom Agenten/Dashboard)
    # Konversions-Tracking (Feedback-Loop fürs Scoring)
    "kontaktiert_am":      "TEXT",
    "termin_am":           "TEXT",
    "verkauft_am":         "TEXT",
    "verkauft_euro":       "INTEGER DEFAULT 0",
    # Feed-Konsolidierung (leads.db eliminiert): Quelle + Mockup am kanonischen Lead
    "finder":              "TEXT",
    "mockup_url":          "TEXT",
}


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")   # unter Last warten statt sofort 'locked'
    return c


def init_db() -> None:
    with _lock, _conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS evaluated_leads (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            raw_id                INTEGER UNIQUE,
            schluessel            TEXT,
            name                  TEXT,
            adresse               TEXT,
            stadt                 TEXT,
            bundesland            TEXT,
            branche               TEXT,
            telefon               TEXT,
            email_vorhanden       INTEGER DEFAULT 0,
            email_adresse         TEXT,
            telefon_verifiziert   INTEGER DEFAULT 0,
            has_website           INTEGER DEFAULT 0,
            website_url           TEXT,
            discovered_website    TEXT,
            website_veraltet      INTEGER DEFAULT 0,
            website_alter_jahre   INTEGER DEFAULT -1,
            website_probleme      TEXT,
            fotos_in_maps         INTEGER DEFAULT 0,
            bilder_vorhanden      INTEGER DEFAULT 0,
            foto_url              TEXT,
            social_media          TEXT,
            hat_nur_social        INTEGER DEFAULT 0,
            beschreibung          TEXT,
            ist_privat_zahler     INTEGER DEFAULT 0,
            firmengroesse         TEXT,
            potenzial_euro        INTEGER DEFAULT 0,
            potenzial_begruendung TEXT,
            pitch_hook            TEXT,
            score                 INTEGER DEFAULT 0,
            lead_typ              TEXT DEFAULT 'Cold',
            email_entwurf         TEXT,
            score_breakdown       TEXT,
            verify_log            TEXT,
            verifiziert           INTEGER DEFAULT 1,
            status                TEXT DEFAULT 'neu',
            bewertet_am           TEXT,
            lead_key              TEXT
        )
        """)
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_score "
            "ON evaluated_leads(score DESC, lead_typ, ist_privat_zahler)"
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_status  ON evaluated_leads(status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_branche ON evaluated_leads(branche, bundesland)")
        c.commit()
    migrate()
    # Unique-Index für lead_key NACH migrate() — Spalte existiert jetzt sicher
    with _lock, _conn() as c:
        c.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_lead_key "
            "ON evaluated_leads(lead_key) WHERE lead_key IS NOT NULL"
        )
        c.commit()


def migrate() -> None:
    """Ergänzt fehlende Spalten in einer bestehenden DB (idempotent)."""
    with _lock, _conn() as c:
        have = {r["name"] for r in c.execute("PRAGMA table_info(evaluated_leads)")}
        for col, sql_def in _NEW_COLUMNS.items():
            if col not in have:
                c.execute(f"ALTER TABLE evaluated_leads ADD COLUMN {col} {sql_def}")
        c.commit()


def insert_evaluated(data: dict) -> int | None:
    """INSERT OR REPLACE — nutzt lead_key (global) oder raw_id (lokal) für Dedup."""
    row = {k: data[k] for k in _COLUMNS if k in data}
    # lead_key immer befüllen (kein Kreisimport — lokale Funktion)
    if not row.get("lead_key"):
        row["lead_key"] = _compute_lead_key(data.get("name", ""), data.get("stadt", ""))
    # raw_id ist optional (None für remote Leads aus Pull)
    if not row.get("raw_id") and not row.get("lead_key"):
        return None
    cols = ", ".join(row.keys())
    ph   = ", ".join("?" for _ in row)
    with _lock, _conn() as c:
        cur = c.execute(
            f"INSERT OR REPLACE INTO evaluated_leads ({cols}) VALUES ({ph})",
            list(row.values()),
        )
        c.commit()
        return cur.lastrowid


def get_top(limit: int = 10) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM evaluated_leads "
            "ORDER BY score DESC, ist_privat_zahler DESC, potenzial_euro DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


_SORT_CLAUSES = {
    "score":         "score DESC",
    "sicherheit":    "sicherheit DESC, score DESC",
    "erwartungswert":"erwartungswert_euro DESC, sicherheit DESC",
    "potenzial":     "potenzial_euro DESC",
    "datum":         "bewertet_am DESC",
}


def get_all(limit: int = 500, offset: int = 0, branche: str | None = None,
            bundesland: str | None = None, lead_typ: str | None = None,
            sort: str = "score", suche: str = "") -> list[dict]:
    where  = []
    params: list = []
    if branche:
        where.append("branche=?");    params.append(branche)
    if bundesland:
        where.append("bundesland=?"); params.append(bundesland)
    if lead_typ:
        where.append("lead_typ=?");   params.append(lead_typ)
    if suche:
        where.append("(name LIKE ? OR stadt LIKE ? OR branche LIKE ?)")
        like = f"%{suche}%"
        params += [like, like, like]
    clause   = ("WHERE " + " AND ".join(where)) if where else ""
    order_by = _SORT_CLAUSES.get(sort, _SORT_CLAUSES["score"])
    params  += [limit, offset]
    with _lock, _conn() as c:
        rows = c.execute(
            f"SELECT * FROM evaluated_leads {clause} "
            f"ORDER BY {order_by} LIMIT ? OFFSET ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    with _lock, _conn() as c:
        total      = c.execute("SELECT COUNT(*) FROM evaluated_leads").fetchone()[0]
        hot        = c.execute("SELECT COUNT(*) FROM evaluated_leads WHERE lead_typ='Hot'").fetchone()[0]
        warm       = c.execute("SELECT COUNT(*) FROM evaluated_leads WHERE lead_typ='Warm'").fetchone()[0]
        cold       = c.execute("SELECT COUNT(*) FROM evaluated_leads WHERE lead_typ='Cold'").fetchone()[0]
        mit_email  = c.execute("SELECT COUNT(*) FROM evaluated_leads WHERE email_vorhanden=1").fetchone()[0]
        ohne_web   = c.execute("SELECT COUNT(*) FROM evaluated_leads WHERE has_website=0").fetchone()[0]
        privat     = c.execute("SELECT COUNT(*) FROM evaluated_leads WHERE ist_privat_zahler=1").fetchone()[0]
        avg_pot    = c.execute("SELECT AVG(potenzial_euro) FROM evaluated_leads").fetchone()[0] or 0
        sum_pot    = c.execute("SELECT SUM(potenzial_euro) FROM evaluated_leads").fetchone()[0] or 0
        mit_bild   = c.execute("SELECT COUNT(*) FROM evaluated_leads WHERE bilder_vorhanden=1").fetchone()[0]
        ohne_web_e = c.execute("SELECT COUNT(*) FROM evaluated_leads WHERE has_website=0").fetchone()[0]
        br_rows = c.execute(
            "SELECT branche, COUNT(*) AS n FROM evaluated_leads "
            "GROUP BY branche ORDER BY n DESC LIMIT 15"
        ).fetchall()
        bl_rows = c.execute(
            "SELECT bundesland, COUNT(*) AS n FROM evaluated_leads "
            "GROUP BY bundesland ORDER BY n DESC LIMIT 20"
        ).fetchall()
    return {
        "total":            total,
        "hot":              hot,
        "warm":             warm,
        "cold":             cold,
        "mit_email":        mit_email,
        "ohne_website":     ohne_web,
        "privat_zahler":    privat,
        "avg_potenzial":    round(avg_pot),
        "summe_potenzial":  round(sum_pot),
        "mit_bildern":      mit_bild,
        "ohne_website_echt": ohne_web_e,
        "top_branchen":     {r["branche"]: r["n"] for r in br_rows if r["branche"]},
        "top_bundeslaender": {r["bundesland"]: r["n"] for r in bl_rows if r["bundesland"]},
    }


def get_typ_counts() -> dict:
    """Leichte Hot/Warm/Cold-Zähler fürs Dashboard (ohne die volle get_stats-Runde)."""
    with _lock, _conn() as c:
        hot  = c.execute("SELECT COUNT(*) FROM evaluated_leads WHERE lead_typ='Hot'").fetchone()[0]
        warm = c.execute("SELECT COUNT(*) FROM evaluated_leads WHERE lead_typ='Warm'").fetchone()[0]
        cold = c.execute("SELECT COUNT(*) FROM evaluated_leads WHERE lead_typ='Cold'").fetchone()[0]
    return {"hot": hot, "warm": warm, "cold": cold}


def set_mockup(eval_id: int, url: str) -> None:
    with _lock, _conn() as c:
        c.execute("UPDATE evaluated_leads SET mockup_url=? WHERE id=?", (url, eval_id))
        c.commit()


def set_email_entwurf(eval_id: int, entwurf_json: str) -> None:
    with _lock, _conn() as c:
        c.execute("UPDATE evaluated_leads SET email_entwurf=? WHERE id=?", (entwurf_json, eval_id))
        c.commit()


def update_status(eval_id: int, status: str) -> None:
    from datetime import datetime
    ts  = datetime.now().isoformat(timespec="seconds")
    col = {"kontaktiert": "kontaktiert_am", "termin": "termin_am",
           "verkauft": "verkauft_am"}.get(status)          # feste Whitelist → f-string sicher
    with _lock, _conn() as c:
        if col:
            c.execute(f"UPDATE evaluated_leads SET status=?, {col}=COALESCE({col}, ?) WHERE id=?",
                      (status, ts, eval_id))
        else:
            c.execute("UPDATE evaluated_leads SET status=? WHERE id=?", (status, eval_id))
        c.commit()
        row = c.execute("SELECT * FROM evaluated_leads WHERE id=?", (eval_id,)).fetchone()
    # Status-Änderung auch in die Cloud spiegeln (fire-and-forget, beste Mühe)
    if row:
        try:
            from cloud_sync import push_lead
            push_lead(dict(row))
        except Exception:
            pass


def get_by_id(eval_id: int) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM evaluated_leads WHERE id=?", (eval_id,)).fetchone()
    return dict(row) if row else None


def set_email_status(eval_id: int, status: str, fehler: str = "") -> None:
    """Setzt den E-Mail-Versandstatus eines Leads (entwurf|gesendet|fehler|opt_out|…)."""
    from datetime import datetime
    ts = datetime.now().isoformat(timespec="seconds") if status == "gesendet" else None
    with _lock, _conn() as c:
        c.execute(
            "UPDATE evaluated_leads SET email_status=?, "
            "email_gesendet_am=COALESCE(?, email_gesendet_am), email_fehler=? WHERE id=?",
            (status, ts, fehler, eval_id),
        )
        c.commit()


def set_opt_out(eval_id: int, opt_out: int = 1) -> None:
    with _lock, _conn() as c:
        c.execute("UPDATE evaluated_leads SET email_opt_out=? WHERE id=?", (int(opt_out), eval_id))
        c.commit()


def set_notiz(eval_id: int, notiz: str) -> None:
    """Setzt/ergänzt die freie CRM-Notiz und spiegelt sie in die Cloud."""
    with _lock, _conn() as c:
        c.execute("UPDATE evaluated_leads SET notiz=? WHERE id=?", (notiz, eval_id))
        c.commit()
        row = c.execute("SELECT * FROM evaluated_leads WHERE id=?", (eval_id,)).fetchone()
    if row:
        try:
            from cloud_sync import push_lead
            push_lead(dict(row))
        except Exception:
            pass


def set_verkauft_euro(eval_id: int, euro: int) -> None:
    """Erfasst den realisierten Umsatz eines Leads (Feedback-Loop)."""
    with _lock, _conn() as c:
        c.execute("UPDATE evaluated_leads SET verkauft_euro=? WHERE id=?", (int(euro or 0), eval_id))
        c.commit()
        row = c.execute("SELECT * FROM evaluated_leads WHERE id=?", (eval_id,)).fetchone()
    if row:
        try:
            from cloud_sync import push_lead
            push_lead(dict(row))
        except Exception:
            pass


def get_conversion_stats() -> dict:
    """Feedback-Loop: was wird tatsächlich zu Kunden? Konversion nach Status,
    Branche und Score-Band — als Realitäts-Abgleich fürs Scoring-Modell."""
    with _lock, _conn() as c:
        by_status = {r["status"]: r["n"] for r in c.execute(
            "SELECT status, COUNT(*) AS n FROM evaluated_leads GROUP BY status")}
        umsatz = c.execute(
            "SELECT COALESCE(SUM(verkauft_euro),0) FROM evaluated_leads WHERE status='verkauft'"
        ).fetchone()[0] or 0
        # Konversion (verkauft/gesamt) je Branche, nur Branchen mit Aktivität
        br = c.execute(
            "SELECT branche, "
            " SUM(CASE WHEN status='verkauft' THEN 1 ELSE 0 END) AS verkauft, "
            " SUM(CASE WHEN status IN ('kontaktiert','termin','verkauft') THEN 1 ELSE 0 END) AS aktiv, "
            " COUNT(*) AS gesamt "
            "FROM evaluated_leads GROUP BY branche "
            "HAVING aktiv > 0 ORDER BY verkauft DESC LIMIT 15").fetchall()
        # Konversion je Score-Band
        band = c.execute(
            "SELECT CASE WHEN score>=72 THEN 'Hot(72+)' WHEN score>=48 THEN 'Warm(48-71)' ELSE 'Cold(<48)' END AS band, "
            " SUM(CASE WHEN status='verkauft' THEN 1 ELSE 0 END) AS verkauft, "
            " SUM(CASE WHEN status IN ('kontaktiert','termin','verkauft') THEN 1 ELSE 0 END) AS aktiv "
            "FROM evaluated_leads GROUP BY band").fetchall()
    return {
        "nach_status": by_status,
        "umsatz_verkauft_euro": umsatz,
        "nach_branche": [dict(r) for r in br],
        "nach_score_band": [dict(r) for r in band],
    }


def archive_lead(eval_id: int, reason: str = "bereits bearbeitet") -> None:
    """Markiert einen Lead als 'Archiviert' mit 0 € Erwartungswert.

    Archivierte Leads werden von _pick_next_lead() übersprungen und tauchen
    nicht mehr als Bau-Kandidaten auf. Der original-Score bleibt für Stats
    erhalten; nur lead_typ und erwartungswert_euro werden überschrieben."""
    note = reason[:300]
    with _lock, _conn() as c:
        c.execute(
            "UPDATE evaluated_leads "
            "SET lead_typ='Archiviert', erwartungswert_euro=0, "
            "    beschreibung=?, status='archiviert' "
            "WHERE id=?",
            (note, eval_id),
        )
        c.commit()
        row = c.execute("SELECT * FROM evaluated_leads WHERE id=?", (eval_id,)).fetchone()
    if row:
        try:
            from cloud_sync import push_lead
            push_lead(dict(row))
        except Exception:
            pass


def clear_all() -> int:
    """Leert die komplette evaluated_leads-Tabelle. Gibt Anzahl gelöschter Zeilen zurück."""
    with _lock, _conn() as c:
        n = c.execute("SELECT COUNT(*) FROM evaluated_leads").fetchone()[0]
        c.execute("DELETE FROM evaluated_leads")
        c.commit()
    return n


def get_by_raw_id(raw_id: int) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT * FROM evaluated_leads WHERE raw_id=?", (raw_id,)
        ).fetchone()
    return dict(row) if row else None


def get_for_graph(limit: int = 2000, offset: int = 0, min_id: int = 0) -> list[dict]:
    """Leichtgewichtige Knoten für die Graph-Visualisierung.

    min_id>0  → inkrementell: nur Knoten mit id > min_id (für Auto-Refresh).
    offset>0  → Seiten-Paginierung (id ASC).
    sonst     → bestes-zuerst (score DESC) für den initialen Vollabruf.
    """
    cols = ("id, name, branche, stadt, bundesland, score, "
            "potenzial_euro, lead_typ, has_website")
    with _lock, _conn() as c:
        if min_id > 0:
            rows = c.execute(
                f"SELECT {cols} FROM evaluated_leads "
                "WHERE id > ? ORDER BY id ASC LIMIT ?",
                (min_id, limit),
            ).fetchall()
        elif offset > 0:
            rows = c.execute(
                f"SELECT {cols} FROM evaluated_leads "
                "ORDER BY id ASC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        else:
            rows = c.execute(
                f"SELECT {cols} FROM evaluated_leads "
                "ORDER BY score DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_locations() -> list[dict]:
    """Aggregierte Lead-Standorte je Stadt (für die 3D-Globus-Visualisierung).
    Gibt [{stadt, bundesland, hot, warm, cold, n}] nach Häufigkeit absteigend."""
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT stadt, bundesland, lead_typ, COUNT(*) AS n FROM evaluated_leads "
            "WHERE stadt IS NOT NULL AND stadt != '' GROUP BY stadt, lead_typ"
        ).fetchall()
    agg: dict = {}
    for r in rows:
        stadt = (r["stadt"] or "").strip()
        if not stadt:
            continue
        d = agg.setdefault(stadt, {"stadt": stadt, "bundesland": (r["bundesland"] or "").strip(),
                                   "hot": 0, "warm": 0, "cold": 0, "n": 0})
        typ = (r["lead_typ"] or "Cold").lower()
        if typ in ("hot", "warm", "cold"):
            d[typ] += r["n"]
        d["n"] += r["n"]
        if not d["bundesland"] and r["bundesland"]:
            d["bundesland"] = r["bundesland"].strip()
    return sorted(agg.values(), key=lambda x: -x["n"])


def get_graph_stats() -> dict:
    """{bundesland: {branche: {hot: n, warm: n, cold: n}}}"""
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT bundesland, branche, lead_typ, COUNT(*) AS n "
            "FROM evaluated_leads GROUP BY bundesland, branche, lead_typ"
        ).fetchall()
    out: dict = {}
    for r in rows:
        bl  = r["bundesland"] or "Unbekannt"
        br  = r["branche"] or "Unbekannt"
        typ = (r["lead_typ"] or "Cold").lower()
        out.setdefault(bl, {}).setdefault(br, {"hot": 0, "warm": 0, "cold": 0})
        if typ in out[bl][br]:
            out[bl][br][typ] += r["n"]
    return out


# ── CSV-Export ──────────────────────────────────────────────────────────────
# Saubere, nach Score sortierte Tabelle mit sprechenden deutschen Spalten.
# Semikolon-Trennung + UTF-8-BOM → öffnet in deutschem Excel mit korrekten Umlauten.

_CSV_SPALTEN = [
    ("Rang",             None),
    ("Schlüssel",        "schluessel"),
    ("Score",            "score"),
    ("Sicherheit",       "sicherheit"),
    ("Erwartungswert (€)","erwartungswert_euro"),
    ("Typ",              "lead_typ"),
    ("Potenzial (€)",    "potenzial_euro"),
    ("Name",             "name"),
    ("Branche",          "branche"),
    ("Stadt",            "stadt"),
    ("Bundesland",       "bundesland"),
    ("Adresse",          "adresse"),
    ("Telefon",          "telefon"),
    ("E-Mail",           "email_adresse"),
    ("Ansprechpartner",  "ansprechpartner"),
    ("Website?",         "_website_status"),
    ("Website-URL",      "_website_url"),
    ("Website-Alter (J)","website_alter_jahre"),
    ("Website-Probleme", "_website_probleme"),
    ("Bilder?",          "_bilder"),
    ("Foto-URL",         "foto_url"),
    ("Firmengröße",      "firmengroesse"),
    ("Privatzahler?",    "_privat"),
    ("Pitch-Hook",       "pitch_hook"),
    ("Beschreibung",     "beschreibung"),
    ("Status",           "status"),
    ("Bewertet am",      "bewertet_am"),
]


def _csv_value(lead: dict, key: str) -> str:
    import json as _json
    if key == "_website_status":
        if not lead.get("has_website"):
            return "KEINE Website"
        return "veraltet" if lead.get("website_veraltet") else "vorhanden"
    if key == "_website_url":
        return lead.get("discovered_website") or lead.get("website_url") or ""
    if key == "_website_probleme":
        try:
            probs = _json.loads(lead.get("website_probleme") or "[]")
            return " | ".join(probs) if isinstance(probs, list) else ""
        except Exception:
            return ""
    if key == "_bilder":
        return "ja" if lead.get("bilder_vorhanden") else "nein"
    if key == "_privat":
        return "ja" if lead.get("ist_privat_zahler") else "nein"
    val = lead.get(key, "")
    return "" if val is None else str(val)


def export_csv() -> str:
    """Sortierter CSV-Export (Erwartungswert absteigend = sicherstes Geld zuerst) + BOM."""
    import csv, io
    rows = get_all(limit=100000, sort="erwartungswert")
    buf = io.StringIO()
    buf.write("﻿")   # UTF-8-BOM für Excel
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL,
                   lineterminator="\r\n")
    w.writerow([titel for titel, _ in _CSV_SPALTEN])
    for i, lead in enumerate(rows, start=1):
        zeile = []
        for _titel, key in _CSV_SPALTEN:
            zeile.append(str(i) if key is None else _csv_value(lead, key))
        w.writerow(zeile)
    return buf.getvalue()
