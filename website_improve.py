"""
website_improve.py — hebt eine bereits gebaute Landing-Page auf Profi-Niveau.

Zwei Funktionen:
  enrich(folder, lead, say): die "5 Profi-Agenten"-Pipeline —
    1. Stratege   → Positionierung, Ton, Akzentfarbe (Claude)
    2. Texter     → erweiterte, auf den Lead zugeschnittene Texte (Claude)
    3. Bildregie  → Referenzbilder (Hero + Über-uns) lokal generieren
    4. Designer   → Premium-Template (index.html) + Premium-CSS (style.css)
    5. QA         → content.json prüfen/vervollständigen, SEO, Konsistenz
  chat_edit(folder, instruction): freie Claude-Anweisung — ändert content.json
    gezielt ODER beantwortet eine Frage (für "Mit Claude debuggen/verbessern").

Beide arbeiten auf dem Projektordner; das Re-Deploy macht website_builder.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

MODEL = "claude-opus-4-8"


def _client():
    import anthropic
    import config
    key = config.get_api_key()
    return anthropic.Anthropic(api_key=key) if key else None


def _read_content(folder: Path) -> dict:
    try:
        return json.loads((folder / "content.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_content(folder: Path, content: dict) -> None:
    (folder / "content.json").write_text(
        json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_json(text: str) -> "dict | None":
    s = text.find("{")
    if s < 0:
        return None
    depth = 0
    in_str = esc = False
    for i in range(s, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[s:i + 1])
                except Exception:
                    return None
    return None


def _claude_json(system: str, prompt: str, max_tokens: int = 2200) -> "dict | None":
    client = _client()
    if client is None:
        return None
    try:
        msg = client.messages.create(
            model=MODEL, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": prompt}])
        text = "".join(getattr(b, "text", "") for b in msg.content
                       if getattr(b, "type", "") == "text")
        return _extract_json(text)
    except Exception:
        return None


# ── Pipeline ──────────────────────────────────────────────────────────────────

def enrich(folder: "str | Path", lead: dict, say) -> dict:
    """Führt die 5-stufige Verbesserung durch. say(progress, text) meldet jeden
    Schritt. Gibt das finale content-dict zurück (bereits geschrieben)."""
    folder = Path(folder)
    content = _read_content(folder)
    base = {**content}
    name = (content.get("site_name") or lead.get("name") or "Ihr Betrieb").strip()
    branche = (content.get("branche") or lead.get("branche") or "Handwerk").strip()
    stadt = (content.get("stadt") or lead.get("stadt") or "").strip()
    bewertung = lead.get("bewertung") or content.get("bewertung") or ""

    lead_info = (f"- Name: {name}\n- Branche: {branche}\n- Stadt: {stadt}\n"
                 f"- Bewertung: {bewertung}\n"
                 f"- Telefon: {content.get('telefon', '')}\n"
                 f"- E-Mail: {content.get('email', '')}\n"
                 f"- Adresse: {content.get('adresse', '')}")

    # 1/5 — Stratege --------------------------------------------------------
    say(15, "Agent 1/5 · Stratege: Positionierung & Tonalität…")
    strat = _claude_json(
        "Du bist Marken-Stratege für lokale Handwerks-/Dienstleistungsbetriebe. "
        "Antworte NUR mit JSON.",
        f"Betrieb:\n{lead_info}\n\nLiefere JSON:\n"
        '{ "positionierung": "1 Satz USP", "ton": "z.B. bodenständig-seriös", '
        '"akzent": "#RRGGBB zur Branche passend", "claim": "kurzer Marken-Claim" }') or {}
    akzent = strat.get("akzent") if re.fullmatch(r"#[0-9a-fA-F]{6}", str(strat.get("akzent", ""))) else base.get("akzent", "#c8102e")

    # 2/5 — Texter ----------------------------------------------------------
    say(32, "Agent 2/5 · Texter: erweiterte, lead-genaue Texte…")
    texte = _claude_json(
        "Du bist Senior-Werbetexter (design-pro). Konkret, deutsch, vertrauenswürdig, "
        "kein KI-Geschwurbel, keine leeren Floskeln. Antworte NUR mit JSON.",
        f"Betrieb:\n{lead_info}\nPositionierung: {strat.get('positionierung','')}\n"
        f"Ton: {strat.get('ton','')}\n\n"
        "Erzeuge JSON mit GENAU diesen Feldern (Texte auf den Betrieb zugeschnitten):\n"
        "{\n"
        '  "headline": "kraftvolle Hero-Headline (max 8 Wörter)",\n'
        '  "subline": "1 Nutzenversprechen-Satz",\n'
        '  "ueber_titel": "Überschrift Über-uns",\n'
        '  "ueber_text": "3-4 Sätze, echt & vertrauenswürdig",\n'
        '  "leistungen": [{"titel":"…","text":"1-2 Sätze konkret"}, … 5-6 Stück],\n'
        '  "usps": ["kurzer Vorteil", … 3-4 Stück],\n'
        '  "faq": [{"frage":"…","antwort":"…"}, … 3-4 Stück],\n'
        '  "kontakt_text": "1 einladender Satz für die Kontakt-Sektion",\n'
        '  "cta_text": "konkreter Call-to-Action",\n'
        '  "seo_title": "Titel-Tag", "seo_desc": "Meta-Description max 150 Z."\n'
        "}", max_tokens=2600) or {}

    content.update({"site_name": name, "branche": branche, "stadt": stadt, "akzent": akzent})
    for k in ("headline", "subline", "ueber_titel", "ueber_text", "cta_text",
              "kontakt_text", "seo_title", "seo_desc"):
        if isinstance(texte.get(k), str) and texte[k].strip():
            content[k] = texte[k].strip()
    if isinstance(texte.get("leistungen"), list) and texte["leistungen"]:
        content["leistungen"] = [{"titel": str(x.get("titel", "")).strip(),
                                  "text": str(x.get("text", "")).strip()}
                                 for x in texte["leistungen"][:6]
                                 if isinstance(x, dict) and x.get("titel")]
    if isinstance(texte.get("usps"), list):
        content["usps"] = [str(u).strip() for u in texte["usps"][:4] if str(u).strip()]
    if isinstance(texte.get("faq"), list):
        content["faq"] = [{"frage": str(x.get("frage", "")).strip(),
                           "antwort": str(x.get("antwort", "")).strip()}
                          for x in texte["faq"][:4]
                          if isinstance(x, dict) and x.get("frage")]
    content.setdefault("claim", strat.get("claim", ""))
    _write_content(folder, content)

    # 3/5 — Bildregie -------------------------------------------------------
    say(52, "Agent 3/5 · Bildregie: Referenzbilder generieren…")
    _generate_reference_images(folder, branche, content, say)
    _write_content(folder, content)

    # 4/5 — Designer (Premium-Template + CSS) ------------------------------
    say(74, "Agent 4/5 · Designer: Premium-Layout & -Design…")
    _install_premium_template(folder)

    # 5/5 — QA --------------------------------------------------------------
    say(88, "Agent 5/5 · QA: Konsistenz, SEO, Vollständigkeit…")
    content.setdefault("jahr", base.get("jahr") or 2026)
    if not content.get("seo_title"):
        content["seo_title"] = f"{name}" + (f" — {branche} {stadt}" if stadt else "")
    if not content.get("seo_desc"):
        content["seo_desc"] = f"{branche} aus {stadt}. Jetzt anfragen." if stadt else f"{branche}. Jetzt anfragen."
    _write_content(folder, content)
    say(95, "Verbesserung fertig — bereit zum Deploy.")
    return content


def _generate_reference_images(folder: Path, branche: str, content: dict, say) -> None:
    """Erzeugt Hero- + Über-uns-Referenzbild lokal (best-effort, mit Zeitlimit)."""
    try:
        import media_engine
        if not media_engine.get_status().get("diffusers_ok"):
            return
        import website_builder
        img_dir = folder / "static" / "img"
        jobs = [
            ("hero.png", "hero_image",
             f"professional wide hero banner photograph for a German {branche} business, "
             "modern, clean, bright daylight, high quality, no text, no logo"),
            ("ueber.png", "about_image",
             f"authentic photo of a German {branche} team at work, friendly, professional, "
             "natural light, high quality, no text, no logo"),
        ]
        hp = media_engine.hero_image_params()
        for fn, field, prompt in jobs:
            target = img_dir / fn
            ok = website_builder._generate_hero_local_timed(
                media_engine, prompt, img_dir, {**hp}, getattr(website_builder, "_HERO_TIMEOUT", 180))
            # generate_hero_local_timed schreibt immer 'hero.png' → ggf. umbenennen
            src = img_dir / "hero.png"
            if ok and fn != "hero.png" and src.exists():
                try:
                    src.replace(target)
                except Exception:
                    pass
            if (img_dir / fn).exists():
                content[field] = f"/static/img/{fn}"
    except Exception:
        pass


def _install_premium_template(folder: Path) -> None:
    """Schreibt die erweiterte Premium-Vorlage (index.html + style.css)."""
    (folder / "templates").mkdir(parents=True, exist_ok=True)
    (folder / "static" / "css").mkdir(parents=True, exist_ok=True)
    (folder / "templates" / "index.html").write_text(_PREMIUM_HTML, encoding="utf-8")
    (folder / "static" / "css" / "style.css").write_text(_PREMIUM_CSS, encoding="utf-8")


# ── Mit Claude: gezielt verbessern / debuggen ─────────────────────────────────

def chat_edit(folder: "str | Path", instruction: str) -> dict:
    """Wendet eine freie Anweisung auf die Seite an. Gibt
    {ok, answer, changed, content}. Bei Fragen: answer gefüllt, changed=False.
    Bei Änderungswünschen: content.json angepasst, changed=True."""
    folder = Path(folder)
    content = _read_content(folder)
    if not content:
        return {"ok": False, "answer": "content.json nicht gefunden.", "changed": False}
    client = _client()
    if client is None:
        return {"ok": False, "answer": "ANTHROPIC_KEY fehlt — Claude nicht verfügbar.", "changed": False}

    sys = (
        "Du bist JARVIS' Web-Editor. Du bekommst die content.json einer Landing-Page und "
        "eine Anweisung von Sir. Ist es eine ÄNDERUNG (Text/Headline/Farbe/Leistungen/…), "
        "gib das VOLLSTÄNDIGE neue content.json zurück. Ist es eine FRAGE, antworte kurz. "
        "Antworte als JSON: {\"antwort\": \"kurze Erklärung was du getan/geantwortet hast\", "
        "\"content\": { …vollständiges content.json… } ODER null bei reiner Frage }. "
        "Ändere NUR was sinnvoll ist; behalte alle übrigen Felder bei."
    )
    prompt = (f"Aktuelle content.json:\n{json.dumps(content, ensure_ascii=False)}\n\n"
              f"Anweisung von Sir:\n{instruction}")
    try:
        msg = client.messages.create(model=MODEL, max_tokens=3000, system=sys,
                                     messages=[{"role": "user", "content": prompt}])
        text = "".join(getattr(b, "text", "") for b in msg.content
                       if getattr(b, "type", "") == "text")
        data = _extract_json(text) or {}
    except Exception as e:
        return {"ok": False, "answer": f"Fehler: {type(e).__name__}", "changed": False}

    antwort = str(data.get("antwort") or "").strip() or "Erledigt, Sir."
    neu = data.get("content")
    if isinstance(neu, dict) and neu:
        # nur plausible Inhalte übernehmen (site_name muss bleiben)
        neu.setdefault("site_name", content.get("site_name", ""))
        _write_content(folder, neu)
        return {"ok": True, "answer": antwort, "changed": True, "content": neu}
    return {"ok": True, "answer": antwort, "changed": False, "content": content}


# ── Premium-Assets (deterministisch, garantiert valides Django/CSS) ───────────

_PREMIUM_HTML = r"""{% load static %}<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ c.seo_title }}</title>
  <meta name="description" content="{{ c.seo_desc }}">
  <meta property="og:title" content="{{ c.seo_title }}">
  <meta property="og:description" content="{{ c.seo_desc }}">
  <meta property="og:type" content="website">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{% static 'css/style.css' %}">
  <style>:root{ --accent: {{ c.akzent }}; }</style>
