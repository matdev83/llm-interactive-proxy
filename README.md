# OpenAI Compatible Intercepting Proxy Server

This project provides an intercepting proxy server that is compatible with the OpenAI API. It allows for modification of requests and responses, command execution within chat messages, and model overriding. The proxy can forward requests to **OpenRouter.ai** or **Google Gemini**, selectable at run time.

## Features

- **OpenAI API Compatibility** – drop-in replacement for `/v1/chat/completions` and `/v1/models`.
- **Request Interception and Command Parsing** – user messages can contain commands (default prefix `!/`) to change proxy behaviour.
- **Configurable Command Prefix** – via the `COMMAND_PREFIX` environment variable, CLI, or in‑chat commands.
- **Dynamic Model Override** – commands like `!/set(model=...)` change the model for subsequent requests.
- **Multiple Backends** – forward requests to OpenRouter or Google Gemini, chosen with `LLM_BACKEND`.
- **Streaming and Non‑Streaming Support** – for both OpenRouter and Gemini backends.
- **Aggregated Model Listing** – the `/models` and `/v1/models` endpoints return the union of all models discovered from configured backends, prefixed with the backend name.
- **Session History Tracking** – optional per-session logs using the `X-Session-ID` header.
- **Agent Detection** – recognizes popular coding agents and formats proxy responses accordingly.
- **CLI Configuration** – command line flags can override environment variables for quick testing.
- **Persistent Configuration** – use `--config config/file.json` to save and reload failover routes and defaults across restarts.

## Getting Started

These instructions will get you a copy of the project up and running on your local machine for development and testing purposes.

### Prerequisites

- Python 3.8+
- `pip` for installing Python packages

### Installation

