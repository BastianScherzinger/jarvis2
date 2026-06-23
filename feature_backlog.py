"""
feature_backlog.py — Backlog konkreter, klein umsetzbarer Web-Features je Branche.

Der Nightly-Improver (claude_coder/local_coder) holt sich pro Seite das nächste noch
nicht eingebaute Feature und lässt es bauen. Welche Features eine Seite schon hat,
steht in content.json["features_added"] (Liste der Feature-Keys).

Jedes Feature: {key, label, spec}. 'spec' ist die präzise Bau-Anweisung — entweder
direkt an `claude -p` (Variante A) oder von Claude für die Seite verfeinert und dann
von der lokalen KI gebaut (Variante B).
"""
from __future__ import annotations

# Universelle Features (für JEDE Branche sinnvoll) — kommen nach den Branchen-Features.
_GENERIC = [
    {"key": "oeffnungszeiten", "label": "Öffnungszeiten-Box",
     "spec": "Füge eine klare Öffnungszeiten-Sektion hinzu (Mo–So) mit gut lesbarer "
             "Tabelle/Liste und einem 'heute geöffnet'-Hinweis. Daten als content.json-Feld "
             "'oeffnungszeiten' (Liste {tag, zeit}); Template-Sektion ergänzen, design-pro."},
    {"key": "faq", "label": "FAQ-Akkordeon",
     "spec": "Füge eine FAQ-Sektion als zugängliches <details>-Akkordeon mit 4-6 branchen-"
             "typischen Fragen/Antworten hinzu (content.json['faq'] = [{frage, antwort}])."},
    {"key": "bewertungen", "label": "Bewertungs-/Kundenstimmen-Slider",
     "spec": "Füge 3-4 glaubwürdige Kundenstimmen (Name, Ort, kurzer Text, 5 Sterne) als "
             "content.json['bewertungen'] hinzu und eine ansprechende Sektion (Karten/Slider)."},
    {"key": "kontaktformular", "label": "Anfrage-/Kontaktformular",
     "spec": "Füge ein schlankes Anfrageformular hinzu (Name, Telefon/E-Mail, Anliegen) das "
             "per POST an die bestehende Django-Anfrage-View/Route geht oder als mailto-"
             "Fallback. Labels, Pflichtfelder dezent, mobil bedienbar, ein klarer Submit-CTA."},
    {"key": "karte", "label": "Standort-Karte (OpenStreetMap)",
     "spec": "Bette eine schlanke Standort-Karte (OpenStreetMap iframe, kein API-Key) zur "
             "Adresse/Stadt ein, plus Anfahrt-Hinweis. Nur wenn Stadt/Adresse vorhanden."},
    {"key": "sticky_cta", "label": "Mobiler Sticky-CTA",
     "spec": "Füge mobil einen dauerhaft sichtbaren 'Anrufen'-Button (tel:) am unteren "
             "Rand hinzu (position:fixed, nur <760px), ohne Desktop zu stören."},
    {"key": "stats_counter", "label": "Stats-Counter mit Animation",
     "spec": "Füge eine Stats-Sektion mit 3 animierten Zählern hinzu: Jahre Erfahrung, Kunden bedient, Bewertungen. "
             "Die Zähler (class='count-up', data-target=ZAHL) laufen hoch wenn der Nutzer scrollt. "
             "Daten in content.json['jahre_erfahrung'], content.json['kunden_bedient']. JS-Datei counter_up.js "
             "muss im Template eingebunden sein: "
             "<script src=\"{% static 'js/counter_up.js' %}\"></script>"},
    {"key": "testimonials", "label": "Kundenstimmen-Sektion",
     "spec": "Füge eine Bewertungs-/Kundenstimmen-Sektion hinzu (content.json['bewertungen'] = [{name, ort, text}]). "
             "3-4 glaubwürdige, branchenspezifische Kundenstimmen (keine leeren Floskeln). "
             "Grid-Layout, je Karte: Name, Ort, Text, 5 Sterne. Seriös, kein Slider (Zugänglichkeit)."},
    {"key": "process_steps", "label": "Ablauf in 3 Schritten",
     "spec": "Füge eine 'So funktioniert es'-Sektion (3 Schritte) hinzu. Schritt-Nummer als large accent-farbene Zahl. "
             "content.json['process_steps'] = [{schritt:'1', titel:'Anfrage', text:'...'}]. Konvertierungsstark."},
    {"key": "team_sektion", "label": "Team-Vorstellung",
     "spec": "Füge eine Team-/Über-uns-Sektion mit Mitarbeiter-Karten hinzu. "
             "content.json['team'] = [{name:'...', rolle:'...'}]. Fotos optional (Platzhalter-Monogramm wenn kein Bild). "
             "Menschlich, vertrauenswürdig. Max 4 Personen."},
]

