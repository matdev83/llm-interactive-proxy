# Project Structure: Intercepting Proxy for LLM APIs

This document outlines the architecture and file organization of the Intercepting Proxy for LLM APIs. The project is designed to sit between a client application and an LLM provider (currently OpenRouter.ai), allowing for custom logic, such as command processing, to be applied to requests before they reach the LLM.

## High-Level Overview

The proxy is built using FastAPI, providing a web server that exposes an OpenAI-compatible API endpoint. Key functionalities include:

* **API Proxying**: Forwarding chat completion requests to the actual LLM provider.
* **Command Processing**: Intercepting and processing special commands embedded in user messages (e.g., `!/set(model=...)`).
* **Extensibility**: Designed with an abstract backend interface (`src/backends/base.py`) to easily integrate with different LLM providers.

## Directory Structure

```bash
.
├── docs/
│   ├── DEVELOPMENT.md
│   └── STRUCTURE.md          (This file)
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── models.py
│   ├── proxy_logic.py
│   ├── backends/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── gemini.py
│   │   └── openrouter.py
│   └── connectors/
│       ├── __init__.py
│       └── base.py
├── dev/
│   └── test_client.py
├── tests/
│   ├── __init__.py
│   ├── integration/
│   │   └── chat_completions_tests/
│   │       ├── test_basic_proxying.py
│   │       ├── test_command_only_requests.py
│   │       ├── test_error_handling.py
│   │       └── test_model_commands.py
│   └── unit/
│       ├── __init__.py
│       ├── test_proxy_logic.py
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
├── .gitignore
├── pyproject.toml
├── pytest.ini
├── README.md
└── setup.py
```

## Detailed File Descriptions

### `src/` - Source Code

This directory contains the core logic of the proxy server.

* **`src/main.py`**:
  * **Role**: The main entry point and FastAPI application setup.
  * **Responsibilities**:
    * Loads configuration from environment variables.
    * Initializes the FastAPI application and sets up logging.
    * Manages the lifecycle of the HTTP client (`httpx.AsyncClient`) and LLM backend connectors.
    * Defines the API endpoints (`/`, `/v1/chat/completions`, `/v1/models`).
    * Handles incoming chat completion requests, orchestrating the command processing (`proxy_logic`) and delegating to the appropriate LLM backend (`connectors`).
    * Manages "command-only" responses, where no actual LLM call is made.
    * Proxies model listing requests directly to the LLM provider.

* **`src/models.py`**:
  * **Role**: Defines Pydantic data models for API requests and responses.
  * **Responsibilities**:
    * Structures the data for `ChatMessage` (supporting text and multimodal content).
    * Defines the `ChatCompletionRequest` model, mirroring the OpenAI API specification.
    * Defines response models like `ChatCompletionChoiceMessage`, `ChatCompletionChoice`, `CompletionUsage`, and `CommandProcessedChatCompletionResponse`.
    * Ensures type safety and data validation for API interactions.

<<<<<<< HEAD
* **`src/proxy_logic.py`**:
  * **Role**: Implements the business logic for processing custom commands embedded in user messages.
  * **Responsibilities**:
    * **`ProxyState` Class**: Manages the dynamic state of the proxy, such as overriding the LLM model for subsequent requests. This state is typically tied to a session or request context.
    * **`parse_arguments(args_str)`**: Parses command arguments from a string (e.g., `model=gpt-4`).
    * **`_process_text_for_commands(text_content, current_proxy_state)`**: A private helper function that identifies and processes commands within a single text string. It modifies the `ProxyState` and removes the command text from the message content.
    * **`process_commands_in_messages(messages, current_proxy_state)`**: The primary function that iterates through a list of `ChatMessage` objects, identifies and processes commands (typically in the last user message), and returns the modified message list and a flag indicating if any commands were processed. It handles both string and multimodal message content.
