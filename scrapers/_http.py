"""
Geteilte HTTP- und Ollama-Helfer für alle Scraper und den Verifier.
Öffentliche API: get, ddg_search, ask_ollama, extract_json, ollama_models,
warmup_ollama, UA, DIRECTORY_HEADERS, get_directory, parse_rating.
"""
import json
import os
import re
import socket
import threading
import time
import urllib.request
import urllib.parse
import urllib.error

import logger

def _int_env(name: str, default: int) -> int:
    """Robuste int-Env (nicht-numerischer Wert darf den Start NICHT crashen)."""
    try:
        return int(os.environ.get(name, str(default)) or default)
    except (ValueError, TypeError):
        return default


# Ergebnis der EINEN nvidia-smi-Abfrage beim Import: hat das System eine GPU?
# Wird von _num_gpu wiederverwendet → keine zweite nvidia-smi-Abfrage nötig.
_GPU_HINT: list = [None]   # None = unbekannt, True/False = erkannt


def _detect_gpu_parallel() -> int:
    """GPU-aware Default: 4 parallel bei dedizierter GPU (serialisiert GPU-intern schnell),
    2 bei CPU-only (langsamere Inferenz, mehr Threads würden nur aufstauen).
    Überschreibbar per JARVIS_OLLAMA_PARALLEL."""
    env_val = os.environ.get("JARVIS_OLLAMA_PARALLEL", "").strip()
    if env_val:
        try:
            return max(1, int(env_val))
        except (ValueError, TypeError):
            pass
    try:
        import subprocess
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.total",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=4)
        has_gpu = r.returncode == 0 and bool(r.stdout.strip())
        _GPU_HINT[0] = has_gpu                 # für _num_gpu mitverwenden (1× nvidia-smi)
        if has_gpu:
            vram_mb = float(r.stdout.strip().splitlines()[0])
            return 4 if vram_mb >= 6000 else 2
    except Exception:
        _GPU_HINT[0] = False
    return 2


_OLLAMA_PARALLEL = _detect_gpu_parallel()
_OLLAMA_SEM = threading.Semaphore(_OLLAMA_PARALLEL)
_OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
# Großzügiger Timeout: Kaltstart eines 7B-Modells (Laden von Platte) kann
# 30-120s dauern. keep_alive hält das Modell danach im Speicher.
_OLLAMA_TIMEOUT = 180

# GPU-Layer-Option: -1 = alle Schichten auf die GPU laden (auto). Bei reiner CPU auf 0 lassen
# (default), damit Ollama CPU-Threads optimal nutzt statt 0 GPU-Layer zu versuchen.
def _num_gpu() -> int:
    env_val = os.environ.get("JARVIS_OLLAMA_NUM_GPU", "").strip()
    if env_val:
        try:
            return int(env_val)
        except (ValueError, TypeError):
            pass
    # GPU-Erkennung aus _detect_gpu_parallel wiederverwenden (dieselbe nvidia-smi-Info) —
    # so braucht der Modul-Import nur EINE nvidia-smi-Abfrage statt zwei.
    if _GPU_HINT[0] is not None:
        return -1 if _GPU_HINT[0] else 0
    try:
        import subprocess
        r = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=3)
        return -1 if r.returncode == 0 and r.stdout.strip() else 0
    except Exception:
        return 0

# Lazy + gecacht: kein zweiter nvidia-smi-Aufruf beim Modul-Import; der Wert wird beim
# ersten Ollama-Call aus dem _GPU_HINT (bzw. Env) abgeleitet und gecacht.
_NUM_GPU_CACHE: list = [None]


def _num_gpu_cached() -> int:
    if _NUM_GPU_CACHE[0] is None:
        _NUM_GPU_CACHE[0] = _num_gpu()
    return _NUM_GPU_CACHE[0]


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


# ── HTTP ────────────────────────────────────────────────────────────────────

def get(url: str, timeout: int = 10) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


# ── Verzeichnis-Scraper: gemeinsame Header/Get/Rating-Helfer ─────────────────
# Vorher 4x byte-identisch dupliziert in gelbe_seiten/dasoertliche/elfacht/golocal.py
# (siehe workspace/LEAD_COLLECTOR_UND_AUDIT.md, "Fix 6"). Bewusst getrennt von `get()`
# oben (andere Header/Timeout, andere Aufrufer) statt es zu überladen.
DIRECTORY_HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
}


