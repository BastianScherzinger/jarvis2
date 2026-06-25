"""
discord_bot.py — Freigabe-Bot mit Voting-Gate vor dem Kundenversand.

Ablauf:
  1. Der Auto-Builder baut + verbessert eine Webseite und ruft `submit_for_review(...)`.
  2. Der Bot postet sie in den Discord-Kanal (Link + Details) mit zwei Buttons:
     👍 (Daumen hoch) / 👎 (Daumen runter).
  3. Erreichen die 👍 die Schwelle (DISCORD_APPROVALS_NEEDED, Default 2) ohne ein
     einziges 👎-Veto, gilt die Seite als FREIGEGEBEN.
  4. Täglich um DISCORD_SEND_HOUR (Default 12 Uhr) gehen alle freigegebenen Seiten an
     die ECHTE Kundenadresse (umgeht bewusst JARVIS_EMAIL_REDIRECT — das Voting ist
     die Sicherung).

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


def _send_hour() -> int:
    try:
        return max(0, min(23, int(os.environ.get("DISCORD_SEND_HOUR", "12") or "12")))
    except ValueError:
        return 12


def enabled() -> bool:
    """True nur, wenn discord.py vorhanden UND Token + Kanal konfiguriert sind."""
    return _HAS_DISCORD and bool(_token()) and _channel_id() > 0


def status() -> dict:
    return {
        "has_lib": _HAS_DISCORD, "enabled": enabled(), "running": _started,
        "channel": _channel_id(), "send_hour": _send_hour(),
        "needed": int(os.environ.get("DISCORD_APPROVALS_NEEDED", "2") or "2"),
        "reviews": rq.stats(),
    }


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
    return bool(r.get("ok")), (r.get("status") or r.get("fehler") or "")


import threading as _threading
_send_lock = _threading.Lock()


def send_approved_now() -> dict:
    """Versendet sofort alle freigegebenen, noch nicht gesendeten Seiten. Gibt eine
    Zusammenfassung zurück. (Wird vom 12-Uhr-Scheduler und manuell genutzt.)
    Ein Lock verhindert, dass 12-Uhr-Lauf UND manueller Aufruf gleichzeitig dieselben
    Reviews greifen und doppelt versenden."""
    if not _send_lock.acquire(blocking=False):
        return {"sent": 0, "failed": 0, "lines": ["Versand läuft bereits."], "total": 0}
    try:
        todo = rq.approved_unsent()
        sent, failed, lines = 0, 0, []
        for r in todo:
            # Pro Review erneut prüfen, ob er noch sendebereit ist (nicht zwischenzeitlich gesendet).
            cur = rq.get(r["id"])
            if not cur or cur.get("status") == rq.SENT or cur.get("sent_ts"):
                continue
            ok, info = _send_one_real(r)
            rq.mark_sent(r["id"], ok, info)
            if ok:
                sent += 1
                lines.append(f"✅ {r.get('name','?')} → {r.get('email','?')}")
            else:
                failed += 1
                lines.append(f"⚠️ {r.get('name','?')}: {info}")
        logger.info("Discord", f"{_send_hour()}-Uhr-Versand: {sent} gesendet, {failed} übersprungen")
        return {"sent": sent, "failed": failed, "lines": lines, "total": len(todo)}
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
        needed = int(os.environ.get("DISCORD_APPROVALS_NEEDED", "2") or "2")
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

        if st == rq.APPROVED:
            e.set_footer(text=f"✅ Freigegeben — Versand heute um {_send_hour()}:00 an den Kunden.")
        elif st == rq.REJECTED:
            e.set_footer(text="❌ Ein 👎 ist ein Veto — diese Seite wird nicht versendet.")
        elif st == rq.SENT:
            e.set_footer(text="📨 Versendet.")
        else:
            e.set_footer(text=f"👍 {needed}× Daumen hoch (ohne 👎) gibt die Seite frei · Versand um {_send_hour()}:00")
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
            e.set_footer(text="JARVIS startet automatisch bei 0 Uhr neu · Abstimmung: 👍👍 = Freigabe")
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
            await _send_startup_embed()

    @tasks.loop(time=dtime(hour=_send_hour(), minute=0))
    async def _noon_loop():
        res = await asyncio.to_thread(send_approved_now)
        try:
            ch = _bot.get_channel(_channel_id())
            if ch and res["total"]:
                head = f"📨 **{_send_hour()}-Uhr-Versand** — {res['sent']} gesendet, {res['failed']} offen"
                await ch.send(head + ("\n" + "\n".join(res["lines"]) if res["lines"] else ""))
        except Exception:
            pass


# ── Öffentliche API (vom Auto-Builder / app.py genutzt) ────────────────────────

def submit_for_review(name: str, stadt: str, branche: str, link: str,
                      email: str = "", ansprechpartner: str = "", folder: str = "",
                      recipients: "list | None" = None,
                      email_text: str = "", email_subject: str = "", preis: int = 0) -> "dict | None":
    """Legt einen Review an und postet ihn (falls der Bot läuft) in den Discord-Kanal.
    Gibt den Review zurück, oder None wenn der Bot nicht aktiv ist.
    recipients: optionale Empfängerliste (Custom-Modus, 11+).
    email_text: Plaintext der Angebots-Mail (wird im Embed angezeigt).
    email_subject: Betreffzeile der Angebots-Mail.
    preis: Angebotspreis (Tier) — 0 = fairer Standardpreis."""
    if not enabled() or not _started or _loop is None:
        return None
    review = rq.add(name, stadt, branche, link, email, ansprechpartner, folder, recipients,
                    email_text=email_text, preis=preis)
    if email_subject:
        try:
            rq.update(review["id"], email_subject=email_subject)
            review["email_subject"] = email_subject
        except Exception:
            pass
    try:
        asyncio.run_coroutine_threadsafe(_post(review), _loop)
    except Exception as e:
        logger.warn("Discord", f"Review-Post nicht zustellbar: {type(e).__name__}")
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
    logger.info("Discord", "Freigabe-Bot startet…")
    return {"ok": True}