=======
*   **`src/proxy_logic.py`**:
    *   **Role**: Implements the business logic for processing custom commands embedded in user messages.
    *   **Responsibilities**:
        *   **`ProxyState` Class**: Manages the dynamic state of the proxy, such as overriding the LLM model for subsequent requests. This state is typically tied to a session or request context.
        *   **`parse_arguments(args_str)`**: Parses command arguments from a string (e.g., `model=gpt-4`).
        *   **`_process_text_for_commands(text_content, current_proxy_state, command_pattern)`**: A private helper function that identifies and processes commands within a single text string using the provided regex pattern. It modifies the `ProxyState` and removes the command text from the message content.
        *   **`process_commands_in_messages(messages, current_proxy_state, command_prefix='!/')`**: The primary function that iterates through a list of `ChatMessage` objects, identifies and processes commands (typically in the last user message), and returns the modified message list and a flag indicating if any commands were processed. It handles both string and multimodal message content. The `command_prefix` parameter controls which command syntax is recognized.
>>>>>>> codex/make-command-prefix-configurable

* **`src/backends/`**:
  * **Role**: Contains the abstract base class and concrete implementations for connecting to various LLM providers. This is where the core logic for interacting with different LLMs resides.
  * **`src/backends/base.py`**:
    * **Role**: Defines the abstract base class `LLMBackend`.
    * **Responsibilities**: Establishes a common asynchronous interface (`chat_completion`, `list_models`) that all LLM backend implementations must adhere to. This promotes extensibility and allows the `main.py` to interact with different LLM providers uniformly.
  * **`src/backends/openrouter.py`**:
    * **Role**: Implements the `LLMBackend` interface for OpenRouter.ai.
    * **Responsibilities**: Handles the specific API calls to OpenRouter's `/chat/completions` and `/v1/models` endpoints, constructs request payloads, manages streaming and non-streaming responses, and performs error handling.
  * **`src/backends/gemini.py`**:
    * **Role**: Implements the `LLMBackend` interface for Google Gemini.
    * **Responsibilities**: Handles API calls to the Google Gemini API, constructs request payloads, manages responses, and performs error handling. (Details to be filled in as implementation progresses).

* **`src/connectors/`**:
  * **Role**: Contains components related to connecting or interacting with external services, potentially distinct from core LLM backends. (Further clarification needed based on current usage).
  * **`src/connectors/base.py`**:
    * **Role**: Defines base classes or interfaces for connectors. (Further clarification needed based on current usage).

### `dev/` - Development Utilities

This directory contains scripts and utilities useful during development.

* **`dev/test_client.py`**:
  * **Role**: A simple Python script for testing the proxy API endpoints locally.
  * **Responsibilities**: Provides a command-line interface or simple function calls to send requests to the running proxy, useful for manual testing and debugging.

### `docs/` - Documentation

This directory holds project documentation.

* **`docs/DEVELOPMENT.md`**: Likely contains guidelines and information for developers working on the project.
* **`docs/STRUCTURE.md`**: This file, detailing the project's architecture and file responsibilities.

### `tests/` - Tests

This directory contains automated tests for the project.

* **`tests/integration/`**:
  * **Role**: Contains integration tests that verify the interaction between different components of the proxy and with external services (like OpenRouter).
  * **`chat_completions_tests/`**: Specific integration tests for the chat completions endpoint, covering basic proxying, command-only requests, error handling, and model commands.
* **`tests/unit/`**:
  * **Role**: Contains unit tests that verify the functionality of individual components in isolation.
  * **`test_cli.py`**: Unit tests for any command-line interface components or scripts.
  * **`test_proxy_logic.py`**: Unit tests for the core `proxy_logic.py` module.
  * **`gemini_backend_tests/`**: Unit tests specifically for the `src/backends/gemini.py` backend implementation.
  * **`openrouter_connector_tests/`**: Unit tests specifically for the `src/backends/openrouter.py` backend implementation, covering various scenarios like streaming, non-streaming, and error conditions.
  * **`proxy_logic_tests/`**: More granular unit tests for specific functions within `proxy_logic.py` (e.g., `test_parse_arguments`, `test_process_commands_in_messages`, `test_process_text_for_commands`).

### Other Root Files

* **`.gitignore`**: Specifies intentionally untracked files to ignore by Git.
* **`pyproject.toml`**: Configuration file for Python projects, often used for build systems (like Poetry or Hatch) and project metadata.
* **`pytest.ini`**: Configuration file for the `pytest` testing framework.
* **`README.md`**: General project information, setup instructions, and usage guide.
* **`setup.py`**: Script for packaging and distributing the Python project (though `pyproject.toml` is becoming more common for this).

This structure promotes modularity, testability, and maintainability, making it easier to understand, extend, and debug the proxy server.
