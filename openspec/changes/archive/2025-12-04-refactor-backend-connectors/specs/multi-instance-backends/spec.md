# Backend Connector Separation

## ADDED Requirements

### Requirement: Naming Convention for Backend Instances
Backend instances MUST have unique names following the format `<connector-name>.<instance-name>`.
-   The name MUST consist of only ASCII characters, numbers, and hyphens.
-   The name MUST include exactly one dot `.` separator (implied by the prefix/suffix logic, though typically "first dot" is the delimiter).
-   Slashes, backslashes, spaces, colons, and other special characters are NOT allowed.
-   The prefix (before the dot) MUST correspond to a valid, registered connector name.

#### Scenario: Valid instance name
Given a configured backend name "gemini-oauth-plan.account1"
When the system validates the name
Then it should accept it as valid
And identify "gemini-oauth-plan" as the connector

#### Scenario: Invalid instance name (no dot)
Given a configured backend name "gemini_account1"
When the system validates the name
Then it should reject it (unless it is a legacy/default backend)

#### Scenario: Invalid characters
Given a configured backend name "gemini/account1"
When the system validates the name
Then it should reject it due to invalid characters

#### Scenario: Invalid connector prefix
Given a configured backend name "invalidconnector.instance1"
And "invalidconnector" is not a registered backend type
When the system validates the name
Then it should reject it

### Requirement: Automated Instance Creation from Environment Variables (Strategy A)
For API-Key based connectors, the system MUST automatically discover and create backend instances for numbered environment variables corresponding to registered connectors.
-   Format: `{CONNECTOR_UPPERCASE}_API_KEY_{N}`
-   Resulting Instance Name: `{connector}.{N}`

#### Scenario: Auto-discovery of numbered keys
Given the environment variables `OPENROUTER_API_KEY_1=key1` and `OPENROUTER_API_KEY_2=key2`
And "openrouter" is a registered API-Key based backend connector
When the proxy starts up
Then it should automatically create a backend instance named "openrouter.1" with key "key1"
And it should automatically create a backend instance named "openrouter.2" with key "key2"

### Requirement: Instance-Specific Configuration Loading
The system MUST look for and load configuration files for specific backend instances.
-   Location: `config/backends/backend-instances/<instance-name>.yaml`
-   Behavior: If found, the settings in this file override defaults.
-   Logging: The system MUST log whether a config file was found/loaded or not.

#### Scenario: Loading instance config
Given an instance "openrouter.1" created via auto-discovery
And a file exists at `config/backends/backend-instances/openrouter.1.yaml` with content `allow_concurrent_use: false`
When the backend instance is initialized
Then it should have `allow_concurrent_use` set to `False`
And it should log that the config file was loaded

#### Scenario: Missing instance config
Given an instance "openrouter.2" created via auto-discovery
And no file exists at `config/backends/backend-instances/openrouter.2.yaml`
When the backend instance is initialized
Then it should use default settings (e.g., `allow_concurrent_use` is `True`)
And it should log that no config file was found (or use default)

### Requirement: Custom Base URL per Instance
Each backend instance MUST support a custom base URL setting (`api_url`).
-   Default: If not specified, it uses the connector's default URL.
-   Override: Can be set in the instance-specific configuration file.

#### Scenario: Overriding Base URL
Given an instance "openai.staging"
And a config file `config/backends/backend-instances/openai.staging.yaml` with `api_url: "https://staging.openai.com/v1"`
When the backend instance is initialized
Then it should use "https://staging.openai.com/v1" as the base URL

#### Scenario: Default Base URL
Given an instance "openai.production"
And no `api_url` is specified in its config
When the backend instance is initialized
Then it should use the default OpenAI base URL (e.g., "https://api.openai.com/v1")

### Requirement: Global Multimodal Input Types Dictionary
The system MUST maintain a global dictionary of supported multimodal input types (e.g., Image, PDF, Audio).
Instance configurations MUST allow defining supported input types using these keys.

#### Scenario: Override supported input types
Given an instance "gemini.text-only"
And its configuration specifies `supported_input_types: []`
When the backend is initialized
Then it should accept no multimodal inputs

#### Scenario: Default input types
Given an instance "gemini.pro"
And its configuration does not specify `supported_input_types`
When the backend is initialized
Then it should use the connector's default supported types (e.g., Image, PDF)

### Requirement: File-based Credential Discovery (Strategy B)
For backends that use credential files (not API keys), the system MUST discover instances by scanning `config/backends/backend-instances/`.
-   Pattern: `<connector-name>.*.yaml`
-   Action: Create an instance for each matching file.
-   Constraint: No two instances of the same connector type can point to the same credential file path.

#### Scenario: Discover file-based instances
Given `config/backends/backend-instances/qwen-oauth.user1.yaml` points to `creds1.json`
And `config/backends/backend-instances/qwen-oauth.user2.yaml` points to `creds2.json`
When the proxy starts
Then it should create "qwen-oauth.user1" and "qwen-oauth.user2"

#### Scenario: Duplicate credential files
Given `qwen-oauth.user1.yaml` points to `creds1.json`
And `qwen-oauth.user3.yaml` also points to `creds1.json`
When the proxy starts
Then it should refuse to create the second instance (or fail validation) due to duplicate credentials

#### Scenario: Default file-based fallback
Given no config files exist for "qwen-oauth"
When the proxy starts
Then it should create a default instance "qwen-oauth.1" using the default credential path

