# Implementation Tasks: Response Adapters God Object Refactoring

## Summary

This document breaks down the refactoring of `src/core/transport/fastapi/response_adapters.py` into actionable implementation tasks organized by phase. Each task includes acceptance criteria, dependencies, and test requirements.

**Total Effort**: L (1-2 weeks)
**Total Tasks**: 32
**Phases**: 5

---

## Task Dependency Graph

```
Phase 1 (Foundation)
├── Task 1.1: Create package structure
├── Task 1.2: Define protocols ← 1.1
├── Task 1.3: Implement SSEFormatter ← 1.2
├── Task 1.4: Implement SSEDecoder ← 1.2
└── Task 1.5: Phase 1 validation gate ← 1.3, 1.4

Phase 2 (Support Layers) ← Phase 1
├── Task 2.1: Implement HeaderSanitizer ← 1.2
├── Task 2.2: Implement JSONSanitizer ← 1.2
├── Task 2.3: Implement UsageNormalizer ← 1.2
├── Task 2.4: Implement UsageHeaderInjector ← 2.3
├── Task 2.5: Implement WireCaptureCoordinator ← 1.2
└── Task 2.6: Phase 2 validation gate ← 2.1-2.5

Phase 3 (Metadata & Response) ← Phase 2
├── Task 3.1: Implement ReasoningInjector ← 1.2
├── Task 3.2: Implement JSONResponseBuilder ← 2.1, 2.2, 2.4
├── Task 3.3: Implement StreamingResponseBuilder ← 1.3
├── Task 3.4: Implement OtherResponseBuilder ← 2.1
└── Task 3.5: Phase 3 validation gate ← 3.1-3.4

Phase 4 (Streaming Layer) ← Phase 3
├── Task 4.1: Implement ToolBlockBuffer ← 1.2
├── Task 4.2: Implement StreamingContentConverter ← 1.4, 3.1, 2.3, 4.1
└── Task 4.3: Phase 4 validation gate ← 4.1, 4.2

Phase 5 (Facade & Cleanup) ← Phase 4
├── Task 5.1: Create thin facade ← 3.2, 3.3, 4.2
├── Task 5.2: Wire integration ← 5.1
├── Task 5.3: Remove extracted code ← 5.2
├── Task 5.4: Final validation gate ← 5.3
└── Task 5.5: Documentation update ← 5.4
```

---

## Phase 1: Foundation (Days 1-3)

### Task 1.1: Create Package Structure

**ID**: `1.1`
**Requirements**: 2.1
**Priority**: P0
**Effort**: S (< 1 hour)

**Description**: Create the `adapters/` package directory structure with all necessary `__init__.py` files.

**Acceptance Criteria**:

- [ ] Directory `src/core/transport/fastapi/adapters/` created
- [ ] `__init__.py` files in: `adapters/`, `sse/`, `metadata/`, `usage/`, `sanitization/`, `capture/`, `streaming/`, `response/`
- [ ] All `__init__.py` files have proper docstrings
- [ ] Package is importable: `from src.core.transport.fastapi.adapters import *`

**Files to Create**:

```
src/core/transport/fastapi/adapters/
├── __init__.py
├── sse/
│   └── __init__.py
├── metadata/
│   └── __init__.py
├── usage/
│   └── __init__.py
├── sanitization/
│   └── __init__.py
├── capture/
│   └── __init__.py
├── streaming/
│   └── __init__.py
└── response/
    └── __init__.py
```

**Dependencies**: None

**Test Requirements**: Import verification only

---

### Task 1.2: Define All Protocols

**ID**: `1.2`
**Requirements**: 2.4, 11.1
**Priority**: P0
**Effort**: M (2-4 hours)

**Description**: Create `protocols.py` with all 13 protocol definitions using Python `Protocol` classes.

**Acceptance Criteria**:

