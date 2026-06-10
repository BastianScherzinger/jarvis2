"""
Regionen + Branchen für den Lead-Scanner.
Berlin (12 Bezirke) + Schleswig-Holstein (9 Städte).
"""

BERLIN_BEZIRKE = [
    "Berlin Mitte", "Berlin Prenzlauer Berg", "Berlin Friedrichshain",
    "Berlin Kreuzberg", "Berlin Neukölln", "Berlin Tempelhof",
    "Berlin Charlottenburg", "Berlin Spandau", "Berlin Pankow",
    "Berlin Lichtenberg", "Berlin Marzahn", "Berlin Steglitz",
]

SH_STAEDTE = [
    "Kiel", "Lübeck", "Flensburg", "Neumünster",
    "Norderstedt", "Elmshorn", "Pinneberg", "Itzehoe", "Heide",
]

ALLE_REGIONEN = BERLIN_BEZIRKE + SH_STAEDTE

BRANCHEN = [
    # Handwerk — höchster Wert
    "Elektriker", "Klempner", "Heizungsbauer", "Maler", "Dachdecker",
    "Fliesenleger", "Schreiner", "Schlosser", "Sanitär",
    # Bau
    "Bauunternehmen", "Gerüstbau", "Trockenbau", "Fenster Türen",
    # Gesundheit
    "Physiotherapeut", "Heilpraktiker", "Zahnarzt", "Optiker",
    # Kfz
    "KFZ Werkstatt", "Reifenhandel", "Autoaufbereitung",
    # Dienstleistung
    "Friseur", "Kosmetik", "Reinigung", "Umzugsunternehmen",
    "Schlüsseldienst", "Tierarzt",
    # Gastronomie
    "Restaurant", "Café", "Bäckerei", "Catering",
]

# Branchen mit höchstem Honorar → höherer Score-Bonus
HIGH_VALUE = {
    "Elektriker", "Klempner", "Heizungsbauer", "Dachdecker",
    "Bauunternehmen", "Sanitär", "Schreiner", "KFZ Werkstatt",
    "Physiotherapeut", "Zahnarzt", "Umzugsunternehmen",
}

KETTEN_KEYWORDS = [
    "mcdonalds", "burger king", "subway", "starbucks", "rewe", "edeka",
    "lidl", "aldi", "dm ", "rossmann", "obi ", "bauhaus", "hornbach",
    "saturn", "mediamarkt", "ikea", "h&m", "zara", "netto", "penny",
    "woolworth", "action", "tedi",
]
