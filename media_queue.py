"""
Media-Job-Queue — serielle Abarbeitung von Bild/Video-Generierungen.
Nur EIN Job gleichzeitig (GPU/VRAM-Constraint).
"""
from __future__ import annotations

import queue
import threading
import time
import uuid
from pathlib import Path

_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_q: queue.Queue = queue.Queue()
_worker_started = False

_BASE = Path(__file__).parent
_IMAGES_DIR = _BASE / "workspace" / "media" / "images"
_VIDEOS_DIR = _BASE / "workspace" / "media" / "videos"


def _ensure_worker() -> None:
    """Startet den Worker-Thread lazy beim ersten submit (daemon)."""
    global _worker_started
    with _lock:
        if _worker_started:
            return
        t = threading.Thread(target=_worker, name="media-worker", daemon=True)
        t.start()
        _worker_started = True


def submit(kind: str, params: dict) -> str:
    """
    Legt einen Job an und reiht ihn ein. Gibt job_id zurück.
    kind: 'image' | 'video' | 'higgsfield' | 'mockup'
    """
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id":          job_id,
        "kind":        kind,
        "status":      "queued",
        "prompt":      params.get("prompt", ""),
        "model":       params.get("model_key") or params.get("hf_model") or params.get("model") or "",
        "progress":    0,
        "result_url":  "",
        "result_urls": [],                       # alle bisher fertigen Bild-URLs
        "result_items": [],                      # Asset-Set: [{label, url, asset}]
        "done_count":  0,
        "total":       (len(params.get("assets") or []) if kind == "asset_set"
                        else int(params.get("count", 1)) if kind == "image_set" else 1),
        "summary":     params.get("summary", ""),
        "error":       "",
        "lead_id":     params.get("lead_id"),
        "created":     time.time(),
        "elapsed":     0,
        "_params":     params,
    }
    with _lock:
        _jobs[job_id] = job
    _ensure_worker()
    _q.put(job_id)
    return job_id


def get(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        return {k: v for k, v in job.items() if not k.startswith("_")}


def list_jobs(limit: int = 20) -> list[dict]:
    """Neueste zuerst."""
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda j: j["created"], reverse=True)
        return [{k: v for k, v in j.items() if not k.startswith("_")} for j in jobs[:limit]]


def _set(job_id: str, **fields) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job.update(fields)


