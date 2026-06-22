"""
Werbe-Prompt-Builder.

Baut aus einem strukturierten Formular-Brief (Branche, Stil, Stimmung, Motiv,
Verwendung, Format) einen ausgefeilten englischen Diffusion-Prompt (SD/SDXL/FLUX
verstehen Englisch am besten) plus Negativ-Prompt und Bildmaße. Ein fester
Basis-Prompt sorgt für Werbe-Qualität, die Formular-Antworten ergänzen ihn.
"""
from __future__ import annotations

# Qualitäts-Präfix der jedem Prompt vorangestellt wird
_QUALITY = "masterpiece, best quality, ultra-detailed, ultra-realistic, 8K UHD, HDR, sharp focus, "

# ── Stil ─────────────────────────────────────────────────────────────────────
_STIL = {
    "fotorealistisch": "professional advertising photography, photorealistic, DSLR photo, natural soft diffused lighting, 50mm portrait lens, shallow depth of field, lifelike textures, true-to-life colors",
    "modern_clean":    "modern clean commercial photography, minimalist, bright airy studio lighting, crisp sharp professional photo, fresh contemporary look",
    "cinematisch":     "cinematic photography, dramatic atmospheric lighting, rich deep colors, anamorphic lens flare, film grain, high dynamic range, bokeh",
    "illustrativ":     "modern flat vector illustration, clean geometric shapes, smooth gradients, polished corporate illustration, vibrant brand colors",
    "minimalistisch":  "minimalist composition, generous negative space, simple elegant design, refined premium aesthetic, muted sophisticated palette",
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

_NEGATIV = (
    "text, words, letters, typography, watermark, logo, signature, title, caption, "
    "blurry, blur, out of focus, soft focus, low quality, bad quality, worst quality, "
    "jpeg artifacts, compression artifacts, pixelated, grainy, noisy, "
    "distorted, deformed, ugly, disfigured, mutated, mutation, "
    "extra limbs, extra arms, extra legs, bad hands, bad anatomy, malformed, "
    "floating limbs, disconnected limbs, gross, obese, "
    "poorly drawn, poorly rendered, bad proportions, "
    "cropped, out of frame, cut off, duplicate, clone, "
    "oversaturated, overexposed, underexposed, dark, flat lighting, "
    "cartoon, anime, illustration, painting, drawing, sketch, 3d render, cgi"
)


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
# Kurze Prompt-Bausteine — CLIP (SD/SDXL) verarbeitet nur 77 Tokens, daher knapp.
ASSET_TYPES = [
    {"key": "logo",   "label": "Logo",   "frag": "minimalist flat logo icon, plain background",
     "w": 1024, "h": 1024, "logo": True},
    {"key": "hero",   "label": "Website Hero-Banner", "frag": "website hero banner, wide",
     "w": 1024, "h": 576, "logo": False},
    {"key": "flyer",  "label": "Flyer",  "frag": "promotional flyer background, portrait poster",
     "w": 768, "h": 1024, "logo": False},
    {"key": "ad",     "label": "Werbeanzeige", "frag": "advertising poster, marketing visual",
     "w": 1024, "h": 1024, "logo": False},
    {"key": "social", "label": "Social-Media-Post", "frag": "instagram post, square creative",
     "w": 1024, "h": 1024, "logo": False},
]

# Kurzfassungen für knappe Prompts (SDXL CLIP ≈ 77 Tokens).
_STIL_SHORT = {
    "fotorealistisch": "professional photorealistic advertising photo, DSLR, sharp, natural light",
    "modern_clean":    "modern clean commercial photo, bright studio, crisp sharp",
    "cinematisch":     "cinematic photo, dramatic lighting, film quality",
    "illustrativ":     "flat vector illustration, clean geometric, vibrant",
    "minimalistisch":  "minimalist photo, elegant, premium, negative space",
}
_STIMMUNG_SHORT = {
    "professionell": "professional corporate blue-white tones, trustworthy",
    "warm":          "warm golden tones, inviting, cozy",
    "edel":          "dark elegant premium, sophisticated, luxury",
    "frisch":        "fresh natural light tones, clean, organic",
    "kraftvoll":     "bold high-contrast colors, energetic, eye-catching",
}

# Asset-spezifische Negativ-Prompts
_NEG_LOGO = (_NEGATIV +
             ", photo, realistic, 3d, background clutter, multiple logos, busy")
_NEG_PHOTO = _NEGATIV


def build_asset_set(brief: dict) -> list[dict]:
    """5 Werbe-Assets (Logo, Hero, Flyer, Anzeige, Social) je mit eigenem
    realistischen Prompt + Format."""
    stil_f     = _STIL_SHORT.get(brief.get("stil", ""), _STIL_SHORT["fotorealistisch"])
    stimmung_f = _STIMMUNG_SHORT.get(brief.get("stimmung", ""), _STIMMUNG_SHORT["professionell"])
    subject    = _branche_kontext(brief.get("branche", ""), brief.get("motiv", ""))[:90]
    cs         = ", empty copy space for text overlay" if brief.get("text_platz", True) else ""

    out: list[dict] = []
    for a in ASSET_TYPES:
        if a.get("logo"):
            prompt = (f"minimalist flat logo icon design, {subject}, "
                      f"{stimmung_f}, simple clean icon, white background, no text, no words")
            neg = _NEG_LOGO
        else:
            prompt = (f"{_QUALITY}{stil_f}, {a['frag']}, {subject}, "
                      f"{stimmung_f}, professional advertising visual, "
                      f"high-end commercial photography{cs}")
            neg = _NEG_PHOTO
        out.append({
            "asset": a["key"], "label": a["label"],
            "prompt": prompt, "negative_prompt": neg,
            "width": a["w"], "height": a["h"],
        })
    return out


def build_video_prompt(brief: dict) -> dict:
    """Baut einen kinoreifen englischen Werbevideo-Prompt (für lokales Wan oder
    Higgsfield) aus einem Brief: betrieb, branche, motiv, stil, stimmung.
    Gibt {prompt, summary}."""
    subject = _branche_kontext(brief.get("branche", ""), brief.get("motiv", ""))
    stil = (brief.get("stil") or "").strip().lower()
    bewegung = {
        "cinematisch":     "slow cinematic dolly shot, smooth camera movement, shallow depth of field",
        "modern_clean":    "smooth gimbal motion, bright clean look, steady professional pan",
        "fotorealistisch": "realistic handheld camera, natural motion, documentary feel",
        "minimalistisch":  "slow elegant push-in, minimalist framing, calm pacing",
        "illustrativ":     "smooth animated motion graphics style, clean transitions",
    }.get(stil, "smooth cinematic camera movement, professional motion")
    stimmung = _STIMMUNG.get(brief.get("stimmung", ""), _STIMMUNG["professionell"])
    betrieb = (brief.get("betrieb") or "").strip()
    prompt = (
        f"Professional advertising video clip: {subject}. "
        f"{bewegung}. {stimmung}. Cinematic commercial quality, high dynamic range, "
        f"sharp focus, beautiful natural lighting, 4K, no text, no watermark."
    )
    summary = " · ".join(filter(None, [betrieb or None, brief.get("branche") or None, "Werbevideo"]))
    return {"prompt": prompt[:900], "summary": summary}


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

    # Qualitäts-Präfix + Formular-Ergänzungen
    prompt = (
        f"{_QUALITY}{stil_f}, {subject}, {stimmung_f}, {verw_f}, "
        f"professional marketing image, advertising campaign quality, "
        f"award-winning commercial photography, perfectly composed{text_frag}"
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
