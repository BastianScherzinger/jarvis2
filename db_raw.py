"""
DB1 — Rohdaten direkt vom Scraper. Kein KI-Call, nur was sofort verfügbar ist.
Läuft PARALLEL zur bestehenden leads.db (db.py) — Scraper schreiben in beide.
"""
import sqlite3
import threading
from pathlib import Path
from datetime import datetime

from leadkey import lead_key as _lead_key, phone_key as _phone_key

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


_thread_local = threading.local()


def _conn() -> sqlite3.Connection:
    """Wiederverwendete Connection PRO THREAD statt einer neuen Connection + 2x PRAGMA bei
    JEDEM einzelnen Aufruf (spürbar bei 32+ parallelen Evaluator-Threads mit vielen kleinen
    DB-Zugriffen). Der bestehende globale `_lock` serialisiert ohnehin jeden Zugriff — diese
    Änderung spart nur das ständige Neu-Verbinden, ändert nichts an der Nebenläufigkeit.
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
            foto_urls       TEXT,
            bewertung       REAL DEFAULT 0,
            anz_bewertungen INTEGER DEFAULT 0,
            finder          TEXT,
            eval_status     TEXT DEFAULT 'pending',
            claimed_at      TEXT,
            gefunden_am     TEXT,
            lead_key        TEXT,
            tel_key         TEXT
        )
        """)
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_eval "
            "ON raw_leads(eval_status, has_website, bewertung DESC)"
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_name_stadt_raw ON raw_leads(name, stadt)")
        # Der Dedup-Check in insert_raw() vergleicht case-insensitiv (LOWER(name)=LOWER(?) AND
        # LOWER(stadt)=LOWER(?)) — der Index oben auf den Rohspalten hilft SQLite dabei NICHT
        # (Funktionen auf Spalten verhindern normale Index-Nutzung). Dieser Expression-Index
        # auf genau denselben Ausdrücken macht den Dedup-Scan bei wachsender Tabelle wieder
        # schnell, ohne Migration/Datenänderung nötig zu machen.
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_name_stadt_norm_raw "
            "ON raw_leads(LOWER(name), LOWER(stadt))"
        )
        c.commit()
    _migrate()


def _migrate() -> None:
    """Additive Spalten für Bestands-DBs (foto_url/foto_urls kamen später dazu)."""
    with _lock, _conn() as c:
        have = {r[1] for r in c.execute("PRAGMA table_info(raw_leads)")}
        if "foto_url" not in have:
            c.execute("ALTER TABLE raw_leads ADD COLUMN foto_url TEXT")
        if "foto_urls" not in have:
            c.execute("ALTER TABLE raw_leads ADD COLUMN foto_urls TEXT")
        if "claimed_at" not in have:
            c.execute("ALTER TABLE raw_leads ADD COLUMN claimed_at TEXT")
        needs_backfill = "lead_key" not in have
        if needs_backfill:
            c.execute("ALTER TABLE raw_leads ADD COLUMN lead_key TEXT")
        # tel_key = normalisierte Telefonnummer (zusätzlicher Dedup-Anker gegen dieselbe Firma
        # mit unterschiedlicher Namens-Schreibweise, siehe insert_raw). Wie lead_key nachrüsten.
        needs_tel_backfill = "tel_key" not in have
        if needs_tel_backfill:
            c.execute("ALTER TABLE raw_leads ADD COLUMN tel_key TEXT")
        # Muss NACH der ALTER TABLE oben stehen (nicht in init_db()'s CREATE-INDEX-Block) —
        # bei einer Bestands-DB ohne lead_key-Spalte existiert die Spalte zum Zeitpunkt von
        # init_db() noch nicht, CREATE INDEX würde dort mit "no such column" fehlschlagen.
        c.execute("CREATE INDEX IF NOT EXISTS idx_lead_key_raw ON raw_leads(lead_key)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tel_key_raw ON raw_leads(tel_key)")
        c.commit()
    if needs_backfill:
        _backfill_lead_keys()
    if needs_tel_backfill:
        _backfill_tel_keys()


def _backfill_lead_keys() -> None:
    """Einmalige Nachrüstung für Bestands-DBs: berechnet lead_key (derselbe globale
    Dedup-Schlüssel wie DB2/Cloud, siehe leadkey.py) für alle Zeilen ohne. Läuft nur einmal
    (danach ist die Spalte für alle Zeilen gesetzt), best-effort pro Zeile."""
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT id, name, stadt FROM raw_leads WHERE lead_key IS NULL"
        ).fetchall()
        for row in rows:
            try:
                key = _lead_key(row["name"] or "", row["stadt"] or "")
                c.execute("UPDATE raw_leads SET lead_key=? WHERE id=?", (key, row["id"]))
            except Exception:
                continue
        c.commit()


