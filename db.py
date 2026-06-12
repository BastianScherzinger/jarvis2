"""
LeadHunter — SQLite Datenbank-Layer.
Speichert gefundene Unternehmen dedupliziert, schnell, lokal.
"""
import json
import sqlite3
import threading
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "data" / "leads.db"
_lock   = threading.Lock()

# Neue Spalten (Phase 1 — KI-Verifikation). name → SQL-Definition.
_VERIFY_COLUMNS = {
    "verified_score":   "INTEGER DEFAULT -1",
    "verify_status":    "TEXT DEFAULT 'pending'",
    "pitch_hook":       "TEXT",
    "verify_begruendung": "TEXT",
    "website_issues":   "TEXT",
    "social_media":     "TEXT",
    "email_draft":      "TEXT",
    "mockup_url":       "TEXT",
    "end_score":        "INTEGER DEFAULT -1",
    "verified_am":      "TEXT",
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
    migrate()


def migrate() -> None:
    """Fügt fehlende Verifikations-Spalten + Index hinzu (idempotent)."""
    with _lock, _conn() as c:
        have = {r["name"] for r in c.execute("PRAGMA table_info(leads)").fetchall()}
        for col, ddl in _VERIFY_COLUMNS.items():
            if col not in have:
                c.execute(f"ALTER TABLE leads ADD COLUMN {col} {ddl}")
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_verify "
            "ON leads(verify_status, lead_typ, score DESC)"
        )
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
        verified = c.execute("SELECT COUNT(*) FROM leads WHERE verify_status='verified'").fetchone()[0]
        pending  = c.execute("SELECT COUNT(*) FROM leads WHERE verify_status='pending'").fetchone()[0]
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
        "verified": verified,
        "pending":  pending,
        "bundeslaender": {r["bundesland"]: r["n"] for r in bl_rows if r["bundesland"]},
        "finders": {r["finder"]: r["n"] for r in finders},
    }


def get_all(limit: int = 500, offset: int = 0) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM leads ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
    return [dict(r) for r in rows]


def clear_all() -> int:
    """Leert die komplette leads-Tabelle. Gibt Anzahl gelöschter Zeilen zurück."""
    with _lock, _conn() as c:
        n = c.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        c.execute("DELETE FROM leads")
        c.commit()
    return n


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


# ── Verifikations-Pipeline ──────────────────────────────────────────────────

def _table_columns() -> set:
    with _lock, _conn() as c:
        return {r["name"] for r in c.execute("PRAGMA table_info(leads)").fetchall()}


def claim_next_pending() -> dict | None:
    """
    Holt ATOMAR den nächsten zu verifizierenden Lead und markiert ihn sofort
    als 'running' — SELECT + UPDATE im selben Lock-Block (keine Doppel-Arbeit
    bei mehreren Verifier-Threads). Hot zuerst, dann höchster Score.
    """
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT * FROM leads WHERE verify_status='pending' "
            "ORDER BY (lead_typ='Hot') DESC, score DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        lead = dict(row)
        c.execute(
            "UPDATE leads SET verify_status='running' WHERE id=?", (lead["id"],)
        )
        c.commit()
        lead["verify_status"] = "running"
        return lead


def update_verification(lead_id: int, result: dict) -> None:
    """Schreibt das Verifikations-Ergebnis zurück."""
    status = result.get("verify_status", "verified")
    with _lock, _conn() as c:
        c.execute(
            "UPDATE leads SET "
            "verified_score=?, verify_status=?, pitch_hook=?, verify_begruendung=?, "
            "website_issues=?, social_media=?, end_score=?, lead_typ=?, verified_am=? "
            "WHERE id=?",
            (
                int(result.get("verified_score", -1)),
                status,
                result.get("pitch_hook", "") or "",
                result.get("verify_begruendung", "") or "",
                json.dumps(result.get("website_issues", []), ensure_ascii=False),
                json.dumps(result.get("social_media", {}), ensure_ascii=False),
                int(result.get("end_score", -1)),
                result.get("lead_typ", "Cold"),
                datetime.now().isoformat(timespec="seconds"),
                lead_id,
            ),
        )
        c.commit()


def reset_stale_running() -> None:
    """Setzt hängengebliebene 'running'-Leads (Crash/Neustart) auf 'pending'."""
    with _lock, _conn() as c:
        c.execute("UPDATE leads SET verify_status='pending' WHERE verify_status='running'")
        c.commit()


def get_top_opportunities(limit: int = 10) -> list[dict]:
    """
    Beste verifizierte Chancen. Falls weniger als `limit` verifiziert sind,
    wird mit den besten unverifizierten aufgefüllt — Panel bleibt nie leer.
    """
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM leads WHERE verify_status='verified' "
            "ORDER BY end_score DESC, score DESC LIMIT ?", (limit,)
        ).fetchall()
        out = [dict(r) for r in rows]
        if len(out) < limit:
            seen = {r["id"] for r in out}
            fill = c.execute(
                "SELECT * FROM leads WHERE verify_status!='verified' "
                "ORDER BY score DESC LIMIT ?", (limit,)
            ).fetchall()
            for r in fill:
                if r["id"] not in seen:
                    out.append(dict(r))
                if len(out) >= limit:
                    break
    return out[:limit]


def update_lead_status(lead_id: int, status: str) -> None:
    with _lock, _conn() as c:
        c.execute("UPDATE leads SET status=? WHERE id=?", (status, lead_id))
        c.commit()


def get_lead(lead_id: int) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    return dict(row) if row else None


def get_competition(stadt: str, branche: str) -> dict:
    """
    Konkurrenz-Analyse: wie viele Betriebe der gleichen Branche/Stadt
    haben (k)eine Website. Verkaufsargument für Outreach.
    """
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS gesamt, "
            "SUM(CASE WHEN has_website=0 THEN 1 ELSE 0 END) AS ohne "
            "FROM leads WHERE stadt=? AND branche=?",
            (stadt, branche),
        ).fetchone()
    gesamt = int(row["gesamt"] or 0)
    ohne   = int(row["ohne"] or 0)
    prozent = round(ohne / gesamt * 100) if gesamt else 0
    return {"gesamt": gesamt, "ohne_website": ohne, "prozent_ohne": prozent}


def set_lead_field(lead_id: int, field: str, value) -> None:
    """Setzt ein einzelnes Feld — Spaltenname gegen Whitelist (SQL-Injection-Schutz)."""
    if field not in _table_columns():
        raise ValueError(f"Unbekannte Spalte: {field}")
    with _lock, _conn() as c:
        c.execute(f"UPDATE leads SET {field}=? WHERE id=?", (value, lead_id))
        c.commit()
