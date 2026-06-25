"""
offer_mail.py — baut die designte Angebots-Mail (Webseite für 350 €).
Gemeinsam genutzt von app.py (Button) und auto_builder.py (Auto-Builder).
"""
from __future__ import annotations

import hashlib
import html as _html


def _subject(name: str, branche: str, stadt: str, has_link: bool) -> str:
    """Conversion-starke Betreffzeile. Deterministisch rotiert (pro Betrieb stabil),
    damit nicht alle Mails identisch wirken — ohne Spam-Trigger (kein €/!!! im Betreff)."""
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
        f"Für {name}: moderne Webseite zum Festpreis",
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


def _wvm() -> dict:
    """WVM-IT-Absenderdaten für die Signatur (per Env überschreibbar)."""
    import os
    url = (os.environ.get("JARVIS_WVM_URL") or "https://wvm-it.at").strip()
    dom = url.replace("https://", "").replace("http://", "").rstrip("/")
    return {
        "name": (os.environ.get("JARVIS_WVM_NAME") or "WVM-IT").strip(),
        "url": url,
        "domain": dom,
        "logo": (os.environ.get("JARVIS_WVM_LOGO_URL") or "").strip(),  # öffentliche URL für E-Mail
        "person": (os.environ.get("JARVIS_WVM_PERSON") or "Bastian Scherzinger").strip(),
    }


def _price(preis: "int | None") -> int:
    """Effektiver Angebotspreis: übergebener Tier-Preis (>0), sonst fairer Standardpreis
    aus JARVIS_OFFER_PRICE (Default 299 € — günstig, aber lohnend für eine komplette Seite)."""
    import os
    try:
        p = int(preis or 0)
    except Exception:
        p = 0
    if p > 0:
        return p
    try:
        return int(os.environ.get("JARVIS_OFFER_PRICE", "299") or "299")
    except Exception:
        return 299


def build(name: str, link: str, branche: str = "", stadt: str = "",
          ansprechpartner: str = "", preis: "int | None" = 0,
          unsubscribe_url: str = "") -> tuple:
    """Gibt (betreff, text, html). Fairer Komplettpreis (Default 299 €, per Tier/Env), alles
    anpassbar, Live-Link, rechtssicherer Footer (Impressum + Abmeldung).

    Ist kein gültiger Live-Link vorhanden, wird KEIN kaputter Button gerendert —
    stattdessen eine ehrliche Variante ohne Link."""
    url = _norm_url(link)
    region = f" in {stadt}" if stadt else ""
    fach = branche or "Ihr Betrieb"
    anrede = _anrede(ansprechpartner)
    betreff = _subject(name, branche, stadt, bool(url))
    wvm = _wvm()
    eur = _price(preis)
    try:
        import legal_pages
        rechtsfooter = legal_pages.build_email_footer(unsubscribe_url)
    except Exception:
        rechtsfooter = ""

    # ── Plain-Text — kurz, menschlich, freundlich ───────────────────────────
    linkblock = (f"Hier ist sie, schon online:\n{url}\n\n" if url
                 else "Den Live-Link schicke ich Ihnen auf eine kurze Antwort hin sofort zu.\n\n")
    text = (
        f"{anrede}\n\n"
        f"ich bin auf {name}{region} gestoßen und fand schade, dass ein Betrieb mit so gutem "
        f"Ruf online kaum sichtbar ist. Also habe ich Ihnen einfach mal eine moderne Webseite "
        f"gebaut – ganz unverbindlich.\n\n"
        f"{linkblock}"
        f"Gefällt sie Ihnen? Dann übernehme ich sie für Sie und passe jedes Detail an Ihre "
        f"Wünsche an – Texte, Farben, Bilder. Komplett fertig für {eur} € einmalig, kein Abo, "
        f"keine versteckten Kosten. Gefällt sie nicht, kostet es Sie nichts.\n\n"
        f"Antworten Sie einfach kurz auf diese Mail, dann klären wir den Rest.\n\n"
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
        <a href="{e_url}" style="display:inline-block;background:#1e8eff;color:#fff;font-weight:700;font-size:16px;padding:15px 34px;border-radius:999px;text-decoration:none;box-shadow:0 8px 22px rgba(30,142,255,.45)">🌐 Webseite ansehen →</a>
      </p>
      <p style="margin:10px 0 0;font-size:12px;color:#8fa6c0">Unverbindlich · ohne Anmeldung · in 10 Sekunden offen</p>"""
        if url else
        """<p style="margin:18px 0 0;font-size:14px;color:#c4d4e6">Antworten Sie kurz auf diese Mail — wir senden Ihnen den Live-Link sofort zu.</p>"""
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
        {e_anrede} wir haben {e_name}{e_region} eine moderne, professionelle Webseite gebaut — komplett
        unverbindlich. Sehen Sie selbst, wie Ihr Betrieb online wirken könnte:</p>
      {cta_html}
    </div>
    <!-- Body -->
    <div style="background:#fff;border-radius:0 0 20px 20px;padding:30px 32px;box-shadow:0 14px 44px rgba(11,22,38,.12)">
      <!-- Preis-Anker -->
      <div style="display:flex;align-items:center;gap:16px;background:#f3f8ff;border:1px solid #d6e6fb;border-radius:16px;padding:18px 22px;margin:0 0 24px">
        <div>
          <div style="font-size:12px;color:#6a7c90;text-transform:uppercase;letter-spacing:.08em">Komplettpreis</div>
          <div style="font-size:34px;font-weight:800;color:#0b1626;line-height:1">{eur}&nbsp;€</div>
          <div style="font-size:12px;color:#8a99ab"><span style="text-decoration:line-through">Agentur ab 1.500&nbsp;€</span> · einmalig, kein Abo</div>
        </div>
        <div style="margin-left:auto;text-align:right">
          <span style="display:inline-block;background:#e6f9ef;color:#12a150;font-weight:700;font-size:12px;padding:6px 12px;border-radius:999px">★ alles inklusive</span>
        </div>
      </div>
      <ul style="margin:0 0 22px;padding:0;list-style:none;font-size:15px;line-height:1.75;color:#2c3743">
        <li style="margin-bottom:7px">✅ Professionelle, mobiloptimierte Webseite — passend zu {e_fach}</li>
        <li style="margin-bottom:7px">✅ <strong>Alles individuell anpassbar</strong> — Texte, Farben, Bilder, Inhalte</li>
        <li style="margin-bottom:7px">✅ Sofort online, schnell startklar, eigene Domain möglich</li>
        <li>✅ Keine versteckten Kosten, kein Abo, keine Verpflichtung</li>
      </ul>
      <div style="border-left:3px solid #1e8eff;background:#f7faff;padding:12px 16px;border-radius:0 10px 10px 0;margin:0 0 22px;font-size:14.5px;color:#3a4654;line-height:1.6">
        Gefällt sie Ihnen, übernehmen wir sie für Sie und passen <strong>jedes Detail</strong>
        nach Ihren Wünschen an. Gefällt sie nicht? Dann kostet Sie das nichts — Sie haben sie
        ja schon gesehen.</div>
      <p style="font-size:15px;color:#3a4654;margin:0 0 4px">Klingt gut? Antworten Sie einfach kurz auf diese Mail.</p>
      {signatur_html}
    </div>
    {foot_link}
  </div>
  {legal_html}
</body></html>"""
    return betreff, text, html
