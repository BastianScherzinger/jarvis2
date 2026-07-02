"""
reply_templates.py — Vorlagen für die ANTWORT auf Kundenreaktionen (Schritt 7).

Aktuell: die Preisanfrage-Antwort (von Sir formuliert, hier parametrisiert). Wird genutzt, wenn
eine Kundenantwort als „preisfrage" erkannt wird (inbox_reader) — JARVIS legt dann einen fertigen
Antwort-Entwurf bei, den Sir nur noch prüfen und abschicken muss (Abschluss bleibt menschlich).

Preise kommen aus pricing.py (eine Quelle der Wahrheit). Signatur/Referenzen via .env anpassbar.
"""
from __future__ import annotations

import os

import pricing


def _signer() -> str:
    return (os.environ.get("JARVIS_REPLY_SIGNER") or "Basti").strip()


def _references() -> list[str]:
    raw = os.environ.get("JARVIS_REPLY_REFERENCES") or "ruempelwerk-mitteldeutschland.de, rtc-service.com"
    return [r.strip() for r in raw.split(",") if r.strip()]


def _anrede(ansprechpartner: str, name: str) -> str:
    ap = (ansprechpartner or "").strip()
    if ap and 2 <= len(ap.split()) <= 4:
        return f"Guten Tag {ap},"
    return "Guten Tag,"


def _seitentyp(branche: str) -> tuple[str, str]:
    """(Seitenbezeichnung, Beispiel-Unterseiten) je nach Branche."""
    b = (branche or "").lower()
    if any(x in b for x in ("zahn", "arzt", "ärzt", "aerzt", "praxis", "dent", "therap", "kiefer")):
        return "Praxis-Webseite", "z. B. Leistungen, Team, Kontakt, Notdienst"
    return "Unternehmens-Webseite", "z. B. Leistungen, Über uns, Kontakt"


def price_inquiry(name: str = "", ansprechpartner: str = "", branche: str = "",
                  demo_url: str = "") -> dict:
    """Antwort-Entwurf auf eine Preisanfrage. Gibt {subject, body}."""
    anrede = _anrede(ansprechpartner, name)
    seitentyp, unterseiten = _seitentyp(branche)
    refs = _references()
    ref_line = " und ".join(refs) if refs else ""
    signer = _signer()
    demo_frage = ""
    if demo_url:
        demo_frage = (f"\nMich würde außerdem interessieren, wie Ihnen die Beispiel-Webseite gefallen "
                      f"hat, die wir bereits für Sie erstellt haben ({demo_url}). Gibt es etwas, das "
                      f"Sie anders gestalten oder ergänzen würden?\n")
    else:
        demo_frage = ("\nMich würde außerdem interessieren, wie Ihnen die Beispiel-Webseite gefallen "
                      "hat, die wir bereits für Sie erstellt haben. Gibt es etwas, das Sie anders "
                      "gestalten oder ergänzen würden?\n")

    subject = "Ihre Anfrage — individuelle Webseite, fairer Festpreis"
    body = (
        f"{anrede}\n\n"
        "vielen Dank für Ihre Nachricht und Ihr Interesse an der Webseite.\n\n"
        f"Ich bin {signer}, der Entwickler unseres Teams, und kümmere mich um die technische "
        "Umsetzung unserer Webseiten. Jede Seite wird individuell programmiert – kein Baukasten, "
        "sondern eine moderne, schnelle und professionelle Webseite, die Ihr Unternehmen optimal "
        "präsentiert.\n\n"
        "Damit ich Ihnen einen fairen Festpreis nennen kann, würde ich gerne kurz wissen, was Sie "
        "sich vorstellen:\n\n"
        f"• Soll es eine moderne {seitentyp} mit den wichtigsten Informationen sein?\n"
        f"• Möchten Sie mehrere Unterseiten ({unterseiten})?\n"
        "• Benötigen Sie besondere Funktionen wie Terminanfragen, einen geschützten Admin-Bereich "
        "oder später vielleicht sogar einen kleinen Online-Shop?\n"
        f"{demo_frage}\n"
        f"Unsere Webseiten beginnen bereits {pricing.base_text()} als einmalige Zahlung. Je nach "
        f"Umfang und gewünschten Funktionen liegt der Preis meist zwischen {pricing.range_text()}. "
        "Sie erhalten dafür eine individuell programmierte Webseite ohne laufende "
        "Entwicklungskosten – professionell, modern und jederzeit erweiterbar.\n\n"
        "Sobald ich weiß, was Sie sich wünschen, erhalten Sie von mir ein transparentes "
        "Festpreis-Angebot – selbstverständlich unverbindlich und ohne versteckte Kosten.\n\n"
        "Ich freue mich auf Ihre Rückmeldung.\n\n"
        "Freundliche Grüße\n\n"
        f"{signer}\nWebentwicklung\nWVM-IT\n"
    )
    if ref_line:
        body += ("\nPS: Das Ganze können wir gerne mit Rechnung machen, und wir zeigen Ihnen gerne "
                 f"Referenzen: {ref_line} sind ein paar unserer vielen zufriedenen Kunden. Wir "
                 "würden uns freuen, auch mit Ihnen zusammenzuarbeiten :)\n")
    return {"subject": subject, "body": body}


# Registry: kategorie (aus inbox_reader) → Vorlagen-Funktion. Erweiterbar.
BY_CATEGORY = {
    "preisfrage": price_inquiry,
    "interesse":  price_inquiry,     # Interesse ohne konkrete Frage → gleicher freundlicher Einstieg
}


def suggest(kategorie: str, name: str = "", ansprechpartner: str = "", branche: str = "",
            demo_url: str = "") -> dict:
    """Passenden Antwort-Entwurf zur erkannten Kategorie liefern ({} wenn keine Vorlage passt)."""
    fn = BY_CATEGORY.get((kategorie or "").strip().lower())
    if not fn:
        return {}
    return fn(name=name, ansprechpartner=ansprechpartner, branche=branche, demo_url=demo_url)
