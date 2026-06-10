"""
AI-gestützter Scraper — Claude oder Ollama browsen selbst nach Leads.
Nutzt DuckDuckGo-Suche + HTML-Parsing ohne Playwright.
"""
import json
import os
import re
import urllib.request
import urllib.parse
import time

from agents.scorer import score as calc_score
from scrapers.website_checker import check_website
import db

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36"


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _ddg_search(query: str) -> list[dict]:
    """DuckDuckGo HTML-Suche — gibt [{title, url, snippet}] zurück."""
    q    = urllib.parse.quote_plus(query)
    html = _get(f"https://html.duckduckgo.com/html/?q={q}")
    if not html:
        return []
    results = []
    for m in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([^<]+)</a>'
        r'.*?<a[^>]+class="result__snippet"[^>]*>([^<]+)</a>',
        html, re.DOTALL
    )[:8]:
        results.append({"url": m.group(1), "title": m.group(2).strip(), "snippet": m.group(3).strip()})
    return results


def _ask_ollama(prompt: str, system: str = "") -> str:
    model = os.environ.get("JARVIS_TOOL_MODEL") or os.environ.get("JARVIS_LOCAL_MODEL", "qwen2.5:7b")
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system or "Du bist ein präziser Daten-Extraktor."},
            {"role": "user",   "content": prompt},
        ],
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())["message"]["content"]
    except Exception as e:
        return f"FEHLER: {e}"


def _ask_claude(prompt: str) -> str:
    try:
        import anthropic
        from config import get_api_key
        client = anthropic.Anthropic(api_key=get_api_key())
        msg    = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
    except Exception as e:
        return f"FEHLER: {e}"


def run_loop(region: str, branche: str, on_lead, stop_event, ai_mode="local", max_per=20):
    """
    ai_mode: 'local' | 'cloud' | 'both'
    Sucht via DuckDuckGo nach Unternehmen, lässt KI die Daten extrahieren.
    """
    query = f"{branche} {region} Telefon"
    results = _ddg_search(query)

    found = 0
    for res in results:
        if stop_event.is_set() or found >= max_per:
            break

        url     = res.get("url", "")
        title   = res.get("title", "")
        snippet = res.get("snippet", "")

        if not title:
            continue

        # Seiteninhalt lesen
        html    = _get(url)
        content = re.sub(r"<[^>]+>", " ", html)[:2000] if html else snippet

        extract_prompt = f"""Extrahiere aus folgendem Text Informationen über ein Unternehmen.
Antworte NUR mit einem JSON-Objekt, keine Erklärungen.

Text:
{content[:1500]}

JSON-Format (alle Felder erforderlich):
{{
  "name": "Firmenname oder leer",
  "adresse": "Straße Hausnr, PLZ Stadt oder leer",
  "telefon": "Telefonnummer oder leer",
  "website_url": "URL oder leer",
  "branche": "{branche}"
}}"""

        if ai_mode == "cloud":
            raw = _ask_claude(extract_prompt)
            finder = "claude_ai"
        elif ai_mode == "both":
            raw    = _ask_ollama(extract_prompt) if found % 2 == 0 else _ask_claude(extract_prompt)
            finder = "ollama_ai" if found % 2 == 0 else "claude_ai"
        else:
            raw    = _ask_ollama(extract_prompt)
            finder = "ollama_ai"

        # JSON aus Antwort extrahieren
        try:
            m    = re.search(r"\{[^{}]+\}", raw, re.DOTALL)
            data = json.loads(m.group(0)) if m else {}
        except Exception:
            data = {}

        name = data.get("name") or title
        if not name or len(name) < 3:
            continue

        website_url = data.get("website_url") or url
        has_web     = bool(website_url)
        web_info    = check_website(website_url) if has_web else {}

        lead = {
            "name":           name[:120],
            "adresse":        (data.get("adresse") or "")[:200],
            "stadt":          region,
            "bundesland":     "Berlin" if "Berlin" in region else "Schleswig-Holstein",
            "branche":        branche,
            "telefon":        (data.get("telefon") or "")[:50],
            "website_url":    website_url[:300] if has_web else "",
            "has_website":    int(has_web),
            "website_alter":  web_info.get("alter_jahre", -1),
            "bewertung":      0.0,
            "anz_bewertungen": 0,
            "bilder":         0,
            "finder":         finder,
            "maps_url":       "",
        }

        pts, typ         = calc_score(lead)
        lead["score"]    = pts
        lead["lead_typ"] = typ

        lead_id = db.insert(lead)
        if lead_id:
            lead["id"] = lead_id
            on_lead(lead)
            found += 1

        time.sleep(0.8)
