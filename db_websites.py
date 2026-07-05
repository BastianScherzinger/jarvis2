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
    "kontakt_email", "site_key", "ansprechpartner", "archived",
    "email_sent", "email_sent_ts", "replied",
}


def _site_key(name: str, stadt: str) -> str:
    """Cross-PC-Schlüssel je Webseite (= Lead-Key aus name|stadt)."""
    try:
        from leadkey import lead_key
        return lead_key(name or "", stadt or "")
    except Exception:
        import hashlib
        return hashlib.md5(f"{(name or '').lower()}|{(stadt or '').lower()}".encode()).hexdigest()


_thread_local = threading.local()


def _conn() -> sqlite3.Connection:
    """Wiederverwendete Connection PRO THREAD statt einer neuen Connection + 2x PRAGMA bei
    JEDEM einzelnen Aufruf. Der bestehende globale `_lock` serialisiert ohnehin jeden Zugriff —
    diese Änderung spart nur das ständige Neu-Verbinden, ändert nichts an der Nebenläufigkeit.
    Prüft den Pfad mit, falls DB_PATH zur Laufzeit geändert wird (z.B. in Tests)."""
    path   = str(DB_PATH)
    cached = getattr(_thread_local, "conn", None)
    if cached is not None and getattr(_thread_local, "path", None) == path:
        return cached
    if cached is not None:
        try:
            cached.close()
        except Exception:
            pass
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")   # unter Last warten statt sofort 'locked'
    _thread_local.conn = conn
    _thread_local.path = path
    return conn


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
            ansprechpartner TEXT,
            site_key      TEXT,
            archived      INTEGER DEFAULT 0,
            email_sent    INTEGER DEFAULT 0,
            email_sent_ts REAL    DEFAULT 0,
            replied       INTEGER DEFAULT 0,
            created       REAL,
            updated       REAL
        )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_websites_created ON websites(created DESC)")
        # Migration für bestehende DBs: neue Spalten additiv ergänzen.
        cols = {r[1] for r in c.execute("PRAGMA table_info(websites)").fetchall()}
        if "live" not in cols:
            c.execute("ALTER TABLE websites ADD COLUMN live INTEGER DEFAULT 0")
            c.execute("UPDATE websites SET live=1 WHERE live_url IS NOT NULL AND live_url != ''")
        if "kontakt_email" not in cols:
            c.execute("ALTER TABLE websites ADD COLUMN kontakt_email TEXT")
        if "ansprechpartner" not in cols:
            c.execute("ALTER TABLE websites ADD COLUMN ansprechpartner TEXT")
        if "site_key" not in cols:
            c.execute("ALTER TABLE websites ADD COLUMN site_key TEXT")
        if "archived" not in cols:
            c.execute("ALTER TABLE websites ADD COLUMN archived INTEGER DEFAULT 0")
        if "email_sent" not in cols:
            c.execute("ALTER TABLE websites ADD COLUMN email_sent INTEGER DEFAULT 0")
        if "email_sent_ts" not in cols:
            c.execute("ALTER TABLE websites ADD COLUMN email_sent_ts REAL DEFAULT 0")
        if "replied" not in cols:
            c.execute("ALTER TABLE websites ADD COLUMN replied INTEGER DEFAULT 0")
        c.execute("CREATE INDEX IF NOT EXISTS idx_websites_sitekey ON websites(site_key)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_websites_archived ON websites(archived)")
        for r in c.execute("SELECT id, name, stadt FROM websites WHERE site_key IS NULL OR site_key=''").fetchall():
            c.execute("UPDATE websites SET site_key=? WHERE id=?",
                      (_site_key(r["name"], r["stadt"]), r["id"]))
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
            " folder, repo_url, live_url, error, images, log, kontakt_email, site_key, created, updated) "
            "VALUES (?, ?, ?, ?, ?, 'queued', 0, '', '', '', '', '', '[]', '[]', ?, ?, ?, ?)",
            (job_id, lead_id, name, stadt, branche, kontakt_email,
             _site_key(name, stadt), now, now),
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


def get_all(include_archived: bool = False) -> list[dict]:
    """Aktive Seiten (archived=0), neueste zuerst. images/log als geparste Listen.
    include_archived=True gibt ALLE zurück (z.B. für Dedup-Prüfungen)."""
    with _lock, _conn() as c:
        if include_archived:
            rows = c.execute("SELECT * FROM websites ORDER BY created DESC").fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM websites WHERE archived=0 ORDER BY created DESC"
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_archived() -> list[dict]:
    """Nur archivierte Seiten, neueste zuerst."""
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM websites WHERE archived=1 ORDER BY created DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def archive_all() -> int:
    """Archiviert alle aktiven (nicht laufenden) Seiten. Gibt die Anzahl zurück.
    Seiten mit status='queued' oder 'running' werden nicht archiviert, da sie aktiv
    im Build-Prozess sind. Die leads bleiben als gebaut markiert (kein Doppelbau)."""
    with _lock, _conn() as c:
        cur = c.execute(
            "UPDATE websites SET archived=1, updated=? "
            "WHERE archived=0 AND status NOT IN ('queued','running')",
            (time.time(),)
        )
        c.commit()
        return cur.rowcount


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


