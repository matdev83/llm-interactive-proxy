# Design: Refactor Backend Connectors

## Architecture

### Target State
-   **Registry**: `BackendRegistry` stores connector implementations (`connector_name -> factory`).
-   **Multimodal Dictionary**: A new global module (e.g. `src/core/domain/multimodal.py`) defines standard input types.
-   **Configuration**: `BackendSettings` allows keys in the format `<connector>.<instance>`.
-   **Auto-Discovery Strategies**:
    -   **Strategy A (API Key)**: Scans env vars (e.g., `OPENROUTER_API_KEY_N`).
    -   **Strategy B (Credential File)**: Scans config files (`config/backends/backend-instances/*.yaml`).
-   **Uniqueness**: Enforces that for a given connector, no two instances share the same credentials file path.
-   **Config Loading**: Merges auto-discovered settings with instance-specific YAML files.
-   **Instantiation**: `BackendFactory` uses parsed instance name to resolve connector.
-   **Instance Management**: Tracks runtime state (concurrency).

### Connector Classification

| Connector | Strategy | Notes |
| :--- | :--- | :--- |
| `openai` | A (API Key) | Standard OpenAI compatible |
| `anthropic` | A (API Key) | Standard Anthropic |
| `gemini` | A (API Key) | Standard Gemini API |
| `openrouter` | A (API Key) | |
| `zai` | A (API Key) | |
| `minimax` | A (API Key) | |
| `zenmux` | A (API Key) | |
| `gemini-oauth-free` | B (File) | Uses `FileCredentialProvider` |
| `gemini-oauth-plan` | B (File) | Uses `FileCredentialProvider` |
| `antigravity-oauth` | B (File) | Uses `AntigravitySQLiteCredentialProvider` |
| `gemini-cli-cloud-project` | B (File) | Uses GCP service account or ADC |
| `qwen-oauth` | B (File) | Uses `oauth_creds.json` |
| `anthropic-oauth` | B (File) | Uses `oauth_creds.json` |
| `hybrid` | Manual | Configured via `config.yaml` or dynamic model spec |
| `gemini-cli-acp` | Manual | Spawns subprocess, uses `project_dir` |

## Code Quality & Best Practices

### Immutability Strategy
To prevent unexpected side effects and race conditions, configuration objects MUST be immutable.
-   **BackendConfig**: Already a Pydantic model with `frozen=True`.
-   **Instance Configuration**: The dictionary/object holding resolved instance settings (api_key, url, etc.) passed to `initialize` should be treated as read-only by the backend.
-   **Runtime State**: Mutable state (rate limits, circuit breaker status, connection pools) MUST be separated from configuration.
    -   Use `asyncio.Lock` for shared mutable state where necessary.
    -   Use atomic operations for counters.
    -   Do not modify `self.config` or attributes derived from it after initialization.

### Test Driven Development (TDD)
Implementation MUST follow TDD patterns:
1.  Write a failing test case defining the expected behavior (e.g., "requesting `gemini` round-robins between `.1` and `.2`").
2.  Implement the minimal code to pass the test.
3.  Refactor while keeping tests green.
4.  Tests must cover:
    -   Discovery logic (env vars vs files).
    -   Naming validation.
    -   Load balancing / Rotation.
    -   Model routing (with and without prefixes).
    -   Concurrency limits (non-blocking checks).
    -   Immutability violations (optional, via static analysis or runtime checks).

### Data Flow

#### Strategy A: API Key Backends (e.g., OpenRouter, OpenAI)
1.  **Discovery**:
    -   Scan `config.yaml` -> Creates `openrouter` (legacy/default instance).
    -   Scan Env Vars: `OPENROUTER_API_KEY_1` -> Creates `openrouter.1`.
2.  **Configuration**:
    -   For each instance (e.g., `openrouter.1`), check `config/backends/backend-instances/openrouter.1.yaml`.
    -   If found, load settings (e.g., `api_url`, `allow_concurrent_use`) and merge. **Note**: For Type A, the file does *not* trigger discovery, only configuration.
3.  **Grouping**:
    -   BackendService groups `[openrouter, openrouter.1]` under the `openrouter` connector key for load balancing.

#### Strategy B: Credential File Backends (e.g., Qwen-OAuth, Gemini-OAuth)
1.  **Discovery**:
    -   Scan `config.yaml` -> Creates `qwen-oauth` (legacy/default).
    -   Glob `config/backends/backend-instances/qwen-oauth.*.yaml`.
    -   File `qwen-oauth.user1.yaml` exists -> Creates `qwen-oauth.user1`.
2.  **Configuration**:
    -   The YAML file acts as *both* discovery source AND configuration source.
    -   Contains `credentials_path` + settings (`allow_concurrent_use`).
3.  **Fallback**:
    -   If NO instances found (no config.yaml entry, no files), create default `qwen-oauth.1` using default credential path.
4.  **Validation**:
    -   Check uniqueness of `credentials_path` across ALL instances (legacy + file-discovered).

## Components

### Global Multimodal Registry (`src/core/domain/multimodal.py`)
-   Define constants/enums: `IMAGE`, `PDF`, `AUDIO`, etc.
-   Provide a dictionary of metadata if needed.

### BackendConfig (`src/core/config/app_config.py`)
Add:
-   `allow_concurrent_use: bool = True`.
-   `connector: str | None`.
-   `supported_input_types: list[str] | None`.
-   `api_url`.
-   `credentials_path: str | None`.

### BackendSettings (`src/core/config/app_config.py`)
Update `__init__`:
1.  **Discovery Logic**:
    -   Categorize connectors: `api_key_based` vs `file_based`.
    -   **Legacy**: Load from `config.yaml`.
    -   **Type A**: Scan Env Vars -> Add instances. Check YAML for overrides.
    -   **Type B**: Scan YAML files -> Add instances.
        -   Extract instance name from filename.
        -   Load config.
    -   **Validation**: Enforce `credentials_path` uniqueness across the entire set.
    -   **Fallback**: Apply fallbacks for Type B if empty.

### BackendService (`src/core/services/backend_service.py`)
-   **Instance Registry**: Maintain map of `connector_type -> list[instance_name]`.
    -   Example: `openrouter -> [openrouter, openrouter.1, openrouter.2]`.
-   **Global Model Routing Table**:
    -   Map `model_name -> list[instance_name]`.
    -   Populated via parallel `list_models` calls during startup.
    -   Handles prefixes (e.g. maps `google/gemini-pro` to `gemini-pro` if backend reports it without vendor prefix, or supports direct matching).
-   **Load Balancer**: Implement Round Robin selection.
-   **Failover**: If selected instance fails (e.g. rate limit), try next instance in the group before failing over to a different model/backend.
-   **Granular Rate Limiting**:
    -   Track `instance_available_after` (float timestamp) for global limits.
    -   Track `model_available_after` (dict[str, float]) for model-specific limits.
    -   `is_available(instance, model)`: Checks if instance AND model are available (current_time > available_after).
    -   Update `LLMBackend` interface to expose `set_rate_limit(model=None, duration=...)`.

## Trade-offs
-   **Uniqueness Check**: Requires loading all configs before finalizing instances.
-   **File Naming**: Strict `<connector>.<name>.yaml` requirement.
-   **Rotation State**: Need to track last used instance per connector type (thread-safe).
-   **State Complexity**: Managing two layers of rate limits requires careful state updates and checks.
-   **Model Discovery Latency**: Building the global routing table requires initializing backends and fetching models. **Mitigation**: Perform model fetching in parallel (`asyncio.gather`) during startup.
