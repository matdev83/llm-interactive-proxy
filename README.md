# OpenAI Compatible Intercepting Proxy Server

This project provides an intercepting proxy server that is compatible with the OpenAI API. It allows for modification of requests and responses, command execution within chat messages, and model overriding. The proxy can forward requests to **OpenRouter.ai** or **Google Gemini**, selectable at run time.

## 🚀 KILLER FEATURES

- **🔄 Automated API Key Rotation** – Use multiple accounts' "free tier" allowances to combine them into one powerful cumulative pool of free tiers. Configure multiple API keys and let the proxy automatically rotate between them to maximize your usage limits.

- **🎯 Override Model Name** – Force any application to use the model of your choice, regardless of what the application originally requested. Perfect for redirecting expensive model calls to cheaper alternatives or testing different models without modifying your applications.

- **🛡️ Failover Routing** – Define intelligent rules to automatically switch to other backend/model combinations if the original model has temporary problems or gets rate limited. This ensures high availability and resilience.

- **💎 Gemini CLI Gateway** – Expose Gemini models with their generous free allowances as standard OpenAI/OpenRouter endpoints. Route calls from any application that doesn't natively support Gemini through the Gemini CLI app instead of the API endpoint, unlocking free access to powerful models.

- **📊 Comprehensive Usage Logging & Audit Trail** – Full LLM accounting integration tracks all API calls with detailed metrics including token usage, costs, execution times, and user attribution. Persistent database storage with REST API endpoints for usage statistics and audit reports. Perfect for compliance, cost monitoring, and usage analytics.

## Features

- **OpenAI API Compatibility** – drop-in replacement for `/v1/chat/completions` and `/v1/models`.
- **Gemini API Compatibility** – native Google Gemini API endpoints (`/v1beta/models` and `/v1beta/models/{model}:generateContent`) with full compatibility for the official `google-genai` client library.
- **Request Interception and Command Parsing** – user messages can contain commands (default prefix `!/`) to change proxy behaviour.
- **Configurable Command Prefix** – via the `COMMAND_PREFIX` environment variable, CLI, or in‑chat commands.
- **Dynamic Model Override** – commands like `!/set(model=...)` change the model for subsequent requests.
- **Multiple Backends** – forward requests to OpenRouter, Google Gemini, or Gemini CLI Direct. Chosen with `LLM_BACKEND`.
- **Gemini CLI Direct Support** - Route requests directly to the system-installed Gemini CLI application, providing access to Gemini models without requiring API keys.
- **Streaming and Non‑Streaming Support** – for OpenRouter and Gemini backends. Gemini CLI Direct backend supports both streaming and non-streaming responses.
- **Aggregated Model Listing** – the `/models` and `/v1/models` endpoints return the union of all models discovered from configured backends, prefixed with the backend name (e.g., `openrouter:model_name`, `gemini:model_name`, `gemini-cli-direct:model_name`).
- **Session History Tracking** – optional per-session logs using the `X-Session-ID` header.
- **Agent Detection** – recognizes popular coding agents and formats proxy responses accordingly.
- **CLI Configuration** – command line flags can override environment variables for quick testing.
- **Persistent Configuration** – use `--config config/file.json` to save and reload failover routes and defaults across restarts.

## Getting Started

These instructions will get you a copy of the project up and running on your local machine for development and testing purposes.

### Prerequisites

