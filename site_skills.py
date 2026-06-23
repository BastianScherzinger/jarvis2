"""
site_skills.py — Template variant library for JARVIS LeadHunter landing pages.
Five visually distinct HTML+CSS variants mapped by business type (branche).
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Variant selection
# ---------------------------------------------------------------------------

_BOLD_KEYWORDS = {
    "dachdecker", "elektriker", "sanitär", "sanitar", "heizung",
    "klempner", "bauunternehmen", "bau", "gerüst", "gerüstbau",
}
_MODERN_KEYWORDS = {
    "zahnarzt", "arzt", "physiotherapeut", "rechtsanwalt", "steuerberater",
    "notar", "praxis", "kanzlei", "medizin", "zahnarztpraxis",
}
_WARM_KEYWORDS = {
    "friseur", "kosmetik", "restaurant", "café", "cafe", "gastro",
    "bäckerei", "backerei", "florist", "blumen", "catering",
}
_CRAFT_KEYWORDS = {
    "schreiner", "tischler", "zimmerer", "kfz", "werkstatt",
    "maurer", "maler", "lackierer", "schlosser", "metallbau",
}


def pick_variant(branche: str, content: dict) -> str:
    """
    Maps branche keywords to a variant name.
    Returns one of: 'bold', 'modern', 'warm', 'craft', 'premium'.
    """
    b = branche.lower().strip()
    for kw in _BOLD_KEYWORDS:
        if kw in b:
            return "bold"
    for kw in _MODERN_KEYWORDS:
        if kw in b:
            return "modern"
    for kw in _WARM_KEYWORDS:
        if kw in b:
            return "warm"
    for kw in _CRAFT_KEYWORDS:
        if kw in b:
            return "craft"
    return "premium"


# ---------------------------------------------------------------------------
# JS skill files
# ---------------------------------------------------------------------------

_COUNTER_UP_JS = r"""/* counter_up.js — Pure vanilla JS count-up animation using IntersectionObserver */
(function () {
  'use strict';

  function animateCount(el) {
    var target = parseInt(el.getAttribute('data-target'), 10);
    if (isNaN(target)) return;
    var duration = 1600;
    var startTime = null;
    var startVal = 0;

    function easeOut(t) {
      return 1 - Math.pow(1 - t, 3);
    }

    function step(timestamp) {
      if (!startTime) startTime = timestamp;
      var elapsed = timestamp - startTime;
      var progress = Math.min(elapsed / duration, 1);
      var current = Math.floor(easeOut(progress) * (target - startVal) + startVal);
      el.textContent = current;
      if (progress < 1) {
        requestAnimationFrame(step);
      } else {
        el.textContent = target;
      }
    }

    requestAnimationFrame(step);
  }

  var prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  if (prefersReduced) {
    document.querySelectorAll('.count-up').forEach(function (el) {
      var t = el.getAttribute('data-target');
      if (t) el.textContent = t;
    });
    return;
  }

  if (!('IntersectionObserver' in window)) {
    document.querySelectorAll('.count-up').forEach(function (el) {
      var t = el.getAttribute('data-target');
      if (t) el.textContent = t;
    });
    return;
  }

  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        animateCount(entry.target);
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.3 });

  document.querySelectorAll('.count-up').forEach(function (el) {
    observer.observe(el);
  });
})();
"""

_SWIPER_LITE_JS = r"""/* swiper_lite.js — Lightweight touch slider for testimonials (~80 lines, no deps) */
(function () {
  'use strict';

  function SwiperLite(container) {
    this.container = container;
    this.track = container.querySelector('.swiper-track');
    this.slides = Array.from(container.querySelectorAll('.swiper-slide'));
    this.current = 0;
    this.total = this.slides.length;
    this.startX = 0;
    this.isDragging = false;
    if (this.total < 2) return;
    this._buildDots();
    this._bindEvents();
    this._update();
  }

  SwiperLite.prototype._buildDots = function () {
    var wrap = document.createElement('div');
    wrap.className = 'swiper-dots';
    for (var i = 0; i < this.total; i++) {
      var dot = document.createElement('button');
      dot.className = 'swiper-dot';
      dot.setAttribute('aria-label', 'Slide ' + (i + 1));
      dot.addEventListener('click', this._goto.bind(this, i));
      wrap.appendChild(dot);
    }
    this.container.appendChild(wrap);
    this.dots = Array.from(wrap.querySelectorAll('.swiper-dot'));
  };

  SwiperLite.prototype._goto = function (idx) {
    this.current = Math.max(0, Math.min(idx, this.total - 1));
    this._update();
  };

  SwiperLite.prototype._update = function () {
    if (this.track) {
      this.track.style.transform = 'translateX(-' + (this.current * 100) + '%)';
    }
    this.slides.forEach(function (s, i) {
      s.setAttribute('aria-hidden', i !== this.current ? 'true' : 'false');
    }, this);
    if (this.dots) {
      this.dots.forEach(function (d, i) {
        d.classList.toggle('active', i === this.current);
      }, this);
    }
  };

  SwiperLite.prototype._bindEvents = function () {
    var self = this;
    this.container.addEventListener('touchstart', function (e) {
      self.startX = e.touches[0].clientX;
      self.isDragging = true;
    }, { passive: true });
    this.container.addEventListener('touchend', function (e) {
      if (!self.isDragging) return;
      var diff = self.startX - e.changedTouches[0].clientX;
      if (Math.abs(diff) > 40) {
        diff > 0 ? self._goto(self.current + 1) : self._goto(self.current - 1);
      }
      self.isDragging = false;
    });
    this.container.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowRight') self._goto(self.current + 1);
      if (e.key === 'ArrowLeft') self._goto(self.current - 1);
    });
  };

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.swiper-lite').forEach(function (el) {
      new SwiperLite(el);
    });
  });
})();
"""


def ensure_base_skills(base_dir: Path = None) -> None:
    """
    Creates data/skills/ directory and writes counter_up.js and swiper_lite.js.
    """
    if base_dir is None:
        base_dir = Path(__file__).parent
    skills_dir = base_dir / "data" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    (skills_dir / "counter_up.js").write_text(_COUNTER_UP_JS, encoding="utf-8")
    (skills_dir / "swiper_lite.js").write_text(_SWIPER_LITE_JS, encoding="utf-8")


# ---------------------------------------------------------------------------
# HTML templates (shared structural pieces, variant-specific where noted)
# ---------------------------------------------------------------------------

_HTML_HEAD = r"""{% load static %}<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ c.seo_title }}</title>
  <meta name="description" content="{{ c.seo_desc }}">
  <meta property="og:title" content="{{ c.seo_title }}">
  <meta property="og:description" content="{{ c.seo_desc }}">
  <meta property="og:type" content="website">
"""

_HTML_FOOT_SCRIPTS = r"""  <script src="{% static 'js/counter_up.js' %}" defer></script>
  <script src="{% static 'js/swiper_lite.js' %}" defer></script>
  <script>
    // Reveal on scroll
    (function(){
      if(!('IntersectionObserver' in window)) {
        document.querySelectorAll('.reveal').forEach(function(el){ el.classList.add('revealed'); });
        return;
      }
      var obs = new IntersectionObserver(function(entries){
        entries.forEach(function(e){ if(e.isIntersecting){ e.target.classList.add('revealed'); obs.unobserve(e.target); } });
      }, {threshold:0.1});
      document.querySelectorAll('.reveal').forEach(function(el){ obs.observe(el); });
    })();
    // Sticky nav shadow
    window.addEventListener('scroll', function(){
      document.querySelector('.nav').classList.toggle('nav-scrolled', window.scrollY > 40);
    });
  </script>
</body>
</html>
"""

_LEISTUNGEN_BLOCK = r"""  <!-- LEISTUNGEN -->
  <section id="leistungen" class="section leistungen reveal">
    <div class="wrap">
      <h2 class="section-t">Unsere Leistungen</h2>
      <div class="leistungen-grid">
        {% for l in c.leistungen %}
        <article class="leistung-card">
          {% if l.icon %}<div class="leistung-icon">{{ l.icon }}</div>{% endif %}
          <h3>{{ l.name }}</h3>
          <p>{{ l.beschreibung }}</p>
        </article>
        {% endfor %}
      </div>
    </div>
  </section>
"""

_UEBER_BLOCK = r"""  <!-- ÜBER UNS -->
  <section id="ueber" class="section ueber reveal">
    <div class="wrap ueber-in">
      <div class="ueber-text">
        <h2 class="section-t">Über uns</h2>
        <p>{{ c.ueber_uns }}</p>
        {% if c.zertifikate %}
        <ul class="zertifikate">
          {% for z in c.zertifikate %}<li>✓ {{ z }}</li>{% endfor %}
        </ul>
        {% endif %}
      </div>
      {% if c.team_foto %}
      <div class="ueber-img">
        <img src="{{ c.team_foto }}" alt="Team {{ c.site_name }}" loading="lazy">
      </div>
      {% endif %}
    </div>
  </section>
"""

_STATS_BLOCK = r"""  <!-- STATS -->
  <section class="stats reveal">
    <div class="wrap stats-in">
      <div class="stat-item"><span class="count-up" data-target="{{ c.jahre_erfahrung|default:10 }}">0</span><span class="stat-plus">+</span><div class="stat-label">Jahre Erfahrung</div></div>
      <div class="stat-item"><span class="count-up" data-target="{{ c.kunden_bedient|default:200 }}">0</span><span class="stat-plus">+</span><div class="stat-label">Zufriedene Kunden</div></div>
      <div class="stat-item"><span class="count-up" data-target="{{ c.anz_bewertungen|default:50 }}">0</span><span class="stat-label">Bewertungen</div></div>
    </div>
  </section>
"""

_GALERIE_BLOCK = r"""  <!-- GALERIE -->
  {% if c.fotos %}
  <section class="section galerie reveal">
    <div class="wrap">
      <h2 class="section-t">Einblicke</h2>
      <div class="galerie-grid">
        {% for foto in c.fotos %}
        <div class="galerie-item"><img src="{{ foto }}" alt="Galerie {{ forloop.counter }}" loading="lazy"></div>
        {% endfor %}
      </div>
    </div>
  </section>
  {% endif %}
