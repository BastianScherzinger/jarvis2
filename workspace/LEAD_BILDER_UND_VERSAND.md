# Lead-Foto-Bewertung, Token-Punkte 11–14/18 & Railway-Versand-Seite

Stand 2026-06-26. Umsetzung der Anforderung „mach 11 12 13 14 und 18 — aber Leads richtig
recherchieren, Lead-Bilder lokal bewerten und sinnvoll einbauen; auf der Railway-Lead-Seite
die versandbereiten Webseiten mit Buttons mobil zeigen".

## A · Token-Sparplan-Punkte 11–14 + 18 (Headless-Makeover)

`claude_coder.py`
- **18 — nur nötige Tools:** der headless `claude -p`-Lauf bekommt `--allowedTools
  "Read Edit Write MultiEdit Glob Grep LS"` (kein WebSearch/WebFetch/Bash → keine vergeudeten
  Tool-Runden). Per `JARVIS_CLAUDE_ALLOWED_TOOLS` justierbar, `-` hebt die Beschränkung auf.
- **11–14 — Token-Disziplin im System-Prompt** (`_SYS_APPEND`): surgische Edits über eindeutige
  Anker/Selektoren statt Ganzdatei-Lesen (11), mehrere Änderungen je Datei in EINEM MultiEdit (12),
  Datei-Reads klein halten/nur Ausschnitt (13), KEINE Probe-/Test-Renders und kein endloses
  Polishing — fertig, sobald es valide rendert (14).

`overnight_makeover.py` — der One-Pass-Prompt nennt dieselben Regeln explizit + weist an, die
bereits qualitätssortierten Lead-Fotos sinnvoll einzubauen (kein Hero-Duplikat).

## B · Leads richtig recherchiert — bessere Fotos

`scrapers/maps.py` — die auf Google Maps gefundenen Foto-URLs werden jetzt auf **hohe Auflösung
hochgerechnet** (Größen-Suffix `=w###-h###…` → `=w1280-h960`) und über die Basis-URL
**dedupliziert** (kein Bild mehrfach in verschiedenen Größen). Ergebnis: scharfe, brauchbare
Fotos für die Kundenseite statt winziger Thumbnails. Der Hero-Kandidat wird ebenfalls hochauflösend.

## C · Lead-Bilder LOKAL bewerten + sinnvoll einbauen

Neues Modul `lead_images.py` (0 Claude-Tokens, läuft komplett lokal):
- **Heuristik (Pillow + NumPy):** Auflösung/Megapixel, Seitenverhältnis, Schärfe (Laplace-Varianz),
  Farbigkeit (Hasler-Süsstrunk), Helligkeit/Kontrast → erkennt **Logos/Grafiken/Karten, zu kleine
  Thumbnails, unscharfe und über-/unterbelichtete** Bilder und verwirft sie. Score 0–100.
- **Optional Ollama-Vision** (`JARVIS_VISION_MODEL`, z.B. `llava`/`qwen2.5vl`): verfeinert
  Relevanz/Qualität je Bild + liefert eine kurze Bildunterschrift. Best-effort, GPU-bewusst.
- **Rollen-Zuordnung:** bestes echtes **Querformat → Hero** (spart ein Higgsfield-Bild,
  `hero_source='lead_foto'`), bestes **Hochformat → Über-uns**, Rest → **Galerie** (nach Qualität
  sortiert). Verworfene Bilder erscheinen nicht.

Einbau:
- `website_builder._run`: nach dem Foto-Download bewertet+ordnet `evaluate_and_arrange`; Hero
  wird (falls hero-tauglich) aus dem besten Foto gesetzt, Über-uns + Galerie ebenso.
- `overnight_makeover._grade_fotos_once`: bewertet die Fotos auch bei **bestehenden** Seiten beim
  Verbessern neu (idempotent über `content['fotos_graded']`), lässt ein vorhandenes Hero in Ruhe.

Schalter: `JARVIS_LEAD_PHOTO_HERO` (Default 1), `JARVIS_VISION_MODEL`, sowie
`JARVIS_IMG_MIN_SIDE/_MIN_SHARP/_MIN_COLOR/_HERO_MIN_W`.

## D · Railway-Lead-Seite — Versand-Bereich (separates Repo `leadsite.git`)

`webseiten buisnes/jarvis-lead-site` (Django, dunkles RailWatch-Theme):
- Neue Seite **`/versand/`** (`versand_view` + `api_versand_json`): liest **versandbereite**
  Webseiten aus Supabase `jarvis_websites` (live=1, mit live_url), verknüpft Kontakt
  (E-Mail/Telefon) aus `jarvis_leads` über den site_key/lead_key.
- Mobil-first, designt (design-pro): Karten je Seite mit **kleinen Buttons** — **Ansehen**
  (Live-Seite öffnen), **WhatsApp** (`wa.me` + vorausgefüllter Text inkl. Link) und **E-Mail**
  (`mailto:` mit Betreff + Text + Link). Direkt vom Handy abschickbar. Leerzustand + Fehler-Hinweis,
  Touch-Ziele ≥ 46 px, `prefers-reduced-motion`, Auto-Refresh der Zähler.
- Verlinkt aus der Leads-Topbar + Sidebar-Nav. Doku in `SETUP.md` (braucht `SUPABASE_ANON_KEY`
  mit Lesezugriff auf `jarvis_websites`).

## Tests / Verifikation
- `python -m pytest tests/test_core.py -q` → **93 passed** (inkl. 2 neue lead_images-Tests).
- Lead-Site: `python manage.py check` → 0 issues; Versand-Template rendert (Karten + Leerzustand).
- Alle geänderten `.py` py_compile-sauber.
