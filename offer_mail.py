"""
offer_mail.py — baut die designte Angebots-Mail (Webseite für 350 €).
Gemeinsam genutzt von app.py (Button) und auto_builder.py (Auto-Builder).
"""
from __future__ import annotations


def build(name: str, link: str, branche: str = "", stadt: str = "") -> tuple:
    """Gibt (betreff, text, html). Komplettpreis 350 €, alles anpassbar, Live-Link."""
    linkzeile = link or "(Link folgt)"
    region = f" in {stadt}" if stadt else ""
    fach = branche or "Ihr Betrieb"
    betreff = f"Webseite für {name} – fertig & online (Komplettpreis 350 €)"
    text = (
        f"Guten Tag,\n\n"
        f"wir sind auf {name}{region} aufmerksam geworden – ein Betrieb mit gutem Ruf, "
        f"aber bislang ohne professionellen Webauftritt. Deshalb haben wir Ihnen "
        f"unverbindlich eine moderne Webseite erstellt. Sie ist bereits online:\n\n"
        f"{linkzeile}\n\n"
        f"Unser Angebot, ehrlich und einfach:\n"
        f"• Komplette, professionelle Webseite zum Festpreis von 350 € – keine versteckten Kosten.\n"
        f"• Modernes, mobiloptimiertes Design, passend zu {fach}.\n"
        f"• Alles individuell anpassbar: Texte, Farben, Bilder, Inhalte – ganz nach Ihren Wünschen.\n"
        f"• Schnell startklar und sofort online.\n\n"
        f"Schauen Sie in Ruhe rein. Gefällt sie Ihnen, übernehmen wir sie für Sie und passen "
        f"jedes Detail an. Sie entscheiden, was bleibt und was sich ändert.\n\n"
        f"Antworten Sie einfach auf diese Mail – wir besprechen die Details unverbindlich.\n\n"
        f"Beste Grüße\nBastian Scherzinger"
    )
    html = f"""<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:#eef1f4;font-family:'Segoe UI',Arial,Helvetica,sans-serif;color:#1a1f27">
  <div style="max-width:580px;margin:0 auto;padding:26px 18px">
    <div style="background:#0f1b2d;border-radius:18px 18px 0 0;padding:30px 30px 22px;color:#fff">
      <p style="margin:0 0 8px;font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:#5fd0ff">Ihre neue Webseite – startklar</p>
      <h1 style="margin:0;font-size:25px;line-height:1.25;font-weight:700">{name} ist online.</h1>
      <p style="margin:12px 0 0;font-size:15px;line-height:1.6;color:#c7d4e3">
        Wir haben {name}{region} unverbindlich eine moderne Webseite gebaut – schauen Sie selbst:</p>
      <p style="margin:20px 0 4px">
        <a href="{linkzeile}" style="display:inline-block;background:#1e8eff;color:#fff;font-weight:700;font-size:16px;padding:14px 30px;border-radius:999px;text-decoration:none">Webseite ansehen →</a>
      </p>
    </div>
    <div style="background:#fff;border-radius:0 0 18px 18px;padding:28px 30px;box-shadow:0 12px 40px rgba(15,27,45,.10)">
      <div style="background:#f4f8ff;border:1px solid #d8e6fb;border-radius:14px;padding:18px 20px;margin:0 0 22px">
        <div style="font-size:13px;color:#5b6b7e">Komplettpreis</div>
        <div style="font-size:30px;font-weight:800;color:#0f1b2d;line-height:1.1">350&nbsp;€ <span style="font-size:14px;font-weight:600;color:#5b6b7e">– einmalig, alles inklusive</span></div>
      </div>
      <ul style="margin:0 0 22px;padding:0;list-style:none;font-size:15px;line-height:1.7;color:#333b46">
        <li style="margin-bottom:6px">✓ Professionelle, mobiloptimierte Webseite passend zu {fach}</li>
        <li style="margin-bottom:6px">✓ <strong>Alles individuell anpassbar</strong> – Texte, Farben, Bilder, Inhalte</li>
        <li style="margin-bottom:6px">✓ Sofort online, schnell startklar</li>
        <li>✓ Keine versteckten Kosten, kein Abo</li>
      </ul>
      <p style="font-size:15px;line-height:1.65;color:#454b54;margin:0 0 18px">
        Gefällt sie Ihnen, übernehmen wir sie für Sie und passen jedes Detail nach Ihren
        Wünschen an. Sie entscheiden, was bleibt und was sich ändert.</p>
      <p style="font-size:15px;color:#454b54;margin:0">Einfach auf diese Mail antworten.<br>Beste Grüße<br><strong>Bastian Scherzinger</strong></p>
    </div>
    <p style="text-align:center;color:#90a0b3;font-size:12px;margin:16px 0 0">{linkzeile}</p>
  </div>
</body></html>"""
    return betreff, text, html