</head>
<body>
  <header class="nav">
    <div class="wrap nav-in">
      <a class="brand" href="#top">{{ c.site_name }}</a>
      <nav class="nav-links">
        <a href="#leistungen">Leistungen</a>
        <a href="#ueber">Über uns</a>
        {% if c.faq %}<a href="#faq">FAQ</a>{% endif %}
        <a href="#kontakt">Kontakt</a>
      </nav>
      {% if c.telefon %}<a class="btn btn-sm" href="tel:{{ c.telefon }}">Anrufen</a>{% endif %}
    </div>
  </header>

  <main id="top">
    <!-- HERO -->
    {% if c.hero_image %}
    <section class="hero hero-banner" style="--hero-img:url('{{ c.hero_image }}')">
    {% elif c.fotos %}
    <section class="hero hero-banner" style="--hero-img:url('{{ c.fotos.0 }}')">
    {% else %}
    <section class="hero hero-plain">
    {% endif %}
      <div class="wrap hero-in">
        <div class="hero-copy">
          {% if c.stadt %}<span class="eyebrow">{{ c.branche }} · {{ c.stadt }}</span>{% endif %}
          <h1>{{ c.headline }}</h1>
          <p class="lead">{{ c.subline }}</p>
          <div class="hero-cta">
            <a class="btn" href="#kontakt">{{ c.cta_text }}</a>
            {% if c.telefon %}<a class="btn btn-ghost btn-on-dark" href="tel:{{ c.telefon }}">{{ c.telefon }}</a>{% endif %}
          </div>
        </div>
      </div>
    </section>

    <!-- USP-BAND -->
    {% if c.usps %}
    <section class="usps">
      <div class="wrap usps-in">
        {% for u in c.usps %}<div class="usp"><span class="usp-dot"></span>{{ u }}</div>{% endfor %}
      </div>
    </section>
    {% endif %}

    <!-- LEISTUNGEN -->
    {% if c.leistungen %}
    <section id="leistungen" class="section">
      <div class="wrap">
        <h2 class="section-t">Was wir für Sie tun</h2>
        <div class="grid">
          {% for s in c.leistungen %}
          <article class="card">
            <div class="card-mark" aria-hidden="true"></div>
            <h3>{{ s.titel }}</h3>
            <p>{{ s.text }}</p>
          </article>
          {% endfor %}
        </div>
      </div>
    </section>
    {% endif %}

    <!-- ÜBER (mit Bild) -->
    <section id="ueber" class="section section-tint">
      <div class="wrap about">
        <div class="about-copy">
          <h2 class="section-t">{{ c.ueber_titel }}</h2>
          <p class="about-text">{{ c.ueber_text }}</p>
          <ul class="trust">
            <li><strong>Regional</strong><span>aus {{ c.stadt|default:"Ihrer Region" }}</span></li>
            <li><strong>Zuverlässig</strong><span>termintreu &amp; sauber</span></li>
            <li><strong>Persönlich</strong><span>fester Ansprechpartner</span></li>
          </ul>
        </div>
        {% if c.about_image %}<figure class="about-img"><img src="{{ c.about_image }}" alt="{{ c.site_name }}" loading="lazy"></figure>{% endif %}
      </div>
    </section>

    <!-- GALERIE -->
    {% if c.fotos|length > 1 %}
    <section class="section">
      <div class="wrap">
        <h2 class="section-t">Einblicke</h2>
        <div class="gallery">
          {% for f in c.fotos %}<figure class="g-item"><img src="{{ f }}" alt="{{ c.site_name }} Foto {{ forloop.counter }}" loading="lazy"></figure>{% endfor %}
        </div>
      </div>
    </section>
    {% endif %}

    <!-- FAQ -->
    {% if c.faq %}
    <section id="faq" class="section">
      <div class="wrap wrap-narrow">
        <h2 class="section-t">Häufige Fragen</h2>
        <div class="faq">
          {% for q in c.faq %}
          <details class="faq-item"><summary>{{ q.frage }}</summary><p>{{ q.antwort }}</p></details>
          {% endfor %}
        </div>
      </div>
    </section>
    {% endif %}

    <!-- KONTAKT -->
    <section id="kontakt" class="section cta">
      <div class="wrap cta-in">
        <h2>{{ c.cta_text }}</h2>
        <p>{{ c.kontakt_text|default:"Wir melden uns kurzfristig zurück — versprochen." }}</p>
        <div class="cta-actions">
          {% if c.telefon %}<a class="btn btn-light" href="tel:{{ c.telefon }}">☎ {{ c.telefon }}</a>{% endif %}
          {% if c.email %}<a class="btn btn-light" href="mailto:{{ c.email }}">✉ {{ c.email }}</a>{% endif %}
        </div>
        {% if c.adresse %}<p class="cta-adr">{{ c.adresse }}</p>{% endif %}
      </div>
    </section>
  </main>

  <footer class="foot">
    <div class="wrap foot-in">
      <span>© {{ c.jahr }} {{ c.site_name }}</span>
      <span class="foot-sub">{{ c.branche }}{% if c.stadt %} · {{ c.stadt }}{% endif %}</span>
    </div>
  </footer>