"""

_TESTIMONIALS_BLOCK = r"""  <!-- BEWERTUNGEN -->
  {% if c.bewertungen %}
  <section class="section testimonials reveal">
    <div class="wrap"><h2 class="section-t">Was unsere Kunden sagen</h2>
    <div class="testi-grid">
      {% for b in c.bewertungen %}
      <article class="testi-card">
        <div class="testi-stars">{% for i in "12345" %}★{% endfor %}</div>
        <p class="testi-text">"{{ b.text }}"</p>
        <cite>— {{ b.name }}{% if b.ort %}, {{ b.ort }}{% endif %}</cite>
      </article>
      {% endfor %}
    </div></div>
  </section>
  {% endif %}
"""

_FAQ_BLOCK = r"""  <!-- FAQ -->
  {% if c.faq %}
  <section class="section faq reveal">
    <div class="wrap faq-wrap">
      <h2 class="section-t">Häufige Fragen</h2>
      <div class="faq-list">
        {% for item in c.faq %}
        <details class="faq-item">
          <summary class="faq-q">{{ item.frage }}</summary>
          <div class="faq-a"><p>{{ item.antwort }}</p></div>
        </details>
        {% endfor %}
      </div>
    </div>
  </section>
  {% endif %}
"""

_KONTAKT_BLOCK = r"""  <!-- KONTAKT CTA -->
  <section id="kontakt" class="section kontakt reveal">
    <div class="wrap kontakt-in">
      <div class="kontakt-text">
        <h2>Jetzt Kontakt aufnehmen</h2>
        <p>{{ c.kontakt_text|default:"Wir sind für Sie da. Rufen Sie uns an oder schreiben Sie uns — wir melden uns schnellstmöglich." }}</p>
        <div class="kontakt-actions">
          {% if c.telefon %}<a class="btn" href="tel:{{ c.telefon }}">{{ c.telefon }}</a>{% endif %}
          {% if c.email %}<a class="btn btn-ghost" href="mailto:{{ c.email }}">{{ c.email }}</a>{% endif %}
        </div>
        {% if c.adresse %}<address>{{ c.adresse }}</address>{% endif %}
        {% if c.oeffnungszeiten %}<p class="oeffnungszeiten">{{ c.oeffnungszeiten }}</p>{% endif %}
      </div>
    </div>
  </section>
"""

_FOOTER_BLOCK = r"""  <!-- FOOTER -->
  <footer class="footer">
    <div class="wrap footer-in">
      <p class="footer-brand">{{ c.site_name }}</p>
      <nav class="footer-nav">
        {% if c.impressum_url %}<a href="{{ c.impressum_url }}">Impressum</a>{% endif %}
        {% if c.datenschutz_url %}<a href="{{ c.datenschutz_url }}">Datenschutz</a>{% endif %}
      </nav>
      <p class="footer-copy">&copy; {{ c.jahr|default:"2025" }} {{ c.site_name }}</p>
    </div>
  </footer>
"""

# ---------------------------------------------------------------------------
# VARIANT: BOLD (dark/industrial, trade/construction)
# ---------------------------------------------------------------------------

_HTML_BOLD = (
    _HTML_HEAD
    + r"""  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800&family=Barlow:wght@400;500;600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{% static 'css/style.css' %}">
</head>
<body>
  <header class="nav">
    <div class="wrap nav-in">
      <a class="brand" href="#top">{% if c.logo_image %}<img class="brand-logo" src="{{ c.logo_image }}" alt="{{ c.site_name }}">{% else %}{{ c.site_name }}{% endif %}</a>
      <nav class="nav-links">
        <a href="#leistungen">Leistungen</a>
        <a href="#ueber">Über uns</a>
        <a href="#kontakt">Kontakt</a>
      </nav>
      {% if c.telefon %}<a class="btn btn-sm" href="tel:{{ c.telefon }}">{{ c.telefon }}</a>{% endif %}
    </div>
  </header>

  <main id="top">
    <!-- HERO BOLD: full-bleed dark, diagonal cut -->
    <section class="hero{% if c.hero_image %} hero-banner{% endif %}" {% if c.hero_image %}style="--hero-img:url('{{ c.hero_image }}')"{% elif c.fotos %}style="--hero-img:url('{{ c.fotos.0 }}')"{% endif %}>
      <div class="hero-overlay"></div>
      <div class="wrap hero-in">
        <div class="hero-copy">
          {% if c.stadt %}<span class="eyebrow">{{ c.branche }} &mdash; {{ c.stadt }}</span>{% endif %}
          <h1>{{ c.headline }}</h1>
          <p class="lead">{{ c.subline }}</p>
          <div class="hero-cta">
            <a class="btn" href="#kontakt">{{ c.cta_text }}</a>
            {% if c.telefon %}<a class="btn btn-ghost btn-on-dark" href="tel:{{ c.telefon }}">{{ c.telefon }}</a>{% endif %}
          </div>
        </div>
      </div>
      <div class="hero-cut"></div>
    </section>

    <!-- USP BAND -->
    {% if c.usps %}
    <section class="usp-band reveal">
      <div class="wrap usp-in">
        {% for u in c.usps %}<div class="usp-item"><span class="usp-icon">&#10003;</span>{{ u }}</div>{% endfor %}
      </div>
    </section>
    {% endif %}
"""
    + _LEISTUNGEN_BLOCK
    + _UEBER_BLOCK
    + _STATS_BLOCK
    + _GALERIE_BLOCK
    + _TESTIMONIALS_BLOCK
    + _FAQ_BLOCK
    + _KONTAKT_BLOCK
    + _FOOTER_BLOCK
    + r"""  </main>
"""
    + _HTML_FOOT_SCRIPTS
)

_CSS_BOLD = r""":root {
  --bg: #0d0f14;
  --bg2: #161a23;
  --bg3: #1e2433;
  --accent: #e04c1a;
  --accent2: #ff6b35;
  --text: #f0f2f7;
  --text2: #9aa0b4;
  --card-bg: #1e2433;
  --card-border: #2e3448;
  --radius: 6px;
  --radius-lg: 10px;
  --shadow: 0 4px 24px rgba(0,0,0,0.6);
  --font-head: 'Barlow Condensed', 'Impact', sans-serif;
  --font-body: 'Barlow', system-ui, sans-serif;
  --nav-h: 68px;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
  .reveal { opacity: 1 !important; transform: none !important; }
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body { background: var(--bg); color: var(--text); font-family: var(--font-body); font-size: 1rem; line-height: 1.6; }
img { max-width: 100%; display: block; }
a { color: var(--accent); text-decoration: none; }

.wrap { max-width: 1180px; margin: 0 auto; padding: 0 1.25rem; }

/* NAV */
.nav { position: sticky; top: 0; z-index: 100; background: var(--bg); border-bottom: 1px solid var(--card-border); transition: box-shadow 0.3s; }
.nav-scrolled { box-shadow: 0 2px 20px rgba(0,0,0,0.8); }
.nav-in { display: flex; align-items: center; gap: 2rem; height: var(--nav-h); }
.brand { font-family: var(--font-head); font-size: 1.5rem; font-weight: 800; color: var(--text); letter-spacing: 0.04em; text-transform: uppercase; }
.brand-logo { height: 40px; width: auto; }
.nav-links { display: flex; gap: 1.5rem; margin-left: auto; }
.nav-links a { color: var(--text2); font-weight: 500; font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.05em; transition: color 0.2s; }
.nav-links a:hover { color: var(--accent); }

/* BUTTONS */
.btn { display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.75rem 1.6rem; background: var(--accent); color: #fff; font-family: var(--font-head); font-size: 1rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; border-radius: var(--radius); border: 2px solid var(--accent); transition: background 0.2s, transform 0.15s; cursor: pointer; }
.btn:hover { background: var(--accent2); border-color: var(--accent2); transform: translateY(-2px); }
.btn-sm { padding: 0.55rem 1.2rem; font-size: 0.85rem; }
.btn-ghost { background: transparent; color: var(--text); border-color: rgba(240,242,247,0.4); }
.btn-ghost:hover { background: rgba(240,242,247,0.1); }
.btn-on-dark { color: #fff; border-color: rgba(255,255,255,0.5); }

/* HERO */
.hero { position: relative; min-height: 92vh; display: flex; align-items: center; background: var(--bg2); overflow: hidden; }
.hero-banner { background-image: var(--hero-img); background-size: cover; background-position: center; }
.hero-overlay { position: absolute; inset: 0; background: linear-gradient(120deg, rgba(13,15,20,0.93) 40%, rgba(13,15,20,0.55)); z-index: 1; }
.hero-in { position: relative; z-index: 2; padding-top: 5rem; padding-bottom: 8rem; }
.hero-copy { max-width: 680px; }
.eyebrow { display: inline-block; font-family: var(--font-head); font-size: 0.9rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: var(--accent); margin-bottom: 1rem; }
.hero-copy h1 { font-family: var(--font-head); font-size: clamp(2.8rem, 6vw, 5.5rem); font-weight: 800; line-height: 1.05; text-transform: uppercase; letter-spacing: 0.02em; margin-bottom: 1.2rem; }
.lead { font-size: 1.2rem; color: var(--text2); max-width: 540px; margin-bottom: 2rem; }
.hero-cta { display: flex; flex-wrap: wrap; gap: 1rem; }
.hero-cut { position: absolute; bottom: -1px; left: 0; right: 0; height: 80px; background: var(--bg); clip-path: polygon(0 100%, 100% 0, 100% 100%); z-index: 2; }

/* USP BAND */
.usp-band { background: var(--accent); padding: 1rem 0; }
.usp-in { display: flex; flex-wrap: wrap; gap: 1.5rem; justify-content: center; }
.usp-item { display: flex; align-items: center; gap: 0.5rem; font-family: var(--font-head); font-weight: 700; font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.05em; color: #fff; }
.usp-icon { font-size: 1.1rem; }

/* SECTIONS */
.section { padding: 5rem 0; }
.section-t { font-family: var(--font-head); font-size: clamp(1.8rem, 3.5vw, 2.6rem); font-weight: 800; text-transform: uppercase; letter-spacing: 0.03em; margin-bottom: 2.5rem; color: var(--text); }
.section-t::after { content: ''; display: block; width: 56px; height: 4px; background: var(--accent); margin-top: 0.7rem; border-radius: 2px; }

/* LEISTUNGEN */
.leistungen { background: var(--bg2); }
.leistungen-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 1.5rem; }
.leistung-card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: var(--radius); padding: 1.75rem; transition: border-color 0.2s, box-shadow 0.2s; }
.leistung-card:hover { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
.leistung-icon { font-size: 1.8rem; margin-bottom: 0.75rem; }
.leistung-card h3 { font-family: var(--font-head); font-size: 1.2rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 0.5rem; }
.leistung-card p { color: var(--text2); font-size: 0.95rem; }

/* ÜBER UNS */
.ueber { background: var(--bg); }
.ueber-in { display: grid; grid-template-columns: 1fr 1fr; gap: 4rem; align-items: center; }
.ueber-text .section-t { margin-bottom: 1.5rem; }
.ueber-text p { color: var(--text2); line-height: 1.8; }
.zertifikate { list-style: none; margin-top: 1.5rem; display: flex; flex-direction: column; gap: 0.5rem; }
.zertifikate li { color: var(--text2); font-size: 0.95rem; }
.zertifikate li::before { color: var(--accent); }
.ueber-img img { border-radius: var(--radius-lg); border: 2px solid var(--card-border); }

/* STATS */
.stats { background: var(--bg2); padding: 3.5rem 0; border-top: 1px solid var(--card-border); border-bottom: 1px solid var(--card-border); }
.stats-in { display: flex; justify-content: space-around; flex-wrap: wrap; gap: 2rem; text-align: center; }
.stat-item { display: flex; flex-direction: column; align-items: center; gap: 0.25rem; }
.count-up { font-family: var(--font-head); font-size: clamp(2.8rem, 5vw, 4.5rem); font-weight: 800; color: var(--accent); line-height: 1; }
.stat-plus { font-family: var(--font-head); font-size: 2rem; font-weight: 800; color: var(--accent); }
.stat-label { font-size: 0.85rem; color: var(--text2); text-transform: uppercase; letter-spacing: 0.08em; margin-top: 0.25rem; }

/* GALERIE */
.galerie { background: var(--bg); }
.galerie-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 1rem; }
.galerie-item { border-radius: var(--radius); overflow: hidden; aspect-ratio: 4/3; }
.galerie-item img { width: 100%; height: 100%; object-fit: cover; transition: transform 0.4s; }
.galerie-item:hover img { transform: scale(1.06); }

/* TESTIMONIALS */
.testimonials { background: var(--bg2); }
.testi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.5rem; }
.testi-card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: var(--radius); padding: 1.75rem; transition: border-color 0.2s; }
.testi-card:hover { border-color: var(--accent); }
.testi-stars { color: var(--accent); font-size: 1.1rem; letter-spacing: 0.1em; margin-bottom: 0.75rem; }
.testi-text { color: var(--text2); font-size: 0.97rem; line-height: 1.7; margin-bottom: 1rem; font-style: italic; }
.testi-card cite { font-size: 0.85rem; color: var(--text); font-style: normal; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }

