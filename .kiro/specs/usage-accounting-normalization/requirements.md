# Requirements Document

## Introduction
This specification defines normalized usage accounting behaviors that eliminate duplication and ensure consistent usage reporting across protocols and backends.

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Developers integrating LLM capabilities via unified API
- Operators managing backend configurations and monitoring
- End-users consuming LLM responses through client applications

## Requirements

### Requirement 1: Canonical Usage Record
**Objective:** As a platform operator, I want usage metrics normalized into a canonical record, so that reporting and billing are consistent.

**Priority:** P0 (Critical)

#### Acceptance Criteria
- 1.1 When a backend response includes usage metrics, the Usage Accounting Service shall produce a canonical usage record for that request.
- 1.2 The Usage Accounting Service shall include provider identifier, model identifier, request identifier, prompt token count, completion token count, total token count, cost, completion outcome, and provider extensions in the canonical usage record when those values are available from inputs.
- 1.3 When prompt token count and completion token count are available, the Usage Accounting Service shall set total token count to their sum.
- 1.4 If a canonical usage field cannot be derived from inputs, the Usage Accounting Service shall set that field to null in the canonical usage record.
- 1.5 When RequestContext.request_id is present, the Usage Accounting Service shall set request identifier to that value.
- 1.6 When RequestContext.request_id is absent and RequestContext.processing_context.values includes request_id, the Usage Accounting Service shall set request identifier to that value.
- 1.7 When backend type is available from response metadata or request context, the Usage Accounting Service shall set provider identifier to that backend type.
- 1.8 When effective model is available from response metadata or request context, the Usage Accounting Service shall set model identifier to that model.
- 1.9 When the request is handled by the OpenAI Chat Completions controller, the Usage Accounting Service shall set protocol to openai.
- 1.10 When the request is handled by the OpenAI Responses controller, the Usage Accounting Service shall set protocol to openai-responses.
- 1.11 When the request is handled by the Anthropic Messages controller, the Usage Accounting Service shall set protocol to anthropic.
- 1.12 When the request is handled by the Gemini controller, the Usage Accounting Service shall set protocol to gemini.

#### Technical Constraints
- Async compatibility: Must use `async/await` patterns
- DI integration: Services registered via `ServiceCollection`
- Error hierarchy: Exceptions extend `LLMProxyError`

### Requirement 2: Cross-Protocol Consistency
**Objective:** As a developer integrating multiple APIs, I want consistent usage metrics across protocols, so that clients receive uniform accounting data.

**Priority:** P0 (Critical)

#### Acceptance Criteria
- 2.1 When equivalent usage inputs are received from different protocol adapters, the Usage Accounting Service shall produce identical canonical usage records.
- 2.2 When a protocol provides additional usage metrics not represented in the canonical schema, the Usage Accounting Service shall store those metrics under a single extensions container in the canonical usage record.
- 2.3 The Usage Accounting Service shall not drop provider-specific usage metrics when they can be represented in the extensions container.
- 2.4 The Usage Accounting Service shall normalize units and naming so that canonical usage fields have consistent meaning across providers.

#### Technical Constraints
- Async compatibility: Must use `async/await` patterns
- DI integration: Services registered via `ServiceCollection`
- Config precedence: CLI > ENV > YAML

### Requirement 3: Streaming and Partial Usage
**Objective:** As an operator, I want streaming usage normalized at completion, so that streaming requests are accounted for accurately.

**Priority:** P1 (High)

#### Acceptance Criteria
- 3.1 When a streaming response completes successfully, the Usage Accounting Service shall emit a final canonical usage record for that request with completion outcome set to complete.
- 3.2 While a streaming response is in progress, the Usage Accounting Service shall not emit a final canonical usage record.
- 3.3 If a streaming response terminates early or errors, the Usage Accounting Service shall emit a canonical usage record marked with completion outcome set to incomplete.
- 3.4 If completion outcome is incomplete, the Usage Accounting Service shall set incomplete reason to one of: client_disconnect, backend_error, timeout, upstream_cancelled, unknown.
- 3.5 When a streaming response ends after a client disconnect is detected, the Usage Accounting Service shall set incomplete reason to client_disconnect.
- 3.6 When a streaming response ends after an explicit cancellation callback without an error classification, the Usage Accounting Service shall set incomplete reason to upstream_cancelled.
- 3.7 When a streaming response ends with an APITimeoutError classification, the Usage Accounting Service shall set incomplete reason to timeout.
- 3.8 When a streaming response ends with a BackendError or APIConnectionError classification, the Usage Accounting Service shall set incomplete reason to backend_error.
- 3.9 If no incomplete reason can be determined from available context, the Usage Accounting Service shall set incomplete reason to unknown.

