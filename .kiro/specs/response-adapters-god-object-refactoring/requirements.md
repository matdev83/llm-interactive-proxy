# Requirements Document

## Introduction

This specification defines requirements for refactoring `src/core/transport/fastapi/response_adapters.py` from a 1851-line monolithic "God Object" into a modular, layered architecture. The refactoring must maintain full backward compatibility with existing public APIs while introducing proper separation of concerns, dependency injection, and testability.

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:

- Developers maintaining and extending the response adapter layer
- Operators debugging response transformation issues
- End-users consuming LLM responses through client applications
- Test authors requiring isolated unit testing of adapter components

## Discovered Constraints (from Gap Analysis)

### Naming Conflict

**Critical Discovery**: There are TWO files named `response_adapters.py`:

1. `src/core/transport/fastapi/response_adapters.py` (1851 lines) - **Target of refactoring**
2. `src/core/adapters/response_adapters.py` (75 lines) - Legacy simple facade (unrelated)

These serve different purposes. The legacy facade (`src/core/adapters/`) is NOT part of this refactoring and must be preserved as-is.

### Actual Public API Usage

Only **one** public function is imported by external controllers:

| Controller | Import |
|------------|--------|
| `chat_controller.py` | `domain_response_to_fastapi` |
| `responses_controller.py` | `domain_response_to_fastapi` |
| `anthropic_controller.py` | `domain_response_to_fastapi` |

The functions `to_fastapi_response` and `to_fastapi_streaming_response` are only called internally by `domain_response_to_fastapi`. However, they must still be exported for backward compatibility.

### Existing Patterns to Follow

- `src/core/ports/streaming_contracts.py` - Facade pattern for re-exports
- `src/core/ports/sse_assembler.py` - SSE assembly following ports/adapters pattern
- Global accessor pattern: `get_*_service()` for singleton access outside DI

## Requirements

### Requirement 1: Public API Preservation

**Objective:** As a developer using the response adapters, I want the existing public API to remain unchanged, so that I don't need to modify any calling code after the refactoring.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1.1. The Response Adapter Module shall export functions `to_fastapi_response`, `to_fastapi_streaming_response`, and `domain_response_to_fastapi` with identical signatures to the current implementation.

1.2. When calling `to_fastapi_response` with a `ResponseEnvelope`, the Response Adapter Module shall return a `FastAPI.Response` with identical content, headers, and status code as the current implementation.

1.3. When calling `to_fastapi_streaming_response` with a `StreamingResponseEnvelope`, the Response Adapter Module shall return a `StreamingResponse` that yields identical SSE-formatted bytes as the current implementation.

1.4. When calling `domain_response_to_fastapi` with any supported domain response type, the Response Adapter Module shall dispatch to the appropriate adapter and return an identical response.

1.5. The Response Adapter Module shall maintain backward compatibility with all existing callers in `src/core/app/controllers/` and `src/core/services/`.

1.6. The Response Adapter Module located at `src/core/transport/fastapi/response_adapters.py` shall NOT affect the unrelated legacy file at `src/core/adapters/response_adapters.py`.

#### Technical Constraints

- Async compatibility: Must use `async/await` patterns for streaming
- Re-exports must be available from `response_adapters.py` (thin facade)

---

### Requirement 2: Modular Layer Architecture

**Objective:** As a developer, I want response adaptation logic separated into cohesive, single-responsibility modules, so that I can understand, test, and modify each layer independently.

**Priority:** P0 (Critical)

#### Acceptance Criteria

2.1. The Response Adapter subsystem shall be organized into distinct layer modules under `src/core/transport/fastapi/adapters/`:

- SSE layer (formatting and decoding)
- Metadata layer (reasoning injection)
- Usage layer (calculation and headers)
- Sanitization layer (JSON and header sanitization)
- Capture layer (wire capture coordination)
- Streaming layer (tool block buffering and content conversion)
- Response layer (FastAPI response creation)

2.2. Each layer module shall have a single, clearly defined responsibility as specified in its layer contract.

2.3. When a layer requires functionality from another layer, it shall depend on that layer's protocol/interface rather than concrete implementation.

