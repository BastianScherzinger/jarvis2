"""
LeadForge-DB — eigene, komplett isolierte SQLite-Datenbank für Datenpakete.

Bewusst getrennt von leads_raw.db/leads_evaluated.db (Website-Verkaufs-Pipeline):
gleiche Konventionen (WAL, threading.Lock, additive migrate()), aber eigener
Verkaufszweck (Firmendaten-Bundles statt Website-Kaltakquise). Übernimmt beim
Aufbau qualifizierte Zeilen aus evaluated_leads, verändert diese Tabelle aber nie.
"""
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "lead_packages.db"
_lock = threading.Lock()

MIN_KONTAKTWEGE = 2          # Entscheidung A: "strenger, mind. 2 Kontaktwege"
FRISCHE_TAGE = 90            # Entscheidung: Daten max. 90 Tage alt gelten als verkaufbar


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    return c


def init_db() -> None:
    with _lock, _conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS stock_leads (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_key            TEXT UNIQUE,
            source_eval_id      INTEGER,
            name                TEXT NOT NULL,
            adresse             TEXT,
            stadt               TEXT,
            region              TEXT,
            land                TEXT DEFAULT 'DE',
            branche             TEXT,
            telefon             TEXT,
            email_adresse       TEXT,
            website_url         TEXT,
            has_website         INTEGER DEFAULT 0,
            kontaktwege_anzahl  INTEGER DEFAULT 0,
            bewertung           REAL DEFAULT 0,
            anz_bewertungen     INTEGER DEFAULT 0,
            quality_score       INTEGER DEFAULT 0,
            potential_label     TEXT,
            cross_sell_ohne_web INTEGER DEFAULT 0,
            quelle              TEXT,
            last_checked_at     TEXT,
            created_at          TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS packages (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            branche             TEXT,
            region              TEXT,
            land                TEXT,
            bundle_size         INTEGER,
            preis_euro          INTEGER,
            beschreibung        TEXT,
            verfuegbare_menge   INTEGER DEFAULT 0,
            created_at          TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            kaeufer         TEXT,
            branche         TEXT,
            region          TEXT,
            land            TEXT,
            bundle_size     INTEGER,
            format          TEXT DEFAULT 'csv',
            watermark_id    TEXT UNIQUE,
            preis_euro      INTEGER,
            status          TEXT DEFAULT 'offen',
            erstellt_am     TEXT,
            geliefert_am    TEXT,
            datei_pfad      TEXT
        )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_stock_branche ON stock_leads(branche, region, land)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_stock_quality ON stock_leads(quality_score DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
        c.commit()


def kontaktwege(telefon: str, email: str, website: str) -> int:
    return sum(1 for v in (telefon, email, website) if (v or "").strip())


def upsert_stock_lead(row: dict) -> int | None:
    """INSERT OR REPLACE über lead_key. Erzwingt die Mindestqualität
    (>= MIN_KONTAKTWEGE Kontaktwege) — alles darunter wird verworfen statt gespeichert."""
    n_kontakt = kontaktwege(row.get("telefon", ""), row.get("email_adresse", ""), row.get("website_url", ""))
    if n_kontakt < MIN_KONTAKTWEGE:
        return None
    row = dict(row)
    row["kontaktwege_anzahl"] = n_kontakt
    row.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
    row.setdefault("last_checked_at", row["created_at"])

    cols = [
        "lead_key", "source_eval_id", "name", "adresse", "stadt", "region", "land", "branche",
        "telefon", "email_adresse", "website_url", "has_website", "kontaktwege_anzahl",
        "bewertung", "anz_bewertungen", "quality_score", "potential_label",
        "cross_sell_ohne_web", "quelle", "last_checked_at", "created_at",
    ]
    data = {k: row.get(k) for k in cols}
    placeholders = ", ".join("?" for _ in cols)
    with _lock, _conn() as c:
        cur = c.execute(
            f"INSERT OR REPLACE INTO stock_leads ({', '.join(cols)}) VALUES ({placeholders})",
            [data[k] for k in cols],
        )
        c.commit()
        return cur.lastrowid


def count_stock(branche: str | None = None, land: str | None = None) -> int:
    where, params = [], []
    if branche:
        where.append("branche=?"); params.append(branche)
    if land:
        where.append("land=?"); params.append(land)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with _lock, _conn() as c:
        return c.execute(f"SELECT COUNT(*) FROM stock_leads {clause}", params).fetchone()[0]


def stock_stats() -> dict:
    with _lock, _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM stock_leads").fetchone()[0]
        by_land = c.execute(
            "SELECT land, COUNT(*) AS n FROM stock_leads GROUP BY land ORDER BY n DESC"
        ).fetchall()
        by_branche = c.execute(
            "SELECT branche, COUNT(*) AS n FROM stock_leads GROUP BY branche ORDER BY n DESC LIMIT 20"
        ).fetchall()
    return {
        "total": total,
        "nach_land": {r["land"]: r["n"] for r in by_land},
        "top_branchen": {r["branche"]: r["n"] for r in by_branche if r["branche"]},
    }


def get_all_stock(limit: int = 100000, land: str | None = None, branche: str | None = None) -> list[dict]:
    where, params = [], []
    if land:
        where.append("land=?"); params.append(land)
    if branche:
        where.append("branche=?"); params.append(branche)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    with _lock, _conn() as c:
        rows = c.execute(
            f"SELECT * FROM stock_leads {clause} ORDER BY id LIMIT ?", params
        ).fetchall()
    return [dict(r) for r in rows]


def update_scoring(stock_id: int, quality_score: int, potential_label: str | None = None) -> None:
    with _lock, _conn() as c:
        if potential_label is not None:
            c.execute(
                "UPDATE stock_leads SET quality_score=?, potential_label=? WHERE id=?",
                (int(quality_score), potential_label, stock_id),
            )
        else:
            c.execute(
                "UPDATE stock_leads SET quality_score=? WHERE id=?",
                (int(quality_score), stock_id),
            )
        c.commit()


def delete_stock(ids: list[int]) -> int:
    """Löscht Zeilen (z.B. schwächere Fuzzy-Dubletten). Gibt Anzahl gelöschter Zeilen zurück."""
    if not ids:
        return 0
    with _lock, _conn() as c:
        placeholders = ", ".join("?" for _ in ids)
        cur = c.execute(f"DELETE FROM stock_leads WHERE id IN ({placeholders})", ids)
        c.commit()
        return cur.rowcount


def create_order(order: dict) -> int:
    row = dict(order)
    row.setdefault("erstellt_am", datetime.now().isoformat(timespec="seconds"))
    row.setdefault("status", "offen")
    cols = ["kaeufer", "branche", "region", "land", "bundle_size", "format",
            "watermark_id", "preis_euro", "status", "erstellt_am"]
    data = {k: row.get(k) for k in cols}
    with _lock, _conn() as c:
        cur = c.execute(
            f"INSERT INTO orders ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [data[k] for k in cols],
        )
        c.commit()
        return cur.lastrowid


def get_orders(limit: int = 200) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_order(order_id: int) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    return dict(row) if row else None


def mark_order_delivered(order_id: int) -> None:
    with _lock, _conn() as c:
        c.execute(
            "UPDATE orders SET status='geliefert', "
            "geliefert_am=COALESCE(geliefert_am, ?) WHERE id=?",
            (datetime.now().isoformat(timespec="seconds"), order_id),
        )
        c.commit()


def migrate_from_evaluated(limit: int = 100000) -> dict:
    """Einmalige/wiederholbare Übernahme qualifizierter DE-Bestandsleads aus
    evaluated_leads in stock_leads. Liest evaluated_leads nur lesend — verändert
    dort nichts. Nur Zeilen mit >= MIN_KONTAKTWEGE Kontaktwegen werden übernommen."""
    import db_evaluated

    rows = db_evaluated.get_all(limit=limit, sort="score")
    uebernommen = 0
    verworfen = 0
    for r in rows:
        stock_row = {
            "lead_key": r.get("lead_key"),
            "source_eval_id": r.get("id"),
            "name": r.get("name"),
            "adresse": r.get("adresse"),
            "stadt": r.get("stadt"),
            "region": r.get("bundesland"),
            "land": "DE",
            "branche": r.get("branche"),
            "telefon": r.get("telefon"),
            "email_adresse": r.get("email_adresse"),
            "website_url": r.get("discovered_website") or r.get("website_url"),
            "has_website": r.get("has_website"),
            "bewertung": 0,
            "anz_bewertungen": 0,
            "quality_score": 0,          # wird in Phase 4 (quality_score.py) befüllt
            "potential_label": None,     # wird in Phase 4 (potential_score.py) befüllt
            "cross_sell_ohne_web": 0 if r.get("has_website") else 1,
            "quelle": "evaluated_import",
        }
        if upsert_stock_lead(stock_row) is not None:
            uebernommen += 1
        else:
            verworfen += 1
    return {"uebernommen": uebernommen, "verworfen_mindestqualitaet": verworfen}
