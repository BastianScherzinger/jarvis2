"""
review_queue.py — Freigabe-Warteschlange für den Discord-Voting-Gate.

Jede fertig gebaute + verbesserte Webseite landet hier als "Review" (Status pending),
bevor sie an einen echten Kunden geschickt wird. Der Discord-Bot postet sie, sammelt
Daumen-hoch/-runter und setzt den Status. Um DISCORD_SEND_HOUR (Default 12 Uhr) gehen
alle freigegebenen (approved) Reviews an die echte Kundenadresse.

Persistenz: data/reviews.json (überlebt Neustarts — Buttons funktionieren weiter).
Reiner Standardbibliotheks-Code, thread-sicher.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

_BASE = Path(__file__).parent
_PATH = _BASE / "data" / "reviews.json"
_lock = threading.Lock()

# Status-Werte:
PENDING, APPROVED, REJECTED, SENT, SKIPPED = "pending", "approved", "rejected", "sent", "skipped"


def _load() -> dict:
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"reviews": []}


def _save(data: dict) -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_PATH)
    except Exception:
        pass


def _needed() -> int:
    # Standard: 1× 👍 gibt die Seite frei (1× 👎 ist weiterhin ein Veto → verworfen).
    # Über DISCORD_APPROVALS_NEEDED in der .env anhebbar.
    import os
    return max(1, int(os.environ.get("DISCORD_APPROVALS_NEEDED", "1") or "1"))


def add(name: str, stadt: str, branche: str, link: str, email: str = "",
        ansprechpartner: str = "", folder: str = "", recipients: "list | None" = None,
        email_text: str = "") -> dict:
    """Legt einen neuen Review (Status pending) an und gibt ihn zurück.

    recipients: optionale Empfängerliste (Custom-Modus, 11+). Ist sie gesetzt, geht das
    Angebot nach Freigabe an JEDE dieser Adressen; sonst an die Einzeladresse `email`.
    email_text: Plaintext-Version der Angebots-Mail (für Discord-Vorschau)."""
    rid = uuid.uuid4().hex[:12]
    rec = [e.strip() for e in (recipients or []) if e and "@" in e]
    # Dedup: schon ein offener Review für dieselbe Seite → nicht nochmal posten.
    with _lock:
        data = _load()
        for existing in data["reviews"]:
            if (existing.get("name", "").lower().strip() == name.lower().strip()
                    and existing.get("status") in (PENDING, APPROVED)):
                return dict(existing)
        review = {
            "id": rid, "name": name, "stadt": stadt, "branche": branche,
            "link": link, "email": email, "ansprechpartner": ansprechpartner,
            "folder": folder, "recipients": rec, "status": PENDING,
            "votes_up": [], "votes_down": [],
            "message_id": 0, "channel_id": 0, "ts": time.time(),
            "sent_ts": 0.0, "note": "", "email_text": (email_text or ""),
        }
        data["reviews"].append(review)
        _save(data)
    return dict(review)


def get(rid: str) -> "dict | None":
    with _lock:
        for r in _load()["reviews"]:
            if r["id"] == rid:
                return dict(r)
    return None


def all(limit: int = 200) -> list:
    with _lock:
        return list(reversed(_load()["reviews"]))[:limit]


def update(rid: str, **fields) -> "dict | None":
    with _lock:
        data = _load()
        for r in data["reviews"]:
            if r["id"] == rid:
                r.update(fields)
                _save(data)
                return dict(r)
    return None


def set_message(rid: str, message_id: int, channel_id: int) -> None:
    update(rid, message_id=int(message_id), channel_id=int(channel_id))


def vote(rid: str, user_id: str, up: bool, owners: "list | None" = None) -> "dict | None":
    """Verbucht eine Stimme. Ein Daumen-runter ist ein Veto (-> rejected). Erreichen die
    Daumen-hoch die nötige Schwelle (DISCORD_APPROVALS_NEEDED) -> approved.

    owners: optionale Whitelist erlaubter User-IDs (sonst zählt jeder)."""
    uid = str(user_id)
    if owners:
        owners = [str(o) for o in owners if str(o).strip()]
        if owners and uid not in owners:
            return {"error": "not_owner"}
    with _lock:
        data = _load()
        for r in data["reviews"]:
            if r["id"] != rid:
                continue
            if r["status"] in (SENT,):
                return dict(r)
            up_set = [u for u in r["votes_up"] if u != uid]
            dn_set = [u for u in r["votes_down"] if u != uid]
            if up:
                up_set.append(uid)
            else:
                dn_set.append(uid)
            r["votes_up"], r["votes_down"] = up_set, dn_set
            if dn_set:
                r["status"] = REJECTED
            elif len(up_set) >= _needed():
                r["status"] = APPROVED
            else:
                r["status"] = PENDING
            _save(data)
            return dict(r)
    return None


def approved_unsent() -> list:
    """Freigegebene Reviews, die noch nicht versendet wurden."""
    with _lock:
        return [dict(r) for r in _load()["reviews"] if r["status"] == APPROVED]


def pending() -> list:
    with _lock:
        return [dict(r) for r in _load()["reviews"] if r["status"] == PENDING]


def mark_sent(rid: str, ok: bool, note: str = "") -> None:
    update(rid, status=SENT if ok else SKIPPED, sent_ts=time.time(), note=note)


def stats() -> dict:
    with _lock:
        rs = _load()["reviews"]
    c = {PENDING: 0, APPROVED: 0, REJECTED: 0, SENT: 0, SKIPPED: 0}
    for r in rs:
        c[r.get("status", PENDING)] = c.get(r.get("status", PENDING), 0) + 1
    c["needed"] = _needed()
    c["total"] = len(rs)
    return c