- [ ] File `src/core/transport/fastapi/adapters/protocols.py` created
- [ ] All 13 protocols defined with typed signatures:
  - `ISSEFormatter`, `ISSEDecoder`
  - `IReasoningInjector`
  - `IUsageNormalizer`, `IUsageHeaderInjector`
  - `IJSONSanitizer`, `IHeaderSanitizer`
  - `IWireCaptureCoordinator`
  - `IToolBlockBuffer`, `IStreamingContentConverter`
  - `IJSONResponseBuilder`, `IStreamingResponseBuilder`, `IOtherResponseBuilder`
- [ ] Each protocol has docstrings and type hints
- [ ] Protocols are runtime-checkable where beneficial
- [ ] File is < 200 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/protocols.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/test_protocols.py`

**Dependencies**: Task 1.1

**Test Requirements**:

- [ ] Test that each protocol can be used as a type hint
- [ ] Test that implementations satisfy protocol contracts

---

### Task 1.3: Implement SSEFormatter

**ID**: `1.3`
**Requirements**: 3.1, 3.2, 3.3
**Priority**: P0
**Effort**: S (1-2 hours)

**Description**: Extract SSE formatting logic into `SSEFormatter` class implementing `ISSEFormatter`.

**Acceptance Criteria**:

- [ ] File `src/core/transport/fastapi/adapters/sse/formatter.py` created
- [ ] Class `SSEFormatter` implements `ISSEFormatter`
- [ ] `format_chunk(content: dict | bytes | str) -> bytes` method works correctly:
  - Dict → `data: {json}\n\n`
  - Bytes → passed through
  - String → encoded to bytes
- [ ] No dependencies on external services
- [ ] File is < 100 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/sse/formatter.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/sse/test_sse_formatter.py`

**Dependencies**: Task 1.2

**Test Requirements** (TDD):

- [ ] Test dict formatting produces correct SSE format
- [ ] Test bytes pass-through
- [ ] Test string encoding
- [ ] Test empty content handling
- [ ] Test special characters in JSON
- [ ] Property test: format is always valid SSE

---

### Task 1.4: Implement SSEDecoder

**ID**: `1.4`
**Requirements**: 3.4, 3.5, 3.6, 3.7, 3.8
**Priority**: P0
**Effort**: M (2-4 hours)

**Description**: Extract and consolidate SSE decoding logic into `SSEDecoder` class implementing `ISSEDecoder`.

**Acceptance Criteria**:

- [ ] File `src/core/transport/fastapi/adapters/sse/decoder.py` created
- [ ] Class `SSEDecoder` implements `ISSEDecoder`
- [ ] `decode_payload(payload: bytes | str) -> tuple[Any, dict, bool]` method:
  - Returns (decoded_content, metadata_hints, is_done)
  - Detects `[DONE]` markers correctly
  - Handles OpenAI, Anthropic, Gemini SSE formats
- [ ] Consolidates duplicate `_decode_sse_payload` from lines 354 and 1242
- [ ] No dependencies on external services
- [ ] File is < 150 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/sse/decoder.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/sse/test_sse_decoder.py`

**Dependencies**: Task 1.2

**Test Requirements** (TDD):

- [ ] Test OpenAI format decoding
- [ ] Test Anthropic format decoding
- [ ] Test Gemini format decoding
- [ ] Test `[DONE]` marker detection
- [ ] Test malformed SSE handling
- [ ] Test empty payload handling
- [ ] Test metadata extraction from decoded content

---

### Task 1.5: Phase 1 Validation Gate

**ID**: `1.5`
**Requirements**: 12.1, 12.5, 13.7
**Priority**: P0
**Effort**: S (< 1 hour)

**Description**: Run full test suite to verify Phase 1 changes don't break existing functionality.

**Acceptance Criteria**:

- [ ] All new unit tests pass
- [ ] All existing tests pass unchanged:
  - `tests/unit/test_response_adapters_properties.py`
  - `tests/unit/streaming/test_response_adapter_dict_handling.py`
  - `tests/unit/core/adapters/test_response_adapters.py`
- [ ] No regressions in integration tests
- [ ] Git commit created with Phase 1 changes

**Command**:

```bash
.venv\Scripts\python.exe -m pytest tests/unit/ -v
```

**Dependencies**: Tasks 1.3, 1.4

---

## Phase 2: Support Layers (Days 4-6)

### Task 2.1: Implement HeaderSanitizer

**ID**: `2.1`
**Requirements**: 6.3, 6.4, 6.5
**Priority**: P1
**Effort**: S (1-2 hours)

**Description**: Extract header sanitization logic into `HeaderSanitizer` class.

**Acceptance Criteria**:

- [ ] File `src/core/transport/fastapi/adapters/sanitization/header_sanitizer.py` created
- [ ] Class `HeaderSanitizer` implements `IHeaderSanitizer`
- [ ] `ALLOWED_PREFIXES` constant: `("x-", "access-control-", "anthropic-", "openai-", "zenmux-")`
- [ ] `HOP_BY_HOP_HEADERS` constant includes all RFC 2616 hop-by-hop headers
- [ ] `sanitize(headers: dict | None) -> dict` removes disallowed headers
- [ ] No dependencies on external services
- [ ] File is < 80 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/sanitization/header_sanitizer.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/sanitization/test_header_sanitizer.py`

