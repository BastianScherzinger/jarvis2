"""
LeadHunter — SQLite Datenbank-Layer.
Speichert gefundene Unternehmen dedupliziert, schnell, lokal.
"""
import sqlite3
import threading
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "data" / "leads.db"
_lock   = threading.Lock()


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _lock, _conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT    NOT NULL,
            adresse         TEXT,
            stadt           TEXT,
            bundesland      TEXT,
            branche         TEXT,
            telefon         TEXT,
            website_url     TEXT,
            has_website     INTEGER DEFAULT 0,
            website_alter   INTEGER DEFAULT -1,
            bewertung       REAL    DEFAULT 0,
            anz_bewertungen INTEGER DEFAULT 0,
            bilder          INTEGER DEFAULT 0,
            score           INTEGER DEFAULT 0,
            lead_typ        TEXT    DEFAULT 'Cold',
            finder          TEXT,
            maps_url        TEXT,
            status          TEXT    DEFAULT 'neu',
            gefunden_am     TEXT
        )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_name_stadt ON leads(name, stadt)")
        c.commit()


def exists(name: str, stadt: str) -> bool:
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT 1 FROM leads WHERE name=? AND stadt=? LIMIT 1", (name, stadt)
        ).fetchone()
    return row is not None


def insert(lead: dict) -> int | None:
    """Fügt einen Lead ein — gibt id zurück, None wenn Duplikat."""
    if exists(lead.get("name", ""), lead.get("stadt", "")):
        return None
    lead.setdefault("gefunden_am", datetime.now().isoformat(timespec="seconds"))
    cols = ", ".join(lead.keys())
    ph   = ", ".join("?" for _ in lead)
    with _lock, _conn() as c:
        cur = c.execute(f"INSERT INTO leads ({cols}) VALUES ({ph})", list(lead.values()))
        c.commit()
        return cur.lastrowid


def get_stats() -> dict:
    with _lock, _conn() as c:
        total   = c.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        hot     = c.execute("SELECT COUNT(*) FROM leads WHERE lead_typ='Hot'").fetchone()[0]
        warm    = c.execute("SELECT COUNT(*) FROM leads WHERE lead_typ='Warm'").fetchone()[0]
        no_web  = c.execute("SELECT COUNT(*) FROM leads WHERE has_website=0").fetchone()[0]
        finders = c.execute(
            "SELECT finder, COUNT(*) as n FROM leads GROUP BY finder ORDER BY n DESC"
        ).fetchall()
        bl_rows = c.execute(
            "SELECT bundesland, COUNT(*) as n FROM leads "
            "GROUP BY bundesland ORDER BY n DESC LIMIT 20"
        ).fetchall()
    return {
        "total":   total,
        "hot":     hot,
        "warm":    warm,
        "cold":    total - hot - warm,
        "no_web":  no_web,
        "bundeslaender": {r["bundesland"]: r["n"] for r in bl_rows if r["bundesland"]},
        "finders": {r["finder"]: r["n"] for r in finders},
    }


def get_all(limit: int = 500, offset: int = 0) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM leads ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
    return [dict(r) for r in rows]


def export_csv() -> str:
    import csv, io
    rows = get_all(limit=99999)
    if not rows:
        return ""
    buf = io.StringIO()
    w   = csv.DictWriter(buf, fieldnames=rows[0].keys())
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()
