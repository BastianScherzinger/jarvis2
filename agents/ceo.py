"""
JARVIS — CEO Agent. Einziger Ansprechpartner fuer den User.
Koordiniert das Team via Tool-Use und hat Zugriff auf den PC.
Unterstützt JARVIS_MODE=cloud (Claude API) und JARVIS_MODE=local (Ollama).
"""
import base64 as _b64
import concurrent.futures as _cf
import datetime
import json
import re
import time
from pathlib import Path
import anthropic
from config import get_api_key, get_mode
from agents.llm_adapter import get_adapter
from agents.tools import TOOL_DEFINITIONS, execute_tool
from agents.team import TEAM
import jarvis_log as log
import tts as _tts

_BRAIN_DIR = Path(__file__).parent.parent / "obsidian_brain"


def _brain_entry(topic: str, lines: list[str]) -> None:
    """Schreibt einen Eintrag in obsidian_brain/ — lässt das Wissen wachsen."""
    try:
        _BRAIN_DIR.mkdir(exist_ok=True)
        safe = re.sub(r'[^\w\säöüÄÖÜß-]', '', topic)[:45].strip()
        safe = re.sub(r'\s+', '_', safe) or "session"
        fname = _BRAIN_DIR / f"{safe}.md"
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        block = f"\n## {ts}\n" + "\n".join(f"- {l}" for l in lines if str(l).strip()) + "\n"
        with open(fname, 'a', encoding='utf-8') as f:
            f.write(block)
    except Exception:
        pass  # Brain-Schreiben darf nie den Haupt-Flow unterbrechen


def _ollama_enrich_brain(topic: str, context: str) -> None:
    """Lässt Ollama einen Tagebucheintrag ins Session-Journal schreiben — Hintergrundthread."""
    import os as _os, threading as _th

    model = _os.environ.get("JARVIS_LOCAL_MODEL", "")
    if not model:
        return

    def _write():
        try:
            prompt = (
                f"Beschreibe in einem präzisen deutschen Satz was JARVIS getan hat:\n{context[:400]}"
            )
            chunks = list(_ollama_token_stream(
                [{"role": "user", "content": prompt}],
                "Du bist JARVIS-Protokollant. Schreibe technische Tagebucheinträge in der dritten Person. "
                "Kein Markdown, kein Punkt am Satzende, maximal 180 Zeichen.",
            ))
            summary = "".join(chunks).strip()[:200]
            if not summary:
                return
            _BRAIN_DIR.mkdir(exist_ok=True)
            journal = _BRAIN_DIR / f"session_{datetime.date.today().isoformat()}.md"
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            with open(journal, 'a', encoding='utf-8') as f:
                f.write(f"- **{ts}** `[{topic}]` {summary}\n")
        except Exception:
            pass

    _th.Thread(target=_write, daemon=True).start()


def _strip_emojis(text: str) -> str:
    out = []
    for ch in text:
        cp = ord(ch)
        if (0x2600 <= cp <= 0x27BF or 0x1F300 <= cp <= 0x1FAFF
                or 0xFE00 <= cp <= 0xFE0F or cp == 0x200D or cp == 0x20E3):
            continue
        out.append(ch)
    return ''.join(out)


_SPOKEN_FILLER = re.compile(
    r'^(Selbstverständlich|Natürlich|Sicher|Absolut|Gewiss|Selbst|'
    r'Sehr gerne|Klar|Gerne|In der Tat|Tatsächlich)[,!.]?\s*',
    re.IGNORECASE,
)

