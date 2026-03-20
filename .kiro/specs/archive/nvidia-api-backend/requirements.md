# Requirements Document

## Introduction

This specification adds **Nvidia** as a selectable LLM backend for the Universal LLM Proxy, so clients can route traffic using the same `backend:model` conventions and frontends as for existing providers.

**Project context**: Universal LLM Proxy — traffic routing, failover, accounting, and observability across multiple LLM backends (async FastAPI, staged initialization, connector registry).

**Stakeholders**:

- Developers routing inference through the proxy to Nvidia-hosted models
- Operators configuring backends, credentials, and resilience policies
- Maintainers extending the connector catalog without breaking shared completion and capture behavior

**Input (from spec init)**: Add Nvidia API backend.

## Requirements

### Requirement 1: Backend identity and registration

**Objective:** As an operator, I want Nvidia exposed as a distinct backend type, so that I can target it explicitly in configuration and in `backend:model` selections.

**Priority:** P0

#### Acceptance Criteria

1. The Universal LLM Proxy shall expose a stable backend type identifier for Nvidia that operators can reference consistently (for example in `backend:model` and backend configuration).
2. When the application completes backend-stage initialization, the Nvidia backend shall be registered in the same backend registry mechanism used by other first-class connectors, so it is discoverable for routing and health-related flows.
3. Where the Nvidia backend is disabled or not configured, the Universal LLM Proxy shall not advertise it as an available routing target for new requests.

#### Technical constraints

- Registration and discovery shall follow existing connector patterns (`src/connectors/`, backend registry) without introducing a parallel ad-hoc registration path.

---

### Requirement 2: Configuration and credentials

**Objective:** As an operator, I want Nvidia connection settings and secrets managed through the proxy’s normal configuration surfaces, so that deployment matches CLI, environment, and YAML precedence rules.

**Priority:** P0

#### Acceptance Criteria

1. The Universal LLM Proxy shall allow operators to configure Nvidia connectivity (including any base URL or region endpoint the vendor documents for the chosen API) through the same configuration model and validation approach as comparable API-key backends.
2. If required Nvidia credentials are missing or invalid for a configured instance, the Universal LLM Proxy shall fail in a predictable, operator-visible way at startup or first use (consistent with comparable backends), rather than silently falling back to another vendor.
3. Where configuration supports optional tuning parameters (timeouts, model allowlists, or similar), the Universal LLM Proxy shall validate declared values and reject invalid combinations with clear diagnostics.
4. Where the Nvidia API key is not supplied via a higher-precedence configuration source, the Universal LLM Proxy shall resolve the API key from the `NVIDIA_API_KEY` environment variable when that variable is set.

#### Technical constraints

- Configuration precedence shall remain **CLI > ENV > YAML > defaults** where applicable.
- Operators shall be able to provide the Nvidia API key via the `NVIDIA_API_KEY` environment variable; user-facing documentation shall name this variable and describe its place in the precedence order relative to YAML and CLI.

---

### Requirement 3: Chat completion execution

**Objective:** As a client developer, I want chat-style completion requests routed to Nvidia when selected, so that application code does not need Nvidia-specific SDKs beyond the proxy’s supported frontends.

**Priority:** P0

#### Acceptance Criteria

1. When a request specifies the Nvidia backend (via configured routing rules and `backend:model` or equivalent selection), the Universal LLM Proxy shall forward the request to Nvidia’s supported HTTP inference interface and return responses through the same frontend contract the client used (for example OpenAI-compatible chat completions where that path is supported).
2. When the client requests a non-streaming completion, the Universal LLM Proxy shall return a complete response payload appropriate to that frontend once the upstream call finishes successfully.
3. When the client requests a streaming completion, the Universal LLM Proxy shall stream incremental output to the client without buffering the full upstream response before the stream begins, except where buffering is unavoidable due to protocol translation (in which case behavior shall match documented proxy constraints for similar backends).
4. While an upstream Nvidia call is in progress, the Universal LLM Proxy shall preserve request correlation identifiers in logs and captures consistently with other backends.

#### Technical constraints

- Work shall remain async/non-blocking for I/O on the hot path.

---

### Requirement 4: Errors, resilience, and accounting

**Objective:** As an operator, I want Nvidia failures and usage treated like other backends, so that failover, limits, and cost signals remain trustworthy.

**Priority:** P1

#### Acceptance Criteria

1. If Nvidia returns an error response or the connection fails, the Universal LLM Proxy shall map the outcome to structured proxy errors and HTTP statuses consistent with existing backend error handling policies.
2. If resilience configuration includes Nvidia in failover groups or ordered backends, when Nvidia fails for a given request, the Universal LLM Proxy shall apply the same failover semantics as for other eligible backends in that configuration.
3. When usage accounting is enabled, the Universal LLM Proxy shall record token or usage metrics for Nvidia responses to the same degree of fidelity as for comparable API backends (including streaming aggregates where supported).

#### Technical constraints

- Domain errors shall use the project’s `LLMProxyError` hierarchy and transport mapping conventions.

---

### Requirement 5: Observability

**Objective:** As a maintainer, I want Nvidia traffic visible in existing observability tooling, so that incidents and regressions are diagnosable without custom tracing.

**Priority:** P1

#### Acceptance Criteria

1. Where wire capture is enabled, the Universal LLM Proxy shall include Nvidia upstream and downstream traffic in captures with the same capture modes and redaction rules as other API backends.
2. The Universal LLM Proxy shall emit structured log events for Nvidia requests that include correlation fields comparable to other backends (request id, backend type, model identifier, outcome).

#### Technical constraints

- Secrets (API keys, bearer tokens) shall not appear in logs or captures beyond existing redaction behavior.

---

### Requirement 6: Documentation

**Objective:** As an operator, I want concise user-facing documentation, so that I can enable and verify the Nvidia backend without reading source code.

**Priority:** P2

#### Acceptance Criteria

1. The Universal LLM Proxy shall ship or update user-facing documentation that describes how to enable the Nvidia backend, required configuration fields, and how to select `backend:model` values.
2. Where Nvidia exposes model naming or endpoint constraints that affect proxy configuration, the documentation shall state those constraints explicitly.

#### Technical constraints

- Documentation updates shall live alongside existing backend guides (for example under `docs/user_guide/backends/`) rather than only in code comments.

---

## Non-functional requirements

### NFR 1: Performance

- For non-streaming chat completions, end-to-end latency shall not regress median proxy overhead versus comparable API-key backends on the same hardware (measured as proxy-added latency, excluding upstream Nvidia inference time).
- For streaming, time-to-first-byte observed by the client shall remain in line with other streaming API backends under similar network conditions.

### NFR 2: Reliability

- Connection handling shall use resilient HTTP client settings consistent with other backends (retries only where aligned with existing backend policy).
- Long-running streams shall tolerate normal client disconnects without destabilizing the server process.

### NFR 3: Observability

- Metrics and captures for Nvidia shall be attributable per backend type in inspection tools (for example capture inspection scripts).

### NFR 4: Security

- Credentials shall be loaded only through configuration mechanisms; they shall not be logged or embedded in error messages returned to clients.

## Glossary

| Term | Definition |
|------|------------|
| Backend | LLM provider connector registered with the proxy’s backend registry |
| Backend type | Stable string identifier for a connector (used in routing and config) |
| `backend:model` | Proxy convention for selecting provider and model in one token |
| Wire capture | CBOR (or configured) recording of request/response traffic for debugging |
| Universal LLM Proxy | The FastAPI-based proxy product described in steering |
