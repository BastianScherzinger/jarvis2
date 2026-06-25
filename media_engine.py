"""
JARVIS Media Engine
Lokale Bild- und Video-Generierung via Hugging Face Diffusers.
Modelle werden beim ersten Aufruf automatisch von HuggingFace heruntergeladen.
"""
from __future__ import annotations
import os
import re
import time
from pathlib import Path

# Saubere Logs: HF/Diffusers/Transformers-Fortschrittsbalken + Hinweise aus.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
os.environ.setdefault("DIFFUSERS_VERBOSITY", "error")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

_BASE = Path(__file__).parent
WORKSPACE_IMAGES = _BASE / "workspace" / "media" / "images"
WORKSPACE_VIDEOS = _BASE / "workspace" / "media" / "videos"
for _d in [WORKSPACE_IMAGES, WORKSPACE_VIDEOS]:
    _d.mkdir(parents=True, exist_ok=True)


# ── Modell-Katalog ───────────────────────────────────────────────────────────

IMAGE_MODELS: dict[str, dict] = {
    "sd-turbo": {
        "hf_id":          "stabilityai/sd-turbo",
        "name":           "SD-Turbo (schnell)",
        "pipeline":       "StableDiffusionPipeline",
        "size_gb":        2.1,
        "min_vram":       4,
        "default_w":      768,
        "default_h":      512,
        "supports_neg":   False,   # destilliert → kein Negativ-Prompt, CFG=0
        "gated":          False,
        "default_steps":  2,
        "guidance_scale": 0.0,
        "keep_scheduler": True,    # Turbo braucht seinen trainierten Scheduler
        "desc":           "Sehr schnell (1-4 Steps) — ideal auf CPU & für Hero-Banner",
    },
    "sdxl": {
        "hf_id":          "stabilityai/stable-diffusion-xl-base-1.0",
        "name":           "Stable Diffusion XL 1.0",
        "pipeline":       "StableDiffusionXLPipeline",
        "size_gb":        6.5,
        "min_vram":       8,
        "default_w":      1024,
        "default_h":      1024,
        "supports_neg":   True,
        "gated":          False,
        "default_steps":  30,
        "guidance_scale": 7.5,
        "desc":           "Beste offene Qualität — 1024×1024, realistisch, kein Token nötig",
    },
    "flux-schnell": {
        "hf_id":          "black-forest-labs/FLUX.1-schnell",
        "name":           "FLUX.1 Schnell",
        "pipeline":       "FluxPipeline",
        "size_gb":        15,
        "min_vram":       8,
        "default_w":      1024,
        "default_h":      1024,
        "supports_neg":   False,
        "gated":          True,
        "default_steps":  4,
        "guidance_scale": 3.5,
        "desc":           "Höchste Qualität — Lizenz auf huggingface.co akzeptieren + HF_TOKEN in .env",
    },
}

VIDEO_MODELS: dict[str, dict] = {
    "wan-1.3b": {
        # Diffusers-Format-Repo (enthält model_index.json) — das Original
        # 'Wan-AI/Wan2.1-T2V-1.3B' hat keins → 404 beim Laden.
        "hf_id":     "Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
        "name":      "Wan 2.1 T2V 1.3B",
        "size_gb":   2.7,
        "min_vram":  8,
        "default_frames": 25,
        "default_w": 832,
        "default_h": 480,
        "desc":      "Text-to-Video 480p — braucht GPU (auf CPU unbrauchbar langsam)",
    },
}

ALL_MODELS: dict[str, dict] = {**IMAGE_MODELS, **VIDEO_MODELS}


# ── Konfiguration aus .env ───────────────────────────────────────────────────

def get_active_image_model() -> str:
    """Liest JARVIS_IMAGE_MODEL aus .env. Default: sdxl.
    Ein gesperrtes Modell (FLUX) ohne HF_TOKEN wird auf ein offenes umgebogen —
    so läuft die Generierung schnell statt am 12B-FLUX zu hängen."""
    content = (_BASE / ".env").read_text(encoding="utf-8", errors="replace") if (_BASE / ".env").exists() else ""
    m = re.search(r"JARVIS_IMAGE_MODEL=(.+)", content)
    key = m.group(1).strip() if m else "sdxl"
    mc = IMAGE_MODELS.get(key)
    if mc and mc.get("gated") and not _hf_token():
        return _open_image_model()
    return key if key in IMAGE_MODELS else "sdxl"


def get_active_video_model() -> str:
    """Liest JARVIS_VIDEO_MODEL aus .env. Default: wan-1.3b."""
    content = (_BASE / ".env").read_text(encoding="utf-8", errors="replace") if (_BASE / ".env").exists() else ""
    m = re.search(r"JARVIS_VIDEO_MODEL=(.+)", content)
    return m.group(1).strip() if m else "wan-1.3b"


# ── Device & Dtype ───────────────────────────────────────────────────────────

def _device_dtype():
    import torch
    if torch.cuda.is_available():
        return "cuda", torch.float16
    try:
        if torch.backends.mps.is_available():
            return "mps", torch.float16
    except Exception:
        pass
    return "cpu", torch.float32


# ── Pipeline Cache ───────────────────────────────────────────────────────────

_cache: dict = {}