def _extract_spoken(text: str, max_chars: int = 300) -> str:
    text = _strip_emojis(text)
    text = re.sub(r'```[\s\S]*?```', 'Code-Beispiel anbei.', text)
    text = re.sub(r'`[^`\n]+`', '', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'^#{1,6}\s+.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*{1,3}([^*\n]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,2}([^_\n]+)_{1,2}', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'^\s*\|.*\|.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[-*+\d.]+\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[-=_]{3,}$', '', text, flags=re.MULTILINE)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'[|~^\\]', '', text)
    text = re.sub(r'\n+', ' ', text).strip()
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'\([^a-zA-ZäöüÄÖÜß]*\)', '', text)
    text = _SPOKEN_FILLER.sub('', text).strip()
    if not text:
        return ''
    sentences = re.split(r'(?<=[.!?])\s+', text)
    sentences = [
        s.strip() for s in sentences
        if len(s.strip()) > 8 and not re.fullmatch(r'[\d\s.,;:-]+', s.strip())
    ]
    result = ''
    for s in sentences[:3]:
        candidate = (result + ' ' + s).strip()
        if len(candidate) <= max_chars:
            result = candidate
        else:
            break
    return result.strip() or text[:max_chars]


_usage: dict = {"input": 0, "output": 0, "requests": 0, "last_ctx": 0}

def get_usage() -> dict:
    return dict(_usage)


CEO_MODEL = "claude-sonnet-4-6"

_SYSTEM_FALLBACK = """\
Du bist JARVIS — Just A Rather Very Intelligent System.
Sprich den User als "Sir" an. Antworte kurz und präzise. Handle direkt.
"""

# System-Prompt für reinen Ollama-Text-Fallback (ohne Tool-Use)
_OLLAMA_SYSTEM = """\
Du bist JARVIS — Just A Rather Very Intelligent System. Tony Starks KI-Assistent.

PERSÖNLICHKEIT: Kompetent, loyal, leichter britischer Humor. Niemals nervös oder unsicher.

ABSOLUTE REGELN:
- Sprich den User IMMER als "Sir" an — nie beim Namen, nie mit "du" allein
- Antworte AUF DEUTSCH, kurz (1-3 Sätze genügen fast immer)
- KEIN Smalltalk. KEINE Floskeln: nie "Natürlich!", "Gerne!", "Absolut!", "Verstanden, ich werde..."
- Code: maximal korrekt, idiomatisch, kein Halbfertiges
- Bei Fehlern: Root Cause + Fix. Nicht drumherumreden.
- Meinung haben: wenn etwas ineffizient ist, kurz sagen — dann trotzdem ausführen.

KONTEXT: JARVIS ist ein Python-Flask-Dashboard (Port 5000) mit 10 Spezial-Agenten.
Du bist gerade der TEXT-FALLBACK — Tool-Use nicht verfügbar in diesem Modus.
Antworte im JARVIS-Stil mit dem Wissen das du hast.
"""


