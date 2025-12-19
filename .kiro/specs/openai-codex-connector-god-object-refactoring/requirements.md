# Requirements Document

## Introduction
This specification defines requirements for refactoring the OpenAI Codex connector to reduce complexity, improve modularity, and preserve existing behavior within the LLM Interactive Proxy.

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Developers integrating LLM capabilities via unified API
- Operators managing backend configurations and monitoring
- End-users consuming LLM responses through client applications

## Requirements

### Requirement 1: Behavior Compatibility
**Objective:** As a developer integrating LLM clients, I want the OpenAI Codex connector refactor to preserve existing behavior, so that client integrations remain stable.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1. When the proxy routes a chat completions or responses request to the OpenAI Codex backend, the OpenAI Codex connector shall produce response payloads that match the current schema and field semantics for those endpoints.
2. When streaming is requested for the OpenAI Codex backend, the OpenAI Codex connector shall emit streaming events in the same ordering and termination behavior as the current connector.
3. If the upstream OpenAI Codex API returns an error, timeout, or invalid response, the OpenAI Codex connector shall map the outcome to the same `LLMProxyError` subclass and HTTP status as the current connector.
4. When configuration values for the OpenAI Codex backend are provided, the OpenAI Codex connector shall honor the same supported configuration keys and defaults as the current connector.
5. The OpenAI Codex connector shall preserve existing request parameter transformation semantics for supported OpenAI Codex requests.
6. When a request is in native Responses format, the OpenAI Codex connector shall preserve current passthrough detection behavior and validation rules for accepting or rejecting passthrough.
7. When tool schemas are merged with custom tools, the OpenAI Codex connector shall preserve the current collision handling behavior for conflicting tool definitions.

#### Technical Constraints
- Async compatibility: Must use `async/await` patterns
- Error hierarchy: Exceptions extend `LLMProxyError`
- API surface stability: No breaking changes to exposed backend type or config keys
- Config precedence: CLI > ENV > YAML

### Requirement 2: Separation of Concerns and Modularity
**Objective:** As a maintainer, I want connector responsibilities separated, so that changes are isolated and easier to reason about.

**Priority:** P1 (High)

#### Acceptance Criteria
1. The OpenAI Codex connector shall expose distinct, independently testable components for request preparation, response parsing, streaming handling, and error translation.
2. When request preparation changes, the OpenAI Codex connector shall not require modifications to response parsing or streaming handling components to preserve correct behavior.
3. Where optional capabilities such as streaming or tool calls are enabled, the OpenAI Codex connector shall encapsulate their logic so that the base request/response path remains stable.
4. The OpenAI Codex connector shall define explicit interfaces or contracts between its components to prevent direct access to internal state beyond those contracts.

#### Technical Constraints
- SOLID and DRY principles guide component boundaries
- No circular dependencies between connector components
- Connector modules remain within the `src/connectors/` package boundary
- Avoid cross-layer imports from controller or transport layers

### Requirement 3: DI and Layering Compliance
**Objective:** As a platform engineer, I want the connector to align with DI and layering rules, so that staged initialization and service wiring remain stable.

**Priority:** P1 (High)

#### Acceptance Criteria
1. When backend discovery runs during startup, the OpenAI Codex connector module shall register the backend using the existing backend type identifier.
2. The OpenAI Codex connector shall accept external collaborators through dependency injection so they can be substituted in tests.
3. The OpenAI Codex connector shall not depend on controller-layer types outside the connector boundary.
4. While running within staged initialization, the OpenAI Codex connector shall remain instantiable by the existing backend stage without requiring new stages.

#### Technical Constraints
- DI integration: Services registered via `ServiceCollection`
- Interfaces: Contracts sourced from `src/core/interfaces/` where applicable
- Staged init compatibility: No new stage ordering requirements

### Requirement 4: Testability and Maintainability
**Objective:** As a developer, I want the refactored connector to be easy to test and maintain, so that future changes are low-risk.

**Priority:** P1 (High)

