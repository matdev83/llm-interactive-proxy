# Project Context

## Purpose
The LLM Interactive Proxy is a universal middleware that sits between LLM-aware clients and backend providers (OpenAI, Anthropic, Gemini, etc.). Its goal is to allow any LLM application to work with any model by handling protocol translation, traffic routing, API key rotation, traffic inspection, and safety enforcement. It enables seamless integration, failover, and debugging capabilities for AI applications.

## Tech Stack
- **Language**: Python 3.10+
- **Framework**: FastAPI (Async)
- **HTTP Client**: httpx
- **Data Validation**: Pydantic v2
- **Testing**: pytest (asyncio, xdist, httpx-mock, freezegun)
- **Linting & Formatting**: Ruff, Black, Mypy
- **Logging**: structlog
- **Serialization**: CBOR2 (for wire captures)

## Project Conventions

### Code Style
- Follow PEP 8 guidelines.
- Use **Black** for formatting and **Ruff** for linting.
- **Async/Await** is mandatory for I/O operations; avoid blocking the event loop.
- Use `pathlib` for file paths or forward slashes (Windows compatible).
- Explicit exception handling with `LLMProxyError` hierarchy; log with `exc_info=True`.

### Architecture Patterns
- **Staged Initialization**: Startup logic is organized into stages (`src/core/app/stages`).
- **Dependency Injection (DI)**: Service-based architecture.
- **Adapter Pattern**: Used for LLM backends (`src/connectors`) to normalize different provider APIs.
- **Middleware Pipeline**: Core logic processes requests/responses through a chain of middleware (Routing, Translation, Safety).

### Testing Strategy
- **TDD**: Write tests before code.
- **Unit Tests**: Fast, isolated tests.
- **Integration Tests**: Verify interactions between components.
- **Markers**: Use markers like `slow`, `integration`, `unit` to categorize tests.
- Run `pytest` for fast feedback; run full suite before PRs.

### Git Workflow
- Create feature branches.
- Commit changes with descriptive messages.
- Update `pyproject.toml` for dependencies (no manual `pip install`).

## Domain Context
- **Frontends**: The API surfaces exposed by the proxy (e.g., OpenAI-compatible, Anthropic-compatible).
- **Backends**: Connectors to external LLM providers (OpenAI, Gemini, Anthropic, OpenRouter, etc.).
- **Routing**: Logic to determine which backend handles a request.
- **Wire Captures**: Binary (CBOR) recording of full request/response traffic for debugging (`var/wire_captures_cbor`).
- **Safety**: Features like dangerous command blocking, file sandboxing, and loop detection.

## Important Constraints
- **Environment**: Primary development environment is Windows.
- **Dependencies**: Managed strictly via `pyproject.toml`.
- **Safety**: Features should never be removed without explicit request.

## External Dependencies
- **LLM Providers**: OpenAI, Anthropic, Google Gemini, OpenRouter, etc.
