"""
Geteilte HTTP- und Ollama-Helfer für alle Scraper und den Verifier.
Öffentliche API: get, ddg_search, ask_ollama, extract_json, ollama_models,
warmup_ollama, UA.
"""
import json
import os
import re
import threading
import time
import urllib.request
import urllib.parse
import urllib.error

# Ollama serialisiert Anfragen intern auf einer GPU. Bei vielen parallelen Evaluator-
# Threads stauen sich die Requests und laufen in den Timeout. Die Semaphore begrenzt
# gleichzeitige Ollama-Calls → kein Timeout-Kaskade. Auf einer starken Maschine (viel RAM/
# GPU) per JARVIS_OLLAMA_PARALLEL erhöhbar; Default 2 (sicher auch auf CPU).
_OLLAMA_SEM = threading.Semaphore(max(1, int(os.environ.get("JARVIS_OLLAMA_PARALLEL", "2") or "2")))
_OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
# Großzügiger Timeout: Kaltstart eines 7B-Modells (Laden von Platte) kann
# 30-120s dauern. keep_alive hält das Modell danach im Speicher.
_OLLAMA_TIMEOUT = 180

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
    Begrenzt durch Semaphore (max 2 parallel) + keep_alive hält Modell geladen.
    """
    if not model:
        model = os.environ.get("JARVIS_VERIFIER_MODEL") or \
                os.environ.get("JARVIS_LOCAL_MODEL", "qwen2.5:7b")
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system or "Du bist ein präziser Daten-Extraktor. Antworte NUR mit JSON."},
            {"role": "user",   "content": prompt},
        ],
        "stream": False,
        "keep_alive": "10m",                # Modell 10 Min im Speicher halten
        # num_predict großzügig: das Bewertungs-JSON (inkl. E-Mail-Entwurf) wurde
        # bei 400 oft abgeschnitten → unparsebar → Ollama-Anpassung fiel auf 0.
        "options": {"temperature": 0.1, "num_predict": 768},
    }).encode("utf-8")
    req = urllib.request.Request(
        _OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    with _OLLAMA_SEM:
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())["message"]["content"]
        except urllib.error.URLError:
            return ""   # Ollama nicht erreichbar — kein Fehler-Spam
        except Exception:
            return ""   # Timeout o.ä. — Aufrufer nutzt Fallback


_BEST_MODEL: list = [None]


def best_chat_model() -> str:
    """Bestes installiertes CHAT-Modell für die Lead-Bewertung — VRAM-bewusst.

    Auswahl:
      1. explizites JARVIS_EVAL_MODEL — ABER nur wenn es in den Speicher passt
         (sonst würde z.B. 32B auf 16 GB VRAM auslagern und alles ausbremsen).
      2. Hardware-Empfehlung (z.B. qwen2.5:14b auf 16 GB VRAM), wenn installiert.
      3. größtes installiertes Nicht-Coder-Modell, das in den Speicher passt.
    Code-Modelle (qwen2.5-coder) werden gemieden (halluzinieren). Ergebnis gecacht.
    """
    if _BEST_MODEL[0]:
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

    _BEST_MODEL[0] = chosen
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