def get_directory(url: str, timeout: int = 14) -> str:
    """HTTP-GET mit den vollen Verzeichnis-Scraper-Headern (UA+Accept-Language+Accept)."""
    req = urllib.request.Request(url, headers=DIRECTORY_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def parse_rating(art) -> tuple[float, int]:
    """Extrahiert (Sterne 0-5, Anzahl Bewertungen) aus einem Verzeichnis-Listen-Eintrag
    (BeautifulSoup-Tag). Robust — gibt (0.0, 0) zurück wenn nichts gefunden, crasht nie."""
    bewertung, anz = 0.0, 0
    try:
        rate_el = (
            art.select_one("[itemprop='ratingValue']") or
            art.select_one("[class*='rating']") or
            art.select_one("[class*='stars']") or
            art.select_one("[class*='bewertung']")
        )
        txt = ""
        if rate_el:
            txt = rate_el.get("content") or rate_el.get("aria-label") or rate_el.get_text(" ", strip=True)
        if txt:
            m = re.search(r"(\d[.,]?\d?)", txt)
            if m:
                val = float(m.group(1).replace(",", "."))
                if 0.0 <= val <= 5.0:
                    bewertung = val
    except Exception:
        bewertung = 0.0
    try:
        cnt_el = (
            art.select_one("[itemprop='reviewCount']") or
            art.select_one("[class*='count']")
        )
        cnt_txt = ""
        if cnt_el:
            cnt_txt = cnt_el.get("content") or cnt_el.get_text(" ", strip=True)
        if not cnt_txt:
            full = art.get_text(" ", strip=True)
            mb = re.search(r"\((\d+)\s*Bewertung", full, re.I) or \
                 re.search(r"(\d+)\s*Bewertung", full, re.I)
            if mb:
                cnt_txt = mb.group(1)
        if cnt_txt:
            mc = re.search(r"\d+", cnt_txt)
            if mc:
                anz = int(mc.group(0))
    except Exception:
        anz = 0
    return bewertung, anz


# ── Web-Suche (Multi-Engine + globaler Rate-Limiter) ──────────────────────────
# Freie Suchmaschinen blocken server-seitige Anfragen schnell, wenn 6 Worker +
# Evaluatoren gleichzeitig feuern. Deshalb: globaler Mindestabstand zwischen
# Suchen + Rotation über mehrere Engines (blockt eine, wird die nächste probiert).
_SEARCH_LOCK         = threading.Lock()
_last_search_ts      = [0.0]
_SEARCH_MIN_INTERVAL = 1.3   # Sekunden zwischen zwei Suchen (global)
_engine_idx          = [0]   # Rotation, damit nicht immer dieselbe Engine zuerst


def _rate_limit() -> None:
    with _SEARCH_LOCK:
        dt = time.time() - _last_search_ts[0]
        if dt < _SEARCH_MIN_INTERVAL:
            time.sleep(_SEARCH_MIN_INTERVAL - dt)
        _last_search_ts[0] = time.time()


def _search_mojeek(q: str) -> list[dict]:
    html = get("https://www.mojeek.com/search?q=" + urllib.parse.quote_plus(q), timeout=12)
    out = []
    # Ergebnis-Links: <li class="rN"><a title="URL" href="URL" class="ob">
    for m in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*class="ob"', html):
        out.append({"url": m.group(1), "title": "", "snippet": ""})
    if not out:
        for m in re.finditer(r'<a[^>]+class="ob"[^>]+href="(https?://[^"]+)"', html):
            out.append({"url": m.group(1), "title": "", "snippet": ""})
    return out


def _search_ddg(q: str) -> list[dict]:
    # DDG braucht POST mit Formulardaten (GET liefert nur das leere Formular).
    body = urllib.parse.urlencode({"q": q, "kl": "de-de"}).encode()
    req = urllib.request.Request(
        "https://html.duckduckgo.com/html/", data=body,
        headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded",
                 "Accept-Language": "de-DE,de;q=0.9"},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            html = r.read().decode("utf-8", errors="replace")
    except Exception:
        return []
    out = []
    for m in re.finditer(
        r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        html, re.IGNORECASE | re.DOTALL,
    ):
        url = m.group(1).strip()
        mm  = re.search(r'uddg=([^&]+)', url)   # DDG-Redirect entpacken
        if mm:
            url = urllib.parse.unquote(mm.group(1))
        if url.startswith("http"):
            out.append({"url": url, "title": re.sub(r"<[^>]+>", "", m.group(2)).strip(), "snippet": ""})
    return out


def _search_bing(q: str) -> list[dict]:
    html = get("https://www.bing.com/search?q=" + urllib.parse.quote_plus(q) +
               "&setlang=de&cc=DE", timeout=12)
    out = []
    for m in re.finditer(r'<h2>\s*<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                         html, re.IGNORECASE | re.DOTALL):
        url = m.group(1)
        if any(b in url for b in ("bing.com", "microsoft.com", "msn.com")):
            continue
        out.append({"url": url, "title": re.sub(r"<[^>]+>", "", m.group(2)).strip(), "snippet": ""})
    return out


_ENGINES = [_search_ddg, _search_mojeek, _search_bing]


def ddg_search(query: str) -> list[dict]:
    """Web-Suche über mehrere Engines mit Rotation + globalem Rate-Limit.
    Gibt bis zu 8 Treffer [{url,title,snippet}]. Leere Liste wenn alle blocken."""
    _rate_limit()
    n = len(_ENGINES)
    start = _engine_idx[0] % n
    _engine_idx[0] = (start + 1) % n
    for off in range(n):
        engine = _ENGINES[(start + off) % n]
        try:
            res = engine(query)
        except Exception:
            res = []
        if res:
            return res[:8]
    return []


# ── Ollama ──────────────────────────────────────────────────────────────────

def ask_ollama(prompt: str, system: str = "", model: str = "",
               timeout: int = _OLLAMA_TIMEOUT) -> str:
    """
    Fragt das lokale Ollama-Modell. Modell-Auswahl dynamisch:
    explizites model > JARVIS_VERIFIER_MODEL > JARVIS_LOCAL_MODEL > qwen2.5:7b.
    Env-Vars werden bei JEDEM Aufruf neu gelesen (Laufzeit-Wechsel möglich).
    Begrenzt durch Semaphore (GPU: 4 parallel, CPU: 2) + keep_alive hält Modell geladen.
    num_gpu=-1: alle Schichten auf die GPU laden (0 auf CPU-only-Systemen).
    """
    if not model:
        model = os.environ.get("JARVIS_VERIFIER_MODEL") or \
                os.environ.get("JARVIS_LOCAL_MODEL", "qwen2.5:7b")
    options: dict = {
        "temperature": 0.1,
        "num_predict": 768,
        # num_gpu: -1 = GPU auto (alle Layer), 0 = CPU-only.
        # Lazy beim ersten Call erkannt + gecacht (kein nvidia-smi beim Import).
        "num_gpu": _num_gpu_cached(),
    }
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system or "Du bist ein präziser Daten-Extraktor. Antworte NUR mit JSON."},
            {"role": "user",   "content": prompt},
        ],
        "stream": False,
        "keep_alive": "10m",                # Modell 10 Min im Speicher halten
        "options": options,
    }).encode("utf-8")
    req = urllib.request.Request(
        _OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    # Bis zu 2 Versuche: bei einem TIMEOUT (Modell schwitzt evtl. am Limit) einmal kurz
    # nachfassen, bevor auf die Heuristik zurückgefallen wird. Bei „nicht erreichbar"
    # (Connection refused, Ollama aus) KEIN Retry und kein Spam. Unerwartete Fehler
    # (JSON-/KeyError) werden EINMAL geloggt statt still verschluckt.
    # Der Backoff läuft AUSSERHALB des Semaphors — der Slot wird zwischen den Versuchen
    # freigegeben, damit andere Threads nicht hinter einem schlafenden Retry warten.
    for _attempt in range(2):
        retry = False
        with _OLLAMA_SEM:
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return json.loads(r.read())["message"]["content"]
            except urllib.error.URLError as e:
                if _attempt == 0 and isinstance(getattr(e, "reason", None),
                                                (TimeoutError, socket.timeout)):
                    retry = True                   # Connect-Timeout → einmal retryen
                else:
                    return ""                      # nicht erreichbar/refused → Fallback
            except (TimeoutError, socket.timeout):
                if _attempt == 0:
                    retry = True                   # Read-Timeout → einmal retryen
                else:
                    return ""
            except Exception as e:
                logger.warn("Ollama", f"ask_ollama unerwartet: {type(e).__name__}")
                return ""
        if not retry:
            return ""
        time.sleep(0.8)                            # Backoff ohne belegten Semaphor-Slot
    return ""


_BEST_MODEL: list = [None, 0.0]   # [model_name, cache_ts]
_BEST_MODEL_TTL = 600             # Cache 10 Min gültig (Modelle können zur Laufzeit installiert werden)
_BEST_MODEL_LOCK = threading.Lock()   # schützt den Cache gegen parallele Evaluator-Threads


def best_chat_model() -> str:
    """Bestes installiertes CHAT-Modell für die Lead-Bewertung — VRAM-bewusst.

    Auswahl:
      1. explizites JARVIS_EVAL_MODEL — ABER nur wenn es in den Speicher passt
         (sonst würde z.B. 32B auf 16 GB VRAM auslagern und alles ausbremsen).
      2. Hardware-Empfehlung (z.B. qwen2.5:14b auf 16 GB VRAM), wenn installiert.
      3. größtes installiertes Nicht-Coder-Modell, das in den Speicher passt.
    Code-Modelle (qwen2.5-coder) werden gemieden (halluzinieren). Ergebnis 10 Min gecacht.
    """
    with _BEST_MODEL_LOCK:
        if _BEST_MODEL[0] and time.time() - _BEST_MODEL[1] < _BEST_MODEL_TTL:
            return _BEST_MODEL[0]

    models  = ollama_models()
    by_name = {m["name"]: m.get("size_gb", 0) for m in models}

    # Hardware-Kapazität (VRAM bei GPU, sonst RAM) + Empfehlung
    rec, cap = "", 0.0
    try:
        import hardware
        hw  = hardware.detect()
        cap = hw["vram_gb"] if hw["has_gpu"] else hw["ram_gb"]
        rec = hardware.recommend(hw)["model"]
    except Exception:
        pass

    def _passt(name: str) -> bool:
        s = by_name.get(name, 0)
        return cap <= 0 or s <= 0 or s <= cap * 1.05   # passt in den Speicher?

    env = os.environ.get("JARVIS_EVAL_MODEL", "").strip()
    chosen = ""
    if env and _passt(env):
        chosen = env                                   # explizit + passt
    elif rec and rec in by_name and _passt(rec):
        chosen = rec                                   # Empfehlung (z.B. 14b/16GB)
    if not chosen:
        chat = [m for m in models
                if "coder" not in m["name"].lower() and "embed" not in m["name"].lower()
                and _passt(m["name"])]
        pool = chat or [m for m in models if _passt(m["name"])] or models
        if pool:
            chosen = max(pool, key=lambda m: m.get("size_gb", 0))["name"]
        else:
            chosen = env or rec or os.environ.get("JARVIS_LOCAL_MODEL", "qwen2.5:7b")

    with _BEST_MODEL_LOCK:
        _BEST_MODEL[0] = chosen
        _BEST_MODEL[1] = time.time()
    return chosen


def warmup_ollama() -> bool:
    """
    Lädt das Bewertungs-Modell EINMAL in den Speicher (Kaltstart 30-120s).
    Sollte beim Scraper-Start in einem eigenen Thread aufgerufen werden, damit
    die Evaluator-Threads danach schnelle Antworten bekommen statt zu timeouten.
    Gibt True zurück wenn Ollama geantwortet hat.
    """
    r = ask_ollama('Antworte nur mit: {"ok":1}', "Test",
                   model=best_chat_model(), timeout=300)
    return bool(r)


def ollama_models() -> list[dict]:
    """Listet installierte Ollama-Modelle. Leere Liste bei Fehler."""
    req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read())
    except Exception:
        return []
    out = []
    for m in data.get("models", []):
        name = m.get("name", "")
        if not name:
            continue
        size = m.get("size", 0) or 0
        out.append({"name": name, "size_gb": round(size / 1_000_000_000, 1)})
    return out


# ── JSON-Extraktion ─────────────────────────────────────────────────────────

def extract_json(text: str) -> dict:
    if not text:
        return {}
    s = text.strip()
    # 1. Direkter Versuch (Ollama liefert oft reines JSON)
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # 2. Erstes BALANCIERTES {...} per Tiefenzähler extrahieren (string-bewusst).
    #    Greedy r"\{.*\}" matchte vom ersten { bis zum letzten } und scheiterte
    #    bei Fließtext/zwei Objekten/abgeschnittenem JSON → Werte fielen still auf 0.
    start = s.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(s)):
            c = s[i]
            if in_str:
                if esc:        esc = False
                elif c == "\\": esc = True
                elif c == '"': in_str = False
            elif c == '"':     in_str = True
            elif c == "{":     depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(s[start:i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except Exception:
                        pass
                    break   # dieser Block kaputt → nächstes { suchen
        start = s.find("{", start + 1)
    return {}
