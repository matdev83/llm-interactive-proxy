<!-- OPENSPEC:START -->
# OpenSpec Instructions

These instructions are for AI assistants working in this project.

Always open `@/openspec/AGENTS.md` when the request:
- Mentions planning or proposals (words like proposal, spec, change, plan)
- Introduces new capabilities, breaking changes, architecture shifts, or big performance/security work
- Sounds ambiguous and you need the authoritative spec before coding

Use `@/openspec/AGENTS.md` to learn:
- How to create and apply change proposals
- Spec format and conventions
- Project structure and guidelines

Keep this managed block so 'openspec update' can refresh the instructions.

<!-- OPENSPEC:END -->

# Agent Onboarding & Development Guidelines

## Project Identity

**Universal LLM Proxy** built with **FastAPI (Async)** using **Staged Initialization**.

- **Core Features**: Traffic routing, failover, accounting, and byte-precise **CBOR wire captures**.
- **Architecture**: Service-based (DI), Staged startup (`src/core/app/stages`), Adapter pattern for LLM backends.

## Quick Start

1. **Environment**: Windows-based. ALWAYS use `./.venv/Scripts/python.exe`.
2. **Config**: `cp config/config.example.yaml config/config.yaml` (if missing).
3. **Start**: `./.venv/Scripts/python.exe -m src.core.cli`
4. **Docs**: Check `docs/` for architecture deep-dives.

## Key Architecture Paths

| Path | Purpose |
|------|---------|
| `src/core/cli.py` | **Entry Point**. CLI args -> Config -> App Builder. |
| `src/core/app/stages/` | **Startup Logic**. Infrastructure -> Services -> Backends -> Controllers. |
| `src/connectors/` | **Backends**. Implementations for OpenAI, Gemini, Anthropic, etc. |
| `src/core/simulation/` | **Debugging**. Traffic replay & inspection tools (`capture_reader.py`). |
| `var/wire_captures_cbor/` | **Data**. Binary captures of all traffic (pair with `var/logs/`). |

## Commands & Workflow

**Rule**: Edit `pyproject.toml` for deps. **NO** manual `pip install`. **NO** emojis.

| Action | Command |
|--------|---------|
| **Test (Fast)** | `./.venv/Scripts/python.exe -m pytest` (skips slow/integration) |
| **Test (Full)** | `./.venv/Scripts/python.exe -m pytest -m "integration or unit"` |
| **Lint/Fix** | `./.venv/Scripts/python.exe -m ruff --fix check .` |
| **Format** | `./.venv/Scripts/python.exe -m black .` |
| **Inspect** | `./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py <file> --detect-issues` |

## Quality & Testing Standards

1. **TDD**: Write test -> Fail -> Code -> Pass.
2. **Verify**: Run **directly related tests** first. Fix until green.
3. **Regression**: Run full suite after multi-file changes.
4. **Style**: PEP 8, Async/Await correctness, Exception Hierarchy (`LLMProxyError`).
5. **Safety**: Never remove features without explicit request.

## Common Pitfalls

- **Async**: Use `await` for all I/O. Don't block the event loop.
- **Paths**: Use `pathlib` or `/` forward slashes (Windows accepts them).
- **Errors**: Don't use bare `except Exception`. Log with `exc_info=True`.
