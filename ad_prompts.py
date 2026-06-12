"""
Werbe-Prompt-Builder.

Baut aus einem strukturierten Formular-Brief (Branche, Stil, Stimmung, Motiv,
Verwendung, Format) einen ausgefeilten englischen Diffusion-Prompt (SD/SDXL/FLUX
verstehen Englisch am besten) plus Negativ-Prompt und Bildmaße. Ein fester
Basis-Prompt sorgt für Werbe-Qualität, die Formular-Antworten ergänzen ihn.
"""
from __future__ import annotations

# ── Stil ─────────────────────────────────────────────────────────────────────
_STIL = {
    "fotorealistisch": "professional advertising photography, photorealistic, ultra detailed, natural soft lighting, shot on 50mm lens, shallow depth of field",
    "modern_clean":    "modern clean commercial design, minimalist, bright and airy, crisp professional photography",
    "cinematisch":     "cinematic photography, dramatic lighting, rich colors, film look, high dynamic range, depth of field",
    "illustrativ":     "modern flat vector illustration, clean geometric shapes, smooth gradients, corporate illustration style",
    "minimalistisch":  "minimalist composition, generous negative space, simple elegant, refined, premium aesthetic",
}

# ── Stimmung / Farben ────────────────────────────────────────────────────────
_STIMMUNG = {
    "professionell": "professional blue and white color palette, corporate, trustworthy and competent atmosphere",
    "warm":          "warm inviting golden tones, friendly welcoming atmosphere, cozy",
    "edel":          "dark elegant tones, premium luxury feel, sophisticated, high-end",
    "frisch":        "fresh natural green and light tones, bright, clean and organic feeling",
    "kraftvoll":     "bold strong contrast, energetic, confident, eye-catching colors",
}

# ── Verwendung ───────────────────────────────────────────────────────────────
_VERWENDUNG = {
    "website_hero":  "website hero banner composition, wide cinematic framing, marketing campaign",
    "social_post":   "social media post, instagram style, eye-catching, scroll-stopping",
    "werbeanzeige":  "advertising poster, marketing campaign visual, promotional",
    "flyer":         "promotional flyer visual, clean print-ready composition",
}

# ── Format → (Breite, Höhe), Vielfache von 8 ─────────────────────────────────
_FORMAT = {
    "quadrat":  (1024, 1024),   # 1:1  Social / Instagram-Feed
    "quer":     (1024, 576),    # 16:9 Website-Hero / Banner
    "hoch":     (576, 1024),    # 9:16 Stories / Reels
}

# ── Branche → englischer Bild-Kontext (häufige Handwerks-/Dienstleister) ──────
_BRANCHE_EN = {
    "elektriker": "electrician at work, electrical installation",
    "klempner": "plumber working on pipes, plumbing service",
    "heizungsbauer": "heating technician installing a modern heating system",
    "sanitär": "bathroom and sanitary installation, modern bathroom",
    "maler": "painter painting a wall, painting and decorating",
    "dachdecker": "roofer working on a roof, roofing craftsmanship",
    "fliesenleger": "tiler laying tiles, modern tiled bathroom",
    "schreiner": "carpenter in a woodworking workshop, fine wooden furniture",
    "schlosser": "metalworker, metal fabrication workshop",
    "bauunternehmen": "construction site, building company at work",
    "gerüstbau": "scaffolding on a building facade",
    "trockenbau": "drywall construction interior",
    "fenster türen": "modern windows and doors installation",
    "glaserei": "glazier working with glass, glass craftsmanship",
    "physiotherapeut": "modern physiotherapy practice, therapist treating a patient",
    "heilpraktiker": "natural healing practice, calm wellness room",
    "zahnarzt": "modern dental practice, friendly dentist",
    "optiker": "modern optician shop with eyewear display",
    "kfz werkstatt": "car repair workshop, mechanic working on a car",
    "reifenhandel": "tire shop, stacks of car tires",
    "autoaufbereitung": "professional car detailing, shiny clean car",
    "friseur": "modern hair salon, hairdresser styling hair",
    "kosmetik": "beauty and cosmetics studio, spa treatment",
    "reinigung": "professional cleaning service, sparkling clean room",
    "umzugsunternehmen": "moving company, movers carrying boxes, moving truck",
    "schlüsseldienst": "locksmith service, door lock",
    "tierarzt": "modern veterinary practice, vet with a pet",
    "restaurant": "cozy restaurant interior, plated gourmet food",
    "café": "modern cozy cafe interior, coffee and pastries",
    "bäckerei": "artisan bakery, fresh bread and pastries",
    "catering": "elegant catering buffet, finger food presentation",
    "fotograf": "professional photography studio",
    "gartenbau": "landscaped garden, gardening service",
    "landschaftsgärtner": "beautiful landscaped garden design",
    "steuerberater": "modern professional office, tax consultant at desk",
    "rechtsanwalt": "professional law office, lawyer at desk",
    "logopäde": "speech therapy practice, friendly therapist",
    "ergotherapeut": "occupational therapy practice",
    "podologe": "modern podology foot care practice",
    "rolladenservice": "roller shutters on a modern house",
    "sonnenschutz": "sun protection awnings on a terrace",
    "insektenschutz": "insect screen on a window",
}

