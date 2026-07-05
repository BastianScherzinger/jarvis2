"""
discord_bot.py — Freigabe-Bot mit Voting-Gate vor dem Kundenversand.

Ablauf:
  1. Der Auto-Builder baut + verbessert eine Webseite und ruft `submit_for_review(...)`.
  2. Der Bot postet sie in den Discord-Kanal (Link + Details) mit zwei Buttons:
     👍 (Daumen hoch) / 👎 (Daumen runter).
  3. Erreichen die 👍 die Schwelle (DISCORD_APPROVALS_NEEDED, Default 1) ohne ein
     einziges 👎-Veto, gilt die Seite als FREIGEGEBEN.
  4. An jedem konfigurierten Versand-Slot (DISCORD_SEND_HOURS, Default 9/12/15/18 Uhr —
     mehrmals täglich) gehen alle freigegebenen Seiten an die ECHTE Kundenadresse
     (umgeht bewusst JARVIS_EMAIL_REDIRECT — das Voting ist die Sicherung).

Robust: Ohne installiertes `discord.py` oder ohne DISCORD_BOT_TOKEN ist der Bot ein
No-op (`enabled()` = False); der Auto-Builder fällt dann auf den alten Weg zurück
(E-Mail-Vorschau an Bastian). Buttons sind persistent (DynamicItem) und funktionieren
auch nach einem Neustart weiter.

Setup siehe .env (DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID, ...).
"""
from __future__ import annotations

import asyncio
import os
import threading
from datetime import datetime, time as dtime

import logger
import review_queue as rq

try:
    import discord
    from discord.ext import tasks
    _HAS_DISCORD = True
except Exception:                                    # discord.py nicht installiert
    _HAS_DISCORD = False

_loop: "asyncio.AbstractEventLoop | None" = None
_bot = None
_started = False
_lock = threading.Lock()


# ── Konfiguration ─────────────────────────────────────────────────────────────

def _token() -> str:
    return os.environ.get("DISCORD_BOT_TOKEN", "").strip()


def _channel_id() -> int:
    try:
        return int(os.environ.get("DISCORD_CHANNEL_ID", "0") or "0")
    except ValueError:
        return 0


def _owners() -> list:
    return [x.strip() for x in os.environ.get("DISCORD_OWNER_IDS", "").split(",") if x.strip()]


def _send_hours() -> list[int]:
    """Alle Versand-Slots (Stunden 0–23) für den Tagesversand — mehrere erlaubt, damit
    freigegebene Seiten MEHRMALS täglich rausgehen statt nur einmal um 12 Uhr.

    Priorität:
      1. DISCORD_SEND_HOURS  — Komma-Liste, z.B. "9,12,15,18"
      2. DISCORD_SEND_HOUR   — einzelne Stunde (Abwärtskompatibilität)
      3. Default             — 9, 12, 15, 18 Uhr
    """
    raw = (os.environ.get("DISCORD_SEND_HOURS") or "").strip()
    if not raw and "DISCORD_SEND_HOUR" in os.environ:
        raw = (os.environ.get("DISCORD_SEND_HOUR") or "").strip()
    if not raw:
        raw = "9,12,15,18"
    hours = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            h = int(part)
        except ValueError:
            continue
        if 0 <= h <= 23:
            hours.append(h)
    return sorted(set(hours)) or [12]


def _send_hour() -> int:
    """Primärer (erster) Versand-Slot — für Anzeige-Zwecke, wo nur eine Stunde passt."""
    return _send_hours()[0]


def _send_hours_label() -> str:
    """Menschenlesbare Liste aller Versand-Slots, z.B. '9:00, 12:00, 15:00 & 18:00 Uhr'."""
    hs = _send_hours()
    if len(hs) == 1:
        return f"{hs[0]}:00 Uhr"
    return ", ".join(f"{h}:00" for h in hs[:-1]) + f" & {hs[-1]}:00 Uhr"


def enabled() -> bool:
    """True nur, wenn discord.py vorhanden UND Token + Kanal konfiguriert sind."""
    return _HAS_DISCORD and bool(_token()) and _channel_id() > 0


def auto_send() -> bool:
    """Auto-Send-Modus: fertige Seiten werden OHNE 👍-Bestätigung direkt freigegeben und
    gehen beim Tagesversand (DISCORD_SEND_HOUR) automatisch an den Kunden. Default: AN.
    Ausschalten mit JARVIS_AUTO_SEND=0 (dann gilt wieder das 👍-Freigabe-Gate)."""
    return os.environ.get("JARVIS_AUTO_SEND", "1").strip().lower() not in ("0", "false", "no", "off", "")


# ── Versand-Latch: pro Stunden-Slot EINMAL versenden ───────────────────────────
# Verhindert Doppelversand innerhalb desselben Slots (z.B. wenn die App zur Versandstunde
# neu startet und Task-Loop + Watchdog beide feuern). Persistiert Datum + bereits erledigte
# Slots lokal. Früher nur ein Tages-Latch → nur ein Versand pro Tag möglich.
from pathlib import Path as _Path
_NOON_STATE = _Path(__file__).parent / "data" / "noon_state.json"


