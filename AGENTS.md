# Project Structure for Software Development Agents

This document outlines the repository's structure and the purpose of its main components, specifically tailored for software development agents. The proxy is implemented using **FastAPI** and facilitates forwarding requests to configurable LLM backends.

## Software Development Principles for Agents

All software development agents interacting with this codebase **MUST** adhere to the following principles to ensure maintainability, scalability, and high quality:

- **Layered, Modular Architecture**: The codebase is designed with a clear separation of concerns. Agents should strive to maintain and enhance this modularity, ensuring that components are loosely coupled and highly cohesive. New functionalities should be introduced in a way that extends existing layers or creates new, well-defined modules.

- **Pythonic Conventions and Standards**: All code contributions and modifications must strictly follow Pythonic conventions, including PEP 8 for style guidelines. Agents should prioritize readability, simplicity, and idiomatic Python.

- **Test-Driven Development (TDD)**: This is a critical principle. Every enhanced, changed, or added functionality **MUST** be covered by related, comprehensive tests. Agents are strictly prohibited from introducing any changes that are not accompanied by extensive tests ensuring proper project maintenance and preventing regressions. This includes:
  - Writing tests before writing the code that makes them pass.
  - Ensuring high test coverage for all new or modified logic.
  - Maintaining and updating existing tests as the codebase evolves.

- **Software Architecture Principles**: Agents should employ the following principles in their development process:
  - **TDD (Test-Driven Development)**: As detailed above, tests drive development.
  - **SOLID**: Adhere to the SOLID principles to create robust, maintainable, and flexible designs:
    - **Single Responsibility Principle (SRP)**: A class should have only one reason to change.
    - **Open/Closed Principle (OCP)**: Software entities (classes, modules, functions, etc.) should be open for extension, but closed for modification.
    - **Liskov Substitution Principle (LSP)**: Objects in a program should be replaceable with instances of their subtypes without altering the correctness of that program.
    - **Interface Segregation Principle (ISP)**: Clients should not be forced to depend on interfaces they do not use.
    - **Dependency Inversion Principle (DIP)**: High-level modules should not depend on low-level modules. Both should depend on abstractions. Abstractions should not depend on details. Details should depend on abstractions.
  - **KISS (Keep It Simple, Stupid)**: Favor simplicity over complexity. Solutions should be as straightforward as possible while meeting requirements.
  - **DRY (Don't Repeat Yourself)**: Avoid code duplication. Promote reusable components and abstractions.

## Directory Overview

```text
.
├── dev/                     # Development utilities
│   ├── example_config.json
│   └── test_client.py
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

## Key Components

### `src/main.py`

Creates the FastAPI application, loads configuration from environment variables or CLI arguments and exposes the OpenAI-compatible endpoints. During startup it initialises the selected backend connector (`openrouter` or `gemini`), sets up an `httpx.AsyncClient`, and stores a `SessionManager` for recording interactions. It also defines a welcome banner shown in interactive mode that lists the functional backends along with how many API keys and models were discovered for each.

### `src/proxy_logic.py`

Defines the `ProxyState` class, which manages the current model override, project context, and interactive mode state. It also re-exports command parsing helpers.

### `src/commands/`

Contains individual command implementations. Each command file registers itself
via a decorator so that new commands can be added without modifying the parser.
The `!/help` command lists them dynamically along with their descriptions and
examples.

### `src/command_parser.py`

Implements the `CommandParser` class used to detect and handle proxy commands.
Commands are identified using a configurable prefix (default `!/`). It loads all
commands registered under `src/commands/` at runtime.

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

## Testing and Debugging

For effective testing and debugging of changes, especially those related to command-line argument parsing and application configuration, the `tests/unit/test_cli.py` script can be utilized. This script provides a dedicated test suite for the `src/core/cli.py` module, which handles CLI argument parsing and application startup.

### How to Use `test_cli.py`

You can run the tests within `test_cli.py` using `pytest`. To execute only these specific tests, navigate to the project root and run:

```bash
pytest tests/unit/test_cli.py
```

This will execute all tests defined in `test_cli.py`, allowing you to verify that CLI arguments are parsed and applied correctly, and that environment variables are set as expected.

### Example Configuration Files

The `dev/` directory contains example JSON configuration files that can be used to test various scenarios with the proxy. These files demonstrate how different settings (e.g., backend selection, API keys, command prefixes) can be configured. You can use these as a reference when developing or debugging:

- `dev/example_config.json`: A general example configuration.
- `dev/test_config.json`: Another example, potentially used for specific test cases.

These configuration files can be loaded by the application to simulate different operational environments, which is particularly useful when testing the `cli.py` module's ability to correctly interpret and apply settings.
