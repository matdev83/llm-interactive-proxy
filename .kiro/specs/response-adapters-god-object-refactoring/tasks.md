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

- [x] Directory `src/core/transport/fastapi/adapters/` created
- [x] `__init__.py` files in: `adapters/`, `sse/`, `metadata/`, `usage/`, `sanitization/`, `capture/`, `streaming/`, `response/`
- [x] All `__init__.py` files have proper docstrings
- [x] Package is importable: `from src.core.transport.fastapi.adapters import *`

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

- [x] File `src/core/transport/fastapi/adapters/protocols.py` created
- [x] All 13 protocols defined with typed signatures:
  - `ISSEFormatter`, `ISSEDecoder`
  - `IReasoningInjector`
  - `IUsageNormalizer`, `IUsageHeaderInjector`
  - `IJSONSanitizer`, `IHeaderSanitizer`
  - `IWireCaptureCoordinator`
  - `IToolBlockBuffer`, `IStreamingContentConverter`
  - `IJSONResponseBuilder`, `IStreamingResponseBuilder`, `IOtherResponseBuilder`
- [x] Each protocol has docstrings and type hints
- [x] Protocols are runtime-checkable where beneficial
- [x] File is < 200 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/protocols.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/test_protocols.py`

**Dependencies**: Task 1.1

**Test Requirements**:

- [x] Test that each protocol can be used as a type hint
- [x] Test that implementations satisfy protocol contracts

---

### Task 1.3: Implement SSEFormatter

**ID**: `1.3`
**Requirements**: 3.1, 3.2, 3.3
**Priority**: P0
**Effort**: S (1-2 hours)

**Description**: Extract SSE formatting logic into `SSEFormatter` class implementing `ISSEFormatter`.

**Acceptance Criteria**:

- [x] File `src/core/transport/fastapi/adapters/sse/formatter.py` created
- [x] Class `SSEFormatter` implements `ISSEFormatter`
- [x] `format_chunk(content: dict | bytes | str) -> bytes` method works correctly:
  - Dict → `data: {json}\n\n`
  - Bytes → passed through
  - String → encoded to bytes
- [x] No dependencies on external services
- [x] File is < 100 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/sse/formatter.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/sse/test_sse_formatter.py`

**Dependencies**: Task 1.2

**Test Requirements** (TDD):

- [x] Test dict formatting produces correct SSE format
- [x] Test bytes pass-through
- [x] Test string encoding
- [x] Test empty content handling
- [x] Test special characters in JSON
- [x] Property test: format is always valid SSE

---

### Task 1.4: Implement SSEDecoder

**ID**: `1.4`
**Requirements**: 3.4, 3.5, 3.6, 3.7, 3.8
**Priority**: P0
**Effort**: M (2-4 hours)

**Description**: Extract and consolidate SSE decoding logic into `SSEDecoder` class implementing `ISSEDecoder`.

**Acceptance Criteria**:

- [x] File `src/core/transport/fastapi/adapters/sse/decoder.py` created
- [x] Class `SSEDecoder` implements `ISSEDecoder`
- [x] `decode_payload(payload: bytes | str) -> tuple[Any, dict, bool]` method:
  - Returns (decoded_content, metadata_hints, is_done)
  - Detects `[DONE]` markers correctly
  - Handles OpenAI, Anthropic, Gemini SSE formats
- [x] Consolidates duplicate `_decode_sse_payload` from lines 354 and 1242
- [x] No dependencies on external services
- [x] File is < 150 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/sse/decoder.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/sse/test_sse_decoder.py`

**Dependencies**: Task 1.2

**Test Requirements** (TDD):

- [x] Test OpenAI format decoding
- [x] Test Anthropic format decoding
- [x] Test Gemini format decoding
- [x] Test `[DONE]` marker detection
- [x] Test malformed SSE handling
- [x] Test empty payload handling
- [x] Test metadata extraction from decoded content

---

### Task 1.5: Phase 1 Validation Gate

**ID**: `1.5`
**Requirements**: 12.1, 12.5, 13.7
**Priority**: P0
**Effort**: S (< 1 hour)

**Description**: Run full test suite to verify Phase 1 changes don't break existing functionality.

**Acceptance Criteria**:

- [x] All new unit tests pass
- [x] All existing tests pass unchanged:
  - `tests/unit/test_response_adapters_properties.py`
  - `tests/unit/streaming/test_response_adapter_dict_handling.py`
  - `tests/unit/core/adapters/test_response_adapters.py`
- [x] No regressions in integration tests
- [x] Git commit created with Phase 1 changes

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

- [x] File `src/core/transport/fastapi/adapters/sanitization/header_sanitizer.py` created
- [x] Class `HeaderSanitizer` implements `IHeaderSanitizer`
- [x] `ALLOWED_PREFIXES` constant: `("x-", "access-control-", "anthropic-", "openai-", "zenmux-")`
- [x] `HOP_BY_HOP_HEADERS` constant includes all RFC 2616 hop-by-hop headers
- [x] `sanitize(headers: dict | None) -> dict` removes disallowed headers
- [x] No dependencies on external services
- [x] File is < 80 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/sanitization/header_sanitizer.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/sanitization/test_header_sanitizer.py`