- Python 3.8+
- `pip` for installing Python packages
- **For Gemini CLI Direct backend**: [Google Gemini CLI](https://github.com/google-gemini/gemini-cli) installed system-wide and authenticated

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

    # Gemini CLI Direct backend configuration
    # Uses system-installed Gemini CLI - ensure 'gemini auth' has been run first
    # GOOGLE_CLOUD_PROJECT="your-google-cloud-project-id"  # Required for Gemini CLI

    # Client API key for accessing this proxy
    # LLM_INTERACTIVE_PROXY_API_KEY="choose_a_secret_key"

    # Disable all interactive commands
    # DISABLE_INTERACTIVE_COMMANDS="true"  # same as passing --disable-interactive-commands

    # Enable or disable prompt redaction (default true)
    # REDACT_API_KEYS_IN_PROMPTS="false"  # same as passing --disable-redact-api-keys-in-prompts

    # Enable or disable LLM accounting (usage tracking and audit logging)
    # DISABLE_ACCOUNTING="true"  # same as passing --disable-accounting
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

### Gemini CLI Direct Backend Setup

The Gemini CLI Direct backend allows you to use Google's Gemini models directly through the system-installed Gemini CLI application, without requiring API keys. This backend provides an alternative way to access Gemini models.

#### Prerequisites for Gemini CLI Direct

1. **Install Google Gemini CLI**: Follow the installation instructions from the [official Gemini CLI repository](https://github.com/google-gemini/gemini-cli).

2. **Add to PATH**: Ensure the `gemini` executable is available in your system's PATH. You can verify this by running:

    ```bash
    gemini --version
    ```

3. **Authenticate (One-time setup)**: Before using the Gemini CLI with this proxy, you must authenticate it:

    ```bash
    gemini auth
    ```

    Follow the prompts to complete the authentication process. This is a one-time operation that stores your credentials locally.

4. **Set Google Cloud Project ID**: The Gemini CLI requires a Google Cloud Project ID to be set. Add this to your `.env` file:

    ```env
    GOOGLE_CLOUD_PROJECT=your-google-cloud-project-id
    ```

    Replace `your-google-cloud-project-id` with your actual Google Cloud Project ID.

#### Using Gemini CLI Direct Backend

Once the Gemini CLI is installed and authenticated, you can use the `gemini-cli-direct` backend:

- **Set as default backend**: Use `--default-backend gemini-cli-direct` when starting the proxy
- **Set via environment**: `LLM_BACKEND=gemini-cli-direct`
- **Switch in-chat**: Use `!/set(backend=gemini-cli-direct)` in your messages

The Gemini CLI Direct backend:

- **No API keys required** - Uses your authenticated Gemini CLI session
- **Direct CLI integration** - Communicates directly with the `gemini` command
- **Supports streaming and non-streaming** - Full compatibility with OpenAI API clients
- **Available models**: `gemini-cli-direct:gemini-2.5-pro`, `gemini-cli-direct:gemini-1.5-pro`, `gemini-cli-direct:gemini-2.0-flash-exp`, `gemini-cli-direct:gemini-pro`

**Note**: The Gemini CLI Direct backend uses the default model configured in your Gemini CLI installation and does not pass model selection parameters to the CLI.

### Running the Proxy Server

To start the proxy server, run the following command from the project's root directory:

```bash
python -m src.main
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

- `--default-backend {openrouter,gemini,gemini-cli-direct}`: Sets the default backend when multiple backends are functional.
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
- `--daemon`: Runs the server as a daemon (in the background). Requires `--log` to be set.
- `--disable-interactive-mode`: Disables interactive mode by default for new sessions.
- `--disable-redact-api-keys-in-prompts`: Disables API key redaction in prompts.
- `--disable-auth`: Disables client API key authentication (only allowed when binding to `127.0.0.1`).
- `--force-set-project`: Requires a project name to be set before sending prompts.
- `--disable-interactive-commands`: Disables all in-chat command processing.
- `--disable-accounting`: Disables LLM accounting (usage tracking and audit logging).

### Usage Tracking and Analytics

The proxy includes comprehensive LLM usage tracking powered by the `llm-accounting` package. All API calls are automatically logged with detailed metrics.

#### Usage Endpoints

- **`GET /usage/stats`** - Get usage statistics and analytics
  - Query parameters: `days` (default: 30), `backend`, `project`, `username`
  - Returns aggregated usage data, costs, and model rankings

- **`GET /usage/recent`** - Get recent usage entries
  - Query parameters: `limit` (default: 100)
  - Returns detailed log of recent API calls with full metadata

#### Tracked Metrics

- Token usage (prompt, completion, total)
- Execution time and costs
- Backend and model information
- User and project attribution
- Session tracking
- Timestamp and caller information

All data is stored persistently in a local SQLite database and can be exported for compliance or analytics purposes.

### Running Tests

To run the automated tests, use pytest:

```bash
pytest
```

Ensure you have installed the development dependencies (`requirements-dev.txt`) before running tests.

Some integration tests communicate with the real Gemini backend. Provide the key at
runtime using the environment variable `GEMINI_API_KEY_1`. The tests read this variable
on startup and no API keys are stored in the repository.

The test suite includes comprehensive integration tests for Gemini API compatibility using the official `google-genai` client library, ensuring full compatibility with real Gemini API clients.

## Usage

Once the proxy server is running, you can configure your OpenAI-compatible client applications to point to the proxy's address (e.g., `http://localhost:8000/v1`) instead of the official OpenAI API base URL.

### Gemini API Compatibility

The proxy also provides native Google Gemini API endpoints, allowing you to use the official `google-genai` client library directly with the proxy. This enables access to all configured backends (OpenRouter, Gemini, Gemini CLI Direct) through the Gemini API interface.

#### Using the Official Google Gemini Client

Install the official Google Gemini client library:

```bash
pip install google-genai
```

Then use it with the proxy:

```python
from google import genai
from google.genai import types as genai_types

# Create client pointing to the proxy
client = genai.Client(
    api_key="your-proxy-api-key",
    http_options=genai_types.HttpOptions(
        base_url="http://localhost:8000"  # Your proxy URL
    )
)

# List available models (from all backends)
models = client.models.list()
for model in models.models:
    print(f"Model: {model.name}")

# Generate content using any backend
response = client.models.generate_content(
    model="openrouter:gpt-4",  # Use OpenRouter backend
    contents=[
        genai_types.Content(
            parts=[genai_types.Part(text="Hello, how are you?")],
            role="user"
        )
    ]
)
print(response.text)

# Or use Gemini backend
response = client.models.generate_content(
    model="gemini:gemini-pro",  # Use Gemini backend
    contents=[
        genai_types.Content(
            parts=[genai_types.Part(text="Explain quantum computing")],
            role="user"
        )
    ]
)
print(response.text)
```

#### Gemini API Endpoints

The proxy provides these Gemini-compatible endpoints:

- **`GET /v1beta/models`** - List all available models from all backends in Gemini format
- **`POST /v1beta/models/{model}:generateContent`** - Generate content (non-streaming)
- **`POST /v1beta/models/{model}:streamGenerateContent`** - Generate content (streaming)

#### Authentication

Use the same authentication as the OpenAI endpoints, but with the `x-goog-api-key` header:

```bash
curl -X POST "http://localhost:8000/v1beta/models/openrouter:gpt-4:generateContent" \
  -H "x-goog-api-key: your-proxy-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [
      {
        "parts": [{"text": "Hello, world!"}],
        "role": "user"
      }
    ]
  }'
```

#### Backend Routing

Model names can include backend prefixes to route to specific backends:

- `openrouter:gpt-4` - Routes to OpenRouter backend
- `gemini:gemini-pro` - Routes to Gemini backend  
- `gemini-cli-direct:gemini-1.5-pro` - Routes to Gemini CLI Direct backend
- `gpt-4` - Uses default backend (no prefix)

### Command Feature

You can embed special commands within your chat messages to control the proxy's behavior. Commands are discovered dynamically and listed with `!/help`. A specific command can be inspected using `!/help(<command>)`. If the proxy was started with `--disable-interactive-commands`, these commands will be ignored.

#### Available In-Chat Commands

- `!/help`: List all available commands.
- `!/help(<command>)`: Show details for a specific command.
    Example: `!/help(set)`
- `!/set(model=backend:model_name)`: Overrides the model for the current session/request.
    Example: `Hello, please use !/set(model=openrouter:mistralai/mistral-7b-instruct) for this conversation.`
    Note: For `gemini-cli-direct` backend, the model specified (e.g., `gemini-cli-direct:gemini-pro`) is ignored as the backend uses the default Gemini CLI model.
- `!/unset(model)`: Clears any previously set model override.
- `!/set(backend=openrouter|gemini|gemini-cli-direct)`: Overrides the backend for the current session/request.
    Example: `!/set(backend=gemini-cli-direct)`
- `!/unset(backend)`: Unsets the overridden backend.
- `!/set(default-backend=openrouter|gemini|gemini-cli-direct)`: Sets the default backend persistently.
    Example: `!/set(default-backend=gemini-cli-direct)`
- `!/unset(default-backend)`: Unsets the default backend, restoring initial configuration.
- `!/set(project-name=project_name)`: Sets the project name for the current session.
    Example: `!/set(project=my-project)`
- `!/set(project-dir="<project_root_dir>")`, `!/set(dir="<project_root_dir>")`, or `!/set(project-directory="<project_root_dir>")`: Sets the project directory for the current session. The directory must exist and be readable.
    Example: `!/set(project-dir="C:\Users\Test\Projects\MyProject")`
- `!/unset(project)` or `!/unset(project-name)`: Unsets the project name.
- `!/pwd`: Prints the current project directory.
- `!/set(interactive=true|false|on|off)`: Enables or disables interactive mode for the current session.
    Example: `!/set(interactive=true)` to enable, `!/set(interactive=off)` to disable.
- `!/unset(interactive)` or `!/unset(interactive-mode)`: Unsets interactive mode.
- `!/set(redact-api-keys-in-prompts=true|false)`: Enable or disable prompt API key redaction for all sessions.
    Example: `!/set(redact-api-keys-in-prompts=false)`
- `!/unset(redact-api-keys-in-prompts)`: Restore the default redaction behaviour.
- `!/set(command-prefix=prefix)`: Change the command prefix used by the proxy.
    Example: `!/set(command-prefix=##)`
- `!/unset(command-prefix)`: Reset the prefix back to `!/`.
- `!/set(reasoning-effort=low|medium|high)`: Set reasoning effort level for reasoning models (o1, o3, o4-mini, etc.).
    Example: `!/set(reasoning-effort=high)`
- `!/set(reasoning=effort=high)` or `!/set(reasoning=max_tokens=2000)`: Set unified reasoning configuration for OpenRouter.
    Example: `!/set(reasoning=effort=medium)` or `!/set(reasoning=max_tokens=1500)`
- `!/unset(reasoning-effort)`: Clear reasoning effort setting.
- `!/unset(reasoning)`: Clear reasoning configuration.
- `!/set(thinking-budget=<tokens>)`: Set Gemini thinking budget (128-32768 tokens).
    Example: `!/set(thinking-budget=2048)`
- `!/set(gemini-generation-config=<config>)`: Set Gemini generation configuration with thinking settings.
    Example: `!/set(gemini-generation-config={'thinkingConfig': {'thinkingBudget': 1024}})`
- `!/unset(thinking-budget)`: Clear Gemini thinking budget.
- `!/unset(gemini-generation-config)`: Clear Gemini generation configuration.
- `!/set(temperature=<value>)`: Set temperature for model output randomness (0.0-2.0 for OpenAI, 0.0-1.0 for Gemini).
    Example: `!/set(temperature=0.7)`
- `!/unset(temperature)`: Clear temperature setting.
- `!/hello`: Return the interactive welcome banner.
- `!/create-failover-route(name=<name>,policy=k|m|km|mk)`: Create a new failover route with given policy.
    Example: `!/create-failover-route(name=myroute,policy=k)`
    Policies:
  - `k` (Keys Failover): Fixed model, cycles through all available API keys for the backend.
  - `m` (Models Failover): Cycles through models, using the first API key for each backend.
  - `km` (Keys then Models Failover): For each model, cycles through all available API keys before moving to the next model.
  - `mk` (Models then Keys - Round-Robin): Interleaves attempts across models and their API keys, providing a form of round-robin distribution.
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
- `!/oneoff(backend/model)` or `!/one-off(backend/model)`: Sets a one-time override for the backend and model for the next request only.
    Example: `!/oneoff(gemini/gemini-pro)` or `!/one-off(openrouter/gpt-4)`
    Usage patterns:
  - **Command-only**: Send `!/oneoff(backend/model)` alone, then follow with your prompt in the next message
  - **Command+prompt**: Send `!/oneoff(backend/model)` followed by your prompt in the same message
    The override is automatically cleared after the single request is processed.

The command prefix must be 2-10 printable characters with no whitespace. If the prefix is exactly two characters, they cannot be the same.

The proxy will process these commands, strip them from the message sent to the LLM, and adjust its behavior accordingly.

## Reasoning Models Support

The proxy provides comprehensive support for reasoning models (also known as "thinking" models) from various providers. These models, such as OpenAI's o1/o3/o4-mini series, Anthropic's Claude models with reasoning, DeepSeek's R1, and Gemini's thinking variants, can perform step-by-step reasoning before providing their final answer.

**Important**: Different providers use different parameter formats for reasoning control. The proxy handles these differences automatically.

### Provider-Specific Reasoning Parameters

#### OpenAI-Compatible Interfaces (OpenRouter)
- **`reasoning_effort`**: Simple effort levels (`low`, `medium`, `high`)
- **`reasoning`**: Unified configuration object with `effort`, `max_tokens`, `exclude` fields

#### Gemini Backend
- **`thinking_budget`**: Number of tokens allocated for reasoning (128-32768)
- **`generation_config`**: Full Gemini generation configuration including `thinkingConfig`

### Setting Reasoning Parameters

You can control reasoning behavior using several methods:

#### 1. In-Chat Commands (Recommended)

**OpenAI/OpenRouter Models:**
```bash
# Set reasoning effort level (works with OpenAI and OpenRouter models)
!/set(reasoning-effort=high)

# Set OpenRouter unified reasoning configuration
!/set(reasoning=effort=medium)
!/set(reasoning=max_tokens=2000)
!/set(reasoning=exclude=true)

# Clear OpenAI/OpenRouter reasoning settings
!/unset(reasoning-effort)
!/unset(reasoning)
```

**Gemini Models:**
```bash
# Set Gemini thinking budget (128-32768 tokens)
!/set(thinking-budget=2048)

# Set full Gemini generation config with thinking
!/set(gemini-generation-config={'thinkingConfig': {'thinkingBudget': 1024}})

# Clear Gemini reasoning settings
!/unset(thinking-budget)
!/unset(gemini-generation-config)
```

#### 2. Direct API Parameters

**OpenAI/OpenRouter Models:**
```json
{
  "model": "openrouter:openai/o1",
  "messages": [...],
  "reasoning_effort": "high",
  "reasoning": {
    "effort": "medium",
    "max_tokens": 1500,
    "exclude": false
  }
}
```

**Gemini Models:**
```json
{
  "model": "gemini:gemini-2.5-pro",
  "messages": [...],
  "thinking_budget": 2048,
  "generation_config": {
    "thinkingConfig": {
      "thinkingBudget": 1024
    },
    "temperature": 0.7
  }
}
```

#### 3. Extra Parameters (Universal)

For maximum flexibility with any provider, use the `extra_params` field:

**OpenRouter:**
```json
{
  "model": "openrouter:deepseek/deepseek-r1",
  "messages": [...],
  "extra_params": {
    "reasoning": {
      "effort": "high",
      "max_tokens": 2000
    }
  }
}
```

**Gemini:**
```json
{
  "model": "gemini:gemini-2.5-flash",
  "messages": [...],
  "extra_params": {
    "generationConfig": {
      "thinkingConfig": {
        "thinkingBudget": 1024
      }
    }
  }
}
```

### Backend-Specific Behavior

- **OpenRouter**: Automatically converts `reasoning_effort` and `reasoning` parameters to the appropriate OpenRouter format. Supports all reasoning models available through OpenRouter.

- **Gemini**: Converts `thinking_budget` to Gemini's `generationConfig.thinkingConfig.thinkingBudget` format. Also supports direct `generation_config` for full control over Gemini's generation parameters.

- **Gemini CLI Direct**: Reasoning parameters are passed through but effectiveness depends on the CLI version and model support.

### Example Usage Scenarios

**Complex Problem Solving with OpenAI Models:**
```bash
!/set(reasoning-effort=high)
Solve this complex mathematical proof step by step...
```

**Token-Controlled Reasoning with OpenRouter:**
```bash
!/set(reasoning=max_tokens=3000)
Analyze this large dataset and provide detailed insights...
```

**Gemini Thinking Budget Control:**
```bash
!/set(thinking-budget=2048)
Please think through this design problem carefully...
```

**Fast Reasoning (Internal Only):**
```bash
!/set(reasoning=effort=medium,exclude=true)
Quick analysis needed for this business decision...
```

### Model Compatibility

The reasoning features work with various reasoning models:

- **OpenAI**: o1-preview, o1-mini, o3, o4-mini
- **OpenRouter**: All reasoning models including:
  - DeepSeek R1 (`deepseek/deepseek-r1`)
  - QwQ (`qwen/qwq-32b-preview`)
  - OpenAI models via OpenRouter
  - Other reasoning-capable models
- **Gemini**: Gemini 2.5 Pro, Gemini 2.5 Flash, and other thinking variants
- **Other providers**: Any model that supports reasoning tokens through their respective APIs

### Important Notes

1. **Provider Auto-Detection**: The proxy automatically detects which backend you're using and applies the correct reasoning parameter format.

2. **Parameter Validation**: 
   - OpenAI `reasoning_effort` accepts only `low`, `medium`, `high`
   - Gemini `thinking_budget` must be between 128 and 32768 tokens

3. **Billing Considerations**: Reasoning tokens count toward your token usage and may incur additional costs. Check your provider's pricing for reasoning tokens.

4. **Session Persistence**: Reasoning settings persist throughout your session until explicitly unset or the proxy is restarted.

For the most up-to-date list of supported models, check the `/models` endpoint or visit the respective provider documentation.

## Temperature Configuration

The proxy provides comprehensive temperature control for fine-tuning model output randomness across different providers.

### Setting Temperature

**In-Chat Commands:**
```bash
!/set(temperature=0.7)    # Set temperature to 0.7
!/unset(temperature)      # Clear temperature setting
```

**Direct API Parameters:**
```json
{
  "model": "openrouter:gpt-4",
  "temperature": 0.8,
  "messages": [...]
}
```

**Model-Specific Defaults (Config File):**
```json
{
  "model_defaults": {
    "openrouter:gpt-4": {
      "reasoning": {
        "temperature": 0.7
      }
    }
  }
}
```

### Provider-Specific Behavior

- **OpenAI/OpenRouter**: Supports temperature range 0.0 to 2.0
- **Gemini**: Supports temperature range 0.0 to 1.0 (values > 1.0 are automatically clamped)

### Temperature Guidelines

- **0.0**: Deterministic output (most conservative)
- **0.3-0.5**: Good for factual, analytical tasks
- **0.7**: Balanced creativity and coherence (recommended default)
- **0.9-1.0**: High creativity for brainstorming, creative writing
- **1.5-2.0**: Maximum creativity (OpenAI only, use with caution)

### Precedence Order

1. Direct API parameters (highest priority)
2. Session-level settings (`!/set(temperature=...)`)
3. Model-specific defaults (from config file)
4. Provider defaults (lowest priority)

## Configuration

The proxy's runtime configuration is determined by a hierarchy of settings, allowing for flexible deployment and management.

### Model-Specific Reasoning Defaults

You can configure default reasoning parameters for specific models in the configuration file. This allows you to automatically apply appropriate reasoning settings based on the model being used, without needing to set them manually for each session.

#### Configuration File Format

```json
{
  "default_backend": "openrouter",
  "interactive_mode": true,
  "model_defaults": {
    "openrouter:openai/o1": {
      "reasoning": {
        "reasoning_effort": "high",
        "temperature": 0.3
      }
    },
    "gemini:gemini-2.5-pro": {
      "reasoning": {
        "thinking_budget": 2048,
        "generation_config": {
          "thinkingConfig": {
            "thinkingBudget": 2048
          },
          "temperature": 0.7
        },
        "temperature": 0.7
      }
    }
  }
}
```

#### Model Naming Patterns

Model defaults can be specified using:
- **Full model names**: `"openrouter:openai/o1"`, `"gemini:gemini-2.5-pro"`
- **Short model names**: `"gemini-exp-1206"` (matches any backend)

#### Reasoning Configuration Options

**For OpenAI-Compatible Models (OpenRouter):**
- `reasoning_effort`: Set to `"low"`, `"medium"`, or `"high"`
- `reasoning`: Unified reasoning config with `effort`, `max_tokens`, `exclude` fields

**For Gemini Models:**
- `thinking_budget`: Number of tokens (128-32768) allocated for reasoning
- `generation_config`: Full Gemini generation configuration including `thinkingConfig`
- `temperature`: Controls randomness (0.0-1.0 for Gemini, automatically clamped if > 1.0)

**Universal Parameters:**
- `temperature`: Controls output randomness (0.0-2.0 for OpenAI/OpenRouter, 0.0-1.0 for Gemini)

#### How It Works

1. When a request is made, the proxy determines the effective model
2. If model defaults exist for that model, they are applied automatically
3. Session-level settings (from `!/set` commands) take precedence over defaults
4. Direct API parameters take precedence over both defaults and session settings

#### Example Configuration

See `config/sample-reasoning-config.json` for a comprehensive example with various reasoning models configured.

### Configuration Sources

The proxy loads its configuration from the following sources, in order of precedence (later sources override earlier ones):

1. **Default Values**: Hardcoded defaults within the application (e.g., `proxy_port` defaults to `8000`).
2. **Environment Variables**: Values loaded from the system environment or a `.env` file in the project root. This is the primary way to set API keys and general runtime parameters.
    - **`.env` file**: A file named `.env` in the project's root directory is automatically loaded at startup. This is ideal for managing sensitive information like API keys and for setting common parameters without modifying system-wide environment variables. An example is provided in `.env.example`.
3. **CLI Arguments**: Command-line arguments provided when starting `main.py`. These arguments override corresponding environment variables and default values, useful for one-off testing or specific deployments.
4. **Persistent Configuration File**: A JSON file specified by the `--config` CLI argument (e.g., `--config config/file.json`). This file is used to persist dynamic settings like failover routes and other in-chat command modifications across proxy restarts.

### Persistent Configuration File

The `--config FILE` CLI argument points to a JSON file that the proxy uses to save and load certain runtime configurations. This is particularly useful for:

- **Failover Routes**: Routes created or modified using in-chat commands (e.g., `!/create-failover-route`, `!/route-append`) are saved to this file.
- **Default Backend**: Changes made via `!/set(default-backend=...)` are persisted.
- **Other Dynamic Settings**: Any other settings that can be modified via in-chat commands and are designed for persistence.

This file allows you to maintain your dynamic routing and default preferences across server restarts without needing to re-enter commands or set environment variables. The file is automatically updated by the proxy when relevant commands are executed.

## Routing Policies Explained

The proxy implements flexible routing policies to manage how requests are sent to different LLM backends and their associated API keys. This ensures resilience, load distribution, and efficient use of resources.

### Default Routing (Fixed Setting)

If no specific failover route is defined for a requested model, the proxy defaults to a fixed routing strategy. It will use the backend specified by the `LLM_BACKEND` environment variable (or `--default-backend` CLI argument) and attempt to use its first configured API key. There is no automatic failover or key rotation in this default mode.

### Failover Routing

Failover routing allows you to define a sequence of backend/model/key combinations to try if an initial attempt fails (e.g., due to rate limiting, network errors, or model unavailability). The proxy will sequentially attempt each combination in the defined route until a successful response is received.

Failover routes are configured using the `!/create-failover-route` command, specifying a `name` and a `policy`. The `policy` determines how the list of attempts is constructed from the route's elements.

#### Failover Policy Details

- **`k` (Keys Failover)**:
  - **Description**: This policy is designed for a single target model but with multiple API keys for its backend. It will attempt to use the specified model, cycling through all available API keys for that backend until a successful response is received.
  - **Use Case**: Maximizing usage of a specific model by leveraging multiple API key allowances (e.g., free tiers).
  - **Example**: If a route `myroute` is defined with `policy=k` and elements `["openrouter:gpt-4"]`, and you have `OPENROUTER_API_KEY_1`, `OPENROUTER_API_KEY_2`, the proxy will first try `openrouter:gpt-4` with `OPENROUTER_API_KEY_1`. If that fails, it will try `openrouter:gpt-4` with `OPENROUTER_API_KEY_2`, and so on.

- **`m` (Models Failover)**:
  - **Description**: This policy allows you to define a sequence of different `backend:model` pairs. For each backend in the sequence, it will attempt to use only its *first* configured API key. If an attempt fails, it moves to the next `backend:model` pair in the route.
  - **Use Case**: Prioritizing certain models or backends, then falling back to alternatives if the primary options are unavailable.
  - **Example**: If `myroute` has `policy=m` and elements `["openrouter:gpt-4", "gemini:gemini-pro"]`, the proxy will first try `openrouter:gpt-4` with `OPENROUTER_API_KEY_1`. If that fails, it will then try `gemini:gemini-pro` with `GEMINI_API_KEY_1`.

- **`km` (Keys then Models Failover)**:
  - **Description**: This policy combines `k` and `m`. For each `backend:model` pair specified in the route, the proxy will first attempt to use *all* available API keys for that specific backend. Only after exhausting all keys for the current `backend:model` pair will it move to the next `backend:model` pair in the route.
  - **Use Case**: Ensuring maximum utilization of all available keys for a primary model before considering alternative models.
  - **Example**: If `myroute` has `policy=km` and elements `["openrouter:gpt-4", "gemini:gemini-pro"]`, and OpenRouter has `OR_KEY_1, OR_KEY_2`, while Gemini has `GM_KEY_1`, the proxy will try:
        1. `openrouter:gpt-4` with `OR_KEY_1`
        2. `openrouter:gpt-4` with `OR_KEY_2` (if 1 fails)
        3. `gemini:gemini-pro` with `GM_KEY_1` (if 2 fails)

- **`mk` (Models then Keys - Round-Robin Distribution)**:
  - **Description**: This policy provides a form of round-robin distribution across available API keys for *multiple* backends/models. It constructs an interleaved sequence of attempts by cycling through the API keys for each backend listed in the route elements. This helps distribute the load more evenly across your available credentials.
  - **Use Case**: Load balancing requests across multiple API keys and backends to prevent hitting rate limits on a single key or backend, or to distribute costs.
  - **Example**: If `myroute` has `policy=mk` and elements `["openrouter:gpt-4", "gemini:gemini-pro"]`, and OpenRouter has keys `OR_KEY_1, OR_KEY_2`, and Gemini has `GM_KEY_1, GM_KEY_2, GM_KEY_3`, the proxy will try:
        1. `openrouter:gpt-4` with `OR_KEY_1`
        2. `gemini:gemini-pro` with `GM_KEY_1`
        3. `openrouter:gpt-4` with `OR_KEY_2` (if available)
        4. `gemini:gemini-pro` with `GM_KEY_2` (if available)
        5. `gemini:gemini-pro` with `GM_KEY_3` (if available, OpenRouter has no more keys at this index)
        This ensures that requests are distributed across the available keys for each backend in a cyclical manner, providing a more balanced load.

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