</body>
</html>
"""

_PREMIUM_CSS = r""":root{
  --accent:#c8102e; --ink:#15181d; --ink2:#454b54; --bg:#ffffff; --bg2:#f6f4f1;
  --line:#e7e3dd; --radius:16px; --maxw:1140px;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{font-family:'Inter',system-ui,sans-serif;color:var(--ink);background:var(--bg);line-height:1.65;-webkit-font-smoothing:antialiased}
.wrap{max-width:var(--maxw);margin:0 auto;padding:0 24px}
.wrap-narrow{max-width:780px}
h1,h2,h3{font-family:'Fraunces',Georgia,serif;line-height:1.1;letter-spacing:-.01em;color:var(--ink)}
a{color:inherit;text-decoration:none}
img{max-width:100%;display:block}

/* Nav */
.nav{position:sticky;top:0;z-index:50;background:rgba(255,255,255,.86);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.nav-in{display:flex;align-items:center;gap:20px;height:66px}
.brand{font-family:'Fraunces',serif;font-weight:700;font-size:21px;letter-spacing:-.02em}
.nav-links{display:flex;gap:26px;margin-left:auto;font-weight:500;font-size:15px;color:var(--ink2)}
.nav-links a:hover{color:var(--accent)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;background:var(--accent);color:#fff;font-weight:600;font-size:15px;padding:13px 24px;border-radius:999px;transition:transform .15s,filter .15s;box-shadow:0 6px 20px rgba(0,0,0,.10)}
.btn:hover{transform:translateY(-1px);filter:brightness(1.05)}
.btn-sm{padding:9px 18px;font-size:14px}
.btn-ghost{background:transparent;border:1.5px solid var(--accent);color:var(--accent);box-shadow:none}
.btn-on-dark{border-color:rgba(255,255,255,.7);color:#fff}
.btn-light{background:#fff;color:var(--ink)}

/* Hero */
.hero{position:relative;padding:118px 0 104px;overflow:hidden}
.hero-plain{background:linear-gradient(135deg,var(--bg2),#fff)}
.hero-plain::after{content:"";position:absolute;inset:0;background:radial-gradient(70% 90% at 85% 10%,color-mix(in srgb,var(--accent) 16%,transparent),transparent 60%);pointer-events:none}
.hero-banner{color:#fff}
.hero-banner::before{content:"";position:absolute;inset:0;background-image:var(--hero-img);background-size:cover;background-position:center;z-index:-2}
.hero-banner::after{content:"";position:absolute;inset:0;background:linear-gradient(100deg,rgba(8,10,14,.82),rgba(8,10,14,.45));z-index:-1}
.hero-banner h1{color:#fff}
.hero-in{position:relative}
.hero-copy{max-width:680px}
.eyebrow{display:inline-block;font-weight:600;font-size:13px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);margin-bottom:16px}
.hero-banner .eyebrow{color:#fff;opacity:.92}
h1{font-size:clamp(38px,6vw,62px);font-weight:700}
.lead{font-size:clamp(17px,2.2vw,21px);color:var(--ink2);margin:20px 0 30px;max-width:560px}
.hero-banner .lead{color:rgba(255,255,255,.92)}
.hero-cta{display:flex;gap:14px;flex-wrap:wrap}

/* USP-Band */
.usps{background:var(--ink);color:#fff}
.usps-in{display:flex;flex-wrap:wrap;gap:14px 34px;padding:20px 24px;justify-content:center}
.usp{display:flex;align-items:center;gap:10px;font-weight:500;font-size:15px}
.usp-dot{width:8px;height:8px;border-radius:50%;background:var(--accent);flex-shrink:0}

/* Sections */
.section{padding:84px 0}
.section-tint{background:var(--bg2)}
.section-t{font-size:clamp(26px,4vw,38px);font-weight:700;margin-bottom:38px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:22px}
.card{background:#fff;border:1px solid var(--line);border-radius:var(--radius);padding:28px;transition:transform .18s,box-shadow .18s}
.card:hover{transform:translateY(-3px);box-shadow:0 14px 34px rgba(0,0,0,.07)}
.card-mark{width:42px;height:42px;border-radius:12px;background:color-mix(in srgb,var(--accent) 14%,transparent);position:relative;margin-bottom:16px}
.card-mark::after{content:"";position:absolute;inset:13px;border-radius:4px;background:var(--accent)}
.card h3{font-size:20px;margin-bottom:8px}
.card p{color:var(--ink2);font-size:15.5px}

/* Über */
.about{display:grid;grid-template-columns:1.1fr .9fr;gap:48px;align-items:center}
.about-text{color:var(--ink2);font-size:17px;margin-bottom:24px}
.about-img img{border-radius:var(--radius);box-shadow:0 20px 50px rgba(0,0,0,.12);width:100%;object-fit:cover;aspect-ratio:4/3}
.trust{list-style:none;display:flex;flex-wrap:wrap;gap:26px}
.trust li{display:flex;flex-direction:column}
.trust strong{font-size:16px}
.trust span{color:var(--ink2);font-size:14px}

/* Galerie */
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}
.g-item img{border-radius:12px;aspect-ratio:4/3;object-fit:cover;width:100%}

/* FAQ */
.faq{display:flex;flex-direction:column;gap:12px}
.faq-item{border:1px solid var(--line);border-radius:12px;padding:6px 20px;background:#fff}
.faq-item summary{cursor:pointer;font-weight:600;padding:14px 0;list-style:none}
.faq-item summary::-webkit-details-marker{display:none}
.faq-item p{color:var(--ink2);padding:0 0 16px}

/* CTA */
.cta{background:var(--ink);color:#fff;text-align:center;border-radius:0}
.cta h2{color:#fff;font-size:clamp(26px,4vw,40px)}
.cta p{color:rgba(255,255,255,.82);margin:14px 0 28px}
.cta-actions{display:flex;gap:14px;justify-content:center;flex-wrap:wrap}
.cta-adr{margin-top:22px;color:rgba(255,255,255,.6);font-size:14px}

/* Footer */
.foot{border-top:1px solid var(--line);padding:28px 0}
.foot-in{display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;color:var(--ink2);font-size:14px}

@media(max-width:760px){
  .about{grid-template-columns:1fr;gap:28px}
  .nav-links{display:none}
  .section{padding:60px 0}
  .hero{padding:84px 0 72px}
}
"""