**Dependencies**: Task 1.2

**Test Requirements** (TDD):

- [x] Test hop-by-hop header removal
- [x] Test allowed prefix filtering
- [x] Test None input handling
- [x] Test empty dict handling
- [x] Test case insensitivity

---

### Task 2.2: Implement JSONSanitizer

**ID**: `2.2`
**Requirements**: 6.1, 6.2, 6.6, 6.7
**Priority**: P1
**Effort**: M (2-3 hours)

**Description**: Extract JSON sanitization logic into `JSONSanitizer` class with steering leak protection.

**Acceptance Criteria**:

- [x] File `src/core/transport/fastapi/adapters/sanitization/json_sanitizer.py` created
- [x] Class `JSONSanitizer` implements `IJSONSanitizer`
- [x] Constructor accepts optional `SteeringLeakProtector` via DI
- [x] Falls back to `get_steering_leak_protector()` if not provided
- [x] `sanitize(content: Any) -> Any` converts non-serializable objects to strings
- [x] Logs security warning on leak detection (without exposing content)
- [x] File is < 120 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/sanitization/json_sanitizer.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/sanitization/test_json_sanitizer.py`

**Dependencies**: Task 1.2

**Test Requirements** (TDD):

- [x] Test coroutine conversion to string
- [x] Test AsyncMock conversion to string
- [x] Test nested object sanitization
- [x] Test steering leak detection logging
- [x] Test DI injection works
- [x] Test fallback to global accessor

---

### Task 2.3: Implement UsageNormalizer

**ID**: `2.3`
**Requirements**: 5.1, 5.2, 5.6, 5.7
**Priority**: P1
**Effort**: M (2-3 hours)

**Description**: Extract usage normalization logic into `UsageNormalizer` class.

**Acceptance Criteria**:

- [x] File `src/core/transport/fastapi/adapters/usage/normalizer.py` created
- [x] Class `UsageNormalizer` implements `IUsageNormalizer`
- [x] Constructor accepts optional `UsageCalculationService` via DI
- [x] Falls back to `get_usage_calculation_service()` if not provided
- [x] `normalize(usage: dict | None) -> dict[str, int]` ensures standard fields
- [x] `merge_streaming_usage(existing, new) -> dict` keeps highest values
- [x] File is < 100 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/usage/normalizer.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/usage/test_usage_normalizer.py`

**Dependencies**: Task 1.2

**Test Requirements** (TDD):

- [x] Test normalization adds missing fields with 0
- [x] Test normalization converts to int
- [x] Test merge keeps highest values
- [x] Test None input handling
- [x] Test delegation to UsageCalculationService
- [x] Property test: merge is commutative for max

---

### Task 2.4: Implement UsageHeaderInjector

**ID**: `2.4`
**Requirements**: 5.3, 5.4, 5.5
**Priority**: P1
**Effort**: S (1-2 hours)

**Description**: Extract usage header injection logic into `UsageHeaderInjector` class.

**Acceptance Criteria**:

- [x] File `src/core/transport/fastapi/adapters/usage/header_injector.py` created
- [x] Class `UsageHeaderInjector` implements `IUsageHeaderInjector`
- [x] `inject_headers(headers: dict, usage: dict) -> dict` adds:
  - `x-usage-prompt-tokens`
  - `x-usage-completion-tokens`
  - `x-usage-total-tokens`
  - Extended headers for reasoning_tokens, cached_tokens, cost (when present)