/* FAQ */
.faq { background: var(--bg); }
.faq-wrap { max-width: 780px; }
.faq-list { display: flex; flex-direction: column; gap: 0.75rem; }
.faq-item { border: 1px solid var(--card-border); border-radius: var(--radius); overflow: hidden; }
.faq-q { padding: 1.1rem 1.25rem; cursor: pointer; font-weight: 600; font-size: 1rem; list-style: none; display: flex; justify-content: space-between; align-items: center; background: var(--card-bg); }
.faq-q::after { content: '+'; font-size: 1.4rem; color: var(--accent); transition: transform 0.2s; }
.faq-item[open] .faq-q::after { transform: rotate(45deg); }
.faq-a { padding: 1rem 1.25rem; background: var(--bg2); color: var(--text2); font-size: 0.95rem; line-height: 1.7; }

/* KONTAKT */
.kontakt { background: var(--bg2); }
.kontakt-in { max-width: 640px; }
.kontakt h2 { font-family: var(--font-head); font-size: clamp(1.8rem, 3vw, 2.8rem); font-weight: 800; text-transform: uppercase; margin-bottom: 1rem; }
.kontakt p { color: var(--text2); margin-bottom: 1.5rem; }
.kontakt-actions { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem; }
address { color: var(--text2); font-style: normal; font-size: 0.9rem; }
.oeffnungszeiten { color: var(--text2); font-size: 0.9rem; margin-top: 0.5rem; }

/* FOOTER */
.footer { background: var(--bg); border-top: 1px solid var(--card-border); padding: 2rem 0; }
.footer-in { display: flex; align-items: center; flex-wrap: wrap; gap: 1rem; justify-content: space-between; }
.footer-brand { font-family: var(--font-head); font-weight: 700; text-transform: uppercase; font-size: 1rem; }
.footer-nav { display: flex; gap: 1.5rem; }
.footer-nav a { color: var(--text2); font-size: 0.85rem; }
.footer-nav a:hover { color: var(--accent); }
.footer-copy { color: var(--text2); font-size: 0.8rem; }

/* REVEAL */
.reveal { opacity: 0; transform: translateY(28px); transition: opacity 0.6s ease, transform 0.6s ease; }
.reveal.revealed { opacity: 1; transform: none; }

/* SWIPER */
.swiper-dots { display: flex; justify-content: center; gap: 0.5rem; margin-top: 1.5rem; }
.swiper-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--card-border); border: none; cursor: pointer; }
.swiper-dot.active { background: var(--accent); }

/* RESPONSIVE */
@media (max-width: 760px) {
  .nav-links { display: none; }
  .hero { min-height: 70vh; }
  .hero-copy h1 { font-size: 2.4rem; }
  .ueber-in { grid-template-columns: 1fr; gap: 2rem; }
  .ueber-img { order: -1; }
  .stats-in { gap: 1.5rem; }
  .count-up { font-size: 2.5rem; }
  .section { padding: 3rem 0; }
  .footer-in { flex-direction: column; text-align: center; }
}
"""

# ---------------------------------------------------------------------------
# VARIANT: MODERN (clean clinical white, professional services)
# ---------------------------------------------------------------------------

_HTML_MODERN = (
    _HTML_HEAD
    + r"""  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{% static 'css/style.css' %}">
</head>
<body>
  <header class="nav">
    <div class="wrap nav-in">
      <a class="brand" href="#top">{% if c.logo_image %}<img class="brand-logo" src="{{ c.logo_image }}" alt="{{ c.site_name }}">{% else %}{{ c.site_name }}{% endif %}</a>
      <nav class="nav-links">
        <a href="#leistungen">Leistungen</a>
        <a href="#ueber">Über uns</a>
        <a href="#kontakt">Kontakt</a>
      </nav>
      {% if c.telefon %}<a class="btn btn-sm" href="tel:{{ c.telefon }}">Termin vereinbaren</a>{% endif %}
    </div>
  </header>

  <main id="top">
    <!-- HERO MODERN: split grid, text left, image right -->
    <section class="hero">
      <div class="wrap hero-in">
        <div class="hero-copy">
          {% if c.stadt %}<span class="eyebrow">{{ c.branche }} &middot; {{ c.stadt }}</span>{% endif %}
          <h1>{{ c.headline }}</h1>
          <p class="lead">{{ c.subline }}</p>
          <div class="hero-cta">
            <a class="btn" href="#kontakt">{{ c.cta_text }}</a>
            {% if c.telefon %}<a class="btn btn-ghost" href="tel:{{ c.telefon }}">{{ c.telefon }}</a>{% endif %}
          </div>
        </div>
        {% if c.hero_image %}
        <div class="hero-img-wrap">
          <img src="{{ c.hero_image }}" alt="{{ c.headline }}" class="hero-img" loading="eager">
        </div>
        {% elif c.fotos %}
        <div class="hero-img-wrap">
          <img src="{{ c.fotos.0 }}" alt="{{ c.headline }}" class="hero-img" loading="eager">
        </div>
        {% endif %}
      </div>
    </section>

    <!-- USP BAND -->
    {% if c.usps %}
    <section class="usp-band reveal">
      <div class="wrap usp-in">
        {% for u in c.usps %}<div class="usp-item"><span class="usp-icon">&#10003;</span>{{ u }}</div>{% endfor %}
      </div>
    </section>
    {% endif %}
"""
    + _LEISTUNGEN_BLOCK
    + _UEBER_BLOCK
    + _STATS_BLOCK
    + _GALERIE_BLOCK
    + _TESTIMONIALS_BLOCK
    + _FAQ_BLOCK
    + _KONTAKT_BLOCK
    + _FOOTER_BLOCK
    + r"""  </main>