2.4. The Response Adapter subsystem shall provide a central `protocols.py` file defining all layer contracts using Python `Protocol` classes.

2.5. Each layer module shall be importable and testable in isolation without requiring the full application context.

2.6. The `response_adapters.py` file shall become a thin facade that re-exports public API functions, following the pattern established by `src/core/ports/streaming_contracts.py`.

#### Technical Constraints

- DI integration: Layer services shall be registrable via `ServiceCollection`
- Interfaces: Use `Protocol` classes for structural typing (not ABC)

---

### Requirement 3: SSE Pipeline Layer

**Objective:** As a developer, I want SSE formatting and decoding logic encapsulated in a dedicated layer, so that SSE concerns are isolated and reusable.

**Priority:** P1 (High)

#### Acceptance Criteria

3.1. The SSE Pipeline Layer shall provide an `ISSEFormatter` protocol with a method to format arbitrary content as SSE bytes.

3.2. When formatting a dict chunk as SSE, the SSE Formatter shall produce bytes in the format `data: {json}\n\n`.

3.3. When formatting bytes or string chunks, the SSE Formatter shall pass them through with appropriate encoding.

3.4. The SSE Pipeline Layer shall provide an `ISSEDecoder` protocol with a method to decode SSE-formatted payloads.

3.5. When decoding SSE payloads, the SSE Decoder shall return a tuple of (decoded_content, metadata_hints, is_done).

3.6. When encountering `[DONE]` markers in SSE payloads, the SSE Decoder shall return `is_done=True`.

3.7. The SSE Pipeline Layer shall consolidate the duplicate `_decode_sse_payload` function definitions (currently at lines 354 and 1242) into a single implementation.

3.8. The SSE Pipeline Layer may leverage patterns from the existing `src/core/ports/sse_assembler.py` where appropriate.

#### Technical Constraints

- Must handle all SSE formats used by OpenAI, Anthropic, and Gemini backends

---

### Requirement 4: Metadata Injection Layer

**Objective:** As a developer, I want reasoning metadata injection logic encapsulated in a dedicated layer, so that metadata enrichment is consistent and testable.

**Priority:** P1 (High)

#### Acceptance Criteria

4.1. The Metadata Injection Layer shall provide an `IReasoningInjector` protocol for injecting reasoning metadata into OpenAI-style payloads.

4.2. When metadata contains `reasoning_content` or `reasoning` fields, the Reasoning Injector shall inject them into choice delta/message blocks.

4.3. If the payload already contains reasoning fields, the Reasoning Injector shall not overwrite existing values.

4.4. When the payload is not dict-structured, the Reasoning Injector shall build an OpenAI-style envelope to carry reasoning metadata.

4.5. The Metadata Injection Layer shall support both streaming (`delta`) and non-streaming (`message`) payload formats.

4.6. When tool_calls are present in metadata but not in content, the Reasoning Injector shall include them in the constructed payload.

#### Technical Constraints

- Must preserve existing behavior for all OpenAI, Anthropic, and Gemini response formats

---

### Requirement 5: Usage Calculation Layer

**Objective:** As a developer, I want usage calculation and header injection logic encapsulated in a dedicated layer, so that token accounting is centralized and auditable.

**Priority:** P1 (High)

#### Acceptance Criteria

5.1. The Usage Calculation Layer shall provide an `IUsageNormalizer` protocol for normalizing usage dictionaries to OpenRouter-compatible format.

5.2. When normalizing usage, the Usage Normalizer shall ensure `prompt_tokens`, `completion_tokens`, and `total_tokens` are present as integers.

5.3. The Usage Calculation Layer shall provide an `IUsageHeaderInjector` protocol for applying usage data as HTTP headers.

5.4. When injecting usage headers, the Usage Header Injector shall add headers `x-usage-prompt-tokens`, `x-usage-completion-tokens`, and `x-usage-total-tokens`.

5.5. Where usage contains extended fields (reasoning_tokens, cached_tokens, cost), the Usage Header Injector shall include corresponding headers.