def _backfill_tel_keys() -> None:
    """Einmalige Nachrüstung für Bestands-DBs: berechnet tel_key (normalisierte Telefonnummer,
    siehe leadkey.phone_key) für alle Zeilen ohne. Läuft nur einmal, best-effort pro Zeile."""
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT id, telefon FROM raw_leads WHERE tel_key IS NULL"
        ).fetchall()
        for row in rows:
            try:
                c.execute("UPDATE raw_leads SET tel_key=? WHERE id=?",
                          (_phone_key(row["telefon"] or ""), row["id"]))
            except Exception:
                continue
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
    "website_url", "has_website", "maps_url", "bilder_maps", "foto_url", "foto_urls",
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

    # Firmennamen mit lokaler Logik säubern (SEO-Codes/Wiederholungen/Spam raus) —
    # VOR Dedup + Speicherung, damit Feed, DB und der globale lead_key denselben
    # sauberen Namen verwenden. In-place, damit on_lead() den sauberen Namen sendet.
    from agents.name_clean import quick_clean
    name = quick_clean(name) or name
    lead["name"] = name
    key     = _lead_key(name, stadt)
    tel_key = _phone_key(lead.get("telefon") or "")

    # bilder_maps aus 'bilder' übernehmen wenn nicht explizit gesetzt
    row = {k: v for k, v in lead.items() if k in _RAW_COLUMNS}
    if "bilder_maps" not in row:
        row["bilder_maps"] = int(lead.get("bilder", 0) or 0)
    row.setdefault("gefunden_am", datetime.now().isoformat(timespec="seconds"))
    row["lead_key"] = key
    row["tel_key"]  = tel_key

    with _lock, _conn() as c:
        # Dedup über den globalen lead_key (leadkey.py) — derselbe Schlüssel wie DB2/Cloud
        # (vereinheitlicht, vorher ein eigener ungeindexter LOWER(name)/LOWER(stadt)-Scan hier
        # vs. lead_key-Hash dort). Indiziert über idx_lead_key_raw.
        dup = c.execute(
            "SELECT 1 FROM raw_leads WHERE lead_key=? LIMIT 1", (key,)
        ).fetchone()
        if dup:
            return None
        # ZUSÄTZLICHER Dedup über die Telefonnummer: fängt dieselbe Firma ab, die zwei Quellen
        # mit unterschiedlicher Namens-Schreibweise gefunden haben (verschiedene lead_keys, aber
        # derselbe Anschluss) — genau die „gleiche Firma zweimal bearbeitet"-Fälle. Nur wenn
        # tel_key belastbar ist (>=7 Ziffern, sonst ''), damit leere/kurze Nummern nichts falsch
        # zusammenführen. Indiziert über idx_tel_key_raw.
        if tel_key:
            dup_tel = c.execute(
                "SELECT 1 FROM raw_leads WHERE tel_key=? LIMIT 1", (tel_key,)
            ).fetchone()
            if dup_tel:
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
    now = datetime.now().isoformat(timespec="seconds")
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT * FROM raw_leads WHERE eval_status='pending' "
            # gefunden_am ASC als Tiebreaker → kein Aushungern alter Pending-Leads
            "ORDER BY has_website ASC, bewertung DESC, gefunden_am ASC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        lead = dict(row)
        c.execute(
            "UPDATE raw_leads SET eval_status='running', claimed_at=? WHERE id=?",
            (now, lead["id"]),
        )
        c.commit()
        lead["eval_status"] = "running"
        return lead


def count_pending() -> int:
    """Anzahl der Roh-Leads, die noch auf Bewertung warten ('pending'). Für den
    Lead-Collector: nach Sammel-Fensterende warten, bis dieser Rest-Backlog vom
    Evaluator abgearbeitet ist, bevor auch der Evaluator gestoppt wird."""
    with _lock, _conn() as c:
        row = c.execute("SELECT COUNT(*) AS n FROM raw_leads WHERE eval_status='pending'").fetchone()
        return int(row["n"]) if row else 0


def reset_stale_running(max_minutes: int = 10) -> int:
    """Watchdog: setzt 'running'-Leads, deren claimed_at älter als max_minutes ist
    (oder fehlt — z.B. Crash mitten in analyze()), zurück auf 'pending'. Gibt die
    Anzahl zurück. Wird periodisch vom Controller aufgerufen."""
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(minutes=max_minutes)).isoformat(timespec="seconds")
    with _lock, _conn() as c:
        cur = c.execute(
            "UPDATE raw_leads SET eval_status='pending', claimed_at=NULL "
            "WHERE eval_status='running' AND (claimed_at IS NULL OR claimed_at < ?)",
            (cutoff,),
        )
        c.commit()
        return cur.rowcount


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


def get_by_id(raw_id: int) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM raw_leads WHERE id=?", (raw_id,)).fetchone()
    return dict(row) if row else None


def get_competition(stadt: str, branche: str) -> dict:
    """Wie viele Betriebe gleicher Stadt/Branche haben (k)eine Website (Verkaufsargument)."""
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS gesamt, "
            "SUM(CASE WHEN has_website=0 THEN 1 ELSE 0 END) AS ohne "
            "FROM raw_leads WHERE LOWER(stadt)=LOWER(?) AND LOWER(branche)=LOWER(?)",
            (stadt or "", branche or ""),
        ).fetchone()
    gesamt = int(row["gesamt"] or 0)
    ohne   = int(row["ohne"] or 0)
    return {"gesamt": gesamt, "ohne_website": ohne,
            "prozent_ohne": round(ohne / gesamt * 100) if gesamt else 0}


def get_dashboard_stats() -> dict:
    """Zähler für das Dashboard-Topbar: Gesamtfunde, ohne-Website, Quellen, Bundesländer.
    (Hot/Warm/Cold liefert db_evaluated — die Bewertungs-DB.)"""
    with _lock, _conn() as c:
        total   = c.execute("SELECT COUNT(*) FROM raw_leads").fetchone()[0]
        no_web  = c.execute("SELECT COUNT(*) FROM raw_leads WHERE has_website=0").fetchone()[0]
        finders = c.execute(
            "SELECT finder, COUNT(*) AS n FROM raw_leads GROUP BY finder ORDER BY n DESC"
        ).fetchall()
        bl_rows = c.execute(
            "SELECT bundesland, COUNT(*) AS n FROM raw_leads "
            "GROUP BY bundesland ORDER BY n DESC LIMIT 20"
        ).fetchall()
    return {
        "total":         total,
        "no_web":        no_web,
        "finders":       {r["finder"]: r["n"] for r in finders if r["finder"]},
        "bundeslaender": {r["bundesland"]: r["n"] for r in bl_rows if r["bundesland"]},
    }


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