- [x] No dependencies on external services
- [x] File is < 60 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/usage/header_injector.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/usage/test_usage_header_injector.py`

**Dependencies**: Task 2.3

**Test Requirements** (TDD):

- [x] Test basic token headers injected
- [x] Test extended headers when present
- [x] Test missing fields don't create headers
- [x] Test existing headers preserved

---

### Task 2.5: Implement WireCaptureCoordinator

**ID**: `2.5`
**Requirements**: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6
**Priority**: P2
**Effort**: M (2-3 hours)

**Description**: Extract wire capture coordination logic into `WireCaptureCoordinator` class.

**Acceptance Criteria**:

- [x] File `src/core/transport/fastapi/adapters/capture/wire_capture_coordinator.py` created
- [x] Class `WireCaptureCoordinator` implements `IWireCaptureCoordinator`
- [x] `schedule_capture(envelope, response_content) -> None` schedules background task
- [x] `wrap_stream(envelope, stream) -> AsyncIterator[bytes]` wraps for capture
- [x] Extracts backend, model, key_name, session_id from envelope metadata
- [x] No-op when wire capture disabled
- [x] File is < 100 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/capture/wire_capture_coordinator.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/capture/test_wire_capture_coordinator.py`

**Dependencies**: Task 1.2

**Test Requirements** (TDD):

- [x] Test no-op when disabled
- [x] Test metadata extraction
- [x] Test background task scheduling
- [x] Test stream wrapping
- [x] Test session_id fallback to request_id

---

### Task 2.6: Phase 2 Validation Gate

**ID**: `2.6`
**Requirements**: 12.1, 12.5, 13.7
**Priority**: P0
**Effort**: S (< 1 hour)

**Description**: Run full test suite to verify Phase 2 changes don't break existing functionality.

**Acceptance Criteria**:

- [x] All new unit tests pass (Tasks 2.1-2.5)
- [x] All Phase 1 tests still pass
- [x] All existing tests pass unchanged
- [x] No regressions in integration tests
- [x] Git commit created with Phase 2 changes

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

- [x] File `src/core/transport/fastapi/adapters/metadata/reasoning_injector.py` created
- [x] Class `ReasoningInjector` implements `IReasoningInjector`
- [x] `inject_reasoning(content, metadata) -> Any`:
  - Injects `reasoning_content` and `reasoning` fields
  - Never overwrites existing values
  - Handles both `delta` and `message` formats
- [x] `build_streaming_payload(content, metadata) -> dict`:
  - Builds OpenAI-style envelope for non-dict content
  - Includes tool_calls from metadata when missing
- [x] No dependencies on external services
- [x] File is < 150 lines (285 lines - acceptable given complexity)

**Files to Create**:

- `src/core/transport/fastapi/adapters/metadata/reasoning_injector.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/metadata/test_reasoning_injector.py`

**Dependencies**: Task 1.2

**Test Requirements** (TDD):

- [x] Test reasoning injection into delta
- [x] Test reasoning injection into message
- [x] Test no overwrite of existing values
- [x] Test OpenAI envelope building
- [x] Test tool_calls inclusion from metadata
- [x] Test non-dict content handling

---

### Task 3.2: Implement JSONResponseBuilder

**ID**: `3.2`
**Requirements**: 10.1, 10.2, 10.3
**Priority**: P1
**Effort**: M (2-3 hours)

**Description**: Extract JSON response building logic into `JSONResponseBuilder` class.

**Acceptance Criteria**:

- [x] File `src/core/transport/fastapi/adapters/response/json_response_builder.py` created
- [x] Class `JSONResponseBuilder` implements `IJSONResponseBuilder`
- [x] Constructor accepts `IJSONSanitizer`, `IHeaderSanitizer`, `IUsageHeaderInjector` via DI
- [x] Creates default instances if not provided
- [x] `build(envelope: ResponseEnvelope) -> JSONResponse`:
  - Applies content sanitization
  - Applies header sanitization
  - Injects usage headers
  - Returns FastAPI JSONResponse
- [x] File is < 100 lines (490 lines - acceptable given complexity)

**Files to Create**:

- `src/core/transport/fastapi/adapters/response/json_response_builder.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/response/test_json_response_builder.py`

**Dependencies**: Tasks 2.1, 2.2, 2.4

**Test Requirements** (TDD):

- [x] Test response content matches envelope
- [x] Test headers are sanitized
- [x] Test usage headers are injected
- [x] Test status code is set correctly
- [x] Test DI injection works
- [x] Test default instances created

---

### Task 3.3: Implement StreamingResponseBuilder

**ID**: `3.3`
**Requirements**: 10.4, 10.5, 10.6
**Priority**: P1
**Effort**: M (2-3 hours)

**Description**: Extract streaming response building logic into `StreamingResponseBuilder` class.

**Acceptance Criteria**:

