"""
legal_pages.py — Deterministische deutsche Rechtstexte (Impressum, Datenschutz, AGB)
aus den Betriebsdaten. KEIN KI-Aufruf → 0 Tokens, voll offline, immer gleich rechtssicher
strukturiert. Fehlende Pflichtangaben werden als „[bitte ergänzen]" markiert (nichts erfunden).

Der Makeover injiziert diese Texte in content.json (impressum/datenschutz/agb); die
Makeover-Stufe „QA & Recht" muss sie dann nur noch rendern + im Footer verlinken — sie
erzeugt sie NICHT neu (spart Claude-Code-Tokens).
"""
from __future__ import annotations

_PH = "[bitte ergänzen]"


def _v(x) -> str:
    s = (str(x).strip() if x is not None else "")
    return s or _PH


def build_impressum(name: str = "", adresse: str = "", telefon: str = "",
                    email: str = "", ansprechpartner: str = "") -> str:
    """Impressum nach § 5 DDG (vormals § 5 TMG)."""
    return (
        "Impressum\n\n"
        "Angaben gemäß § 5 DDG\n\n"
        f"{_v(name)}\n"
        f"{_v(adresse)}\n\n"
        "Vertreten durch:\n"
        f"{_v(ansprechpartner)}\n\n"
        "Kontakt:\n"
        f"Telefon: {_v(telefon)}\n"
        f"E-Mail: {_v(email)}\n\n"
        "Umsatzsteuer-ID:\n"
        "Umsatzsteuer-Identifikationsnummer gemäß § 27 a Umsatzsteuergesetz: " + _PH + "\n\n"
        "Verbraucherstreitbeilegung/Universalschlichtungsstelle:\n"
        "Wir sind nicht bereit oder verpflichtet, an Streitbeilegungsverfahren vor einer "
        "Verbraucherschlichtungsstelle teilzunehmen.\n\n"
        "Haftung für Inhalte:\n"
        "Als Diensteanbieter sind wir gemäß § 7 Abs.1 DDG für eigene Inhalte auf diesen Seiten "
        "nach den allgemeinen Gesetzen verantwortlich. Verpflichtungen zur Entfernung oder Sperrung "
        "der Nutzung von Informationen nach den allgemeinen Gesetzen bleiben hiervon unberührt."
    )


def build_datenschutz(name: str = "", adresse: str = "", telefon: str = "",
                      email: str = "", ansprechpartner: str = "") -> str:
    """Schlanke, DSGVO-konforme Datenschutzerklärung für eine Landing-Page mit Kontaktformular."""
    verantwortlich = _v(name)
    return (
        "Datenschutzerklärung\n\n"
        "1. Datenschutz auf einen Blick\n"
        "Die folgenden Hinweise geben einen einfachen Überblick darüber, was mit Ihren "
        "personenbezogenen Daten passiert, wenn Sie diese Website besuchen. Personenbezogene Daten "
        "sind alle Daten, mit denen Sie persönlich identifiziert werden können.\n\n"
        "2. Verantwortliche Stelle\n"
        f"{verantwortlich}\n{_v(adresse)}\n"
        f"Telefon: {_v(telefon)}\nE-Mail: {_v(email)}\n"
        f"Ansprechpartner: {_v(ansprechpartner)}\n\n"
        "3. Erfassung von Daten / Kontaktformular\n"
        "Wenn Sie uns über das Kontaktformular oder per E-Mail kontaktieren, werden Ihre Angaben "
        "inklusive der von Ihnen dort angegebenen Kontaktdaten zwecks Bearbeitung der Anfrage und "
        "für den Fall von Anschlussfragen bei uns gespeichert. Rechtsgrundlage ist Art. 6 Abs. 1 "
        "lit. b DSGVO (Anbahnung/Erfüllung eines Vertrags) bzw. Art. 6 Abs. 1 lit. f DSGVO "
        "(berechtigtes Interesse an der Beantwortung). Diese Daten geben wir nicht ohne Ihre "
        "Einwilligung weiter.\n\n"
        "4. Hosting & Server-Log-Dateien\n"
        "Der Provider der Seiten erhebt und speichert automatisch Informationen in sogenannten "
        "Server-Log-Dateien (Browsertyp, Betriebssystem, Referrer-URL, Hostname, Uhrzeit). Diese "
        "Daten sind nicht bestimmten Personen zuordenbar und dienen der technischen Sicherheit.\n\n"
        "5. Ihre Rechte\n"
        "Sie haben jederzeit das Recht auf Auskunft, Berichtigung, Löschung oder Einschränkung der "
        "Verarbeitung Ihrer Daten, ein Widerspruchsrecht sowie das Recht auf Datenübertragbarkeit "
        "(Art. 15–21 DSGVO). Zudem steht Ihnen ein Beschwerderecht bei einer Aufsichtsbehörde zu.\n\n"
        "6. SSL-/TLS-Verschlüsselung\n"
        "Diese Seite nutzt aus Sicherheitsgründen eine SSL-/TLS-Verschlüsselung."
    )


def build_agb(name: str = "") -> str:
    """Kurze, allgemeine AGB für Dienstleistungen eines lokalen Betriebs."""
    firma = _v(name)
    return (
        "Allgemeine Geschäftsbedingungen (AGB)\n\n"
        "1. Geltungsbereich\n"
        f"Diese AGB gelten für alle Verträge und Leistungen zwischen {firma} (nachfolgend "
        "„Auftragnehmer\") und dem Kunden, soweit nicht ausdrücklich etwas anderes vereinbart wurde.\n\n"
        "2. Angebot und Vertragsschluss\n"
        "Angebote sind freibleibend. Ein Vertrag kommt durch Auftragsbestätigung bzw. Ausführung "
        "der Leistung zustande.\n\n"
        "3. Leistungen und Preise\n"
        "Art und Umfang der Leistung ergeben sich aus der jeweiligen Vereinbarung. Es gelten die zum "
        "Zeitpunkt des Vertragsschlusses vereinbarten Preise zzgl. der gesetzlichen Umsatzsteuer.\n\n"
        "4. Zahlungsbedingungen\n"
        "Rechnungen sind, sofern nicht anders vereinbart, innerhalb von 14 Tagen nach Rechnungs"
        "stellung ohne Abzug zur Zahlung fällig.\n\n"
        "5. Gewährleistung und Haftung\n"
        "Es gelten die gesetzlichen Gewährleistungsregelungen. Die Haftung für leicht fahrlässige "
        "Pflichtverletzungen ist ausgeschlossen, soweit keine wesentlichen Vertragspflichten "
        "betroffen sind oder Schäden aus der Verletzung von Leben, Körper oder Gesundheit resultieren.\n\n"
        "6. Schlussbestimmungen\n"
        "Es gilt das Recht der Bundesrepublik Deutschland. Sollte eine Bestimmung unwirksam sein, "
        "bleibt die Wirksamkeit der übrigen Bestimmungen unberührt."
    )


def build_all(meta: dict) -> dict:
    """Alle drei Rechtstexte aus einem Betriebs-/Lead-dict (best-effort Feldwahl)."""
    name  = meta.get("name") or meta.get("site_name") or ""
    adr   = meta.get("adresse") or ""
    tel   = meta.get("telefon") or ""
    email = meta.get("email") or meta.get("email_adresse") or meta.get("kontakt_email") or ""
    ap    = meta.get("ansprechpartner") or ""
    return {
        "impressum":   build_impressum(name, adr, tel, email, ap),
        "datenschutz": build_datenschutz(name, adr, tel, email, ap),
        "agb":         build_agb(name),
    }
