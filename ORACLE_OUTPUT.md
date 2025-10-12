# LLM Interactive Proxy - Project Overview

## Project Purpose
The LLM Interactive Proxy is a middleware gateway that sits between LLM-aware clients and LLM backend providers. It serves as a "swiss-army knife" for working with language models and agentic workflows by presenting multiple front-end APIs (OpenAI, Anthropic, Gemini) while routing to various providers of choice.

## Core Architecture
The proxy operates as a translation and routing layer:
- **Front-end APIs**: Exposes OpenAI, Anthropic, and Gemini compatible endpoints
- **Core Proxy Logic**: Handles routing, translation, commands, and safety features
- **Back-end Connectors**: Connects to OpenAI, Anthropic, Gemini, OpenRouter, ZAI, Qwen, and other providers

## Key Features

### Compatibility
- Multiple front-ends (OpenAI, Anthropic, Gemini) with many backend providers
- Protocol translation between different API formats
- Streaming support across all providers
- OpenAI Responses API for structured JSON output with schema validation

### Reliability
- Failover routing with fallback models/providers
- Automated API key rotation to maximize free tiers
- Rate limiting and context window enforcement

### Safety & Integrity
- Loop detection to prevent infinite patterns
- Dangerous command prevention for destructive actions
- API key redaction in prompts and logs
- Brute-force protection with IP-based blocking
- Automatic token refresh for OAuth backends

### Control & Ergonomics
- Dynamic model switching with in-chat commands (`!/backend(...)`, `!/model(...)`)
- Model name rewriting with regex-based rules
- Force model override for all requests
- Planning-phase strong model overrides for better initial analysis

### Advanced Capabilities
- **LLM Assessment System**: Monitors conversation quality and detects unproductive patterns
- **Tool Call Reactor**: Event-driven system to intercept and modify tool calls
- **Intelligent Session Management**: Automatic session continuity detection without requiring client session IDs
- **Edit-Precision Tuning**: Automatic parameter adjustment for precise file editing tasks
- **Pytest Output Compression**: Automatically compresses verbose test output

## Supported Providers

### Front-ends
- OpenAI Chat Completions (`/v1/chat/completions`)
- OpenAI Responses (`/v1/responses`)
- Anthropic Messages (`/anthropic/v1/messages`)
- Google Gemini (`/v1beta/models`)

### Back-ends
- OpenAI, OpenAI OAuth, Anthropic, Anthropic OAuth
- Google Gemini (API key, OAuth, GCP-billed, CLI Agent with ACP)
- OpenRouter, ZAI, Qwen OAuth
- Multiple OAuth-based providers for free tier access

## Current Development Status
Based on the git status, the project is currently in a cherry-pick operation with conflicts in:
- `src/core/services/tool_call_reactor_middleware.py`
- `tests/unit/core/services/test_tool_call_reactor_middleware.py`

There are also modified files across connectors (OpenRouter, Qwen OAuth) and various test files, indicating active development in the tool call reactor system and connector functionality.

## Development Guidelines
- Follow PEP 8 with type hints
- Use ruff for linting and black for formatting
- Write tests first (TDD approach)
- Maintain SOLID principles and modular architecture
- Prefer f-strings for string formatting
- Use custom exception hierarchy for error handling

## Quick Start
```bash
export OPENAI_API_KEY=...
python -m src.core.cli --default-backend openai
```

The proxy is configured to work with existing tools by simply pointing them to the proxy endpoint instead of direct LLM providers.