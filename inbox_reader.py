"""
inbox_reader.py — Gmail-Antworten lesen + LOKAL analysieren (Schritt 7 „Abschluss").

Liest per IMAP die Antworten auf die versendeten Angebots-Mails, ordnet jede Antwort dem
zugehörigen Lead / der Webseite zu (Absender = Kundenadresse aus review_queue) und lässt sie
von der lokalen KI (Ollama) einordnen: Interesse / Absage / Rückfrage / Preisfrage — mit
Kurz-Zusammenfassung, Dringlichkeit und empfohlenem nächsten Schritt. Ergebnisse landen in
data/replies.json, im Aktivitäts-Feed (Home) und — bei echtem Interesse — als Discord-Ping.

SICHERHEIT
  • Läuft NUR, wenn JARVIS_INBOX_ENABLED=true UND ein IMAP-Zugang gesetzt ist.
  • Reines LESEN (BODY.PEEK) — es wird nichts gelöscht, verschoben, als gelesen markiert,
    verschickt oder automatisch beantwortet. Der Abschluss bleibt beim Menschen.
  • Analyse 100 % lokal (Ollama) → keine Cloud-Kosten, keine Daten nach außen.

.env
  JARVIS_INBOX_ENABLED=false
  IMAP_HOST=imap.gmail.com
  IMAP_PORT=993
  IMAP_USER=postfach@gmail.com      # Default: SMTP_USER
  IMAP_PASS=<Gmail-App-Passwort>     # 2FA nötig, dann App-Passwort erzeugen. Default: SMTP_PASS
  JARVIS_INBOX_POLL=300              # Sekunden zwischen zwei Prüfläufen
  JARVIS_INBOX_FOLDER=INBOX
  JARVIS_INBOX_LOOKBACK_DAYS=14      # nur Mails der letzten N Tage betrachten
  JARVIS_LOCAL_MODEL / JARVIS_TOOL_MODEL  # Ollama-Modell für die Analyse
"""
from __future__ import annotations

import email
import imaplib
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

import logger
from scrapers import _http

_BASE   = Path(__file__).resolve().parent
_STORE  = _BASE / "data" / "replies.json"
_lock   = threading.Lock()
_started = False

# Kategorien, die einen echten Discord-Ping wert sind (Chance auf Abschluss).
_HOT = {"interesse", "rueckfrage", "preisfrage", "termin"}


# ── Konfiguration ─────────────────────────────────────────────────────────────

def enabled() -> bool:
    return (os.environ.get("JARVIS_INBOX_ENABLED", "false") or "").strip().lower() == "true"


def _cfg() -> dict:
    return {
        "host":   os.environ.get("IMAP_HOST", "imap.gmail.com").strip(),
        "port":   int(os.environ.get("IMAP_PORT", "993") or 993),
        "user":   (os.environ.get("IMAP_USER") or os.environ.get("SMTP_USER") or "").strip(),
        "pass":   (os.environ.get("IMAP_PASS") or os.environ.get("SMTP_PASS") or ""),
        "folder": os.environ.get("JARVIS_INBOX_FOLDER", "INBOX").strip() or "INBOX",
        "poll":   max(60, int(os.environ.get("JARVIS_INBOX_POLL", "300") or 300)),
        "lookback": max(1, int(os.environ.get("JARVIS_INBOX_LOOKBACK_DAYS", "14") or 14)),
    }


def configured() -> bool:
    c = _cfg()
    return bool(c["host"] and c["user"] and c["pass"])


# ── Persistenz ────────────────────────────────────────────────────────────────

def _read_store() -> dict:
    try:
        return json.loads(_STORE.read_text(encoding="utf-8"))
    except Exception:
        return {"replies": [], "seen_uids": []}


def _write_store(d: dict) -> None:
    try:
        _STORE.parent.mkdir(parents=True, exist_ok=True)
        _STORE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def replies(limit: int = 100) -> list:
    """Neueste analysierte Antworten (für Dashboard/API)."""
    with _lock:
        items = list(_read_store().get("replies", []))
    return items[-limit:][::-1]     # neueste zuerst


def status() -> dict:
    d = _read_store()
    reps = d.get("replies", [])
    hot = sum(1 for r in reps if (r.get("kategorie") in _HOT))
    return {
        "enabled": enabled(),
        "configured": configured(),
        "count": len(reps),
        "hot": hot,
        "last_ts": (reps[-1].get("ts") if reps else 0),
        "host": _cfg()["host"] if configured() else "",
    }


# ── E-Mail-Parsing ────────────────────────────────────────────────────────────

def _decode(s) -> str:
    try:
        return str(make_header(decode_header(s or "")))
    except Exception:
        return str(s or "")


