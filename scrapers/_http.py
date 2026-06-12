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

# Ollama serialisiert Anfragen intern auf einer GPU. Bei 6+ parallelen Threads
# (Evaluator + Verifier) stauen sich die Requests und laufen in den Timeout.
# Die Semaphore begrenzt gleichzeitige Ollama-Calls → kein Timeout-Kaskade.
_OLLAMA_SEM = threading.Semaphore(2)
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
        "options": {"temperature": 0.1, "num_predict": 400},
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
    """Bestes installiertes CHAT-Modell für die Lead-Bewertung.

    Code-Modelle (z.B. qwen2.5-coder) sind für deutsche Vertriebstexte
    ungeeignet (halluzinieren) — daher bevorzugt: explizites JARVIS_EVAL_MODEL,
    sonst das größte installierte Nicht-Coder-Modell, sonst Fallback.
    Ergebnis wird gecacht.
    """
    env = os.environ.get("JARVIS_EVAL_MODEL", "").strip()
    if env:
        return env
    if _BEST_MODEL[0]:
        return _BEST_MODEL[0]
    models = ollama_models()
    chat   = [m for m in models if "coder" not in m["name"].lower()
              and "embed" not in m["name"].lower()]
    pool   = chat or models
    if pool:
        best = max(pool, key=lambda m: m.get("size_gb", 0))["name"]
    else:
        best = os.environ.get("JARVIS_LOCAL_MODEL", "qwen2.5:7b")
    _BEST_MODEL[0] = best
    return best


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
    try:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except Exception:
        pass
    # Fallback: kleinstes, nicht-verschachteltes Objekt
    try:
        m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except Exception:
        pass
    return {}
