# Instructions for Gemini Agent

This document provides instructions for the Gemini agent interacting with this codebase.

## Project Overview

The project is a FastAPI-based proxy that forwards requests to configurable LLM backends. The codebase follows a layered, modular architecture with a strong emphasis on Pythonic conventions and standards.

## Environment Setup (Windows)

This is a Windows-based environment.

### 1. Activate Virtual Environment

Before running any Python commands, you **MUST** activate the virtual environment located in the `.venv` directory.

**Activation Command:**
`.venv\Scripts\activate`

**Note:** Prepend the activation string to all subsequent commands, like so:
`.venv\Scripts\activate && [YOUR_COMMAND]`

### 2. Install Dependencies

To install all project dependencies, including those required for development, run the following command from the project root directory:

`.venv\Scripts\activate && pip install -e .[dev]`

## Running the Application

To run the proxy server, execute the following command from the project root directory:

`.venv\Scripts\activate && python src/core/cli.py`

To run as a daemon, use the `--daemon` flag and specify a log file:

`.venv\Scripts\activate && python src/core/cli.py --daemon --log my_log_file.log`

The server will start, and by default, it will be accessible at `http://127.0.0.1:8000`.

## API Documentation

This project uses FastAPI, which provides automatic interactive API documentation. Once the server is running, you can access the documentation at the following endpoints:

*   **Swagger UI**: `http://127.0.0.1:8000/docs`
*   **ReDoc**: `http://127.0.0.1:8000/redoc`

## Development Principles

You **MUST** adhere to the following principles:

*   **Layered, Modular Architecture**: Maintain and enhance the modularity of the codebase.
*   **Pythonic Conventions**: Follow PEP 8 and prioritize readable, simple, and idiomatic Python.
*   **Test-Driven Development (TDD)**: All changes **MUST** be covered by comprehensive tests.
*   **Non-Breaking Changes**: Make changes in an additive way. Debug, improve, or create code. Do **NOT** delete code unless explicitly instructed by the user.

## Code Quality and Testing

### Linting

This project uses `ruff` and `pylint` for code quality. To run the linters, use the following commands:

`.venv\Scripts\activate && ruff check .`
`.venv\Scripts\activate && pylint src`

### Testing

Testing is a critical part of the development process.

*   **Prove Correctness**: Always run tests to prove the correctness of the code you have created or modified.
*   **New Functionality**: If you develop new functionality, you **MUST** write corresponding tests and ensure they pass.
*   **Regression Testing**: After any change, you **MUST** run the entire test suite to ensure you have not introduced any regressions.

**Running the full test suite:**

`.venv\Scripts\activate && pytest`

## Repository Map

*   **C:/Users/Mateusz/source/repos/llm-interactive-proxy/**
    *   `.agent.md`: Agent instructions.
    *   `.gitignore`: Git ignore patterns.
    *   `AGENTS.md`: Project structure and principles for agents.
    *   `GEMINI.md`: This file.
    *   `pylintrc`: Pylint configuration.
    *   `pyproject.toml`: Project metadata and build configuration.
    *   `pytest.ini`: Pytest configuration.
    *   `README.md`: Project overview.
    *   **config/**: Configuration files.
    *   **data/**: Data files.
    *   **dev/**: Development scripts and utilities.
    *   **docs/**: Documentation.
    *   **examples/**: Example usage scripts.
    *   **logs/**: Log files.
    *   **src/**: Source code.
        *   `agents.py`: Agent detection and response helpers.
        *   `command_config.py`: `CommandConfig` class.
        *   `command_parser.py`: `CommandParser` class.
        *   `command_prefix.py`: Command prefix utilities.
        *   `command_processor.py`: `CommandProcessor` class.
        *   `command_utils.py`: Command utilities.
        *   `constants.py`: Project constants.
        *   `gemini_converters.py`: Gemini data converters.
        *   `gemini_models.py`: Pydantic models for Gemini.
        *   `llm_accounting_utils.py`: LLM accounting utilities.
        *   `main.py`: FastAPI application factory and endpoints.
        *   `models.py`: Pydantic models for API payloads.
        *   `performance_tracker.py`: `PerformanceTracker` class.
        *   `proxy_logic.py`: `ProxyState` class.
        *   `rate_limit.py`: Rate limiting utilities.
        *   `security.py`: `APIKeyRedactor` class.
        *   `session.py`: `Session` and `SessionManager` classes.
        *   **commands/**: Command implementations.
            *   `base.py`: `BaseCommand` class.
            *   `create_failover_route_cmd.py`: `CreateFailoverRouteCommand` class.
            *   `delete_failover_route_cmd.py`: `DeleteFailoverRouteCommand` class.
            *   `failover_base.py`: `FailoverBaseCommand` class.
            *   `hello_cmd.py`: `HelloCommand` class.
            *   `help_cmd.py`: `HelpCommand` class.
            *   `list_failover_routes_cmd.py`: `ListFailoverRoutesCommand` class.
            *   `oneoff_cmd.py`: `OneoffCommand` class.
            *   `route_append_cmd.py`: `RouteAppendCommand` class.
            *   `route_clear_cmd.py`: `RouteClearCommand` class.
            *   `route_list_cmd.py`: `RouteListCommand` class.
            *   `route_prepend_cmd.py`: `RoutePrependCommand` class.
            *   `set_cmd.py`: `SetCommand` class.
            *   `unset_cmd.py`: `UnsetCommand` class.
        *   **connectors/**: LLM backend connectors.
            *   `base.py`: `LLMBackend` interface.
            *   `gemini.py`: `GeminiBackend` class.
            *   `gemini_cli_batch.py`: `GeminiCLIBatchBackend` class.
            *   `gemini_cli_direct.py`: `GeminiCLIDirectBackend` class.
            *   `gemini_cli_interactive.py`: `GeminiCLIInteractiveBackend` class.
            *   `openrouter.py`: `OpenRouterBackend` class.
        *   **core/**: Core application logic.
            *   `cli.py`: CLI argument parsing.
            *   `config.py`: `ProxyConfig` class.
            *   `metadata.py`: Project metadata loading.
            *   `persistence.py`: Configuration persistence.
        *   **services/**: Business logic services.
            *   `chat_service.py`: `ChatService` class.
    *   **tests/**: Automated tests.
