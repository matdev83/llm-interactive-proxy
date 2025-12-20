# Requirements Document

## Introduction
This document defines the requirements for refactoring the Backend Request Manager Service to reduce file size and improve modularity while preserving existing behavior and public contracts.

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Developers integrating LLM capabilities via unified API
- Operators managing backend configurations and monitoring
- End-users consuming LLM responses through client applications

## Requirements

### Requirement 1: Public Contract Stability
**Objective:** As an integrator, I want the backend request manager contract to remain stable, so that existing integrations continue to work without changes

**Priority:** P0 (Critical)

#### Acceptance Criteria
1. The Backend Request Manager Service shall implement the `IBackendRequestManager` contract used for DI registration.
2. When `process_backend_request` is invoked and the deduplication service reports a duplicate, the Backend Request Manager Service shall raise `DuplicateRequestError` containing the session identifier and content hash.
3. When a backend response is returned for a streaming request, the Backend Request Manager Service shall return a `StreamingResponseEnvelope` to the caller.
4. If no content is produced after the configured empty-stream retry limit, then the Backend Request Manager Service shall raise a `BackendError` with the retry reason and session identifier.
5. The Backend Request Manager Service shall preserve the existing public request and response types at its call boundaries (`ChatRequest`, `ResponseEnvelope`, `StreamingResponseEnvelope`).

#### Technical Constraints
- Async compatibility: must use `async/await` for I/O.
- DI integration: keep compatibility with existing interface registrations.
- Error hierarchy: exceptions raised from this service shall extend `LLMProxyError`.

### Requirement 2: Request Preparation and History Compaction
**Objective:** As a request pipeline maintainer, I want command results and history compaction applied consistently, so that backends receive correct, up-to-date messages

**Priority:** P0 (Critical)

#### Acceptance Criteria
1. When command results include modified messages with user content, the Backend Request Manager Service shall replace the request messages with normalized `ChatMessage` items derived from those modified messages.
2. If modified messages are present and all modified messages lack content, then the Backend Request Manager Service shall return `None` to skip backend execution.
3. When command results include extractable tool output messages, the Backend Request Manager Service shall append those messages to the backend request.
4. While history compaction is enabled and the token estimate meets or exceeds the configured threshold, the Backend Request Manager Service shall compact history and update the request messages with the compacted result.
5. If history compaction raises an exception, then the Backend Request Manager Service shall log a warning with exception details and continue with the original messages.
6. When request messages are modified, the Backend Request Manager Service shall create a new `ChatRequest` without mutating the original request instance.

#### Technical Constraints
- Optional collaborators (history compaction service, config) must be handled safely when absent.
- Request preparation must remain asynchronous and non-blocking.

### Requirement 3: Non-Streaming Response Processing and Retry
**Objective:** As an operator, I want non-streaming responses validated and retried safely, so that empty responses and unsafe tool-call loops are handled consistently

**Priority:** P0 (Critical)

#### Acceptance Criteria
1. When a non-streaming backend response contains content, the Backend Request Manager Service shall process it through the response processor before returning it.
2. If the response processor raises `EmptyResponseRetryError`, then the Backend Request Manager Service shall create a retry request with the recovery prompt appended and submit it once to the backend processor.
3. When processing context includes a response schema, the Backend Request Manager Service shall apply structured output validation middleware and surface validation failures.
4. The Backend Request Manager Service shall filter non-streaming response metadata to include only JSON-serializable values and exclude the original request object.
5. When a response indicates a swallowed tool call and the request is not already marked as a tool-call retry, the Backend Request Manager Service shall initiate the tool-call retry flow with escalating steering and enforce the retry limit.
6. If the tool-call retry limit is exceeded, then the Backend Request Manager Service shall return a terminal response with termination metadata.
7. The Backend Request Manager Service shall include retry count metadata (`dangerous_command_retry_count`, `tool_call_reactor_retry_count`) in tool-call retry flows.

#### Technical Constraints
- Preserve existing metadata keys used by downstream processors and clients.
- Avoid additional backend calls beyond the defined retry limits.

### Requirement 4: Streaming Response Handling and Safety
**Objective:** As a streaming client, I want streaming responses processed safely, so that retries, loop detection, and steering are consistently applied

**Priority:** P0 (Critical)