**Dependencies**: Task 1.2

**Test Requirements** (TDD):

- [ ] Test hop-by-hop header removal
- [ ] Test allowed prefix filtering
- [ ] Test None input handling
- [ ] Test empty dict handling
- [ ] Test case insensitivity

---

### Task 2.2: Implement JSONSanitizer

**ID**: `2.2`
**Requirements**: 6.1, 6.2, 6.6, 6.7
**Priority**: P1
**Effort**: M (2-3 hours)

**Description**: Extract JSON sanitization logic into `JSONSanitizer` class with steering leak protection.

**Acceptance Criteria**:

- [ ] File `src/core/transport/fastapi/adapters/sanitization/json_sanitizer.py` created
- [ ] Class `JSONSanitizer` implements `IJSONSanitizer`
- [ ] Constructor accepts optional `SteeringLeakProtector` via DI
- [ ] Falls back to `get_steering_leak_protector()` if not provided
- [ ] `sanitize(content: Any) -> Any` converts non-serializable objects to strings
- [ ] Logs security warning on leak detection (without exposing content)
- [ ] File is < 120 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/sanitization/json_sanitizer.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/sanitization/test_json_sanitizer.py`

**Dependencies**: Task 1.2

**Test Requirements** (TDD):

- [ ] Test coroutine conversion to string
- [ ] Test AsyncMock conversion to string
- [ ] Test nested object sanitization
- [ ] Test steering leak detection logging
- [ ] Test DI injection works
- [ ] Test fallback to global accessor

---

### Task 2.3: Implement UsageNormalizer

**ID**: `2.3`
**Requirements**: 5.1, 5.2, 5.6, 5.7
**Priority**: P1
**Effort**: M (2-3 hours)

**Description**: Extract usage normalization logic into `UsageNormalizer` class.

**Acceptance Criteria**:

- [ ] File `src/core/transport/fastapi/adapters/usage/normalizer.py` created
- [ ] Class `UsageNormalizer` implements `IUsageNormalizer`
- [ ] Constructor accepts optional `UsageCalculationService` via DI
- [ ] Falls back to `get_usage_calculation_service()` if not provided
- [ ] `normalize(usage: dict | None) -> dict[str, int]` ensures standard fields
- [ ] `merge_streaming_usage(existing, new) -> dict` keeps highest values
- [ ] File is < 100 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/usage/normalizer.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/usage/test_usage_normalizer.py`

**Dependencies**: Task 1.2

**Test Requirements** (TDD):

- [ ] Test normalization adds missing fields with 0
- [ ] Test normalization converts to int
- [ ] Test merge keeps highest values
- [ ] Test None input handling
- [ ] Test delegation to UsageCalculationService
- [ ] Property test: merge is commutative for max

---

### Task 2.4: Implement UsageHeaderInjector

