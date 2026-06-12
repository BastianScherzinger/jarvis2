"""
DB1 — Rohdaten direkt vom Scraper. Kein KI-Call, nur was sofort verfügbar ist.
Läuft PARALLEL zur bestehenden leads.db (db.py) — Scraper schreiben in beide.
"""
import sqlite3
import threading
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "data" / "leads_raw.db"
_lock   = threading.Lock()

# Amtliche KFZ-Unterscheidungszeichen je Bundesland (2-Buchstaben-Kürzel).
_BL_KUERZEL = {
    "baden-württemberg":      "BW",
    "baden-wuerttemberg":     "BW",
    "bayern":                 "BY",
    "berlin":                 "BE",
    "brandenburg":            "BB",
    "bremen":                 "HB",
    "hamburg":                "HH",
    "hessen":                 "HE",
    "mecklenburg-vorpommern": "MV",
    "niedersachsen":          "NI",
    "nordrhein-westfalen":    "NW",
    "nrw":                    "NW",
    "rheinland-pfalz":        "RP",
    "saarland":               "SL",
    "sachsen":                "SN",
    "sachsen-anhalt":         "ST",
    "schleswig-holstein":     "SH",
    "thüringen":              "TH",
    "thueringen":             "TH",
}


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db() -> None:
    with _lock, _conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS raw_leads (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            schluessel      TEXT UNIQUE,
            name            TEXT NOT NULL,
            adresse         TEXT,
            stadt           TEXT,
            bundesland      TEXT,
            branche         TEXT,
            telefon         TEXT,
            website_url     TEXT,
            has_website     INTEGER DEFAULT 0,
            maps_url        TEXT,
            bilder_maps     INTEGER DEFAULT 0,
            foto_url        TEXT,
            bewertung       REAL DEFAULT 0,
            anz_bewertungen INTEGER DEFAULT 0,
            finder          TEXT,
            eval_status     TEXT DEFAULT 'pending',
            gefunden_am     TEXT
        )
        """)
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_eval "
            "ON raw_leads(eval_status, has_website, bewertung DESC)"
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_name_stadt_raw ON raw_leads(name, stadt)")
        c.commit()
    _migrate()


def _migrate() -> None:
    """Additive Spalten für Bestands-DBs (foto_url kam später dazu)."""
    with _lock, _conn() as c:
        have = {r[1] for r in c.execute("PRAGMA table_info(raw_leads)")}
        if "foto_url" not in have:
            c.execute("ALTER TABLE raw_leads ADD COLUMN foto_url TEXT")
        c.commit()


def _bl_kuerzel(bundesland: str) -> str:
    key = (bundesland or "").strip().lower()
    if key in _BL_KUERZEL:
        return _BL_KUERZEL[key]
    # Fallback: erste 2 Buchstaben uppercase
    letters = [ch for ch in (bundesland or "") if ch.isalpha()]
    return ("".join(letters[:2]) or "XX").upper()


def exists_raw(name: str, stadt: str) -> bool:
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT 1 FROM raw_leads WHERE name=? AND stadt=? LIMIT 1", (name, stadt)
        ).fetchone()
    return row is not None


# Spalten die raw_leads kennt — fremde Keys aus dem Scraper-dict werden gefiltert.
_RAW_COLUMNS = {
    "name", "adresse", "stadt", "bundesland", "branche", "telefon",
    "website_url", "has_website", "maps_url", "bilder_maps", "foto_url",
    "bewertung", "anz_bewertungen", "finder", "gefunden_am",
}


def insert_raw(lead: dict) -> int | None:
    """
    Fügt einen Roh-Lead ein. Dedup über UNIQUE(name, stadt) via vorheriger Prüfung
    plus INSERT OR IGNORE. Generiert schluessel NACH dem Insert.
    Gibt die ID zurück oder None bei Duplikat.
    """
    name  = (lead.get("name") or "").strip()
    stadt = (lead.get("stadt") or "").strip()
    if not name:
        return None

    # bilder_maps aus 'bilder' übernehmen wenn nicht explizit gesetzt
    row = {k: v for k, v in lead.items() if k in _RAW_COLUMNS}
    if "bilder_maps" not in row:
        row["bilder_maps"] = int(lead.get("bilder", 0) or 0)
    row.setdefault("gefunden_am", datetime.now().isoformat(timespec="seconds"))

    with _lock, _conn() as c:
        dup = c.execute(
            "SELECT 1 FROM raw_leads WHERE name=? AND stadt=? LIMIT 1", (name, stadt)
        ).fetchone()
        if dup:
            return None

        cols = ", ".join(row.keys())
        ph   = ", ".join("?" for _ in row)
        cur  = c.execute(
            f"INSERT OR IGNORE INTO raw_leads ({cols}) VALUES ({ph})",
            list(row.values()),
        )
        if not cur.lastrowid or cur.rowcount == 0:
            c.commit()
            return None
        raw_id     = cur.lastrowid
        schluessel = f"{_bl_kuerzel(row.get('bundesland', ''))}-{raw_id:06d}"
        c.execute("UPDATE raw_leads SET schluessel=? WHERE id=?", (schluessel, raw_id))
        c.commit()
        return raw_id


def claim_next_pending() -> dict | None:
    """
    Holt ATOMAR den nächsten zu bewertenden Lead und markiert ihn sofort als
    'running' — SELECT + UPDATE im selben Lock-Block (keine Doppel-Arbeit bei
    mehreren Evaluator-Threads). Leads OHNE Website zuerst (wertvollste Kunden),
    dann höchste Bewertung.
    """
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT * FROM raw_leads WHERE eval_status='pending' "
            "ORDER BY has_website ASC, bewertung DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        lead = dict(row)
        c.execute(
            "UPDATE raw_leads SET eval_status='running' WHERE id=?", (lead["id"],)
        )
        c.commit()
        lead["eval_status"] = "running"
        return lead


def update_eval_status(raw_id: int, status: str) -> None:
    with _lock, _conn() as c:
        c.execute("UPDATE raw_leads SET eval_status=? WHERE id=?", (status, raw_id))
        c.commit()


def reset_stale() -> None:
    """Setzt hängengebliebene 'running'-Leads (Crash/Neustart) auf 'pending'."""
    with _lock, _conn() as c:
        c.execute("UPDATE raw_leads SET eval_status='pending' WHERE eval_status='running'")
        c.commit()


def reset_all_for_reeval() -> int:
    """Setzt ALLE Leads (auch 'done'/'failed') auf 'pending' für eine komplette
    Neu-Bewertung. Gibt die Anzahl betroffener Zeilen zurück."""
    with _lock, _conn() as c:
        cur = c.execute("UPDATE raw_leads SET eval_status='pending'")
        c.commit()
        return cur.rowcount


def clear_all() -> int:
    """Leert die komplette raw_leads-Tabelle. Gibt Anzahl gelöschter Zeilen zurück."""
    with _lock, _conn() as c:
        n = c.execute("SELECT COUNT(*) FROM raw_leads").fetchone()[0]
        c.execute("DELETE FROM raw_leads")
        c.commit()
    return n


def get_pending_count() -> int:
    with _lock, _conn() as c:
        return c.execute(
            "SELECT COUNT(*) FROM raw_leads WHERE eval_status='pending'"
        ).fetchone()[0]


def get_raw_stats() -> dict:
    with _lock, _conn() as c:
        total      = c.execute("SELECT COUNT(*) FROM raw_leads").fetchone()[0]
        pending    = c.execute("SELECT COUNT(*) FROM raw_leads WHERE eval_status='pending'").fetchone()[0]
        done       = c.execute("SELECT COUNT(*) FROM raw_leads WHERE eval_status='done'").fetchone()[0]
        failed     = c.execute("SELECT COUNT(*) FROM raw_leads WHERE eval_status='failed'").fetchone()[0]
        has_web    = c.execute("SELECT COUNT(*) FROM raw_leads WHERE has_website=1").fetchone()[0]
        no_web     = c.execute("SELECT COUNT(*) FROM raw_leads WHERE has_website=0").fetchone()[0]
    return {
        "total":       total,
        "pending":     pending,
        "done":        done,
        "failed":      failed,
        "has_website": has_web,
        "no_website":  no_web,
    }