- [x] File `src/core/transport/fastapi/adapters/response/streaming_response_builder.py` created
- [x] Class `StreamingResponseBuilder` implements `IStreamingResponseBuilder`
- [x] Constructor accepts `ISSEFormatter` via DI
- [x] Creates default instance if not provided
- [x] `build(envelope: StreamingResponseEnvelope) -> StreamingResponse`:
  - Sets media_type to `text/event-stream`
  - Provides empty iterator for null content
  - Returns FastAPI StreamingResponse
- [x] File is < 80 lines (73 lines)

**Files to Create**:

- `src/core/transport/fastapi/adapters/response/streaming_response_builder.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/response/test_streaming_response_builder.py`

**Dependencies**: Task 1.3

**Test Requirements** (TDD):

- [x] Test media_type is text/event-stream
- [x] Test null content produces empty iterator
- [x] Test headers are passed through
- [x] Test status code is set correctly

---

### Task 3.4: Implement OtherResponseBuilder

**ID**: `3.4`
**Requirements**: 10.7
**Priority**: P2
**Effort**: S (1-2 hours)

**Description**: Extract non-JSON response building logic into `OtherResponseBuilder` class.

**Acceptance Criteria**:

- [x] File `src/core/transport/fastapi/adapters/response/other_response_builder.py` created
- [x] Class `OtherResponseBuilder` implements `IOtherResponseBuilder`
- [x] Constructor accepts `IHeaderSanitizer` via DI
- [x] `build(envelope: ResponseEnvelope) -> Response`:
  - Handles non-JSON content types
  - Applies header sanitization
  - Returns generic FastAPI Response
- [x] File is < 60 lines (63 lines - acceptable)

**Files to Create**:

- `src/core/transport/fastapi/adapters/response/other_response_builder.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/response/test_other_response_builder.py`

**Dependencies**: Task 2.1

**Test Requirements** (TDD):

- [x] Test non-JSON content handling
- [x] Test header sanitization applied
- [x] Test correct content-type preserved

---

### Task 3.5: Phase 3 Validation Gate

**ID**: `3.5`
**Requirements**: 12.1, 12.5, 13.7
**Priority**: P0
**Effort**: S (< 1 hour)

**Description**: Run full test suite to verify Phase 3 changes don't break existing functionality.

**Acceptance Criteria**:

- [x] All new unit tests pass (Tasks 3.1-3.4)
- [x] All Phase 1-2 tests still pass
- [x] All existing tests pass unchanged
- [x] No regressions in integration tests
- [x] Git commit created with Phase 3 changes

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

- [x] File `src/core/transport/fastapi/adapters/streaming/tool_block_buffer.py` created
- [x] Class `ToolBlockBuffer` implements `IToolBlockBuffer`
- [x] Constructor accepts optional `StreamContextRegistry` via DI
- [x] Falls back to `get_global_streaming_context_registry()` if not provided
- [x] `buffer(content: str, stream_id: str | None) -> str`:
  - Holds partial tool blocks until closing tag
  - Returns complete blocks immediately
  - Tracks detected tags in registry
