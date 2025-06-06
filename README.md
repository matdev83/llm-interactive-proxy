# OpenAI Compatible Intercepting Proxy Server

This project provides an intercepting proxy server that is compatible with the OpenAI API. It allows for modification of requests and responses, command execution within chat messages, and model overriding. The proxy can forward requests to **OpenRouter.ai** or **Google Gemini**, selectable at run time.

## Features

- **OpenAI API Compatibility** – drop-in replacement for `/v1/chat/completions` and `/v1/models`.
- **Request Interception and Command Parsing** – user messages can contain commands (default prefix `!/`) to change proxy behaviour.
- **Configurable Command Prefix** via the `COMMAND_PREFIX` environment variable or CLI.
- **Dynamic Model Override** – commands like `!/set(model=...)` change the model for subsequent requests.
- **Multiple Backends** – forward requests to OpenRouter or Google Gemini, chosen with `LLM_BACKEND`.
- **Streaming and Non‑Streaming Support** for both OpenRouter and Gemini backends.
- **Aggregated Model Listing** – the `/models` endpoint returns the union of all
  models discovered from configured backends, prefixed with the backend name.
- **Session History Tracking** – optional per-session logs using the `X-Session-ID` header.
- **CLI Configuration** – command line flags can override environment variables for quick testing, including interactive mode.
- **Persistent Configuration** – use `--config config/file.json` to save and reload failover routes and defaults across restarts.
- **Configurable Interactive Mode** – enable or disable interactive mode by default via environment variable, CLI argument, or in-chat commands.
- **Prompt API Key Redaction** – redact configured API keys from prompts. Enabled by default; can be turned off via the `--disable-redact-api-keys-in-prompts` CLI flag, environment variable, or commands.

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
python src/main.py --config config/settings.json
```

The server will typically start on `http://127.0.0.1:8000` (or as configured in your `.env` file). You should see log output indicating the server has started, e.g.:
`INFO:     Started server process [xxxxx]`
`INFO:     Waiting for application startup.`
`INFO:     Application startup complete.`
`INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)`

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

You can embed special commands within your chat messages to control the proxy's behavior. The primary command currently supported is:

- `!/set(model=model_name)`: Overrides the model for the current session/request.
    Example: `Hello, please use !/set(model=mistralai/mistral-7b-instruct) for this conversation.`
- `!/unset(model)`: Clears any previously set model override.
- `!/set(interactive=true|false|on|off)`: Enables or disables interactive mode for the current session.
    Example: `!/set(interactive=true)` to enable, `!/set(interactive=off)` to disable.
- `!/unset(interactive)`: Resets interactive mode to its default setting (configured at startup).
- `!/set(redact-api-keys-in-prompts=true|false)`: Enable or disable prompt API key redaction for all sessions.
- `!/unset(redact-api-keys-in-prompts)`: Restore the default redaction behaviour.

The proxy will process these commands, strip them from the message sent to the LLM, and adjust its behavior accordingly.

## Project Structure

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
├── requirements.txt      # Main application dependencies
├── requirements-dev.txt  # Development and test dependencies
└── pyproject.toml        # Project metadata, build system config
```

## Contributing

For planned work and future ideas see `ROADMAP.md` in the project root.