### Requirement: Instance-specific Concurrency Control
Each backend instance MUST support an `allow_concurrent_use` boolean flag (defaulting to True).
If `allow_concurrent_use` is False, the system MUST prevent multiple concurrent requests to that specific instance.

#### Scenario: Blocking concurrent request
Given an instance "gemini.free-tier" with `allow_concurrent_use: false`
And a request is currently being processed by "gemini.free-tier"
When a second request attempts to use "gemini.free-tier"
Then the system should reject the second request immediately (non-blocking check)
And return a ServiceUnavailable or ResourceBusy error

#### Scenario: Allowing concurrent request
Given an instance "gemini.pro" with `allow_concurrent_use: true`
And a request is currently being processed by "gemini.pro"
When a second request attempts to use "gemini.pro"
Then the system should allow the request to proceed

### Requirement: Granular Rate Limiting (Instance and Model Level)
The system MUST track rate limits at two distinct levels for each backend instance:
1.  **Instance Level**: Affects all models served by the instance (e.g., account-wide quota exceeded).
2.  **Model Level**: Affects only a specific model on the instance (e.g., TPM limit for "gpt-4" reached).

Availability MUST be tracked using absolute timestamps (e.g., `available_after` datetime) rather than relative durations.

#### Scenario: Instance-wide Rate Limit
Given backend instance "openrouter.1"
When a request fails with a global rate limit error (e.g., 429 Account Exceeded) and a 60-second retry-after
Then the system should mark "openrouter.1" as unavailable
And calculate `available_after` as Now + 60 seconds
And subsequent requests to ANY model on "openrouter.1" should be skipped until `available_after`

#### Scenario: Model-specific Rate Limit
Given backend instance "gemini.1" supporting "flash" and "pro"
When a request to "flash" fails with a model-specific rate limit (e.g., 429 Resource Exhausted) and a 30-second retry-after
Then the system should mark "flash" on "gemini.1" as unavailable until Now + 30 seconds
And subsequent requests to "gemini.1:flash" should be skipped
But requests to "gemini.1:pro" should still be allowed to proceed

#### Scenario: Routing with Partial Availability
Given instance "provider.1" where "model-A" is rate-limited but "model-B" is available
And instance "provider.2" where both are available
When a request for "model-A" arrives
Then the system should skip "provider.1" and route to "provider.2"
When a request for "model-B" arrives
Then the system should load balance between "provider.1" and "provider.2"

### Requirement: Automated Backend Resolution and Backward Compatibility
The system MUST support requests using generic backend names (e.g., `gemini`, `openai`) and automatically resolve them to one of the available concrete instances (e.g., `gemini.1`, `gemini.account2`).
This ensures backward compatibility for clients that are unaware of specific instance names.

-   If a request specifies a backend name that matches a registered connector type (but not a specific instance), the system MUST treat it as a request for *any* available instance of that connector.
-   The system MUST apply load balancing (Round Robin) and availability checks (Rate Limiting) to select the best instance.

#### Scenario: Routing Generic Request
Given configured instances "gemini.1" and "gemini.2"
When a client sends a request with model "gemini:gemini-1.5-pro"
Then the system should recognize "gemini" as the connector type
And resolve the request to either "gemini.1" or "gemini.2" based on load balancing policy
And forward the request to the selected instance

#### Scenario: Fallback to Single Instance
Given only one configured instance "anthropic.primary"
When a client sends a request with model "anthropic:claude-3-5-sonnet"
Then the system should resolve "anthropic" to "anthropic.primary"

#### Scenario: No Instances Available
Given no configured instances for connector "minimax"
When a client sends a request with model "minimax:abab6"
Then the system should return an error indicating no backend instances are available for "minimax"

### Requirement: Instance Rotation and Load Balancing
When a request targets a generic connector type (e.g., `openrouter`) but multiple instances are configured (e.g., `openrouter.1`, `openrouter.2`), the system MUST automatically load balance requests across the available instances using a rotation strategy (e.g., Round Robin).

#### Scenario: Round Robin Rotation
Given available instances "openrouter.1" and "openrouter.2"
When the first request for "openrouter:gpt-4" is received
Then the system should route it to "openrouter.1" (or the first available)
When the second request for "openrouter:gpt-4" is received
Then the system should route it to "openrouter.2" (or the next available)

#### Scenario: Instance Failure Skip
Given "openrouter.1" is currently rate limited or busy
And "openrouter.2" is available
When a request for "openrouter:gpt-4" is received
Then the system should route it to "openrouter.2"

### Requirement: Multiple credentials for same connector
The system MUST support configuring multiple instances of the same connector, each with its own API key or credentials path.

#### Scenario: Multiple keys
Given "openai.dev" with key "sk-dev"
And "openai.prod" with key "sk-prod"
When requests are routed to "openai.dev"
Then they should use "sk-dev"

### Requirement: Backend Factory Resolution logic
The `BackendFactory` MUST resolve the connector implementation by parsing the backend instance name to extract the connector prefix.
If the name does not contain a dot (legacy names), it should look up the name directly in the registry.

#### Scenario: Resolve via prefix
Given a backend instance name "anthropic.research-group"
When the factory creates the backend
Then it should use the "anthropic" connector factory

#### Scenario: Legacy fallback
Given a backend instance name "openai"
When the factory creates the backend
Then it should use the "openai" connector factory

