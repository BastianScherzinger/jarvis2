"""
Geteilte HTTP- und Ollama-Helfer für alle Scraper und den Verifier.
Öffentliche API: get, ddg_search, ask_ollama, extract_json, ollama_models, UA.
"""
import json
import os
import re
import urllib.request
import urllib.parse
import urllib.error

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


def ddg_search(query: str) -> list[dict]:
    """DuckDuckGo Lite HTML-Suche — robusteres Parsing."""
    q    = urllib.parse.quote_plus(query)
    html = get(f"https://lite.duckduckgo.com/lite/?q={q}", timeout=12)
    if not html:
        html = get(f"https://html.duckduckgo.com/html/?q={q}", timeout=12)
    if not html:
        return []

    results = []
    # Lite DDG: Links in <a class="result-link">
    for m in re.finditer(
        r'<a[^>]+class="[^"]*result-link[^"]*"[^>]+href="([^"]+)"[^>]*>([^<]+)</a>',
        html, re.IGNORECASE
    ):
        url   = m.group(1).strip()
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if url.startswith("http") and title:
            results.append({"url": url, "title": title, "snippet": ""})
            if len(results) >= 8:
                break

    # Fallback: Standard DDG
    if not results:
        for m in re.finditer(
            r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            html, re.IGNORECASE | re.DOTALL
        ):
            url   = m.group(1).strip()
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if url.startswith("http") and title:
                results.append({"url": url, "title": title, "snippet": ""})
                if len(results) >= 8:
                    break

    return results


# ── Ollama ──────────────────────────────────────────────────────────────────

def ask_ollama(prompt: str, system: str = "", model: str = "") -> str:
    """
    Fragt das lokale Ollama-Modell. Modell-Auswahl dynamisch:
    explizites model > JARVIS_VERIFIER_MODEL > JARVIS_LOCAL_MODEL > qwen2.5:7b.
    Env-Vars werden bei JEDEM Aufruf neu gelesen (Laufzeit-Wechsel möglich).
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
        "options": {"temperature": 0.1},
    }).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())["message"]["content"]
    except urllib.error.URLError:
        return ""   # Ollama nicht erreichbar — kein Fehler-Spam
    except Exception as e:
        return f"FEHLER: {e}"


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