**ID**: `2.4`
**Requirements**: 5.3, 5.4, 5.5
**Priority**: P1
**Effort**: S (1-2 hours)

**Description**: Extract usage header injection logic into `UsageHeaderInjector` class.

**Acceptance Criteria**:

- [ ] File `src/core/transport/fastapi/adapters/usage/header_injector.py` created
- [ ] Class `UsageHeaderInjector` implements `IUsageHeaderInjector`
- [ ] `inject_headers(headers: dict, usage: dict) -> dict` adds:
  - `x-usage-prompt-tokens`
  - `x-usage-completion-tokens`
  - `x-usage-total-tokens`
  - Extended headers for reasoning_tokens, cached_tokens, cost (when present)
- [ ] No dependencies on external services
- [ ] File is < 60 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/usage/header_injector.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/usage/test_usage_header_injector.py`

**Dependencies**: Task 2.3

**Test Requirements** (TDD):

- [ ] Test basic token headers injected
- [ ] Test extended headers when present
- [ ] Test missing fields don't create headers
- [ ] Test existing headers preserved

---

### Task 2.5: Implement WireCaptureCoordinator

**ID**: `2.5`
**Requirements**: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6
**Priority**: P2
**Effort**: M (2-3 hours)

**Description**: Extract wire capture coordination logic into `WireCaptureCoordinator` class.

**Acceptance Criteria**:

- [ ] File `src/core/transport/fastapi/adapters/capture/wire_capture_coordinator.py` created
- [ ] Class `WireCaptureCoordinator` implements `IWireCaptureCoordinator`
- [ ] `schedule_capture(envelope, response_content) -> None` schedules background task
- [ ] `wrap_stream(envelope, stream) -> AsyncIterator[bytes]` wraps for capture
- [ ] Extracts backend, model, key_name, session_id from envelope metadata
- [ ] No-op when wire capture disabled
- [ ] File is < 100 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/capture/wire_capture_coordinator.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/capture/test_wire_capture_coordinator.py`

**Dependencies**: Task 1.2

**Test Requirements** (TDD):

- [ ] Test no-op when disabled
- [ ] Test metadata extraction
- [ ] Test background task scheduling
- [ ] Test stream wrapping
- [ ] Test session_id fallback to request_id

---

### Task 2.6: Phase 2 Validation Gate

**ID**: `2.6`
**Requirements**: 12.1, 12.5, 13.7
**Priority**: P0
**Effort**: S (< 1 hour)

**Description**: Run full test suite to verify Phase 2 changes don't break existing functionality.

**Acceptance Criteria**:

- [ ] All new unit tests pass (Tasks 2.1-2.5)
- [ ] All Phase 1 tests still pass
- [ ] All existing tests pass unchanged
- [ ] No regressions in integration tests
- [ ] Git commit created with Phase 2 changes

**Command**:

```bash
.venv\Scripts\python.exe -m pytest tests/unit/ -v
```

**Dependencies**: Tasks 2.1, 2.2, 2.3, 2.4, 2.5

---

## Phase 3: Metadata & Response (Days 7-8)

### Task 3.1: Implement ReasoningInjector

**ID**: `3.1`
**Requirements**: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6
**Priority**: P1
**Effort**: M (2-4 hours)

**Description**: Extract reasoning metadata injection logic into `ReasoningInjector` class.

**Acceptance Criteria**:

- [ ] File `src/core/transport/fastapi/adapters/metadata/reasoning_injector.py` created
- [ ] Class `ReasoningInjector` implements `IReasoningInjector`
- [ ] `inject_reasoning(content, metadata) -> Any`:
  - Injects `reasoning_content` and `reasoning` fields
  - Never overwrites existing values
  - Handles both `delta` and `message` formats
- [ ] `build_streaming_payload(content, metadata) -> dict`:
  - Builds OpenAI-style envelope for non-dict content
  - Includes tool_calls from metadata when missing