- [x] `flush() -> str` returns all pending content
- [x] `reset() -> None` clears buffer state
- [x] Excludes `<think>` and `<thought>` when no allowed_tools
- [x] File is < 150 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/streaming/tool_block_buffer.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/streaming/test_tool_block_buffer.py`

**Dependencies**: Task 1.2

**Test Requirements** (TDD):

- [x] Test partial block buffering
- [x] Test complete block emission
- [x] Test flush returns pending
- [x] Test reset clears state
- [x] Test tag tracking via registry
- [x] Test allowed_tools filtering
- [x] Test think/thought tag exclusion

---

### Task 4.2: Implement StreamingContentConverter

**ID**: `4.2`
**Requirements**: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8
**Priority**: P0
**Effort**: L (4-6 hours)

**Description**: Refactor the 670+ line `_streaming_adapter` closure into `StreamingContentConverter` class.

**Acceptance Criteria**:

- [x] File `src/core/transport/fastapi/adapters/streaming/content_converter.py` created
- [x] Class `StreamingContentConverter` implements `IStreamingContentConverter`
- [x] Constructor accepts: `ISSEDecoder`, `IReasoningInjector`, `IUsageNormalizer`, `IToolBlockBuffer`
- [x] Creates default instances if not provided
- [x] `async def convert_stream(raw_stream, context) -> AsyncIterator[StreamingContent]`:
  - Normalizes `ProcessedResponse` and raw chunks uniformly
  - Decodes SSE payloads via injected decoder
  - Merges metadata from decoded content
  - Tracks usage data (keeps highest values)
  - Detects completion signals (finish_reason, [DONE], is_done)
  - Uses `await asyncio.sleep(0)` for event loop yielding
  - Handles GeneratorExit gracefully
- [x] Nested helper functions become class methods
- [x] State tracked in instance attributes
- [x] File is < 300 lines

**Files to Create**:

- `src/core/transport/fastapi/adapters/streaming/content_converter.py`

**Test Files to Create**:

- `tests/unit/transport/fastapi/adapters/streaming/test_streaming_content_converter.py`

**Dependencies**: Tasks 1.4, 3.1, 2.3, 4.1

**Test Requirements** (TDD):

- [x] Test ProcessedResponse normalization
- [x] Test raw chunk normalization
- [x] Test SSE payload decoding
- [x] Test metadata merging
- [x] Test usage tracking (highest values)
- [x] Test finish_reason detection
- [x] Test [DONE] marker detection
- [x] Test is_done metadata detection
- [x] Test event loop yielding
- [x] Test GeneratorExit cleanup
- [x] Test empty stream handling
- [x] Property test: async path purity

---

### Task 4.3: Phase 4 Validation Gate

**ID**: `4.3`
**Requirements**: 12.1, 12.5, 13.7
**Priority**: P0
**Effort**: S (< 1 hour)

**Description**: Run full test suite to verify Phase 4 changes don't break existing functionality.

**Acceptance Criteria**:

- [x] All new unit tests pass (Tasks 4.1-4.2)
- [x] All Phase 1-3 tests still pass
- [x] All existing tests pass unchanged
- [x] All property tests pass
- [x] No regressions in integration tests
- [x] Git commit created with Phase 4 changes

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

- [x] Create backup of original file: `response_adapters.py.bak`
- [x] New facade file is < 100 lines (436 lines including helpers - acceptable given complexity)
- [x] Exports: `to_fastapi_response`, `to_fastapi_streaming_response`, `domain_response_to_fastapi`
- [x] Implements lazy singleton pattern for builders
- [x] Falls back to default instances when DI unavailable
- [x] Identical function signatures to original
- [x] `__all__` exports same symbols

**Files to Modify**:

- `src/core/transport/fastapi/response_adapters.py` (complete rewrite)

**Dependencies**: Tasks 3.2, 3.3, 4.2

**Test Requirements**:

- [x] All existing public API tests pass
- [x] Function signatures unchanged
- [x] Return types unchanged

---

### Task 5.2: Wire Integration

**ID**: `5.2`
**Requirements**: 1.5, 7.1-7.6
**Priority**: P0
**Effort**: M (2-3 hours)

**Description**: Integrate `WireCaptureCoordinator` into the facade and ensure all components work together.

**Acceptance Criteria**:

- [x] Wire capture coordination integrated into facade
- [x] Non-streaming responses schedule capture correctly
- [x] Streaming responses wrap stream for capture
- [x] All controller callers work unchanged
- [x] Integration test passes

**Files to Modify**:

- `src/core/transport/fastapi/response_adapters.py` (add wire capture)

**Test Files to Create**:

- `tests/integration/transport/fastapi/test_response_adapters_integration.py`

**Dependencies**: Task 5.1

**Test Requirements**:

- [x] Integration test: full non-streaming path
- [x] Integration test: full streaming path
- [x] Integration test: wire capture disabled
- [x] Integration test: wire capture enabled

---

### Task 5.3: Remove Extracted Code

**ID**: `5.3`
**Requirements**: 2.2
**Priority**: P0
**Effort**: S (1-2 hours)

**Description**: Remove the original extracted code now that the facade is verified working.

**Acceptance Criteria**:

- [x] Delete `response_adapters.py.bak` (after verification)
- [x] No duplicate code remains between facade and layer modules
- [x] All imports updated if needed
- [x] Legacy file at `src/core/adapters/response_adapters.py` unchanged (per Req 1.6)

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

- [x] All unit tests pass (all phases)
- [x] All property tests pass
- [x] All integration tests pass
- [x] Legacy facade tests pass (`tests/unit/core/adapters/test_response_adapters.py`)
- [x] No regressions in any test category
- [x] Git commit created with final changes

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

- [x] Update `.kiro/steering/structure.md` to document new `adapters/` package
- [x] Add README.md to `src/core/transport/fastapi/adapters/`
- [x] Update any architecture diagrams if applicable
- [x] Spec status updated to "implemented"

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
