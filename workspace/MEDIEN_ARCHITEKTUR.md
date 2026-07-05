# JARVIS — Medien-System (Bilder & Videos) · Stand 23.06.2026

Dokumentiert die Bild-/Video-Generierung: Architektur, was in diesem Durchgang
gebaut wurde, und Verbesserungsmöglichkeiten.

## Update 23.06. — Video-Backend mit Auto-Cloud-Fallback (kein GPU-Fehler mehr)
`media_engine.generate_video` wählt das Backend über **`JARVIS_VIDEO_BACKEND`**:
- `auto` (Standard): **keine GPU → automatisch Higgsfield-Cloud**. Der frühere Fehler
  „Lokale Videogenerierung (Wan 2.1) benötigt eine GPU … Nutze 'Higgsfield Cloud'"
  kommt **nicht mehr** — das Video entsteht direkt über die Cloud.
- `higgsfield`: immer Cloud (auch mit GPU).
- `local`: erzwingt lokales Wan (nur sinnvoll mit GPU).
- Fehlt der Cloud-Key, kommt eine **lösbare** Meldung: „HIGGSFIELD_API_KEY=ID:SECRET in
  die .env eintragen". Cloud-Modell via `JARVIS_HIGGSFIELD_VIDEO_MODEL` (Default `dop-lite`).
- `.env`: `HIGGSFIELD_API_KEY` als **kombiniertes `ID:SECRET`** (von Higgsfield-Auth
  verstanden), plus `JARVIS_VIDEO_BACKEND=auto`. Damit laufen Videos auf dem CPU-PC.

## Was in diesem Durchgang gebaut wurde
1. **Higgsfield-Bild-Backend** — neuer Queue-Typ `higgsfield_image`; `generate/image`
   nimmt jetzt `backend: local|higgsfield`. Asset-Set (`generate/set`) ebenso (`backend`).
2. **Bilder-Tab komplett:** freier Einzelbild-Prompt mit **Lokal/Higgsfield-Wähler**
   (oben), darunter das 5er-Werbe-Set mit eigenem **Modus-Wähler**. Galerie unverändert.
3. **Video-Tab:** Backend-Wähler (Lokal Wan / Higgsfield) war da; ergänzt um eine
   **Werbevideo-Vorlage** (Lead-Dropdown + Betrieb/Branche → fertiger Clip).
4. **Werbevideos** via `ad_prompts.build_video_prompt()` + Route
   `/api/media/generate/ad-video` (Brief → kinoreifer Prompt → lokal oder Higgsfield).
5. **Leads & Webseiten:** Bilder-Tab hat Lead-Picker (5 Assets); Video-Tab hat Lead-Picker
   (Werbevideo). Im **Webseiten-Tab** je Karte zwei Buttons: **🖼 Werbebilder** (5er-Set)
   und **🎬 Werbevideo** (lokal oder Higgsfield).

## Architektur (Datenfluss)
```
Frontend (index.html + app.js)
  Bilder-Tab:  generateImage()      -> POST /api/media/generate/image {backend}
               generateImageSet()   -> POST /api/media/generate/set   {backend, lead_id}
  Video-Tab:   generateVideo()      -> POST /api/media/generate/video {backend}
               generateAdVideo()    -> POST /api/media/generate/ad-video {brief, backend}
  Webseiten:   wsAdImages/wsAdVideo -> dieselben /set bzw. /ad-video Routen
        |
        v
app.py  (Routen validieren, ad_prompts baut Prompts)
        |  media_queue.submit(kind, params)
        v
media_queue.py  (EIN Worker-Thread, seriell — GPU/VRAM-Constraint)
        |  kind: image | higgsfield_image | asset_set | image_set | video | higgsfield | mockup
        v
media_engine.py
   lokal:      generate_image (sd-turbo/sdxl/flux) · generate_video (Wan 2.1)
   higgsfield: generate_image_higgsfield (Soul) · generate_video_higgsfield (Dop)
        |
        v
workspace/media/{images,videos}/   -> /api/media/gallery -> Galerie im Frontend
```

### Modell-Wahl
- **Lokal Bild:** hardware-adaptiv — GPU≥12GB+HF_TOKEN→FLUX, GPU≥6GB/MPS→SDXL, sonst SD-Turbo.
- **Lokal Video:** Wan 2.1 T2V 1.3B (480p, langsam auf CPU).
- **Higgsfield:** Cloud, account-gebunden über `HIGGSFIELD_API_KEY` (= der gewünschte
  enigmabible1-Account). Bild = Soul (1080p), Video = Dop Lite/Preview/Turbo (3/6/9 Credits).

