"""
db_websites.py — Persistenter Speicher für Webseiten-Bau-Jobs.

Jeder vom website_builder gestartete Bau-Job wird hier gespiegelt, damit der
Fortschritt einen Neustart überlebt und das Dashboard alle gebauten Seiten
(inkl. nachträglich hinzugefügter Bilder) auflisten kann.

Folgt dem Muster von db_evaluated.py: sqlite3 + threading.Lock, WAL-Journal,
busy_timeout, row_factory = sqlite3.Row, CREATE TABLE IF NOT EXISTS.
"""
import json
import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "websites.db"
_lock   = threading.Lock()

# Spalten, die update() schreiben darf (Whitelist — schützt vor Tippfehlern/Injection).
# 'live' = 1 NUR wenn die Seite verifiziert erreichbar ist (echter Deploy-Status).
_UPDATE_SPALTEN = {
    "status", "progress", "step", "folder", "repo_url", "live_url", "error", "log", "live",
    "kontakt_email",
}


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")   # unter Last warten statt sofort 'locked'
    return c


def _parse_liste(roh) -> list:
    """JSON-Text → Python-Liste. Bei ungültigem JSON oder Nicht-Liste: leere Liste."""
    if not roh:
        return []
    try:
        val = json.loads(roh)
        return val if isinstance(val, list) else []
    except Exception:
        return []


def _row_to_dict(row: sqlite3.Row) -> dict:
    """sqlite3.Row → dict mit geparsten images/log-Listen."""
    d = dict(row)
    d["images"] = _parse_liste(d.get("images"))
    d["log"]    = _parse_liste(d.get("log"))
    return d


def init_db() -> None:
    with _lock, _conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS websites (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id    TEXT UNIQUE,
            lead_id   INTEGER,
            name      TEXT,
            stadt     TEXT,
            branche   TEXT,
            status    TEXT,
            progress  INTEGER DEFAULT 0,
            step      TEXT,
            folder    TEXT,
            repo_url  TEXT,
            live_url  TEXT,
            error     TEXT,
            images        TEXT,
            log           TEXT,
            live          INTEGER DEFAULT 0,
            kontakt_email TEXT,
            created       REAL,
            updated       REAL
        )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_websites_created ON websites(created DESC)")
        # Migration für bestehende DBs: neue Spalten additiv ergänzen.
        cols = {r[1] for r in c.execute("PRAGMA table_info(websites)").fetchall()}
        if "live" not in cols:
            c.execute("ALTER TABLE websites ADD COLUMN live INTEGER DEFAULT 0")
            # Bestandszeilen mit Live-URL galten unter der alten Logik als 'live'.
            c.execute("UPDATE websites SET live=1 WHERE live_url IS NOT NULL AND live_url != ''")
        if "kontakt_email" not in cols:
            c.execute("ALTER TABLE websites ADD COLUMN kontakt_email TEXT")
        c.commit()


def create(job_id: str, name: str, stadt: str = "", branche: str = "",
           lead_id: "int | None" = None, kontakt_email: str = "") -> int:
    """Legt eine neue Zeile für einen Bau-Job an und gibt deren id zurück.

    Idempotent: existiert job_id bereits, wird nur 'updated' (und ggf. die
    Kontakt-E-Mail) gesetzt und die vorhandene id zurückgegeben."""
    now = time.time()
    with _lock, _conn() as c:
        vorhanden = c.execute(
            "SELECT id FROM websites WHERE job_id=?", (job_id,)
        ).fetchone()
        if vorhanden:
            if kontakt_email:
                c.execute("UPDATE websites SET updated=?, kontakt_email=? WHERE job_id=?",
                          (now, kontakt_email, job_id))
            else:
                c.execute("UPDATE websites SET updated=? WHERE job_id=?", (now, job_id))
            c.commit()
            return int(vorhanden["id"])
        cur = c.execute(
            "INSERT INTO websites "
            "(job_id, lead_id, name, stadt, branche, status, progress, step, "
            " folder, repo_url, live_url, error, images, log, kontakt_email, created, updated) "
            "VALUES (?, ?, ?, ?, ?, 'queued', 0, '', '', '', '', '', '[]', '[]', ?, ?, ?)",
            (job_id, lead_id, name, stadt, branche, kontakt_email, now, now),
        )
        c.commit()
        return int(cur.lastrowid)


def update(job_id: str, **fields) -> None:
    """Aktualisiert erlaubte Spalten einer Job-Zeile. 'log' darf als Python-Liste
    übergeben werden (wird als JSON serialisiert). 'updated' wird immer gesetzt."""
    sets:   list = []
    params: list = []
    for spalte, wert in fields.items():
        if spalte not in _UPDATE_SPALTEN:
            continue
        if spalte == "log":
            wert = json.dumps(wert if isinstance(wert, list) else [], ensure_ascii=False)
        sets.append(f"{spalte}=?")
        params.append(wert)
    sets.append("updated=?")
    params.append(time.time())
    params.append(job_id)
    with _lock, _conn() as c:
        c.execute(f"UPDATE websites SET {', '.join(sets)} WHERE job_id=?", params)
        c.commit()


def get_all() -> list[dict]:
    """Alle Seiten, neueste zuerst. images/log als geparste Listen."""
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM websites ORDER BY created DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get(wid: int) -> "dict | None":
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM websites WHERE id=?", (wid,)).fetchone()
    return _row_to_dict(row) if row else None


def get_by_job(job_id: str) -> "dict | None":
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM websites WHERE job_id=?", (job_id,)).fetchone()
    return _row_to_dict(row) if row else None


def get_by_folder(folder: str) -> "dict | None":
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM websites WHERE folder=? ORDER BY created DESC LIMIT 1",
                        (folder,)).fetchone()
    return _row_to_dict(row) if row else None


def delete(wid: int) -> bool:
    """Entfernt eine Webseiten-Zeile. Gibt True, wenn etwas gelöscht wurde."""
    with _lock, _conn() as c:
        cur = c.execute("DELETE FROM websites WHERE id=?", (wid,))
        c.commit()
        return cur.rowcount > 0


def add_image(wid: int, filename: str) -> "dict | None":
    """Hängt einen Dateinamen an die images-Liste an (dedupliziert) und gibt die
    aktualisierte Zeile zurück."""
    with _lock, _conn() as c:
        row = c.execute("SELECT images FROM websites WHERE id=?", (wid,)).fetchone()
        if not row:
            return None
        bilder = _parse_liste(row["images"])
        if filename not in bilder:
            bilder.append(filename)
            c.execute(
                "UPDATE websites SET images=?, updated=? WHERE id=?",
                (json.dumps(bilder, ensure_ascii=False), time.time(), wid),
            )
            c.commit()
    return get(wid)