"""
    + _HTML_FOOT_SCRIPTS
)

_CSS_MODERN = r""":root {
  --bg: #ffffff;
  --bg2: #f8fafb;
  --bg3: #eef2f7;
  --accent: #1a6fe8;
  --accent2: #0f52c4;
  --text: #0f1826;
  --text2: #5a6a82;
  --card-bg: #ffffff;
  --card-border: #e2eaf4;
  --radius: 20px;
  --radius-lg: 28px;
  --shadow: 0 4px 24px rgba(26,111,232,0.08);
  --shadow-hover: 0 8px 40px rgba(26,111,232,0.15);
  --font-head: 'Inter', system-ui, sans-serif;
  --font-body: 'Inter', system-ui, sans-serif;
  --nav-h: 72px;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
  .reveal { opacity: 1 !important; transform: none !important; }
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body { background: var(--bg); color: var(--text); font-family: var(--font-body); font-size: 1rem; line-height: 1.65; }
img { max-width: 100%; display: block; }
a { color: var(--accent); text-decoration: none; }

.wrap { max-width: 1180px; margin: 0 auto; padding: 0 1.25rem; }

/* NAV */
.nav { position: sticky; top: 0; z-index: 100; background: rgba(255,255,255,0.95); backdrop-filter: blur(12px); border-bottom: 1px solid var(--card-border); transition: box-shadow 0.3s; }
.nav-scrolled { box-shadow: 0 2px 24px rgba(26,111,232,0.07); }
.nav-in { display: flex; align-items: center; gap: 2rem; height: var(--nav-h); }
.brand { font-size: 1.25rem; font-weight: 700; color: var(--text); letter-spacing: -0.02em; }
.brand-logo { height: 36px; width: auto; }
.nav-links { display: flex; gap: 2rem; margin-left: auto; }
.nav-links a { color: var(--text2); font-size: 0.9rem; font-weight: 500; transition: color 0.2s; }
.nav-links a:hover { color: var(--accent); }

/* BUTTONS */
.btn { display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.75rem 1.6rem; background: var(--accent); color: #fff; font-size: 0.9rem; font-weight: 600; border-radius: var(--radius); border: 1.5px solid var(--accent); transition: background 0.2s, transform 0.15s, box-shadow 0.2s; cursor: pointer; }
.btn:hover { background: var(--accent2); border-color: var(--accent2); transform: translateY(-2px); box-shadow: 0 6px 20px rgba(26,111,232,0.3); }
.btn-sm { padding: 0.55rem 1.2rem; font-size: 0.85rem; }
.btn-ghost { background: transparent; color: var(--accent); border-color: var(--accent); }
.btn-ghost:hover { background: rgba(26,111,232,0.06); transform: translateY(-2px); }

/* HERO split */
.hero { padding: var(--nav-h) 0 4rem; background: linear-gradient(135deg, var(--bg) 60%, var(--bg2) 100%); overflow: hidden; }
.hero-in { display: grid; grid-template-columns: 1fr 1fr; gap: 4rem; align-items: center; min-height: calc(88vh - var(--nav-h)); }
.eyebrow { display: inline-flex; align-items: center; gap: 0.5rem; background: rgba(26,111,232,0.09); color: var(--accent); font-size: 0.8rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; padding: 0.35rem 0.9rem; border-radius: 100px; margin-bottom: 1.25rem; }
.hero-copy h1 { font-size: clamp(2rem, 4vw, 3.4rem); font-weight: 700; line-height: 1.15; letter-spacing: -0.03em; margin-bottom: 1.25rem; color: var(--text); }
.lead { font-size: 1.1rem; color: var(--text2); max-width: 480px; margin-bottom: 2rem; }
.hero-cta { display: flex; flex-wrap: wrap; gap: 1rem; }
.hero-img-wrap { border-radius: var(--radius-lg); overflow: hidden; box-shadow: var(--shadow-hover); }
.hero-img { width: 100%; height: 520px; object-fit: cover; }

/* USP BAND */
.usp-band { background: var(--bg2); border-top: 1px solid var(--card-border); border-bottom: 1px solid var(--card-border); padding: 1.25rem 0; }
.usp-in { display: flex; flex-wrap: wrap; gap: 2rem; justify-content: center; }
.usp-item { display: flex; align-items: center; gap: 0.5rem; font-size: 0.9rem; font-weight: 600; color: var(--text); }
.usp-icon { color: var(--accent); font-size: 1rem; }

/* SECTIONS */
.section { padding: 5rem 0; }
.section-t { font-size: clamp(1.6rem, 3vw, 2.2rem); font-weight: 700; letter-spacing: -0.02em; margin-bottom: 2.5rem; color: var(--text); }
.section-t::after { content: ''; display: block; width: 40px; height: 3px; background: var(--accent); margin-top: 0.75rem; border-radius: 2px; }

/* LEISTUNGEN */
.leistungen { background: var(--bg); }
.leistungen-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 1.5rem; }
.leistung-card { background: var(--card-bg); border: 1.5px solid var(--card-border); border-radius: var(--radius); padding: 2rem; box-shadow: var(--shadow); transition: box-shadow 0.25s, transform 0.25s; }
.leistung-card:hover { box-shadow: var(--shadow-hover); transform: translateY(-4px); }
.leistung-icon { font-size: 1.75rem; margin-bottom: 0.75rem; }
.leistung-card h3 { font-size: 1.05rem; font-weight: 700; margin-bottom: 0.5rem; }
.leistung-card p { color: var(--text2); font-size: 0.93rem; }

/* ÜBER UNS */
.ueber { background: var(--bg2); }
.ueber-in { display: grid; grid-template-columns: 1fr 1fr; gap: 4rem; align-items: center; }
.ueber-text p { color: var(--text2); line-height: 1.8; }
.zertifikate { list-style: none; margin-top: 1.25rem; display: flex; flex-direction: column; gap: 0.45rem; }
.zertifikate li { color: var(--text2); font-size: 0.93rem; display: flex; align-items: center; gap: 0.5rem; }
.ueber-img img { border-radius: var(--radius-lg); box-shadow: var(--shadow); }

/* STATS */
.stats { background: var(--accent); padding: 4rem 0; }
.stats-in { display: flex; justify-content: space-around; flex-wrap: wrap; gap: 2rem; text-align: center; }
.stat-item { display: flex; flex-direction: column; align-items: center; gap: 0.2rem; }
.count-up { font-size: clamp(2.6rem, 5vw, 4rem); font-weight: 700; color: #fff; line-height: 1; letter-spacing: -0.03em; }
.stat-plus { font-size: 1.8rem; font-weight: 700; color: rgba(255,255,255,0.8); }
.stat-label { font-size: 0.8rem; color: rgba(255,255,255,0.75); font-weight: 500; text-transform: uppercase; letter-spacing: 0.08em; margin-top: 0.25rem; }

/* GALERIE */
.galerie { background: var(--bg); }
.galerie-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 1rem; }
.galerie-item { border-radius: var(--radius); overflow: hidden; aspect-ratio: 4/3; }
.galerie-item img { width: 100%; height: 100%; object-fit: cover; transition: transform 0.4s; }
.galerie-item:hover img { transform: scale(1.05); }

/* TESTIMONIALS */
.testimonials { background: var(--bg2); }
.testi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.5rem; }
.testi-card { background: var(--card-bg); border: 1.5px solid var(--card-border); border-radius: var(--radius); padding: 1.75rem; box-shadow: var(--shadow); transition: box-shadow 0.25s; }
.testi-card:hover { box-shadow: var(--shadow-hover); }
.testi-stars { color: #f59e0b; font-size: 1.05rem; letter-spacing: 0.1em; margin-bottom: 0.75rem; }
.testi-text { color: var(--text2); font-size: 0.95rem; line-height: 1.7; margin-bottom: 1rem; font-style: italic; }
.testi-card cite { font-size: 0.85rem; color: var(--text); font-style: normal; font-weight: 600; }

/* FAQ */
.faq { background: var(--bg); }
.faq-wrap { max-width: 760px; }
.faq-list { display: flex; flex-direction: column; gap: 0.75rem; }
.faq-item { border: 1.5px solid var(--card-border); border-radius: var(--radius); overflow: hidden; }
.faq-q { padding: 1.1rem 1.25rem; cursor: pointer; font-weight: 600; font-size: 0.97rem; list-style: none; display: flex; justify-content: space-between; align-items: center; background: var(--bg2); color: var(--text); }
.faq-q::after { content: '+'; font-size: 1.3rem; color: var(--accent); transition: transform 0.2s; }
.faq-item[open] .faq-q::after { transform: rotate(45deg); }
.faq-a { padding: 1rem 1.25rem; background: var(--bg); color: var(--text2); font-size: 0.93rem; line-height: 1.7; }

/* KONTAKT */
.kontakt { background: linear-gradient(135deg, var(--bg2) 0%, var(--bg) 100%); }
.kontakt-in { max-width: 620px; }
.kontakt h2 { font-size: clamp(1.6rem, 3vw, 2.4rem); font-weight: 700; letter-spacing: -0.02em; margin-bottom: 1rem; }
.kontakt p { color: var(--text2); margin-bottom: 1.5rem; }
.kontakt-actions { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem; }
address { color: var(--text2); font-style: normal; font-size: 0.9rem; }
.oeffnungszeiten { color: var(--text2); font-size: 0.9rem; margin-top: 0.5rem; }

/* FOOTER */
.footer { background: var(--text); padding: 2rem 0; }
.footer-in { display: flex; align-items: center; flex-wrap: wrap; gap: 1rem; justify-content: space-between; }
.footer-brand { font-weight: 700; font-size: 1rem; color: #fff; }
.footer-nav { display: flex; gap: 1.5rem; }
.footer-nav a { color: rgba(255,255,255,0.55); font-size: 0.85rem; transition: color 0.2s; }
.footer-nav a:hover { color: #fff; }
.footer-copy { color: rgba(255,255,255,0.4); font-size: 0.8rem; }

/* REVEAL */
.reveal { opacity: 0; transform: translateY(24px); transition: opacity 0.6s ease, transform 0.6s ease; }
.reveal.revealed { opacity: 1; transform: none; }

/* SWIPER */
.swiper-dots { display: flex; justify-content: center; gap: 0.5rem; margin-top: 1.5rem; }
.swiper-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--card-border); border: none; cursor: pointer; }
.swiper-dot.active { background: var(--accent); }

/* RESPONSIVE */
@media (max-width: 760px) {
  .nav-links { display: none; }
  .hero-in { grid-template-columns: 1fr; gap: 2rem; min-height: auto; padding: 2rem 0; }
  .hero-img { height: 280px; }
  .hero-copy h1 { font-size: 1.9rem; }
  .ueber-in { grid-template-columns: 1fr; gap: 2rem; }
  .stats-in { gap: 1.5rem; }
  .count-up { font-size: 2.4rem; }
  .section { padding: 3rem 0; }
  .footer-in { flex-direction: column; text-align: center; }
}
"""

# ---------------------------------------------------------------------------
# VARIANT: WARM (earthy friendly, hospitality/beauty)
# ---------------------------------------------------------------------------

_HTML_WARM = (
    _HTML_HEAD
    + r"""  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,500;0,600;0,700;1,500&family=Source+Sans+3:wght@400;500;600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{% static 'css/style.css' %}">
</head>
<body>
  <header class="nav">
    <div class="wrap nav-in">
      <a class="brand" href="#top">{% if c.logo_image %}<img class="brand-logo" src="{{ c.logo_image }}" alt="{{ c.site_name }}">{% else %}{{ c.site_name }}{% endif %}</a>
      <nav class="nav-links">
        <a href="#leistungen">Leistungen</a>
        <a href="#ueber">Über uns</a>
        <a href="#kontakt">Kontakt</a>
      </nav>
      {% if c.telefon %}<a class="btn btn-sm" href="tel:{{ c.telefon }}">Reservieren</a>{% endif %}
    </div>
  </header>

  <main id="top">
    <!-- HERO WARM: warm gradient overlay, centered text -->
    <section class="hero{% if c.hero_image %} hero-banner{% endif %}" {% if c.hero_image %}style="--hero-img:url('{{ c.hero_image }}')"{% elif c.fotos %}style="--hero-img:url('{{ c.fotos.0 }}')"{% endif %}>
      <div class="hero-overlay"></div>
      <div class="wrap hero-in">
        <div class="hero-copy">
          {% if c.stadt %}<span class="eyebrow">{{ c.branche }} &bull; {{ c.stadt }}</span>{% endif %}
          <h1>{{ c.headline }}</h1>
          <p class="lead">{{ c.subline }}</p>
          <div class="hero-cta">
            <a class="btn" href="#kontakt">{{ c.cta_text }}</a>
            {% if c.telefon %}<a class="btn btn-ghost btn-on-dark" href="tel:{{ c.telefon }}">{{ c.telefon }}</a>{% endif %}
          </div>
        </div>
      </div>
    </section>

    <!-- USP BAND -->
    {% if c.usps %}
    <section class="usp-band reveal">
      <div class="wrap usp-in">
        {% for u in c.usps %}<div class="usp-item"><span class="usp-icon">&#9829;</span>{{ u }}</div>{% endfor %}
      </div>
    </section>
    {% endif %}
"""
    + _LEISTUNGEN_BLOCK
    + _UEBER_BLOCK
    + _STATS_BLOCK
    + _GALERIE_BLOCK
    + _TESTIMONIALS_BLOCK
    + _FAQ_BLOCK
    + _KONTAKT_BLOCK
    + _FOOTER_BLOCK
    + r"""  </main>
"""
    + _HTML_FOOT_SCRIPTS
)

_CSS_WARM = r""":root {
  --bg: #fdf8f3;
  --bg2: #f5ede3;
  --bg3: #ede0d3;
  --accent: #c85a2a;
  --accent2: #a04522;
  --accent-light: #f9e4d8;
  --text: #2d1f14;
  --text2: #7a5c48;
  --card-bg: #fdf8f3;
  --card-border: #e5d5c4;
  --radius: 24px;
  --radius-lg: 32px;
  --shadow: 0 4px 20px rgba(200,90,42,0.08);
  --shadow-hover: 0 8px 36px rgba(200,90,42,0.15);
  --font-head: 'Lora', Georgia, serif;
  --font-body: 'Source Sans 3', system-ui, sans-serif;
  --nav-h: 70px;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
  .reveal { opacity: 1 !important; transform: none !important; }
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body { background: var(--bg); color: var(--text); font-family: var(--font-body); font-size: 1rem; line-height: 1.7; }
img { max-width: 100%; display: block; }
a { color: var(--accent); text-decoration: none; }

.wrap { max-width: 1180px; margin: 0 auto; padding: 0 1.25rem; }

/* NAV */
.nav { position: sticky; top: 0; z-index: 100; background: rgba(253,248,243,0.96); backdrop-filter: blur(8px); border-bottom: 1px solid var(--card-border); transition: box-shadow 0.3s; }
.nav-scrolled { box-shadow: 0 2px 20px rgba(200,90,42,0.07); }
.nav-in { display: flex; align-items: center; gap: 2rem; height: var(--nav-h); }
.brand { font-family: var(--font-head); font-size: 1.35rem; font-weight: 600; color: var(--text); font-style: italic; }
.brand-logo { height: 38px; width: auto; }
.nav-links { display: flex; gap: 2rem; margin-left: auto; }
.nav-links a { color: var(--text2); font-size: 0.92rem; font-weight: 500; transition: color 0.2s; }
.nav-links a:hover { color: var(--accent); }

/* BUTTONS */
.btn { display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.8rem 1.8rem; background: var(--accent); color: #fff; font-family: var(--font-body); font-size: 0.95rem; font-weight: 600; border-radius: var(--radius); border: 2px solid var(--accent); transition: background 0.2s, transform 0.15s; cursor: pointer; }
.btn:hover { background: var(--accent2); border-color: var(--accent2); transform: translateY(-2px); }
.btn-sm { padding: 0.55rem 1.3rem; font-size: 0.85rem; }
.btn-ghost { background: transparent; color: var(--text); border-color: rgba(45,31,20,0.3); }
.btn-ghost:hover { background: rgba(45,31,20,0.06); }
.btn-on-dark { color: #fff; border-color: rgba(255,255,255,0.6); }
.btn-on-dark:hover { background: rgba(255,255,255,0.15); }

/* HERO */
.hero { position: relative; min-height: 90vh; display: flex; align-items: center; background: var(--bg2); overflow: hidden; }
.hero-banner { background-image: var(--hero-img); background-size: cover; background-position: center; }
.hero-overlay { position: absolute; inset: 0; background: linear-gradient(to bottom, rgba(45,31,20,0.6) 0%, rgba(45,31,20,0.35) 100%); z-index: 1; }
.hero-in { position: relative; z-index: 2; padding: 6rem 0; text-align: center; }
.hero-copy { max-width: 700px; margin: 0 auto; }
.eyebrow { display: inline-block; font-family: var(--font-body); font-size: 0.82rem; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; color: rgba(255,255,255,0.8); background: rgba(200,90,42,0.7); padding: 0.35rem 1rem; border-radius: 100px; margin-bottom: 1.25rem; }
.hero-copy h1 { font-family: var(--font-head); font-size: clamp(2.4rem, 5.5vw, 4.5rem); font-weight: 700; line-height: 1.15; color: #fff; margin-bottom: 1.25rem; }
.lead { font-size: 1.15rem; color: rgba(255,255,255,0.85); max-width: 520px; margin: 0 auto 2rem; }
.hero-cta { display: flex; flex-wrap: wrap; gap: 1rem; justify-content: center; }

/* USP BAND */
.usp-band { background: var(--accent); padding: 1.1rem 0; }
.usp-in { display: flex; flex-wrap: wrap; gap: 2rem; justify-content: center; }
.usp-item { display: flex; align-items: center; gap: 0.5rem; font-size: 0.92rem; font-weight: 600; color: #fff; }
.usp-icon { font-size: 0.85rem; opacity: 0.8; }

/* SECTIONS */
.section { padding: 5rem 0; }
.section-t { font-family: var(--font-head); font-size: clamp(1.7rem, 3.2vw, 2.4rem); font-weight: 600; color: var(--text); margin-bottom: 2.5rem; }
.section-t::after { content: ''; display: block; width: 48px; height: 3px; background: var(--accent); margin-top: 0.75rem; border-radius: 2px; }

/* LEISTUNGEN */
.leistungen { background: var(--bg); }
.leistungen-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(255px, 1fr)); gap: 1.5rem; }
.leistung-card { background: var(--bg2); border: 1.5px solid var(--card-border); border-radius: var(--radius); padding: 2rem; transition: box-shadow 0.25s, transform 0.25s; }
.leistung-card:hover { box-shadow: var(--shadow-hover); transform: translateY(-3px); }
.leistung-icon { font-size: 1.8rem; margin-bottom: 0.8rem; }
.leistung-card h3 { font-family: var(--font-head); font-size: 1.1rem; font-weight: 600; margin-bottom: 0.5rem; }
.leistung-card p { color: var(--text2); font-size: 0.93rem; }

/* ÜBER UNS */
.ueber { background: var(--bg2); }
.ueber-in { display: grid; grid-template-columns: 1fr 1fr; gap: 4rem; align-items: center; }
.ueber-text p { color: var(--text2); line-height: 1.85; }
.zertifikate { list-style: none; margin-top: 1.25rem; display: flex; flex-direction: column; gap: 0.45rem; }
.zertifikate li { color: var(--text2); font-size: 0.92rem; display: flex; gap: 0.5rem; }
.ueber-img img { border-radius: var(--radius-lg); box-shadow: var(--shadow); }

/* STATS */
.stats { background: var(--bg3); padding: 4rem 0; border-top: 1px solid var(--card-border); border-bottom: 1px solid var(--card-border); }
.stats-in { display: flex; justify-content: space-around; flex-wrap: wrap; gap: 2rem; text-align: center; }
.stat-item { display: flex; flex-direction: column; align-items: center; gap: 0.2rem; }
.count-up { font-family: var(--font-head); font-size: clamp(2.6rem, 4.5vw, 4rem); font-weight: 700; color: var(--accent); line-height: 1; }
.stat-plus { font-family: var(--font-head); font-size: 1.8rem; font-weight: 600; color: var(--accent); }
.stat-label { font-size: 0.82rem; color: var(--text2); text-transform: uppercase; letter-spacing: 0.08em; margin-top: 0.25rem; }

/* GALERIE */
.galerie { background: var(--bg); }
.galerie-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 1.1rem; }
.galerie-item { border-radius: var(--radius); overflow: hidden; aspect-ratio: 4/3; }
.galerie-item img { width: 100%; height: 100%; object-fit: cover; transition: transform 0.4s; }
.galerie-item:hover img { transform: scale(1.05); }

/* TESTIMONIALS */
.testimonials { background: var(--bg2); }
.testi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(275px, 1fr)); gap: 1.5rem; }
.testi-card { background: var(--card-bg); border: 1.5px solid var(--card-border); border-radius: var(--radius); padding: 1.75rem; box-shadow: var(--shadow); }
.testi-stars { color: var(--accent); font-size: 1.05rem; letter-spacing: 0.1em; margin-bottom: 0.75rem; }
.testi-text { color: var(--text2); font-size: 0.95rem; line-height: 1.75; margin-bottom: 1rem; font-style: italic; font-family: var(--font-head); }
.testi-card cite { font-size: 0.85rem; color: var(--text); font-style: normal; font-weight: 600; }

/* FAQ */
.faq { background: var(--bg); }
.faq-wrap { max-width: 760px; }
.faq-list { display: flex; flex-direction: column; gap: 0.75rem; }
.faq-item { border: 1.5px solid var(--card-border); border-radius: var(--radius); overflow: hidden; }
.faq-q { padding: 1.1rem 1.25rem; cursor: pointer; font-weight: 600; font-size: 0.97rem; list-style: none; display: flex; justify-content: space-between; align-items: center; background: var(--bg2); color: var(--text); }
.faq-q::after { content: '+'; font-size: 1.3rem; color: var(--accent); transition: transform 0.2s; }
.faq-item[open] .faq-q::after { transform: rotate(45deg); }
.faq-a { padding: 1rem 1.25rem; background: var(--bg); color: var(--text2); font-size: 0.93rem; line-height: 1.75; }

/* KONTAKT */
.kontakt { background: var(--accent-light); }
.kontakt-in { max-width: 620px; }
.kontakt h2 { font-family: var(--font-head); font-size: clamp(1.7rem, 3vw, 2.4rem); font-weight: 600; margin-bottom: 1rem; color: var(--text); }
.kontakt p { color: var(--text2); margin-bottom: 1.5rem; }
.kontakt-actions { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem; }
address { color: var(--text2); font-style: normal; font-size: 0.9rem; }
.oeffnungszeiten { color: var(--text2); font-size: 0.9rem; margin-top: 0.5rem; }

/* FOOTER */
.footer { background: var(--text); padding: 2rem 0; }
.footer-in { display: flex; align-items: center; flex-wrap: wrap; gap: 1rem; justify-content: space-between; }
.footer-brand { font-family: var(--font-head); font-weight: 600; font-size: 1rem; color: #fff; font-style: italic; }
.footer-nav { display: flex; gap: 1.5rem; }
.footer-nav a { color: rgba(255,255,255,0.5); font-size: 0.85rem; }
.footer-nav a:hover { color: #fff; }
.footer-copy { color: rgba(255,255,255,0.35); font-size: 0.8rem; }

/* REVEAL */
.reveal { opacity: 0; transform: translateY(24px); transition: opacity 0.65s ease, transform 0.65s ease; }
.reveal.revealed { opacity: 1; transform: none; }

/* SWIPER */
.swiper-dots { display: flex; justify-content: center; gap: 0.5rem; margin-top: 1.5rem; }
.swiper-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--card-border); border: none; cursor: pointer; }
.swiper-dot.active { background: var(--accent); }

/* RESPONSIVE */
@media (max-width: 760px) {
  .nav-links { display: none; }
  .hero { min-height: 72vh; }
  .hero-copy h1 { font-size: 2.2rem; }
  .ueber-in { grid-template-columns: 1fr; gap: 2rem; }
  .stats-in { gap: 1.5rem; }
  .count-up { font-size: 2.4rem; }
  .section { padding: 3rem 0; }
  .footer-in { flex-direction: column; text-align: center; }
}
"""

# ---------------------------------------------------------------------------
# VARIANT: CRAFT (industrial hands-on, tradespeople)
# ---------------------------------------------------------------------------

_HTML_CRAFT = (
    _HTML_HEAD
    + r"""  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&family=Roboto:wght@400;500;600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{% static 'css/style.css' %}">
</head>
<body>
  <header class="nav">
    <div class="wrap nav-in">
      <a class="brand" href="#top">{% if c.logo_image %}<img class="brand-logo" src="{{ c.logo_image }}" alt="{{ c.site_name }}">{% else %}{{ c.site_name }}{% endif %}</a>
      <nav class="nav-links">
        <a href="#leistungen">Leistungen</a>
        <a href="#ueber">Über uns</a>
        <a href="#kontakt">Kontakt</a>
      </nav>
      {% if c.telefon %}<a class="btn btn-sm" href="tel:{{ c.telefon }}">Angebot anfragen</a>{% endif %}
    </div>
  </header>

  <main id="top">
    <!-- HERO CRAFT: solid with texture overlay, no-nonsense -->
    <section class="hero{% if c.hero_image %} hero-banner{% endif %}" {% if c.hero_image %}style="--hero-img:url('{{ c.hero_image }}')"{% elif c.fotos %}style="--hero-img:url('{{ c.fotos.0 }}')"{% endif %}>
      <div class="hero-overlay"></div>
      <div class="wrap hero-in">
        <div class="hero-copy">
          {% if c.stadt %}<span class="eyebrow">{{ c.branche }} &ndash; {{ c.stadt }}</span>{% endif %}
          <h1>{{ c.headline }}</h1>
          <p class="lead">{{ c.subline }}</p>
          <div class="hero-cta">
            <a class="btn" href="#kontakt">{{ c.cta_text }}</a>
            {% if c.telefon %}<a class="btn btn-ghost btn-on-dark" href="tel:{{ c.telefon }}">{{ c.telefon }}</a>{% endif %}
          </div>
        </div>
      </div>
    </section>

    <!-- USP BAND -->
    {% if c.usps %}
    <section class="usp-band reveal">
      <div class="wrap usp-in">
        {% for u in c.usps %}<div class="usp-item"><span class="usp-icon">&#9670;</span>{{ u }}</div>{% endfor %}
      </div>
    </section>
    {% endif %}
"""
    + _LEISTUNGEN_BLOCK
    + _UEBER_BLOCK
    + _STATS_BLOCK
    + _GALERIE_BLOCK
    + _TESTIMONIALS_BLOCK
    + _FAQ_BLOCK
    + _KONTAKT_BLOCK
    + _FOOTER_BLOCK
    + r"""  </main>
"""
    + _HTML_FOOT_SCRIPTS
)

_CSS_CRAFT = r""":root {
  --bg: #f4f1ec;
  --bg2: #e8e3db;
  --bg3: #ddd6cb;
  --accent: #7a4a23;
  --accent2: #5e3719;
  --accent-light: #f0e8de;
  --text: #1e1510;
  --text2: #6b5540;
  --card-bg: #ede8e0;
  --card-border: #cfc8bd;
  --radius: 4px;
  --radius-lg: 8px;
  --shadow: 0 3px 12px rgba(122,74,35,0.12);
  --shadow-hover: 0 6px 24px rgba(122,74,35,0.2);
  --font-head: 'Playfair Display', Georgia, serif;
  --font-body: 'Roboto', system-ui, sans-serif;
  --nav-h: 68px;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
  .reveal { opacity: 1 !important; transform: none !important; }
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body { background: var(--bg); color: var(--text); font-family: var(--font-body); font-size: 1rem; line-height: 1.65; }
img { max-width: 100%; display: block; }
a { color: var(--accent); text-decoration: none; }

.wrap { max-width: 1180px; margin: 0 auto; padding: 0 1.25rem; }

/* NAV */
.nav { position: sticky; top: 0; z-index: 100; background: var(--bg); border-bottom: 2px solid var(--card-border); transition: box-shadow 0.3s; }
.nav-scrolled { box-shadow: 0 3px 16px rgba(122,74,35,0.1); }
.nav-in { display: flex; align-items: center; gap: 2rem; height: var(--nav-h); }
.brand { font-family: var(--font-head); font-size: 1.4rem; font-weight: 800; color: var(--text); }
.brand-logo { height: 40px; width: auto; }
.nav-links { display: flex; gap: 1.75rem; margin-left: auto; }
.nav-links a { color: var(--text2); font-size: 0.9rem; font-weight: 500; transition: color 0.2s; }
.nav-links a:hover { color: var(--accent); }

/* BUTTONS */
.btn { display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.75rem 1.6rem; background: var(--accent); color: #fff; font-size: 0.92rem; font-weight: 600; border-radius: var(--radius); border: 2px solid var(--accent); transition: background 0.2s; cursor: pointer; }
.btn:hover { background: var(--accent2); border-color: var(--accent2); }
.btn-sm { padding: 0.55rem 1.2rem; font-size: 0.85rem; }
.btn-ghost { background: transparent; color: var(--text); border-color: var(--card-border); }
.btn-ghost:hover { background: rgba(0,0,0,0.05); }
.btn-on-dark { color: #fff; border-color: rgba(255,255,255,0.5); }
.btn-on-dark:hover { background: rgba(255,255,255,0.12); }

/* HERO */
.hero { position: relative; min-height: 88vh; display: flex; align-items: center; background: var(--bg2); overflow: hidden; }
.hero-banner { background-image: var(--hero-img); background-size: cover; background-position: center; }
.hero-overlay { position: absolute; inset: 0; background: linear-gradient(90deg, rgba(30,21,16,0.88) 0%, rgba(30,21,16,0.5) 70%); z-index: 1; }
.hero-in { position: relative; z-index: 2; padding: 5rem 0 7rem; }
.hero-copy { max-width: 640px; }
.eyebrow { display: inline-block; font-size: 0.85rem; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: rgba(255,255,255,0.75); border-left: 3px solid var(--accent); padding-left: 0.75rem; margin-bottom: 1rem; }
.hero-copy h1 { font-family: var(--font-head); font-size: clamp(2.4rem, 5.5vw, 4.8rem); font-weight: 800; line-height: 1.1; color: #fff; margin-bottom: 1.25rem; }
.lead { font-size: 1.1rem; color: rgba(255,255,255,0.78); max-width: 520px; margin-bottom: 2rem; }
.hero-cta { display: flex; flex-wrap: wrap; gap: 1rem; }

/* USP BAND */
.usp-band { background: var(--accent); padding: 1rem 0; }
.usp-in { display: flex; flex-wrap: wrap; gap: 1.75rem; justify-content: center; }
.usp-item { display: flex; align-items: center; gap: 0.5rem; font-size: 0.9rem; font-weight: 600; color: #fff; letter-spacing: 0.02em; }
.usp-icon { font-size: 0.65rem; opacity: 0.8; }

/* SECTIONS */
.section { padding: 5rem 0; }
.section-t { font-family: var(--font-head); font-size: clamp(1.7rem, 3.2vw, 2.5rem); font-weight: 800; margin-bottom: 2.5rem; color: var(--text); }
.section-t::after { content: ''; display: block; width: 52px; height: 3px; background: var(--accent); margin-top: 0.7rem; }

/* LEISTUNGEN */
.leistungen { background: var(--bg2); }
.leistungen-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(255px, 1fr)); gap: 1.25rem; }
.leistung-card { background: var(--card-bg); border: 2px solid var(--card-border); border-radius: var(--radius); padding: 1.75rem; transition: border-color 0.2s, box-shadow 0.2s; }
.leistung-card:hover { border-color: var(--accent); box-shadow: var(--shadow-hover); }
.leistung-icon { font-size: 1.75rem; margin-bottom: 0.75rem; }
.leistung-card h3 { font-family: var(--font-head); font-size: 1.15rem; font-weight: 700; margin-bottom: 0.5rem; }
.leistung-card p { color: var(--text2); font-size: 0.93rem; }

/* ÜBER UNS */
.ueber { background: var(--bg); }
.ueber-in { display: grid; grid-template-columns: 1fr 1fr; gap: 4rem; align-items: center; }
.ueber-text p { color: var(--text2); line-height: 1.8; }
.zertifikate { list-style: none; margin-top: 1.25rem; display: flex; flex-direction: column; gap: 0.45rem; }
.zertifikate li { color: var(--text2); font-size: 0.92rem; display: flex; gap: 0.5rem; }
.ueber-img img { border-radius: var(--radius-lg); border: 2px solid var(--card-border); }

/* STATS */
.stats { background: var(--text); padding: 4rem 0; }
.stats-in { display: flex; justify-content: space-around; flex-wrap: wrap; gap: 2rem; text-align: center; }
.stat-item { display: flex; flex-direction: column; align-items: center; gap: 0.2rem; }
.count-up { font-family: var(--font-head); font-size: clamp(2.6rem, 5vw, 4.2rem); font-weight: 800; color: var(--accent); line-height: 1; }
.stat-plus { font-family: var(--font-head); font-size: 1.9rem; font-weight: 700; color: var(--accent); }
.stat-label { font-size: 0.82rem; color: rgba(244,241,236,0.6); text-transform: uppercase; letter-spacing: 0.08em; margin-top: 0.25rem; }

/* GALERIE */
.galerie { background: var(--bg2); }
.galerie-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 0.875rem; }
.galerie-item { border-radius: var(--radius); overflow: hidden; aspect-ratio: 4/3; border: 2px solid var(--card-border); }
.galerie-item img { width: 100%; height: 100%; object-fit: cover; transition: transform 0.4s; }
.galerie-item:hover img { transform: scale(1.06); }

/* TESTIMONIALS */
.testimonials { background: var(--bg); }
.testi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(275px, 1fr)); gap: 1.25rem; }
.testi-card { background: var(--card-bg); border: 2px solid var(--card-border); border-radius: var(--radius); padding: 1.75rem; }
.testi-stars { color: var(--accent); font-size: 1.05rem; letter-spacing: 0.1em; margin-bottom: 0.75rem; }
.testi-text { color: var(--text2); font-size: 0.95rem; line-height: 1.75; margin-bottom: 1rem; font-style: italic; font-family: var(--font-head); }
.testi-card cite { font-size: 0.85rem; color: var(--text); font-style: normal; font-weight: 600; }

/* FAQ */
.faq { background: var(--bg2); }
.faq-wrap { max-width: 760px; }
.faq-list { display: flex; flex-direction: column; gap: 0.5rem; }
.faq-item { border: 2px solid var(--card-border); border-radius: var(--radius); overflow: hidden; }
.faq-q { padding: 1.1rem 1.25rem; cursor: pointer; font-weight: 600; font-size: 0.97rem; list-style: none; display: flex; justify-content: space-between; align-items: center; background: var(--card-bg); color: var(--text); }
.faq-q::after { content: '+'; font-size: 1.3rem; color: var(--accent); transition: transform 0.2s; }
.faq-item[open] .faq-q::after { transform: rotate(45deg); }
.faq-a { padding: 1rem 1.25rem; background: var(--bg); color: var(--text2); font-size: 0.93rem; line-height: 1.75; }

/* KONTAKT */
.kontakt { background: var(--accent-light); }
.kontakt-in { max-width: 620px; }
.kontakt h2 { font-family: var(--font-head); font-size: clamp(1.7rem, 3vw, 2.5rem); font-weight: 800; margin-bottom: 1rem; }
.kontakt p { color: var(--text2); margin-bottom: 1.5rem; }
.kontakt-actions { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem; }
address { color: var(--text2); font-style: normal; font-size: 0.9rem; }
.oeffnungszeiten { color: var(--text2); font-size: 0.9rem; margin-top: 0.5rem; }

/* FOOTER */
.footer { background: var(--text); padding: 2rem 0; }
.footer-in { display: flex; align-items: center; flex-wrap: wrap; gap: 1rem; justify-content: space-between; }
.footer-brand { font-family: var(--font-head); font-weight: 700; font-size: 1.05rem; color: #fff; }
.footer-nav { display: flex; gap: 1.5rem; }
.footer-nav a { color: rgba(244,241,236,0.45); font-size: 0.85rem; }
.footer-nav a:hover { color: rgba(244,241,236,0.9); }
.footer-copy { color: rgba(244,241,236,0.3); font-size: 0.8rem; }

/* REVEAL */
.reveal { opacity: 0; transform: translateY(20px); transition: opacity 0.55s ease, transform 0.55s ease; }
.reveal.revealed { opacity: 1; transform: none; }

/* SWIPER */
.swiper-dots { display: flex; justify-content: center; gap: 0.5rem; margin-top: 1.5rem; }
.swiper-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--card-border); border: none; cursor: pointer; }
.swiper-dot.active { background: var(--accent); }