#### Acceptance Criteria
1. When a streaming request is processed, the Backend Request Manager Service shall wrap the stream with response processor middleware before emitting chunks.
2. If the streaming response yields no meaningful output, then the Backend Request Manager Service shall retry with the recovery prompt and stop after the maximum configured retries.
3. When a swallowed tool call is detected during streaming, the Backend Request Manager Service shall initiate the tool-call retry flow and enforce the retry limit, returning a terminal error chunk on limit exceed.
4. While streaming, the Backend Request Manager Service shall run loop detection on emitted text and cancel the stream with a cancellation chunk when a loop is detected.
5. Where Angel verification is enabled for the session, the Backend Request Manager Service shall buffer the stream and replace it with a corrected response when the Angel service returns a steer decision; if verification fails or is disabled, the service shall pass through original chunks.
6. The Backend Request Manager Service shall attach session and request context metadata (`session_id`, `original_request`, `client_os` when available) to streaming chunks.

#### Technical Constraints
- Preserve streaming envelope properties (`media_type`, `headers`, `cancel_callback`).
- Streaming handling must remain fully async and non-blocking.

### Requirement 5: Modularity and Testability
**Objective:** As a maintainer, I want the backend request manager to be modular and testable, so that changes are easier to reason about and validate

**Priority:** P1 (High)

#### Acceptance Criteria
1. The Backend Request Manager Service shall separate request preparation, non-streaming response processing, streaming response processing, and retry management into distinct components with explicit interfaces.
2. When these components are exercised in isolation, the system shall allow mocked dependencies for backend processor, response processor, and optional collaborators.
3. The Backend Request Manager Service shall keep orchestration in a single entry point that delegates responsibilities to the components.
4. If optional collaborators (history compaction, deduplication, config) are not provided, then the Backend Request Manager Service shall still process requests without raising initialization errors.
5. When structured output validation, loop detection, or Angel verification is required, the Backend Request Manager Service shall delegate those responsibilities to dedicated components that can be injected and tested in isolation.

#### Technical Constraints
- Component boundaries must align with existing DI and interface patterns.
- Public behavior must remain unchanged after refactoring.

### Requirement 6: Metadata Contract Preservation
**Objective:** As a downstream processor, I want stable response metadata contracts, so that streaming accumulation, steering protection, and retry behavior remain consistent

**Priority:** P0 (Critical)

#### Acceptance Criteria
1. The Backend Request Manager Service shall preserve the presence and meaning of response metadata keys consumed by downstream components, including `tool_call_swallowed`, `_steering_replacement`, `dangerous_command_retry_count`, `tool_call_reactor_retry_count`, `session_id`, and `original_request` when applicable.
2. When returning a terminal response due to tool-call retry limits, the Backend Request Manager Service shall set metadata fields that indicate session termination and security limit enforcement.
3. When streaming responses include steering replacements, the Backend Request Manager Service shall emit `_steering_replacement` in chunk metadata to allow downstream accumulation reset.

#### Technical Constraints
- Metadata keys used by downstream components must remain backward compatible.

## Non-Functional Requirements

Note: NFR acceptance criteria use numeric IDs 7.1-10.2 for task traceability.

### NFR 1: Performance
- 7.1 The Backend Request Manager Service shall not introduce additional backend invocations beyond existing retry limits for empty responses and tool-call retries.
- 7.2 While streaming, the Backend Request Manager Service shall emit the first available backend chunk without additional buffering unless Angel verification is enabled.

### NFR 2: Reliability
- 8.1 The Backend Request Manager Service shall preserve fail-open behavior for optional features (history compaction, Angel verification) so primary request processing continues when they fail.
- 8.2 If streaming middleware raises an exception, then the Backend Request Manager Service shall log a warning with exception details and continue with the original response path where possible.

### NFR 3: Observability
- 9.1 The Backend Request Manager Service shall log warnings or errors with exception context for retry failures, compaction failures, and streaming middleware failures.
- 9.2 The Backend Request Manager Service shall include session identifiers in retry and termination metadata for downstream diagnostics.

### NFR 4: Security
- 10.1 The Backend Request Manager Service shall enforce the dangerous tool-call retry limit and return a terminal response when exceeded.
- 10.2 The Backend Request Manager Service shall exclude non-JSON-serializable objects from response metadata to prevent unsafe serialization.

## Glossary
| Term | Definition |
|------|------------|
| Backend Request Manager Service | Service responsible for preparing backend requests and handling backend responses, including retries and streaming. |
| Tool-call swallow | A backend response state indicating a tool call was blocked and must be retried with steering context. |
| Empty response retry | The recovery flow that retries a request when the backend returns no meaningful content. |
| Angel verification | A secondary verification flow that can steer or replace a streaming response based on policy checks. |
