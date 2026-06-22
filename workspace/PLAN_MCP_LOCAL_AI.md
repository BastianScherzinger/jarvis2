# Plan — MCP-Tools für lokale KIs

> Ziel: Lokale Ollama-Modelle (z.B. `qwen2.5-coder:32b`) befähigen, MCP-Tools autonom zu nutzen, um Landing-Pages (Django-Template, `content.json`-gesteuert) nachts auf der GPU zu bauen/verbessern — ohne Claude-API-Kosten. (Erstellt vom Agenten-Team.)

## 0. Executive Summary
Ollama-Modelle sprechen **kein** natives MCP. MCP ist ein Protokoll **zwischen Host und Tool-Servern** (JSON-RPC), nicht zwischen Host und Modell. Die Brücke ist immer:
```
Ollama-Modell ──tool_calls(JSON)──► unser Agent (Python) ──JSON-RPC──► MCP-Server
                                          │ (übersetzt Ollama-Tool ⇄ MCP-Tool 1:1)
```
Wir bauen `mcp_bridge.py`, das (1) MCP-Server als Subprozesse (stdio) startet, (2) deren `tools/list` in das Ollama-`tools`-Schema übersetzt, (3) einen Tool-Loop fährt: Modell → tool_calls → MCP `call_tool` → Ergebnis zurück, bis fertig.

**Kritischer Befund:** `qwen2.5-coder:32b` trägt in Ollama **kein "Tools"-Badge** (Chat-Template exponiert die Tools-API nicht zuverlässig). Für die **Orchestrierung** ein Modell mit nativem Tool-Support nehmen (`qwen2.5:32b-instruct`, `llama3.1+`, `qwen3`); die **Code-Generierung** an `qwen2.5-coder:32b` als reines Sub-Tool delegieren (Two-Model-Split).

## 1. MCP technisch (Kurz)
JSON-RPC 2.0 zwischen Host und Servern. Transports: **stdio** (Subprozess, lokal — unsere Wahl) oder SSE/HTTP (remote). Nötige Calls: `initialize`, `tools/list` (liefert name/description/inputSchema), `tools/call` ({name, arguments} → content). Mehr braucht die Bridge nicht.

## 2. Drei Optionen, wie Ollama MCP-Tools nutzt
- **(a) Natives Tool-Calling** (bevorzugt fürs Orchestrator-Modell): `ollama.chat(model, messages, tools=[...])`; Antwort enthält `message.tool_calls`; Ergebnis als `role:"tool"`-Message zurück. Modelle mit Badge: `qwen2.5:*-instruct`, `llama3.1/3.2`, `qwen3`, `mistral-nemo`.
- **(b) Adapter/Bridge** (unsere Architektur): MCP `tools/list` → 1:1 auf Ollama-`function.parameters` mappen (beides JSON-Schema). Bei tool_call → `session.call_tool(name, args)`.
- **(c) ReAct-Loop** (Fallback ohne Badge, z.B. `qwen2.5-coder`): Modell gibt JSON `Thought/Action/Action Input`, Parser ruft MCP, hängt `Observation` an. `format="json"` erzwingen + strikter Parser mit Retry.

## 3. Sinnvolle MCP-Server
| Server | Zweck | Priorität |
|--------|-------|-----------|
| Filesystem (`server-filesystem`) | content.json/Templates/Assets — **gescopt auf Seitenordner** | Pflicht |
| Playwright (`@playwright/mcp`) | Seite öffnen, Screenshot, Konsolen-/Netzwerkfehler | Pflicht |
| Git (`mcp-server-git`) | Branch/Commit je Verbesserung, Revert bei Regression | Hoch |
| Fetch/Web | Referenzen/Bilder abrufen | Mittel |
| Eigener „design-pro"-MCP (FastMCP) | `apply_design_rules`, `check_contrast`, `lint_css`, `render_check` | Mittel (USP) |

**Nicht alle Tools ans Modell** — pro Aufgabe ein minimales Toolset (5–10). Der bestehende `render_check` bleibt erste Wahl (schnell, deterministisch); Playwright nur fürs visuelle Urteil.

