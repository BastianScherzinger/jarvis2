"""
Regionen + Branchen für den Lead-Scanner.
Deutschland-weit: alle 16 Bundesländer, ~1000+ Städte bis zur Kleinstadt.

BUNDESLAND_STAEDTE  → {Bundesland: [Stadt, ...]}
get_bundesland(stadt) → schnelles Lookup Stadt → Bundesland
ALLE_REGIONEN       → flache Liste aller Städtenamen
"""

BUNDESLAND_STAEDTE: dict[str, list[str]] = {
    "Baden-Württemberg": [
        "Stuttgart", "Karlsruhe", "Mannheim", "Freiburg im Breisgau", "Heidelberg",
        "Heilbronn", "Ulm", "Pforzheim", "Reutlingen", "Esslingen am Neckar",
        "Ludwigsburg", "Tübingen", "Villingen-Schwenningen", "Konstanz", "Aalen",
        "Sindelfingen", "Schwäbisch Gmünd", "Friedrichshafen", "Offenburg", "Göppingen",
        "Waiblingen", "Ravensburg", "Böblingen", "Lörrach", "Baden-Baden",
        "Fellbach", "Kornwestheim", "Leonberg", "Bietigheim-Bissingen", "Nürtingen",
        "Ostfildern", "Remseck am Neckar", "Backnang", "Schorndorf", "Weinheim",
        "Bruchsal", "Singen", "Rastatt", "Schwäbisch Hall", "Bühl",
        "Kehl", "Crailsheim", "Wertheim", "Tuttlingen", "Rottweil",
        "Balingen", "Albstadt", "Sigmaringen", "Biberach an der Riß", "Weingarten",
        "Bad Mergentheim", "Mosbach", "Tauberbischofsheim", "Künzelsau", "Öhringen",
        "Vaihingen an der Enz", "Mühlacker", "Calw", "Nagold", "Herrenberg",
        "Filderstadt", "Leinfelden-Echterdingen", "Kirchheim unter Teck", "Geislingen an der Steige",
        "Eislingen", "Plochingen", "Wendlingen", "Metzingen", "Pfullingen",
        "Überlingen", "Radolfzell", "Stockach", "Waldkirch", "Emmendingen",
        "Lahr", "Achern", "Gaggenau", "Ettlingen", "Stutensee",
        "Waldshut-Tiengen", "Bad Säckingen", "Rheinfelden", "Weil am Rhein", "Schopfheim",
        "Wangen im Allgäu", "Leutkirch", "Bad Saulgau", "Ehingen", "Laupheim",
        "Bad Waldsee", "Spaichingen", "Donaueschingen", "Bad Krozingen", "Müllheim",
    ],
    "Bayern": [
        "München", "Nürnberg", "Augsburg", "Regensburg", "Ingolstadt",
        "Würzburg", "Fürth", "Erlangen", "Bayreuth", "Bamberg",
        "Aschaffenburg", "Landshut", "Kempten", "Rosenheim", "Neu-Ulm",
        "Schweinfurt", "Passau", "Hof", "Freising", "Straubing",
        "Dachau", "Memmingen", "Weiden in der Oberpfalz", "Kaufbeuren", "Coburg",
        "Garmisch-Partenkirchen", "Ansbach", "Schwabach", "Landsberg am Lech", "Traunstein",
        "Weilheim in Oberbayern", "Germering", "Unterschleißheim", "Olching", "Fürstenfeldbruck",
        "Puchheim", "Gröbenzell", "Karlsfeld", "Neuburg an der Donau", "Pfaffenhofen an der Ilm",
        "Eichstätt", "Gunzenhausen", "Roth", "Forchheim", "Herzogenaurach",
        "Lichtenfels", "Kronach", "Kulmbach", "Marktredwitz", "Selb",
        "Tirschenreuth", "Amberg", "Sulzbach-Rosenberg", "Schwandorf", "Cham",
        "Neumarkt in der Oberpfalz", "Deggendorf", "Plattling", "Vilshofen", "Pocking",
        "Dingolfing", "Vilsbiburg", "Mühldorf am Inn", "Altötting", "Burghausen",
        "Waldkraiburg", "Bad Reichenhall", "Freilassing", "Berchtesgaden", "Prien am Chiemsee",
        "Wasserburg am Inn", "Ebersberg", "Grafing", "Markt Schwaben", "Erding",
        "Dorfen", "Moosburg an der Isar", "Geisenfeld", "Schrobenhausen", "Aichach",
        "Friedberg", "Königsbrunn", "Gersthofen", "Neusäß", "Stadtbergen",
        "Bobingen", "Schwabmünchen", "Donauwörth", "Nördlingen", "Dillingen an der Donau",
        "Günzburg", "Krumbach", "Mindelheim", "Bad Wörishofen", "Buchloe",
        "Marktoberdorf", "Füssen", "Sonthofen", "Immenstadt im Allgäu", "Lindau",
        "Lindenberg im Allgäu", "Starnberg", "Gauting", "Herrsching am Ammersee", "Tutzing",
        "Murnau am Staffelsee", "Penzberg", "Bad Tölz", "Geretsried", "Wolfratshausen",
        "Holzkirchen", "Miesbach", "Tegernsee", "Bad Aibling", "Kolbermoor",
        "Haar", "Vaterstetten", "Ottobrunn", "Unterhaching",
        "Taufkirchen", "Neubiberg", "Garching bei München", "Ismaning", "Unterföhring",
        "Bad Kissingen", "Bad Neustadt an der Saale", "Haßfurt", "Ebern", "Zeil am Main",
        "Volkach", "Kitzingen", "Ochsenfurt", "Marktheidenfeld", "Lohr am Main",
        "Gemünden am Main", "Karlstadt", "Veitshöchheim", "Höchberg", "Rimpar",
        "Hammelburg", "Mellrichstadt", "Bad Brückenau", "Münnerstadt", "Gerolzhofen",
        "Rothenburg ob der Tauber", "Dinkelsbühl", "Feuchtwangen", "Wassertrüdingen", "Treuchtlingen",
        "Weißenburg in Bayern", "Pleinfeld", "Hilpoltstein", "Allersberg", "Greding",
    ],
    "Berlin": [
        "Berlin Mitte", "Berlin Prenzlauer Berg", "Berlin Friedrichshain",
        "Berlin Kreuzberg", "Berlin Neukölln", "Berlin Tempelhof",
        "Berlin Charlottenburg", "Berlin Spandau", "Berlin Pankow",
        "Berlin Lichtenberg", "Berlin Marzahn", "Berlin Steglitz",
    ],
    "Brandenburg": [
        "Potsdam", "Cottbus", "Brandenburg an der Havel", "Frankfurt (Oder)", "Oranienburg",
        "Falkensee", "Eberswalde", "Königs Wusterhausen", "Bernau bei Berlin", "Fürstenwalde",
        "Schwedt/Oder", "Strausberg", "Hennigsdorf", "Neuruppin", "Rathenow",
        "Senftenberg", "Ludwigsfelde", "Luckenwalde", "Teltow", "Werder (Havel)",
        "Wittenberge", "Prenzlau", "Forst (Lausitz)", "Spremberg", "Guben",
        "Lübben", "Lübbenau", "Finsterwalde", "Herzberg (Elster)", "Jüterbog",
        "Zossen", "Wildau", "Blankenfelde-Mahlow", "Hohen Neuendorf", "Velten",
        "Kleinmachnow", "Stahnsdorf", "Erkner", "Rüdersdorf", "Nauen",
        "Beelitz", "Treuenbrietzen", "Belzig", "Pritzwalk", "Perleberg",
        "Wittstock/Dosse", "Kyritz", "Neustadt (Dosse)", "Lauchhammer", "Großräschen",
        "Calau", "Vetschau", "Doberlug-Kirchhain", "Elsterwerda", "Bad Liebenwerda",
        "Müllrose", "Beeskow", "Storkow", "Mittenwalde", "Trebbin",
        "Bad Belzig", "Brück", "Niemegk", "Ziesar", "Lehnin",
    ],
    "Bremen": [
        "Bremen", "Bremerhaven", "Bremen Vegesack", "Bremen Hemelingen",
        "Bremen Burglesum", "Bremen Osterholz", "Bremen Walle",
    ],
    "Hamburg": [
        "Hamburg", "Hamburg Altona", "Hamburg Eimsbüttel", "Hamburg Wandsbek",
        "Hamburg Harburg", "Hamburg Bergedorf", "Hamburg Nord", "Hamburg Mitte",
    ],
    "Hessen": [
        "Frankfurt am Main", "Wiesbaden", "Kassel", "Darmstadt", "Offenbach am Main",
        "Hanau", "Marburg", "Gießen", "Fulda", "Rüsselsheim",
        "Wetzlar", "Bad Homburg", "Oberursel", "Rödermark", "Dreieich",
        "Langen", "Neu-Isenburg", "Maintal", "Bad Vilbel", "Mörfelden-Walldorf",
        "Rodgau", "Hofheim am Taunus", "Kelkheim", "Eschborn", "Königstein im Taunus",
        "Friedberg", "Bad Nauheim", "Butzbach", "Limburg an der Lahn", "Weilburg",
        "Dillenburg", "Herborn", "Bad Hersfeld", "Rotenburg an der Fulda", "Eschwege",
        "Korbach", "Frankenberg", "Baunatal", "Vellmar", "Melsungen",
        "Witzenhausen", "Hofgeismar", "Wolfhagen", "Schwalmstadt", "Homberg (Efze)",
        "Alsfeld", "Lauterbach", "Hünfeld", "Schlüchtern", "Gelnhausen",
        "Bad Orb", "Seligenstadt", "Dietzenbach", "Heusenstamm", "Obertshausen",
        "Groß-Gerau", "Kelsterbach", "Raunheim", "Viernheim", "Lampertheim",
        "Bensheim", "Heppenheim", "Lorsch", "Michelstadt", "Erbach",
    ],
    "Mecklenburg-Vorpommern": [
        "Rostock", "Schwerin", "Neubrandenburg", "Stralsund", "Greifswald",
        "Wismar", "Güstrow", "Waren (Müritz)", "Neustrelitz", "Parchim",
        "Bergen auf Rügen", "Wolgast", "Anklam", "Ribnitz-Damgarten", "Grevesmühlen",
        "Bad Doberan", "Ludwigslust", "Hagenow", "Boizenburg", "Demmin",
        "Pasewalk", "Ueckermünde", "Teterow", "Malchin", "Sassnitz",
        "Barth", "Grimmen", "Stavenhagen", "Röbel", "Plau am See",
        "Crivitz", "Sternberg", "Bützow", "Gadebusch", "Rehna",
    ],
    "Niedersachsen": [
        "Hannover", "Braunschweig", "Osnabrück", "Oldenburg", "Wolfsburg",
        "Göttingen", "Hildesheim", "Salzgitter", "Wilhelmshaven", "Delmenhorst",
        "Lüneburg", "Celle", "Garbsen", "Hameln", "Lingen",
        "Langenhagen", "Nordhorn", "Wolfenbüttel", "Goslar", "Peine",
        "Emden", "Cuxhaven", "Stade", "Melle", "Neustadt am Rübenberge",
        "Wunstorf", "Laatzen", "Seelze", "Buxtehude", "Achim",
        "Verden", "Nienburg", "Stadthagen", "Bückeburg", "Springe",
        "Barsinghausen", "Gehrden", "Burgdorf", "Lehrte", "Sehnde",
        "Uelzen", "Winsen (Luhe)", "Buchholz in der Nordheide", "Soltau", "Walsrode",
        "Munster", "Bad Harzburg", "Seesen", "Northeim", "Einbeck",
        "Osterode am Harz", "Holzminden", "Bad Pyrmont", "Alfeld", "Elze",
        "Cloppenburg", "Vechta", "Friesoythe", "Westerstede", "Bad Zwischenahn",
        "Varel", "Jever", "Aurich", "Leer", "Norden",
        "Papenburg", "Meppen", "Haren", "Georgsmarienhütte", "Bramsche",
        "Quakenbrück", "Bad Essen", "Bohmte", "Wallenhorst", "Belm",
        "Rinteln", "Obernkirchen", "Helmstedt", "Königslutter", "Schöningen",
        "Gifhorn", "Wittingen", "Sarstedt", "Bad Salzdetfurth", "Gronau (Leine)",
        "Bad Gandersheim", "Dassel", "Uslar", "Hardegsen", "Moringen",
        "Bovenden", "Duderstadt", "Hann. Münden", "Adelebsen", "Stadtoldendorf",
        "Bad Münder", "Coppenbrügge", "Salzhemmendorf", "Eldagsen", "Lauenau",
    ],
    "Nordrhein-Westfalen": [
        "Köln", "Düsseldorf", "Dortmund", "Essen", "Duisburg",
        "Bochum", "Wuppertal", "Bielefeld", "Bonn", "Münster",
        "Mönchengladbach", "Gelsenkirchen", "Aachen", "Krefeld", "Oberhausen",
        "Hagen", "Hamm", "Mülheim an der Ruhr", "Leverkusen", "Solingen",
        "Herne", "Neuss", "Paderborn", "Bottrop", "Recklinghausen",
        "Remscheid", "Bergisch Gladbach", "Moers", "Siegen", "Witten",
        "Gütersloh", "Iserlohn", "Düren", "Ratingen", "Lünen",
        "Marl", "Velbert", "Minden", "Viersen", "Dorsten",
        "Rheine", "Detmold", "Castrop-Rauxel", "Troisdorf", "Gladbeck",
        "Arnsberg", "Lüdenscheid", "Bocholt", "Dinslaken", "Herford",
        "Kerpen", "Unna", "Euskirchen", "Hürth", "Kaarst",
        "Grevenbroich", "Wesel", "Hilden", "Sankt Augustin", "Stolberg",
        "Eschweiler", "Menden", "Bergkamen", "Frechen", "Bornheim",
        "Lippstadt", "Erftstadt", "Pulheim", "Wülfrath", "Langenfeld",
        "Monheim am Rhein", "Meerbusch", "Kamp-Lintfort", "Goch", "Kleve",
        "Geldern", "Emmerich am Rhein", "Kevelaer", "Straelen", "Nettetal",
        "Willich", "Kempen", "Tönisvorst", "Korschenbroich", "Jüchen",
        "Dormagen", "Rommerskirchen", "Brühl", "Wesseling", "Niederkassel",
        "Lohmar", "Siegburg", "Hennef", "Königswinter", "Bad Honnef",
        "Rheinbach", "Mechernich", "Schleiden", "Zülpich", "Würselen",
        "Alsdorf", "Herzogenrath", "Baesweiler", "Jülich", "Erkelenz",
        "Hückelhoven", "Geilenkirchen", "Heinsberg", "Wegberg", "Wassenberg",
        "Beckum", "Ahlen", "Oelde", "Warendorf", "Telgte",
        "Greven", "Emsdetten", "Steinfurt", "Ibbenbüren", "Lengerich",
        "Coesfeld", "Dülmen", "Lüdinghausen", "Borken", "Ahaus",
        "Gronau", "Vreden", "Stadtlohn", "Bad Salzuflen", "Lemgo",
        "Bünde", "Löhne", "Vlotho", "Espelkamp", "Lübbecke",
        "Petershagen", "Porta Westfalica", "Hövelhof", "Schloß Holte-Stukenbrock", "Verl",
        "Halle (Westfalen)", "Versmold", "Harsewinkel", "Rietberg", "Rheda-Wiedenbrück",
        "Bad Oeynhausen", "Soest", "Werl", "Möhnesee", "Schwerte",
        "Holzwickede", "Fröndenberg", "Wickede", "Balve", "Sundern",
        "Meschede", "Brilon", "Olpe", "Attendorn", "Lennestadt",
        "Kreuztal", "Netphen", "Bad Berleburg", "Hilchenbach", "Freudenberg",
        "Bad Driburg", "Brakel", "Höxter", "Warburg", "Steinheim",
        "Bad Lippspringe", "Delbrück", "Salzkotten", "Büren", "Geseke",
        "Erwitte", "Rüthen", "Warstein", "Anröchte", "Ennepetal",
        "Gevelsberg", "Schwelm", "Sprockhövel", "Wetter (Ruhr)", "Herdecke",
        "Hattingen", "Breckerfeld", "Hemer", "Plettenberg", "Werdohl",
        "Altena", "Neuenrade", "Halver", "Kierspe", "Meinerzhagen",
    ],
    "Rheinland-Pfalz": [
        "Mainz", "Ludwigshafen am Rhein", "Koblenz", "Trier", "Kaiserslautern",
        "Worms", "Neuwied", "Neustadt an der Weinstraße", "Speyer", "Frankenthal",
        "Bad Kreuznach", "Pirmasens", "Zweibrücken", "Andernach", "Idar-Oberstein",
        "Landau in der Pfalz", "Bingen am Rhein", "Ingelheim am Rhein", "Mayen", "Bad Neuenahr-Ahrweiler",
        "Sinzig", "Remagen", "Lahnstein", "Boppard", "Bad Ems",
        "Montabaur", "Westerburg", "Diez", "Limburgerhof", "Haßloch",
        "Grünstadt", "Eisenberg", "Alzey", "Nieder-Olm", "Bodenheim",
        "Wörrstadt", "Kirn", "Meisenheim", "Lauterecken", "Rockenhausen",
        "Kirchheimbolanden", "Germersheim", "Wörth am Rhein", "Kandel", "Bad Bergzabern",
        "Annweiler am Trifels", "Wittlich", "Bernkastel-Kues", "Bitburg", "Daun",
        "Prüm", "Gerolstein", "Cochem", "Simmern", "Kirchberg",
    ],
    "Saarland": [
        "Saarbrücken", "Neunkirchen", "Homburg", "Völklingen", "Sankt Ingbert",
        "Saarlouis", "Merzig", "Sankt Wendel", "Blieskastel", "Dillingen/Saar",
        "Lebach", "Püttlingen", "Wadgassen", "Bexbach", "Sulzbach/Saar",
        "Schwalbach", "Heusweiler", "Illingen", "Ottweiler", "Losheim am See",
    ],
    "Sachsen": [
        "Leipzig", "Dresden", "Chemnitz", "Zwickau", "Plauen",
        "Görlitz", "Freiberg", "Bautzen", "Pirna", "Hoyerswerda",
        "Freital", "Radebeul", "Riesa", "Meißen", "Grimma",
        "Markkleeberg", "Delitzsch", "Borna", "Döbeln", "Coswig",
        "Limbach-Oberfrohna", "Glauchau", "Crimmitschau", "Werdau", "Reichenbach im Vogtland",
        "Auerbach", "Annaberg-Buchholz", "Aue", "Schwarzenberg", "Marienberg",
        "Mittweida", "Frankenberg", "Hainichen", "Flöha", "Oelsnitz",
        "Zittau", "Löbau", "Niesky", "Weißwasser", "Kamenz",
        "Bischofswerda", "Radeberg", "Großenhain", "Oschatz", "Wurzen",
        "Eilenburg", "Torgau", "Schkeuditz", "Taucha", "Brandis",
        "Zwenkau", "Pegau", "Wilkau-Haßlau", "Stollberg", "Lugau",
    ],
    "Sachsen-Anhalt": [
        "Halle (Saale)", "Magdeburg", "Dessau-Roßlau", "Wittenberg", "Halberstadt",
        "Stendal", "Bernburg", "Bitterfeld-Wolfen", "Weißenfels", "Naumburg",
        "Merseburg", "Zeitz", "Schönebeck", "Aschersleben", "Köthen",
        "Quedlinburg", "Wernigerode", "Sangerhausen", "Stassfurt", "Burg",
        "Genthin", "Haldensleben", "Oschersleben", "Wanzleben", "Gardelegen",
        "Salzwedel", "Tangermünde", "Osterburg", "Hettstedt", "Eisleben",
        "Querfurt", "Hohenmölsen", "Hohenstein", "Thale", "Blankenburg",
        "Ballenstedt", "Gräfenhainichen", "Jessen", "Zerbst", "Coswig (Anhalt)",
    ],
    "Schleswig-Holstein": [
        "Kiel", "Lübeck", "Flensburg", "Neumünster", "Norderstedt",
        "Elmshorn", "Pinneberg", "Itzehoe", "Heide", "Rendsburg",
        "Wedel", "Ahrensburg", "Geesthacht", "Henstedt-Ulzburg", "Reinbek",
        "Bad Oldesloe", "Schleswig", "Husum", "Eckernförde", "Kaltenkirchen",
        "Quickborn", "Bad Segeberg", "Halstenbek", "Glinde", "Wentorf bei Hamburg",
        "Barsbüttel", "Schenefeld", "Tornesch", "Uetersen", "Mölln",
        "Ratzeburg", "Lauenburg", "Plön", "Preetz", "Heiligenhafen",
        "Oldenburg in Holstein", "Fehmarn", "Neustadt in Holstein", "Bad Schwartau", "Stockelsdorf",
        "Ahrensbök", "Eutin", "Malente", "Bordesholm", "Nortorf",
        "Büdelsdorf", "Wahlstedt", "Bad Bramstedt", "Brunsbüttel", "Wilster",
        "Tönning", "Friedrichstadt", "Niebüll", "Tönder", "Kappeln",
    ],
    "Thüringen": [
        "Erfurt", "Jena", "Gera", "Weimar", "Gotha",
        "Nordhausen", "Eisenach", "Suhl", "Mühlhausen", "Altenburg",
        "Arnstadt", "Ilmenau", "Apolda", "Saalfeld", "Rudolstadt",
        "Sömmerda", "Sonneberg", "Greiz", "Pößneck", "Meiningen",
        "Bad Salzungen", "Schmalkalden", "Zella-Mehlis", "Bad Langensalza", "Sondershausen",
        "Heiligenstadt", "Leinefelde-Worbis", "Waltershausen", "Ohrdruf", "Friedrichroda",
        "Hildburghausen", "Bad Lobenstein", "Schleiz", "Zeulenroda-Triebes", "Eisenberg",
        "Stadtroda", "Kahla", "Bad Berka", "Blankenhain", "Tabarz",
        "Schmölln", "Meuselwitz", "Lucka", "Gößnitz", "Ronneburg",
    ],
}

