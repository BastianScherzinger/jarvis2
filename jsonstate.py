"""
jsonstate.py — atomares Schreiben von JSON-State-Dateien.

Warum: Mehrere Module persistieren kleinen Zustand als JSON (Kosten, Latches,
Suppress-Listen, Auth-Tokens, Logs). Ein direktes write_text() in die Zieldatei
ist NICHT atomar — stürzt der Prozess (oder Windows) mitten im Schreiben ab,
bleibt eine halbe/leere Datei zurück und der komplette Zustand ist verloren
(die Lese-Seiten fangen das zwar ab, starten dann aber bei null: Kosten weg,
Suppress-Liste weg, Logins weg).

Muster hier: in eine .tmp-Datei im SELBEN Ordner schreiben, dann os.replace()
— das ist auf Windows wie POSIX ein atomarer Austausch, die Zieldatei ist zu
jedem Zeitpunkt entweder der alte oder der neue vollständige Stand.

Thread-Sicherheit bleibt Sache des Aufrufers (jedes Modul hat seinen _lock);
dieser Helfer macht nur den Schreibvorgang selbst crash-sicher.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def atomic_write_json(path: "Path | str", obj, indent: "int | None" = None) -> None:
    """Schreibt obj als JSON (UTF-8, ensure_ascii=False) atomar nach path.
    Legt Elternordner bei Bedarf an. Wirft bei Fehlern — Fehlerbehandlung
    (z.B. still schlucken) bleibt bewusst beim Aufrufer."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=indent), encoding="utf-8")
    os.replace(tmp, p)