## WICHTIG — Higgsfield-Account aktivieren (ID + Secret!)
Higgsfield (Platform-SDK) authentifiziert mit **ID UND Secret** als `Key ID:SECRET`.
Zwei gleichwertige Wege in der `.env` (nicht committen — gitignored):
- **Kombiniert:** `HIGGSFIELD_API_KEY=DEINE_ID:DEIN_SECRET`  (mit Doppelpunkt!)
- **Getrennt:** `HIGGSFIELD_API_KEY=DEINE_ID` + `HIGGSFIELD_SECRET=DEIN_SECRET`

> Steht nur EIN 64-Zeichen-Token ohne `:` drin (und kein HIGGSFIELD_SECRET), nutzt der
> Code `Bearer <token>` — das schlägt beim Platform-API i.d.R. fehl (401/404). Daher
> ID **und** Secret eintragen.

Key erstellen: https://cloud.higgsfield.ai/api-keys mit **enigmabible1@gmail.com**.
Optional: `JARVIS_HF_IMAGE_SIZE`, `JARVIS_HF_IMAGE_QUALITY` (Defaults 1536x864 / 1080p).
Ohne gültige Auth fällt jede Higgsfield-Aktion mit klarer Meldung zurück; lokal läuft weiter.

## Lokales Video (Wan 2.1) — Fix 22.06.
- Repo korrigiert: `Wan-AI/Wan2.1-T2V-1.3B` → **`Wan-AI/Wan2.1-T2V-1.3B-Diffusers`**
  (Original hatte kein `model_index.json` → 404). VAE wird jetzt in float32 geladen
  (sonst schwarze/NaN-Frames), `flow_shift=3.0` für 480p.
- **CPU-Guard:** auf einer reinen CPU bricht die lokale Videogenerierung sofort mit klarer
  Meldung ab (Wan braucht GPU) — statt stundenlangem Hänger. Für Videos auf CPU-PCs →
  Higgsfield Cloud nutzen.

## Verbesserungsmöglichkeiten
- **Higgsfield-Endpunkte ungetestet** (kein Key gesetzt): `text2image/soul` und
  `v1/generations` nach Doku gebaut — beim ersten echten Lauf Antwortstruktur prüfen
  (`_hf_extract_image_url` / Video-URL-Pfade) und ggf. anpassen.
- **Bild→Video (i2v):** `generate_video_higgsfield` kann `image_url` — könnte den
  Webseiten-Hero als Startbild nutzen (echter Marken-Clip statt generisch).
- **Werbevideos an Leads/Webseiten speichern** (wie Mockups via `set_mockup`) — aktuell
  landen sie nur in der globalen Galerie, nicht an der Entität.
- **Galerie-Filter** nach Lead/Set/Quelle; Löschen einzelner Medien im Frontend.
- **Kosten-Anzeige** für Higgsfield (Credits via `higgsfield_balance()`) vor dem Start.
- **Parallelität:** Queue ist bewusst seriell (VRAM). Cloud-Jobs (Higgsfield) könnten
  parallel laufen, da sie keine lokale GPU brauchen — eigener Cloud-Worker denkbar.

## Tests
`tests/test_core.py`: +3 (build_video_prompt, image-higgsfield-Backend-Route,
ad-video-Route lokal/higgsfield/400) → **52 grün**. `smoke_audit.py` 51/51 grün.

## Update 05.07. — Werbevideo-Tab: Website-URL → echtes TikTok-Ad (9:16, 10s)
Neuer, eigenständiger Reiter **Werbevideo** (`data-page="ad-video"`) — anders als die
bisherigen Werbevideos (KI-generiert aus Text-Prompt via Wan/Higgsfield) nimmt dieser
Weg die **echte Website** des Kunden per Playwright auf und schneidet daraus einen
fertigen 9:16-Clip. Kein GPU/Cloud-Credit nötig, läuft komplett lokal & kostenlos.

