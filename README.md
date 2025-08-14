# Interactive LLM Proxy Server

This project is a *swiss-army knife* for anyone hacking on language models and agentic workflows. It sits between your LLM-aware client and any LLM backend, allowing you to translate, reroute, and augment requests on the fly. With the proxy, you can execute chat-embedded commands, override models, rotate API keys, prevent loops, and inspect every token exchanged—all from a single, drop-in gateway.

## Core Features

- **Multi-Protocol Gateway**: Use any client (OpenAI, Anthropic, Gemini) with any backend. The proxy handles the protocol conversion automatically.
- **Advanced Loop Detection**: High-performance, streaming loop detection (hash-based) that automatically halts repetitive loops and stops upstream token generation. When a loop is detected, the proxy sends an SSE line to the client: `data: [Response cancelled: Loop detected - Pattern '<…>' repeated N times]` and attempts to cancel the upstream stream. Behavior is tiered-configurable:
  - Server-wide defaults via `LOOP_DETECTION_*` env vars
  - Backend/model defaults via model defaults (`loop_detection_enabled`)
  - Session override via `!/set(loop-detection=true|false)`
- **Tool Call Loop Detection**: Prevents repetitive tool calls that may indicate a model is stuck in a loop. Tracks tool call signatures and intervenes when the same tool is called repeatedly with identical parameters. Features:
  - **Signature-based tracking**: Identifies identical tool calls by name and arguments
  - **TTL-based pruning**: Avoids false positives by considering only recent calls
  - **Two modes**: "break" (stops repeating calls immediately) and "chance_then_break" (gives one chance to fix before breaking)
  - **Tiered configuration**:
    - Server-wide defaults via `TOOL_LOOP_*` env vars
    - Backend/model defaults via model defaults (`tool_loop_detection_enabled`, etc.)
    - Session override via `!/set(tool-loop-*=value)` commands
  - **Streaming compatibility**: Works with both streaming and non-streaming responses
- **Comprehensive Usage Tracking**: Logs all requests to a local database with endpoints (`/usage/stats`, `/usage/recent`) for monitoring costs and performance.
- **In-Chat Command System**: Control the proxy on the fly using commands inside your prompts (e.g., `!/help`, `!/set(backend=...)`).
- **Security**: Automatically redacts API keys and other secrets from prompts before they are sent to the LLM.
- **Unified Reasoning & Temperature Control**: The proxy understands and translates reasoning parameters (e.g., `reasoning_effort`, `thinking_budget`) and `temperature` settings across different backends, providing consistent control.

## Supported APIs & Protocol Conversion

The proxy normalises requests internally, meaning **any front-end can be wired to any back-end**. This unlocks powerful protocol-conversion scenarios.

| Client-Side (front-end) Protocol | Path prefix       | Typical SDK    |
| -------------------------------- | ----------------- | -------------- |
| OpenAI                           | `/v1/*`           | `openai`       |
| OpenRouter                       | `/v1/*`           | `openai`       |
| Anthropic Messages API           | `/anthropic/v1/*` | `anthropic`    |
| Google Gemini Generative AI      | `/v1beta/*`       | `google-genai` |

**Examples:**
- **Anthropic SDK ➜ OpenRouter**: Set `base_url="http://proxy/anthropic/v1"` and request model `openrouter:gpt-4`.
- **OpenAI client ➜ Gemini model**: Request model `gemini:gemini-1.5-pro` with your OpenAI client.
- **OpenAI client ➜ ZAI model**: Request model `zai:glm-4.5-flash` with your OpenAI client.
- **OpenAI client ➜ Custom OpenAI-compatible API**: Use `!/set(openai_url=https://custom-api.example.com/v1)` to redirect requests to a custom endpoint.

## Example Use Cases

1.  **Leverage Free Tiers with Key Rotation**
    - **Scenario**: You have multiple free-tier accounts for Gemini and want to combine their limits.
    - **Configuration (`.env` file)**:
      ```env
      GEMINI_API_KEY_1="first_free_tier_key"
      GEMINI_API_KEY_2="second_free_tier_key"
      GEMINI_API_KEY_3="third_free_tier_key"
      ```
    - **How it works**: The proxy will automatically cycle through these keys. If a request with `GEMINI_API_KEY_1` gets rate-limited, the next request will automatically use `GEMINI_API_KEY_2`, maximizing your free usage.