def _worker() -> None:
    """
    Endlos-Loop: nimmt Jobs aus der Queue und arbeitet sie seriell ab.
    media_engine wird ERST hier importiert (lazy — torch-Import dauert lange,
    soll Flask-Start nicht blockieren).
    """
    while True:
        job_id = _q.get()
        with _lock:
            job = _jobs.get(job_id)
        if job is None:
            continue

        t0 = time.time()
        _set(job_id, status="running", progress=5)
        kind   = job["kind"]
        params = job["_params"]

        try:
            import media_engine  # lazy import

            if kind == "asset_set":
                # 5 feste Werbe-Assets (Logo, Hero, Flyer, Anzeige, Social),
                # jedes mit eigenem Prompt + Format. Seriell, Fortschritt live.
                import logger as _lg
                assets = params.get("assets") or []
                tot    = len(assets) or 1
                _lg.info("Bilder", f"Generiere Werbe-Set ({tot} Assets)…")
                urls, items = [], []
                for i, a in enumerate(assets):
                    ta = time.time()
                    _lg.info("Bilder", f"→ {a.get('label','')} ({i+1}/{tot})…")
                    res = media_engine.generate_image(
                        a.get("prompt", ""),
                        params.get("model_key") or None,
                        negative_prompt=a.get("negative_prompt")
                            or "blurry, low quality, watermark, text, deformed",
                        steps=int(params.get("steps", 0)),
                        width=a.get("width"),
                        height=a.get("height"),
                    )
                    u = res.get("web_url", "")
                    if u:
                        urls.append(u)
                        items.append({"label": a.get("label", ""), "url": u, "asset": a.get("asset", "")})
                        _lg.success("Bilder", f"✓ {a.get('label','')} fertig ({round(time.time()-ta,1)}s)")
                    _set(
                        job_id, status="running",
                        done_count=len(urls), total=tot,
                        progress=int((i + 1) / tot * 100),
                        result_urls=list(urls), result_items=list(items),
                        result_url=urls[0] if urls else "",
                        elapsed=round(time.time() - t0, 1),
                    )
                if not urls:
                    raise RuntimeError("Keine Assets erzeugt")
                _lg.success("Bilder", f"Werbe-Set fertig — {len(urls)} Assets in {round(time.time()-t0,1)}s")
                _set(job_id, status="done", progress=100,
                     result_urls=list(urls), result_items=list(items),
                     result_url=urls[0], elapsed=round(time.time() - t0, 1))
                continue

            if kind == "image_set":
                # Werbe-Foto-Set: N Bilder seriell, jedes ist eine eigene Variation
                # (kein fester Seed → natürliche Vielfalt). Fortschritt live updaten.
                count   = max(1, min(int(params.get("count", 10)), 12))
                urls: list[str] = []
                for i in range(count):
                    res = media_engine.generate_image(
                        params.get("prompt", ""),
                        params.get("model_key") or None,
                        negative_prompt=params.get("negative_prompt")
                            or "blurry, low quality, watermark, text, deformed",
                        steps=int(params.get("steps", 28)),
                        width=params.get("width"),
                        height=params.get("height"),
                    )
                    u = res.get("web_url", "")
                    if u:
                        urls.append(u)
                    _set(
                        job_id,
                        status="running",
                        done_count=len(urls),
                        progress=int((i + 1) / count * 100),
                        result_urls=list(urls),
                        result_url=urls[0] if urls else "",
                        elapsed=round(time.time() - t0, 1),
                    )
                if not urls:
                    raise RuntimeError("Keine Bilder erzeugt")
                _set(job_id, status="done", progress=100, result_urls=list(urls),
                     result_url=urls[0], elapsed=round(time.time() - t0, 1))
                continue

            if kind in ("image", "mockup"):
                result = media_engine.generate_image(
                    params.get("prompt", ""),
                    params.get("model_key") or None,
                    steps=int(params.get("steps", 25)),
                    width=params.get("width"),
                    height=params.get("height"),
                )
            elif kind == "video":
                result = media_engine.generate_video(
                    params.get("prompt", ""),
                    params.get("model_key") or None,
                    num_frames=int(params.get("num_frames", 25)),
                )
            elif kind == "higgsfield":
                result = media_engine.generate_video_higgsfield(
                    params.get("prompt", ""),
                    params.get("hf_model") or params.get("model") or "dop-lite",
                )
            else:
                raise ValueError(f"Unbekannter Job-Typ: '{kind}'")

            url = result.get("web_url", "")
            _set(
                job_id,
                status="done",
                progress=100,
                result_url=url,
                elapsed=round(time.time() - t0, 1),
            )

            # Mockup → in Lead-DB schreiben
            if kind == "mockup" and job.get("lead_id"):
                try:
                    import db
                    db.set_lead_field(job["lead_id"], "mockup_url", url)
                except Exception:
                    pass

        except Exception as e:
            _set(
                job_id,
                status="error",
                error=str(e)[:300],
                elapsed=round(time.time() - t0, 1),
            )


def gallery() -> dict:
    """
    Scannt die Bild- und Video-Verzeichnisse.
    Gibt dict zurück: {"images": [...], "videos": [...]} — neueste zuerst, max 100 je Typ.
    """
    def _scan(d: Path, web_prefix: str, exts: set[str]) -> list[dict]:
        if not d.exists():
            return []
        items = []
        for p in d.iterdir():
            if p.is_file() and p.suffix.lower() in exts:
                try:
                    mtime = p.stat().st_mtime
                except OSError:
                    continue
                items.append({
                    "url":   f"{web_prefix}/{p.name}",
                    "name":  p.name,
                    "mtime": mtime,
                })
        items.sort(key=lambda x: x["mtime"], reverse=True)
        return items[:100]

    return {
        "images": _scan(_IMAGES_DIR, "/workspace/media/images", {".png", ".jpg", ".jpeg", ".webp"}),
        "videos": _scan(_VIDEOS_DIR, "/workspace/media/videos", {".mp4", ".gif", ".webm"}),
    }