def upsert_remote(fields: dict) -> None:
    """Schreibt eine aus der Cloud gezogene Webseite in die lokale DB (Dedup über
    site_key). Vorhandene lokale Zeile (z.B. der bauende PC) wird aktualisiert,
    ihr lokaler 'folder' bleibt erhalten."""
    sk = (fields.get("site_key") or "").strip()
    if not sk:
        return
    cols = ["name", "stadt", "branche", "repo_url", "live_url", "status", "step",
            "kontakt_email", "ansprechpartner"]
    images = json.dumps(fields.get("images") or [], ensure_ascii=False)
    live = int(fields.get("live") or 0)
    now = time.time()
    with _lock, _conn() as c:
        row = c.execute("SELECT id FROM websites WHERE site_key=?", (sk,)).fetchone()
        if row:
            sets = ", ".join(f"{k}=?" for k in cols) + ", live=?, images=?, updated=?"
            params = [fields.get(k) for k in cols] + [live, images, now, sk]
            c.execute(f"UPDATE websites SET {sets} WHERE site_key=?", params)
        else:
            jid = "remote-" + sk[:16]
            c.execute(
                "INSERT INTO websites "
                "(job_id, site_key, name, stadt, branche, status, progress, step, folder, "
                " repo_url, live_url, live, error, images, log, kontakt_email, created, updated) "
                "VALUES (?, ?, ?, ?, ?, ?, 100, ?, '', ?, ?, ?, '', ?, '[]', ?, ?, ?)",
                (jid, sk, fields.get("name"), fields.get("stadt"), fields.get("branche"),
                 fields.get("status") or "done", fields.get("step") or "",
                 fields.get("repo_url") or "", fields.get("live_url") or "", live,
                 images, fields.get("kontakt_email") or "", now, now))
        c.commit()


def set_contact(wid: int, email: str = "", ansprechpartner: str = "") -> "dict | None":
    """Setzt die gefundene Kontakt-E-Mail (und optional den Ansprechpartner) einer
    Webseiten-Zeile. Leere Werte überschreiben Vorhandenes NICHT. Gibt die Zeile zurück."""
    sets, params = [], []
    if (email or "").strip():
        sets.append("kontakt_email=?"); params.append(email.strip())
    if (ansprechpartner or "").strip():
        sets.append("ansprechpartner=?"); params.append(ansprechpartner.strip())
    if not sets:
        return get(wid)
    sets.append("updated=?"); params.append(time.time())
    params.append(wid)
    with _lock, _conn() as c:
        c.execute(f"UPDATE websites SET {', '.join(sets)} WHERE id=?", params)
        c.commit()
    return get(wid)


def mark_replied(name: str, stadt: str) -> bool:
    """Markiert die zur Lead-Adresse passende Webseite als 'vom Kunden beantwortet'
    (site_key = name+stadt, wie überall sonst im Projekt für Cross-PC-Dedup). Für
    inbox_reader.py: eine erkannte Kundenantwort schützt die Seite dauerhaft vor dem
    Alt-Demo-Teardown (auto_builder.teardown_stale_demos), egal wie alt sie ist.
    Gibt True zurück, wenn eine passende Zeile gefunden+markiert wurde."""
    sk = _site_key(name or "", stadt or "")
    row = get_by_site_key(sk)
    if not row or not row.get("job_id"):
        return False
    if not row.get("replied"):
        update(row["job_id"], replied=1)
    return True


def get_by_site_key(sk: str) -> "dict | None":
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM websites WHERE site_key=? ORDER BY created DESC LIMIT 1",
                        (sk,)).fetchone()
    return _row_to_dict(row) if row else None


def has_site_key(sk: str) -> bool:
    """Schlanker Existenz-Check (SELECT 1) für den Duplikat-Guard — vermeidet den
    Full-Table-Scan via get_all() bei JEDEM Lead. Best-effort: fehlt die Tabelle
    (frische Installation, init_db noch nicht gelaufen) → False statt Crash."""
    if not sk:
        return False
    try:
        with _lock, _conn() as c:
            row = c.execute("SELECT 1 FROM websites WHERE site_key=? LIMIT 1", (sk,)).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False


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