## 4. Architektur `mcp_bridge.py`
```
night_runner.py            — Seiten-Queue
  └─ OllamaReActAgent       — Tool-Loop, Step-/Zeit-Budget, Logging
       └─ McpBridge         — startet MCP-Server, list_tools, call_tool, Schema-Mapping
            ├─ Filesystem MCP (stdio, cwd=Seitenordner)
            ├─ Playwright MCP (stdio)
            ├─ Git MCP        (stdio)
            └─ design-pro MCP (FastMCP)
```
- **McpBridge:** pro Server `StdioServerParameters` → `stdio_client` → `ClientSession.initialize()`; Tool-Namen mit Server-Präfix (`fs__write_file`); `to_ollama_tools()` (Schema-Mapping/Normalisierung); `call()` mit Fehler-/Timeout-Kapselung (nie Exception nach oben).
- **OllamaReActAgent:** System-Prompt + Tools an `ollama.chat`; solange tool_calls → ausführen, `role:"tool"` anhängen, Step-Budget dekrementieren; Abbruch bei Final/Budget/Fehlerserie; nach jedem Zyklus `render_check` als Gate.

## 5. Sicherheit / Sandbox
Das Modell ist nicht vertrauenswürdig — die Bridge ist die Policy-Schicht.
- **Pfad-Beschränkung:** Filesystem-MCP nur mit dem Seitenordner als Root; zusätzlich `realpath` + `startswith`-Check gegen `..`/Symlinks.
- **Keine Secrets ins Modell:** `.env`/Keys nie im Root/Prompt/Tool-Ergebnis; Secret-Redaction-Filter (Regex `sk-`, `key=`).
- **Keine generische Shell** ans Nacht-Modell — nur kuratierte Tools (write_file, render_check, screenshot, git_commit).
- **Timeouts** je call + Gesamt-Budget je Seite; Subprozesse bei Hang killen.
- **Git als Sicherheitsnetz:** Branch je Seite, Commit nur bei grünem Gate, Revert bei Regression.

## 6. Umsetzungsphasen
Libs: `mcp` (offizielles Python-SDK, Client + FastMCP), `ollama` (ollama-python), `anyio/asyncio`, Node/npx für die JS-MCP-Server. Bestehendes wiederverwenden: `render_check`, content.json-Logik, `local_tools.py`, design-pro-Skill.
- **P0 Spike:** Filesystem-MCP per stdio, `list_tools` + `write_file` aus Python.
- **P1 Bridge-Kern:** Multi-Server-Start, Schema-Mapping, `call()` + Tests.
- **P2 ReAct-Agent:** `qwen2.5:32b-instruct`, Step-Budget, Logging, Minimal-Toolset (fs+render_check).
- **P3 Visuelle Schleife:** Playwright + Git-MCP; Gate vor Commit.
- **P4 design-pro-MCP:** FastMCP-Server.
- **P5 Nacht-Integration:** `night_runner.py` Queue + Report; Coder-Split optional.
- **P6 Hardening:** Sandbox-/Traversal-/Secret-Tests, Timeout-Recovery, Eval-Suite (% grün ohne Mensch).

## 7. Grenzen lokaler Modelle + Gegenmaßnahmen
| Risiko | Gegenmaßnahme |
|--------|---------------|
| coder:32b ohne Tools-Badge | Orchestrierung mit `:32b-instruct`; Coder als Code-Sub-Tool |
| Kaputte Tool-Args | `format="json"`/Grammar, strikter Parser + Retry, Schema-Validierung |
| Degradation bei vielen Tools | minimales Toolset (5–10), kurze Beschreibungen |
| Endlosschleifen | hartes Step-/Zeit-Budget, Abbruch nach N gleichen Calls |
| Schwaches visuelles Urteil | deterministische Gates (render_check, Kontrast/Lint) statt Modell-Urteil |
| Regressionen | Git-Branch + grünes Gate vor Commit, Auto-Revert |
| Kontext-Überlauf | Tool-Outputs trunkieren, nur Diffs |

**Leitprinzip:** Determinismus außerhalb des Modells — das Modell *schlägt vor*, Bridge + Gates *entscheiden*. So bleibt der Nacht-Batch auch mit mittelmäßigem lokalem Tool-Caller stabil.

## Quellen
Ollama Tool-Calling-Doku · Ollama Library qwen2.5-coder · Qwen-Ollama-Guide · MCP Python SDK (github.com/modelcontextprotocol/python-sdk, PyPI `mcp`) · modelcontextprotocol.io „Build an MCP client".
