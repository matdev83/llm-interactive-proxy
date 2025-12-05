# Backend Instances Concept

The **Backend Instances** architecture allows the proxy to support multiple distinct instances of the same backend connector type (e.g., multiple `openai` or `gemini` backends). This enables granular control over routing, rate limiting, logging, and configuration for different credentials or use cases using the same underlying provider logic.

## Core Concept

Traditionally, the proxy mapped backend types 1:1 with connectors (e.g., `openai` configuration used the `openai` connector).

The new architecture decouples **Backends** (instances) from **Connectors** (implementations):
- **Connector**: The code implementation (e.g., `src/connectors/openai.py`).
- **Backend Instance**: A configured instance of a connector with a unique name (e.g., `openai.primary`, `openai.backup`, `gemini.pro`).

## Key Features

1.  **Multi-Instance Support**: Define multiple backends using the same connector (e.g., `gemini.1`, `gemini.2`).
2.  **Granular Rate Limiting**: Each instance has its own independent rate limit bucket.
3.  **Instance-Based Routing**: Route traffic to specific instances (e.g., `openai.production:gpt-4`).
4.  **Isolated Logging**: Logs and metrics track the specific instance name.
5.  **Multimodal Capabilities**: Instances can declare `supported_input_types` (e.g., `image`, `pdf`).

## Naming Convention

Backend instances follow a structured naming convention:
```
<connector-name>.<instance-name>
```
- **Connector Name**: Must match a registered connector (e.g., `openai`, `gemini`, `anthropic`).
- **Instance Name**: Arbitrary identifier (e.g., `primary`, `dev`, `1`).

Examples:
- `openai.primary` (Connector: `openai`)
- `gemini.team-a` (Connector: `gemini`)
- `gemini-oauth-plan.production` (Connector: `gemini-oauth-plan`)

## Configuration Methods

Backend instances can be configured via three primary methods, processed in the following priority order:

### 1. Configuration File (YAML)
Define instances directly in `config/config.yaml` under the `backends` section. You must specify the `connector` field if the instance name doesn't match a connector name exactly.

```yaml
backends:
  # Standard implicit definition
  openai:
    api_key: "sk-..."

  # Explicit instance definition
  openai.dev:
    connector: "openai"
    api_key: "sk-dev-..."
    allow_concurrent_use: true

  gemini.backup:
    connector: "gemini"
    api_key: "AIza..."
```

### 2. Instance Configuration Files
Place YAML files in `config/backends/backend-instances/`. The filename determines the instance name:
- Filename pattern: `<connector>.<name>.yaml`
- Example: `config/backends/backend-instances/openai.team-b.yaml`

Content of `openai.team-b.yaml`:
```yaml
api_key: "sk-..."
timeout: 120
```
This automatically creates a backend instance named `openai.team-b`.

### 3. Environment Variables (Auto-Discovery)
The system automatically discovers numbered instances via environment variables.

Format: `{CONNECTOR_UPPERCASE}_API_KEY_{N}`

- `OPENAI_API_KEY_1=sk-...` -> Creates `openai.1`
- `OPENAI_API_KEY_2=sk-...` -> Creates `openai.2`
- `GEMINI_API_KEY_1=AIza...` -> Creates `gemini.1`

## Advanced Configuration

### Credentials Path
For file-based backends (OAuth), you can specify the credentials file path. The system enforces uniqueness to prevent conflicts.

```yaml
gemini-oauth-plan.user1:
  connector: "gemini-oauth-plan"
  credentials_path: "var/creds/user1.json"
```

### Multimodal Input Types
Declare what input types an instance supports for validation.

```yaml
gemini.vision:
  connector: "gemini"
  supported_input_types: ["image", "video", "pdf"]
```

## Implementation Details

- **BackendFactory**:
  - Resolves the connector type from the instance name (split by `.`).
  - Sets the `backend_type` attribute of the instance to the full instance name to ensure unique identity for logging and rate limiting.
- **BackendSettings**:
  - Handles the discovery logic (scanning env vars and the `backend-instances` directory).
  - Merges configurations from different sources.
  - Validates uniqueness of credential paths.
