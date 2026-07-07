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
        "5. Herkunft der Daten bei Direktansprache\n"
        "Soweit wir Betriebe erstmals per E-Mail kontaktieren, verarbeiten wir öffentlich "
        "zugängliche Geschäftskontaktdaten (Firmenname, Anschrift, Telefon, geschäftliche "
        "E-Mail), die wir aus allgemein einsehbaren Quellen wie Branchenverzeichnissen, "
        "Kartendiensten (z. B. Google Maps) und der jeweiligen Firmen-Website erhoben haben "
        "(Art. 14 DSGVO). Zweck ist die einmalige geschäftliche Kontaktaufnahme; Rechtsgrundlage "
        "ist unser berechtigtes Interesse (Art. 6 Abs. 1 lit. f DSGVO). Nicht kontaktierte "
        "Datensätze werden nach spätestens sechs Monaten automatisch gelöscht.\n\n"
        "6. Ihre Rechte\n"
        "Sie haben jederzeit das Recht auf Auskunft, Berichtigung, Löschung oder Einschränkung der "
        "Verarbeitung Ihrer Daten, ein Widerspruchsrecht sowie das Recht auf Datenübertragbarkeit "
        "(Art. 15–21 DSGVO). Zudem steht Ihnen ein Beschwerderecht bei einer Aufsichtsbehörde zu.\n\n"
        "7. SSL-/TLS-Verschlüsselung\n"
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


def wvm_company() -> dict:
    """Eigene Firmendaten (WVM-IT) für den rechtssicheren Mail-Footer — aus der .env, mit
    Platzhaltern. EINMAL setzen: JARVIS_WVM_NAME/PERSON/ADDRESS/EMAIL/PHONE/URL/VATID."""
    import os
    g = lambda k, d="": (os.environ.get(k) or d).strip()
    url = g("JARVIS_WVM_URL", "https://wvm-it.at")
    return {
        "name":    g("JARVIS_WVM_NAME", "WVM-IT"),
        "person":  g("JARVIS_WVM_PERSON", "Bastian Scherzinger"),
        "address": g("JARVIS_WVM_ADDRESS", _PH),
        "email":   g("JARVIS_WVM_EMAIL", _PH),
        "phone":   g("JARVIS_WVM_PHONE", ""),
        "url":     url,
        "domain":  url.replace("https://", "").replace("http://", "").rstrip("/"),
        "vatid":   g("JARVIS_WVM_VATID", ""),
    }


def build_email_footer(unsubscribe_url: str = "") -> str:
    """Rechtssicherer Plaintext-Footer für die Kalt-Akquise-Mail (UWG/DSGVO):
    Absender-Impressum + Abmeldehinweis. Der Abmelde-Link wird angehängt, wenn vorhanden;
    zusätzlich gilt immer „mit STOP antworten" (funktioniert ohne öffentlichen Webhost)."""
    w = wvm_company()
    teile = [
        "—",
        f"{w['name']} · {w['person']}",
        w["address"],
    ]
    kontakt = " · ".join(x for x in [f"Tel: {w['phone']}" if w["phone"] else "",
                                     f"E-Mail: {w['email']}", w["url"]] if x)
    teile.append(kontakt)
    if w["vatid"]:
        teile.append(f"USt-IdNr.: {w['vatid']}")
    teile.append("")
    # DSGVO Art. 14 — Hinweis auf Herkunft der Daten (bei nicht vom Betroffenen erhobenen Daten).
    ds = f"{w['url']}/datenschutz" if w.get("url") else ""
    teile.append(
        "Datenschutzhinweis (Art. 13/14 DSGVO): Wir haben Ihre öffentlich zugänglichen "
        "Geschäftskontaktdaten aus allgemein einsehbaren Quellen (u. a. Branchenverzeichnisse, "
        "Google Maps, Ihre Website) erhoben. Verarbeitungszweck ist die einmalige geschäftliche "
        "Direktansprache; Rechtsgrundlage ist unser berechtigtes Interesse (Art. 6 Abs. 1 lit. f "
        "DSGVO). Sie können der Verarbeitung jederzeit widersprechen."
        + (f" Mehr dazu: {ds}" if ds else ""))
    teile.append("")
    if unsubscribe_url:
        teile.append(f"Keine weiteren Mails? Hier abmelden: {unsubscribe_url}")
    teile.append("Sie erhalten diese einmalige Nachricht als Gewerbetreibender im Rahmen einer "
                 "Geschäftsanbahnung. Möchten Sie keine weitere Mail, antworten Sie einfach mit "
                 "\"STOP\" — wir tragen Sie sofort aus.")
    return "\n".join(teile)


def missing_impressum_fields(meta: dict) -> list[str]:
    """Prüft die Impressums-PFLICHTangaben nach § 5 DDG: Name, ladungsfähige Anschrift und
    mindestens ein Kontaktweg (E-Mail oder Telefon). Gibt die Namen fehlender/Platzhalter-
    Felder zurück (leer = vollständig). Damit keine Seite mit `[bitte ergänzen]`-Impressum
    stillschweigend live geht."""
    def _fehlt(*keys) -> bool:
        for k in keys:
            v = str(meta.get(k) or "").strip()
            if v and v != _PH:
                return False
        return True
    fehlend: list[str] = []
    if _fehlt("name", "site_name"):
        fehlend.append("name")
    if _fehlt("adresse"):
        fehlend.append("adresse")
    if _fehlt("email", "email_adresse", "kontakt_email", "telefon"):
        fehlend.append("kontakt (email/telefon)")
    return fehlend


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