def _ollama_token_stream(history: list[dict], system: str):
    """Yields rohe Text-Chunks aus Ollama — Text-only (kein Tool-Use)."""
    import os as _os
    import urllib.request as _req
    import urllib.error as _uerr

    model = _os.environ.get("JARVIS_LOCAL_MODEL", "qwen2.5:7b")

    ollama_msgs = [{"role": "system", "content": system}]
    for m in history:
        content = m.get("content", "")
        if isinstance(content, list):
            parts = []
            for b in content:
                if isinstance(b, dict):
                    parts.append(b.get("text") or b.get("content") or "")
                elif hasattr(b, "text"):
                    parts.append(b.text)
            content = " ".join(p for p in parts if p).strip() or "(Tool-Ergebnis)"
        ollama_msgs.append({"role": m["role"], "content": str(content)})

    payload = json.dumps({
        "model": model,
        "messages": ollama_msgs,
        "stream": True,
    }).encode("utf-8")

    request = _req.Request(
        "http://127.0.0.1:11434/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with _req.urlopen(request, timeout=120) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    chunk = obj.get("message", {}).get("content", "")
                    if chunk:
                        yield chunk
                    if obj.get("done"):
                        break
                except json.JSONDecodeError:
                    continue
    except _uerr.URLError:
        yield "\n\n*Offline: Claude und Ollama nicht erreichbar. Bitte `ollama serve` starten.*"
    except Exception as exc:
        yield f"\n\n*Ollama-Fehler: {exc}*"


def _load_system_prompt() -> str:
    """Lädt CLAUDE.md als System-Prompt. Ergänzt lokales Modell und Antwort-Stil."""
    import os as _os
    claude_md = Path(__file__).parent.parent / "CLAUDE.md"
    if claude_md.exists():
        try:
            content = claude_md.read_text(encoding="utf-8").strip()

            local_model = _os.environ.get("JARVIS_LOCAL_MODEL", "")
            mode        = _os.environ.get("JARVIS_MODE", "cloud").strip().lower()
            local_info  = ""
            if local_model:
                if mode == "local":
                    local_info = (
                        f"\n\n## Aktiver Modus: LOCAL\n"
                        f"JARVIS läuft vollständig lokal via Ollama. Modell: `{local_model}` (Port 11434). "
                        f"Kein Cloud-API nötig. Tool-Use, Brain, Bilder, Videos — alles lokal."
                    )
                else:
                    local_info = (
                        f"\n\n## Aktiver lokaler KI-Fallback\n"
                        f"Konfiguriert: `{local_model}` via Ollama (Port 11434). "
                        f"Übernimmt automatisch bei Claude-Ausfall (APIConnectionError, AuthenticationError, RateLimit). "
                        f"Ollama versteht den gleichen Gesprächsverlauf, antwortet aber ohne Tool-Use."
                    )

            img_model      = _os.environ.get("JARVIS_IMAGE_MODEL", "")
            vid_model      = _os.environ.get("JARVIS_VIDEO_MODEL", "")
            higgsfield_key = _os.environ.get("HIGGSFIELD_API_KEY", "")
            media_info     = ""
            if img_model or vid_model or higgsfield_key:
                media_info = "\n\n## Medien-Generierung — Bild & Video KI\n"
                media_info += (
                    "JARVIS kann Bilder und Videos mit KI generieren — lokal UND in der Cloud.\n"
                    "NIEMALS sagen 'ich kann keine Bilder/Videos generieren' — du KANNST es!\n\n"
                )
                if img_model:
                    media_info += (
                        f"- **Bildmodell aktiv**: `{img_model}` → Tool: `generate_image`\n"
                        "  - Trigger: 'mach mir ein Bild von X', 'zeichne Y', 'generiere eine Illustration'\n"
                        "  - Prompt IMMER auf Englisch für beste Qualität\n"
                        "  - Erster Download: automatisch (einmalig 2-15 GB)\n"
                    )
                if vid_model:
                    media_info += (
                        f"- **Lokales Videomodell**: `{vid_model}` → Tool: `generate_video`\n"
                        "  - Nutze wenn kein Higgsfield-Key vorhanden. Dauert 2-15 Min.\n"
                    )
                if higgsfield_key:
                    media_info += (
                        "- **Higgsfield.ai Cloud** → Tool: `higgsfield_video` ← BEVORZUGEN für Videos!\n"
                        "  - Trigger: 'mach mir ein Video', 'higgsfield video', 'generiere einen Clip'\n"
                        "  - Modelle: dop-lite (schnell, 3 Credits), dop-preview (6), dop-turbo (beste, 9)\n"
                        "  - Auch Image-to-Video: image_url Parameter setzen\n"
                        "  - Dauert 1-3 Minuten — weit besser als lokales Modell\n"
                        "  - 10 Credits/Tag kostenlos, dann Abonnement\n"
                    )
                media_info += (
                    "- Das Ergebnis erscheint **automatisch als Bild/Video im Chat**\n"
                    "- Prompt immer auf Englisch für beste Ergebnisse\n"
                    "- Nach der Generierung kurz kommentieren was erstellt wurde\n"
                )

            return (
                content
                + local_info
                + media_info
                + "\n\n## Dashboard-Features — KRITISCH: Wie diese Features funktionieren\n"
                "\n"
                "Das JARVIS-Dashboard ist eine Webseite im Browser (localhost:5000). "
                "Alle visuellen Features (Karten, Sphere, Dropdown) sind BROWSER-UI-Elemente in JavaScript — "
                "NIEMALS versuchen diese mit run_command, search_files oder anderen PC-Tools zu steuern. Das ist falsch.\n"
                "\n"
                "### Satelliten-Ansicht (WICHTIG — genau lesen!)\n"
                "- Was es ist: Eine Leaflet.js Satelliten-Karte (ESRI World Imagery) im rechten Panel des Dashboards\n"
                "- Wo: Im Browser bei localhost:5000, rechtes Panel, hinter dem Arc-Reactor-Logo\n"
                "- Wie es aktiviert wird: Das JavaScript im Browser (app.js) ÜBERWACHT JARVIS'S ANTWORTEN.\n"
                "  Wenn JARVIS antwortet und der Text die Wörter 'Satellit' + 'aktiviert'/'an'/'öffne' enthält,\n"
                "  schaltet das Frontend die Karte AUTOMATISCH ein. JARVIS muss nur die richtigen Wörter sagen.\n"
                "- KORREKTE Reaktion wenn Sir 'Satellit an' / 'zeig den Satellit' / 'schalte Satellit an' sagt:\n"
                "  → Antworte: 'Satelliten-Ansicht aktiviert, Sir.' (kein Tool-Call nötig, kein run_command!)\n"
                "  → Das Frontend erkennt 'Satellit' + 'aktiviert' und schaltet die Karte automatisch ein.\n"
                "- KORREKTE Reaktion wenn Sir fragt ob du einen Satellit HAST:\n"
                "  → Antworte: 'Ja, Sir — Satelliten-Ansicht ist verfügbar. Soll ich die Karte aktivieren?'\n"
                "- VERBOTEN: Niemals Get-Process, search_files, run_command für Satellit aufrufen — das ist falsch!\n"
                "\n"
                "### Weitere Dashboard-Features\n"
                "- **Neural Core** (Wissenssphäre): Three.js 3D-Sphere links — zeigt obsidian_brain/ Dateien als Knoten\n"
                "- **KI-Modul-Wähler**: Dropdown oben in der Navbar — schaltet zwischen Ollama-Modellen\n"
                "- **Sprach-Ein/Ausgabe**: Mikrofon oben rechts — Whisper STT lokal + edge-tts Conrad Neural\n"
                "\n\n## Antwort-Stil\n"
                "- KÜRZE ÜBER ALLES. Einfache Antwort: 1-2 Sätze. Nie mehr als nötig.\n"
                "- KEIN Smalltalk. Kein 'Natürlich!', 'Gerne!', 'Sehr gerne!', 'Absolut!', 'Verstanden, ich werde...'.\n"
                "- Kurze Antworten: Fließtext. Komplexe: Markdown mit Struktur. Code: immer Code-Blöcke.\n"
                "- Code-Qualität: maximal. Korrekt, sicher, idiomatisch Python. Keine Halbfertigkeiten.\n"
                "- Erkläre nur WAS nicht klar ist. WAS der Code tut — nie erklären. Nur das WARUM wenn überraschend.\n"
                "- Bei Fehlern: Root Cause nennen + Fix. Nicht drumherumreden.\n"
            )
        except Exception:
            pass
    return _SYSTEM_FALLBACK


CEO_SYSTEM = _load_system_prompt()


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _jarvis_ollama_fallback(ceo, messages: list[dict], user_message: str):
    """Generator — Text-only Ollama-Fallback wenn Cloud nicht verfügbar. Kein Tool-Use."""
    fallback_text = ""
    for chunk in _ollama_token_stream(messages, _OLLAMA_SYSTEM):
        fallback_text += chunk
        yield _sse({"type": "token", "text": chunk})

    ceo.history.append({"role": "assistant", "content": fallback_text})
    _brain_entry(
        user_message[:40],
        [f"Frage: {user_message[:100]}", f"Offline-Antwort (Ollama): {fallback_text[:160]}"],
    )
    yield _sse({"type": "done", "usage": dict(_usage)})

    spoken = _extract_spoken(fallback_text) or fallback_text.strip()
    if spoken and len(spoken) > 3:
        try:
            audio_bytes, mime = _tts.speak(spoken)
            log.tool_call("tts", f"→ {len(audio_bytes)//1024}KB (Fallback): {spoken[:50]}")
            yield _sse({
                "type":      "spoken",
                "text":      spoken,
                "audio_b64": _b64.b64encode(audio_bytes).decode("ascii"),
                "mime":      mime,
                "final":     True,
            })
        except Exception as tts_e:
            log.warn(f"TTS Fallback: {tts_e}")


class JarvisCEO:
    def __init__(self):
        self._adapter  = get_adapter(cloud_model=CEO_MODEL)
        self._is_local = get_mode() == "local"
        self.history: list[dict] = []

    def _trim_history(self) -> None:
        """Hält die History unter 40 Einträgen — verhindert Context-Bloat."""
        if len(self.history) > 40:
            self.history = self.history[-30:]
            log.warn("History getrimmt auf 30 Einträge (Overnight-Schutz)")

    def stream(self, user_message: str):
        """Generator — yields SSE strings. Unterstützt Cloud (Claude) und Local (Ollama)."""
        self._trim_history()
        self.history.append({"role": "user", "content": user_message})
        messages = list(self.history)

        log.user_msg(user_message)
        log.jarvis_thinking()
        yield _sse({"type": "status", "text": "JARVIS analysiert..."})

        stream_start     = time.time()
        token_count      = 0
        accumulated_resp = ""
        _rate_retries    = 0
        _tool_rounds     = 0
        _MAX_TOOL_ROUNDS = 8   # Ollama-Schutz gegen Tool-Loop

        while True:
            round_text = ""
            tool_calls = []

            # ── LLM Stream via Adapter ────────────────────────────────────────
            try:
                for ev_type, ev_data in self._adapter.stream_round(
                    messages, CEO_SYSTEM, TOOL_DEFINITIONS
                ):
                    if ev_type == "text":
                        chunk        = ev_data
                        round_text  += chunk
                        token_count += 1
                        yield _sse({"type": "token", "text": chunk})

                    elif ev_type == "tool_call":
                        tool_calls.append(ev_data)

                    elif ev_type == "done":
                        if ev_data:
                            _in = ev_data.get("input_tokens", 0)
                            _usage["input"]    += _in
                            _usage["output"]   += ev_data.get("output_tokens", 0)
                            _usage["requests"] += 1
                            if _in:
                                _usage["last_ctx"] = _in

                _rate_retries = 0

            # ── Fehlerbehandlung ──────────────────────────────────────────────
            except anthropic.RateLimitError as e:
                if self._is_local:
                    log.warn(f"Unerwarteter Fehler im Local Mode: {e}")
                    yield _sse({"type": "token", "text": f"\n\n*Fehler: {e}*"})
                    yield _sse({"type": "done", "usage": dict(_usage)})
                    break
                _rate_retries += 1
                wait_s = 15 * _rate_retries
                log.warn(f"Rate-Limit (429) — warte {wait_s}s (Versuch {_rate_retries}): {e}")
                yield _sse({"type": "token",
                            "text": f"\n\n*Rate-Limit — kurze Pause ({wait_s}s)...*"})
                if _rate_retries <= 3:
                    time.sleep(wait_s)
                    continue
                log.warn("Rate-Limit erschöpft — Ollama Fallback")
                yield _sse({"type": "token",
                            "text": "\n\n*Claude Rate-Limit — lokales Modell übernimmt.*\n\n"})
                yield from _jarvis_ollama_fallback(self, messages, user_message)
                break

            except (anthropic.APIConnectionError, anthropic.AuthenticationError) as e:
                if self._is_local:
                    log.warn(f"Unerwarteter Fehler im Local Mode: {e}")
                    yield _sse({"type": "token", "text": f"\n\n*Fehler: {e}*"})
                    yield _sse({"type": "done", "usage": dict(_usage)})
                    break
                log.warn(f"Claude nicht erreichbar ({type(e).__name__}) — Ollama Fallback")
                yield _sse({"type": "token",
                            "text": "*[Claude offline — lokales Modell aktiv]*\n\n"})
                yield from _jarvis_ollama_fallback(self, messages, user_message)
                break

            except anthropic.BadRequestError as e:
                log.warn(f"BadRequest (400) — History reset: {e}")
                self.history.clear()
                yield _sse({"type": "token",
                            "text": "\n\n*Konversation zurückgesetzt. Bitte erneut senden.*"})
                yield _sse({"type": "done", "usage": dict(_usage)})
                break

            except ConnectionError as e:
                # Ollama nicht erreichbar (local mode)
                log.warn(f"Ollama Verbindung fehlgeschlagen: {e}")
                yield _sse({"type": "token", "text": f"\n\n*{e}*"})
                yield _sse({"type": "done", "usage": dict(_usage)})
                break

            except Exception as e:
                log.warn(f"API-Fehler: {type(e).__name__}: {e}")
                err_str = str(e).lower()
                if (not self._is_local and
                        any(kw in err_str for kw in
                            ("connection", "timeout", "network", "ssl", "resolve", "unreachable"))):
                    log.warn("Verbindungsfehler — Ollama Fallback")
                    yield _sse({"type": "token",
                                "text": "*[Verbindungsfehler — lokales Modell]*\n\n"})
                    yield from _jarvis_ollama_fallback(self, messages, user_message)
                else:
                    self.history.clear()
                    yield _sse({"type": "token", "text": f"\n\n*Fehler: {e}*"})
                    yield _sse({"type": "done", "usage": dict(_usage)})
                break

            # ── Tool-Use Round ────────────────────────────────────────────────
            if tool_calls:
                # Schutz gegen endlose Tool-Loops (besonders bei Ollama)
                _tool_rounds += 1
                if _tool_rounds > _MAX_TOOL_ROUNDS:
                    log.warn(f"Tool-Loop-Schutz: {_tool_rounds} Runden — stoppe")
                    accumulated_resp += round_text + "\n\n*Maximale Tool-Runden erreicht.*"
                    self.history.append({"role": "assistant", "content": accumulated_resp})
                    yield _sse({"type": "done", "usage": dict(_usage)})
                    break

                self._adapter.append_assistant(messages, round_text, tool_calls)

                if round_text.strip():
                    log.jarvis_thinking(round_text)
                    spoken_inter = _extract_spoken(round_text) or round_text.strip()
                    if spoken_inter and len(spoken_inter) > 3:
                        try:
                            audio_bytes, mime = _tts.speak(spoken_inter)
                            log.tool_call("tts",
                                          f"→ {len(audio_bytes)//1024}KB (zwischendurch): {spoken_inter[:50]}")
                            yield _sse({
                                "type":      "spoken",
                                "text":      spoken_inter,
                                "audio_b64": _b64.b64encode(audio_bytes).decode("ascii"),
                                "mime":      mime,
                                "final":     False,
                            })
                        except Exception as e:
                            log.warn(f"TTS intermediate: {e}")

                tool_results_normalized: list[dict] = []

                for tc in tool_calls:
                    tool_name  = tc["name"]
                    tool_input = tc["input"]
                    tool_id    = tc["id"]

                    extra = {}
                    if tool_name == "delegate_to_agent":
                        agent_key = tool_input.get("agent", "")
                        agent_obj = TEAM.get(agent_key)
                        task_text = tool_input.get("task", "")
                        extra = {
                            "agent_key":  agent_key,
                            "agent_name": agent_obj.name if agent_obj else agent_key,
                            "agent_role": agent_obj.role if agent_obj else "",
                        }
                        log.agent_start(agent_key,
                                        agent_obj.name if agent_obj else agent_key,
                                        task_text)
                    else:
                        detail = (tool_input.get("path") or tool_input.get("command") or
                                  tool_input.get("pattern") or tool_input.get("url") or "")
                        log.tool_call(tool_name, str(detail))

                    yield _sse({
                        "type":    "tool_call",
                        "tool":    tool_name,
                        "input":   tool_input,
                        "tool_id": tool_id,
                        **extra,
                    })

                    t0 = time.time()
                    try:
                        with _cf.ThreadPoolExecutor(max_workers=1) as _pool:
                            _fut = _pool.submit(execute_tool, tool_name, tool_input)
                            while not _fut.done():
                                yield ": keepalive\n\n"
                                time.sleep(2)
                            result = _fut.result()
                    except Exception as exc:
                        result = f"Tool-Fehler: {exc}"
                        log.tool_error(tool_name, str(exc))
                        yield _sse({"type": "tool_error", "tool": tool_name,
                                    "tool_id": tool_id, "error": str(exc)})

                    elapsed_t  = time.time() - t0
                    str_result = str(result)

                    if tool_name == "delegate_to_agent":
                        agent_key = tool_input.get("agent", "")
                        agent_obj = TEAM.get(agent_key)
                        log.agent_done(agent_key,
                                       agent_obj.name if agent_obj else agent_key,
                                       elapsed_t)
                        task_snippet = tool_input.get("task", "")[:80]
                        _brain_entry(
                            f"Agent {agent_key}",
                            [f"Agent: {agent_obj.name if agent_obj else agent_key}",
                             f"Aufgabe: {task_snippet}",
                             f"Ergebnis: {str_result[:120]}"],
                        )
                        _ollama_enrich_brain(
                            f"Agent:{agent_key}",
                            f"Agent {agent_obj.name if agent_obj else agent_key} "
                            f"löste: {task_snippet} → {str_result[:200]}"
                        )
                    else:
                        log.tool_done(tool_name, len(str_result), elapsed_t)
                        detail = (tool_input.get("path") or tool_input.get("command") or
                                  tool_input.get("url") or tool_input.get("query") or
                                  tool_input.get("pattern") or "")
                        _brain_entry(
                            tool_name,
                            [f"Tool: {tool_name}",
                             f"Aktion: {str(detail)[:80]}",
                             f"Ergebnis: {str_result[:120]}"],
                        )
                        _ollama_enrich_brain(
                            tool_name,
                            f"Tool {tool_name} auf '{str(detail)[:80]}' → {str_result[:200]}"
                        )

                    yield _sse({
                        "type":    "tool_result",
                        "tool":    tool_name,
                        "tool_id": tool_id,
                        "result":  str_result[:2000],
                    })

                    hist_content = (str_result if len(str_result) <= 5000
                                    else str_result[:5000] + "\n... [gekürzt]")
                    tool_results_normalized.append({
                        "id":     tool_id,
                        "name":   tool_name,
                        "result": hist_content,
                    })

                accumulated_resp += round_text
                self._adapter.append_tool_results(messages, tool_results_normalized)

            # ── Finale Antwort ────────────────────────────────────────────────
            else:
                accumulated_resp += round_text
                self.history.append({"role": "assistant", "content": accumulated_resp})
                log.response_done(elapsed=time.time() - stream_start, tokens=token_count)

                _brain_entry(
                    user_message[:40],
                    [f"Frage: {user_message[:100]}",
                     f"Antwort: {round_text[:160]}"],
                )
                _ollama_enrich_brain(
                    "Gespräch",
                    f"Sir fragte: {user_message[:120]} — JARVIS antwortete: {round_text[:200]}"
                )

                yield _sse({"type": "done", "usage": dict(_usage)})

                spoken = _extract_spoken(round_text) or round_text.strip()
                if spoken and len(spoken) > 3:
                    try:
                        audio_bytes, mime = _tts.speak(spoken)
                        log.tool_call("tts", f"→ {len(audio_bytes)//1024}KB: {spoken[:50]}")
                        yield _sse({
                            "type":      "spoken",
                            "text":      spoken,
                            "audio_b64": _b64.b64encode(audio_bytes).decode("ascii"),
                            "mime":      mime,
                            "final":     True,
                        })
                    except Exception as e:
                        log.warn(f"TTS fehlgeschlagen: {e}")
                else:
                    log.warn(f"TTS: kein Text (round_text={repr(round_text[:40])})")
                break

    def reset(self):
        self.history.clear()
        for agent in TEAM.values():
            agent.reset()