# Branchen-spezifische Features (Reihenfolge = Priorität).
_BACKLOG = {
    "dachdecker": [
        {"key": "leistungs_kacheln", "label": "Leistungs-Kacheln",
         "spec": "Strukturiere die Leistungen als Kacheln (Steildach, Flachdach, Dachfenster, "
                 "Reparatur) mit Icon/Strich und kurzem Nutzen-Text."},
        {"key": "notdienst", "label": "Notdienst-Banner",
         "spec": "Füge ein dezentes Notdienst-Banner hinzu ('Sturmschaden? 24h erreichbar') "
                 "mit klickbarer Telefonnummer."},
        {"key": "referenzen", "label": "Referenz-Galerie",
         "spec": "Füge eine Referenz-Galerie (content.json['referenzen'] = [{titel, ort, jahr}]) "
                 "mit Vorher/Nachher-Gedanken und sauberem Grid hinzu."},
    ],
    "elektr": [
        {"key": "leistungs_kacheln", "label": "Service-Liste",
         "spec": "Service-Kacheln: Installation, Smart Home, E-Check, Photovoltaik/Wallbox."},
        {"key": "notdienst", "label": "Notdienst-Sticky",
         "spec": "Notdienst-Hinweis 'rund um die Uhr' mit klickbarer Telefonnummer."},
        {"key": "foerderung", "label": "Förder-Hinweisbox",
         "spec": "Info-Box zu PV/Wallbox-Förderung mit kurzem Vertrauens-Text."},
    ],
    "kfz": [
        {"key": "preisliste", "label": "Service-Preisliste",
         "spec": "Füge eine übersichtliche Service-/Inspektions-Preisliste als Tabelle hinzu "
                 "(content.json['preisliste'] = [{leistung, preis}])."},
        {"key": "hu_au", "label": "HU/AU-Hinweisbox",
         "spec": "Hinweisbox 'HU/AU bei uns möglich' + Rückruf-/Termin-Anstoß."},
        {"key": "marken", "label": "Marken-Logo-Leiste",
         "spec": "Leiste 'Wir warten alle Fabrikate' mit Marken-Textbadges (content.json['marken'])."},
    ],
    "friseur": [
        {"key": "preisliste", "label": "Preisliste Damen/Herren/Kinder",
         "spec": "Preisliste nach Damen/Herren/Kinder (content.json['preisliste'])."},
        {"key": "lookbook", "label": "Lookbook-Galerie",
         "spec": "Lookbook-Grid aus den vorhandenen Fotos mit Hover-Zoom."},
        {"key": "team", "label": "Team-Sektion",
         "spec": "Team-Sektion (content.json['team'] = [{name, rolle}]) mit Karten."},
    ],
    "restaurant": [
        {"key": "speisekarte", "label": "Speisekarte-Sektion",
         "spec": "Gegliederte Speisekarte (content.json['speisekarte'] = [{kategorie, items:[{name,preis}]}])."},
        {"key": "reservierung", "label": "Tisch-Reservierung",
         "spec": "Reservierungsformular (Datum/Uhrzeit/Personen) + Telefon-Fallback."},
        {"key": "galerie", "label": "Ambiente-Galerie",
         "spec": "Galerie (Gerichte/Ambiente) als Grid mit Lightbox-Gedanken."},
    ],
    "umzug": [
        {"key": "umzugsanfrage", "label": "Umzugsanfrage-Formular",
         "spec": "Anfrageformular Von/Nach, Zimmerzahl, Wunschdatum."},
        {"key": "kostenrechner", "label": "Einfacher Kostenrechner",
         "spec": "Schlanker JS-Kostenrechner (Zimmer × Entfernung, grobe Schätzung) — rein "
                 "clientseitig, ohne Backend, render-sicher."},
        {"key": "ablauf", "label": "Ablauf-Stepper",
         "spec": "Ablauf 'Anfrage → Besichtigung → Umzug' als 3-Schritt-Stepper."},
    ],
    "arzt": [
        {"key": "sprechzeiten", "label": "Sprechzeiten-Box",
         "spec": "Sprech-/Telefonsprechzeiten als klare Box (content.json['sprechzeiten'])."},
        {"key": "leistungen_med", "label": "Behandlungsspektrum",
         "spec": "Behandlungs-/Leistungsliste der Praxis."},
        {"key": "team", "label": "Ärzte-/Team-Vorstellung",
         "spec": "Team-Sektion mit Name + Qualifikation (content.json['team'])."},
    ],
    "heizung": [
        {"key": "leistungs_kacheln", "label": "Heizsystem-Kacheln",
         "spec": "Strukturiere die Leistungen als Kacheln (Gas, Wärme, Solar, Wartung) "
                 "mit Icon/Strich und kurzem Nutzen-Text."},
        {"key": "notdienst", "label": "Notdienst-Banner",
         "spec": "Füge ein dezentes Notdienst-Banner hinzu ('Heizung ausgefallen? 24h erreichbar') "
                 "mit klickbarer Telefonnummer."},
        {"key": "foerderung", "label": "Förderhinweis-Box (BAFA/KfW)",
         "spec": "Info-Box zu aktuellen Heizungs-Förderungen (BAFA, KfW) mit kurzem Vertrauens-Text "
                 "und Link zur Förderberatung (content.json['foerderung_hinweis'])."},
    ],
    "maler": [
        {"key": "referenzen", "label": "Referenz-Galerie (Vorher/Nachher)",
         "spec": "Füge eine Referenz-Galerie als Vorher/Nachher-Grid hinzu "
                 "(content.json['referenzen'] = [{titel, ort, vorher_bild, nachher_bild}]) "
                 "mit sauberem Grid-Layout."},
        {"key": "farbberatung_cta", "label": "Farbberatungs-CTA",
         "spec": "Füge einen auffälligen CTA-Block für kostenlose Farbberatung hinzu "
                 "('Kostenlose Farbberatung anfordern') mit Telefon und Kontaktformular-Link."},
        {"key": "leistungs_kacheln", "label": "Leistungskacheln",
         "spec": "Strukturiere die Leistungen als Kacheln (Innenarbeiten, Außenarbeiten, Tapezieren) "
                 "mit Icon und kurzem Nutzen-Text."},
    ],
    "reinigung": [
        {"key": "service_pakete", "label": "Service-Pakete-Tabelle",
         "spec": "Füge eine Vergleichstabelle der Service-Pakete hinzu (Büroreinigung, Privatreinigung, "
                 "Fensterreinigung) — content.json['service_pakete'] = [{name, leistungen:[...], preis_ab}]."},
        {"key": "sofort_anfrage", "label": "Sofort-Anfrage-Formular",
         "spec": "Füge ein schlankes Sofort-Anfrage-Formular hinzu (Art der Reinigung, Fläche in qm, "
                 "Wunschtermin, Kontakt) — per POST oder mailto-Fallback."},
        {"key": "team", "label": "Team-Vorstellung",
         "spec": "Team-Sektion mit Name + Funktion (content.json['team'] = [{name, rolle}]) "
                 "mit Karten und optionalem Monogramm-Platzhalter."},
    ],
    "schreiner": [
        {"key": "portfolio", "label": "Portfolio-Galerie (Möbel/Einbauten)",
         "spec": "Füge eine Portfolio-Galerie mit Fotos individueller Möbelstücke und Einbauten hinzu "
                 "(content.json['portfolio'] = [{titel, beschreibung, bild}]) als sauberes Grid."},
        {"key": "material_auswahl", "label": "Material-Auswahl-Box",
         "spec": "Füge eine Info-Box mit verfügbaren Holzarten und Materialien hinzu "
                 "(content.json['materialien'] = [{name, beschreibung}]) — ansprechend, vertrauensbildend."},
        {"key": "aufmass_cta", "label": "Aufmaß-Termin CTA",
         "spec": "Füge einen klaren CTA-Block für einen kostenlosen Aufmaß-Termin hinzu "
                 "('Kostenloses Aufmaß vereinbaren') mit Telefon und kurzer Terminanfrage."},
    ],
    "physiotherapeut": [
        {"key": "behandlungsangebot", "label": "Behandlungsangebot-Grid",
         "spec": "Strukturiere das Behandlungsangebot als Grid-Kacheln (Massage, KG, MLD, Sportphysio usw.) "
                 "(content.json['behandlungen'] = [{name, beschreibung}]) mit Icon und kurzem Text."},
        {"key": "online_termin", "label": "Online-Terminbuchung CTA",
         "spec": "Füge einen auffälligen CTA-Block für Online-Terminbuchung hinzu "
                 "('Termin online buchen') mit Link/Button und optionaler Telefonnummer."},
        {"key": "team", "label": "Therapeuten-Sektion",
         "spec": "Team-Sektion mit Name, Qualifikation und Schwerpunkten "
                 "(content.json['team'] = [{name, rolle, schwerpunkte}]) mit Karten."},
    ],
    "steuerberater": [
        {"key": "leistungsuebersicht", "label": "Leistungsübersicht",
         "spec": "Füge eine strukturierte Leistungsübersicht hinzu (Jahresabschluss, Lohnbuchhaltung, "
                 "Steuerberatung, Unternehmensberatung) als Kacheln oder Tabelle "
                 "(content.json['leistungen'] = [{name, beschreibung}])."},
        {"key": "mandanten_stats", "label": "Mandanten-Zahlen Stats",
         "spec": "Füge eine Stats-Sektion hinzu (Jahre Erfahrung, betreute Mandate, Mitarbeiter) "
                 "(content.json['stats'] = [{zahl, einheit, beschreibung}]) — seriös, vertrauensstärkend."},
        {"key": "termin_buchung", "label": "Termin-Buchung",
         "spec": "Füge einen Termin-Buchungs-CTA hinzu ('Erstgespräch vereinbaren') "
                 "mit Kontaktformular oder Telefon — niedrigschwellig und professionell."},
    ],
    "rechtsanwalt": [
        {"key": "rechtsgebiete", "label": "Rechtsgebiete-Kacheln",
         "spec": "Strukturiere die Rechtsgebiete als Kacheln (Arbeitsrecht, Familienrecht, Strafrecht usw.) "
                 "(content.json['rechtsgebiete'] = [{name, beschreibung}]) mit Icon und kurzem Text."},
        {"key": "erstberatung_cta", "label": "Erstberatung-CTA",
         "spec": "Füge einen prominenten CTA-Block für eine Erstberatung hinzu "
                 "('Erstberatung vereinbaren') mit Telefon, E-Mail und kurzem Vertrauenstext."},
        {"key": "team", "label": "Kanzlei-Team",
         "spec": "Team-Sektion mit Name, Rechtsgebiet und Qualifikation "
                 "(content.json['team'] = [{name, rolle, schwerpunkte}]) — seriös, professionell."},
    ],
    "zahnarzt": [
        {"key": "behandlungsspektrum", "label": "Behandlungsspektrum-Grid",
         "spec": "Strukturiere das Behandlungsspektrum als Grid-Kacheln (Prophylaxe, Zahnersatz, "
                 "Implantate, Ästhetik usw.) (content.json['behandlungen'] = [{name, beschreibung}])."},
        {"key": "angstpatienten", "label": "Angstpatienten-Sektion",
         "spec": "Füge eine einfühlsame Sektion für Angstpatienten hinzu — kurzer Text, "
                 "Beruhigung, Hinweis auf sanfte Behandlung und Betäubungsmöglichkeiten "
                 "(content.json['angstpatienten_text'])."},
        {"key": "online_termin", "label": "Online-Termin buchen",
         "spec": "Füge einen auffälligen CTA-Block für Online-Terminbuchung hinzu "
                 "('Termin online buchen') mit Link/Button und optionaler Telefonnummer."},
    ],
}

