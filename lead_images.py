"""
lead_images.py — Lokale Bewertung & sinnvolle Einordnung der beim Lead gefundenen Fotos.

Beim Bauen einer Kundenseite lädt der website_builder bis zu 6 Fotos, die der Scraper auf
Google Maps gefunden hat (`foto_urls`). Bisher wurden sie ungeprüft in die Galerie gekippt —
darunter Logos, Karten-Ausschnitte, winzige Thumbnails oder unscharfe Schnappschüsse.

Dieses Modul bewertet die heruntergeladenen Bilder **vollständig lokal** (keine Claude-Tokens,
keine Cloud nötig) und ordnet sie sinnvoll den Rollen Hero / Über-uns / Galerie zu:

  • Heuristik (Pillow + NumPy): Auflösung, Seitenverhältnis, Schärfe (Laplace-Varianz),
    Farbigkeit (Hasler-Süsstrunk), Helligkeit/Kontrast → erkennt Logos/Grafiken/Karten,
    zu kleine Thumbnails, über-/unterbelichtete oder unscharfe Bilder und verwirft sie.
  • Optional Ollama-Vision (`JARVIS_VISION_MODEL`, z.B. `llava` / `qwen2.5vl`): wenn ein
    Vision-Modell installiert ist, verfeinert es Relevanz/Qualität (1–10) je Bild und liefert
    eine kurze Bildunterschrift. GPU-bewusst, best-effort — fehlt es, zählt nur die Heuristik.

Einstieg: evaluate_and_arrange(web_paths, target_folder, branche) -> dict
  → {"hero", "about", "gallery", "captions", "evaluated"} (alle als /static/-Pfade).
Alles best-effort: ohne Pillow oder bei Fehlern werden die Eingaben unverändert als Galerie
zurückgegeben — der Build bricht NIE ab.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

try:
    import logger
except Exception:                       # Logger ist best-effort
    logger = None


def _lg(level: str, msg: str) -> None:
    try:
        if logger:
            getattr(logger, level, logger.info)("LeadBilder", msg)
    except Exception:
        pass


# ── Schwellwerte (per .env justierbar) ───────────────────────────────────────────
def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except Exception:
        return default


_MIN_SEITE   = int(_f("JARVIS_IMG_MIN_SIDE", 400))      # kürzeste Kante in px (sonst Thumbnail)
_MIN_MPX     = _f("JARVIS_IMG_MIN_MPX", 0.16)            # Mindest-Megapixel
_MIN_SCHARF  = _f("JARVIS_IMG_MIN_SHARP", 60.0)         # Laplace-Varianz (unter = unscharf)
_MIN_FARBE   = _f("JARVIS_IMG_MIN_COLOR", 8.0)          # Farbigkeit (unter = Logo/Graustufe)
_HERO_MIN_W  = int(_f("JARVIS_IMG_HERO_MIN_W", 1100))   # Mindestbreite, um Hero zu werden
# Bestes echtes Foto als Hero verwenden (spart ein Higgsfield-Bild). 0 = aus.
_LEAD_HERO   = (os.environ.get("JARVIS_LEAD_PHOTO_HERO", "1") or "1").strip().lower() not in (
    "0", "false", "no", "nein", "off")


# ── Heuristische Bildanalyse ─────────────────────────────────────────────────────

def _metrics(fs_path: Path) -> "dict | None":
    """Roh-Metriken eines Bildes via Pillow/NumPy. None, wenn nicht ladbar."""
    try:
        from PIL import Image
        import numpy as np
    except Exception:
        return None
    try:
        with Image.open(fs_path) as im:
            im = im.convert("RGB")
            w, h = im.size
            # Für die Analyse herunterskalieren (schnell, Metriken bleiben aussagekräftig).
            small = im.copy()
            small.thumbnail((512, 512))
            arr = np.asarray(small, dtype="float32")
    except Exception:
        return None

    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    # Farbigkeit nach Hasler & Süsstrunk (höher = bunter; Logos/Graustufen sind niedrig).
    rg = r - g
    yb = 0.5 * (r + g) - b
    colour = float((rg.std() ** 2 + yb.std() ** 2) ** 0.5
                   + 0.3 * ((rg.mean() ** 2 + yb.mean() ** 2) ** 0.5))
    # Schärfe: Varianz des Laplace-Filters auf der Graustufe.
    gray = 0.299 * r + 0.587 * g + 0.114 * b
    lap = (
        -4 * gray[1:-1, 1:-1]
        + gray[:-2, 1:-1] + gray[2:, 1:-1]
        + gray[1:-1, :-2] + gray[1:-1, 2:]
    )
    sharp = float(lap.var())
    bright = float(gray.mean())            # 0..255
    # Anteil (fast) einfarbiger Fläche → Logos/Grafiken/Karten haben große flache Bereiche.
    std_pix = float(gray.std())
    return {
        "w": w, "h": h, "mpx": (w * h) / 1_000_000.0,
        "aspect": (w / h) if h else 1.0,
        "colour": colour, "sharp": sharp, "bright": bright, "contrast": std_pix,
    }


def _judge(m: dict) -> dict:
    """Bewertet Metriken → {score 0-100, ok, reason, role_hint}."""
    reasons = []
    if min(m["w"], m["h"]) < _MIN_SEITE or m["mpx"] < _MIN_MPX:
        reasons.append("zu klein")
    if m["colour"] < _MIN_FARBE:
        reasons.append("farblos/Logo")
    if m["sharp"] < _MIN_SCHARF:
        reasons.append("unscharf")
    if m["bright"] < 18 or m["bright"] > 242:
        reasons.append("über-/unterbelichtet")
    if m["contrast"] < 12:
        reasons.append("flach/Grafik")
    if m["aspect"] > 4.0 or m["aspect"] < 0.25:
        reasons.append("extremes Format")

    # Score: Auflösung + Schärfe + Farbigkeit + Kontrast, weich normiert.
    res_s   = min(1.0, m["mpx"] / 1.2)
    sharp_s = min(1.0, m["sharp"] / 600.0)
    col_s   = min(1.0, m["colour"] / 45.0)
    con_s   = min(1.0, m["contrast"] / 60.0)
    score = round(100 * (0.34 * res_s + 0.30 * sharp_s + 0.20 * col_s + 0.16 * con_s))
    if reasons:
        score = min(score, 35)

    # Rollen-Hinweis aus dem Format.
    if m["aspect"] >= 1.45 and m["w"] >= _HERO_MIN_W:
        role = "hero"
    elif m["aspect"] <= 0.85:
        role = "about"       # Hochformat → Über-uns/Inhaber
    else:
        role = "gallery"
    return {"score": score, "ok": not reasons,
            "reason": ", ".join(reasons), "role_hint": role}


# ── Optionale Ollama-Vision-Verfeinerung ─────────────────────────────────────────

def _vision_model() -> str:
    return (os.environ.get("JARVIS_VISION_MODEL", "") or "").strip()


def _ollama_vision(fs_path: Path, branche: str) -> "dict | None":
    """Fragt ein lokales Vision-Modell (falls konfiguriert) nach Relevanz/Qualität +
    Bildunterschrift. Gibt {quality 1-10, relevant bool, caption} oder None."""
    model = _vision_model()
    if not model:
        return None
    try:
        import urllib.request
        data = fs_path.read_bytes()
        if len(data) > 6_000_000:
            return None
        b64 = base64.b64encode(data).decode("ascii")
        prompt = (
            f"Dies ist ein Foto eines {branche or 'lokalen'}-Betriebs für dessen neue Webseite. "
            "Bewerte NUR als JSON: {\"quality\":1-10 (Eignung als Webseiten-Foto), "
            "\"relevant\":true/false (zeigt es Arbeit/Betrieb/Räume/Team und KEIN Logo/Karte/"
            "Screenshot), \"caption\":\"kurze deutsche Bildunterschrift\"}."
        )
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt, "images": [b64]}],
            "stream": False, "keep_alive": "10m",
            "options": {"temperature": 0.1, "num_predict": 200},
        }).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/chat", data=payload,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=90) as r:
            txt = json.loads(r.read())["message"]["content"]
        s = txt.find("{"); e = txt.rfind("}")
        if s < 0 or e <= s:
            return None
        d = json.loads(txt[s:e + 1])
        return {
            "quality": float(d.get("quality") or 0),
            "relevant": bool(d.get("relevant", True)),
            "caption": str(d.get("caption") or "").strip()[:120],
        }
    except Exception:
        return None


# ── Pfad-Helfer ──────────────────────────────────────────────────────────────────

def _to_fs(web_path: str, folder: Path) -> "Path | None":
    """/static/img/lead/1.jpg + Projektordner → echter Dateipfad (oder None)."""
    p = (web_path or "").strip()
    if not p.startswith("/static/"):
        return None
    if p.lower().endswith(".svg"):       # SVG-Platzhalter sind keine Lead-Fotos
        return None
    fs = folder / p.lstrip("/")
    return fs if fs.is_file() else None


# ── Öffentliche API ──────────────────────────────────────────────────────────────

def evaluate(web_paths: list, folder: "str | Path", branche: str = "") -> list[dict]:
    """Bewertet jede echte Bilddatei lokal. Gibt je Bild ein dict zurück:
    {path, score, ok, reason, role_hint, caption}. Verworfene haben ok=False."""
    folder = Path(folder)
    out: list[dict] = []
    use_vision = bool(_vision_model())
    for wp in (web_paths or []):
        fs = _to_fs(wp, folder)
        if not fs:
            continue
        m = _metrics(fs)
        if not m:
            continue
        j = _judge(m)
        rec = {"path": wp, "score": j["score"], "ok": j["ok"],
               "reason": j["reason"], "role_hint": j["role_hint"], "caption": ""}
        if use_vision:
            v = _ollama_vision(fs, branche)
            if v is not None:
                # Vision-Urteil einmischen: Qualität skaliert den Score, Irrelevanz verwirft.
                rec["score"] = round(0.6 * rec["score"] + 0.4 * (v["quality"] * 10))
                rec["caption"] = v["caption"]
                if not v["relevant"]:
                    rec["ok"] = False
                    rec["reason"] = (rec["reason"] + ", " if rec["reason"] else "") + "irrelevant (Vision)"
        out.append(rec)
    out.sort(key=lambda r: r["score"], reverse=True)
    return out


def arrange(evaluated: list[dict]) -> dict:
    """Ordnet bewertete Bilder den Rollen zu. Nur ok=True-Bilder werden verwendet.

    Hero: bestes echtes Querformat (role_hint hero) — nur wenn _LEAD_HERO an.
    About: bestes Hochformat. Galerie: der Rest, nach Score sortiert.
    """
    good = [r for r in evaluated if r["ok"]]
    hero = ""
    about = ""
    used: set = set()

    if _LEAD_HERO:
        for r in good:
            if r["role_hint"] == "hero":
                hero = r["path"]; used.add(r["path"]); break
    for r in good:
        if r["path"] in used:
            continue
        if r["role_hint"] == "about":
            about = r["path"]; used.add(r["path"]); break

    gallery = [r["path"] for r in good if r["path"] not in used]
    captions = {r["path"]: r["caption"] for r in evaluated if r.get("caption")}
    return {"hero": hero, "about": about, "gallery": gallery, "captions": captions}


def evaluate_and_arrange(web_paths: list, folder: "str | Path", branche: str = "") -> dict:
    """Komplett: bewerten + einordnen. Gibt
    {"hero","about","gallery","captions","evaluated"} zurück. Bei Fehlern/ohne Pillow
    werden die Eingaben unverändert als Galerie geliefert (kein Build-Abbruch)."""
    try:
        ev = evaluate(web_paths, folder, branche)
        if not ev:
            return {"hero": "", "about": "", "gallery": list(web_paths or []),
                    "captions": {}, "evaluated": []}
        arr = arrange(ev)
        arr["evaluated"] = ev
        gut = sum(1 for r in ev if r["ok"])
        _lg("info", f"{gut}/{len(ev)} Lead-Foto(s) brauchbar · "
                    f"Hero={'ja' if arr['hero'] else 'nein'} · Galerie {len(arr['gallery'])}")
        return arr
    except Exception as e:
        _lg("warn", f"Bewertung übersprungen ({type(e).__name__}) — Fotos unverändert.")
        return {"hero": "", "about": "", "gallery": list(web_paths or []),
                "captions": {}, "evaluated": []}
