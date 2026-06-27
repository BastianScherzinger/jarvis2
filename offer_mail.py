"""
offer_mail.py — baut die seriöse, individualisierte Angebots-Mail.

Tonalität (Sirs Vorgabe): ein junger Entwickler der Firma WVM-IT (Österreich) hat dem
Betrieb eine fertige, KOSTENLOSE Webseite gebaut. Bei Interesse Zusammenarbeit für eine
hochwertige Seite zu einem „sehr fairen Preis" (KEIN Festpreis mehr). Referenzen &
Kundenerfahrungen: www.pystore.de. Rechnung läuft über die Firma WVM-IT (wvm-it.tech).

Gemeinsam genutzt von app.py (Button), auto_builder.py (Auto-Builder) und discord_bot.py
(Freigabe-Versand). Jeder dynamische Wert wird individuell aus den Lead-Daten gefüllt.
"""
from __future__ import annotations

import hashlib
import html as _html


def _subject(name: str, branche: str, stadt: str, has_link: bool) -> str:
    """Conversion-starke Betreffzeile. Deterministisch rotiert (pro Betrieb stabil),
    damit nicht alle Mails identisch wirken — ohne Spam-Trigger (kein €/!!! im Betreff)
    und ohne Preisversprechen (Preis steht nicht mehr im Betreff)."""
    region = f" aus {stadt}" if stadt else ""
    fach = branche or "Ihren Betrieb"
    online = [
        f"{name}: Ihre neue Webseite ist fertig — schauen Sie mal rein",
        f"Für {name}{region}: moderne Webseite, online & startklar",
        f"{name} — so könnte {fach} online aussehen",
        f"Webseite für {name} ist online — unverbindlich ansehen",
        f"{name}: einen Blick wert — Ihre Webseite steht bereit",
    ]
    nolink = [
        f"Eine fertige Webseite für {name} — unverbindlich",
        f"{name}{region}: Vorschlag für Ihren neuen Webauftritt",
        f"Für {name}: moderne Webseite, komplett kostenlos angesehen",
    ]
    pool = online if has_link else nolink
    idx = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16) % len(pool)
    return pool[idx]


def _norm_url(link: str) -> str:
    """Erzwingt ein gültiges http(s)-Schema. Ohne gültigen Link → "" (statt eines
    kaputten relativen hrefs wie 'web-xyz.up.railway.app' oder '(Link folgt)')."""
    link = (link or "").strip()
    if not link:
        return ""
    low = link.lower()
    if low.startswith(("http://", "https://")):
        return link
    if low.startswith("mailto:") or low.startswith("tel:"):
        return ""                                # kein Webseiten-Link
    # nackte Domain (railway/eigene) → https voranstellen, sofern es nach Domain aussieht
    if "." in link and " " not in link:
        return "https://" + link.lstrip("/")
    return ""


def _anrede(ansprechpartner: str) -> str:
    """Persönliche Anrede falls Ansprechpartner bekannt, sonst neutral."""
    ap = (ansprechpartner or "").strip()
    if ap and 2 <= len(ap.split()) <= 3:
        return f"Guten Tag {ap},"
    return "Guten Tag,"


def _domain(url: str) -> str:
    return (url or "").replace("https://", "").replace("http://", "").rstrip("/")


def _wvm() -> dict:
    """WVM-IT-Absenderdaten für Signatur + Impressum (per Env überschreibbar).
    `url`/`domain` = wvm-it.tech (Firma/Rechnung), `shop` = www.pystore.de (Referenzen)."""
    import os
    url = (os.environ.get("JARVIS_WVM_URL") or "https://wvm-it.tech").strip()
    return {
        "name": (os.environ.get("JARVIS_WVM_NAME") or "WVM-IT").strip(),
        "url": url,
        "domain": _domain(url),
        "logo": (os.environ.get("JARVIS_WVM_LOGO_URL") or "").strip(),  # öffentliche URL für E-Mail
        "person": (os.environ.get("JARVIS_WVM_PERSON") or "Florin Feier").strip(),
        "shop": (os.environ.get("JARVIS_WVM_SHOP") or "https://www.pystore.de").strip(),
    }