def _load_noon_state() -> dict:
    try:
        import json as _j
        data = _j.loads(_NOON_STATE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _slot_ran(hour: int) -> bool:
    """True, wenn der Versand-Slot dieser Stunde HEUTE bereits gelaufen ist."""
    from datetime import date as _d
    data = _load_noon_state()
    if data.get("date") != _d.today().isoformat():
        return False
    return int(hour) in (data.get("hours") or [])


def _mark_slot_ran(hour: int) -> None:
    """Markiert den Stunden-Slot als heute erledigt (Datum-Wechsel setzt die Liste zurück)."""
    try:
        import json as _j
        from datetime import date as _d
        today = _d.today().isoformat()
        data = _load_noon_state()
        hours = list(data.get("hours") or []) if data.get("date") == today else []
        if int(hour) not in hours:
            hours.append(int(hour))
        _NOON_STATE.parent.mkdir(parents=True, exist_ok=True)
        _NOON_STATE.write_text(_j.dumps({"date": today, "hours": sorted(hours),
                                         "ts": __import__("time").time()}, ensure_ascii=False),
                               encoding="utf-8")
    except Exception:
        pass


def _due_slots() -> list[int]:
    """Heute fällige, noch nicht versendete Slots (Versandstunde ≤ jetzt), aufsteigend."""
    now_h = datetime.now().hour
    return [h for h in _send_hours() if now_h >= h and not _slot_ran(h)]


def _noon_ran_today() -> bool:
    """Abwärtskompatibel: True, wenn HEUTE mindestens ein Slot versendet wurde."""
    from datetime import date as _d
    data = _load_noon_state()
    return data.get("date") == _d.today().isoformat() and bool(data.get("hours"))


def _mark_noon_ran() -> None:
    """Abwärtskompatibel: markiert den aktuellen Stunden-Slot als erledigt."""
    _mark_slot_ran(datetime.now().hour)


def status() -> dict:
    return {
        "has_lib": _HAS_DISCORD, "enabled": enabled(), "running": _started,
        "channel": _channel_id(), "send_hour": _send_hour(), "send_hours": _send_hours(),
        "needed": int(os.environ.get("DISCORD_APPROVALS_NEEDED", "1") or "1"),
        "auto_send": auto_send(),
        "reviews": rq.stats(),
    }


# ── Kanal-Diagnose (für „Unknown Channel"-Fälle) ───────────────────────────────

def _text_channels_info() -> list:
    """Alle Text-Kanäle, die der Bot SEHEN kann — mit Server, ID und Sende-Recht.
    Liest den (im Bot-Loop gefüllten) Cache; bei Aufruf außerhalb des Loops best-effort."""
    out: list = []
    if not _bot:
        return out
    try:
        guilds = list(getattr(_bot, "guilds", []) or [])
    except Exception:
        guilds = []
    for g in guilds:
        me = getattr(g, "me", None)
        for c in getattr(g, "text_channels", []):
            try:
                can = bool(c.permissions_for(me).send_messages) if me else False
            except Exception:
                can = False
            out.append({"guild": getattr(g, "name", "?"), "guild_id": getattr(g, "id", 0),
                        "channel": getattr(c, "name", "?"), "id": getattr(c, "id", 0),
                        "can_send": can})
    return out


async def _channels_coro() -> list:
    return _text_channels_info()


def channels(timeout: float = 5.0) -> list:
    """Erreichbare Text-Kanäle des Bots (für Diagnose/UI). [] wenn der Bot nicht läuft.
    Holt die Daten threadsicher aus dem Bot-Event-Loop."""
    if not (_HAS_DISCORD and _started and _loop and _bot):
        return []
    try:
        fut = asyncio.run_coroutine_threadsafe(_channels_coro(), _loop)
        return fut.result(timeout=timeout)
    except Exception:
        return _text_channels_info()


def _diagnose_channel() -> None:
    """Loggt beim Start klar, ob der konfigurierte Freigabe-Kanal erreichbar ist — und listet
    sonst die verfügbaren Kanäle samt IDs auf, damit Sir die richtige DISCORD_CHANNEL_ID setzen
    kann. Häufigste Ursache für „Unknown Channel": falsche ID ODER Bot nicht im Server."""
    try:
        cid = _channel_id()
        if not _bot or not list(getattr(_bot, "guilds", []) or []):
            logger.warn("Discord", "Bot ist in KEINEM Server. Lade ihn auf deinen Discord-Server "
                        "ein: Developer Portal → OAuth2 → URL Generator → Scope 'bot' + Rechte "
                        "'Send Messages' & 'Embed Links', URL öffnen, Server wählen.")
            return
        infos = _text_channels_info()
        found = next((i for i in infos if i["id"] == cid), None)
        if found and found["can_send"]:
            logger.success("Discord", f"Freigabe-Kanal OK: #{found['channel']} in "
                                      f"'{found['guild']}' (ID {cid}).")
            return
        if found and not found["can_send"]:
            logger.warn("Discord", f"Kanal #{found['channel']} gefunden, aber der Bot darf dort "
                        "NICHT senden. Im Kanal → Berechtigungen dem Bot 'Nachrichten senden' + "
                        "'Links einbetten' erlauben.")
            return
        # Konfigurierte ID in keinem erreichbaren Server gefunden → Alternativen zeigen.
        sendable = [i for i in infos if i["can_send"]]
        logger.warn("Discord", f"DISCORD_CHANNEL_ID={cid} ist in keinem erreichbaren Server. "
                    f"Bot ist in {len(list(_bot.guilds))} Server(n) — verfügbare Text-Kanäle:")
        for i in (sendable or infos)[:20]:
            flag = "✓ sendbar" if i["can_send"] else "✗ kein Senderecht"
            logger.warn("Discord", f"   {i['guild']} · #{i['channel']}  →  ID {i['id']}   ({flag})")
        if not infos:
            logger.warn("Discord", "   (Keine Text-Kanäle sichtbar — Bot-Rechte/Intents prüfen.)")
        logger.warn("Discord", "→ Eine dieser IDs als DISCORD_CHANNEL_ID in die .env eintragen, "
                    "dann JARVIS neu starten.")
    except Exception as e:
        logger.warn("Discord", f"Kanal-Diagnose fehlgeschlagen: {type(e).__name__}")


# ── E-Mail-Versand der freigegebenen Seiten (Standardbibliothek, threadsicher) ──

def link_is_live(url: str, timeout: int = 8) -> bool:
    """True, wenn die URL wirklich erreichbar ist (HTTP < 400). Verhindert, dass eine Mail
    mit totem Live-Link rausgeht. Leere/relative URLs gelten als nicht live."""
    url = (url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return False
    import urllib.request
    import urllib.error
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "Mozilla/5.0 JARVIS"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return getattr(r, "status", 200) < 400
    except urllib.error.HTTPError as e:
        return e.code < 400
    except Exception:
        return False


def _send_one_real(review: dict) -> tuple:
    """Schickt eine freigegebene Seite an den/die echten Empfänger. (ok, info).
    Bei einer Empfängerliste (Custom-Modus, 11+) geht das Angebot an JEDE Adresse."""
    import mailer
    import offer_mail
    # Link-Garantie: nur einen WIRKLICH erreichbaren Live-Link in die Mail nehmen — sonst
    # baut offer_mail die ehrliche Variante ohne (kaputten) Button.
    raw_link = (review.get("link") or "").strip()
    safe_link = raw_link if link_is_live(raw_link) else ""
    if raw_link and not safe_link:
        logger.warn("Discord", f"Live-Link nicht erreichbar ({raw_link[:80]}) — "
                               "Mail ohne Link-Button versendet.")
    preis = review.get("preis") or 0

    def _build_for(to: str):
        """Baut Betreff/Text/HTML mit dem für DIESE Adresse gültigen Abmelde-Link."""
        try:
            import email_suppress
            unsub = email_suppress.unsub_link(to)
        except Exception:
            unsub = ""
        return offer_mail.build(
            review.get("name", ""), safe_link, review.get("branche", ""),
            review.get("stadt", ""), review.get("ansprechpartner", ""),
            preis=preis, unsubscribe_url=unsub)

    recipients = [e.strip() for e in (review.get("recipients") or []) if "@" in (e or "")]
    if recipients:                                   # Custom-Modus: an alle senden
        ok_n, fail_n = 0, 0
        for to in recipients:
            betreff, text, html = _build_for(to)
            r = mailer.send_email(to, betreff, text, html=html, bypass_redirect=True)
            if r.get("ok"):
                ok_n += 1
            else:
                fail_n += 1
        return ok_n > 0, f"{ok_n}/{len(recipients)} gesendet" + (f", {fail_n} Fehler" if fail_n else "")

    to = (review.get("email") or "").strip()
    if "@" not in to:                                # Adresse fehlt → on-demand suchen
        try:
            import contact_finder
            res = contact_finder.find(review.get("name", ""), review.get("stadt", ""),
                                      review.get("branche", ""), review.get("link", ""))
            to = (res.get("email") or "").strip()
            if to:
                review["email"] = to
        except Exception:
            pass
    if "@" not in to:
        return False, "keine Kundenadresse gefunden"
    # bypass_redirect=True: bewusst an den echten Kunden (Voting ist die Freigabe).
    betreff, text, html = _build_for(to)
    r = mailer.send_email(to, betreff, text, html=html, bypass_redirect=True)
    # WICHTIG: 'fehler' zuerst — mailer.py setzt 'status' bei JEDEM Fehlerfall auf den
    # Literal-String "fehler" (truthy!), darum würde "status or fehler" den echten Grund
    # (z.B. "Stundenlimit erreicht") nie zurückgeben, sondern immer nur das Wort "fehler".
    return bool(r.get("ok")), (r.get("fehler") or r.get("status") or "")


import threading as _threading
_send_lock = _threading.Lock()


def _archive_lead_after_send(review: dict) -> None:
    """Nach erfolgreichem Kundenversand: Lead archivieren (verhindert Neu-Bau derselben Seite)
    + db_websites als 'E-Mail versendet' markieren."""
    name  = (review.get("name") or "").strip()
    stadt = (review.get("stadt") or "").strip()
    if not name:
        return
    # Lead in db_evaluated archivieren
    try:
        import db_evaluated
        from leadkey import lead_key as _lk
        lk = _lk(name, stadt)
        for lead in db_evaluated.get_all(limit=5000):
            if (lead.get("lead_key") == lk or
                    (lead.get("name") or "").strip().lower() == name.lower()):
                db_evaluated.archive_lead(int(lead["id"]), "E-Mail an Kunden versandt — kein Neubau")
                logger.info("Discord", f"Lead archiviert nach Versand: {name}")
                break
    except Exception as e:
        logger.warn("Discord", f"Lead-Archivierung fehlgeschlagen: {type(e).__name__}")
    # Website-Zeile in db_websites als gesendet markieren
    try:
        import db_websites
        import time as _t
        folder = (review.get("folder") or "").strip()
        if folder:
            row = db_websites.get_by_folder(folder)
            if row:
                db_websites.update(row["job_id"],
                                   email_sent=1,
                                   email_sent_ts=_t.time(),
                                   step="✅ E-Mail an Kunden versandt")
    except Exception as e:
        logger.warn("Discord", f"Website-Versand-Markierung: {type(e).__name__}")


def _schedule_premium_after_send(reviews: list) -> None:
    """Stößt für jede frisch verschickte Seite EINMALIG den 1A-Premium-Ausbau an (Master-Prompt,
    alle Bilder + Firmeninfos) + Re-Deploy. Läuft SEQUENZIELL in einem Hintergrund-Thread (teilt
    sich den globalen Makeover-Lock) und blockiert den Versand nie. Idempotent je Seite."""
    import os
    items = [((r.get("folder") or "").strip(), (r.get("name") or "").strip())
             for r in reviews if (r.get("folder") or "").strip()]
    if not items:
        return

    def _worker():
        import time as _t
        try:
            import website_builder as wb
            import overnight_makeover as om
        except Exception:
            return
        for folder, nm in items:
            try:
                if not os.path.isdir(folder) or om.premium_upgraded(folder):
                    continue
                logger.info("Discord", f"1A-Premium-Ausbau nach Versand: {nm}")
                jid = wb.premium_upgrade_existing(folder, nm)
                for _ in range(1800):            # bis ~1 h auf Abschluss warten (Gate seriell)
                    j = wb.get(jid) or {}
                    if j.get("status") in ("done", "error"):
                        break
                    _t.sleep(2)
            except Exception as e:
                logger.warn("Discord", f"Premium-Ausbau nach Versand übersprungen ({nm}): {type(e).__name__}")

    _threading.Thread(target=_worker, daemon=True, name="premium-after-send").start()


def enqueue_unsent_websites() -> int:
    """Auto-Send-Abgleich: bereits gebaute, live, aber noch NICHT versendete Seiten ohne
    offenen Review-Eintrag nachträglich in die Versand-Queue holen — z.B. Seiten, die früher
    in die Vorschau-Mail fielen, weil Discord gerade offline war, oder Altbestand aus der Zeit
    vor Auto-Send. Respektiert strikt: bereits Versendetes (SENT / email_sent) und 👎-Vetos
    (REJECTED) werden NIE erneut eingereiht. Gibt die Anzahl neu eingereihter Seiten zurück.
    Ohne Auto-Send: No-op."""
    if not auto_send():
        return 0
    try:
        import db_websites
        import overnight_makeover as om
    except Exception:
        return 0
    added = 0
    try:
        rows = db_websites.get_all()
    except Exception:
        return 0
    for w in rows:
        try:
            if not w.get("live") or w.get("email_sent"):
                continue                              # nicht live oder schon versendet
            folder = (w.get("folder") or "").strip()
            name   = (w.get("name") or "").strip()
            stadt  = (w.get("stadt") or "").strip()
            if not folder or not name or not om.review_ready(folder):
                continue                              # Pflicht-Stufen noch nicht durch
            prev = rq.latest_for_site(name, stadt)
            if prev and prev.get("status") in (rq.SENT, rq.REJECTED, rq.PENDING, rq.APPROVED):
                continue                              # versendet / vetoed / schon in der Queue
            branche = w.get("branche", "")
            ap      = w.get("ansprechpartner", "")
            link    = (w.get("live_url") or "").strip()
            email   = (w.get("kontakt_email") or "").strip()
            betreff = text = ""
            try:
                import offer_mail
                betreff, text, _ = offer_mail.build(name, link, branche, stadt, ap)
            except Exception:
                pass
            r = submit_for_review(name, stadt, branche, link, email, ap, folder,
                                  email_text=text, email_subject=betreff)
            if r:
                added += 1
        except Exception as e:
            logger.warn("Discord", f"Nachqueue übersprungen ({w.get('name','?')}): {type(e).__name__}")
    if added:
        logger.info("Discord", f"Auto-Send: {added} bereits gebaute Seite(n) nachträglich "
                               "in die Versand-Queue geholt.")
    return added


def prepare_queue_for_auto_send() -> dict:
    """Bringt die Queue im Auto-Send-Modus auf Stand: offene (pending) Reviews freigeben +
    bereits gebaute, noch nicht versendete Seiten nachqueuen. So gehen auch der Altbestand
    und Seiten ohne Review-Eintrag beim nächsten Versand mit raus. Ohne Auto-Send: No-op."""
    if not auto_send():
        return {"promoted": 0, "enqueued": 0}
    promoted = 0
    try:
        promoted = rq.promote_pending()
        if promoted:
            logger.info("Discord", f"Auto-Send: {promoted} offene Seite(n) freigegeben "
                                   "(gehen beim nächsten Versand raus).")
    except Exception as e:
        logger.warn("Discord", f"Pending-Freigabe fehlgeschlagen: {type(e).__name__}")
    enqueued = enqueue_unsent_websites()
    return {"promoted": promoted, "enqueued": enqueued}


def send_approved_now() -> dict:
    """Versendet sofort alle freigegebenen, noch nicht gesendeten Seiten. Gibt eine
    Zusammenfassung zurück. (Wird vom 12-Uhr-Scheduler und manuell genutzt.)
    Ein Lock verhindert, dass 12-Uhr-Lauf UND manueller Aufruf gleichzeitig dieselben
    Reviews greifen und doppelt versenden."""
    if not _send_lock.acquire(blocking=False):
        return {"sent": 0, "failed": 0, "lines": ["Versand läuft bereits."], "total": 0}
    try:
        # Auto-Send: unmittelbar vor dem Versand die Queue vervollständigen — offene Seiten
        # freigeben + bereits gebaute, noch nicht versendete Seiten nachholen. So geht auch
        # der Altbestand mit raus, egal ob 12-Uhr-Lauf oder manueller Versand.
        try:
            prepare_queue_for_auto_send()
        except Exception as e:
            logger.warn("Discord", f"Queue-Vorbereitung übersprungen: {type(e).__name__}")
        todo = rq.approved_unsent()
        sent, failed, lines = 0, 0, []
        sent_reviews = []
        sent_items, failed_items = [], []
        for r in todo:
            # Pro Review erneut prüfen, ob er noch sendebereit ist (nicht zwischenzeitlich gesendet).
            cur = rq.get(r["id"])
            if not cur or cur.get("status") == rq.SENT or cur.get("sent_ts"):
                continue
            ok, info = _send_one_real(r)
            # Ratenlimit-Fehlschläge NICHT als SKIPPED verbuchen (mark_sent setzt sonst
            # dauerhaft status=SKIPPED — approved_unsent() sieht den Review dann NIE wieder,
            # der Kunde bekäme seine Seite also gar nicht mehr). Bleibt der Review APPROVED,
            # holt ihn der Nachzügler-Loop (_noon_watchdog_loop) automatisch nach, sobald im
            # rollierenden Stundenfenster (mailer._rate_ok) wieder Kapazität frei ist.
            rate_limited = (not ok) and "Stundenlimit" in (info or "")
            if not rate_limited:
                rq.mark_sent(r["id"], ok, info)
            # Empfänger-Anzeige: Einzeladresse oder „N Empfänger" im Custom-Modus.
            rec   = r.get("recipients") or []
            to_disp = (f"{len(rec)} Empfänger" if rec else (r.get("email") or "—"))
            item = {"name": r.get("name", "?"), "link": (r.get("link") or "").strip(),
                    "email": to_disp, "branche": r.get("branche", ""),
                    "stadt": r.get("stadt", ""), "info": info}
            if ok:
                sent += 1
                lines.append(f"✅ {item['name']} → {to_disp}")
                _archive_lead_after_send(r)          # Lead archivieren → kein Neubau
                sent_reviews.append(r)
                sent_items.append(item)
            else:
                failed += 1
                tag = " (Nachzügler-Versand holt das automatisch nach)" if rate_limited else ""
                lines.append(f"⚠️ {item['name']}: {info}{tag}")
                failed_items.append(item)
        logger.info("Discord", f"{_send_hour()}-Uhr-Versand: {sent} gesendet, {failed} übersprungen")
        # Verschickte Seiten jetzt im Hintergrund auf 1A-Premium-Standard heben (Master-Prompt).
        if sent_reviews:
            _schedule_premium_after_send(sent_reviews)
        return {"sent": sent, "failed": failed, "lines": lines, "total": len(todo),
                "sent_items": sent_items, "failed_items": failed_items}
    finally:
        _send_lock.release()


# ─────────────────────────────────────────────────────────────────────────────
# Alles ab hier braucht discord.py — nur definieren, wenn vorhanden.
# ─────────────────────────────────────────────────────────────────────────────
if _HAS_DISCORD:

    _STATUS_COLOR = {
        rq.PENDING:  0x4a6fa5,
        rq.APPROVED: 0x2ecc71,
        rq.REJECTED: 0xe74c3c,
        rq.SENT:     0x9b59b6,
        rq.SKIPPED:  0x95a5a6,
    }
    _STATUS_LABEL = {
        rq.PENDING:  "🕓 Abstimmung läuft",
        rq.APPROVED: "✅ Freigegeben",
        rq.REJECTED: "❌ Abgelehnt",
        rq.SENT:     "📨 Versendet",
        rq.SKIPPED:  "⏭️ Übersprungen",
    }

    def _embed(r: dict) -> "discord.Embed":
        st = r.get("status", rq.PENDING)
        needed = int(os.environ.get("DISCORD_APPROVALS_NEEDED", "1") or "1")
        link   = r.get("link") or ""

        # Titel: Name + Live-Link direkt anklickbar
        title_url = link if link.startswith("http") else None
        e = discord.Embed(
            title=f"🌐 {r.get('name','Webseite')} — Makeover fertig",
            url=title_url,
            color=_STATUS_COLOR.get(st, 0x4a6fa5),
        )

        # Zeile 1: Betrieb + Link
        meta = " · ".join(x for x in [r.get("branche", ""), r.get("stadt", "")] if x)
        link_field = f"[{link}]({link})" if link.startswith("http") else (link or "—")
        e.add_field(name="🏢 Betrieb", value=meta or "—", inline=True)
        e.add_field(name="🔗 Live-Link", value=link_field, inline=True)

        # Zeile 2: Empfänger
        rec = r.get("recipients") or []
        if rec:
            empf = f"📋 {len(rec)} Empfänger" + (f"\n`{rec[0]}`" if rec else "")
        else:
            empf = f"`{r.get('email')}`" if r.get("email") else "⚠️ wird vor Versand gesucht"
        e.add_field(name="📬 Empfänger", value=empf, inline=False)

        # E-Mail-Betreff (wenn vorhanden)
        subj = (r.get("email_subject") or "").strip()
        if subj:
            e.add_field(name="✉️ Betreff", value=f"**{subj[:150]}**", inline=False)

        # E-Mail-Text-Vorschau — der eigentliche Angebotstext (max. 900 Zeichen)
        email_txt = (r.get("email_text") or "").strip()
        if email_txt:
            preview = email_txt[:900] + ("…" if len(email_txt) > 900 else "")
            e.add_field(name="📝 Angebots-Mail (Vorschau)", value=f"```{preview}```",
                        inline=False)

        # Status + Stimmen
        e.add_field(
            name="🗳️ Abstimmung",
            value=f"{_STATUS_LABEL.get(st, st)}  ·  👍 {len(r.get('votes_up', []))}/{needed}"
                  f"  👎 {len(r.get('votes_down', []))}",
            inline=False)

        auto = auto_send()
        if st == rq.APPROVED:
            if auto:
                e.set_footer(text=f"✅ Automatisch freigegeben — Versand um {_send_hours_label()} an den "
                                  "Kunden. 👎 stoppt den Versand.")
            else:
                e.set_footer(text=f"✅ Freigegeben — Versand heute um {_send_hours_label()} an den Kunden.")
        elif st == rq.REJECTED:
            e.set_footer(text="❌ Ein 👎 ist ein Veto — diese Seite wird nicht versendet.")
        elif st == rq.SENT:
            e.set_footer(text="📨 Versendet.")
        elif auto:
            e.set_footer(text=f"⚙️ Auto-Send aktiv — geht um {_send_hours_label()} automatisch raus. 👎 stoppt sie.")
        else:
            e.set_footer(text=f"👍 {needed}× Daumen hoch (ohne 👎) gibt die Seite frei · Versand um {_send_hours_label()}")
        return e

    class VoteButton(discord.ui.DynamicItem[discord.ui.Button],
                     template=r"jvote:(?P<action>up|down):(?P<rid>[0-9a-f]+)"):
        """Persistenter Vote-Button (überlebt Neustarts: rid steckt in der custom_id)."""
        def __init__(self, action: str, rid: str, up: int = 0, down: int = 0):
            self.action = action
            self.rid = rid
            is_up = action == "up"
            super().__init__(discord.ui.Button(
                label=f"{'👍' if is_up else '👎'} {up if is_up else down}",
                style=discord.ButtonStyle.success if is_up else discord.ButtonStyle.danger,
                custom_id=f"jvote:{action}:{rid}"))

        @classmethod
        async def from_custom_id(cls, interaction, item, match, /):
            return cls(match["action"], match["rid"])

        async def callback(self, interaction: "discord.Interaction"):
            await _handle_vote(interaction, self.rid, self.action == "up")

    def _view(r: dict) -> "discord.ui.View":
        v = discord.ui.View(timeout=None)
        up, down = len(r.get("votes_up", [])), len(r.get("votes_down", []))
        v.add_item(VoteButton("up", r["id"], up, down))
        v.add_item(VoteButton("down", r["id"], up, down))
        return v

    async def _handle_vote(interaction: "discord.Interaction", rid: str, up: bool):
        r = rq.vote(rid, interaction.user.id, up, _owners())
        if not r:
            await interaction.response.send_message("Review nicht gefunden.", ephemeral=True)
            return
        if r.get("error") == "not_owner":
            await interaction.response.send_message(
                "Du bist nicht stimmberechtigt (DISCORD_OWNER_IDS).", ephemeral=True)
            return
        try:
            await interaction.response.edit_message(embed=_embed(r), view=_view(r))
        except Exception:
            try:
                await interaction.response.defer()
            except Exception:
                pass
        if r.get("status") == rq.APPROVED:
            logger.success("Discord", f"Freigegeben: {r.get('name','?')} (Versand {_send_hour()}:00)")

    async def _post(review: dict):
        ch = _bot.get_channel(_channel_id()) if _bot else None
        if ch is None and _bot is not None:
            try:
                ch = await _bot.fetch_channel(_channel_id())
            except Exception as e:
                logger.warn("Discord", f"Kanal nicht erreichbar: {type(e).__name__}")
                return
        try:
            msg = await ch.send(embed=_embed(review), view=_view(review))
            rq.set_message(review["id"], msg.id, ch.id)
            logger.info("Discord", f"Review gepostet: {review.get('name','?')}")
        except Exception as e:
            logger.warn("Discord", f"Posten fehlgeschlagen: {type(e).__name__}")

    async def _send_startup_embed():
        """Postet beim Bot-Start eine Statusnachricht in den Kanal."""
        try:
            cid = _channel_id()
            ch  = _bot.get_channel(cid) if _bot else None
            if ch is None and _bot is not None:
                try:
                    ch = await _bot.fetch_channel(cid)
                except Exception as fetch_err:
                    logger.warn("Discord", f"Kanal {cid} nicht erreichbar: {fetch_err}")
                    return
            if ch is None:
                logger.warn("Discord", f"Kanal {cid} nicht gefunden — Startnachricht übersprungen")
                return
            # Infos zusammenstellen
            from datetime import datetime as _dt
            ts = _dt.now().strftime("%d.%m.%Y %H:%M")
            # Heute gebaute Seiten
            try:
                import auto_builder as _ab
                state = _ab.status()
                today = state.get("today_count", 0)
                limit = state.get("daily_limit", 5)
                builder_info = f"{today}/{limit} Seiten heute gebaut"
                is_running   = _ab.is_running()
            except Exception:
                builder_info = "–"
                is_running   = False
            # Webseiten-Gesamt
            try:
                import db_websites as _dw
                sites    = _dw.get_all()
                n_total  = len(sites)
                n_live   = sum(1 for s in sites if s.get("live"))
            except Exception:
                n_total = n_live = 0
            # Pending Reviews
            try:
                pending = len(rq.pending())
            except Exception:
                pending = 0

            e = discord.Embed(
                title="⬡ JARVIS LeadHunter — System gestartet",
                description=f"🕐 {ts}",
                color=0x00d4ff,
            )
            e.add_field(name="🌐 Webseiten",
                        value=f"{n_total} gesamt · **{n_live} live**", inline=True)
            e.add_field(name="⚡ Auto-Builder",
                        value=f"{'✅ Läuft' if is_running else '⏸️ Bereit'} · {builder_info}", inline=True)
            e.add_field(name="🗳️ Offene Reviews",
                        value=str(pending) if pending else "Keine", inline=True)
            foot = ("JARVIS startet automatisch bei 0 Uhr neu · "
                    + (f"Auto-Send AN — Versand {_send_hours_label()} ohne Bestätigung"
                       if auto_send() else "Abstimmung: 1× 👍 = Freigabe"))
            e.set_footer(text=foot)
            await ch.send(embed=e)
        except Exception as ex:
            logger.warn("Discord", f"Startnachricht fehlgeschlagen: {type(ex).__name__}")

    async def _post_announcement(title: str, description: str, color: int = 0x00d4ff):
        """Postet eine einfache Status-/Abschlussnachricht in den Kanal (kein Review/Voting)."""
        try:
            cid = _channel_id()
            ch  = _bot.get_channel(cid) if _bot else None
            if ch is None and _bot is not None:
                try:
                    ch = await _bot.fetch_channel(cid)
                except Exception:
                    return
            if ch is None:
                return
            e = discord.Embed(title=title, description=description or "", color=color)
            e.set_footer(text="JARVIS LeadHunter")
            await ch.send(embed=e)
        except Exception as ex:
            logger.warn("Discord", f"Announcement fehlgeschlagen: {type(ex).__name__}")

    async def _post_report_embed(title: str, description: str, fields: list, color: int):
        """Postet einen Embed MIT Feldern (z.B. Top-Lead-Report). Truncation auf die
        harten Discord-Limits (title 256, description 4096, field-name 256, value 1024,
        max 25 Felder). Best-effort — wirft nie."""
        try:
            cid = _channel_id()
            ch  = _bot.get_channel(cid) if _bot else None
            if ch is None and _bot is not None:
                try:
                    ch = await _bot.fetch_channel(cid)
                except Exception:
                    return
            if ch is None:
                return
            e = discord.Embed(title=(title or "")[:256],
                              description=(description or "")[:4096], color=color)
            for nm, val in (fields or [])[:25]:
                e.add_field(name=(nm or "—")[:256], value=(val or "—")[:1024], inline=False)
            e.set_footer(text="JARVIS LeadHunter")
            await ch.send(embed=e)
        except Exception as ex:
            logger.warn("Discord", f"Report fehlgeschlagen: {type(ex).__name__}")


    class _Client(discord.Client):
        def __init__(self):
            super().__init__(intents=discord.Intents.default())

        async def setup_hook(self):
            self.add_dynamic_items(VoteButton)        # Buttons nach Neustart reaktivieren
            _noon_loop.start()

        async def on_ready(self):
            logger.success("Discord", f"Bot online als {self.user} — Kanal {_channel_id()}")
            # Kurz warten bis Guild-Cache vollständig geladen ist,
            # sonst gibt get_channel() None zurück obwohl der Kanal existiert.
            await asyncio.sleep(2)
            _diagnose_channel()                       # klare Meldung bei „Unknown Channel"
            await _send_startup_embed()
            # Auto-Send: Altbestand einmalig aufbereiten (offene freigeben + gebaute, noch
            # nicht versendete Seiten nachqueuen), damit auch sie beim Versand rausgehen.
            try:
                res = await asyncio.to_thread(prepare_queue_for_auto_send)
                if res.get("promoted") or res.get("enqueued"):
                    logger.info("Discord", f"Auto-Send-Aufbereitung: {res.get('promoted',0)} "
                                           f"freigegeben, {res.get('enqueued',0)} nachgequeued.")
            except Exception as ex:
                logger.warn("Discord", f"Auto-Send-Aufbereitung fehlgeschlagen: {type(ex).__name__}")

    def _noon_report_embed(res: dict) -> "discord.Embed":
        """Schöner Mittags-Report: pro versendeter Seite Name + klickbarer Live-Link +
        Empfänger — man sieht direkt, was an Kunden rausging."""
        sent  = res.get("sent", 0)
        items = res.get("sent_items", [])
        fails = res.get("failed_items", [])
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%d.%m.%Y · %H:%M")
        color = 0x2ecc71 if sent else 0x95a5a6
        e = discord.Embed(
            title=f"📨 {_dt.now().hour}-Uhr-Versand — {sent} Webseite{'n' if sent != 1 else ''} an Kunden verschickt",
            description=(f"🕐 {ts}\nDiese frisch freigegebenen Webseiten sind heute "
                         f"an die echten Kunden rausgegangen:" if sent
                         else f"🕐 {ts}\nKeine neuen Freigaben zum Versand."),
            color=color)
        for i, it in enumerate(items[:20], 1):
            link = it.get("link", "")
            name = it.get("name", "?")
            head = f"[{name}]({link})" if link.startswith("http") else name
            meta = " · ".join(x for x in (it.get("branche"), it.get("stadt")) if x)
            val  = f"📬 verschickt an `{it.get('email','—')}`"
            if link.startswith("http"):
                val += f"\n🔗 {link}"
            if meta:
                val = f"{meta}\n{val}"
            e.add_field(name=f"✅ {i}. {head}", value=val, inline=False)
        if len(items) > 20:
            e.add_field(name="…", value=f"und {len(items) - 20} weitere.", inline=False)
        if fails:
            fl = "\n".join(f"• {f.get('name','?')}: {f.get('info','—')}" for f in fails[:10])
            e.add_field(name=f"⚠️ {len(fails)} offen / übersprungen", value=fl, inline=False)
        foot = ("JARVIS LeadHunter · Auto-Send → Versand automatisch an den Kunden"
                if auto_send() else f"JARVIS LeadHunter · Freigabe per 👍 → Versand {_send_hours_label()} an den Kunden")
        e.set_footer(text=foot)
        return e

    async def _post_noon_report(res: dict) -> None:
        """Postet den Tagesversand-Report in den Discord-Kanal (best-effort, wirft nie)."""
        try:
            ch = _bot.get_channel(_channel_id())
            if ch is None and _bot is not None:
                ch = await _bot.fetch_channel(_channel_id())
            # Nur posten, wenn es etwas zu berichten gibt (versendet ODER offene Freigaben).
            if ch and (res.get("sent") or res.get("total")):
                await ch.send(embed=_noon_report_embed(res))
        except Exception as ex:
            logger.warn("Discord", f"12-Uhr-Report fehlgeschlagen: {type(ex).__name__}")

    # Mehrere Versand-Zeitpunkte pro Tag (discord.py tasks.loop akzeptiert eine Liste von
    # times). Feuert an jedem konfigurierten Slot; welcher gemeint ist, ergibt sich aus der
    # aktuellen Stunde.
    _SEND_TIMES = [dtime(hour=h, minute=0) for h in _send_hours()]

    @tasks.loop(time=_SEND_TIMES)
    async def _noon_loop():
        slot = datetime.now().hour
        # Slot-Latch: pro Stunde nur EINMAL (verhindert Doppel-Post bei Neustart zur Slot-Zeit).
        if _slot_ran(slot):
            logger.info("Discord", f"{slot}-Uhr-Report heute bereits gepostet — übersprungen.")
            return
        # WICHTIG: der ganze Body ist gekapselt. Eine unbehandelte Exception würde sonst
        # die tasks.loop DAUERHAFT stoppen (Grund, warum der Versand früher „nach 2 Tagen"
        # aufhörte). Latch erst NACH dem Versand — ein Crash darf den Slot nicht verbrennen.
        try:
            res = await asyncio.to_thread(send_approved_now)
            _mark_slot_ran(slot)
            await _post_noon_report(res)
        except Exception as ex:
            import traceback
            logger.error("Discord", f"{slot}-Uhr-Versand-Fehler: {type(ex).__name__}: {str(ex)[:160]}")
            logger.debug("Discord", "Traceback: "
                         + traceback.format_exc().strip().replace(chr(10), " | ")[-400:])

    @_noon_loop.before_loop
    async def _before_noon_loop():
        # Bis der Bot verbunden ist warten — sonst läuft die Loop evtl. ohne Kanal-Cache.
        try:
            await _bot.wait_until_ready()
        except Exception:
            pass

    @_noon_loop.error
    async def _noon_loop_error(exc):
        # Letzte Absicherung: bricht die Loop doch mit einem Fehler ab → loggen UND neu starten,
        # damit der Tagesversand nicht für immer stehenbleibt.
        logger.error("Discord", f"12-Uhr-Loop abgebrochen ({type(exc).__name__}) — starte neu.")
        try:
            _noon_loop.restart()
        except Exception:
            pass

    # Nachzügler-Versand: wie oft (Sekunden) nach dem 12-Uhr-Lauf erneut geprüft wird, ob noch
    # APPROVED-Reviews offen sind (z.B. durch JARVIS_EMAIL_RATE zurückgehalten) — die rollierende
    # Stunde in mailer._rate_ok() gibt zwischendurch wieder Kapazität frei.
    _RETRY_INTERVAL = int(os.environ.get("JARVIS_EMAIL_RETRY_INTERVAL", "900") or "900")
    _last_retry_ts = [0.0]

    def _noon_watchdog_loop():
        """Unabhängiger Sicherheits-Auslöser für JEDEN Versand-Slot: prüft jede Minute, ob ein
        konfigurierter Slot erreicht und heute noch nicht versendet wurde — und stößt den Versand
        dann an, SELBST wenn der discord.py-Task-Loop gestorben oder der Bot getrennt ist. Ein
        verpasster Slot (z.B. App startet 14:25, Slot 12 und 15 wären fällig) wird beim nächsten
        Tick nachgeholt. Der Versand (Mailer) hängt nicht an Discord; der Report wird best-effort
        nachgereicht. Zwischen den Slots holt derselbe Loop periodisch noch offene
        (ratenlimitierte) Reviews nach — sonst blieben sie bis zum nächsten Slot liegen."""
        import time as _t
        _t.sleep(90)                                  # App-/Bot-Start abwarten
        while True:
            try:
                due = _due_slots() if enabled() else []
                if due:
                    slot = due[-1]                    # jüngster fälliger Slot bestimmt das Log
                    logger.info("Discord", f"{slot}-Uhr-Versand (Sicherheits-Watchdog) — "
                                           "hole nach (Task-Loop hat nicht ausgelöst).")
                    res = send_approved_now()
                    for h in due:                     # alle fälligen Slots als erledigt markieren
                        _mark_slot_ran(h)
                    try:
                        if _loop is not None and (res.get("sent") or res.get("total")):
                            asyncio.run_coroutine_threadsafe(_post_noon_report(res), _loop)
                    except Exception:
                        pass
                elif enabled():
                    now = _t.time()
                    if now - _last_retry_ts[0] >= _RETRY_INTERVAL and rq.approved_unsent():
                        _last_retry_ts[0] = now
                        logger.info("Discord", "Nachzügler-Versand: hole zuvor ratenlimitierte "
                                               "Mails nach.")
                        res = send_approved_now()
                        if res.get("sent"):
                            try:
                                notify(f"📨 Nachzügler-Versand — {res['sent']} weitere "
                                      f"Webseite(n) verschickt",
                                      "Waren zuvor durch das Stunden-Sendelimit "
                                      "(JARVIS_EMAIL_RATE) zurückgehalten worden.", 0x00d4ff)
                            except Exception:
                                pass
            except Exception as e:
                logger.warn("Discord", f"Noon-Watchdog-Fehler: {type(e).__name__}")
            _t.sleep(60)


# ── Öffentliche API (vom Auto-Builder / app.py genutzt) ────────────────────────

def submit_for_review(name: str, stadt: str, branche: str, link: str,
                      email: str = "", ansprechpartner: str = "", folder: str = "",
                      recipients: "list | None" = None,
                      email_text: str = "", email_subject: str = "", preis: int = 0) -> "dict | None":
    """Reiht eine fertige Seite in die Versand-Queue ein und postet sie (falls der Bot läuft)
    best-effort in den Discord-Kanal.

    WICHTIG: Der Review wird IMMER in die lokale Queue gelegt — auch wenn der Discord-Bot
    gerade nicht verbunden ist. So geht die Seite beim Tagesversand zuverlässig raus, selbst
    wenn Discord kurz weg war (früher fiel sie in diesem Fall still durch → nichts wurde
    versendet). Der Discord-Post ist nur die Sichtbarkeit obendrauf.

    Im Auto-Send-Modus (JARVIS_AUTO_SEND, Default AN) wird die Seite direkt APPROVED angelegt
    und geht ohne 👍-Bestätigung beim Tagesversand an den Kunden.

    Gibt den Review zurück, oder None nur wenn weder Auto-Send noch Discord aktiv sind
    (dann greift beim Aufrufer die Vorschau-Mail an Bastian).
    recipients: optionale Empfängerliste (Custom-Modus, 11+).
    email_text: Plaintext der Angebots-Mail (wird im Embed angezeigt).
    email_subject: Betreffzeile der Angebots-Mail.
    preis: Angebotspreis (Tier) — 0 = fairer Standardpreis."""
    auto = auto_send()
    if not auto and not enabled():
        return None                                  # kein Auto-Send + kein Bot → Fallback-Mail
    status = rq.APPROVED if auto else rq.PENDING
    review = rq.add(name, stadt, branche, link, email, ansprechpartner, folder, recipients,
                    email_text=email_text, preis=preis, status=status)
    if email_subject:
        try:
            rq.update(review["id"], email_subject=email_subject)
            review["email_subject"] = email_subject
        except Exception:
            pass
    # Discord-Post best-effort — Fehlen des Bots verhindert NICHT das spätere Versenden.
    if enabled() and _started and _loop is not None:
        try:
            asyncio.run_coroutine_threadsafe(_post(review), _loop)
        except Exception as e:
            logger.warn("Discord", f"Review-Post nicht zustellbar: {type(e).__name__}")
    elif auto:
        logger.info("Discord", f"Auto-Send: '{name}' in Versand-Queue "
                               f"(Discord offline — Post übersprungen, Versand läuft trotzdem).")
    return review


def notify(title: str, description: str = "", color: int = 0x00d4ff) -> bool:
    """Postet eine einfache Status-/Abschlussnachricht in den Discord-Kanal (KEIN Voting-Review).
    Für z.B. die Verabschiedung, wenn der Night-Builder alle Seiten fertig makeovert hat.
    Gibt True zurück, wenn die Nachricht eingereiht wurde."""
    if not enabled() or not _started or _loop is None:
        return False
    try:
        asyncio.run_coroutine_threadsafe(_post_announcement(title, description, color), _loop)
        return True
    except Exception as e:
        logger.warn("Discord", f"Notify nicht zustellbar: {type(e).__name__}")
        return False


def post_report(title: str, description: str = "",
                fields: "list | None" = None, color: int = 0x00d4ff) -> bool:
    """Postet einen Embed MIT Feldern in den Discord-Kanal (z.B. der stündliche Top-Lead-Report
    aus lead_collector). `fields` ist eine Liste von (name, value)-Tupeln. Thread-sicher aus
    jedem Hintergrund-Thread aufrufbar; best-effort — Discord offline => False, wirft nie.
    Gibt True zurück, wenn die Nachricht eingereiht wurde."""
    if not enabled() or not _started or _loop is None:
        return False
    try:
        asyncio.run_coroutine_threadsafe(
            _post_report_embed(title, description, list(fields or []), color), _loop)
        return True
    except Exception as e:
        logger.warn("Discord", f"Report nicht zustellbar: {type(e).__name__}")
        return False


def start() -> dict:
    """Startet den Bot in einem Hintergrund-Thread mit eigenem Event-Loop."""
    global _started, _loop, _bot
    if not enabled():
        return {"ok": False, "reason": "discord nicht konfiguriert (Token/Kanal/Library fehlt)"}
    with _lock:
        if _started:
            return {"ok": True, "already": True}
        _started = True

    def _run():
        global _loop, _bot
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _loop = loop
        _bot = _Client()
        try:
            loop.run_until_complete(_bot.start(_token()))
        except Exception as e:
            logger.error("Discord", f"Bot gestoppt: {type(e).__name__}")
        finally:
            with _lock:
                globals()["_started"] = False

    threading.Thread(target=_run, name="DiscordBot", daemon=True).start()
    # Unabhängiger Sicherheits-Watchdog für den Tagesversand (überlebt ein Sterben des
    # discord.py-Task-Loops bzw. eine Bot-Trennung).
    try:
        threading.Thread(target=_noon_watchdog_loop, name="NoonWatchdog", daemon=True).start()
    except Exception as e:
        logger.warn("Discord", f"Noon-Watchdog nicht gestartet: {type(e).__name__}")
    logger.info("Discord", "Freigabe-Bot startet… (12-Uhr-Versand mit Watchdog abgesichert)")
    return {"ok": True}