### Neue Datei: `website_ad_video.py`
```
build_ad_video(url, job_id, hook_text="", cta_text="", progress_cb=None) -> dict
  1. _capture()          Playwright (headless Chromium): Seite laden (3 Versuche),
                          Cookie-Banner schließen, Lazy-Load per Scroll vortriggern,
                          Hero-Screenshot + Vollseiten-Screenshot (1080px Basisbreite,
                          device_scale_factor=2 -> exakt 1080px Ausgabebreite).
  2. _pick_detail_crops() PIL/numpy: 1080x1920-Fenster über die Gesamtseite scannen,
                          die 3 Fenster mit höchster Helligkeits-Standardabweichung
                          wählen (Kontrast-Heuristik statt GPU-Modell für "beste Szene").
  3. _compose_text_card() PIL: Hook-/CTA-Text als abgedunkelter Textblock über eine
                          Hero-Kopie -- kein ffmpeg-drawtext (keine Font-Abhängigkeit).
  4. _clip_zoom/_clip_scroll  ffmpeg (imageio_ffmpeg-Binary): Hook-Zoom (1,5s) ->
                          Scroll-Pan über Vollseite (5s) -> 3x Detail-Zoom (2,5s) ->
                          CTA-Karte (1s) -> concat-Demuxer, Re-Encode auf 30fps.
  5. _make_ambient_audio() zwei leise Sinustöne (196/294 Hz) mit Fade -- bewusster
                          Offline-Fallback für den in der Vorgabe verlangten
                          "sanften Ambient-Ton", wenn kein lizenzfreier Beat verfügbar ist.
  6. _mux_final()          Video+Ton muxen, -t 10 hart getrimmt, CRF/Maxrate für ≤12MB.
  7. probe()/qa_checks()   ffmpeg -i-Stderr geparst (kein ffprobe gebündelt) ->
                          Dauer/Auflösung/Codec/Ton/Größe; bei zu groß automatischer
                          Re-Encode mit höherem CRF (bis 2 Versuche).
  8. build_caption()       Deutscher Caption-Vorschlag + 8 Hashtags fürs Posten.
```
Ausgabe: `workspace/media/ads/ad_<domain>_<timestamp>.mp4` (gitignored).

### Kritischer ffmpeg-Bug (gefunden + gefixt)
`-t <dauer>` wurde ursprünglich als **Input**-Option (vor `-i`) übergeben. Bei
`-loop 1` liefert der image2-Demuxer standardmäßig 25fps -> `-t 1.5` vor `-i` erzeugte
~37 identische Input-Frames, die `zoompan` (Parameter `d=45`) JEDES EINZELN nochmal um
45 Frames verlängerte -> ein 1,5s-Clip wurde zu ~55s und brauchte je nach Clip mehrere
Minuten CPU-Zeit (im Test: 962 CPU-Sekunden, nie fertig). Fix: `-t` als **Output**-Option
(nach `-vf`/`-r`) gesetzt -> Clip fertig in <1s, exakte Ziel-Länge. Lehre: bei
`-loop 1`-Standbild-Inputs für Zoom/Pan-Filter IMMER `-t`/`-r` als Output-Optionen setzen,
nie vor `-i`.

### Architektur-Einordnung
`website_ad_video` läuft NICHT über `media_engine.py` (kein Diffusers/Torch) -- eigener
Job-Kind `website_ad_video` in `media_queue.py`, in die **Cloud-Queue** (`_CLOUD_KINDS`)
eingereiht, weil Playwright+ffmpeg keine lokale GPU/VRAM brauchen und so nicht hinter
den seriellen Bild/Video-Diffusers-Jobs warten müssen.
```
Frontend (ad_video.js)  -> POST /api/media/generate/website-ad-video {url, hook_text, cta_text}
                         -> GET  /api/media/job/<id>           (Poll: progress, stage, result_url, qa, checks, caption, hashtags)
                         -> GET  /api/media/ads                (Galerie bisheriger Werbevideos)
app.py                  -> media_queue.submit("website_ad_video", params)
media_queue.py           -> website_ad_video.build_ad_video(..., progress_cb=_set)
website_ad_video.py       -> Playwright + ffmpeg (imageio_ffmpeg), siehe oben
```

### Tests
`tests/test_core.py`: +5 (normalize_url, qa_checks gut/schlecht, build_caption,
website-ad-video-Route inkl. 400 ohne url).

### Verbesserungsmöglichkeiten
- Ambient-Ton ist aktuell rein synthetisch (zwei Sinustöne) -- ein echter, lizenzfreier
  Beat-Loop würde "moderner" wirken, wurde aber bewusst weggelassen (Lizenzfragen).
- Detail-Crop-Heuristik ist eine einfache Kontrast-Metrik, kein echtes Bildverständnis --
  reicht für "nicht die leere Sektion erwischen", könnte aber z.B. um Gesichtserkennung
  oder Logo-/Button-Erkennung erweitert werden.
- Hook-/CTA-Text ist aktuell branchenunabhängig; ließe sich aus Meta-Title/Description
  der Seite (bereits in `meta["title"]` vorhanden) automatisch zuspitzen.
