# Phase 0 Audit Notes – OpenAI Codex Connector

## Overview
Initial inventory of Kilo/Cline-specific behaviors baked into the Codex connector and streaming pipeline. Line references use the current repository state at the time of review.

## Connector (`src/connectors/openai_codex.py`)
- `._codex_system_prompt()` hardcodes the Codex CLI system prompt for every request (`instructions` field) regardless of client needs (lines 54-126, 451-468).
- `_default_user_instructions()` loads `AGENTS.md` and `_build_user_instructions_block()` wraps all system prompts in a `<user_instructions>` XML block (lines 267-304), mirroring KiloCode expectations.
- `_build_environment_context_block()` injects environment metadata as `<environment_context>` XML regardless of client protocol (lines 305-333).
- `_build_codex_tools()` returns the Kilo tool schema (shell/apply_patch/view_image) with Codex-specific grammar hints (lines 334-403); no capability-based selection exists.
- `_build_codex_input_items()` converts assistant/tool messages into `output_text` events that assume textual renderers, again emitting XML for tool responses (lines 404-452).
- `_build_codex_payload()` always enables streaming, forces the bundled prompt, and sets `prompt_cache_key` / `include` flags to match the CLI (lines 432-468). No passthrough detection yet.

## Translation Layer (`src/core/domain/translation.py`)
- `_format_tool_call_text()` emits the Kilo XML envelope for `shell`, `apply_patch`, and `view_image` tool calls; fallback text also references "[Tool {name} invoked]" (lines 76-167).
- Streaming handlers (`response.function_call_arguments.*`, `response.output_item.done`, `response.custom_tool_call`, etc.) inject `_tool_call_text` and set `content` to the XML block (lines 1631-1811), forcing textual tool-call deltas even when canonical `tool_calls` is present.

## Translation Service (`src/core/services/translation_service.py`)
- `from_domain_to_openai_stream_chunk()` inspects `_tool_call_text` and rewrites the delta `content` to the XML text for clients (lines 360-405), cementing the Kilo renderer into the core pipeline.

## Agent Detection
- Broader codebase tracks `session.agent == "cline"` (`src/core/services/response_manager_service.py:235-352`, `src/core/domain/session.py:654-670`, `src/agents.py`), but connector/translator do not currently surface capability objects—logic branches directly on the agent flag.

## Tests
- `tests/unit/connectors/test_openai_codex_codex_cli.py` asserts that the payload contains the `<user_instructions>` / `<environment_context>` XML and Codex CLI prompt (lines 23-87), locking in Kilo behaviors.

## Gaps Identified
- No capability abstraction: all behavior assumes Kilo/Codex CLI flow.
- No passthrough path for native Codex payloads.
- Renderer logic lives inside translation rather than behind an interface.
- Prompt/tool schema customization is impossible without editing code.

These items feed Phase 1 tasks: introduce a capability resolver, isolate the renderer, and allow passthrough/customizable prompts without breaking existing expectations.