_NEGATIV = ("text, words, letters, typography, watermark, logo, signature, "
            "blurry, low quality, jpeg artifacts, distorted, deformed, ugly, "
            "extra limbs, bad anatomy, disfigured, cropped, out of frame")


def _branche_kontext(branche: str, motiv: str) -> str:
    """Eigenes Motiv hat Vorrang; sonst aus der Branche ableiten."""
    motiv = (motiv or "").strip()
    if motiv:
        return motiv
    b = (branche or "").strip().lower()
    for key, en in _BRANCHE_EN.items():
        if key in b:
            return en
    if b:
        return f"professional {b} local business in Germany"
    return "professional local business, advertising scene"


# ── Asset-Set: 5 feste Werbe-Assets pro Erstellung ───────────────────────────
# Jedes Asset hat eigenen Prompt-Zusatz + Format (Vielfache von 8).
ASSET_TYPES = [
    {"key": "logo",   "label": "Logo",
     "frag": "minimalist modern logo design, clean simple vector emblem, memorable brand icon, "
             "centered on plain solid background, flat design, professional brand identity",
     "w": 1024, "h": 1024, "logo": True},
    {"key": "hero",   "label": "Website Hero-Banner",
     "frag": "website hero banner, wide cinematic header image, spacious professional composition",
     "w": 1024, "h": 576, "logo": False},
    {"key": "flyer",  "label": "Flyer",
     "frag": "promotional flyer visual, portrait poster layout, eye-catching marketing flyer background",
     "w": 768, "h": 1024, "logo": False},
    {"key": "ad",     "label": "Werbeanzeige",
     "frag": "advertising creative, bold marketing campaign visual, professional ad poster",
     "w": 1024, "h": 1024, "logo": False},
    {"key": "social", "label": "Social-Media-Post",
     "frag": "instagram social media post, scroll-stopping modern square creative",
     "w": 1024, "h": 1024, "logo": False},
]


def build_asset_set(brief: dict) -> list[dict]:
    """5 Werbe-Assets (Logo, Hero, Flyer, Anzeige, Social) je mit eigenem
    Prompt + Format. Rückgabe: Liste von {asset, label, prompt, negative_prompt,
    width, height}."""
    stil_f     = _STIL.get(brief.get("stil", ""), _STIL["fotorealistisch"])
    stimmung_f = _STIMMUNG.get(brief.get("stimmung", ""), _STIMMUNG["professionell"])
    subject    = _branche_kontext(brief.get("branche", ""), brief.get("motiv", ""))
    text_frag  = ", clean uncluttered area with empty copy space for headline and logo" \
                 if brief.get("text_platz", True) else ""

    out: list[dict] = []
    for a in ASSET_TYPES:
        if a.get("logo"):
            # Logo: kein Foto-Stil, klare Marke, garantiert ohne Text
            prompt = (f"{a['frag']}, theme: {subject}, {stimmung_f}, "
                      f"high quality, no text, no words, no letters")
            neg = _NEGATIV + ", photo, photograph, realistic scene, busy background, cluttered"
        else:
            prompt = (f"{stil_f}, {a['frag']}, {subject}, {stimmung_f}, "
                      f"professional marketing image, advertising quality, high resolution, "
                      f"sharp focus, well composed{text_frag}")
            neg = _NEGATIV
        out.append({
            "asset": a["key"], "label": a["label"],
            "prompt": prompt, "negative_prompt": neg,
            "width": a["w"], "height": a["h"],
        })
    return out


def build_ad_prompt(brief: dict) -> dict:
    """
    Brief-Felder: betrieb, branche, motiv, stil, stimmung, verwendung, format,
                  text_platz (bool).
    Gibt zurück: {prompt, negative_prompt, width, height, summary}
    """
    stil_f     = _STIL.get(brief.get("stil", ""), _STIL["fotorealistisch"])
    stimmung_f = _STIMMUNG.get(brief.get("stimmung", ""), _STIMMUNG["professionell"])
    verw_f     = _VERWENDUNG.get(brief.get("verwendung", ""), _VERWENDUNG["social_post"])
    w, h       = _FORMAT.get(brief.get("format", ""), _FORMAT["quadrat"])

    subject = _branche_kontext(brief.get("branche", ""), brief.get("motiv", ""))

    text_frag = ""
    if brief.get("text_platz"):
        text_frag = ", clean uncluttered area with empty copy space for headline and logo"

    # Fester Basis-Prompt + Formular-Ergänzungen
    prompt = (
        f"{stil_f}, {subject}, {stimmung_f}, {verw_f}, "
        f"professional marketing image, advertising quality, "
        f"high resolution, sharp focus, well composed, appealing{text_frag}"
    )

    betrieb = (brief.get("betrieb") or "").strip()
    summary = " · ".join(filter(None, [
        betrieb or None,
        brief.get("branche") or None,
        {"fotorealistisch": "Fotorealistisch", "modern_clean": "Modern & Clean",
         "cinematisch": "Cinematisch", "illustrativ": "Illustrativ",
         "minimalistisch": "Minimalistisch"}.get(brief.get("stil", ""), ""),
        {"quadrat": "1:1", "quer": "16:9", "hoch": "9:16"}.get(brief.get("format", ""), ""),
    ]))

    return {
        "prompt":          prompt,
        "negative_prompt": _NEGATIV,
        "width":           w,
        "height":          h,
        "summary":         summary,
    }
