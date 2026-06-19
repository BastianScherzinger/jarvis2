"""
Kanonischer Lead-Dedup-Schlüssel — EINE Definition für die gesamte Codebase.

Vorher war derselbe Schlüssel an drei Stellen dupliziert (db_evaluated, cloud_sync)
und konnte auseinanderlaufen. Jetzt: eine Quelle, von allen importiert.

WICHTIG: Das Format bleibt unverändert — md5(lower(name)|lower(stadt)) — damit alle
bereits in DB2/Supabase gespeicherten lead_keys weiterhin matchen (keine Doppel beim Sync).
"""
from __future__ import annotations

import hashlib


def lead_key(name: str, stadt: str) -> str:
    """Globaler Unique-Key über alle PCs: md5(lower(name)|lower(stadt))."""
    s = f"{(name or '').strip().lower()}|{(stadt or '').strip().lower()}"
    return hashlib.md5(s.encode("utf-8")).hexdigest()