/* RESPONSIVE */
@media (max-width: 760px) {
  .nav-links { display: none; }
  .hero { min-height: 72vh; }
  .hero-copy h1 { font-size: 2.2rem; }
  .ueber-in { grid-template-columns: 1fr; gap: 2rem; }
  .stats-in { gap: 1.5rem; }
  .count-up { font-size: 2.4rem; }
  .section { padding: 3rem 0; }
  .footer-in { flex-direction: column; text-align: center; }
}
"""

# ---------------------------------------------------------------------------
# VARIANT: PREMIUM (dark glass/gradient, IT/consulting)
# ---------------------------------------------------------------------------

_HTML_PREMIUM = (
    _HTML_HEAD
    + r"""  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{% static 'css/style.css' %}">
</head>
<body>
  <header class="nav">
    <div class="wrap nav-in">
      <a class="brand" href="#top">{% if c.logo_image %}<img class="brand-logo" src="{{ c.logo_image }}" alt="{{ c.site_name }}">{% else %}{{ c.site_name }}{% endif %}</a>
      <nav class="nav-links">
        <a href="#leistungen">Leistungen</a>
        <a href="#ueber">Über uns</a>
        <a href="#kontakt">Kontakt</a>
      </nav>
      {% if c.telefon %}<a class="btn btn-sm" href="tel:{{ c.telefon }}">Beratung anfragen</a>{% endif %}
    </div>
  </header>

  <main id="top">
    <!-- HERO PREMIUM: dark, glowing gradient, glass card -->
    <section class="hero{% if c.hero_image %} hero-banner{% endif %}" {% if c.hero_image %}style="--hero-img:url('{{ c.hero_image }}')"{% elif c.fotos %}style="--hero-img:url('{{ c.fotos.0 }}')"{% endif %}>
      <div class="hero-overlay"></div>
      <div class="hero-glow hero-glow-1"></div>
      <div class="hero-glow hero-glow-2"></div>
      <div class="wrap hero-in">
        <div class="hero-copy">
          {% if c.stadt %}<span class="eyebrow">{{ c.branche }} &middot; {{ c.stadt }}</span>{% endif %}
          <h1>{{ c.headline }}</h1>
          <p class="lead">{{ c.subline }}</p>
          <div class="hero-cta">
            <a class="btn" href="#kontakt">{{ c.cta_text }}</a>
            {% if c.telefon %}<a class="btn btn-ghost btn-on-dark" href="tel:{{ c.telefon }}">{{ c.telefon }}</a>{% endif %}
          </div>
        </div>
      </div>
    </section>

    <!-- USP BAND -->
    {% if c.usps %}
    <section class="usp-band reveal">
      <div class="wrap usp-in">
        {% for u in c.usps %}<div class="usp-item"><span class="usp-icon">&#10022;</span>{{ u }}</div>{% endfor %}
      </div>
    </section>
    {% endif %}
