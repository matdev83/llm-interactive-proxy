# Requirements Document

## Introduction
This specification defines requirements for a follow-up refactor of the OpenAI Codex connector to improve modularity, testability, and maintainability while preserving current behavior and avoiding regressions across the proxy.

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Developers integrating LLM capabilities via unified API
- Operators managing backend configurations and monitoring
- End-users consuming LLM responses through client applications

## Requirements

### Requirement 1: Behavior Compatibility
**Objective:** As a developer integrating LLM clients, I want the Codex connector refactor to preserve existing behavior, so that client integrations remain stable.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1.1. When the proxy routes a chat completions or responses request to the Codex backend, the Codex connector shall produce response payloads that match the current schema and field semantics for those endpoints.
1.2. When streaming is requested for the Codex backend, the Codex connector shall emit streaming events in the same ordering and termination behavior as the current connector.
1.3. If the upstream Codex API returns an error, timeout, or invalid response, the Codex connector shall map the outcome to the same `LLMProxyError` subclass and HTTP status as the current connector.
1.4. When configuration values for the Codex backend are provided, the Codex connector shall honor the same supported configuration keys, defaults, and precedence as the current connector.
1.5. When a request is in native Responses format, the Codex connector shall preserve current passthrough detection and validation behavior.
1.6. When tool schemas are merged with custom tools, the Codex connector shall preserve the current collision handling behavior for conflicting tool definitions.

#### Technical Constraints
- Async compatibility: Must use `async/await` patterns
- Error hierarchy: Exceptions extend `LLMProxyError`
- API surface stability: No breaking changes to exposed backend type or config keys
- Config precedence: CLI > ENV > YAML

### Requirement 2: Modular Responsibilities and SOLID Boundaries
**Objective:** As a maintainer, I want connector responsibilities separated with clear contracts, so that changes are isolated and easier to reason about.

**Priority:** P1 (High)

#### Acceptance Criteria
2.1. The Codex connector shall expose distinct, independently testable components for settings, credentials, payload preparation, response execution, compatibility handling, and tool execution.
2.2. When request preparation behavior changes, the Codex connector shall allow updates within request preparation components without requiring modifications to response execution or streaming handling components to preserve correct behavior.
2.3. Where optional capabilities such as streaming or tool calls are enabled, the Codex connector shall encapsulate their logic in dedicated components so that the base request and response path remains stable.
2.4. The Codex connector shall interact with components exclusively through public interfaces or documented adapters, not through direct access to private component state.

#### Technical Constraints
- SOLID and DRY principles guide component boundaries
- No circular dependencies between connector components
- Connector modules remain within the `src/connectors/` package boundary
- Avoid cross-layer imports from controller or transport layers

### Requirement 3: Single Execution Path Delegation
**Objective:** As a platform engineer, I want request execution centralized, so that streaming retry and error handling remain consistent and testable.

**Priority:** P1 (High)

#### Acceptance Criteria
3.1. When the Codex responses API is invoked, the Codex connector shall delegate network execution and streaming retry handling to the response execution component.
3.2. While a Codex request is being executed, the Codex connector shall not implement parallel streaming retry or authentication refresh behavior outside the response execution component.
3.3. When a response execution component is configured, the Codex connector shall use it for both streaming and non-streaming requests.
3.4. If a response execution component override is provided and does not satisfy the response execution interface contract, the Codex connector shall fail fast with a clear error rather than using an alternate execution path.

#### Technical Constraints
- Async compatibility: Must use `async/await` patterns
- Error hierarchy: Exceptions extend `LLMProxyError`

### Requirement 4: DI and Wiring Compatibility
**Objective:** As a platform engineer, I want the connector to integrate cleanly with DI and staged initialization, so that startup behavior remains stable.

**Priority:** P1 (High)

#### Acceptance Criteria
4.1. When backend discovery runs during startup, the Codex connector shall register the backend using the existing backend type identifier.
4.2. The Codex connector shall accept external collaborators through `CodexConnectorDependencies` for component interfaces so they can be substituted in tests.
4.3. When DI provides a component override, the Codex connector shall use the override without requiring code changes elsewhere.
4.4. When DI does not provide an override for connector-bound components, the Codex connector shall construct defaults and remain functional.
4.5. While running within staged initialization, the Codex connector shall remain instantiable by the existing backend stage without requiring new stages.

#### Technical Constraints
- DI integration: Services registered via `ServiceCollection`
- Interfaces: Contracts sourced from connector-local or `src/core/interfaces/` where applicable
- Staged init compatibility: No new stage ordering requirements

### Requirement 5: Credential Safety and Concurrency
**Objective:** As a platform engineer, I want credential loading and refresh to be concurrency-safe, so that token handling remains reliable under parallel requests.

**Priority:** P0 (Critical)

#### Acceptance Criteria
5.1. When multiple requests or file watcher events trigger credential reload or refresh, the Codex credential manager shall prevent concurrent refresh races and ensure a consistent final in-memory credential state.
5.2. If refreshed credentials are persisted, the Codex credential manager shall ensure the credentials file is not left partially written or corrupted.
5.3. When the credentials file changes during runtime, the Codex credential watcher shall schedule at most one reload task per change event window and resume normal operation afterward.
5.4. When credential shutdown is requested, the Codex credential watcher shall stop and no new reload tasks shall be scheduled.