#### Technical Constraints
- Async compatibility: Must use `async/await` patterns
- Error hierarchy: Exceptions extend `LLMProxyError`
- Wire capture compatibility: Usage records must be compatible with capture serialization

### Requirement 4: Error Handling and Fallbacks
**Objective:** As a platform owner, I want normalization failures to be safe and visible, so that usage issues do not break responses.

**Priority:** P0 (Critical)

#### Acceptance Criteria
- 4.1 If usage data is missing from a backend response, the Usage Accounting Service shall record usage fields as unavailable and continue processing the response.
- 4.2 If usage data is malformed or inconsistent, the Usage Accounting Service shall log a structured warning with request identifier, backend type, model, protocol, and error classification and continue processing the response.
- 4.3 When cost data is unavailable or invalid, the Usage Accounting Service shall mark cost as unavailable and continue processing.

#### Technical Constraints
- Error hierarchy: Exceptions extend `LLMProxyError`
- Logging: Structured logs via structlog
- Config precedence: CLI > ENV > YAML

### Requirement 5: Downstream Exposure and Compatibility
**Objective:** As a client developer, I want usage surfaced consistently without breaking existing APIs, so that integrations remain stable.

**Priority:** P1 (High)

#### Acceptance Criteria
- 5.1 The Usage Accounting Service shall expose the canonical usage record to downstream services (logging, wire capture, response adapters) for every completed request.
- 5.2 When responding to client protocols that include usage fields, the Usage Accounting Service shall populate those fields from the canonical usage record.
- 5.3 The system shall preserve existing public response shapes and usage semantics for all supported protocols.
- 5.4 When canonical usage fields are unavailable, the system shall not overwrite existing protocol-native usage values with zeroes.
- 5.5 When response headers include usage metrics, the system shall derive header values from the canonical usage record.
- 5.6 When wire capture is enabled, the system shall include the canonical usage record under a capture-only metadata key named canonical_usage and shall not add canonical_usage to client response payloads.

#### Technical Constraints
- Async compatibility: Must use `async/await` patterns
- DI integration: Services registered via `ServiceCollection`
- Wire capture compatibility: Usage records must be compatible with capture serialization

## Non-Functional Requirements

### NFR 1: Performance
- The Usage Accounting Service shall add no more than 10 ms p95 overhead to non-streaming responses, excluding backend latency.
- The Usage Accounting Service shall add no more than 20 ms p95 overhead after stream completion to emit final usage.
- The system shall not perform additional network calls solely for usage normalization.

### NFR 2: Reliability
- The Usage Accounting Service shall continue response processing when normalization fails, and shall record the failure as a warning event.
- The system shall produce a canonical usage record for at least 99.9% of completed requests that include usage inputs.
- The system shall not drop responses solely due to missing or malformed usage data.

### NFR 3: Observability
- When wire capture is enabled, the system shall include the canonical usage record in capture metadata under canonical_usage.
- When wire capture is enabled and provider extensions are available, the system shall include those extensions alongside the canonical usage record in capture metadata.
- The system shall emit structured warning logs for normalization failures with request and backend identifiers.
- The system shall expose normalized usage metrics to existing logging and metrics pipelines without format changes.

### NFR 4: Security
- The system shall not log raw API keys in usage records or normalization warnings.
- The system shall not persist raw prompt or completion content in the canonical usage record.
- The system shall validate usage inputs to prevent injection of untrusted fields into canonical usage data.

## Glossary
| Term | Definition |
|------|------------|
| Canonical Usage Record | Normalized set of usage metrics for a request, including token counts, cost, completion outcome, and an extensions container when available. |
| Usage Normalization | Process of mapping provider-specific usage data into the canonical usage record. |
| Provider Extensions | Provider-specific usage metrics preserved alongside the canonical usage record. |
| Unavailable Value | A usage field that cannot be derived from inputs and is represented as null in the canonical usage record. |
| Incomplete Outcome | Indicator that a streaming request ended before normal completion, recorded with a completion outcome and reason. |
| Protocol | Normalized identifier for the frontend API surface: openai, openai-responses, anthropic, gemini. |
| RequestContext | Transport-agnostic context carrying request_id, session_id, and processing metadata for normalization. |
