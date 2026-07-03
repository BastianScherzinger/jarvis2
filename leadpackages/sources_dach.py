"""
Regionen + Branchen für LeadForge — DACH-weit (Entscheidung: Region-Scope = DACH).

Deutschland wird 1:1 aus der bestehenden scrapers/regions.py übernommen (kein
Duplikat, keine Änderung dort). Österreich + Schweiz sind hier neu ergänzt, in
gleicher {Region: [Stadt, ...]}-Form, damit dieselben Lookup-Muster gelten.

Diese Datei ist rein additiv (neues Modul) — scrapers/regions.py bleibt unberührt.
"""
from scrapers.regions import BRANCHEN, HIGH_VALUE  # unverändert wiederverwendet

# ── Österreich: 9 Bundesländer, wichtigste Städte ───────────────────────────
AT_BUNDESLAND_STAEDTE: dict[str, list[str]] = {
    "Wien": ["Wien"],
    "Niederösterreich": [
        "St. Pölten", "Wiener Neustadt", "Krems an der Donau", "Baden", "Mödling",
        "Amstetten", "Klosterneuburg", "Tulln an der Donau", "Stockerau", "Traiskirchen",
        "Schwechat", "Korneuburg", "Zwettl-Niederösterreich", "Neunkirchen", "Waidhofen an der Ybbs",
    ],
    "Oberösterreich": [
        "Linz", "Wels", "Steyr", "Leonding", "Traun",
        "Braunau am Inn", "Vöcklabruck", "Ansfelden", "Marchtrenk", "Bad Ischl",
        "Gmunden", "Enns", "Ried im Innkreis", "Freistadt", "Perg",
    ],
    "Salzburg": [
        "Salzburg", "Hallein", "Saalfelden am Steinernen Meer", "Bischofshofen", "Zell am See",
        "St. Johann im Pongau", "Seekirchen am Wallersee", "Wals-Siezenheim",
    ],
    "Tirol": [
        "Innsbruck", "Kufstein", "Telfs", "Schwaz", "Hall in Tirol",
        "Wörgl", "Lienz", "Imst", "Kitzbühel", "St. Johann in Tirol",
    ],
    "Vorarlberg": [
        "Dornbirn", "Feldkirch", "Bregenz", "Hohenems", "Lustenau",
        "Hard", "Götzis", "Bludenz",
    ],
    "Kärnten": [
        "Klagenfurt am Wörthersee", "Villach", "Wolfsberg", "Spittal an der Drau", "Feldkirchen in Kärnten",
        "Völkermarkt", "St. Veit an der Glan",
    ],
    "Steiermark": [
        "Graz", "Leoben", "Kapfenberg", "Bruck an der Mur", "Feldbach",
        "Knittelfeld", "Leibnitz", "Weiz", "Voitsberg", "Deutschlandsberg",
    ],
    "Burgenland": [
        "Eisenstadt", "Neusiedl am See", "Oberwart", "Güssing", "Mattersburg",
        "Jennersdorf",
    ],
}

_AT_STADT_BL = {s: bl for bl, staedte in AT_BUNDESLAND_STAEDTE.items() for s in staedte}
AT_STAEDTE: list[str] = list(dict.fromkeys(s for st in AT_BUNDESLAND_STAEDTE.values() for s in st))

# ── Schweiz: 26 Kantone, wichtigste Städte ──────────────────────────────────
CH_KANTON_STAEDTE: dict[str, list[str]] = {
    "Zürich": ["Zürich", "Winterthur", "Uster", "Dübendorf", "Dietikon", "Wetzikon", "Bülach"],
    "Bern": ["Bern", "Biel/Bienne", "Thun", "Köniz", "Ostermundigen", "Burgdorf", "Langenthal"],
    "Luzern": ["Luzern", "Emmen", "Kriens", "Horw", "Sursee"],
    "Uri": ["Altdorf"],
    "Schwyz": ["Schwyz", "Freienbach", "Einsiedeln", "Küssnacht am Rigi"],
    "Obwalden": ["Sarnen"],
    "Nidwalden": ["Stans"],
    "Glarus": ["Glarus", "Näfels"],
    "Zug": ["Zug", "Baar", "Cham", "Steinhausen"],
    "Freiburg": ["Freiburg", "Bulle", "Villars-sur-Glâne"],
    "Solothurn": ["Solothurn", "Olten", "Grenchen", "Zuchwil"],
    "Basel-Stadt": ["Basel"],
    "Basel-Landschaft": ["Allschwil", "Reinach", "Muttenz", "Liestal"],
    "Schaffhausen": ["Schaffhausen", "Neuhausen am Rheinfall"],
    "Appenzell Ausserrhoden": ["Herisau", "Teufen"],
    "Appenzell Innerrhoden": ["Appenzell"],
    "St. Gallen": ["St. Gallen", "Rapperswil-Jona", "Wil", "Gossau", "Buchs"],
    "Graubünden": ["Chur", "Davos", "St. Moritz"],
    "Aargau": ["Aarau", "Baden", "Wettingen", "Wohlen", "Rheinfelden"],
    "Thurgau": ["Frauenfeld", "Kreuzlingen", "Arbon", "Amriswil"],
    "Tessin": ["Lugano", "Bellinzona", "Locarno", "Mendrisio"],
    "Waadt": ["Lausanne", "Yverdon-les-Bains", "Montreux", "Nyon", "Renens"],
    "Wallis": ["Sion", "Monthey", "Martigny", "Brig-Glis"],
    "Neuenburg": ["Neuenburg", "La Chaux-de-Fonds"],
    "Genf": ["Genf", "Vernier", "Lancy", "Meyrin"],
    "Jura": ["Delémont", "Porrentruy"],
}

_CH_STADT_KT = {s: kt for kt, staedte in CH_KANTON_STAEDTE.items() for s in staedte}
CH_STAEDTE: list[str] = list(dict.fromkeys(s for st in CH_KANTON_STAEDTE.values() for s in st))


def get_region(land: str, stadt: str) -> str:
    """Bundesland (DE/AT) bzw. Kanton (CH) einer Stadt, sonst leer."""
    if land == "AT":
        return _AT_STADT_BL.get(stadt, "")
    if land == "CH":
        return _CH_STADT_KT.get(stadt, "")
    from scrapers.regions import get_bundesland
    return get_bundesland(stadt)


def staedte_fuer(land: str) -> list[str]:
    if land == "AT":
        return AT_STAEDTE
    if land == "CH":
        return CH_STAEDTE
    from scrapers.regions import ALLE_REGIONEN
    return ALLE_REGIONEN


LAENDER = ["DE", "AT", "CH"]