#### Acceptance Criteria
1. When unit tests execute, the OpenAI Codex connector shall allow request preparation, response parsing, and error translation to be exercised without network I/O by substituting mocked transport dependencies.
2. If a new request or response field is added, the OpenAI Codex connector shall allow the change to be implemented within a single component without modifying unrelated components.
3. The OpenAI Codex connector shall provide clear, documented interfaces for its internal components so they can be mocked or faked in tests.
4. The OpenAI Codex connector shall preserve or improve type annotations so that mypy validates the connector APIs without new ignore directives.

#### Technical Constraints
- Type annotations align with current mypy configuration
- No new mandatory external dependencies for unit tests
- Test seams provided via interfaces or DI

### Requirement 5: Observability and Capture Continuity
**Objective:** As an operator, I want the refactor to preserve usage tracking and wire capture behavior, so that observability remains intact.

**Priority:** P1 (High)

#### Acceptance Criteria
1. When a request is processed by the OpenAI Codex connector, the OpenAI Codex connector shall continue to provide usage metadata required by usage tracking services.
2. When wire capture is enabled, the OpenAI Codex connector shall continue to supply request and response data needed for CBOR capture records.
3. If capture or usage services fail, the OpenAI Codex connector shall follow existing error propagation behavior for those services without altering the primary response path.
4. The OpenAI Codex connector shall continue to emit structured logs with the same log levels and correlation fields as the current connector.

#### Technical Constraints
- Logging follows existing structlog patterns
- Capture integration uses existing capture services and schemas
- Secrets remain redacted in logs and captures

### Requirement 6: Credential Safety and Concurrency
**Objective:** As a platform engineer, I want credential loading and refresh to be concurrency-safe, so that token handling remains reliable under parallel requests.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1. When multiple requests or file watcher events trigger credential reload or refresh, the OpenAI Codex connector shall prevent concurrent refresh races and ensure a consistent final in-memory credential state.
2. If refreshed credentials are persisted, the OpenAI Codex connector shall ensure the credentials file is not left partially written or corrupted.
3. When the credentials file changes during runtime, the OpenAI Codex connector shall schedule at most one reload task per change event window and resume normal operation afterward.

#### Technical Constraints
- Credential handling must remain compatible with current OAuth token refresh behavior
- File watching behavior must remain functional on Windows and Unix environments

### Requirement 7: Streaming Retry Parity
**Objective:** As an operator, I want streaming authentication recovery to behave the same as today, so that long-running streams remain reliable.

**Priority:** P1 (High)

#### Acceptance Criteria
1. When a streaming request encounters authentication failure during the initial handshake, the OpenAI Codex connector shall attempt retries with the same retry budget and backoff behavior as the current connector.
2. When a streaming chunk indicates authentication failure, the OpenAI Codex connector shall follow the same retry and termination behavior as the current connector.
3. If retries are exhausted, the OpenAI Codex connector shall return the same error shape and status as the current connector.

#### Technical Constraints
- Retry limits and backoff sequences remain configurable via existing settings

### Requirement 8: Internal API and Test Seam Stability
**Objective:** As a test author, I want internal seams to remain accessible or be replaced with stable interfaces, so that existing Codex tests can be updated with minimal churn.

**Priority:** P1 (High)

#### Acceptance Criteria
1. When refactoring introduces new components, the OpenAI Codex connector shall expose stable interfaces or adapters so that existing unit and integration tests can exercise Codex behavior without network I/O.
2. If internal attributes used by existing tests are removed or relocated, the OpenAI Codex connector shall provide equivalent access points or documented replacements.
3. The OpenAI Codex connector shall preserve current behavior of KiloCode and Droid compatibility flows for test coverage in existing Codex test suites.

#### Technical Constraints
- Test seams must not require new mandatory external dependencies

### Requirement 9: Documentation and Configuration Parity
**Objective:** As a maintainer, I want documented configuration options to remain valid, so that refactoring does not break user guidance.

**Priority:** P2 (Medium)

#### Acceptance Criteria
1. The OpenAI Codex connector shall continue to honor the configuration keys documented for the Codex backend.
2. When configuration defaults or behaviors are preserved, the OpenAI Codex connector shall keep the documented default behavior consistent.

#### Technical Constraints
- Configuration precedence remains CLI > ENV > YAML

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
- Wire captures: Capture payloads and correlation IDs remain consistent with pre-refactor behavior
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
| OpenAI Codex connector | Backend connector for the OpenAI Codex API |
