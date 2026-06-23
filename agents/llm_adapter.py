"""
JARVIS LLM Adapter — abstrahiert Claude API und Ollama.

JARVIS_MODE=cloud  →  AnthropicAdapter (Claude Sonnet, Tool-Use, Streaming)
JARVIS_MODE=local  →  OllamaAdapter   (qwen2.5:7b+, Tool-Use lokal, kein API-Key)

Normalisierte Events aus stream_round():
  ("text",      str)   — Text-Token für den User
  ("tool_call", dict)  — {id, name, input}  — normalisiert, mode-agnostisch
  ("done",      dict)  — {input_tokens, output_tokens}
"""
from __future__ import annotations
import json
import os
import time
from typing import Any, Generator


# ── Basis-Interface ───────────────────────────────────────────────────────────

class LLMAdapter:

    def stream_round(
        self,
        messages: list[dict],
        system: str,
        tools: list[dict],
    ) -> Generator[tuple[str, Any], None, None]:
        """
        Streams eine LLM-Runde. Yields normalisierte Events:
          ("text",      str)   — Token
          ("tool_call", dict)  — {id, name, input}
          ("done",      dict)  — {input_tokens, output_tokens}
        Wirft Exceptions bei fatalen Fehlern.
        """
        raise NotImplementedError

    def append_assistant(
        self, messages: list, round_text: str, tool_calls: list[dict]
    ) -> None:
        """Fügt die Assistenten-Antwort (mit Tool-Calls) zur messages-Liste hinzu."""
        raise NotImplementedError

    def append_tool_results(
        self, messages: list, tool_results: list[dict]
    ) -> None:
        """
        Fügt Tool-Ergebnisse zur messages-Liste hinzu.
        tool_results: [{id, name, result}]
        """
        raise NotImplementedError


# ── Anthropic Adapter ─────────────────────────────────────────────────────────

class AnthropicAdapter(LLMAdapter):

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        import anthropic as _ant
        self._client = _ant.Anthropic(api_key=api_key)
        self._model  = model

    def stream_round(self, messages, system, tools):
        usage: dict = {"input_tokens": 0, "output_tokens": 0}
        final_msg   = None

        with self._client.messages.stream(
            model=self._model,
            max_tokens=8192,
            system=system,
            tools=tools,
            messages=messages,
        ) as s:
            for event in s:
                if event.type == "content_block_delta":
                    d = event.delta
                    if d.type == "text_delta" and d.text:
                        yield ("text", d.text)

            final_msg = s.get_final_message()
            if hasattr(final_msg, "usage") and final_msg.usage:
                usage["input_tokens"]  = final_msg.usage.input_tokens or 0
                usage["output_tokens"] = final_msg.usage.output_tokens or 0

        try:
            import cost_tracker
            cost_tracker.track_api(self._model, usage["input_tokens"],
                                   usage["output_tokens"], "agent")
        except Exception:
            pass

        # Tool-Calls aus final_msg extrahieren (normalisiert)
        for block in (final_msg.content or []):
            if getattr(block, "type", None) == "tool_use":
                yield ("tool_call", {
                    "id":        block.id,
                    "name":      block.name,
                    "input":     dict(block.input) if block.input else {},
                    "_raw":      block,   # für append_assistant (Anthropic-Fidelity)
                })

        yield ("done", usage)

    def append_assistant(self, messages, round_text, tool_calls):
        content: list = []
        if round_text:
            content.append({"type": "text", "text": round_text})
        for tc in tool_calls:
            raw = tc.get("_raw")
            if raw is not None:
                content.append(raw)
            else:
                content.append({
                    "type":  "tool_use",
                    "id":    tc["id"],
                    "name":  tc["name"],
                    "input": tc["input"],
                })
        messages.append({"role": "assistant", "content": content})

    def append_tool_results(self, messages, tool_results):
        messages.append({"role": "user", "content": [
            {
                "type":        "tool_result",
                "tool_use_id": tr["id"],
                "content":     tr["result"],
            }
            for tr in tool_results
        ]})