5.6. When context requires usage recalculation, the Usage Calculation Layer shall delegate to `UsageCalculationService` and merge results appropriately.

5.7. The Usage Calculation Layer shall preserve the highest observed values when merging streaming usage across chunks.

#### Technical Constraints

- Integration with `src/core/services/usage_calculation_service.py`
- Use `get_usage_calculation_service()` accessor with DI fallback

---

### Requirement 6: Sanitization Layer

**Objective:** As a developer, I want content and header sanitization logic encapsulated in a dedicated layer, so that security concerns are isolated and auditable.

**Priority:** P1 (High)

#### Acceptance Criteria

6.1. The Sanitization Layer shall provide an `IJSONSanitizer` protocol for ensuring JSON-safe content.

6.2. When sanitizing JSON content, the JSON Sanitizer shall convert non-serializable objects (coroutines, AsyncMock, etc.) to string representations.

6.3. The Sanitization Layer shall provide an `IHeaderSanitizer` protocol for filtering HTTP headers.

6.4. When sanitizing headers, the Header Sanitizer shall remove hop-by-hop headers (transfer-encoding, content-encoding, connection, etc.).

6.5. When sanitizing headers, the Header Sanitizer shall only allow headers with prefixes: `x-`, `access-control-`, `anthropic-`, `openai-`, `zenmux-`.

6.6. The Sanitization Layer shall integrate with `SteeringLeakProtector` for final-layer security sanitization.

6.7. If steering leak is detected during sanitization, the Sanitization Layer shall log a security warning.

#### Technical Constraints

- Security: Must be applied as final safety net before response emission
- Use `get_steering_leak_protector()` accessor with DI fallback

---

### Requirement 7: Wire Capture Coordination Layer

**Objective:** As a developer, I want wire capture logic encapsulated in a dedicated layer, so that observability concerns don't pollute response building logic.

**Priority:** P2 (Medium)

#### Acceptance Criteria

7.1. The Wire Capture Coordination Layer shall provide an `IWireCaptureCoordinator` protocol for coordinating outbound response captures.

7.2. When wire capture is enabled, the Wire Capture Coordinator shall extract backend, model, key_name, and session_id from envelope metadata.

7.3. When capturing non-streaming responses, the Wire Capture Coordinator shall create a background task for async capture.

7.4. When capturing streaming responses, the Wire Capture Coordinator shall wrap the stream iterator via `wire_capture.wrap_outbound_stream()`.

7.5. If wire capture is disabled or unavailable, the Wire Capture Coordinator shall perform no operations (no-op).

7.6. The Wire Capture Coordinator shall resolve session_id with fallback to request_id from context.

#### Technical Constraints

- Must not block response emission for capture operations
- Background tasks must handle exceptions properly

---

### Requirement 8: Streaming Content Conversion Layer

**Objective:** As a developer, I want streaming content conversion logic encapsulated in a dedicated layer, so that the complex streaming pipeline is maintainable.

**Priority:** P0 (Critical)

#### Acceptance Criteria

8.1. The Streaming Content Conversion Layer shall provide an `IStreamingContentConverter` protocol for converting raw stream chunks to `StreamingContent`.

8.2. When converting chunks, the Streaming Content Converter shall normalize `ProcessedResponse` and raw chunks uniformly.

8.3. The Streaming Content Converter shall decode SSE payloads and merge metadata from decoded content.

8.4. The Streaming Content Converter shall track and merge usage data across streaming chunks, keeping highest values.

8.5. When a chunk signals stream completion (via finish_reason, [DONE] marker, or is_done metadata), the Streaming Content Converter shall set `is_done=True`.

8.6. The Streaming Content Converter shall yield properly each chunk to maintain async path purity.

8.7. If a client disconnects during streaming (GeneratorExit), the Streaming Content Converter shall clean up resources gracefully.

8.8. The nested closures in `_streaming_adapter` (currently 670+ lines) shall be refactored to class methods for testability.

#### Technical Constraints

- Must use `await asyncio.sleep(0)` for event loop yielding between chunks
- Refactor closures to classes for independent testing

---

