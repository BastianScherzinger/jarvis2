# JARVIS — Medien-System (Bilder & Videos) · Stand 22.06.2026

Dokumentiert die Bild-/Video-Generierung: Architektur, was in diesem Durchgang
gebaut wurde, und Verbesserungsmöglichkeiten.

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
