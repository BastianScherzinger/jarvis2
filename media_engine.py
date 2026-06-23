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
    return {
        "path":    str(out),
        "web_url": web_url,
        "model":   m["name"],
        "prompt":  prompt,
        "elapsed": round(time.time() - t0, 1),
    }


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
    if backend == "higgsfield" or (backend != "local" and on_cpu):
        hf_key = _hf_key()
        if hf_key:
            # Automatischer Cloud-Weg — kein Fehler mehr, das Video entsteht via Higgsfield.
            hf_model = os.environ.get("JARVIS_HIGGSFIELD_VIDEO_MODEL", "dop-lite")
            return generate_video_higgsfield(prompt, model=hf_model)
        if backend == "higgsfield":
            raise RuntimeError(
                "Video-Backend 'higgsfield' gewählt, aber HIGGSFIELD_API_KEY fehlt in der "
                ".env. Format: HIGGSFIELD_API_KEY=KEY_ID:KEY_SECRET  "
                "(Key unter https://cloud.higgsfield.ai/api-keys erstellen).")
        # auto + CPU + kein Higgsfield-Key
        raise RuntimeError(
            f"Kein GPU ({hw['device']}) und kein Higgsfield-Key — Video nicht möglich. "
            "Lösung: HIGGSFIELD_API_KEY=ID:SECRET in die .env eintragen, "
            "dann läuft Video automatisch über die Higgsfield Cloud (dop-lite, 3 Credits).")

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
    return {
        "path":    str(out),
        "web_url": f"/workspace/media/videos/{out.name}",
        "model":   m["name"],
        "prompt":  prompt,
        "elapsed": round(time.time() - t0, 1),
    }


# ── Higgsfield.ai Cloud API ──────────────────────────────────────────────────

_HIGGSFIELD_BASE = "https://platform.higgsfield.ai"

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

    headers_json = _hf_headers(api_key)                      # 'Key id:secret' oder 'Bearer key'
    headers_get  = {"Authorization": headers_json["Authorization"]}

    model = model if model in HIGGSFIELD_MODELS else "dop-lite"

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
        raise RuntimeError(f"Higgsfield API Fehler {e.code}: {body[:300]}")

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
    dl_req = urllib.request.Request(video_url, headers={"User-Agent": "JARVIS/1.0"})
    with urllib.request.urlopen(dl_req, timeout=120) as resp:
        video_bytes = resp.read()

    ts  = time.strftime("%Y%m%d_%H%M%S")
    out = WORKSPACE_VIDEOS / f"higgsfield_{ts}.mp4"
    out.write_bytes(video_bytes)

    return {
        "path":    str(out),
        "web_url": f"/workspace/media/videos/{out.name}",
        "model":   HIGGSFIELD_MODELS.get(model, {}).get("name", model),
        "prompt":  prompt,
        "gen_id":  gen_id,
        "elapsed": round(time.time() - t0, 1),
    }


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
    return {"Authorization": auth, "Content-Type": "application/json"}


def higgsfield_available() -> bool:
    return bool(_hf_key())


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


def generate_image_higgsfield(prompt: str, output_dir: "Path | None" = None,
                              filename: str = "", width: int = 1280, height: int = 720) -> dict:
    """
    Bild via Higgsfield Soul (Cloud). Für schwache Hardware (CPU) gedacht, wenn lokale
    Generierung zu langsam ist. Wirft bei jedem Problem eine Exception — der Aufrufer
    fällt dann auf die lokale Generierung zurück. Enums sind per .env überschreibbar
    (JARVIS_HF_IMAGE_SIZE, JARVIS_HF_IMAGE_QUALITY), da Higgsfield sie strikt prüft.
    """
    import urllib.request
    import urllib.error
    import json

    key = _hf_key()
    if not key:
        raise ValueError("HIGGSFIELD_API_KEY fehlt in .env.")

    size = os.environ.get("JARVIS_HF_IMAGE_SIZE") or ("1536x864" if width >= height else "864x1536")
    quality = os.environ.get("JARVIS_HF_IMAGE_QUALITY", "1080p")
    payload = {"prompt": prompt, "width_and_height": size,
               "quality": quality, "batch_size": "1", "enhance_prompt": True}

    t0 = time.time()
    req = urllib.request.Request(
        f"{_HIGGSFIELD_BASE}/v1/text2image/soul",
        data=json.dumps(payload).encode(), headers=_hf_headers(key), method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            d = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Higgsfield {e.code}: {body}")   # z.B. 402/insufficient credits

    rid = (d.get("id") or d.get("request_id") or d.get("request_set_id")
           or ((d.get("jobs") or [{}])[0].get("id") if d.get("jobs") else None))
    if not rid:
        raise RuntimeError(f"Keine Higgsfield-request-id: {str(d)[:200]}")

    img_url = ""
    for _ in range(40):                      # ~2 Minuten (40 × 3s)
        time.sleep(3)
        try:
            pr = urllib.request.Request(f"{_HIGGSFIELD_BASE}/requests/{rid}/status",
                                        headers=_hf_headers(key))
            with urllib.request.urlopen(pr, timeout=15) as resp:
                pd = json.loads(resp.read().decode())
        except Exception:
            continue
        st = (pd.get("status") or "").lower()
        if st in ("completed", "success", "done"):
            img_url = _hf_extract_image_url(pd)
            break
        if st in ("failed", "error", "nsfw", "cancelled"):
            raise RuntimeError(f"Higgsfield-Status: {st}")
    if not img_url:
        raise TimeoutError("Higgsfield Bild-Timeout (2 Min ohne Ergebnis).")

    data = urllib.request.urlopen(
        urllib.request.Request(img_url, headers={"User-Agent": "JARVIS/1.0"}), timeout=120
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
    return {"path": str(out), "web_url": web_url, "model": "Higgsfield Soul",
            "prompt": prompt, "elapsed": round(time.time() - t0, 1)}


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