2.  **Build Resilient Workflows with Failover Routing**
    - **Scenario**: You want to use a powerful but expensive model like GPT-4, but fall back to a cheaper model if it fails or is unavailable.
    - **Action (In-chat command)**:
      ```
      !/create-failover-route(name=main_fallback, policy=m)
      !/route-append(name=main_fallback, openrouter:gpt-4, openrouter:sonnet-3.5)
      ```
    - **How it works**: When you request the model `main_fallback`, the proxy first tries `openrouter:gpt-4`. If that request fails, it automatically retries the request with `openrouter:sonnet-3.5` without any change needed in your client application.

3.  **Monitor Costs and Usage**
    - **Scenario**: You need to track token usage for a specific project or user.
    - **Action**: After running some requests, query the built-in usage API.
      ```bash
      curl -H "Authorization: Bearer your_proxy_key" "http://localhost:8000/usage/stats?project=my-project"
      ```
    - **How it works**: The proxy logs every request to a local database. The `/usage/stats` and `/usage/recent` endpoints provide immediate access to detailed analytics, helping you monitor costs and performance without any external setup.

4.  **Use Custom OpenAI-Compatible APIs**
    - **Scenario**: You want to use a local LLM server or a third-party API that's compatible with the OpenAI API format.
    - **Action (In-chat command)**:
      ```
      !/set(openai_url=http://localhost:1234/v1)
      ```
    - **How it works**: The proxy will redirect all OpenAI API requests to your custom endpoint while maintaining all the proxy's features like usage tracking, command processing, and security.

## Getting Started

### Prerequisites

- Python 3.8+
- `pip` for installing packages

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/Ymatdev83/llm-interactive-proxy.git
    cd llm-interactive-proxy
    ```

2.  **Create a virtual environment and activate it:**
    ```bash
    python -m venv .venv
    # On Linux/macOS
    source .venv/bin/activate
    # On Windows
    .venv\Scripts\activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -e .[dev]
    ```

### Configuration

1.  **Create a `.env` file** in the project root.
2.  **Add your backend API keys**. The proxy supports single keys or numbered keys for rotation (e.g., `OPENROUTER_API_KEY_1`, `OPENROUTER_API_KEY_2`).
    ```env
    # Example for OpenAI
    OPENAI_API_KEY="your_openai_api_key"
    # Optional: Custom OpenAI API URL
    # OPENAI_API_BASE_URL="https://custom-openai-api.example.com/v1"

    # Example for OpenRouter
    OPENROUTER_API_KEY="your_openrouter_api_key"

    # Example for Google Gemini (supports rotation)
    GEMINI_API_KEY_1="first_gemini_key"
    GEMINI_API_KEY_2="second_gemini_key"

    # Example for Anthropic
    ANTHROPIC_API_KEY="your_anthropic_key"

    # Example for ZAI (Zhipu AI)
    ZAI_API_KEY="your_zai_api_key"
    # Or with rotation:
    # ZAI_API_KEY_1="your_first_zai_api_key"
    # ZAI_API_KEY_2="your_second_zai_api_key"

    # Set a key for clients to access this proxy
    LLM_INTERACTIVE_PROXY_API_KEY="a_secret_key_for_your_clients"
    ```
4.  **Loop Detection (server-wide defaults)**
    ```env
    # Enable/disable globally
    LOOP_DETECTION_ENABLED=true
    # Buffering and algorithm parameters (optional, sensible defaults):
    LOOP_DETECTION_BUFFER_SIZE=2048
    LOOP_DETECTION_MAX_PATTERN_LENGTH=500
    LOOP_DETECTION_CONTENT_CHUNK_SIZE=50
    LOOP_DETECTION_CONTENT_LOOP_THRESHOLD=10
    LOOP_DETECTION_MAX_HISTORY_LENGTH=1000
    ```

5.  **Tool Call Loop Detection (server-wide defaults)**
    ```env
    # Enable/disable globally
    TOOL_LOOP_DETECTION_ENABLED=true
    # Maximum number of consecutive identical tool calls before action is taken
    TOOL_LOOP_MAX_REPEATS=4
    # Time window in seconds for considering tool calls part of a pattern
    TOOL_LOOP_TTL_SECONDS=120
    # How to handle detected tool call loops: "break" or "chance_then_break"
    TOOL_LOOP_MODE=break
    ```

6.  **Model Defaults (per backend/model)**
    - You can provide per-model defaults (persisted config) that include `loop_detection_enabled` and `tool_loop_detection_enabled` to opt-in/out for specific models. Session overrides still take precedence.
7.  **Select the default backend** (optional, defaults to the first one configured).
    ```env
    LLM_BACKEND=zai
    ```

### Running the Server

Start the proxy server from the project's root directory:

```bash
python src/core/cli.py
```

The server will start on `http://127.0.0.1:8000`. For a full list of CLI arguments and environment variables for advanced configuration, run `python src/core/cli.py --help`.

