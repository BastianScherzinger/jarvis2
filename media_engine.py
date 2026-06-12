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

_BASE = Path(__file__).parent
WORKSPACE_IMAGES = _BASE / "workspace" / "media" / "images"
WORKSPACE_VIDEOS = _BASE / "workspace" / "media" / "videos"
for _d in [WORKSPACE_IMAGES, WORKSPACE_VIDEOS]:
    _d.mkdir(parents=True, exist_ok=True)


# ── Modell-Katalog ───────────────────────────────────────────────────────────

IMAGE_MODELS: dict[str, dict] = {
    "sdxl": {
        "hf_id":     "stabilityai/stable-diffusion-xl-base-1.0",
        "name":      "Stable Diffusion XL",
        "pipeline":  "StableDiffusionXLPipeline",
        "size_gb":   6.5,
        "min_vram":  8,
        "default_w": 1024,
        "default_h": 1024,
        "supports_neg": True,
        "gated":     False,
        "desc":      "Empfohlen: hohe Qualität, 1024×1024, offen (kein Token nötig)",
    },
    "sd21": {
        "hf_id":     "stabilityai/stable-diffusion-2-1",
        "name":      "Stable Diffusion 2.1",
        "pipeline":  "StableDiffusionPipeline",
        "size_gb":   2.5,
        "min_vram":  4,
        "default_w": 768,
        "default_h": 768,
        "supports_neg": True,
        "gated":     False,
        "desc":      "Leicht & schnell, ab 4 GB — gut für schwächere Hardware, offen",
    },
    "flux-schnell": {
        "hf_id":     "black-forest-labs/FLUX.1-schnell",
        "name":      "FLUX.1 Schnell (Token nötig)",
        "pipeline":  "FluxPipeline",
        "size_gb":   15,
        "min_vram":  8,
        "default_w": 1024,
        "default_h": 1024,
        "supports_neg": False,
        "gated":     True,
        "desc":      "Beste Qualität — GESPERRT: Lizenz auf huggingface.co akzeptieren + HF_TOKEN in .env",
    },
}

VIDEO_MODELS: dict[str, dict] = {
    "wan-1.3b": {
        "hf_id":     "Wan-AI/Wan2.1-T2V-1.3B",
        "name":      "Wan 2.1 T2V 1.3B",
        "size_gb":   2.7,
        "min_vram":  8,
        "default_frames": 25,
        "default_w": 832,
        "default_h": 480,
        "desc":      "Text-to-Video 480p, ~2 Minuten je Frame",
    },
}

ALL_MODELS: dict[str, dict] = {**IMAGE_MODELS, **VIDEO_MODELS}


# ── Konfiguration aus .env ───────────────────────────────────────────────────

def get_active_image_model() -> str:
    """Liest JARVIS_IMAGE_MODEL aus .env. Default: sd21."""
    content = (_BASE / ".env").read_text(encoding="utf-8", errors="replace") if (_BASE / ".env").exists() else ""
    m = re.search(r"JARVIS_IMAGE_MODEL=(.+)", content)
    return m.group(1).strip() if m else "sd21"


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

    # Speicher sparen auf schwacher Hardware
    if dev == "cpu":
        try: pipe.enable_attention_slicing()
        except Exception: pass
    elif dev == "cuda":
        try: pipe.enable_xformers_memory_efficient_attention()
        except Exception: pass

    _cache[model_key] = pipe
    return pipe


def _load_video_pipe(model_key: str):
    if model_key in _cache:
        return _cache[model_key]

    from diffusers import WanPipeline
    import torch

    if model_key not in VIDEO_MODELS:
        raise ValueError(f"Unbekanntes Videomodell: '{model_key}'. Verfügbar: {list(VIDEO_MODELS)}")

    m         = VIDEO_MODELS[model_key]
    dev, dt   = _device_dtype()
    pipe      = WanPipeline.from_pretrained(m["hf_id"], torch_dtype=dt)
    pipe      = pipe.to(dev)

    if dev == "cuda":
        try: pipe.enable_model_cpu_offload()
        except Exception: pass

    _cache[model_key] = pipe
    return pipe


# ── Öffentliche API ──────────────────────────────────────────────────────────

def _open_image_model() -> str:
    """Erstes offenes (nicht gesperrtes) Bildmodell — Fallback für gated Modelle."""
    for k, m in IMAGE_MODELS.items():
        if not m.get("gated"):
            return k
    return "sdxl"


def generate_image(
    prompt: str,
    model_key: str | None = None,
    negative_prompt: str = "blurry, low quality, watermark, text, deformed, ugly, bad anatomy",
    steps: int = 25,
    width: int | None = None,
    height: int | None = None,
) -> dict:
    """
    Generiert ein Bild. Gibt dict zurück:
      {'path': str, 'web_url': str, 'model': str, 'prompt': str, 'elapsed': float}
    """
    key = model_key or get_active_image_model()
    m   = IMAGE_MODELS.get(key)
    if m is None:
        raise ValueError(f"Bildmodell '{key}' nicht bekannt. Verfügbar: {list(IMAGE_MODELS)}")

    # Gesperrtes Modell (z.B. FLUX) ohne HF-Token → automatisch auf ein offenes
    # Modell ausweichen, statt den User mit einem Fehler zu blockieren.
    if m.get("gated") and not _hf_token():
        fallback = _open_image_model()
        if fallback and fallback != key:
            key = fallback
            m   = IMAGE_MODELS[key]

    w    = width  or m["default_w"]
    h    = height or m["default_h"]
    t0   = time.time()
    pipe = _load_image_pipe(key)

    kwargs: dict = {
        "prompt":              prompt,
        "num_inference_steps": min(max(steps, 1), 80),
        "width":               w,
        "height":              h,
    }
    if m["supports_neg"]:
        kwargs["negative_prompt"] = negative_prompt

    result  = pipe(**kwargs)
    image   = result.images[0]
    ts      = time.strftime("%Y%m%d_%H%M%S")
    out     = WORKSPACE_IMAGES / f"img_{ts}.png"
    image.save(str(out))

    return {
        "path":    str(out),
        "web_url": f"/workspace/media/images/{out.name}",
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
    content = (_BASE / ".env").read_text(encoding="utf-8", errors="replace") if (_BASE / ".env").exists() else ""
    m = re.search(r"HIGGSFIELD_API_KEY=(.+)", content)
    key = m.group(1).strip() if m else ""
    return key or os.environ.get("HIGGSFIELD_API_KEY", "")


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

    headers_json = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    headers_get = {"Authorization": f"Bearer {api_key}"}

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


def get_status() -> dict:
    """Gibt Konfigurationsstatus zurück."""
    img_key = get_active_image_model()
    vid_key = get_active_video_model()
    hf_key_set = bool(_hf_key())
    return {
        "image_model":        IMAGE_MODELS.get(img_key, {}).get("name", img_key),
        "image_model_key":    img_key,
        "video_model":        VIDEO_MODELS.get(vid_key, {}).get("name", vid_key),
        "video_model_key":    vid_key,
        "diffusers_ok":       _check_diffusers(),
        "higgsfield_api_key": hf_key_set,
    }


def _check_diffusers() -> bool:
    try:
        import diffusers, torch  # noqa: F401
        return True
    except ImportError:
        return False
