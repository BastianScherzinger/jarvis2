"""
JARVIS Werbevideo-Generator — baut aus einer beliebigen Website-URL automatisch ein
9:16 TikTok-Werbevideo (10 Sekunden), das Webdesign-Dienstleistungen bewirbt.

Pipeline: Playwright nimmt die echte Website auf (Hero-Screenshot, Volltext-Scroll,
automatisch ausgewählte Detail-Ausschnitte) -> ffmpeg (imageio-ffmpeg-Binary, kein
System-ffmpeg nötig) schneidet daraus Hook/Scroll/Detail-Cuts/CTA mit Zoom- und
Scroll-Bewegung, Text-Overlays und einem sanften Ambient-Ton zusammen -> QS-Check
(Dauer/Auflösung/Codec/Ton/Größe) mit Auto-Korrektur, bevor die Datei abgegeben wird.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
import urllib.parse
from pathlib import Path

_BASE = Path(__file__).parent
OUT_DIR = _BASE / "workspace" / "media" / "ads"
_TMP_ROOT = _BASE / "workspace" / "media" / "_ad_tmp"
OUT_DIR.mkdir(parents=True, exist_ok=True)
_TMP_ROOT.mkdir(parents=True, exist_ok=True)

# Ziel-Format: TikTok 9:16, 30fps, 10s.
W, H, FPS = 1080, 1920, 30
TOTAL_S = 10.0

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_COOKIE_TEXTS = ["Alle akzeptieren", "Akzeptieren", "Zustimmen", "Ich stimme zu",
                 "Accept all", "Accept", "I agree", "Got it", "OK", "Einverstanden",
                 "Verstanden", "Alles klar"]
_COOKIE_HIDE_CSS = (
    "[id*=cookie i],[class*=cookie i],[id*=consent i],[class*=consent i],"
    "[class*=cmp i],[id*=cmp i],.fc-consent-root,#usercentrics-root"
    "{display:none !important;}"
)


def _log(level: str, where: str, msg: str) -> None:
    try:
        import logger as _lg
        getattr(_lg, level, _lg.info)(where, msg)
    except Exception:
        pass


def _ffmpeg_exe() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise ValueError("Keine URL angegeben.")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    if not parsed.netloc:
        raise ValueError(f"Ungültige URL: '{url}'")
    return url


def _run_ffmpeg(args: list[str]) -> None:
    exe = _ffmpeg_exe()
    proc = subprocess.run([exe, "-y", "-hide_banner", "-loglevel", "error", *args],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg-Fehler: {proc.stderr.strip()[-600:]}")


# ── 1. Website aufnehmen (Playwright) ────────────────────────────────────────

def _dismiss_cookies(page) -> None:
    for txt in _COOKIE_TEXTS:
        try:
            loc = page.get_by_text(txt, exact=False).first
            if loc.is_visible(timeout=600):
                loc.click(timeout=1500)
                page.wait_for_timeout(400)
                return
        except Exception:
            continue
    try:
        page.add_style_tag(content=_COOKIE_HIDE_CSS)
    except Exception:
        pass


def _capture(url: str, workdir: Path) -> dict:
    """Lädt die Seite (max. 3 Versuche), schließt Cookie-Banner, lädt Lazy-Content
    per Scroll vor und speichert hero.png (Startbild) + full.png (Gesamtseite)."""
    from playwright.sync_api import sync_playwright

    hero_path = workdir / "hero.png"
    full_path = workdir / "full.png"
    meta = {"title": ""}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            ctx = browser.new_context(
                viewport={"width": W // 2, "height": H // 2},
                device_scale_factor=2, locale="de-DE", user_agent=_UA,
            )
            page = ctx.new_page()

            last_err = None
            loaded = False
            for _attempt in range(3):
                try:
                    page.goto(url, timeout=30000, wait_until="networkidle")
                    page.wait_for_timeout(4000)
                    try:
                        page.evaluate("document.fonts ? document.fonts.ready : Promise.resolve()")
                    except Exception:
                        pass
                    _dismiss_cookies(page)
                    # Lazy-Load vorladen: einmal komplett runter- und wieder hochscrollen.
                    try:
                        page.evaluate(
                            "async () => { const wait = ms => new Promise(r => setTimeout(r, ms)); "
                            "const total = document.body.scrollHeight; "
                            "for (let y = 0; y < total; y += 500) { window.scrollTo(0, y); await wait(150); } "
                            "window.scrollTo(0, 0); await wait(600); }"
                        )
                    except Exception:
                        pass
                    page.wait_for_timeout(600)
                    body_len = page.evaluate(
                        "document.body ? document.body.innerText.length : 0")
                    if body_len < 40:
                        raise RuntimeError("Seite wirkt leer (kein sichtbarer Text).")
                    meta["title"] = page.title() or ""
                    loaded = True
                    break
                except Exception as e:
                    last_err = e
                    page.wait_for_timeout(1200)
            if not loaded:
                raise RuntimeError(f"Website konnte nicht geladen werden: {last_err}")

            page.screenshot(path=str(hero_path))
            try:
                page.screenshot(path=str(full_path), full_page=True)
            except Exception:
                # Sehr lange Seiten überschreiten manchmal das Chromium-Limit für
                # Screenshots -> auf einen großzügigen, aber sicheren Ausschnitt begrenzen.
                page_h = page.evaluate("document.body.scrollHeight") or (H // 2)
                capped = min(int(page_h), 4000)
                page.screenshot(path=str(full_path),
                                clip={"x": 0, "y": 0, "width": W // 2, "height": capped})
        finally:
            browser.close()

    return meta


# ── 2. Beste Ausschnitte wählen (Bildkontrast-Heuristik) ─────────────────────

def _pick_detail_crops(full_path: Path, n: int = 3) -> list[int]:
    """Scannt die Gesamtseite in 1080x1920-Fenstern und wählt die N Fenster mit dem
    stärksten visuellen Kontrast (Standardabweichung der Helligkeit) — ein einfacher,
    schneller Stand-in für 'wähle die visuell attraktivsten Segmente' ganz ohne GPU."""
    from PIL import Image
    import numpy as np

    img = Image.open(full_path).convert("L")
    w, h = img.size
    if h <= H:
        return []
    arr = np.asarray(img, dtype=np.float32)
    step = max(60, H // 5)
    candidates = []
    y = H  # Hero-Bereich überspringen -> andere Sektionen für die Details
    while y + H <= h:
        band = arr[y:y + H]
        candidates.append((float(band.std()), y))
        y += step
    if not candidates:
        return []
    candidates.sort(reverse=True)
    picks: list[int] = []
    for _score, y in candidates:
        if all(abs(y - u) > H * 0.6 for u in picks):
            picks.append(y)
        if len(picks) >= n:
            break
    picks.sort()
    return picks


# ── 3. Text-Karten (PIL statt ffmpeg-drawtext -> keine Font-Abhängigkeit) ────

def _find_font(size: int):
    from PIL import ImageFont
    win_fonts = Path("C:/Windows/Fonts")
    for name in ("seguisb.ttf", "segoeuib.ttf", "arialbd.ttf", "Arial Bold.ttf"):
        p = win_fonts / name
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except Exception:
        return ImageFont.load_default()


def _wrap_text(draw, text: str, font, max_w: int) -> list[str]:
    lines: list[str] = []
    for raw_line in text.split("\n"):
        words = raw_line.split(" ")
        cur = ""
        for word in words:
            trial = f"{cur} {word}".strip()
            if draw.textlength(trial, font=font) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def _compose_text_card(base_path: Path, text: str, out_path: Path, top: bool) -> None:
    """Legt einen abgedunkelten Textblock über eine Kopie des Hero-Bilds — großer,
    kontrastreicher Sans-Serif-Text in der TikTok-safe-zone (nicht am äußersten Rand)."""
    from PIL import Image, ImageDraw

    img = Image.open(base_path).convert("RGB").resize((W, H)).convert("RGBA")
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    band_h = int(H * 0.30)
    y0 = int(H * 0.10) if top else int(H * 0.60)
    draw.rectangle([0, y0, W, y0 + band_h], fill=(8, 10, 20, 165))
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    font = _find_font(64)
    lines = _wrap_text(draw, text, font, W - 140)
    line_h = 78
    total_h = len(lines) * line_h
    ty = y0 + max(20, (band_h - total_h) // 2)
    for line in lines:
        tw = draw.textlength(line, font=font)
        draw.text(((W - tw) // 2, ty), line, font=font, fill=(255, 255, 255, 255))
        ty += line_h

    img.convert("RGB").save(out_path)


# ── 4. ffmpeg-Clips (Zoom / Scroll) ──────────────────────────────────────────

def _clip_zoom(img_path: Path, out_path: Path, duration: float, zoom_to: float = 1.15) -> None:
    # WICHTIG: -t muss eine OUTPUT-Option sein (nach -i). Als Input-Option begrenzt sie nur
    # die (bei -loop 1 mit 25fps-Default) eingelesenen Quell-Frames -- zoompan vervielfacht
    # jeden davon aber um d Frames, was ohne Output--t zu einem Vielfachen der Ziel-Länge
    # (und entsprechend langer Renderzeit) statt der gewünschten kurzen Clips führte.
    frames = max(1, round(duration * FPS))
    inc = (zoom_to - 1.0) / frames
    vf = (f"scale={W * 2}:{H * 2},"
          f"zoompan=z='min(zoom+{inc:.6f},{zoom_to})':d={frames}:s={W}x{H}:fps={FPS},"
          f"format=yuv420p")
    _run_ffmpeg(["-loop", "1", "-i", str(img_path),
                 "-vf", vf, "-r", str(FPS), "-t", str(duration),
                 "-c:v", "libx264", "-crf", "18",
                 "-pix_fmt", "yuv420p", str(out_path)])


def _clip_scroll(full_path: Path, out_path: Path, duration: float) -> None:
    # Vertikaler Scroll-Pan ueber die Gesamtseite. Frueher via crop=...:eval=frame -- diese
    # eval-Option kennen aeltere/minimale imageio-ffmpeg-Builds nicht ("Option not found"),
    # weshalb der Clip fehlschlug. zoompan (Ken-Burns) ist in praktisch jedem Build vorhanden
    # (dasselbe Filter nutzt _clip_zoom erfolgreich) und pant genauso zuverlaessig.
    from PIL import Image
    fw, fh = Image.open(full_path).size
    scaled_h = max(H, round(fh * W / fw))          # auf Breite W skalieren, Hoehe mitziehen
    max_offset = max(0, scaled_h - H)
    if max_offset <= 0:
        _clip_zoom(full_path, out_path, duration, zoom_to=1.08)
        return
    frames = max(2, round(duration * FPS))
    # y wandert linear 0 -> max_offset ueber die Cliplaenge; on = bisher gerenderte Ausgabe-
    # Frames. Komma in min() durch einfache Quotes geschuetzt (wie z-Ausdruck in _clip_zoom).
    y_expr = f"'min({max_offset}*on/{frames - 1},{max_offset})'"
    vf = (f"scale={W}:{scaled_h},"
          f"zoompan=z=1:x=0:y={y_expr}:d=1:s={W}x{H}:fps={FPS},"
          f"format=yuv420p")
    _run_ffmpeg(["-loop", "1", "-i", str(full_path),
                 "-vf", vf, "-r", str(FPS), "-t", str(duration),
                 "-c:v", "libx264", "-crf", "18",
                 "-pix_fmt", "yuv420p", str(out_path)])


def _concat(clip_paths: list[Path], out_path: Path) -> None:
    list_file = out_path.with_suffix(".txt")
    list_file.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in clip_paths), encoding="utf-8")
    _run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(list_file),
                 "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
                 "-r", str(FPS), str(out_path)])


def _make_ambient_audio(path: Path, duration: float) -> None:
    """Dezenter Ambient-Ton (zwei sanfte Sinustöne, ein-/ausgeblendet). Läuft komplett
    offline ohne Lizenzfragen — Fallback laut Vorgabe, falls kein echter Beat verfügbar
    ist. Video entsteht damit nie stumm/fehlerhaft."""
    fade_out_start = max(0.0, duration - 1.2)
    _run_ffmpeg([
        "-f", "lavfi", "-i", f"sine=frequency=196:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=294:duration={duration}",
        "-filter_complex",
        f"[0:a][1:a]amix=inputs=2:duration=first[a];"
        f"[a]volume=0.15,afade=t=in:st=0:d=1,afade=t=out:st={fade_out_start}:d=1.2[aout]",
        "-map", "[aout]", "-ac", "2", "-ar", "44100", str(path),
    ])


def _mux_final(video_path: Path, audio_path: Path, out_path: Path,
               crf: int = 23, maxrate_k: int = 2500) -> None:
    _run_ffmpeg([
        "-i", str(video_path), "-i", str(audio_path),
        "-c:v", "libx264", "-crf", str(crf),
        "-maxrate", f"{maxrate_k}k", "-bufsize", f"{maxrate_k * 2}k",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
        "-t", str(TOTAL_S), "-movflags", "+faststart", "-shortest", str(out_path),
    ])


# ── 5. QS-Check (kein ffprobe gebündelt -> ffmpeg -i parsen) ─────────────────

def probe(path: Path) -> dict:
    exe = _ffmpeg_exe()
    proc = subprocess.run([exe, "-i", str(path)], capture_output=True, text=True)
    info = proc.stderr
    dur_m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", info)
    duration = None
    if dur_m:
        hh, mm, ss = dur_m.groups()
        duration = int(hh) * 3600 + int(mm) * 60 + float(ss)
    vid_m = re.search(r"Video:\s*([a-zA-Z0-9]+).*?(\d{3,5})x(\d{3,5})", info)
    size_mb = round(path.stat().st_size / (1024 * 1024), 2) if path.exists() else 0.0
    return {
        "duration":  duration,
        "codec":     vid_m.group(1) if vid_m else "",
        "width":     int(vid_m.group(2)) if vid_m else 0,
        "height":    int(vid_m.group(3)) if vid_m else 0,
        "has_audio": "Audio:" in info,
        "size_mb":   size_mb,
    }


def qa_checks(qa: dict) -> dict:
    duration_ok  = qa["duration"] is not None and abs(qa["duration"] - TOTAL_S) <= 0.15
    resolution_ok = qa["width"] == W and qa["height"] == H
    codec_ok     = "264" in (qa["codec"] or "")
    audio_ok     = bool(qa["has_audio"])
    size_ok      = qa["size_mb"] <= 12
    return {
        "duration_ok":   duration_ok,
        "resolution_ok": resolution_ok,
        "codec_ok":      codec_ok,
        "audio_ok":      audio_ok,
        "size_ok":       size_ok,
        "all_ok": duration_ok and resolution_ok and codec_ok and audio_ok and size_ok,
    }


# ── 6. Caption + Hashtags ────────────────────────────────────────────────────

def build_caption(domain: str) -> tuple[str, list[str]]:
    name = domain or "deine Website"
    caption = (
        f"Deine Website verdient mehr als 08/15 😍\n"
        f"So könnte {name} aussehen ➡️\n"
        f"Website-Design gefällig? Schreib mir 📩"
    )
    hashtags = ["#webdesign", "#website", "#webdesigner", "#smallbusiness",
                "#tiktokbusiness", "#designagentur", "#webentwicklung", "#kmu"]
    return caption, hashtags


# ── Öffentliche API ──────────────────────────────────────────────────────────

def build_ad_video(url: str, job_id: str, hook_text: str = "", cta_text: str = "",
                    progress_cb=None) -> dict:
    """Baut das komplette 10s-9:16-Werbevideo aus `url`. Gibt dict zurück:
    {path, web_url, qa, checks, caption, hashtags, url, title}."""
    url = normalize_url(url)
    workdir = _TMP_ROOT / job_id
    workdir.mkdir(parents=True, exist_ok=True)

    def prog(p: int, msg: str = "") -> None:
        if progress_cb:
            try:
                progress_cb(p, msg)
            except Exception:
                pass

    try:
        prog(5, "Lade Website…")
        meta = _capture(url, workdir)

        hero = workdir / "hero.png"
        full = workdir / "full.png"

        prog(30, "Wähle beste Ausschnitte…")
        from PIL import Image
        picks = _pick_detail_crops(full, n=3)
        detail_paths: list[Path] = []
        if picks:
            img = Image.open(full).convert("RGB")
            for i, y in enumerate(picks):
                p = workdir / f"detail_{i}.png"
                img.crop((0, y, img.width, y + H)).resize((W, H)).save(p)
                detail_paths.append(p)
        if not detail_paths:
            detail_paths = [hero]

        domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
        hook = (hook_text or "Deine Website könnte SO aussehen 👀").strip()
        cta = (cta_text or "Website-Design gefällig?\nJetzt Nachricht schreiben").strip()

        hook_card = workdir / "hook_card.png"
        cta_card = workdir / "cta_card.png"
        _compose_text_card(hero, hook, hook_card, top=True)
        _compose_text_card(hero, cta, cta_card, top=False)

        prog(45, "Schneide Clips…")
        clips: list[Path] = []

        c_hook = workdir / "c_hook.mp4"
        _clip_zoom(hook_card, c_hook, 1.5, zoom_to=1.18)
        clips.append(c_hook)

        c_scroll = workdir / "c_scroll.mp4"
        _clip_scroll(full, c_scroll, 5.0)
        clips.append(c_scroll)

        per = 2.5 / max(1, len(detail_paths))
        for i, p in enumerate(detail_paths):
            c = workdir / f"c_detail_{i}.mp4"
            _clip_zoom(p, c, per, zoom_to=1.2)
            clips.append(c)

        c_cta = workdir / "c_cta.mp4"
        _clip_zoom(cta_card, c_cta, 1.0, zoom_to=1.05)
        clips.append(c_cta)

        prog(70, "Baue Zusammenschnitt…")
        concat_out = workdir / "concat.mp4"
        _concat(clips, concat_out)

        prog(82, "Ton hinzufügen…")
        audio_path = workdir / "ambient.aac"
        _make_ambient_audio(audio_path, TOTAL_S)

        ts = time.strftime("%Y%m%d_%H%M%S")
        safe_domain = re.sub(r"[^a-zA-Z0-9_.-]", "_", domain) or "site"
        out_path = OUT_DIR / f"ad_{safe_domain}_{ts}.mp4"
        _mux_final(concat_out, audio_path, out_path)

        prog(92, "Prüfe Qualität…")
        qa = probe(out_path)
        checks = qa_checks(qa)
        attempts = 0
        while not checks["size_ok"] and attempts < 2:
            attempts += 1
            _mux_final(concat_out, audio_path, out_path,
                       crf=27 + attempts * 4, maxrate_k=max(600, 2500 - attempts * 700))
            qa = probe(out_path)
            checks = qa_checks(qa)

        caption, hashtags = build_caption(domain)

        prog(100, "Fertig")
        return {
            "path":     str(out_path),
            "web_url":  f"/workspace/media/ads/{out_path.name}",
            "qa":       qa,
            "checks":   checks,
            "caption":  caption,
            "hashtags": hashtags,
            "url":      url,
            "title":    meta.get("title", ""),
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def list_recent(limit: int = 30) -> list[dict]:
    items = []
    if OUT_DIR.exists():
        for p in OUT_DIR.iterdir():
            if p.is_file() and p.suffix.lower() == ".mp4":
                try:
                    mtime = p.stat().st_mtime
                except OSError:
                    continue
                items.append({"url": f"/workspace/media/ads/{p.name}", "name": p.name, "mtime": mtime})
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items[:limit]
