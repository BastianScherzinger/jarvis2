"""
DB2 — KI-angereicherte Lead-Bewertungen. Wird vom Evaluator-Team befüllt.
"""
import sqlite3
import threading
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "leads_evaluated.db"
_lock   = threading.Lock()

# Alle bekannten Spalten — fremde Keys werden beim Insert gefiltert.
_COLUMNS = [
    "raw_id", "schluessel", "name", "adresse", "stadt", "bundesland", "branche",
    "telefon", "email_vorhanden", "email_adresse", "telefon_verifiziert",
    "has_website", "website_url", "website_veraltet", "website_alter_jahre",
    "website_probleme", "fotos_in_maps", "social_media", "hat_nur_social",
    "beschreibung", "ist_privat_zahler", "firmengroesse", "potenzial_euro",
    "potenzial_begruendung", "pitch_hook", "score", "lead_typ", "email_entwurf",
    "status", "bewertet_am",
]


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
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
            website_veraltet      INTEGER DEFAULT 0,
            website_alter_jahre   INTEGER DEFAULT -1,
            website_probleme      TEXT,
            fotos_in_maps         INTEGER DEFAULT 0,
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
            status                TEXT DEFAULT 'neu',
            bewertet_am           TEXT
        )
        """)
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_score "
            "ON evaluated_leads(score DESC, lead_typ, ist_privat_zahler)"
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_status ON evaluated_leads(status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_branche ON evaluated_leads(branche, bundesland)")
        c.commit()


def insert_evaluated(data: dict) -> int | None:
    """INSERT OR REPLACE — raw_id ist UNIQUE, Re-Evaluierung überschreibt."""
    row = {k: data[k] for k in _COLUMNS if k in data}
    if not row.get("raw_id"):
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


def get_all(limit: int = 500, offset: int = 0, branche: str | None = None,
            bundesland: str | None = None, lead_typ: str | None = None) -> list[dict]:
    where  = []
    params: list = []
    if branche:
        where.append("branche=?");    params.append(branche)
    if bundesland:
        where.append("bundesland=?"); params.append(bundesland)
    if lead_typ:
        where.append("lead_typ=?");   params.append(lead_typ)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    params += [limit, offset]
    with _lock, _conn() as c:
        rows = c.execute(
            f"SELECT * FROM evaluated_leads {clause} "
            f"ORDER BY score DESC LIMIT ? OFFSET ?",
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
        "top_branchen":     {r["branche"]: r["n"] for r in br_rows if r["branche"]},
        "top_bundeslaender": {r["bundesland"]: r["n"] for r in bl_rows if r["bundesland"]},
    }


def update_status(eval_id: int, status: str) -> None:
    with _lock, _conn() as c:
        c.execute("UPDATE evaluated_leads SET status=? WHERE id=?", (status, eval_id))
        c.commit()


def get_by_raw_id(raw_id: int) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT * FROM evaluated_leads WHERE raw_id=?", (raw_id,)
        ).fetchone()
    return dict(row) if row else None


def get_for_graph(limit: int = 2000, offset: int = 0) -> list[dict]:
    """Leichtgewichtige Knoten für die Graph-Visualisierung.

    offset=0  → bestes-zuerst (score DESC) für den initialen Vollabruf.
    offset>0  → inkrementell (id ASC): nur Knoten ab dem Offset, damit neu
                bewertete Leads für den 3s-Auto-Refresh zuverlässig nachrücken.
    """
    cols = ("id, name, branche, stadt, bundesland, score, "
            "potenzial_euro, lead_typ, has_website")
    with _lock, _conn() as c:
        if offset > 0:
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
