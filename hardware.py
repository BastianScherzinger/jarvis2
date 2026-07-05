"""
Hardware-Erkennung + lokale-KI-Profile.

Erkennt RAM und (NVIDIA-)GPU/VRAM und empfiehlt das optimale Ollama-Modell —
abgestuft vom sparsamen i7-Laptop bis zur Alienware-Workstation. Keine externen
Abhängigkeiten: RAM via ctypes/os, GPU via nvidia-smi, Ollama via urllib.
"""
from __future__ import annotations
import json
import os
import subprocess
import urllib.request


# ── Profile (vom kleinsten zum größten Modell) ───────────────────────────────
# 'min_cap' = benötigte Kapazität in GB (VRAM bei dGPU, sonst RAM).
PROFILES = [
    {"key": "mini",       "name": "Mini",            "model": "llama3.2:1b",
     "size_gb": 1.3, "min_cap": 4,
     "desc": "Notlösung für sehr schwache Geräte — schnell, aber einfache Texte"},
    {"key": "sparsam",    "name": "Sparsam",         "model": "qwen2.5:3b",
     "size_gb": 1.9, "min_cap": 8,
     "desc": "8-GB-Laptop — flott, brauchbare Bewertungen"},
    {"key": "laptop",     "name": "Laptop-Top",      "model": "qwen2.5:7b",
     "size_gb": 4.7, "min_cap": 12,
     "desc": "i7 HP/Dell (16 GB) — beste Wahl für Laptops: gute deutsche Texte"},
    {"key": "performance","name": "Performance",     "model": "qwen2.5:14b",
     "size_gb": 9.0, "min_cap": 20,
     "desc": "Starke GPU / 32 GB RAM — deutlich präzisere Analysen"},
    {"key": "alienware",  "name": "Alienware",       "model": "qwen2.5:32b",
     "size_gb": 20.0, "min_cap": 22,
     "desc": "Alienware/RTX (24 GB VRAM) — Top-Qualität, nahe an Cloud-Niveau"},
    {"key": "max",        "name": "Maximum",         "model": "llama3.3:70b",
     "size_gb": 43.0, "min_cap": 44,
     "desc": "Workstation (64 GB+ / 48 GB VRAM) — höchste lokale Qualität"},
]

_BY_KEY = {p["key"]: p for p in PROFILES}


# ── RAM ──────────────────────────────────────────────────────────────────────

def ram_gb() -> float:
    """Gesamter Arbeitsspeicher in GB (plattformübergreifend, ohne psutil)."""
    # Windows via ctypes
    try:
        import ctypes

        class _MEMSTAT(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = _MEMSTAT()
        stat.dwLength = ctypes.sizeof(stat)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return round(stat.ullTotalPhys / (1024 ** 3), 1)
    except Exception:
        pass
    # POSIX
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024 ** 3), 1)
    except Exception:
        return 0.0


# ── Bewertungs-Parallelität (RAM-basiert) ────────────────────────────────────

def eval_lanes(ram: "float | None" = None) -> int:
    """Anzahl paralleler Bewertungs-Lanes (Analyse → Recherche → Scoring), RAM-basiert.

    Jede Lane fährt eine eigene, gleichzeitige Ollama-Scoring-Inferenz — das ist der
    eigentliche Flaschenhals der Lead→Webseite-Pipeline. Mehr Lanes = die gefundenen Leads
    werden echt parallel durch die 3-Agenten-Kette geschoben und im Scoring gesammelt, also
    entsprechend schneller. Der Speicherbedarf skaliert mit den Lanes (KV-Cache je Ollama-Slot),
    darum die Bindung an den RAM.

        >= 64 GB → 5 Lanes,  >= 32 GB → 3,  >= 16 GB → 2,  sonst 1.

    Override per .env: JARVIS_EVAL_LANES (feste Zahl). Bewusst leichtgewichtig (nur ram_gb,
    kein torch/media_engine-Import) — wird sehr früh von scrapers/_http importiert."""
    ov = os.environ.get("JARVIS_EVAL_LANES", "").strip()
    if ov:
        try:
            return max(1, int(ov))
        except (ValueError, TypeError):
            pass
    if ram is None:
        try:
            ram = ram_gb()
        except Exception:
            ram = 0.0
    if ram >= 64:
        return 5
    if ram >= 32:
        return 3
    if ram >= 16:
        return 2
    return 1


# ── GPU (NVIDIA) ─────────────────────────────────────────────────────────────

def gpu_info() -> tuple[str, float]:
    """(GPU-Name, VRAM in GB) via nvidia-smi. ('', 0.0) wenn keine NVIDIA-GPU."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=6,
        )
        if out.returncode == 0 and out.stdout.strip():
            line = out.stdout.strip().splitlines()[0]
            name, mem = [x.strip() for x in line.split(",")[:2]]
            return name, round(float(mem) / 1024, 1)   # MB → GB
    except Exception:
        pass
    return "", 0.0


# ── Ollama: installierte Modelle ─────────────────────────────────────────────

def installed_models() -> list[str]:
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read())
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except Exception:
        return []


# ── Erkennung + Empfehlung ───────────────────────────────────────────────────

def detect() -> dict:
    ram = ram_gb()
    gpu_name, vram = gpu_info()
    has_gpu = vram >= 6          # erst ab ~6 GB VRAM sinnvoll für LLMs
    cap = vram if has_gpu else ram
    return {
        "ram_gb": ram,
        "gpu_name": gpu_name,
        "vram_gb": vram,
        "has_gpu": has_gpu,
        "kapazitaet_gb": round(cap, 1),
    }


def recommend(hw: dict | None = None) -> dict:
    """Empfohlenes Profil anhand der Kapazität (VRAM bei dGPU, sonst RAM).
    Ohne dedizierte GPU wird vorsichtiger empfohlen (CPU-Inferenz ist langsam)."""
    hw = hw or detect()
    cap = hw["kapazitaet_gb"]
    has_gpu = hw["has_gpu"]

    if has_gpu:
        if   cap >= 44: key = "max"
        elif cap >= 22: key = "alienware"
        elif cap >= 20: key = "performance"
        elif cap >= 10: key = "performance"
        elif cap >= 6:  key = "laptop"
        else:           key = "sparsam"
    else:  # reine CPU-Inferenz → konservativer (sonst zäh)
        if   cap >= 32: key = "performance"
        elif cap >= 12: key = "laptop"
        elif cap >= 7:  key = "sparsam"
        else:           key = "mini"
    return _BY_KEY[key]


def profile(key: str) -> dict | None:
    return _BY_KEY.get(key)