- [ ] No dependencies on external services
- [ ] File is < 150 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/metadata/reasoning_injector.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/metadata/test_reasoning_injector.py`

**Dependencies**: Task 1.2

**Test Requirements** (TDD):

- [ ] Test reasoning injection into delta
- [ ] Test reasoning injection into message
- [ ] Test no overwrite of existing values
- [ ] Test OpenAI envelope building
- [ ] Test tool_calls inclusion from metadata
- [ ] Test non-dict content handling

---

### Task 3.2: Implement JSONResponseBuilder

**ID**: `3.2`
**Requirements**: 10.1, 10.2, 10.3
**Priority**: P1
**Effort**: M (2-3 hours)

**Description**: Extract JSON response building logic into `JSONResponseBuilder` class.

**Acceptance Criteria**:

- [ ] File `src/core/transport/fastapi/adapters/response/json_response_builder.py` created
- [ ] Class `JSONResponseBuilder` implements `IJSONResponseBuilder`
- [ ] Constructor accepts `IJSONSanitizer`, `IHeaderSanitizer`, `IUsageHeaderInjector` via DI
- [ ] Creates default instances if not provided
- [ ] `build(envelope: ResponseEnvelope) -> JSONResponse`:
  - Applies content sanitization
  - Applies header sanitization
  - Injects usage headers
  - Returns FastAPI JSONResponse
- [ ] File is < 100 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/response/json_response_builder.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/response/test_json_response_builder.py`

**Dependencies**: Tasks 2.1, 2.2, 2.4

**Test Requirements** (TDD):

- [ ] Test response content matches envelope
- [ ] Test headers are sanitized
- [ ] Test usage headers are injected
- [ ] Test status code is set correctly
- [ ] Test DI injection works
- [ ] Test default instances created

---

### Task 3.3: Implement StreamingResponseBuilder

**ID**: `3.3`
**Requirements**: 10.4, 10.5, 10.6
**Priority**: P1
**Effort**: M (2-3 hours)

**Description**: Extract streaming response building logic into `StreamingResponseBuilder` class.

**Acceptance Criteria**:

- [ ] File `src/core/transport/fastapi/adapters/response/streaming_response_builder.py` created
- [ ] Class `StreamingResponseBuilder` implements `IStreamingResponseBuilder`
- [ ] Constructor accepts `ISSEFormatter` via DI
- [ ] Creates default instance if not provided
- [ ] `build(envelope: StreamingResponseEnvelope) -> StreamingResponse`:
  - Sets media_type to `text/event-stream`
  - Provides empty iterator for null content
  - Returns FastAPI StreamingResponse
- [ ] File is < 80 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/response/streaming_response_builder.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/response/test_streaming_response_builder.py`

**Dependencies**: Task 1.3

**Test Requirements** (TDD):

- [ ] Test media_type is text/event-stream
- [ ] Test null content produces empty iterator
- [ ] Test headers are passed through
- [ ] Test status code is set correctly

---

### Task 3.4: Implement OtherResponseBuilder

**ID**: `3.4`
**Requirements**: 10.7
**Priority**: P2
**Effort**: S (1-2 hours)

**Description**: Extract non-JSON response building logic into `OtherResponseBuilder` class.

**Acceptance Criteria**:

- [ ] File `src/core/transport/fastapi/adapters/response/other_response_builder.py` created
- [ ] Class `OtherResponseBuilder` implements `IOtherResponseBuilder`
- [ ] Constructor accepts `IHeaderSanitizer` via DI
- [ ] `build(envelope: ResponseEnvelope) -> Response`:
  - Handles non-JSON content types
  - Applies header sanitization
  - Returns generic FastAPI Response
- [ ] File is < 60 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/response/other_response_builder.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/response/test_other_response_builder.py`

**Dependencies**: Task 2.1

**Test Requirements** (TDD):

- [ ] Test non-JSON content handling
- [ ] Test header sanitization applied
- [ ] Test correct content-type preserved

---

### Task 3.5: Phase 3 Validation Gate

**ID**: `3.5`
**Requirements**: 12.1, 12.5, 13.7
**Priority**: P0
**Effort**: S (< 1 hour)