1. **Clone the repository (if you haven't already):**

    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

2. **Create a virtual environment (recommended):**

    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3. **Create a `.env` file:**
    Copy the example environment variables or create a new `.env` file in the project root:

    ```env
    # Provide a single OpenRouter key
    OPENROUTER_API_KEY="your_openrouter_api_key_here"
    # Or provide multiple keys (up to 20)
    # OPENROUTER_API_KEY_1="first_key"
    # OPENROUTER_API_KEY_2="second_key"

    # Gemini backend keys follow the same pattern
    # GEMINI_API_KEY="your_gemini_api_key_here"
    # GEMINI_API_KEY_1="first_gemini_key"
    # Keys are sent using the `x-goog-api-key` header to avoid exposing them in URLs

    # Client API key for accessing this proxy
    # LLM_INTERACTIVE_PROXY_API_KEY="choose_a_secret_key"

    # Disable all interactive commands
    # DISABLE_INTERACTIVE_COMMANDS="true"  # same as passing --disable-interactive-commands

    # Enable or disable prompt redaction (default true)
    # REDACT_API_KEYS_IN_PROMPTS="false"  # same as passing --disable-redact-api-keys-in-prompts
    ```

    Replace `"your_openrouter_api_key_here"` (or numbered variants) with your
    actual OpenRouter API key(s). The single and numbered formats are mutually
    exclusive. The same rule applies to the Gemini API keys.

4. **Install dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

5. **Install development dependencies (for running tests and development):**

    ```bash
    pip install -r requirements-dev.txt
    ```

### Running the Proxy Server

To start the proxy server, run the `main.py` script from the `src` directory:

```bash
python src/main.py
```

The server will typically start on `http://127.0.0.1:8000` (or as configured in your `.env` file). You should see log output indicating the server has started, e.g.:
`INFO:     Started server process [xxxxx]`
`INFO:     Waiting for application startup.`
`INFO:     Application startup complete.`
`INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)`

By default the server expects an API key from connecting clients. Set the key in
the `LLM_INTERACTIVE_PROXY_API_KEY` environment variable or let the server
generate one on startup. The value must be supplied in the `Authorization`
header using the `Bearer <key>` scheme. Authentication can be disabled with the
`--disable-auth` flag (only allowed when binding to `127.0.0.1`). When disabled,
no client API key is generated or checked.

### CLI Arguments

The proxy server can be configured using the following command-line arguments:

- `--default-backend {openrouter,gemini}`: Sets the default backend when multiple backends are functional.
- `--openrouter-api-key <key>`: Specifies the OpenRouter API key.
- `--openrouter-api-base-url <url>`: Specifies the OpenRouter API base URL.
- `--gemini-api-key <key>`: Specifies the Gemini API key.
- `--gemini-api-base-url <url>`: Specifies the Gemini API base URL.
- `--host <host>`: Specifies the host address to bind the server to (default: `127.0.0.1`).
- `--port <port>`: Specifies the port to listen on (default: `8000`).
- `--timeout <seconds>`: Sets the timeout for requests in seconds.
- `--command-prefix <prefix>`: Sets the command prefix for in-chat commands (default: `!/`).
- `--log FILE`: Writes logs to the specified file instead of stderr.
- `--config FILE`: Specifies the path to a persistent configuration file for saving and reloading failover routes and defaults.
- `--disable-interactive-mode`: Disables interactive mode by default for new sessions.
- `--disable-redact-api-keys-in-prompts`: Disables API key redaction in prompts.
- `--disable-auth`: Disables client API key authentication (only allowed when binding to `127.0.0.1`).
- `--force-set-project`: Requires a project name to be set before sending prompts.
- `--disable-interactive-commands`: Disables all in-chat command processing.

### Running Tests

To run the automated tests, use pytest:

```bash
pytest
```

Ensure you have installed the development dependencies (`requirements-dev.txt`) before running tests.

Some integration tests communicate with the real Gemini backend. Provide the key at
runtime using the environment variable `GEMINI_API_KEY_1`. The tests read this variable
on startup and no API keys are stored in the repository.

## Usage

Once the proxy server is running, you can configure your OpenAI-compatible client applications to point to the proxy's address (e.g., `http://localhost:8000/v1`) instead of the official OpenAI API base URL.

### Command Feature

You can embed special commands within your chat messages to control the proxy's behavior. Commands are discovered dynamically and listed with `!/help`. A specific command can be inspected using `!/help(<command>)`. If the proxy was started with `--disable-interactive-commands`, these commands will be ignored.

#### Available In-Chat Commands:

- `!/help`: List all available commands.
- `!/help(<command>)`: Show details for a specific command.
    Example: `!/help(set)`
- `!/set(model=backend:model_name)`: Overrides the model for the current session/request.
    Example: `Hello, please use !/set(model=openrouter:mistralai/mistral-7b-instruct) for this conversation.`
- `!/unset(model)`: Clears any previously set model override.
- `!/set(backend=openrouter|gemini)`: Overrides the backend for the current session/request.
    Example: `!/set(backend=gemini)`
- `!/unset(backend)`: Unsets the overridden backend.
- `!/set(default-backend=openrouter|gemini)`: Sets the default backend persistently.
    Example: `!/set(default-backend=openrouter)`
- `!/unset(default-backend)`: Unsets the default backend, restoring initial configuration.
- `!/set(project=project_name)` or `!/set(project-name=project_name)`: Sets the project name for the current session.
    Example: `!/set(project=my-project)`
- `!/unset(project)` or `!/unset(project-name)`: Unsets the project name.
- `!/set(interactive=true|false|on|off)`: Enables or disables interactive mode for the current session.
    Example: `!/set(interactive=true)` to enable, `!/set(interactive=off)` to disable.
- `!/unset(interactive)` or `!/unset(interactive-mode)`: Unsets interactive mode.
- `!/set(redact-api-keys-in-prompts=true|false)`: Enable or disable prompt API key redaction for all sessions.
    Example: `!/set(redact-api-keys-in-prompts=false)`
- `!/unset(redact-api-keys-in-prompts)`: Restore the default redaction behaviour.
- `!/set(command-prefix=prefix)`: Change the command prefix used by the proxy.
    Example: `!/set(command-prefix=##)`
- `!/unset(command-prefix)`: Reset the prefix back to `!/`.
- `!/hello`: Return the interactive welcome banner.
- `!/create-failover-route(name=<name>,policy=k|m|km|mk)`: Create a new failover route with given policy.
    Example: `!/create-failover-route(name=myroute,policy=k)`
- `!/delete-failover-route(name=<name>)`: Delete an existing failover route.
    Example: `!/delete-failover-route(name=myroute)`
- `!/list-failover-routes`: List configured failover routes.
    Example: `!/list-failover-routes`
- `!/route-list(name=<route>)`: List elements of a failover route.
    Example: `!/route-list(name=myroute)`
- `!/route-append(name=<route>,backend:model,...)`: Append elements to a failover route.
    Example: `!/route-append(name=myroute,openrouter:model-a)`
- `!/route-prepend(name=<route>,backend:model,...)`: Prepend elements to a failover route.
    Example: `!/route-prepend(name=myroute,openrouter:model-a)`
- `!/route-clear(name=<route>)`: Remove all elements from a failover route.
    Example: `!/route-clear(name=myroute)`

The command prefix must be 2-10 printable characters with no whitespace. If the prefix is exactly two characters, they cannot be the same.

The proxy will process these commands, strip them from the message sent to the LLM, and adjust its behavior accordingly.

## Project Structure

For a detailed overview of the project structure and software development principles for agents, please refer to `AGENTS.md`.

```bash
.
├── src/                  # Source code
│   ├── connectors/       # Backend connectors (OpenRouter, etc.)
│   ├── main.py           # FastAPI application, endpoints
│   ├── models.py         # Pydantic models for API requests/responses
│   └── proxy_logic.py    # Core logic for command parsing, state management
├── tests/                # Automated tests
│   ├── integration/
│   └── unit/
├── .env.example          # Example environment variables (optional, if not in README)
├── .gitignore
├── README.md             # This file
└── pyproject.toml        # Project metadata, build system config
```

## Contributing

We welcome contributions to this project! To contribute, please follow the typical fork-based workflow:

1. **Fork the Repository**: Go to the project's GitHub page and click the "Fork" button. This creates a copy of the repository under your GitHub account.

2. **Clone Your Fork**: Clone your forked repository to your local machine.

    ```bash
    git clone https://github.com/Ymatdev83/llm-interactive-proxy.git
    cd llm-interactive-proxy
    ```

3. **Create a New Branch**: Before making any changes, create a new branch for your feature or bug fix.

    ```bash
    git checkout -b feature/your-feature-name
    ```

    Choose a descriptive branch name (e.g., `bugfix/fix-auth-issue`, `feature/add-new-command`).

4. **Make Your Changes**: Implement your feature or fix the bug. Ensure your code adheres to the project's coding standards and includes relevant tests.

5. **Commit Your Changes**: Commit your changes with a clear and concise commit message.

    ```bash
    git add .
    git commit -m "feat: Add a new command for model override"
    ```

    Refer to conventional commit guidelines for commit message formatting.

6. **Push to Your Fork**: Push your new branch and commits to your forked repository on GitHub.

    ```bash
    git push origin feature/your-feature-name
    ```

7. **Create a Pull Request (PR)**: Go to your forked repository on GitHub. You will see a "Compare & pull request" button. Click it, review your changes, and submit the pull request to the `main` branch of the original repository.

    - Provide a clear title and description for your PR.
    - Reference any related issues.
    - Ensure all tests pass and address any feedback from maintainers.
