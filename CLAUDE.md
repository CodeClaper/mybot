# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- Run tests: `pytest`
- Run a single test: `pytest tests/path/to/test.py::test_name -v`
- Lint: `ruff check .`
- Format: `ruff format .`
- Run interactive agent: `mybot agent`
- Run gateway (WeChat): `mybot gateway`
- Onboarding: `mybot onboard`

## Architecture Overview

mybot is an event-driven AI assistant framework built on an async message bus. The core flow: **Chat Channel → MessageBus → AgentLoop → LLM Provider → Tools → Response**.

### Message Bus (`mybot/bus/`)
Central async pub/sub using `asyncio.Queue`. Two channels: `inbound` (from chat channels) and `outbound` (to chat channels). Key types: `InboundMessage` (has `channel`, `chat_id`, `session_key = "{channel}:{chat_id}"`) and `OutboundMessage`. All components communicate through the bus — nothing calls anything directly.

### Agent Loop (`mybot/agent/loop.py`)
The processing engine. Per message it:
1. Checks for built-in commands (`/new`, `/history`, `/help`) via `CommandRouter`
2. Builds LLM context (system prompt + history) via `ContextBuilder`
3. Runs an iterative agent loop: calls the LLM provider, executes any tool calls, repeats until a final text response or max iterations (100)
4. Saves session to JSONL and publishes response

### System Prompt (`mybot/context/context.py`)
Assembled from:
- **Identity** — agent name ("mybot"), runtime info, workspace path, platform policy
- **Always-active skills** — skills with `always: true` that are injected into every system prompt
- **Skills summary** — list of all available skills with descriptions (full content loaded on-demand when the agent reads the SKILL.md)

### Providers (`mybot/providers/`)
- `BaseProvider` ABC with `chat()` returning `LLMResponse` (includes `tool_calls`, `reasoning_content`, `thinking_blocks`)
- `DefaultProvider` — uses **litellm** (`litellm.acompletion()`) for broad provider support
- `LocalProvider` — uses OpenAI SDK directly for local models (Ollama, etc.)
- Provider is selected by matching the model prefix against `PROVIDERS` registry
- Config supports: anthropic, openai, gemini, openrouter, deepseek, groq, zhipu, vllm, minimax, moonshot, local

### Tools (`mybot/tools/`)
Four default tools registered on startup: `ShellTool` (`exec`), `WebSearchTool` (`web_search`, SerpAPI), `WebFetchTool` (`web_fetch`, readability-lxml), `MessageTool` (`message`, send to chat channels). All registered in `ToolRegistry`.

### Skills (`mybot/agent/skill.py`)
Skills are Markdown files with YAML frontmatter at `mybot/skills/{name}/SKILL.md` (built-in) or `~/.mybot/workspace/skills/{name}/SKILL.md` (user). Only metadata (name + description) is in-context by default; full content loads when the agent reads the file.

### Channels (`mybot/channels/`)
Chat backends implementing `BaseChannel` (login, start, stop, send). Currently only `WeixinChannel` (WeChat ilink API, long-polling with QR login). `ChannelManager` handles lifecycle and routing via `ChannelRegistry` (auto-discovers by scanning for subclasses).

### Sessions (`mybot/context/session.py`)
Conversations persisted as JSONL files in `~/.mybot/workspace/sessions/`. Configurable `memory_window` controls history length. Smart truncation handles orphaned tool results.

### CLI (`mybot/cli/commands.py`)
Four commands via Typer: `onboard` (interactive config), `agent` (interactive chat), `gateway` (agent loop + channel manager), `channels login` (authenticate a channel).

### Config (`mybot/config/schema.py`)
Pydantic-based JSON config at `~/.mybot/config.json`. Sections: agents, channels, gateway, providers, tools. Use `mybot onboard` for interactive setup.

## Key Patterns

- **Bus-driven architecture**: components never import each other directly — they communicate through `MessageBus.publish_inbound()` / `publish_outbound()`
- **liteLLM model naming**: model strings follow the `provider/model` convention (e.g., `deepseek/deepseek-chat`)
- **Provider matching**: provider config is selected by matching the model prefix against provider names in the registry
- **Skill availability**: skills specify `requires` (bins, env vars) to declare dependencies; unavailable skills are flagged in the summary