def _plain_body(msg: "email.message.Message") -> str:
    """Reinen Text extrahieren (text/plain bevorzugt), zitierte Historie abschneiden."""
    text = ""
    try:
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                disp = str(part.get("Content-Disposition") or "")
                if ct == "text/plain" and "attachment" not in disp:
                    payload = part.get_payload(decode=True) or b""
                    text = payload.decode(part.get_content_charset() or "utf-8", "replace")
                    break
            if not text:                       # Fallback: HTML grob entkernen
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        payload = part.get_payload(decode=True) or b""
                        html = payload.decode(part.get_content_charset() or "utf-8", "replace")
                        text = re.sub(r"<[^>]+>", " ", html)
                        break
        else:
            payload = msg.get_payload(decode=True) or b""
            text = payload.decode(msg.get_content_charset() or "utf-8", "replace")
    except Exception:
        text = ""
    return _strip_quoted(text)


def _strip_quoted(text: str) -> str:
    """Zitierte Original-Mail und Signatur abschneiden — nur die eigentliche Antwort behalten."""
    if not text:
        return ""
    lines = []
    for ln in text.splitlines():
        low = ln.strip().lower()
        # Typische Zitat-Trenner (DE/EN) → ab hier ist alles die Original-Mail.
        if (low.startswith(">")
                or re.match(r"^am .+ schrieb .+:", low)
                or re.match(r"^on .+ wrote:", low)
                or low.startswith("von:") or low.startswith("from:")
                or low.startswith("-----ursprüngliche nachricht")
                or low.startswith("gesendet von")):
            break
        lines.append(ln)
    return "\n".join(lines).strip()[:1800]


# ── Zuordnung zum versendeten Angebot ─────────────────────────────────────────

def _match_lead(sender_email: str) -> dict:
    """Findet das versendete Angebot zur Absenderadresse (case-insensitive)."""
    se = (sender_email or "").strip().lower()
    if not se:
        return {}
    try:
        import review_queue as rq
        for r in rq.all(limit=1000):
            if (r.get("email") or "").strip().lower() == se:
                return {"name": r.get("name", ""), "branche": r.get("branche", ""),
                        "stadt": r.get("stadt", ""), "link": r.get("link", ""),
                        "preis": r.get("preis", 0), "review_id": r.get("id", "")}
    except Exception:
        pass
    return {}


# ── Lokale KI-Analyse (Ollama) ────────────────────────────────────────────────

_SYS = (
    "Du bist ein nüchterner Vertriebs-Assistent. Analysiere die Antwort eines Kunden auf ein "
    "Webseiten-Angebot. Antworte AUSSCHLIESSLICH mit einem JSON-Objekt, ohne Fließtext, mit den "
    "Feldern: kategorie (eines von: interesse, absage, rueckfrage, preisfrage, termin, neutral), "
    "zusammenfassung (max 20 Wörter, deutsch), dringlichkeit (hoch|mittel|niedrig), "
    "empfehlung (max 15 Wörter: was Bastian als Nächstes tun sollte)."
)


def _analyze(body: str, lead: dict) -> dict:
    ctx = f"Kunde: {lead.get('name','unbekannt')} ({lead.get('branche','')}). " if lead else ""
    prompt = f"{ctx}Antwort des Kunden:\n\"\"\"\n{body}\n\"\"\"\nGib das JSON zurück."
    raw = ""
    try:
        raw = _http.ask_ollama(prompt, _SYS, model=os.environ.get("JARVIS_TOOL_MODEL", ""))
    except Exception:
        raw = ""
    return _parse_analysis(raw)


def _parse_analysis(raw: str) -> dict:
    default = {"kategorie": "neutral", "zusammenfassung": "", "dringlichkeit": "niedrig",
               "empfehlung": ""}
    if not raw:
        return default
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return default
    try:
        d = json.loads(m.group(0))
    except Exception:
        return default
    kat = str(d.get("kategorie", "neutral")).strip().lower()
    valid = {"interesse", "absage", "rueckfrage", "preisfrage", "termin", "neutral"}
    return {
        "kategorie": kat if kat in valid else "neutral",
        "zusammenfassung": str(d.get("zusammenfassung", ""))[:200],
        "dringlichkeit": str(d.get("dringlichkeit", "niedrig")).strip().lower(),
        "empfehlung": str(d.get("empfehlung", ""))[:200],
    }


# ── Ein Prüflauf ──────────────────────────────────────────────────────────────

