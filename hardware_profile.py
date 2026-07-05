"""
hardware_profile.py — zentrales Leistungsprofil.

Passt Bild-/Medien-/Nightly-Parameter automatisch an die Hardware an (CPU-Kerne,
RAM, GPU/VRAM): auf einem starken Server skaliert alles hoch (mehr Parallelität,
mehr Schritte, mehr Bilder), auf einem schwachen Laptop wird gedrosselt.

Eine Quelle der Wahrheit — von media_engine, media_queue, website_improve und
auto_builder genutzt. Per .env override: JARVIS_PERF_TIER=server|workstation|desktop|
laptop|low.
"""
from __future__ import annotations

import functools
import os

# Parameter je Leistungsstufe.
#   image_steps               — Diffusion-Schritte (Qualität ↔ Tempo)
#   improve_images            — Bilder, die die Verbesserung lokal generiert
#   media_parallel            — gleichzeitige CLOUD-Medien-Jobs (Higgsfield; keine lokale GPU nötig)
#   nightly_improve_per_cycle — wie viele Seiten je Nightly-Runde verbessert werden
_TABLE = {
    "server":      {"image_steps": 40, "improve_images": 6, "media_parallel": 4, "nightly_improve_per_cycle": 3},
    "workstation": {"image_steps": 32, "improve_images": 5, "media_parallel": 3, "nightly_improve_per_cycle": 2},
    "desktop":     {"image_steps": 26, "improve_images": 4, "media_parallel": 2, "nightly_improve_per_cycle": 1},
    "laptop":      {"image_steps": 4,  "improve_images": 3, "media_parallel": 2, "nightly_improve_per_cycle": 1},
    "low":         {"image_steps": 2,  "improve_images": 2, "media_parallel": 1, "nightly_improve_per_cycle": 1},
}


@functools.lru_cache(maxsize=1)
def detect() -> dict:
    """Roh-Hardware (gecacht). cores/ram_gb/device/vram_gb/gpu_name.

    GPU-Erkennung bevorzugt media_engine (torch-basiert — die für DIESEN Python-Prozess
    tatsächlich nutzbare GPU, berücksichtigt CUDA-Treiber-/Toolkit-Kompatibilität). Das ist
    bewusst NICHT dasselbe wie hardware.py::gpu_info() (nvidia-smi-basiert): hardware.py muss
    schon VOR der torch/diffusers-Installation funktionieren (install.py entscheidet damit erst,
    ob der CUDA-Build installiert wird) — media_engine kann zu diesem Zeitpunkt noch gar nicht
    importiert werden. Fällt media_engine (noch) nicht verfügbar/importierbar, wird darum auf
    hardware.gpu_info() zurückgefallen, statt eine vorhandene GPU fälschlich zu übersehen."""
    cores = os.cpu_count() or 4
    ram = 0.0
    device, vram, gpu = "cpu", 0.0, ""
    try:
        import hardware
        ram = float(hardware.ram_gb())
    except Exception:
        pass

    got_gpu_from_media_engine = False
    try:
        import media_engine
        hw = media_engine.hardware_info()
        device = hw.get("device", "cpu")
        vram = float(hw.get("vram_gb", 0.0) or 0.0)
        gpu = hw.get("gpu_name", "")
        got_gpu_from_media_engine = True
        if not ram:
            ram = float(hw.get("ram_gb", 0.0) or 0.0)
    except Exception:
        pass

    if not got_gpu_from_media_engine:
        # media_engine (torch) noch nicht installiert/importierbar — nvidia-smi-Fallback,
        # damit eine vorhandene GPU nicht fälschlich als "keine GPU" gewertet wird.
        try:
            import hardware as _hw
            name, vram_gb = _hw.gpu_info()
            if vram_gb > 0:
                device, vram, gpu = "cuda", vram_gb, name
        except Exception:
            pass

    return {"cores": cores, "ram_gb": round(ram, 1), "device": device,
            "vram_gb": round(vram, 1), "gpu_name": gpu}


def tier() -> str:
    """Leistungsstufe aus der Hardware ableiten (oder JARVIS_PERF_TIER aus .env)."""
    ov = os.environ.get("JARVIS_PERF_TIER", "").strip().lower()
    if ov in _TABLE:
        return ov
    h = detect()
    gpu = h["device"] == "cuda"
    vram, cores, ram = h["vram_gb"], h["cores"], h["ram_gb"]
    if (gpu and vram >= 20) or (cores >= 24 and ram >= 48):
        return "server"
    if (gpu and vram >= 10) or (cores >= 12 and ram >= 24):
        return "workstation"
    if (gpu and vram >= 6) or (cores >= 6 and ram >= 16):
        return "desktop"
    if ram >= 8:
        return "laptop"
    return "low"


def profile() -> dict:
    """Vollständiges Profil: Hardware + abgeleitete Parameter."""
    h = detect()
    t = tier()
    p = dict(_TABLE[t])
    p.update({
        "tier": t,
        "device": h["device"],
        "cores": h["cores"],
        "ram_gb": h["ram_gb"],
        "vram_gb": h["vram_gb"],
        "gpu_name": h["gpu_name"],
        "gpu": h["device"] != "cpu",
        "video_local_ok": h["device"] == "cuda",
    })
    return p


def get(key: str, default=None):
    """Einzelnen Profil-Wert holen (bequem für Aufrufer)."""
    return profile().get(key, default)


def summary() -> str:
    """Menschlich lesbar, bewusst ASCII-only (wird auch in cp1252-Konsolen gedruckt)."""
    p = profile()
    gpu = f"{p['gpu_name']} ({p['vram_gb']:.0f} GB)" if p["gpu"] else "keine GPU"
    return (f"Stufe {p['tier'].upper()} | {p['cores']} Kerne | {p['ram_gb']:.0f} GB RAM | {gpu} "
            f"-> {p['improve_images']} Bilder/Verbesserung, {p['media_parallel']}x Cloud-parallel, "
            f"{p['nightly_improve_per_cycle']} Seite(n)/Nightly-Runde")