Supported backends for the `--default-backend` argument include: `openrouter`, `gemini`, `anthropic`, `qwen-oauth`, and `zai`.

## Usage

### Client Configuration

Configure your LLM client to use the proxy's URL and API key.

- **API Base URL**:
  - For OpenAI/OpenRouter clients: `http://localhost:8000/v1`
  - For Anthropic clients: `http://localhost:8000/anthropic/v1`
  - For Gemini clients: `http://localhost:8000/v1beta`
- **API Key**: Use the `LLM_INTERACTIVE_PROXY_API_KEY` you defined in your `.env` file.

### In-Chat Commands

Control the proxy on the fly by embedding commands in your prompts (default prefix `!/`).

**Common Commands:**
- `!/help`: List all available commands.
- `!/set(model=backend:model_name)`: Override the model for the current session.
- `!/set(backend=openrouter)`: Switch the backend for the current session.
- `!/set(openai_url=https://api.example.com/v1)`: Set a custom URL for the OpenAI API.
- `!/create-failover-route(...)`: Define custom failover logic.
- `!/set(loop-detection=true|false)`: Enable/disable loop detection for the current session (overrides server and model defaults).
- `!/set(tool-loop-detection=true|false)`: Enable/disable tool call loop detection for the current session.
- `!/set(tool-loop-max-repeats=4)`: Set maximum number of consecutive identical tool calls before action is taken.
- `!/set(tool-loop-ttl=120)`: Set time window in seconds for considering tool calls part of a pattern.
- `!/set(tool-loop-mode=break|chance_then_break)`: Set how to handle detected tool call loops.

## Troubleshooting

### Content Loop Detection

If you're seeing false positives with content loop detection (legitimate responses being cut off):

1. **Adjust the buffer size**: `LOOP_DETECTION_BUFFER_SIZE=4096` (default is 2048)
2. **Increase the pattern length**: `LOOP_DETECTION_MAX_PATTERN_LENGTH=1000` (default is 500)
3. **Disable for specific sessions**: Use `!/set(loop-detection=false)` in your prompt
4. **Disable globally**: Set `LOOP_DETECTION_ENABLED=false`

### Tool Call Loop Detection

If you're experiencing issues with tool call loop detection:

1. **False positives** (legitimate repeated tool calls being blocked):
   - **Increase the threshold**: `TOOL_LOOP_MAX_REPEATS=6` (default is 4)
   - **Reduce the TTL**: `TOOL_LOOP_TTL_SECONDS=60` (default is 120) to consider only very recent calls
   - **Try chance mode**: `TOOL_LOOP_MODE=chance_then_break` to give the model one chance to fix itself
   - **Disable for specific sessions**: Use `!/set(tool-loop-detection=false)` in your prompt

2. **False negatives** (loops not being caught):
   - **Decrease the threshold**: `TOOL_LOOP_MAX_REPEATS=3` (default is 4)
   - **Increase the TTL**: `TOOL_LOOP_TTL_SECONDS=180` (default is 120) to consider older calls
   - **Use break mode**: `TOOL_LOOP_MODE=break` to immediately stop repetitive calls

3. **Debugging**:
   - Enable debug logging to see detailed information about tool call tracking
   - Examine the signatures being tracked to ensure they're capturing the right information

## Roadmap

- Zero-knowledge key provisioning
- SSO authentication and a web management UI
- ML-based semantic loop detection
- On-the-fly prompt compression
- Command aliases and deep observability hooks

## Contributing

Contributions are welcome! Please follow the standard fork-and-pull-request workflow.

1.  Fork the repository.
2.  Create a new feature branch.
3.  Make your changes and add tests.
4.  Submit a pull request.

## Project Structure

```
.
├── src/                  # Source code
│   ├── commands/         # In-chat command implementations
│   ├── connectors/       # Backend connectors (OpenRouter, Gemini, etc.)
│   │   └── zai.py        # ZAI (Zhipu AI) backend connector
│   ├── core/             # Core application logic (CLI, config)
│   ├── main.py           # FastAPI application and endpoints
│   └── proxy_logic.py    # Core logic for command parsing, state management
├── tests/                # Automated tests
├── .env                  # Your local environment configuration (create this)
├── pyproject.toml        # Project metadata and dependencies
└── README.md             # This file
```