def check_once() -> dict:
    """Ein IMAP-Durchlauf: neue Antworten holen, zuordnen, analysieren, speichern.
    Gibt {new, hot, error} zurück. Read-only (BODY.PEEK, keine Statusänderung im Postfach)."""
    if not enabled():
        return {"new": 0, "hot": 0, "error": "disabled"}
    if not configured():
        return {"new": 0, "hot": 0, "error": "imap-nicht-konfiguriert"}
    c = _cfg()
    store = _read_store()
    seen = set(store.get("seen_uids", []))
    new_items = []
    try:
        M = imaplib.IMAP4_SSL(c["host"], c["port"])
        try:
            M.login(c["user"], c["pass"])
            M.select(c["folder"], readonly=True)     # readonly → Postfach bleibt unangetastet
            since = (datetime.now() - timedelta(days=c["lookback"])).strftime("%d-%b-%Y")
            typ, data = M.uid("search", None, f'(SINCE {since})')
            if typ != "OK":
                return {"new": 0, "hot": 0, "error": "search-fehlgeschlagen"}
            uids = (data[0].split() if data and data[0] else [])
            for uid in uids:
                uid_s = uid.decode() if isinstance(uid, bytes) else str(uid)
                if uid_s in seen:
                    continue
                seen.add(uid_s)
                try:
                    t2, md = M.uid("fetch", uid, "(BODY.PEEK[])")
                    if t2 != "OK" or not md or not md[0]:
                        continue
                    msg = email.message_from_bytes(md[0][1])
                except Exception:
                    continue
                from_name, from_addr = parseaddr(_decode(msg.get("From", "")))
                lead = _match_lead(from_addr)
                if not lead:
                    continue                          # nur Antworten auf unsere Angebote analysieren
                body = _plain_body(msg)
                if not body:
                    continue
                analysis = _analyze(body, lead)
                try:
                    when = parsedate_to_datetime(msg.get("Date", "")).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    when = datetime.now().strftime("%Y-%m-%d %H:%M")
                item = {
                    "uid": uid_s, "from": from_addr, "from_name": from_name,
                    "subject": _decode(msg.get("Subject", "")),
                    "date": when, "name": lead.get("name", ""),
                    "branche": lead.get("branche", ""), "link": lead.get("link", ""),
                    "preis": lead.get("preis", 0), "review_id": lead.get("review_id", ""),
                    "snippet": body[:280],
                    "ts": time.time(), **analysis,
                }
                new_items.append(item)
        finally:
            try: M.logout()
            except Exception: pass
    except Exception as e:
        logger.warn("Inbox", f"IMAP-Fehler: {type(e).__name__}: {str(e)[:120]}")
        return {"new": 0, "hot": 0, "error": type(e).__name__}

    hot = 0
    if new_items:
        with _lock:
            store = _read_store()
            store.setdefault("replies", []).extend(new_items)
            store["replies"] = store["replies"][-500:]
            store["seen_uids"] = (list(seen))[-2000:]
            _write_store(store)
        for it in new_items:
            _announce(it)
            if it.get("kategorie") in _HOT:
                hot += 1
    else:
        # seen_uids trotzdem sichern (verhindert Re-Analyse fremder Mails jeden Lauf)
        with _lock:
            store = _read_store()
            store["seen_uids"] = (list(seen))[-2000:]
            _write_store(store)
    return {"new": len(new_items), "hot": hot, "error": ""}


def _announce(it: dict) -> None:
    """In den Aktivitäts-Feed schreiben + bei echtem Interesse in Discord pingen."""
    kat = it.get("kategorie", "neutral")
    icon = {"interesse": "🔥", "preisfrage": "💶", "rueckfrage": "❓", "termin": "📅",
            "absage": "🚫", "neutral": "✉️"}.get(kat, "✉️")
    detail = f"{it.get('name') or it.get('from')}: {it.get('zusammenfassung','')}"
    try:
        logger.activity("Posteingang", f"Antwort ({kat})", detail, icon=icon, category="email")
    except Exception:
        pass
    if kat in _HOT:
        try:
            import discord_bot
            discord_bot.notify(
                f"{icon} Kundenantwort — {kat.upper()}",
                f"**{it.get('name') or it.get('from')}**\n{it.get('zusammenfassung','')}\n\n"
                f"→ {it.get('empfehlung','')}\nDringlichkeit: {it.get('dringlichkeit','?')}",
                color=0x2ecc71 if kat in ("interesse", "termin") else 0xf1c40f,
            )
        except Exception:
            pass


# ── Hintergrund-Loop ──────────────────────────────────────────────────────────

def _loop() -> None:
    time.sleep(30)                          # App-Start abwarten
    poll = _cfg()["poll"]
    logger.info("Inbox", f"Antwort-Analyse aktiv (IMAP {_cfg()['host']}, alle {poll}s, "
                         "read-only, lokale KI).")
    while True:
        try:
            res = check_once()
            if res.get("new"):
                logger.success("Inbox", f"{res['new']} neue Antwort(en) analysiert, "
                                        f"{res['hot']} heiß (Interesse/Rückfrage).")
        except Exception as e:
            logger.warn("Inbox", f"Durchlauf-Fehler: {type(e).__name__}")
        time.sleep(max(60, _cfg()["poll"]))


def start() -> dict:
    """Startet die Antwort-Analyse EINMAL (idempotent). Nur wenn aktiviert + konfiguriert."""
    global _started
    if _started:
        return {"ok": True, "already": True}
    if not enabled():
        return {"ok": False, "reason": "JARVIS_INBOX_ENABLED != true"}
    if not configured():
        logger.warn("Inbox", "aktiviert, aber IMAP-Zugang fehlt (IMAP_USER/IMAP_PASS) — bleibt aus.")
        return {"ok": False, "reason": "imap-nicht-konfiguriert"}
    _started = True
    threading.Thread(target=_loop, name="InboxReader", daemon=True).start()
    return {"ok": True}