**Description**: Run full test suite to verify Phase 3 changes don't break existing functionality.

**Acceptance Criteria**:

- [ ] All new unit tests pass (Tasks 3.1-3.4)
- [ ] All Phase 1-2 tests still pass
- [ ] All existing tests pass unchanged
- [ ] No regressions in integration tests
- [ ] Git commit created with Phase 3 changes

**Command**:

```bash
.venv\Scripts\python.exe -m pytest tests/unit/ -v
```

**Dependencies**: Tasks 3.1, 3.2, 3.3, 3.4

---

## Phase 4: Streaming Layer (Days 9-11)

### Task 4.1: Implement ToolBlockBuffer

**ID**: `4.1`
**Requirements**: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7
**Priority**: P1
**Effort**: M (3-4 hours)

**Description**: Extract tool block buffering logic into `ToolBlockBuffer` class.

**Acceptance Criteria**:

- [ ] File `src/core/transport/fastapi/adapters/streaming/tool_block_buffer.py` created
- [ ] Class `ToolBlockBuffer` implements `IToolBlockBuffer`
- [ ] Constructor accepts optional `StreamContextRegistry` via DI
- [ ] Falls back to `get_global_streaming_context_registry()` if not provided
- [ ] `buffer(content: str, stream_id: str | None) -> str`:
  - Holds partial tool blocks until closing tag
  - Returns complete blocks immediately
  - Tracks detected tags in registry
- [ ] `flush() -> str` returns all pending content
- [ ] `reset() -> None` clears buffer state
- [ ] Excludes `<think>` and `<thought>` when no allowed_tools
- [ ] File is < 150 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/streaming/tool_block_buffer.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/streaming/test_tool_block_buffer.py`

**Dependencies**: Task 1.2

**Test Requirements** (TDD):

- [ ] Test partial block buffering
- [ ] Test complete block emission
- [ ] Test flush returns pending
- [ ] Test reset clears state
- [ ] Test tag tracking via registry
- [ ] Test allowed_tools filtering
- [ ] Test think/thought tag exclusion

---

### Task 4.2: Implement StreamingContentConverter

**ID**: `4.2`
**Requirements**: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8
**Priority**: P0
**Effort**: L (4-6 hours)

**Description**: Refactor the 670+ line `_streaming_adapter` closure into `StreamingContentConverter` class.

**Acceptance Criteria**:

- [ ] File `src/core/transport/fastapi/adapters/streaming/content_converter.py` created
- [ ] Class `StreamingContentConverter` implements `IStreamingContentConverter`
- [ ] Constructor accepts: `ISSEDecoder`, `IReasoningInjector`, `IUsageNormalizer`, `IToolBlockBuffer`
- [ ] Creates default instances if not provided
- [ ] `async def convert_stream(raw_stream, context) -> AsyncIterator[StreamingContent]`:
  - Normalizes `ProcessedResponse` and raw chunks uniformly
  - Decodes SSE payloads via injected decoder
  - Merges metadata from decoded content
  - Tracks usage data (keeps highest values)
  - Detects completion signals (finish_reason, [DONE], is_done)
  - Uses `await asyncio.sleep(0)` for event loop yielding
  - Handles GeneratorExit gracefully
- [ ] Nested helper functions become class methods
- [ ] State tracked in instance attributes
- [ ] File is < 300 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/streaming/content_converter.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/streaming/test_streaming_content_converter.py`

**Dependencies**: Tasks 1.4, 3.1, 2.3, 4.1

**Test Requirements** (TDD):

- [ ] Test ProcessedResponse normalization
- [ ] Test raw chunk normalization
- [ ] Test SSE payload decoding
- [ ] Test metadata merging
- [ ] Test usage tracking (highest values)
- [ ] Test finish_reason detection
- [ ] Test [DONE] marker detection
- [ ] Test is_done metadata detection
- [ ] Test event loop yielding
- [ ] Test GeneratorExit cleanup
- [ ] Test empty stream handling
- [ ] Property test: async path purity