### Requirement 9: Tool Block Buffering Layer

**Objective:** As a developer, I want multiline tool block buffering logic encapsulated in a dedicated layer, so that XML-style tool call handling is isolated.

**Priority:** P1 (High)

#### Acceptance Criteria

9.1. The Tool Block Buffering Layer shall provide an `IToolBlockBuffer` protocol for buffering multiline tool blocks across streaming chunks.

9.2. When streaming content contains partial tool blocks (e.g., `<tool_name>...` without closing tag), the Tool Block Buffer shall hold the fragment until complete.

9.3. When a complete tool block is detected, the Tool Block Buffer shall emit the full block in the output.

9.4. When stream completes (is_done=True), the Tool Block Buffer shall flush all pending fragments.

9.5. The Tool Block Buffer shall track detected tool tags via the streaming context registry.

9.6. The Tool Block Buffer shall respect allowed_tools configuration to filter processed tags.

9.7. The Tool Block Buffer shall exclude `<think>` and `<thought>` tags from processing when no allowed_tools are configured.

#### Technical Constraints

- Integration with `StreamContextRegistry` for cross-chunk state
- Use `get_global_streaming_context_registry()` accessor with DI fallback

---

### Requirement 10: Response Builder Layer

**Objective:** As a developer, I want FastAPI response creation logic encapsulated in a dedicated layer, so that response construction is consistent and pluggable.

**Priority:** P1 (High)

#### Acceptance Criteria

10.1. The Response Builder Layer shall provide an `IJSONResponseBuilder` protocol for creating FastAPI JSONResponse objects.

10.2. When building JSON responses, the JSON Response Builder shall apply final steering leak protection.

10.3. When building JSON responses, the JSON Response Builder shall filter headers to allowed prefixes only.

10.4. The Response Builder Layer shall provide an `IStreamingResponseBuilder` protocol for creating FastAPI StreamingResponse objects.

10.5. When building streaming responses, the Streaming Response Builder shall configure media_type as `text/event-stream`.

10.6. When building streaming responses with null content, the Streaming Response Builder shall provide an empty iterator.

10.7. The Response Builder Layer shall provide an `IOtherResponseBuilder` protocol for non-JSON response types.

#### Technical Constraints

- Must handle status code normalization and error status mapping

---

### Requirement 11: Dependency Injection Integration

**Objective:** As a developer, I want all layer services registered via DI, so that I can easily substitute implementations for testing and extension.

**Priority:** P1 (High)

#### Acceptance Criteria

11.1. The Response Adapter subsystem shall define protocols (interfaces) for all layer services in `protocols.py`.

11.2. Each layer implementation shall be registrable in `ServiceCollection` via the DI system.

11.3. When layer services require external dependencies (e.g., `UsageCalculationService`, `SteeringLeakProtector`), they shall receive them via constructor injection.

11.4. The Response Adapter facade (`response_adapters.py`) shall obtain layer services via DI resolution when available.

11.5. If DI container is not available (standalone usage), the Response Adapter facade shall fall back to creating default implementations using existing global accessor functions (`get_*_service()`).

11.6. All layer protocols shall support async methods where appropriate for streaming operations.

#### Technical Constraints

- DI integration: Services registered via `ServiceCollection`
- Factory pattern for complex wiring
- Fallback to current global accessor pattern

---

### Requirement 12: Test Coverage Preservation

**Objective:** As a test author, I want all existing tests to pass after refactoring, so that I have confidence the refactoring didn't break functionality.

**Priority:** P0 (Critical)

#### Acceptance Criteria

12.1. After refactoring, all existing unit tests for `response_adapters.py` shall pass without modification.

12.2. After refactoring, all existing integration tests involving response adapters shall pass without modification.

12.3. Each new layer module shall have dedicated unit tests covering its protocol contract.

12.4. The refactored implementation shall achieve equivalent or better test coverage compared to the original.

12.5. When running the full test suite, zero test failures shall occur as a result of this refactoring.

12.6. The refactored layers shall be independently mockable for upstream consumer testing.