# Schnelles Lookup: Stadt → Bundesland
_STADT_BL: dict[str, str] = {
    stadt: bl
    for bl, staedte in BUNDESLAND_STAEDTE.items()
    for stadt in staedte
}


def get_bundesland(stadt: str) -> str:
    """Gibt das Bundesland einer Stadt zurück (DE zuerst, dann AT), sonst 'Deutschland'.
    AT-Lookup lazy importiert — leadpackages.sources_dach importiert selbst aus diesem
    Modul (BRANCHEN/HIGH_VALUE), ein Modul-Level-Import hier würde einen Zirkelimport
    erzeugen. Reuse statt Duplikat: sources_dach.get_region() hat den AT-Lookup bereits."""
    bl = _STADT_BL.get(stadt)
    if bl:
        return bl
    try:
        from leadpackages.sources_dach import get_region
        at_bl = get_region("AT", stadt)
        if at_bl:
            return at_bl
    except Exception:
        pass
    return "Deutschland"


# Flache Liste aller Städtenamen (dedupliziert, Reihenfolge stabil)
ALLE_REGIONEN: list[str] = list(dict.fromkeys(
    s for staedte in BUNDESLAND_STAEDTE.values() for s in staedte
))

# Rückwärtskompatible Aliase
BERLIN_BEZIRKE = BUNDESLAND_STAEDTE["Berlin"]
SH_STAEDTE     = BUNDESLAND_STAEDTE["Schleswig-Holstein"]

BRANCHEN = [
    # Handwerk — höchster Wert
    "Elektriker", "Klempner", "Heizungsbauer", "Maler", "Dachdecker",
    "Fliesenleger", "Schreiner", "Schlosser", "Sanitär",
    # Bau
    "Bauunternehmen", "Gerüstbau", "Trockenbau", "Fenster Türen",
    # Gesundheit
    "Physiotherapeut", "Heilpraktiker", "Zahnarzt", "Optiker",
    "Ergotherapeut", "Logopäde", "Podologe",
    # Kfz
    "KFZ Werkstatt", "Reifenhandel", "Autoaufbereitung",
    # Dienstleistung
    "Friseur", "Kosmetik", "Reinigung", "Umzugsunternehmen",
    "Schlüsseldienst", "Tierarzt",
    # Beratung
    "Steuerberater", "Rechtsanwalt",
    # Medien / Events
    "Fotograf", "Veranstaltungsservice",
    # Garten / Außen
    "Gartenbau", "Landschaftsgärtner",
    # Sonnen- / Insektenschutz
    "Rolladenservice", "Glaserei", "Insektenschutz", "Sonnenschutz",
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