# ── Ollama Adapter ────────────────────────────────────────────────────────────

_OLLAMA_URL = "http://127.0.0.1:11434/api/chat"


def _to_ollama_tools(anthropic_tools: list[dict]) -> list[dict]:
    """Konvertiert Anthropic-Format → Ollama-Format. input_schema → parameters."""
    return [
        {
            "type": "function",
            "function": {
                "name":        t["name"],
                "description": t["description"],
                "parameters":  t["input_schema"],
            },
        }
        for t in anthropic_tools
    ]


class OllamaAdapter(LLMAdapter):

    def __init__(self, model: str | None = None):
        self._model      = model or _default_model()
        self._tool_cache: dict[int, list[dict]] = {}

    def _ollama_tools(self, tools: list[dict]) -> list[dict]:
        key = id(tools)
        if key not in self._tool_cache:
            self._tool_cache[key] = _to_ollama_tools(tools)
        return self._tool_cache[key]

    def stream_round(self, messages, system, tools):
        import urllib.request as _req
        import urllib.error  as _uerr

        payload = json.dumps({
            "model":    self._model,
            "messages": [{"role": "system", "content": system}] + messages,
            "tools":    self._ollama_tools(tools),
            "stream":   True,
        }).encode("utf-8")

        request = _req.Request(
            _OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        try:
            with _req.urlopen(request, timeout=180) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg = obj.get("message", {})

                    # Text-Token
                    chunk = msg.get("content", "")
                    if chunk:
                        yield ("text", chunk)

                    # Tool-Calls (kommen als komplettes Objekt)
                    raw_tcs = msg.get("tool_calls")
                    if raw_tcs:
                        for i, tc in enumerate(raw_tcs):
                            fn   = tc.get("function", {})
                            name = fn.get("name", "")
                            args = fn.get("arguments", {})
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except json.JSONDecodeError:
                                    args = {}
                            yield ("tool_call", {
                                "id":    f"ollama_{name}_{i}_{int(time.time()*1000)}",
                                "name":  name,
                                "input": args,
                            })

                    if obj.get("done"):
                        break

        except _uerr.URLError as e:
            if "Connection refused" in str(e) or "WinError" in str(e) or "10061" in str(e):
                raise ConnectionError(
                    "Ollama nicht erreichbar — bitte `ollama serve` starten (Port 11434)."
                ) from e
            raise

        yield ("done", {})

    def append_assistant(self, messages, round_text, tool_calls):
        msg: dict = {"role": "assistant", "content": round_text or ""}
        if tool_calls:
            msg["tool_calls"] = [
                {"function": {"name": tc["name"], "arguments": tc["input"]}}
                for tc in tool_calls
            ]
        messages.append(msg)

    def append_tool_results(self, messages, tool_results):
        for tr in tool_results:
            messages.append({"role": "tool", "content": str(tr["result"])})


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _default_model() -> str:
    return (
        os.environ.get("JARVIS_TOOL_MODEL")
        or os.environ.get("JARVIS_LOCAL_MODEL", "qwen2.5:7b")
    )


# ── Factory ───────────────────────────────────────────────────────────────────

def get_adapter(cloud_model: str = "claude-sonnet-4-6") -> LLMAdapter:
    """
    Liest JARVIS_MODE aus .env und gibt den passenden Adapter zurück.
      local → OllamaAdapter  (kein API-Key nötig)
      cloud → AnthropicAdapter (ANTHROPIC_KEY Pflicht)
    """
    mode = os.environ.get("JARVIS_MODE", "cloud").strip().lower()

    if mode == "local":
        return OllamaAdapter(model=_default_model())

    from config import get_api_key
    return AnthropicAdapter(api_key=get_api_key(), model=cloud_model)