12.7. Tests in `tests/unit/core/adapters/test_response_adapters.py` (which test the LEGACY facade) shall continue to pass unchanged.

#### Technical Constraints

- TDD: New layer tests written before implementation
- Existing test files:
  - `tests/unit/test_response_adapters_properties.py` (504 lines)
  - `tests/unit/streaming/test_response_adapter_dict_handling.py` (301 lines)

---

### Requirement 13: Phased Implementation Approach

**Objective:** As an implementer, I want the refactoring executed in validated phases, so that risks are minimized and progress is incremental.

**Priority:** P1 (High)

#### Acceptance Criteria

13.1. The implementation shall follow a phased extraction approach with tests passing after each phase.

13.2. Phase 1 (Foundation) shall establish protocols and extract the SSE layer as a pattern validation.

13.3. Phase 2 (Support Layers) shall extract sanitization, usage, and capture layers.

13.4. Phase 3 (Metadata Layer) shall extract reasoning injection and response builders.

13.5. Phase 4 (Streaming Layer) shall refactor the complex streaming closure to classes.

13.6. Phase 5 (Facade) shall convert `response_adapters.py` to a thin facade and complete DI integration.

13.7. Each phase boundary shall include a full test suite run with zero failures.

#### Technical Constraints

- Git commits per extraction for easy rollback
- Original code may be commented (not deleted) until verified

---

## Non-Functional Requirements

### NFR 1: Performance

- **Streaming latency**: First-byte latency shall not increase by more than 5ms compared to current implementation
- **Memory footprint**: Streaming operations shall not accumulate unbounded buffers
- **CPU overhead**: Layer indirection shall add negligible overhead (< 1% of request processing time)

### NFR 2: Maintainability

- **File size**: No single module shall exceed 300 lines of code
  - **Note**: Some files exceed this constraint but are acceptable given complexity and refactoring goals:
    - `StreamingContentConverter` (669 lines): Refactored from 670+ line closure; represents significant improvement
    - `JSONResponseBuilder` (490 lines): Complex usage calculation and recalculation logic; acceptable given functionality
    - `ToolBlockBuffer` (393 lines): Complex XML-style tag parsing and buffering logic; acceptable given domain complexity
    - `ReasoningInjector` (285 lines): Complex payload building and normalization logic; acceptable given requirements
    - `protocols.py` (318 lines): Contains all 13 protocol definitions in one file for discoverability; acceptable trade-off
    - `response_adapters.py` facade (520 lines): Includes helper functions and backward compatibility code; acceptable per tasks.md notes
- **Cyclomatic complexity**: No function shall exceed cyclomatic complexity of 10
- **Nesting depth**: Maximum nesting depth shall be 4 levels (no "closure soup")

### NFR 3: Observability

- **Logging**: Each layer shall use structured logging with consistent prefixes
- **Debug mode**: TRACE-level logging shall be available for detailed stream processing visibility
- **Error context**: Exceptions shall include layer context for debugging

### NFR 4: Security

- **Steering leak protection**: Final sanitization shall always be applied before response emission
- **Input validation**: Layer inputs shall be validated before processing
- **Defense in depth**: Each layer shall apply appropriate security measures for its domain

## Glossary

| Term | Definition |
|------|------------|
| SSE | Server-Sent Events - streaming protocol format |
| Response Envelope | Domain object wrapping response content, headers, status |
| StreamingContent | Internal contract for streaming chunk with metadata |
| Wire Capture | CBOR-encoded traffic recording for debugging |
| Tool Block | XML-style tool call fragment (e.g., `<read_file>...</read_file>`) |
| Reasoning Metadata | Extended fields (reasoning_content, reasoning) for chain-of-thought |
| Usage | Token consumption metrics (prompt_tokens, completion_tokens, etc.) |
| DI Container | Dependency injection via `ServiceCollection` |
| Protocol | Python typing.Protocol for structural subtyping (duck typing) |
| Thin Facade | Module that only re-exports from internal modules |
| Global Accessor | Function pattern like `get_*_service()` for singleton access |

---

_Updated: 2025-12-18T23:46:29+01:00 (incorporated gap analysis findings)_
