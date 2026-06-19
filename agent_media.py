"""
Medien-Tool für den Claude-Dashboard-Agenten — Bild/Video-Generierung.

Reicht Aufträge an die vorhandene media_queue weiter (lokale Diffusers-Modelle bzw.
Higgsfield-Cloud, falls HIGGSFIELD_API_KEY gesetzt). Generierung läuft asynchron im
Hintergrund — die Tools geben die Job-ID zurück, der Status ist abrufbar.
"""
from __future__ import annotations


def generate_image(prompt: str, model_key: str = "") -> str:
    import media_queue
    prompt = (prompt or "").strip()
    if not prompt:
        return "Kein Bild-Prompt angegeben."
    job_id = media_queue.submit("image", {
        "prompt": prompt[:1000], "model_key": (model_key or "").strip(), "steps": 25,
    })
    return (f"Bild-Job gestartet (id {job_id}). Generierung läuft im Hintergrund und "
            f"erscheint im 'Bilder'-Tab. Status: GET /api/media/job/{job_id}. "
            f"Hinweis: lokale Generierung kann ohne GPU mehrere Minuten dauern.")


def generate_video(prompt: str, backend: str = "local") -> str:
    import media_queue
    prompt = (prompt or "").strip()
    if not prompt:
        return "Kein Video-Prompt angegeben."
    if backend == "higgsfield":
        job_id = media_queue.submit("higgsfield", {"prompt": prompt[:1000], "hf_model": "dop-lite"})
    else:
        backend = "local"
        job_id = media_queue.submit("video", {"prompt": prompt[:1000], "num_frames": 25})
    return (f"Video-Job gestartet (id {job_id}, Backend {backend}). Erscheint im "
            f"'Videos'-Tab. Status: GET /api/media/job/{job_id}.")


def job_status(job_id: str, wait: bool = False) -> str:
    import media_queue
    import time
    end = time.time() + (25 if wait else 0)   # optional bis zu 25s auf Fertigstellung warten
    while True:
        job = media_queue.get(job_id)
        if not job:
            return f"Job {job_id} nicht gefunden."
        st  = job.get("status", "?")
        url = job.get("result_url") or job.get("result") or ""
        err = job.get("error") or ""
        terminal = bool(url) or bool(err) or str(st).lower() in (
            "done", "fertig", "completed", "error", "failed", "fehler")
        if terminal or time.time() >= end:
            return (f"Job {job_id}: {st}" + (f" — {url}" if url else "")
                    + (f" (Fehler: {err})" if err else ""))
        time.sleep(2)


def capabilities() -> str:
    try:
        import media_engine
        s = media_engine.get_status()
        return ("Bild (lokal/Diffusers): " + ("verfügbar" if s.get("diffusers_ok") else "nicht installiert") +
                " · Higgsfield-Video: " + ("API-Key vorhanden" if s.get("higgsfield_api_key") else "kein HIGGSFIELD_API_KEY"))
    except Exception:
        return "Medien-Engine-Status unbekannt."
