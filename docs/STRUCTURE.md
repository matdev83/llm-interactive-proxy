# Project Structure

This document describes the layout of the repository and the purpose of the main files. The proxy is implemented using **FastAPI** and forwards requests to configurable LLM backends.

## Directory overview

```text
.
├── dev/                     # Development utilities
│   ├── example_config.json
│   └── test_client.py
├── docs/
│   └── STRUCTURE.md         # (this file)
├── src/
│   ├── core/                # Core application logic and utilities
│   │   ├── cli.py           # CLI argument parsing and application startup
│   │   ├── config.py        # Configuration loading and management
│   │   ├── metadata.py      # Project metadata loading
│   │   └── persistence.py   # Configuration persistence (save/load)
│   ├── main.py              # Application factory and HTTP endpoints
│   ├── models.py            # Pydantic models for API payloads
│   ├── proxy_logic.py       # ProxyState class and re-exports
│   ├── command_parser.py    # Command parsing utilities
│   ├── session.py           # Simple in-memory session/history tracking
│   ├── agents.py            # Agent detection and response helpers
│   ├── security.py          # Client authentication and API key redaction
│   └── connectors/          # Concrete connector implementations and LLMBackend interface
│       ├── __init__.py
│       ├── base.py          # LLMBackend interface
│       ├── gemini.py        # Google Gemini connector
│       └── openrouter.py    # OpenRouter connector
├── tests/                   # Automated tests
│   ├── integration/
│   │   └── chat_completions_tests/
│   │       ├── test_basic_proxying.py
│   │       ├── test_command_only_requests.py
│   │       ├── test_error_handling.py
│   │       ├── test_model_commands.py
│   │       └── test_session_history.py
│   └── unit/
│       ├── test_cli.py
│       ├── test_proxy_logic.py
│       ├── test_session_manager.py
│       ├── openrouter_connector_tests/
│       │   ├── test_http_error_non_streaming.py
│       │   ├── test_http_error_streaming.py
│       │   ├── test_non_streaming_success.py
│       │   ├── test_payload_construction_and_headers.py
│       │   ├── test_request_error.py
│       │   └── test_streaming_success.py
│       └── proxy_logic_tests/
│           ├── test_parse_arguments.py
│           ├── test_process_commands_in_messages.py
│           └── test_process_text_for_commands.py
├── README.md
├── pyproject.toml
├── pytest.ini
└── setup.py
```

## Key components

### `src/main.py`

Creates the FastAPI application, loads configuration from environment variables or CLI arguments and exposes the OpenAI-compatible endpoints. During startup it initialises the selected backend connector (`openrouter` or `gemini`), sets up an `httpx.AsyncClient`, and stores a `SessionManager` for recording interactions. It also defines a welcome banner shown in interactive mode that lists the functional backends along with how many API keys and models were discovered for each.

### `src/proxy_logic.py`

Defines the `ProxyState` class, which manages the current model override, project context, and interactive mode state. It also re-exports command parsing helpers.

### `src/command_parser.py`

Implements the `CommandParser` class used to detect and handle proxy commands. Commands are identified using a configurable prefix (default `!/`).

### `src/session.py`

Defines `Session` and `SessionManager` used to keep simple per-session history of prompts and backend replies. Session IDs are supplied via the `X-Session-ID` HTTP header. The `SessionManager` can be configured with a default interactive mode for new sessions.

### `src/security.py`

Contains `APIKeyRedactor` and client authentication logic. The proxy expects an API key in the `Authorization` header unless started with `--disable-auth`.

### Connectors

The abstract `LLMBackend` base class and its concrete implementations live under `src/connectors/`:

- `openrouter.py` forwards requests to the OpenRouter API and supports streaming.
- `gemini.py` connects to Google Gemini (non-streaming only).

### Tests

Integration tests cover request forwarding, command handling and session tracking. Unit tests validate the CLI utilities, command parsing logic and connector behaviour.

This modular structure aims to keep backend specific code isolated while letting the FastAPI app orchestrate request processing and session management.