# Mapping von Branchen-Stichwörtern auf Backlog-Schlüssel.
_ALIASES = {
    "dachdecker": "dachdecker", "dach": "dachdecker", "bedach": "dachdecker",
    "elektr": "elektr", "elektro": "elektr",
    "kfz": "kfz", "auto": "kfz", "werkstatt": "kfz", "reifen": "kfz",
    "friseur": "friseur", "frisör": "friseur", "haar": "friseur", "kosmetik": "friseur",
    "restaurant": "restaurant", "gastro": "restaurant", "café": "restaurant",
    "cafe": "restaurant", "bäcker": "restaurant", "imbiss": "restaurant",
    "umzug": "umzug", "umzüge": "umzug", "transport": "umzug",
    "arzt": "arzt", "praxis": "arzt", "therapie": "arzt",
    "logopäd": "arzt", "heilprakt": "arzt",
    "heizung": "heizung", "klempner": "heizung", "sanitär": "heizung",
    "maler": "maler", "streicher": "maler",
    "reinigung": "reinigung", "reinig": "reinigung", "gebäude": "reinigung",
    "schreiner": "schreiner", "tischler": "schreiner", "zimmerer": "schreiner",
    "physiotherapeut": "physiotherapeut", "physio": "physiotherapeut",
    "therapeut": "physiotherapeut",
    "steuerberater": "steuerberater", "steuer": "steuerberater",
    "buchhalter": "steuerberater",
    "rechtsanwalt": "rechtsanwalt", "anwalt": "rechtsanwalt", "kanzlei": "rechtsanwalt",
    "zahnarzt": "zahnarzt",
}


def _match_branche(branche: str) -> "str | None":
    b = (branche or "").lower()
    for stich, key in _ALIASES.items():
        if stich in b:
            return key
    return None


def features_for(branche: str) -> list[dict]:
    """Branchen-Features zuerst, dann universelle. Dedupliziert nach key."""
    seen, out = set(), []
    for f in _BACKLOG.get(_match_branche(branche) or "", []) + _GENERIC:
        if f["key"] not in seen:
            seen.add(f["key"])
            out.append(f)
    return out


def next_feature(branche: str, content: dict) -> "dict | None":
    """Nächstes noch nicht eingebautes Feature (oder None, wenn alle vorhanden)."""
    done = set((content or {}).get("features_added") or [])
    for f in features_for(branche):
        if f["key"] not in done:
            return f
    return None


def mark_done(content: dict, key: str) -> dict:
    """Markiert ein Feature in der content.json als eingebaut (idempotent)."""
    arr = content.setdefault("features_added", [])
    if key not in arr:
        arr.append(key)
    return content