"""
    + _LEISTUNGEN_BLOCK
    + _UEBER_BLOCK
    + _STATS_BLOCK
    + _GALERIE_BLOCK
    + _TESTIMONIALS_BLOCK
    + _FAQ_BLOCK
    + _KONTAKT_BLOCK
    + _FOOTER_BLOCK
    + r"""  </main>
"""
    + _HTML_FOOT_SCRIPTS
)

_CSS_PREMIUM = r""":root {
  --bg: #0a0c12;
  --bg2: #111420;
  --bg3: #181c2e;
  --accent: #6c63ff;
  --accent2: #4e45e0;
  --accent-glow: rgba(108,99,255,0.35);
  --text: #e8eaf6;
  --text2: #8892b0;
  --card-bg: rgba(255,255,255,0.04);
  --card-border: rgba(255,255,255,0.08);
  --radius: 16px;
  --radius-lg: 24px;
  --shadow: 0 4px 24px rgba(0,0,0,0.5);
  --shadow-accent: 0 8px 40px rgba(108,99,255,0.2);
  --font-head: 'Plus Jakarta Sans', system-ui, sans-serif;
  --font-body: 'Plus Jakarta Sans', system-ui, sans-serif;
  --nav-h: 72px;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
  .reveal { opacity: 1 !important; transform: none !important; }
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body { background: var(--bg); color: var(--text); font-family: var(--font-body); font-size: 1rem; line-height: 1.65; }
img { max-width: 100%; display: block; }
a { color: var(--accent); text-decoration: none; }

.wrap { max-width: 1180px; margin: 0 auto; padding: 0 1.25rem; }

/* NAV */
.nav { position: sticky; top: 0; z-index: 100; background: rgba(10,12,18,0.85); backdrop-filter: blur(20px); border-bottom: 1px solid var(--card-border); transition: box-shadow 0.3s; }
.nav-scrolled { box-shadow: 0 2px 32px rgba(0,0,0,0.8); }
.nav-in { display: flex; align-items: center; gap: 2rem; height: var(--nav-h); }
.brand { font-size: 1.25rem; font-weight: 800; background: linear-gradient(135deg, #fff 0%, var(--accent) 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
.brand-logo { height: 36px; width: auto; }
.nav-links { display: flex; gap: 2rem; margin-left: auto; }
.nav-links a { color: var(--text2); font-size: 0.9rem; font-weight: 500; transition: color 0.2s; }
.nav-links a:hover { color: var(--text); }

/* BUTTONS */
.btn { display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.8rem 1.75rem; background: linear-gradient(135deg, var(--accent) 0%, var(--accent2) 100%); color: #fff; font-size: 0.92rem; font-weight: 600; border-radius: var(--radius); border: 1px solid var(--accent); transition: box-shadow 0.25s, transform 0.15s; cursor: pointer; }
.btn:hover { box-shadow: var(--shadow-accent); transform: translateY(-2px); }
.btn-sm { padding: 0.55rem 1.3rem; font-size: 0.85rem; }
.btn-ghost { background: transparent; color: var(--text); border: 1px solid var(--card-border); }
.btn-ghost:hover { background: var(--card-bg); box-shadow: none; }
.btn-on-dark { color: var(--text); border-color: var(--card-border); }

/* HERO */
.hero { position: relative; min-height: 92vh; display: flex; align-items: center; background: var(--bg); overflow: hidden; }
.hero-banner { background-image: var(--hero-img); background-size: cover; background-position: center; }
.hero-overlay { position: absolute; inset: 0; background: linear-gradient(135deg, rgba(10,12,18,0.95) 0%, rgba(10,12,18,0.7) 100%); z-index: 1; }
.hero-glow { position: absolute; border-radius: 50%; filter: blur(80px); z-index: 0; pointer-events: none; }
.hero-glow-1 { width: 480px; height: 480px; background: radial-gradient(circle, rgba(108,99,255,0.25), transparent 70%); top: -80px; right: 10%; }
.hero-glow-2 { width: 320px; height: 320px; background: radial-gradient(circle, rgba(78,69,224,0.18), transparent 70%); bottom: 5%; left: 5%; }
.hero-in { position: relative; z-index: 2; padding: 6rem 0 8rem; }
.hero-copy { max-width: 720px; }
.eyebrow { display: inline-flex; align-items: center; gap: 0.5rem; background: rgba(108,99,255,0.15); border: 1px solid rgba(108,99,255,0.3); color: var(--accent); font-size: 0.78rem; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; padding: 0.35rem 1rem; border-radius: 100px; margin-bottom: 1.5rem; }
.hero-copy h1 { font-size: clamp(2.4rem, 5.5vw, 5rem); font-weight: 800; line-height: 1.1; letter-spacing: -0.03em; background: linear-gradient(135deg, #fff 40%, var(--accent) 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; margin-bottom: 1.5rem; }
.lead { font-size: 1.15rem; color: var(--text2); max-width: 560px; margin-bottom: 2.5rem; line-height: 1.75; }
.hero-cta { display: flex; flex-wrap: wrap; gap: 1rem; }

/* USP BAND */
.usp-band { background: var(--bg2); border-top: 1px solid var(--card-border); border-bottom: 1px solid var(--card-border); padding: 1.25rem 0; }
.usp-in { display: flex; flex-wrap: wrap; gap: 2.5rem; justify-content: center; }
.usp-item { display: flex; align-items: center; gap: 0.6rem; font-size: 0.9rem; font-weight: 600; color: var(--text2); }
.usp-icon { color: var(--accent); font-size: 0.8rem; }

/* SECTIONS */
.section { padding: 5.5rem 0; }
.section-t { font-size: clamp(1.7rem, 3.2vw, 2.4rem); font-weight: 800; letter-spacing: -0.025em; margin-bottom: 2.5rem; background: linear-gradient(135deg, var(--text) 60%, var(--accent) 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
.section-t::after { content: ''; display: block; width: 44px; height: 2px; background: linear-gradient(90deg, var(--accent), transparent); margin-top: 0.8rem; border-radius: 1px; }

/* LEISTUNGEN */
.leistungen { background: var(--bg2); }
.leistungen-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 1.25rem; }
.leistung-card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: var(--radius); padding: 1.75rem; backdrop-filter: blur(8px); transition: border-color 0.25s, box-shadow 0.25s; }
.leistung-card:hover { border-color: rgba(108,99,255,0.5); box-shadow: var(--shadow-accent); }
.leistung-icon { font-size: 1.75rem; margin-bottom: 0.75rem; }
.leistung-card h3 { font-size: 1.05rem; font-weight: 700; margin-bottom: 0.5rem; color: var(--text); }
.leistung-card p { color: var(--text2); font-size: 0.93rem; }

/* ÜBER UNS */
.ueber { background: var(--bg); }
.ueber-in { display: grid; grid-template-columns: 1fr 1fr; gap: 4rem; align-items: center; }
.ueber-text p { color: var(--text2); line-height: 1.8; }
.zertifikate { list-style: none; margin-top: 1.25rem; display: flex; flex-direction: column; gap: 0.45rem; }
.zertifikate li { color: var(--text2); font-size: 0.92rem; display: flex; gap: 0.5rem; align-items: flex-start; }
.ueber-img img { border-radius: var(--radius-lg); border: 1px solid var(--card-border); box-shadow: var(--shadow); }

/* STATS */
.stats { background: var(--bg2); border-top: 1px solid var(--card-border); border-bottom: 1px solid var(--card-border); padding: 4rem 0; }
.stats-in { display: flex; justify-content: space-around; flex-wrap: wrap; gap: 2rem; text-align: center; }
.stat-item { display: flex; flex-direction: column; align-items: center; gap: 0.2rem; }
.count-up { font-size: clamp(2.8rem, 5vw, 4.5rem); font-weight: 800; background: linear-gradient(135deg, #fff 40%, var(--accent) 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; line-height: 1; letter-spacing: -0.03em; }
.stat-plus { font-size: 1.8rem; font-weight: 800; color: var(--accent); }
.stat-label { font-size: 0.8rem; color: var(--text2); text-transform: uppercase; letter-spacing: 0.08em; margin-top: 0.25rem; }

/* GALERIE */
.galerie { background: var(--bg); }
.galerie-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 1rem; }
.galerie-item { border-radius: var(--radius); overflow: hidden; aspect-ratio: 4/3; border: 1px solid var(--card-border); }
.galerie-item img { width: 100%; height: 100%; object-fit: cover; transition: transform 0.4s; }
.galerie-item:hover img { transform: scale(1.06); }

/* TESTIMONIALS */
.testimonials { background: var(--bg2); }
.testi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.25rem; }
.testi-card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: var(--radius); padding: 1.75rem; backdrop-filter: blur(8px); transition: border-color 0.25s, box-shadow 0.25s; }
.testi-card:hover { border-color: rgba(108,99,255,0.4); box-shadow: var(--shadow-accent); }
.testi-stars { color: #f59e0b; font-size: 1.05rem; letter-spacing: 0.1em; margin-bottom: 0.75rem; }
.testi-text { color: var(--text2); font-size: 0.95rem; line-height: 1.75; margin-bottom: 1rem; font-style: italic; }
.testi-card cite { font-size: 0.85rem; color: var(--text); font-style: normal; font-weight: 600; }

/* FAQ */
.faq { background: var(--bg); }
.faq-wrap { max-width: 760px; }
.faq-list { display: flex; flex-direction: column; gap: 0.75rem; }
.faq-item { border: 1px solid var(--card-border); border-radius: var(--radius); overflow: hidden; background: var(--card-bg); backdrop-filter: blur(6px); }
.faq-q { padding: 1.1rem 1.25rem; cursor: pointer; font-weight: 600; font-size: 0.97rem; list-style: none; display: flex; justify-content: space-between; align-items: center; color: var(--text); background: transparent; }
.faq-q::after { content: '+'; font-size: 1.3rem; color: var(--accent); transition: transform 0.2s; }
.faq-item[open] .faq-q::after { transform: rotate(45deg); }
.faq-a { padding: 1rem 1.25rem; border-top: 1px solid var(--card-border); color: var(--text2); font-size: 0.93rem; line-height: 1.75; }

/* KONTAKT */
.kontakt { background: var(--bg2); }
.kontakt-in { max-width: 620px; }
.kontakt h2 { font-size: clamp(1.7rem, 3vw, 2.5rem); font-weight: 800; letter-spacing: -0.025em; margin-bottom: 1rem; background: linear-gradient(135deg, var(--text) 50%, var(--accent) 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
.kontakt p { color: var(--text2); margin-bottom: 1.5rem; }
.kontakt-actions { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.5rem; }
address { color: var(--text2); font-style: normal; font-size: 0.9rem; }
.oeffnungszeiten { color: var(--text2); font-size: 0.9rem; margin-top: 0.5rem; }

/* FOOTER */
.footer { background: var(--bg); border-top: 1px solid var(--card-border); padding: 2rem 0; }
.footer-in { display: flex; align-items: center; flex-wrap: wrap; gap: 1rem; justify-content: space-between; }
.footer-brand { font-weight: 800; font-size: 1rem; background: linear-gradient(135deg, #fff 0%, var(--accent) 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
.footer-nav { display: flex; gap: 1.5rem; }
.footer-nav a { color: var(--text2); font-size: 0.85rem; transition: color 0.2s; }
.footer-nav a:hover { color: var(--text); }
.footer-copy { color: rgba(136,146,176,0.45); font-size: 0.8rem; }

/* REVEAL */
.reveal { opacity: 0; transform: translateY(28px); transition: opacity 0.65s ease, transform 0.65s ease; }
.reveal.revealed { opacity: 1; transform: none; }

/* SWIPER */
.swiper-dots { display: flex; justify-content: center; gap: 0.5rem; margin-top: 1.5rem; }
.swiper-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--card-border); border: none; cursor: pointer; }
.swiper-dot.active { background: var(--accent); }

/* RESPONSIVE */
@media (max-width: 760px) {
  .nav-links { display: none; }
  .hero { min-height: 75vh; }
  .hero-copy h1 { font-size: 2.2rem; }
  .ueber-in { grid-template-columns: 1fr; gap: 2rem; }
  .stats-in { gap: 1.5rem; }
  .count-up { font-size: 2.5rem; }
  .section { padding: 3rem 0; }
  .footer-in { flex-direction: column; text-align: center; }
}
"""

# ---------------------------------------------------------------------------
# Variant dispatch maps
# ---------------------------------------------------------------------------

_VARIANT_HTML = {
    "bold": _HTML_BOLD,
    "modern": _HTML_MODERN,
    "warm": _HTML_WARM,
    "craft": _HTML_CRAFT,
    "premium": _HTML_PREMIUM,
}

_VARIANT_CSS = {
    "bold": _CSS_BOLD,
    "modern": _CSS_MODERN,
    "warm": _CSS_WARM,
    "craft": _CSS_CRAFT,
    "premium": _CSS_PREMIUM,
}

# ---------------------------------------------------------------------------
# Install variant into a generated site folder
# ---------------------------------------------------------------------------


def install_variant(folder: Path, variant: str) -> None:
    """
    Writes templates/index.html and static/css/style.css into the given folder.
    Also copies counter_up.js and swiper_lite.js into static/js/.

    folder: root of the generated Django site (where manage.py lives)
    variant: one of bold / modern / warm / craft / premium
    """
    if variant not in _VARIANT_HTML:
        variant = "premium"

    templates_dir = folder / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    (templates_dir / "index.html").write_text(
        _VARIANT_HTML[variant], encoding="utf-8"
    )

    css_dir = folder / "static" / "css"
    css_dir.mkdir(parents=True, exist_ok=True)
    (css_dir / "style.css").write_text(_VARIANT_CSS[variant], encoding="utf-8")

    js_dir = folder / "static" / "js"
    js_dir.mkdir(parents=True, exist_ok=True)
    (js_dir / "counter_up.js").write_text(_COUNTER_UP_JS, encoding="utf-8")
    (js_dir / "swiper_lite.js").write_text(_SWIPER_LITE_JS, encoding="utf-8")