#### Technical Constraints
- Credential handling must remain compatible with current OAuth token refresh behavior
- File watching behavior must remain functional on Windows and Unix environments

### Requirement 6: Streaming Retry Parity
**Objective:** As an operator, I want streaming authentication recovery to behave the same as today, so that long-running streams remain reliable.

**Priority:** P1 (High)

#### Acceptance Criteria
6.1. When a streaming request encounters authentication failure during the initial handshake, the Codex response execution component shall attempt retries with the same retry budget and backoff behavior as the current connector.
6.2. When a streaming chunk indicates authentication failure, the Codex response execution component shall follow the same retry and termination behavior as the current connector.
6.3. If retries are exhausted, the Codex connector shall return the same error shape and status as the current connector.
6.4. The Codex connector shall honor the existing configuration for retry limits and backoff sequences.

#### Technical Constraints
- Retry limits and backoff sequences remain configurable via existing settings

### Requirement 7: Compatibility Flows and Tool Execution
**Objective:** As a developer, I want compatibility flows to remain stable, so that KiloCode and Droid clients continue to work without regressions.

**Priority:** P1 (High)

#### Acceptance Criteria
7.1. When KiloCode or Droid compatibility is detected, the Codex compatibility layer shall preserve current tool translation semantics and tool execution result formatting.
7.2. When streaming compatibility translation is applied, the Codex connector shall preserve ordering and emit translated chunks consistent with current behavior.
7.3. After streaming completes or errors, the Codex compatibility layer shall clean up per-request state.
7.4. Where compatibility features are disabled, the Codex connector shall keep the base request and response path unchanged.

#### Technical Constraints
- Compatibility logic remains within connector boundaries
- Tool execution remains compatible with existing proxy and MCP tool contracts

### Requirement 8: Observability and Capture Continuity
**Objective:** As an operator, I want observability signals preserved, so that monitoring and debugging remain consistent.

**Priority:** P1 (High)

#### Acceptance Criteria
8.1. When a request is processed by the Codex connector, the Codex connector shall continue to provide usage metadata required by usage tracking services.
8.2. When wire capture is enabled, the Codex connector shall continue to return response envelopes that are compatible with the core wire-capture orchestration (including streaming wrapping) without requiring connector-specific capture code changes.
8.3. If capture or usage services fail, the Codex connector shall follow existing error propagation behavior for those services without altering the primary response path.
8.4. The Codex connector shall continue to emit structured logs with the same log levels and correlation fields as the current connector.
8.5. The Codex connector shall continue to redact secrets in logs and captures.

#### Technical Constraints
- Logging follows existing structlog patterns
- Capture integration uses existing capture services and schemas

### Requirement 9: Testability and Maintainability
**Objective:** As a developer, I want the refactored connector to be easy to test and maintain, so that future changes are low-risk.

**Priority:** P1 (High)

#### Acceptance Criteria
9.1. When unit tests execute, the Codex connector components shall allow request preparation, response execution, and error translation to be exercised without network I/O by substituting mocked transport dependencies.
9.2. If a new request or response field is added, the Codex connector shall allow the change to be implemented within a single component without modifying unrelated components.
9.3. The Codex connector shall provide clear, documented interfaces for its internal components so they can be mocked or faked in tests.
9.4. The Codex connector shall preserve or improve type annotations so that mypy validates the connector APIs without new ignore directives.
9.5. If internal attributes used by existing tests are removed or relocated, the Codex connector shall provide equivalent access points or documented replacements.
9.6. When tests configure Codex component behavior, the Codex connector shall provide stable, documented configuration points without requiring tests to mutate private fields on production classes.

#### Technical Constraints
- Type annotations align with current mypy configuration
- No new mandatory external dependencies for unit tests
- Test seams provided via interfaces or DI

## Non-Functional Requirements

### NFR 1: Performance
- Response latency: No regression compared to the pre-refactor baseline in existing integration benchmarks for non-streaming requests
- Streaming first-byte: No regression compared to the pre-refactor baseline in existing integration benchmarks
- Throughput: No regression in requests per second under existing load tests

### NFR 2: Reliability
- Backend failover: Connector errors remain eligible for existing retry and failover logic
- Circuit breaker: Connector behavior does not bypass existing circuit breaker thresholds
- Rate limiting: Existing rate limiting and usage accounting flows remain unchanged

### NFR 3: Observability
- Wire captures: Capture payloads and correlation IDs remain consistent with current behavior
- Logging levels: Error, warning, and info levels remain consistent for equivalent conditions
- Health checks: No new health check endpoints are required

### NFR 4: Security
- API key handling: Secrets remain redacted from logs and captures
- Input validation: Request validation rules are not relaxed
- Authentication: No changes to authentication or authorization requirements for backend configuration

## Glossary
| Term | Definition |
|------|------------|
| Backend | LLM provider connector (OpenAI, Anthropic, Gemini, etc.) |
| Wire Capture | CBOR-encoded traffic recording for debugging |
| Staged Init | Sequential initialization phases for services |
| DI Container | Dependency injection via `ServiceCollection` |
