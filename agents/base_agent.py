from dataclasses import dataclass, field
from typing import Any
import anthropic
from config import get_api_key, get_mode

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        key = get_api_key()
        if not key:
            raise RuntimeError(
                "Cloud-Modus benötigt ANTHROPIC_KEY in .env "
                "(oder JARVIS_MODE=local für lokalen Betrieb setzen)"
            )
        _client = anthropic.Anthropic(api_key=key)
    return _client


def _ollama_chat(messages: list[dict], system: str) -> str:
    """Synchroner Ollama-Chat für Spezial-Agenten — kein Streaming, kein Tool-Use."""
    import urllib.request as _req
    import urllib.error   as _uerr
    import json as _json
    import os   as _os

    model = (
        _os.environ.get("JARVIS_TOOL_MODEL")
        or _os.environ.get("JARVIS_LOCAL_MODEL", "qwen2.5:7b")
    )
    payload = _json.dumps({
        "model":    model,
        "messages": [{"role": "system", "content": system}] + messages,
        "stream":   False,
    }).encode("utf-8")

    req = _req.Request(
        "http://127.0.0.1:11434/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with _req.urlopen(req, timeout=300) as resp:
            obj = _json.loads(resp.read())
        return obj["message"]["content"]
    except _uerr.URLError as e:
        raise ConnectionError(
            "Ollama nicht erreichbar — bitte `ollama serve` starten (Port 11434)."
        ) from e


@dataclass
class AgentMessage:
    role: str
    content: str


@dataclass
class Agent:
    name: str
    role: str
    description: str
    system_prompt: str
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 8096
    history: list[AgentMessage] = field(default_factory=list)

    def chat(self, user_message: str, context: dict[str, Any] | None = None) -> str:
        system = self.system_prompt
        if context:
            context_str = "\n\n".join(f"[{k}]\n{v}" for k, v in context.items())
            system += f"\n\n## Kontext vom Team:\n{context_str}"

        self.history.append(AgentMessage(role="user", content=user_message))
        messages = [{"role": m.role, "content": m.content} for m in self.history]

        if get_mode() == "local":
            reply = _ollama_chat(messages, system)
        else:
            response = get_client().messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=messages,
            )
            reply = response.content[0].text

        self.history.append(AgentMessage(role="assistant", content=reply))
        return reply

    def reset(self):
        self.history.clear()

    def __str__(self) -> str:
        return f"[{self.role}] {self.name}"