def build(name: str, link: str, branche: str = "", stadt: str = "",
          ansprechpartner: str = "", preis: "int | None" = 0,
          unsubscribe_url: str = "") -> tuple:
    """Gibt (betreff, text, html). Seriöse, persönliche Akquise-Mail eines jungen Entwicklers
    der Firma WVM-IT: fertige KOSTENLOSE Webseite + Live-Link, bei Interesse Zusammenarbeit zu
    einem „sehr fairen Preis" (kein Festpreis), Referenzen auf pystore.de, Rechnung über
    WVM-IT (wvm-it.tech). Rechtssicherer Footer (Impressum + Abmeldung).

    `preis` wird aus Kompatibilität noch akzeptiert, aber NICHT mehr als Festpreis genannt.
    Ist kein gültiger Live-Link vorhanden, wird KEIN kaputter Button gerendert — stattdessen
    eine ehrliche Variante ohne Link."""
    url = _norm_url(link)
    region = f" in {stadt}" if stadt else ""
    fach = branche or "Ihr Betrieb"
    anrede = _anrede(ansprechpartner)
    betreff = _subject(name, branche, stadt, bool(url))
    wvm = _wvm()
    shop_dom = _domain(wvm.get("shop", "")) or "pystore.de"
    try:
        import legal_pages
        rechtsfooter = legal_pages.build_email_footer(unsubscribe_url)
    except Exception:
        rechtsfooter = ""

    # ── Plain-Text — seriös, persönlich, mit den individuellen Lead-Daten ────────
    linkblock = (f"Hier ist sie, schon online:\n{url}\n\n" if url
                 else "Den Live-Link schicke ich Ihnen auf eine kurze Antwort hin sofort zu.\n\n")
    text = (
        f"{anrede}\n\n"
        f"ich bin {wvm['person']}, ein junger Entwickler der Firma {wvm['name']} aus Österreich. "
        f"Ich bin auf {name}{region} gestoßen und habe Ihnen einfach mal eine moderne, "
        f"professionelle Webseite gebaut – komplett kostenlos und unverbindlich.\n\n"
        f"Das Besondere: Ich baue alles selbst und von Hand. Das Layout, das Design, die Farben "
        f"und sogar die Bilder habe ich eigens für {name} erstellt – kein Baukasten, keine "
        f"Vorlage, keine Stockfotos von der Stange. Jede Seite ist ein Einzelstück.\n\n"
        f"{linkblock}"
        f"Wenn sie Ihnen gefällt, arbeite ich gerne mit Ihnen zusammen und baue Ihnen für einen "
        f"sehr fairen Preis eine hochwertige Webseite, individuell auf {fach} zugeschnitten – "
        f"komplett selbst gestaltet, mit eigenem Design, abgestimmten Farben und eigens für Sie "
        f"erstellten Bildern.\n\n"
        f"Selbstverständlich passe ich alles ganz nach Ihren Wünschen an – auf Wunsch mit "
        f"hochwertigen, dezenten Animationen, jederzeit erweiterbar um neue Inhalte und Funktionen. "
        f"Und ich lasse Sie damit nicht allein: Ich betreue Ihre Webseite auch danach laufend – "
        f"Pflege, technische Wartung, Aktualisierungen und Änderungen übernehme ich zuverlässig "
        f"für Sie. Sie haben einen festen Ansprechpartner. Gefällt sie nicht, kostet es Sie nichts.\n\n"
        f"Meine Referenzen und Kundenerfahrungen sehen Sie auf {wvm['shop']}. Die Abrechnung "
        f"läuft seriös über die Firma {wvm['name']} ({wvm['domain']}).\n\n"
        f"Antworten Sie einfach kurz auf diese Mail, dann besprechen wir alles Weitere.\n\n"
        f"Beste Grüße\n{wvm['person']}\n{wvm['name']} · {wvm['domain']}"
        + (("\n\n" + rechtsfooter) if rechtsfooter else "")
    )

    # ── HTML (alle dynamischen Werte escaped) ───────────────────────────────
    e_name = _html.escape(name)
    e_region = _html.escape(region)
    e_fach = _html.escape(fach)
    e_anrede = _html.escape(anrede)
    e_url = _html.escape(url, quote=True)
    e_wvm_url = _html.escape(wvm["url"], quote=True)
    e_wvm_name = _html.escape(wvm["name"])
    e_wvm_dom = _html.escape(wvm["domain"])
    e_wvm_person = _html.escape(wvm["person"])
    e_shop = _html.escape(wvm.get("shop", ""), quote=True)
    e_shop_dom = _html.escape(shop_dom)
    wvm_logo_html = (f'<img src="{_html.escape(wvm["logo"], quote=True)}" alt="{e_wvm_name}" '
                     f'style="height:22px;width:auto;vertical-align:middle;margin-right:6px">'
                     if wvm["logo"] else "")
    signatur_html = (
        f'<p style="font-size:15px;color:#3a4654;margin:14px 0 0">Beste Grüße<br>'
        f'<strong>{e_wvm_person}</strong></p>'
        f'<p style="margin:10px 0 0;font-size:13px;color:#6a7c90">{wvm_logo_html}'
        f'<a href="{e_wvm_url}" style="color:#1e8eff;text-decoration:none;font-weight:600">'
        f'{e_wvm_name} · {e_wvm_dom}</a></p>'
    )

    cta_html = (
        f"""<p style="margin:22px 0 6px">
        <a href="{e_url}" style="display:inline-block;background:#1e8eff;color:#fff;font-weight:700;font-size:16px;padding:15px 34px;border-radius:10px;text-decoration:none;box-shadow:0 8px 22px rgba(30,142,255,.35)">Webseite ansehen →</a>
      </p>
      <p style="margin:10px 0 0;font-size:12px;color:#8fa6c0">Komplett kostenlos und unverbindlich</p>"""
        if url else
        """<p style="margin:18px 0 0;font-size:14px;color:#c4d4e6">Antworten Sie kurz auf diese Mail — ich sende Ihnen den Live-Link sofort zu.</p>"""
    )
    foot_link = f'<p style="text-align:center;color:#90a0b3;font-size:12px;margin:16px 0 0"><a href="{e_url}" style="color:#90a0b3">{e_url}</a></p>' if url else ""

    # Rechtssicherer HTML-Footer: Absender-Impressum (WVM-IT) + Abmeldung (UWG/DSGVO).
    e_unsub = _html.escape(unsubscribe_url, quote=True)
    abmelde_html = (f'<a href="{e_unsub}" style="color:#90a0b3;text-decoration:underline">abmelden</a>'
                    if unsubscribe_url else 'mit „STOP" antworten')
    import os as _os
    _imp = " · ".join(x for x in [
        f"{wvm['name']} · {e_wvm_person}",
        _html.escape((_os.environ.get("JARVIS_WVM_ADDRESS") or "").strip()),
        _html.escape((_os.environ.get("JARVIS_WVM_EMAIL") or "").strip()),
    ] if x)
    legal_html = (
        f'<div style="max-width:600px;margin:14px auto 0;padding:0 16px;text-align:center;'
        f'font-size:11px;line-height:1.6;color:#9aa7b5">'
        f'{_imp}<br>'
        f'Einmalige geschäftliche Kontaktaufnahme. Keine weiteren Mails? Einfach {abmelde_html}.'
        f'</div>'
    )

    html = f"""<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:#e9edf2;font-family:'Segoe UI',Arial,Helvetica,sans-serif;color:#161b22">
  <div style="max-width:600px;margin:0 auto;padding:24px 16px">
    <!-- Hero -->
    <div style="background:linear-gradient(135deg,#0b1626,#16314f);border-radius:20px 20px 0 0;padding:34px 32px 26px;color:#fff">
      <p style="margin:0 0 10px;font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:#6fd3ff">Ihre neue Webseite — bereits online</p>
      <h1 style="margin:0;font-size:27px;line-height:1.22;font-weight:800">{e_name}<br>ist startklar.</h1>
      <p style="margin:14px 0 0;font-size:15px;line-height:1.6;color:#c4d4e6">
        {e_anrede} ich bin {e_wvm_person}, ein junger Entwickler der Firma {e_wvm_name} aus Österreich,
        und habe {e_name}{e_region} eine moderne Webseite gebaut — komplett kostenlos und von Hand:
        Design, Farben und sogar die Bilder eigens für Sie erstellt. Sehen Sie selbst,
        wie Ihr Betrieb online wirken könnte:</p>
      {cta_html}
    </div>
    <!-- Body -->
    <div style="background:#fff;border-radius:0 0 20px 20px;padding:30px 32px;box-shadow:0 14px 44px rgba(11,22,38,.12)">
      <ul style="margin:0 0 22px;padding:0;list-style:none;font-size:15px;line-height:1.75;color:#2c3743">
        <li style="margin-bottom:9px"><span style="color:#1e8eff;font-weight:700">✓</span> Die fertige Webseite ist <strong>komplett kostenlos</strong> — Sie sehen sie einfach an</li>
        <li style="margin-bottom:9px"><span style="color:#1e8eff;font-weight:700">✓</span> <strong>Alles selbst von Hand gebaut</strong> — individuelles Design, abgestimmte Farben und eigens für {e_name} erstellte Bilder. Kein Baukasten, keine Vorlage, keine Stockfotos</li>
        <li style="margin-bottom:9px"><span style="color:#1e8eff;font-weight:700">✓</span> <strong>Lebendig und modern</strong> — auf Wunsch mit hochwertigen, dezenten Animationen</li>
        <li style="margin-bottom:9px"><span style="color:#1e8eff;font-weight:700">✓</span> <strong>Jederzeit erweiterbar und voll anpassbar</strong> — Texte, Farben, Bilder, neue Funktionen, eigene Domain</li>
        <li style="margin-bottom:9px"><span style="color:#1e8eff;font-weight:700">✓</span> <strong>Laufende Betreuung</strong> — Pflege, technische Wartung und Änderungen übernehme ich für Sie. Sie haben einen festen Ansprechpartner</li>
        <li><span style="color:#1e8eff;font-weight:700">✓</span> Bei Interesse baue ich Ihnen die finale Seite für einen <strong>sehr fairen Preis</strong>, individuell für {e_fach} — unverbindlich, gefällt sie nicht, kostet es Sie nichts</li>
      </ul>
      <div style="border-left:3px solid #1e8eff;background:#f7faff;padding:12px 16px;border-radius:0 10px 10px 0;margin:0 0 22px;font-size:14.5px;color:#3a4654;line-height:1.6">
        Meine Referenzen und Kundenerfahrungen finden Sie auf
        <a href="{e_shop}" style="color:#1e8eff;text-decoration:none;font-weight:600">{e_shop_dom}</a>.
        Die Abrechnung läuft seriös über die Firma <strong>{e_wvm_name}</strong> ({e_wvm_dom}).</div>
      <p style="font-size:15px;color:#3a4654;margin:0 0 4px">Klingt gut? Antworten Sie einfach kurz auf diese Mail.</p>
      {signatur_html}
    </div>
    {foot_link}
  </div>
  {legal_html}
</body></html>"""
    return betreff, text, html