---

### Task 4.3: Phase 4 Validation Gate

**ID**: `4.3`
**Requirements**: 12.1, 12.5, 13.7
**Priority**: P0
**Effort**: S (< 1 hour)

**Description**: Run full test suite to verify Phase 4 changes don't break existing functionality.

**Acceptance Criteria**:

- [ ] All new unit tests pass (Tasks 4.1-4.2)
- [ ] All Phase 1-3 tests still pass
- [ ] All existing tests pass unchanged
- [ ] All property tests pass
- [ ] No regressions in integration tests
- [ ] Git commit created with Phase 4 changes

**Command**:

```bash
.venv\Scripts\python.exe -m pytest tests/unit/ -v
```

**Dependencies**: Tasks 4.1, 4.2

---

## Phase 5: Facade & Cleanup (Days 12-14)

### Task 5.1: Create Thin Facade

**ID**: `5.1`
**Requirements**: 1.1, 1.2, 1.3, 1.4, 2.6
**Priority**: P0
**Effort**: M (2-3 hours)

**Description**: Create the new thin facade version of `response_adapters.py` that delegates to layer components.

**Acceptance Criteria**:

- [ ] Create backup of original file: `response_adapters.py.bak`
- [ ] New facade file is < 100 lines
- [ ] Exports: `to_fastapi_response`, `to_fastapi_streaming_response`, `domain_response_to_fastapi`
- [ ] Implements lazy singleton pattern for builders
- [ ] Falls back to default instances when DI unavailable
- [ ] Identical function signatures to original
- [ ] `__all__` exports same symbols

**Files to Modify**:

- `src/core/transport/fastapi/response_adapters.py` (complete rewrite)

**Dependencies**: Tasks 3.2, 3.3, 4.2

**Test Requirements**:

- [ ] All existing public API tests pass
- [ ] Function signatures unchanged
- [ ] Return types unchanged

---

### Task 5.2: Wire Integration

**ID**: `5.2`
**Requirements**: 1.5, 7.1-7.6
**Priority**: P0
**Effort**: M (2-3 hours)

**Description**: Integrate `WireCaptureCoordinator` into the facade and ensure all components work together.

**Acceptance Criteria**:

- [ ] Wire capture coordination integrated into facade
- [ ] Non-streaming responses schedule capture correctly
- [ ] Streaming responses wrap stream for capture
- [ ] All controller callers work unchanged
- [ ] Integration test passes

**Files to Modify**:

- `src/core/transport/fastapi/response_adapters.py` (add wire capture)

**Test Files to Create**:

- `tests/integration/transport/fastapi/test_response_adapters_integration.py`

**Dependencies**: Task 5.1

**Test Requirements**:

- [ ] Integration test: full non-streaming path
- [ ] Integration test: full streaming path
- [ ] Integration test: wire capture disabled
- [ ] Integration test: wire capture enabled

---

### Task 5.3: Remove Extracted Code

**ID**: `5.3`
**Requirements**: 2.2
**Priority**: P0
**Effort**: S (1-2 hours)

**Description**: Remove the original extracted code now that the facade is verified working.

**Acceptance Criteria**:

- [ ] Delete `response_adapters.py.bak` (after verification)
- [ ] No duplicate code remains between facade and layer modules
- [ ] All imports updated if needed
- [ ] Legacy file at `src/core/adapters/response_adapters.py` unchanged (per Req 1.6)

**Files to Modify**:

- `src/core/transport/fastapi/response_adapters.py` (final cleanup)

**Dependencies**: Task 5.2

---

### Task 5.4: Final Validation Gate

**ID**: `5.4`
**Requirements**: 12.1, 12.2, 12.5, 12.7, 13.7
**Priority**: P0
**Effort**: M (1-2 hours)

**Description**: Run complete test suite including integration tests to verify refactoring success.

**Acceptance Criteria**:

