"""
Kanonischer Lead-Dedup-Schlüssel — EINE Definition für die gesamte Codebase.

Vorher war derselbe Schlüssel an drei Stellen dupliziert (db_evaluated, cloud_sync)
und konnte auseinanderlaufen. Jetzt: eine Quelle, von allen importiert.

WICHTIG: Das Format bleibt unverändert — md5(lower(name)|lower(stadt)) — damit alle
bereits in DB2/Supabase gespeicherten lead_keys weiterhin matchen (keine Doppel beim Sync).
"""
from __future__ import annotations

import hashlib
import re


def lead_key(name: str, stadt: str) -> str:
    """Globaler Unique-Key über alle PCs: md5(lower(name)|lower(stadt))."""
    s = f"{(name or '').strip().lower()}|{(stadt or '').strip().lower()}"
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def phone_key(telefon: str) -> str:
    """Normalisierte Telefonnummer als ZUSÄTZLICHER Dedup-Anker.

    Warum: `lead_key` dedupt nur über name+stadt. Findet Maps die Firma als
    „Zahnarzt Dr. Müller" und ein Verzeichnis als „Dr. Müller Zahnarztpraxis", entstehen zwei
    verschiedene lead_keys → dieselbe Firma würde zweimal bewertet und evtl. zweimal gebaut. Die
    Telefonnummer ist derselbe physische Anschluss und damit der verlässlichste Anker.

    Normalisierung: nur Ziffern; internationales 00-Präfix und DE/AT-Ländervorwahl (49/43) sowie
    eine führende Amts-0 werden vereinheitlicht, sodass „+49 30 123456" und „030 123456" gleich
    werden. Gibt '' zurück, wenn < 7 Ziffern übrig bleiben (dann NICHT zum Dedup verwenden —
    zu kurz/unsicher, z.B. leere oder abgeschnittene Nummern)."""
    d = re.sub(r"\D", "", telefon or "")
    if d.startswith("00"):
        d = d[2:]
    for cc in ("49", "43"):                      # DE, AT — internationale Vorwahl entfernen
        if d.startswith(cc) and len(d) > 9:
            d = d[len(cc):]
            break
    d = d.lstrip("0")                            # führende Amts-0 (national) angleichen
    return d if len(d) >= 7 else ""