def _hf_token() -> str | None:
    """Hugging-Face-Token aus .env oder Umgebung (für gated Modelle wie FLUX)."""
    content = (_BASE / ".env").read_text(encoding="utf-8", errors="replace") if (_BASE / ".env").exists() else ""
    m = re.search(r"HF_TOKEN=(.+)", content)
    tok = (m.group(1).strip() if m else "") or os.environ.get("HF_TOKEN") \
        or os.environ.get("HUGGINGFACE_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    return tok or None


class GatedModelError(RuntimeError):
    """Modell ist auf Hugging Face gesperrt (Token/Lizenz nötig)."""


def _load_image_pipe(model_key: str):
    if model_key in _cache:
        return _cache[model_key]

    from diffusers import (
        StableDiffusionPipeline,
        StableDiffusionXLPipeline,
        FluxPipeline,
    )
    import torch

    if model_key not in IMAGE_MODELS:
        raise ValueError(f"Unbekanntes Bildmodell: '{model_key}'. Verfügbar: {list(IMAGE_MODELS)}")

    m         = IMAGE_MODELS[model_key]
    dev, dt   = _device_dtype()
    pipe_map  = {
        "StableDiffusionPipeline":   StableDiffusionPipeline,
        "StableDiffusionXLPipeline": StableDiffusionXLPipeline,
        "FluxPipeline":              FluxPipeline,
    }
    Cls = pipe_map[m["pipeline"]]

    kwargs: dict = {"torch_dtype": dt, "use_safetensors": True}
    tok = _hf_token()
    if tok:
        kwargs["token"] = tok

    try:
        pipe = Cls.from_pretrained(m["hf_id"], **kwargs)
    except Exception as e:
        msg = str(e).lower()
        if m.get("gated") or "gated" in msg or "restricted" in msg or "401" in msg or "403" in msg:
            raise GatedModelError(
                f"'{m['name']}' ist auf Hugging Face gesperrt. Wähle ein offenes "
                f"Modell (Stable Diffusion XL oder SD 2.1) — ODER akzeptiere die "
                f"Lizenz auf huggingface.co/{m['hf_id']} und trage HF_TOKEN=… in die "
                f".env ein."
            )
        raise
    pipe = pipe.to(dev)

    # Diffusers-Fortschrittsbalken (tqdm) abschalten — saubere Logs.
    try: pipe.set_progress_bar_config(disable=True)
    except Exception: pass

    # Schnellerer Scheduler (DPM++ 2M Karras): gleiche Qualität bei ~20-25 Steps
    # statt 30-50 → deutlich schneller. NICHT für Turbo-Modelle (die brauchen ihren
    # trainierten Scheduler, sonst werden 1-2-Step-Bilder unbrauchbar).
    if not m.get("keep_scheduler"):
        try:
            from diffusers import DPMSolverMultistepScheduler
            pipe.scheduler = DPMSolverMultistepScheduler.from_config(
                pipe.scheduler.config, use_karras_sigmas=True, algorithm_type="dpmsolver++"
            )
        except Exception:
            pass

    if dev == "cpu":
        # CPU-Optimierung (32-GB-RAM-PC ohne GPU): alle Kerne nutzen + speicher-
        # schonende Slices/Tiles, damit auch SDXL ohne OOM läuft und SD-Turbo zügig.
        try: torch.set_num_threads(_cpu_threads())
        except Exception: pass
        try: pipe.enable_attention_slicing("max")
        except Exception: pass
        try: pipe.enable_vae_tiling()
        except Exception: pass
        try: pipe.enable_vae_slicing()
        except Exception: pass
    elif dev == "cuda":
        # GPU-Optimierung: schnellere Faltungen + speichereffiziente Attention
        try:
            torch.backends.cudnn.benchmark = True
            torch.backends.cuda.matmul.allow_tf32 = True
        except Exception: pass
        try: pipe.enable_xformers_memory_efficient_attention()
        except Exception: pass
        try: pipe.enable_vae_slicing()
        except Exception: pass

    _cache[model_key] = pipe
    return pipe


def _load_video_pipe(model_key: str):
    if model_key in _cache:
        return _cache[model_key]

    import torch
    from diffusers import WanPipeline

    if model_key not in VIDEO_MODELS:
        raise ValueError(f"Unbekanntes Videomodell: '{model_key}'. Verfügbar: {list(VIDEO_MODELS)}")

    m       = VIDEO_MODELS[model_key]
    dev, _  = _device_dtype()
    # Wan-Empfehlung: VAE in float32 (sonst NaN/schwarze Frames), Pipeline bfloat16
    # auf GPU / float32 auf CPU.
    pipe_dt = torch.bfloat16 if dev == "cuda" else torch.float32
    kwargs: dict = {"torch_dtype": pipe_dt}
    tok = _hf_token()
    if tok:
        kwargs["token"] = tok
    try:
        from diffusers import AutoencoderKLWan
        vae_kwargs = {"subfolder": "vae", "torch_dtype": torch.float32}
        if tok:
            vae_kwargs["token"] = tok
        kwargs["vae"] = AutoencoderKLWan.from_pretrained(m["hf_id"], **vae_kwargs)
    except Exception:
        pass   # ältere diffusers ohne AutoencoderKLWan → Standard-VAE

    pipe = WanPipeline.from_pretrained(m["hf_id"], **kwargs)

    # 480p: flow_shift=3.0 (Wan-Doku) für saubere Bewegung.
    try:
        from diffusers import UniPCMultistepScheduler
        pipe.scheduler = UniPCMultistepScheduler.from_config(
            pipe.scheduler.config, flow_shift=3.0)
    except Exception:
        pass

    if dev == "cuda":
        try:
            pipe.enable_model_cpu_offload()    # verwaltet Device selbst
        except Exception:
            pipe = pipe.to(dev)
    else:
        try: torch.set_num_threads(_cpu_threads())
        except Exception: pass
        pipe = pipe.to(dev)

    _cache[model_key] = pipe
    return pipe


# ── Öffentliche API ──────────────────────────────────────────────────────────

def _open_image_model() -> str:
    """Erstes offenes (nicht gesperrtes) Bildmodell — Fallback für gated Modelle."""
    for k, m in IMAGE_MODELS.items():
        if not m.get("gated"):
            return k
    return "sdxl"


def _env(key: str, default: str = "") -> str:
    """Liest einen Wert aus .env (oder Umgebung). Klein & defensiv."""
    try:
        content = (_BASE / ".env").read_text(encoding="utf-8", errors="replace") if (_BASE / ".env").exists() else ""
        m = re.search(rf"^{re.escape(key)}=(.+)$", content, re.M)
        return (m.group(1).strip() if m else "") or os.environ.get(key, default)
    except Exception:
        return os.environ.get(key, default)


def _resolve_image_model(model_key: "str | None") -> str:
    """Wählt das Bildmodell. Explizite Angabe gewinnt immer. Sonst (Default):
    hardware-bestes Modell — CPU→SD-Turbo (schnell, lohnt sich lokal), GPU→SDXL/FLUX.
    Nur wenn JARVIS_IMAGE_AUTO=0 gesetzt ist, gilt stattdessen JARVIS_IMAGE_MODEL (.env)."""
    if model_key and model_key in IMAGE_MODELS:
        return model_key
    if _env("JARVIS_IMAGE_AUTO", "1") != "0":
        return best_image_model()
    return get_active_image_model()


# ── Hardware-abhängige Modellwahl ────────────────────────────────────────────

def _ram_gb() -> float:
    """System-RAM in GB — nutzt das vorhandene hardware-Modul (ctypes, ohne psutil)."""
    try:
        import hardware
        return float(hardware.ram_gb())
    except Exception:
        try:
            import os as _os
            return round(_os.sysconf("SC_PAGE_SIZE") * _os.sysconf("SC_PHYS_PAGES") / (1024 ** 3), 1)
        except Exception:
            return 0.0


def _cpu_threads() -> int:
    """Physische/logische Kerne für Torch-CPU-Inferenz (mehr Threads = schneller auf CPU)."""
    try:
        import os as _os
        return max(1, (_os.cpu_count() or 4))
    except Exception:
        return 4


def hardware_info() -> dict:
    """Erkennt das Rechen-Backend für die Bildgenerierung.
    Returns {device:'cuda'|'mps'|'cpu', vram_gb:float, gpu_name:str, ram_gb:float}."""
    ram = _ram_gb()
    try:
        import torch
        if torch.cuda.is_available():
            p = torch.cuda.get_device_properties(0)
            return {"device": "cuda", "vram_gb": round(p.total_memory / 1e9, 1),
                    "gpu_name": p.name, "ram_gb": ram}
        try:
            if torch.backends.mps.is_available():
                return {"device": "mps", "vram_gb": 0.0, "gpu_name": "Apple MPS", "ram_gb": ram}
        except Exception:
            pass
    except Exception:
        pass
    return {"device": "cpu", "vram_gb": 0.0, "gpu_name": "", "ram_gb": ram}


def best_image_model() -> str:
    """Bestes Bildmodell für die vorhandene Hardware:
      starke GPU (≥12 GB + HF-Token) → FLUX (höchste Qualität),
      GPU (≥6 GB) / Apple-MPS        → SDXL (krasse Qualität),
      kleine GPU / CPU               → SD-Turbo (schnell)."""
    hw = hardware_info()
    dev, vram = hw["device"], hw["vram_gb"]
    if dev == "cuda":
        if vram >= 12 and "flux-schnell" in IMAGE_MODELS and _hf_token():
            return "flux-schnell"
        if vram >= 6:
            return "sdxl"
        return "sd-turbo"
    if dev == "mps":
        return "sdxl"
    return "sd-turbo"


def hero_image_params() -> dict:
    """Modell + Parameter für ein hochwertiges Hero-/Vorschau-Bild, hardware-angepasst.
    GPU → SDXL/FLUX in hoher Auflösung; CPU → SD-Turbo schnell. Direkt als
    **kwargs an generate_image() übergebbar."""
    key = best_image_model()
    if key == "flux-schnell":
        return {"model_key": "flux-schnell", "steps": 4, "width": 1344, "height": 768}
    if key == "sdxl":
        return {"model_key": "sdxl", "steps": 28, "width": 1280, "height": 720}
    return {"model_key": "sd-turbo", "steps": 2, "width": 768, "height": 512}


def generate_image(
    prompt: str,
    model_key: str | None = None,
    negative_prompt: str = "",
    steps: int = 0,
    width: int | None = None,
    height: int | None = None,
    guidance_scale: float = 0.0,
    output_dir: "Path | None" = None,
    filename: str = "",
) -> dict:
    """
    Generiert ein Bild. Gibt dict zurück:
      {'path': str, 'web_url': str, 'model': str, 'prompt': str, 'elapsed': float}

    output_dir: optionales Zielverzeichnis (z.B. für Set-Unterordner).
    filename:   optionaler Dateiname ohne Pfad (z.B. "logo.png").
    """
    key = _resolve_image_model(model_key)
    m   = IMAGE_MODELS.get(key)
    if m is None:
        raise ValueError(f"Bildmodell '{key}' nicht bekannt. Verfügbar: {list(IMAGE_MODELS)}")

    # Gesperrtes Modell (z.B. FLUX) ohne HF-Token → offenes Modell
    if m.get("gated") and not _hf_token():
        fallback = _open_image_model()
        if fallback and fallback != key:
            key = fallback
            m   = IMAGE_MODELS[key]

    w   = width  or m["default_w"]
    h   = height or m["default_h"]
    if not steps or steps <= 0:
        steps = m.get("default_steps", 30)
    gs  = guidance_scale if guidance_scale > 0 else m.get("guidance_scale", 7.5)
    neg = negative_prompt or (
        "blurry, low quality, watermark, text, deformed, ugly, bad anatomy, "
        "distorted, disfigured, cropped, out of frame"
    )

    t0   = time.time()
    pipe = _load_image_pipe(key)

    kwargs: dict = {
        "prompt":              prompt,
        "num_inference_steps": min(max(steps, 1), 80),
        "width":               w,
        "height":              h,
    }
    # guidance_scale IMMER setzen (0.0 für Turbo deaktiviert CFG korrekt);
    # Negativ-Prompt nur bei Modellen, die ihn unterstützen.
    kwargs["guidance_scale"] = gs
    if m["supports_neg"]:
        kwargs["negative_prompt"] = neg

    result = pipe(**kwargs)
    image  = result.images[0]

    dest = output_dir if output_dir else WORKSPACE_IMAGES
    dest.mkdir(parents=True, exist_ok=True)
    fn   = filename if filename else f"img_{time.strftime('%Y%m%d_%H%M%S')}.png"
    out  = dest / fn
    image.save(str(out))

    # Web-URL relativ zu WORKSPACE_IMAGES — fällt auf "" zurück, wenn das Ziel
    # außerhalb des Workspace liegt (z.B. Hero-Banner in einem Projektordner).
    try:
        rel = out.relative_to(WORKSPACE_IMAGES)
        web_url = f"/workspace/media/images/{rel.as_posix()}"
    except ValueError:
        web_url = ""
    res = {
        "path":    str(out),
        "web_url": web_url,
        "model":   m["name"],
        "prompt":  prompt,
        "elapsed": round(time.time() - t0, 1),
    }
    try:
        import logger as _lg
        _lg.activity("MediaEngine", "Bild generiert",
                     f"{m['name']} · {prompt[:60]}", "🖼", "image")
        import cost_tracker as _ct
        _ct.track_compute(res["elapsed"], hw.get("device") != "cpu" if "hw" in dir() else False, "image_gen")
    except Exception:
        pass
    return res


def generate_video(
    prompt: str,
    model_key: str | None = None,
    negative_prompt: str = "low quality, blurry, watermark, distorted",
    num_frames: int = 25,
) -> dict:
    """
    Generiert ein Video. Gibt dict zurück:
      {'path': str, 'web_url': str, 'model': str, 'prompt': str, 'elapsed': float}
    """
    # Backend-Wahl: auto (Standard) | local | higgsfield.
    # - higgsfield        → immer Cloud
    # - auto + keine GPU  → automatisch Cloud (lokales Wan auf CPU = Stunden/Clip)
    # - local / GPU       → lokal generieren
    backend = (os.environ.get("JARVIS_VIDEO_BACKEND") or "auto").strip().lower()
    hw      = hardware_info()
    on_cpu  = hw["device"] == "cpu"
    _mlog("debug", "Video", f"Backend={backend} device={hw['device']} → "
          + ("Higgsfield Cloud" if (backend == 'higgsfield' or (backend != 'local' and on_cpu)) else "lokal (Wan)"))
    if backend == "higgsfield" or (backend != "local" and on_cpu):
        if on_cpu and backend != "higgsfield":
            _mlog("info", "Video", "Kein GPU erkannt → Video läuft automatisch über Higgsfield Cloud.")
        # 1) Abo-MCP bevorzugt (zuverlässige Modelle wie kling3_0_turbo über die Abo-Credits) —
        #    so wie bei Hero-Bildern. Vermeidet den toten Platform-API-Pfad (dop-lite → 404).
        try:
            import higgsfield_mcp
            if higgsfield_mcp.available():
                ts  = time.strftime("%Y%m%d_%H%M%S")
                out = WORKSPACE_VIDEOS / f"vid_{ts}.mp4"
                out.parent.mkdir(parents=True, exist_ok=True)
                r = higgsfield_mcp.generate_video(prompt, out, aspect_ratio="16:9")
                return {"path": r.get("path", str(out)),
                        "web_url": f"/workspace/media/videos/{out.name}",
                        "model": r.get("model", "Higgsfield (MCP/Abo)"),
                        "prompt": prompt, "engine": "higgsfield_mcp"}
        except Exception as ex:
            _mlog("warn", "Video", f"MCP-Video fehlgeschlagen, versuche Platform-API: {str(ex)[:140]}")
        # 2) Platform-API-Key (eigener Credit-Topf).
        if higgsfield_available():
            hf_model = os.environ.get("JARVIS_HIGGSFIELD_VIDEO_MODEL", "dop-lite")
            return generate_video_higgsfield(prompt, model=hf_model)
        if backend == "higgsfield":
            raise RuntimeError(
                "Video-Backend 'higgsfield' gewählt, aber HIGGSFIELD_API_KEY fehlt in der "
                ".env. Format: HIGGSFIELD_API_KEY=KEY_ID:KEY_SECRET  "
                "(Key unter https://cloud.higgsfield.ai/api-keys erstellen).")
        # auto + CPU + kein Higgsfield (weder MCP-Abo noch API-Key)
        raise RuntimeError(
            f"Kein GPU ({hw['device']}) und kein Higgsfield-Zugang — Video nicht möglich. "
            "Lösung: HIGGSFIELD_API_KEY=ID:SECRET in die .env eintragen (oder Higgsfield-MCP "
            "anmelden), dann läuft Video automatisch über die Higgsfield Cloud.")

    key = model_key or get_active_video_model()
    m   = VIDEO_MODELS.get(key)
    if m is None:
        raise ValueError(f"Videomodell '{key}' nicht bekannt. Verfügbar: {list(VIDEO_MODELS)}")

    t0   = time.time()
    pipe = _load_video_pipe(key)
    nf   = min(max(num_frames, 1), 81)

    output = pipe(
        prompt=prompt,
        negative_prompt=negative_prompt,
        height=m["default_h"],
        width=m["default_w"],
        num_frames=nf,
        guidance_scale=5.0,
    )
    frames = output.frames[0]   # List[PIL.Image]

    ts  = time.strftime("%Y%m%d_%H%M%S")
    out = WORKSPACE_VIDEOS / f"vid_{ts}.mp4"

    try:
        import imageio
        import numpy as np
        writer = imageio.get_writer(str(out), fps=16, codec="libx264", quality=8)
        for f in frames:
            writer.append_data(np.array(f))
        writer.close()
    except Exception:
        # GIF-Fallback wenn MP4-Export fehlschlägt
        out = out.with_suffix(".gif")
        frames[0].save(
            str(out),
            save_all=True,
            append_images=frames[1:],
            duration=62,
            loop=0,
        )

    suffix = out.suffix
    vid_res = {
        "path":    str(out),
        "web_url": f"/workspace/media/videos/{out.name}",
        "model":   m["name"],
        "prompt":  prompt,
        "elapsed": round(time.time() - t0, 1),
    }
    try:
        import logger as _lg
        _lg.activity("MediaEngine", "Video generiert",
                     f"{m['name']} · {prompt[:60]}", "🎬", "video")
        import cost_tracker as _ct
        # Lokales Wan-Video läuft nur auf GPU (CPU-Pfad bricht oben ab) → use_gpu=True.
        _ct.track_compute(vid_res["elapsed"], True, "video_gen")
    except Exception:
        pass
    return vid_res


# ── Higgsfield.ai Cloud API ──────────────────────────────────────────────────

_HIGGSFIELD_BASE = "https://platform.higgsfield.ai"

# Cloudflare blockt „nackte" Python-urllib-Requests mit Error 1010 (Access denied — owner has
# banned your browser's signature). Darum bei JEDEM Higgsfield-Request einen echten
# Browser-User-Agent + Standard-Browser-Header mitschicken.
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _media_debug() -> bool:
    return (os.environ.get("JARVIS_MEDIA_DEBUG", "0").strip().lower() in ("1", "true", "yes", "ja"))


def _mlog(level: str, where: str, msg: str) -> None:
    """Einheitliches Media-Logging (best-effort). level: info|warn|success|debug."""
    try:
        import logger as _lg
        if level == "debug" and not _media_debug():
            return
        getattr(_lg, {"warn": "warn", "success": "success", "debug": "info"}.get(level, "info"),
                _lg.info)(where, msg)
    except Exception:
        pass

# Credits je Higgsfield-Soul-Bild (Schätzung, via .env feinjustierbar). Wird für das
# Kostentracking genutzt — Videos lesen ihre Credits aus HIGGSFIELD_MODELS.
_HF_IMAGE_CREDITS = int(os.environ.get("JARVIS_HF_IMAGE_CREDITS", "1") or "1")

# Verfügbare Higgsfield-Modelle
HIGGSFIELD_MODELS = {
    "dop-lite":    {"name": "Higgsfield Dop Lite",    "credits": 3,  "desc": "Schnell, 3 Credits — gut für Tests"},
    "dop-preview": {"name": "Higgsfield Dop Preview", "credits": 6,  "desc": "Ausgewogen, 6 Credits — Standard"},
    "dop-turbo":   {"name": "Higgsfield Dop Turbo",   "credits": 9,  "desc": "Höchste Qualität, 9 Credits"},
}


def _hf_key() -> str:
    # os.environ zuerst: load_dotenv() hat .env bereits geladen — zuverlässiger als Datei-Parse
    ev = os.environ.get("HIGGSFIELD_API_KEY", "").strip()
    if ev:
        return ev
    # Fallback: direkt aus .env-Datei lesen (falls os.environ noch nicht befüllt)
    content = (_BASE / ".env").read_text(encoding="utf-8", errors="replace") if (_BASE / ".env").exists() else ""
    m = re.search(r"^HIGGSFIELD_API_KEY=(.+)", content, re.M)
    return m.group(1).strip() if m else ""


def _hf_secret() -> str:
    """Separater Secret-Key (Higgsfield SDK = ID:SECRET). Optional — wer den Key
    schon als 'ID:SECRET' in HIGGSFIELD_API_KEY hat, braucht das hier nicht."""
    content = (_BASE / ".env").read_text(encoding="utf-8", errors="replace") if (_BASE / ".env").exists() else ""
    m = re.search(r"^HIGGSFIELD_SECRET=(.+)", content, re.M)    # ^ = Kommentarzeilen ignorieren
    sec = m.group(1).strip() if m else ""
    return sec or os.environ.get("HIGGSFIELD_SECRET", "")


def generate_video_higgsfield(
    prompt: str,
    model: str = "dop-lite",
    image_url: str | None = None,
    motion_strength: float = 0.5,
    enhance_prompt: bool = True,
    seed: int | None = None,
) -> dict:
    """
    Generiert ein Video via Higgsfield.ai Cloud API.
    Polling bis COMPLETED (max 5 Minuten).
    Gibt dict zurück: {'path', 'web_url', 'model', 'prompt', 'elapsed'}
    """
    import urllib.request
    import urllib.error
    import json

    api_key = _hf_key()
    if not api_key:
        raise ValueError(
            "HIGGSFIELD_API_KEY fehlt in .env.\n"
            "API-Key unter https://cloud.higgsfield.ai/api-keys erstellen."
        )

    headers_json = _hf_headers(api_key)                      # inkl. Browser-UA (gegen Cloudflare 1010)
    headers_get  = {k: v for k, v in headers_json.items() if k != "Content-Type"}

    model = model if model in HIGGSFIELD_MODELS else "dop-lite"
    _mlog("info", "Higgsfield", f"Video-Auftrag · Modell {model} · {prompt[:60]}")

    payload: dict = {
        "model":            model,
        "prompt":           prompt,
        "motions_strength": round(max(0.0, min(1.0, motion_strength)), 2),
        "enhance_prompt":   enhance_prompt,
    }
    if image_url:
        payload["input_images"] = [image_url]
    if seed is not None:
        payload["seed"] = seed

    # ── Auftrag erstellen ────────────────────────────────────────────
    t0 = time.time()
    try:
        req = urllib.request.Request(
            f"{_HIGGSFIELD_BASE}/v1/generations",
            data=json.dumps(payload).encode(),
            headers=headers_json,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            create_data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        _mlog("warn", "Higgsfield", f"Video-POST {e.code}: {body[:200]}")
        raise RuntimeError(_hf_error_hint(e.code, body))
    except urllib.error.URLError as e:
        _mlog("warn", "Higgsfield", f"Video-POST Netzwerkfehler: {e}")
        raise RuntimeError(f"Higgsfield nicht erreichbar: {getattr(e, 'reason', e)}")

    gen_id = (
        create_data.get("id")
        or create_data.get("request_id")
        or create_data.get("generation_id")
    )
    if not gen_id:
        raise ValueError(f"Kein ID in Higgsfield-Antwort: {create_data}")

    # ── Polling bis COMPLETED ────────────────────────────────────────
    video_url = ""
    for _ in range(60):          # max 5 Minuten (60 × 5s)
        time.sleep(5)
        poll_req = urllib.request.Request(
            f"{_HIGGSFIELD_BASE}/v1/generations/{gen_id}",
            headers=headers_get,
        )
        try:
            with urllib.request.urlopen(poll_req, timeout=15) as resp:
                poll_data = json.loads(resp.read().decode())
        except Exception:
            continue

        status = (poll_data.get("status") or "").upper()

        if status == "COMPLETED":
            # Video-URL extrahieren — verschiedene mögliche Strukturen
            video_url = (
                (poll_data.get("video") or {}).get("url", "")
                or (poll_data.get("output") or {}).get("url", "")
                or poll_data.get("video_url", "")
            )
            if not video_url:
                outputs = poll_data.get("outputs", [])
                if outputs:
                    first = outputs[0]
                    video_url = first.get("url", "") if isinstance(first, dict) else str(first)
            break

        elif status in ("FAILED", "ERROR", "CANCELLED"):
            err = poll_data.get("error") or poll_data.get("message") or status
            raise RuntimeError(f"Higgsfield Generierung fehlgeschlagen: {err}")

    else:
        raise TimeoutError("Higgsfield Timeout nach 5 Minuten — kein Ergebnis erhalten")

    if not video_url:
        raise RuntimeError(f"Kein Video-URL in Higgsfield-Antwort: {poll_data}")

    # ── Video herunterladen ──────────────────────────────────────────
    dl_req = urllib.request.Request(video_url, headers={"User-Agent": _BROWSER_UA})
    with urllib.request.urlopen(dl_req, timeout=120) as resp:
        video_bytes = resp.read()
    _mlog("success", "Higgsfield", f"Video fertig ({round(time.time() - t0, 1)}s)")

    ts  = time.strftime("%Y%m%d_%H%M%S")
    out = WORKSPACE_VIDEOS / f"higgsfield_{ts}.mp4"
    out.write_bytes(video_bytes)

    hf_res = {
        "path":    str(out),
        "web_url": f"/workspace/media/videos/{out.name}",
        "model":   HIGGSFIELD_MODELS.get(model, {}).get("name", model),
        "prompt":  prompt,
        "gen_id":  gen_id,
        "elapsed": round(time.time() - t0, 1),
    }
    try:
        import logger as _lg
        _lg.activity("Higgsfield", "Video generiert",
                     f"{hf_res['model']} · {prompt[:60]}", "🎬", "video")
        credits = HIGGSFIELD_MODELS.get(model, {}).get("credits", 3)
        import cost_tracker as _ct
        _ct.track_higgsfield(credits, "video_gen")
    except Exception:
        pass
    return hf_res


def _hf_id() -> str:
    """Separater KEY_ID (Higgsfield SDK = ID:SECRET). Optional — wer den Key schon als
    'ID:SECRET' in HIGGSFIELD_API_KEY hat, braucht das hier nicht."""
    content = (_BASE / ".env").read_text(encoding="utf-8", errors="replace") if (_BASE / ".env").exists() else ""
    m = re.search(r"^HIGGSFIELD_ID=(.+)", content, re.M)
    hid = m.group(1).strip() if m else ""
    return hid or os.environ.get("HIGGSFIELD_ID", "")


def _hf_headers(api_key: str) -> dict:
    """Higgsfield-Auth. Das Platform-SDK nutzt 'Key KEY_ID:KEY_SECRET'. Vier Fälle:
      - Key enthält ':'              → direkt als 'Key id:secret'
      - getrennter HIGGSFIELD_SECRET → zu 'Key id:secret' zusammengesetzt
      - getrennter HIGGSFIELD_ID     → 'Key id:key' (key ist dann das Secret)
      - sonst (Einzel-Token)         → 'Bearer key' (ältere Keys)."""
    key = (api_key or "").strip()
    if ":" in key:
        auth = f"Key {key}"
    else:
        sec = _hf_secret()
        if sec:
            auth = f"Key {key}:{sec}"
        else:
            hid = _hf_id()
            auth = f"Key {hid}:{key}" if hid else f"Bearer {key}"
    return {"Authorization": auth, "Content-Type": "application/json",
            "User-Agent": _BROWSER_UA, "Accept": "application/json",
            "Origin": "https://higgsfield.ai", "Referer": "https://higgsfield.ai/"}


def _hf_error_hint(code: int, body: str) -> str:
    """Verständliche Fehlermeldung aus Higgsfield-HTTP-Code + Body. Erkennt insbesondere
    Cloudflare-1010 (gebannte Browser-Signatur) und Guthaben-Probleme."""
    b = (body or "").lower()
    if "1010" in b or "error 1010" in b or ("cloudflare" in b and "denied" in b):
        return ("Higgsfield/Cloudflare-Fehler 1010 (Zugriff blockiert). Behoben durch echten "
                "Browser-User-Agent — falls weiter: Higgsfield-Endpunkt/Key prüfen.")
    # Guthaben ZUERST prüfen: Higgsfield meldet 'Not enough credits' auch als 403 — sonst
    # würde es fälschlich als Auth-Fehler ausgegeben.
    if code == 402 or "credit" in b or "insufficient" in b or "not enough" in b:
        return (f"Higgsfield {code}: API-Key gültig, aber 0 Platform-API-Credits. ACHTUNG: "
                "Abo-Credits (Soul/Plus) sind ein ANDERER Topf als Platform-API-Credits "
                "(platform.higgsfield.ai). Lösung: API-Key auf dem Abo-Konto erstellen ODER "
                "dort API-Credits aufladen.")
    if code in (401, 403):
        return (f"Higgsfield {code}: Auth fehlgeschlagen — HIGGSFIELD_API_KEY (Format ID:SECRET) "
                "in der .env prüfen.")
    if code == 404:
        return f"Higgsfield {code}: Endpunkt nicht gefunden — API-Pfad veraltet."
    return f"Higgsfield-API-Fehler {code}: {body[:200]}"


def higgsfield_available() -> bool:
    return bool(_hf_key())


def higgsfield_selftest() -> dict:
    """Prüft, ob die Higgsfield-Bild-API WIRKLICH nutzbar ist (nicht nur ob ein Key da ist).
    Schickt einen minimalen, gültigen Probe-Auftrag und klassifiziert die Antwort:
      state = 'nokey' | 'unreachable' | 'auth' | 'no_credits' | 'ok'
    Wichtig: bei 'ok' (Auth gültig UND Guthaben vorhanden) wird ein echter — sehr kleiner —
    Auftrag erstellt und kostet ~1 Credit. Daher nur ON DEMAND aufrufen, nicht in get_status.
    Gibt {ok, state, detail, hint}."""
    import urllib.request
    import urllib.error
    import json
    key = _hf_key()
    if not key:
        return {"ok": False, "state": "nokey", "detail": "Kein HIGGSFIELD_API_KEY in .env.",
                "hint": "HIGGSFIELD_API_KEY=ID:SECRET in die .env eintragen."}
    payload = {"params": {"prompt": "selftest", "width_and_height": "1536x1536",
                          "quality": "720p", "batch_size": 1, "enhance_prompt": False}}
    try:
        req = urllib.request.Request(f"{_HIGGSFIELD_BASE}/v1/text2image/soul",
                                     data=json.dumps(payload).encode(),
                                     headers=_hf_headers(key), method="POST")
        with urllib.request.urlopen(req, timeout=25) as r:
            json.loads(r.read().decode())   # Auftrag erstellt → Auth + Guthaben ok
        return {"ok": True, "state": "ok", "detail": "Higgsfield-Bild-API funktioniert (Auftrag erstellt).",
                "hint": ""}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        b = body.lower()
        if e.code == 402 or "credit" in b or "not enough" in b or "insufficient" in b:
            return {"ok": False, "state": "no_credits",
                    "detail": f"Key gültig, aber 0 Platform-API-Credits (HTTP {e.code}).",
                    "hint": ("Wichtig: Higgsfield trennt ABO-Credits (Soul/Plus, nutzbar über "
                             "App/MCP) von PLATFORM-API-Credits (platform.higgsfield.ai, eigener "
                             "Topf). Lösung: den API-Key auf GENAU dem Konto mit dem Abo erstellen "
                             "ODER unter platform.higgsfield.ai API-Credits aufladen.")}
        if e.code in (401, 403):
            return {"ok": False, "state": "auth",
                    "detail": f"Auth abgelehnt (HTTP {e.code}): {body[:120]}",
                    "hint": "HIGGSFIELD_API_KEY-Format prüfen (ID:SECRET)."}
        return {"ok": False, "state": "unreachable",
                "detail": f"HTTP {e.code}: {body[:120]}", "hint": ""}
    except Exception as e:
        return {"ok": False, "state": "unreachable",
                "detail": f"{type(e).__name__}: {str(e)[:120]}",
                "hint": "Higgsfield nicht erreichbar — Netzwerk/Endpunkt prüfen."}


def higgsfield_balance() -> "int | None":
    """Best-effort: verbleibende Higgsfield-Credits. None = unbekannt (kein dokumentierter
    Endpunkt — daher mehrere Pfade probiert; bei Unbekannt wird trotzdem versucht und der
    'NotEnoughCredits'-Fehler der Generierung greift als Rückfall)."""
    key = _hf_key()
    if not key:
        return None
    import urllib.request
    import json
    for path in ("/v1/credits", "/v1/balance", "/v1/account/credits", "/v1/me"):
        try:
            req = urllib.request.Request(_HIGGSFIELD_BASE + path, headers=_hf_headers(key))
            with urllib.request.urlopen(req, timeout=12) as r:
                d = json.loads(r.read().decode())
            if isinstance(d, (int, float)):
                return int(d)
            if isinstance(d, dict):
                for k in ("credits", "balance", "remaining", "available", "credit_balance"):
                    v = d.get(k)
                    if isinstance(v, (int, float)):
                        return int(v)
        except Exception:
            continue
    return None


def _hf_extract_image_url(pd: dict) -> str:
    """Bild-URL aus verschiedenen möglichen Higgsfield-Antwortstrukturen ziehen."""
    jobs = pd.get("jobs") or (pd.get("job_set") or {}).get("jobs") or []
    if jobs and isinstance(jobs[0], dict):
        res = jobs[0].get("results") or {}
        for key in ("raw", "min", "preview"):
            u = (res.get(key) or {}).get("url") if isinstance(res.get(key), dict) else None
            if u:
                return u
        if isinstance(jobs[0].get("result"), dict):
            u = jobs[0]["result"].get("url")
            if u:
                return u
    for key in ("image", "output"):
        u = (pd.get(key) or {}).get("url") if isinstance(pd.get(key), dict) else None
        if u:
            return u
    outs = pd.get("outputs") or []
    if outs:
        first = outs[0]
        return first.get("url", "") if isinstance(first, dict) else str(first)
    return pd.get("image_url", "") or pd.get("url", "")


# Von Higgsfield Soul akzeptierte Bildgrößen (strikt validiert — sonst HTTP 422).
_HF_SIZES_LANDSCAPE = ["2048x1152", "1696x960", "1680x1120", "1632x1088", "2016x1344",
                       "2048x1536", "1536x1152"]
_HF_SIZES_PORTRAIT  = ["1152x2048", "960x1696", "1120x1680", "1088x1632", "1344x2016",
                       "1536x2048", "1152x1536"]
_HF_SIZES_SQUARE    = ["1536x1536", "2048x2048"]
_HF_SIZES_ALL = set(_HF_SIZES_LANDSCAPE + _HF_SIZES_PORTRAIT + _HF_SIZES_SQUARE)


def _hf_valid_size(width: int, height: int) -> str:
    """Bildet die gewünschte Auflösung auf eine von Higgsfield AKZEPTIERTE Größe ab.
    .env-Override JARVIS_HF_IMAGE_SIZE gilt nur, wenn er in der erlaubten Liste steht."""
    override = (os.environ.get("JARVIS_HF_IMAGE_SIZE") or "").strip()
    if override in _HF_SIZES_ALL:
        return override
    w, h = max(1, int(width or 1)), max(1, int(height or 1))
    ratio = w / h
    if ratio >= 1.15:       # Landscape (Hero) → breitestes 16:9 zuerst
        return _HF_SIZES_LANDSCAPE[0]   # 2048x1152
    if ratio <= 0.87:       # Portrait
        return _HF_SIZES_PORTRAIT[0]    # 1152x2048
    return _HF_SIZES_SQUARE[0]          # 1536x1536


def _hf_poll(rid: str, key: str) -> dict:
    """Pollt den Status einer Higgsfield-Bildgenerierung. Probiert mehrere mögliche
    Status-Pfade (die Platform-API variiert) und liefert das erste 200-JSON. {} = nichts."""
    import urllib.request
    import json
    headers = {k: v for k, v in _hf_headers(key).items() if k != "Content-Type"}
    for path in (f"/v1/text2image/soul/{rid}", f"/requests/{rid}/status",
                 f"/v1/requests/{rid}", f"/requests/{rid}", f"/v1/generations/{rid}"):
        try:
            pr = urllib.request.Request(f"{_HIGGSFIELD_BASE}{path}", headers=headers)
            with urllib.request.urlopen(pr, timeout=15) as resp:
                d = json.loads(resp.read().decode())
            if isinstance(d, dict) and d:
                return d
        except Exception:
            continue
    return {}


def generate_image_higgsfield(prompt: str, output_dir: "Path | None" = None,
                              filename: str = "", width: int = 1280, height: int = 720,
                              enhance: "bool | None" = None) -> dict:
    """
    Bild via Higgsfield Soul (Cloud). Für schwache Hardware (CPU) gedacht, wenn lokale
    Generierung zu langsam ist. Wirft bei jedem Problem eine Exception — der Aufrufer
    fällt dann auf die nächste Quelle zurück. Die Enums prüft Higgsfield strikt: Größe wird
    über _hf_valid_size auf einen erlaubten Wert gemappt, der Payload steckt im `params`-Objekt
    (sonst HTTP 422 'params required' — war der Grund, warum kein Hero entstand).
    """
    import urllib.request
    import urllib.error
    import json

    key = _hf_key()
    if not key:
        raise ValueError("HIGGSFIELD_API_KEY fehlt in .env.")

    size = _hf_valid_size(width, height)
    quality = os.environ.get("JARVIS_HF_IMAGE_QUALITY", "1080p")
    # enhance_prompt lässt Higgsfield den Prompt umschreiben — das kann unsere strikte
    # No-Text-Anweisung aushebeln und Text/Logos ins Bild bringen. Für Hero-Bilder daher AUS
    # (enhance=False). Default global über JARVIS_HF_ENHANCE (Default "0").
    if enhance is None:
        enhance = (_env("JARVIS_HF_ENHANCE", "0") or "0").strip().lower() in ("1", "true", "yes", "ja")
    payload = {"params": {"prompt": prompt, "width_and_height": size,
                          "quality": quality, "batch_size": 1, "enhance_prompt": bool(enhance)}}

    t0 = time.time()
    req = urllib.request.Request(
        f"{_HIGGSFIELD_BASE}/v1/text2image/soul",
        data=json.dumps(payload).encode(), headers=_hf_headers(key), method="POST",
    )
    _mlog("info", "Higgsfield", f"Bild-Auftrag (Soul · {size}) · {prompt[:60]}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            d = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        _mlog("warn", "Higgsfield", f"Bild-POST {e.code}: {body[:200]}")
        raise RuntimeError(_hf_error_hint(e.code, body))   # z.B. 1010 / 403 not enough credits

    rid = (d.get("id") or d.get("request_id") or d.get("request_set_id")
           or ((d.get("jobs") or [{}])[0].get("id") if d.get("jobs") else None))
    if not rid:
        raise RuntimeError(f"Keine Higgsfield-request-id: {str(d)[:200]}")

    img_url = ""
    for _ in range(40):                      # ~2 Minuten (40 × 3s)
        time.sleep(3)
        pd = _hf_poll(str(rid), key)
        if not pd:
            continue
        st = (pd.get("status") or "").lower()
        if st in ("completed", "success", "done"):
            img_url = _hf_extract_image_url(pd)
            if img_url:
                break
        if st in ("failed", "error", "nsfw", "cancelled"):
            raise RuntimeError(f"Higgsfield-Status: {st}")
    if not img_url:
        raise TimeoutError("Higgsfield Bild-Timeout (2 Min ohne Ergebnis).")

    data = urllib.request.urlopen(
        urllib.request.Request(img_url, headers={"User-Agent": _BROWSER_UA}), timeout=120
    ).read()
    dest = output_dir if output_dir else WORKSPACE_IMAGES
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / (filename or f"hf_{time.strftime('%Y%m%d_%H%M%S')}.png")
    out.write_bytes(data)
    try:
        rel = out.relative_to(WORKSPACE_IMAGES)
        web_url = f"/workspace/media/images/{rel.as_posix()}"
    except ValueError:
        web_url = ""
    try:
        import logger as _lg
        _lg.activity("Higgsfield", "Bild generiert",
                     f"Soul · {prompt[:60]}", "🖼", "image")
        import cost_tracker as _ct
        _ct.track_higgsfield(_HF_IMAGE_CREDITS, "image_gen")
    except Exception:
        pass
    return {"path": str(out), "web_url": web_url, "model": "Higgsfield Soul",
            "prompt": prompt, "elapsed": round(time.time() - t0, 1)}


# ── OpenAI (ChatGPT) Bildgenerierung — gpt-image-1 ───────────────────────────
# Standard-Quelle für Hero-Bilder: hochwertige, fotorealistische Banner direkt aus
# der OpenAI-Cloud, unabhängig von der lokalen Hardware. Mit hartem TAGESLIMIT, damit
# die Kosten gedeckelt bleiben (JARVIS_OPENAI_IMAGE_DAILY_MAX).

_OPENAI_BASE        = "https://api.openai.com/v1/images/generations"
_OPENAI_USAGE_PATH  = _BASE / "data" / "openai_image_usage.json"


def _openai_key() -> str:
    """OpenAI-API-Key aus Umgebung oder .env (OPENAI_API_KEY, Fallback OPENAI_KEY)."""
    return (_env("OPENAI_API_KEY") or _env("OPENAI_KEY")).strip()


def openai_available() -> bool:
    return bool(_openai_key())


def _openai_quality() -> str:
    q = (_env("JARVIS_OPENAI_IMAGE_QUALITY", "medium") or "medium").strip().lower()
    return q if q in ("low", "medium", "high", "auto") else "medium"


def openai_daily_max() -> int:
    """Maximale OpenAI-Bilder pro Tag (Kostendeckel). 0 = deaktiviert."""
    try:
        return int(_env("JARVIS_OPENAI_IMAGE_DAILY_MAX", "30") or "30")
    except Exception:
        return 30


def _openai_today() -> str:
    return time.strftime("%Y-%m-%d")


def _openai_used_today() -> int:
    try:
        import json
        d = json.loads(_OPENAI_USAGE_PATH.read_text(encoding="utf-8"))
        return int(d.get("count", 0)) if d.get("date") == _openai_today() else 0
    except Exception:
        return 0


def _openai_bump() -> None:
    """Erhöht den Tageszähler (rollt bei Tageswechsel auf 0 zurück)."""
    try:
        import json
        used = _openai_used_today()
        _OPENAI_USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _OPENAI_USAGE_PATH.write_text(
            json.dumps({"date": _openai_today(), "count": used + 1}, ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        pass


def openai_quota_left() -> int:
    """Verbleibende OpenAI-Bilder heute (>=0). max=0 → 0 (deaktiviert)."""
    mx = openai_daily_max()
    if mx <= 0:
        return 0
    return max(0, mx - _openai_used_today())


# ── Hero-Bild-Tageslimit (Higgsfield-Abo-Budget schonen) ─────────────────────
# Das ~40 €-Higgsfield-Abo reicht für grob ~5 hochwertige Hero-Bilder pro Tag. Da der
# Nightbuilder 5 Seiten/Tag baut (je 1 Hero) und Re-Makeover das Hero NICHT neu erzeugt,
# passt ein hartes Tageslimit von 5 exakt und verhindert Budget-Überraschungen.
_HERO_USAGE_PATH = _BASE / "data" / "hero_image_usage.json"


def hero_daily_max() -> int:
    """Maximale Cloud-Hero-Bilder pro Tag (Abo-Budget). 0 = unbegrenzt."""
    try:
        return int(_env("JARVIS_HERO_DAILY_MAX", "5") or "5")
    except Exception:
        return 5


def _hero_used_today() -> int:
    try:
        import json
        d = json.loads(_HERO_USAGE_PATH.read_text(encoding="utf-8"))
        return int(d.get("count", 0)) if d.get("date") == time.strftime("%Y-%m-%d") else 0
    except Exception:
        return 0


def _hero_bump() -> None:
    """Erhöht den Hero-Tageszähler (rollt bei Tageswechsel auf 0 zurück)."""
    try:
        import json
        used = _hero_used_today()
        _HERO_USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _HERO_USAGE_PATH.write_text(
            json.dumps({"date": time.strftime("%Y-%m-%d"), "count": used + 1}, ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        pass


def hero_quota_left() -> int:
    """Verbleibende Cloud-Hero-Bilder heute. max<=0 → unbegrenzt (großer Wert)."""
    mx = hero_daily_max()
    if mx <= 0:
        return 1_000_000
    return max(0, mx - _hero_used_today())


# Branchen-Szenen-Lexikon: konkrete, fotografisch verwertbare Bildmotive je Gewerk.
# Macht den Hero-Prompt „krass genau" (echtes Werkzeug/echte Umgebung statt generisch),
# auch ohne ein KI-Modell zur Prompt-Verfeinerung. Key = Teilstring der Branche (lower).
_HERO_SCENES: dict[str, str] = {
    "dachdecker": "two roofers in clean safety harnesses installing crisp new clay roof tiles on a steep residential roof, blue sky, scaffolding, professional roofing tools",
    "dach":       "a freshly finished tiled roof of a German house seen from a flattering angle, gutters and ridge perfectly aligned, sunny sky",
    "maler":      "a painter in spotless white workwear rolling a smooth coat of warm paint on an interior wall, drop cloths, ladder, bright airy room",
    "lackier":    "a glossy freshly painted car body panel under studio light in a clean professional paint booth",
    "elektr":     "a focused electrician neatly wiring a modern distribution board, tidy cabling, multimeter, clean workshop light",
    "sanitär":    "a plumber fitting a sleek modern bathroom faucet, chrome fittings, clean tiled bathroom, professional tools",
    "heizung":    "a heating technician servicing a modern wall-mounted condensing boiler, clean utility room, professional gauges",
    "klima":      "a technician installing a sleek modern air-conditioning unit on a clean wall, tools laid out neatly",
    "garten":     "a landscaped German garden with freshly mown lawn, trimmed hedges and a tidy stone path, golden hour light",
    "gala":       "a freshly paved natural-stone patio with neat planting beds in a sunny residential garden",
    "kfz":        "a clean modern car repair workshop with a vehicle on a lift, organized tool wall, mechanic in clean uniform",
    "auto":       "a polished car in a spotless professional automotive workshop, dramatic light, organized tools",
    "friseur":    "a bright modern hair salon interior with stylish chairs, large mirrors and warm designer lighting",
    "kosmetik":   "a serene modern beauty studio with soft lighting, clean treatment bed and elegant minimalist decor",
    "bau":        "a tidy construction site with a crew in clean hi-vis and helmets reviewing plans, modern building shell, clear sky",
    "tischler":   "a craftsman in a sunlit woodworking workshop planing a solid oak board, wood shavings, hand tools on a clean bench",
    "schreiner":  "a craftsman in a sunlit woodworking workshop assembling fine furniture, fresh sawdust, organized hand tools",
    "gastro":     "an inviting modern restaurant interior with set tables and warm ambient lighting, ready for guests",
    "restaurant": "an elegant plated dish on a rustic wooden table in a warm restaurant setting, shallow depth of field",
    "bäcker":     "a rustic display of fresh artisan bread and pastries in a warm bakery, morning light",
    "reinigung":  "a spotless freshly cleaned modern interior, sunlight on streak-free glass, professional cleaning equipment tidy in frame",
    "fenster":    "freshly installed large modern windows in a bright room, clean frames, sunlight streaming in",
    "fliesen":    "a tiler setting large-format tiles in a flawless straight pattern, clean spacers and trowel, modern bathroom",
    "zimmerei":   "a timber roof truss being assembled by carpenters, fresh-cut beams, blue sky, professional tools",
    "metallbau":  "a welder in proper gear shaping a clean steel railing in a tidy metal workshop, sparks, organized tools",
    "umzug":      "a professional moving team in matching uniforms carefully carrying furniture into a clean modern van",
    "immobilie":  "a bright modern German home exterior with manicured front garden at golden hour, inviting and premium",
}


def _hero_scene(branche: str) -> str:
    """Konkretes Bildmotiv für die Branche (Lexikon) — sonst ein neutrales Premium-Motiv."""
    low = (branche or "").lower()
    for key, scene in _HERO_SCENES.items():
        if key in low:
            return scene
    return (f"an authentic, inviting workplace scene of a German {branche or 'local'} business "
            "with real tools and a tidy premium environment")


def hero_master_prompt(branche: str = "", name: str = "", stadt: str = "",
                       beschreibung: str = "", akzent: str = "") -> str:
    """Ausführlicher, auf den Lead angepasster Master-Prompt für ein professionelles,
    fotorealistisches Hero-Banner (kein Text, kein Logo). Nutzt das Branchen-Szenen-Lexikon
    (_HERO_SCENES) für ein konkretes Motiv — so wird der Prompt branchengenau statt generisch."""
    br    = (branche or "lokaler Betrieb").strip()
    ort   = (stadt or "Deutschland").strip()
    desc  = (beschreibung or "").strip()
    scene = _hero_scene(br)
    extra = f" Tailor the details to this specific business: {desc[:240]}." if desc else ""
    acc   = f" Subtle brand accent color {akzent} present in the scene (clothing/signage/props), never as text." if akzent else ""
    return (
        f"Ultra-realistic editorial commercial photograph — premium website hero banner for a "
        f"German {br} business in {ort}. Scene: {scene}.{extra} "
        "Shot on a full-frame camera (35mm f/1.8), natural bright daylight or warm golden-hour "
        "light, soft realistic shadows, shallow depth of field with creamy bokeh, cinematic color "
        "grading, high dynamic range, crisp tack-sharp focus, immaculate styling, award-winning "
        "advertising photography, magazine-grade quality. Real authentic people and genuine tools "
        "of this exact trade, candid professional moment, trustworthy and competent mood. Clean "
        "modern composition following rule of thirds, generous clean NEGATIVE SPACE on the LEFT "
        "third (an HTML headline is overlaid there later by code), uncluttered background. "
        "16:9 landscape orientation." + acc +
        " The image must be a PURE PHOTOGRAPH with ZERO graphics overlaid. ABSOLUTELY NO text, "
        "no words, no letters, no numbers, no captions, no signage with writing, no labels, no "
        "logos, no brand marks, no watermarks, no UI, no buttons, no posters, no banners with "
        "writing. No distorted hands, no extra limbs, no collage, no borders or frames. "
        "Photorealistic only. If any text would appear, leave that area empty instead."
    )


def _hero_prompt_inputs(branche, name, stadt, beschreibung, leistungen):
    leist = ", ".join(str(x.get("titel", "")).strip() if isinstance(x, dict) else str(x)
                      for x in (leistungen or [])[:5] if x)
    sysmsg = ("You are a world-class advertising art director writing a single prompt for a "
              "photorealistic text-to-image model (Higgsfield Soul). Output ONE English prompt "
              "line for a premium website hero banner photo. Be concrete and specific to the exact "
              "trade and scene, with camera/lens/light direction. CRITICAL: the image must contain "
              "ZERO text/words/letters/logos/watermarks and keep clean negative space on the LEFT "
              "third for an HTML headline overlay. 60-90 words. Answer with the prompt ONLY.")
    usr = (f"Business: {name or '(local business)'} — trade: {branche or 'local services'} — "
           f"city: {stadt or 'Germany'}.\nServices: {leist or '(general)'}\n"
           f"Owner description: {(beschreibung or '')[:240]}\n"
           f"Reference scene to build on: {_hero_scene(branche)}\n"
           "Write the precise hero-image prompt now.")
    return sysmsg, usr


def _finalize_hero_line(line: str, base: str) -> str:
    line = next((l.strip().strip('"').strip() for l in (line or "").splitlines() if l.strip()), "")
    if len(line) < 40:
        return base
    if "no text" not in line.lower():
        line += (" 16:9 landscape, photorealistic, cinematic, negative space on the left for an "
                 "HTML headline. Absolutely no text, no words, no letters, no logos, no watermarks.")
    return line[:900]


def hero_prompt_smart(branche: str = "", name: str = "", stadt: str = "",
                      beschreibung: str = "", akzent: str = "", leistungen: "list | None" = None) -> str:
    """Erzeugt einen PRÄZISEN Hero-Bild-Prompt. Philosophie „Claude plant den Prompt, Higgsfield
    baut das Bild": der Prompt wird per CLAUDE (günstiger Haiku-One-Shot) art-direktet, da das
    visuelle Aushängeschild Claude-Qualität verdient. Fällt auf das deterministische, sehr starke
    Master-Template zurück (Claude aus/limitiert) oder optional Ollama. Best-effort — nie ein Fehler."""
    base = hero_master_prompt(branche=branche, name=name, stadt=stadt,
                              beschreibung=beschreibung, akzent=akzent)
    sysmsg, usr = _hero_prompt_inputs(branche, name, stadt, beschreibung, leistungen)

    # 1) Claude-One-Shot (Standard) — klein & günstig (Haiku), echte Art-Direction.
    if _env("JARVIS_HERO_PROMPT_CLAUDE", "1") != "0":
        try:
            import anthropic
            import config
            key = config.get_api_key()
            if key:
                model = _env("JARVIS_HERO_PROMPT_MODEL", "claude-haiku-4-5-20251001")
                client = anthropic.Anthropic(api_key=key)
                # Prompt-Caching: der System-Block ist über ALLE Seiten identisch → als
                # ephemeren Cache markieren (kostet bei Wiederholung ~1/10).
                msg = client.messages.create(
                    model=model, max_tokens=320,
                    system=[{"type": "text", "text": sysmsg,
                             "cache_control": {"type": "ephemeral"}}],
                    messages=[{"role": "user", "content": usr}])
                try:
                    import cost_tracker
                    cost_tracker.track_message(model, msg, "hero_prompt", name)
                except Exception:
                    pass
                txt = "".join(getattr(b, "text", "") for b in msg.content
                              if getattr(b, "type", "") == "text")
                line = _finalize_hero_line(txt, base)
                if line != base:
                    return line
        except Exception as e:
            _mlog("warn", "Hero", f"Claude-Hero-Prompt nicht möglich ({type(e).__name__}) → Master-Template.")

    # 2) Optionaler Ollama-Fallback (nur wenn ausdrücklich aktiviert).
    if _env("JARVIS_HERO_PROMPT_LOCAL", "0") != "0":
        try:
            from scrapers._http import ask_ollama
            to = int(_env("JARVIS_HERO_PROMPT_TIMEOUT", "60") or "60")
            out = (ask_ollama(usr, system=sysmsg, timeout=to) or "").strip()
            return _finalize_hero_line(out, base)
        except Exception:
            return base

    # 3) Deterministisches Master-Template (kostenlos, sehr stark).
    return base


def generate_image_openai(prompt: str, output_dir: "Path | None" = None,
                          filename: str = "", width: int = 1536, height: int = 1024,
                          quality: str = "", name: str = "") -> dict:
    """Bild via OpenAI gpt-image-1 (Cloud). Respektiert das Tageslimit
    (JARVIS_OPENAI_IMAGE_DAILY_MAX) und wirft sonst eine Exception — der Aufrufer
    fällt dann auf die nächste Quelle (Higgsfield/lokal) zurück."""
    import base64
    import json
    import urllib.request
    import urllib.error

    key = _openai_key()
    if not key:
        raise ValueError("OPENAI_API_KEY fehlt in .env.")
    if openai_quota_left() <= 0:
        raise RuntimeError(
            f"OpenAI-Tageslimit erreicht ({_openai_used_today()}/{openai_daily_max()}) — "
            "Kostendeckel. Morgen wieder, oder JARVIS_OPENAI_IMAGE_DAILY_MAX erhöhen.")

    # Seitenverhältnis → von gpt-image-1 unterstützte Größe.
    if width > height:
        size = "1536x1024"
    elif height > width:
        size = "1024x1536"
    else:
        size = "1024x1024"
    qual = (quality or _openai_quality())

    payload = {"model": "gpt-image-1", "prompt": prompt, "size": size, "n": 1}
    if qual in ("low", "medium", "high", "auto"):
        payload["quality"] = qual

    t0  = time.time()
    req = urllib.request.Request(
        _OPENAI_BASE, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            d = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"OpenAI {e.code}: {body}")

    try:
        b64 = d["data"][0]["b64_json"]
        data_bytes = base64.b64decode(b64)
    except Exception:
        # Manche Antworten liefern eine URL statt b64 → herunterladen.
        url = (d.get("data") or [{}])[0].get("url", "")
        if not url:
            raise RuntimeError(f"OpenAI-Antwort ohne Bild: {str(d)[:200]}")
        data_bytes = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "JARVIS/1.0"}),
            timeout=120).read()

    dest = output_dir if output_dir else WORKSPACE_IMAGES
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / (filename or f"openai_{time.strftime('%Y%m%d_%H%M%S')}.png")
    out.write_bytes(data_bytes)

    _openai_bump()   # Tageszähler erst NACH Erfolg erhöhen
    try:
        rel = out.relative_to(WORKSPACE_IMAGES)
        web_url = f"/workspace/media/images/{rel.as_posix()}"
    except ValueError:
        web_url = ""
    try:
        import logger as _lg
        _lg.activity("OpenAI", "Hero-Bild generiert",
                     f"gpt-image-1 · {qual} · {prompt[:50]}", "🖼", "image")
        import cost_tracker as _ct
        _ct.track_openai_image(qual, "image_gen", name)
    except Exception:
        pass
    return {"path": str(out), "web_url": web_url, "model": "OpenAI gpt-image-1",
            "prompt": prompt, "elapsed": round(time.time() - t0, 1)}


def higgsfield_mcp_available() -> bool:
    """True, wenn der Higgsfield-MCP-Client angemeldet ist (nutzt die ABO-Credits)."""
    try:
        import higgsfield_mcp
        return higgsfield_mcp.available()
    except Exception:
        return False


def hero_engine() -> str:
    """Welche Engine liefert Hero-Bilder? JARVIS_HERO_ENGINE: higgsfield (Default — Sirs Abo;
    bevorzugt den MCP-Weg = Abo-Credits, fällt auf API-Key/OpenAI zurück) | higgsfield_mcp
    (nur Abo-MCP) | higgsfield_only (nur API-Key) | openai | local | auto. Steuert die
    Auto-Pipeline (Build + Makeover); im Medien-Reiter bleibt jede Engine manuell wählbar."""
    e = (_env("JARVIS_HERO_ENGINE", "higgsfield") or "higgsfield").strip().lower()
    valid = ("higgsfield", "higgsfield_mcp", "higgsfield_only", "openai", "local", "auto")
    return e if e in valid else "higgsfield"


def generate_hero_cloud(prompt: str, output_dir: "Path | None" = None, filename: str = "hero.png",
                        width: int = 1536, height: int = 1024, name: str = "") -> dict:
    """Hero-Bild über eine CLOUD-Engine gemäß JARVIS_HERO_ENGINE (Default Higgsfield = Abo).
    OpenAI wird NUR genutzt, wenn ausdrücklich gewählt (kostet extra). Gibt das Engine-Ergebnis
    inkl. {'engine': ...}. Wirft, wenn keine Cloud-Engine ein Bild liefert (Aufrufer fällt dann
    auf Lokal/Farbverlauf zurück)."""
    # Higgsfield bleibt Standard (Sirs Abo). Bevorzugt wird der MCP-Weg (nutzt die ABO-Credits),
    # dann der Platform-API-Key (eigener Topf), dann OpenAI (gedeckelt) — so steht eine Seite NIE
    # ohne echten Hero da. 'higgsfield_mcp' = nur Abo-MCP, 'higgsfield_only' = nur API-Key.
    order = {
        "higgsfield":      ["higgsfield_mcp", "higgsfield", "openai"],
        "higgsfield_mcp":  ["higgsfield_mcp"],
        "higgsfield_only": ["higgsfield"],
        "openai":          ["openai", "higgsfield_mcp", "higgsfield"],
        "local":           [],                  # 'local' → keine Cloud (Aufrufer rendert lokal)
        "auto":            ["higgsfield_mcp", "higgsfield", "openai"],
    }.get(hero_engine(), ["higgsfield_mcp", "higgsfield", "openai"])
    # Hartes Tageslimit fürs Abo-Budget (Default 5). Erschöpft → klar werfen, der Aufrufer
    # (_ensure_hero) behält das bestehende Bild bzw. den Gradient.
    if hero_quota_left() <= 0:
        raise RuntimeError(f"Hero-Tageslimit erreicht ({_hero_used_today()}/{hero_daily_max()}) "
                           "— Budget-Deckel. Morgen wieder oder JARVIS_HERO_DAILY_MAX erhöhen.")
    errs: list[str] = []
    for e in order:
        try:
            if e == "higgsfield_mcp" and higgsfield_mcp_available():
                import higgsfield_mcp
                ar = higgsfield_mcp._aspect_for(width, height)
                dest = Path(output_dir) if output_dir else WORKSPACE_IMAGES
                fpath = dest / (filename or "hero.png")
                r = higgsfield_mcp.generate_image(prompt, fpath, aspect_ratio=ar)
                try:
                    rel = Path(r["path"]).relative_to(WORKSPACE_IMAGES)
                    web_url = f"/workspace/media/images/{rel.as_posix()}"
                except Exception:
                    web_url = ""
                _hero_bump()
                return {"path": r["path"], "web_url": web_url,
                        "model": "Higgsfield Soul (MCP/Abo)", "prompt": prompt,
                        "engine": "higgsfield_mcp"}
            if e == "higgsfield" and higgsfield_available():
                r = generate_image_higgsfield(prompt, output_dir=output_dir,
                                              filename=filename, width=width, height=height,
                                              enhance=False)
                r["engine"] = "higgsfield"
                _hero_bump()
                return r
            if e == "openai" and openai_available() and openai_quota_left() > 0:
                r = generate_image_openai(prompt, output_dir=output_dir, filename=filename,
                                          width=width, height=height, name=name)
                r["engine"] = "openai"
                _hero_bump()
                return r
        except Exception as ex:
            errs.append(f"{e}:{type(ex).__name__}")
            _mlog("warn", "Hero", f"{e}-Hero fehlgeschlagen: {str(ex)[:140]}")
    raise RuntimeError("Keine Cloud-Hero-Engine erfolgreich: " + (", ".join(errs) or "nichts konfiguriert"))


def get_status() -> dict:
    """Gibt Konfigurationsstatus zurück."""
    img_key = get_active_image_model()
    vid_key = get_active_video_model()
    hf_key_set = bool(_hf_key())
    hw = hardware_info()
    auto_key = best_image_model()
    cpu = hw["device"] == "cpu"
    # Ehrliche Empfehlung fürs Frontend: was lohnt sich lokal auf dieser Hardware?
    if cpu:
        hinweis = (f"CPU · {hw['ram_gb']:.0f} GB RAM — Bilder lokal mit SD-Turbo (schnell). "
                   "Videos lokal nicht praktikabel → Higgsfield Cloud nutzen.")
    else:
        hinweis = f"GPU {hw['gpu_name']} ({hw['vram_gb']:.0f} GB) — Bilder & Videos lokal in hoher Qualität."
    return {
        "image_model":        IMAGE_MODELS.get(img_key, {}).get("name", img_key),
        "image_model_key":    img_key,
        "video_model":        VIDEO_MODELS.get(vid_key, {}).get("name", vid_key),
        "video_model_key":    vid_key,
        "diffusers_ok":       _check_diffusers(),
        "higgsfield_api_key": hf_key_set,
        "higgsfield_mcp":     higgsfield_mcp_available(),
        "openai_image":       openai_available(),
        "openai_quota_left":  openai_quota_left(),
        "openai_daily_max":   openai_daily_max(),
        "openai_used_today":  _openai_used_today(),
        # Hardware + hardware-gewähltes Modell für Hero/Mockup (System-Auto-Wahl)
        "device":             hw["device"],
        "gpu_name":           hw["gpu_name"],
        "vram_gb":            hw["vram_gb"],
        "ram_gb":             hw["ram_gb"],
        "video_local_ok":     not cpu,        # lokales Video nur mit GPU sinnvoll
        "empfehlung":         hinweis,
        "auto_image_model":   IMAGE_MODELS.get(auto_key, {}).get("name", auto_key),
        "auto_image_model_key": auto_key,
        "perf_tier":          _perf_tier(),
        "perf_summary":       _perf_summary(),
    }


def _perf_tier() -> str:
    try:
        import hardware_profile
        return hardware_profile.tier()
    except Exception:
        return ""


def _perf_summary() -> str:
    try:
        import hardware_profile
        return hardware_profile.summary()
    except Exception:
        return ""


def _check_diffusers() -> bool:
    try:
        import diffusers, torch  # noqa: F401
        return True
    except ImportError:
        return False