- [ ] All unit tests pass (all phases)
- [ ] All property tests pass
- [ ] All integration tests pass
- [ ] Legacy facade tests pass (`tests/unit/core/adapters/test_response_adapters.py`)
- [ ] No regressions in any test category
- [ ] Git commit created with final changes

**Commands**:

```bash
# Full test suite
.venv\Scripts\python.exe -m pytest tests/ -v

# Specific critical tests
.venv\Scripts\python.exe -m pytest tests/unit/test_response_adapters_properties.py -v
.venv\Scripts\python.exe -m pytest tests/unit/streaming/test_response_adapter_dict_handling.py -v
.venv\Scripts\python.exe -m pytest tests/unit/core/adapters/test_response_adapters.py -v
```

**Dependencies**: Task 5.3

---

### Task 5.5: Documentation Update

**ID**: `5.5`
**Requirements**: N/A (housekeeping)
**Priority**: P2
**Effort**: S (1 hour)

**Description**: Update documentation to reflect the new modular architecture.

**Acceptance Criteria**:

- [ ] Update `.kiro/steering/structure.md` to document new `adapters/` package
- [ ] Add README.md to `src/core/transport/fastapi/adapters/`
- [ ] Update any architecture diagrams if applicable
- [ ] Spec status updated to "implemented"

**Files to Create**:

- `src/core/transport/fastapi/adapters/README.md`

**Files to Modify**:

- `.kiro/steering/structure.md`
- `.kiro/specs/response-adapters-god-object-refactoring/spec.json`

**Dependencies**: Task 5.4

---

## Task Summary by Phase

| Phase | Tasks | Effort | Critical Path |
|-------|-------|--------|---------------|
| Phase 1 | 5 | Days 1-3 | 1.1 → 1.2 → 1.3, 1.4 → 1.5 |
| Phase 2 | 6 | Days 4-6 | 2.1-2.5 (parallel) → 2.6 |
| Phase 3 | 5 | Days 7-8 | 3.1-3.4 (parallel) → 3.5 |
| Phase 4 | 3 | Days 9-11 | 4.1 → 4.2 → 4.3 |
| Phase 5 | 5 | Days 12-14 | 5.1 → 5.2 → 5.3 → 5.4 → 5.5 |
| **Total** | **24 main tasks** | **1-2 weeks** | |

---

## Files Created Summary

### Source Files (20 files)

```
src/core/transport/fastapi/adapters/
├── __init__.py
├── protocols.py
├── sse/
│   ├── __init__.py
│   ├── formatter.py
│   └── decoder.py
├── metadata/
│   ├── __init__.py
│   └── reasoning_injector.py
├── usage/
│   ├── __init__.py
│   ├── normalizer.py
│   └── header_injector.py
├── sanitization/
│   ├── __init__.py
│   ├── header_sanitizer.py
│   └── json_sanitizer.py
├── capture/
│   ├── __init__.py
│   └── wire_capture_coordinator.py
├── streaming/
│   ├── __init__.py
│   ├── tool_block_buffer.py
│   └── content_converter.py
├── response/
│   ├── __init__.py
│   ├── json_response_builder.py
│   ├── streaming_response_builder.py
│   └── other_response_builder.py
└── README.md
```

### Test Files (14 files)

```
tests/unit/transport/fastapi/adapters/
├── test_protocols.py
├── sse/
│   ├── test_sse_formatter.py
│   └── test_sse_decoder.py
├── metadata/
│   └── test_reasoning_injector.py
├── usage/
│   ├── test_usage_normalizer.py
│   └── test_usage_header_injector.py
├── sanitization/
│   ├── test_header_sanitizer.py
│   └── test_json_sanitizer.py
├── capture/
│   └── test_wire_capture_coordinator.py
├── streaming/
│   ├── test_tool_block_buffer.py
│   └── test_streaming_content_converter.py
└── response/
    ├── test_json_response_builder.py
    ├── test_streaming_response_builder.py
    └── test_other_response_builder.py

tests/integration/transport/fastapi/
└── test_response_adapters_integration.py
```

---

_Generated: 2025-12-18T23:56:30+01:00_
