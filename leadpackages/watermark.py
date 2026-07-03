"""
Unsichtbares Käufer-Wasserzeichen für Exporte (Entscheidung: Leak-Schutz ja).

Kodiert die Bestell-/Käufer-ID als Folge von Zero-Width-Zeichen (U+200B/U+200C),
die in Text-Editoren, Excel und den meisten CSV-Viewern unsichtbar sind, aber bei
einem geleakten Datenpaket per decode() zurückgelesen werden können. In jede Zeile
eingebettet (nicht nur die erste), damit auch ein Teil-Leak (z.B. nur 20 von 200
Zeilen kopiert) noch zuordenbar bleibt.
"""
from __future__ import annotations

import secrets

_ZERO = "​"   # Zero Width Space  -> Bit 0
_ONE = "‌"    # Zero Width Non-Joiner -> Bit 1


def new_watermark_id() -> str:
    return secrets.token_hex(6)   # 12 Hex-Zeichen, genug Entropie für eine Bestell-ID


def _encode(text: str) -> str:
    bits = "".join(format(b, "08b") for b in text.encode("utf-8"))
    return "".join(_ONE if b == "1" else _ZERO for b in bits)


def decode(text: str) -> str:
    bits = "".join("1" if ch == _ONE else "0" for ch in text if ch in (_ZERO, _ONE))
    n = len(bits) - (len(bits) % 8)
    byte_values = [int(bits[i:i + 8], 2) for i in range(0, n, 8)]
    try:
        return bytes(byte_values).decode("utf-8", errors="ignore")
    except ValueError:
        return ""


def embed(rows: list[dict], watermark_id: str, field: str = "adresse") -> list[dict]:
    """Gibt eine neue Liste zurück (Original bleibt unverändert) — jede Zeile trägt
    das unsichtbare Zeichen-Muster im angegebenen Feld."""
    marker = _encode(watermark_id)
    out = []
    for row in rows:
        row = dict(row)
        row[field] = (row.get(field) or "") + marker
        out.append(row)
    return out
