# Research & Design Decisions: Streaming Contracts God Object Refactoring

## Summary
- **Feature**: `streaming-contracts-god-object-refactoring`
- **Discovery Scope**: Refactor / architecture hardening
- **Key Findings**:
  - `src/core/ports/streaming_contracts.py` is a mixed-responsibility module (contracts + parsing + serialization + error mapping).
  - The “ports” layer currently imports `httpx` and embeds vendor error mapping, violating boundary direction.
  - `StreamingContent` includes complex multi-provider parsing (`from_raw`) and transport serialization (`to_bytes`), inflating complexity and making unit testing difficult.
  - The implementation approach for this spec is explicitly **Option B (Create New Components)**; the facade remains, but responsibilities move to new domain/ports/transport/services modules.

## Research Log

### Current Public Surface (Compatibility Risk)
Observed widespread imports of:
- `StreamingContent`
- `StopChunkWithUsage`, `UsageChunkLeakError`
- `IStreamNormalizer`, `BaseStreamNormalizer`, `IStreamProcessor`, `IStreamAssembler`
- `SentinelManager`
- `StreamingErrorMapper`, `handle_streaming_error`

Implication: the refactor must preserve `src.core.ports.streaming_contracts` as a stable import facade (re-export layer).

### Current Responsibility Map (God Object Evidence)
From initial scan of `src/core/ports/streaming_contracts.py`:
- **Domain semantics**: usage stop-chunk wrapper and leak prevention.
- **Domain model**: `StreamingContent` with invariants and metadata normalization.
- **Provider parsing**: `from_raw` contains provider/format heuristics for OpenAI/Anthropic/Gemini, plus SSE parsing.
- **Transport serialization**: `to_bytes` emits SSE including terminal framing and tool-call sanitization.
- **Error mapping**: `httpx` exception mapping to `LLMProxyError` types.
- **Contracts**: streaming interfaces/protocols.

Implication: SRP is violated at module and class level; complexity is concentrated in methods that are hard to unit test in isolation.

### Existing Related Modules (Integration Considerations)
The codebase already contains streaming infrastructure outside `streaming_contracts.py`:
- `src/core/ports/sse_assembler.py` (SSE output assembly)
- Provider normalizers: `src/core/ports/openai_normalizer.py`, `src/core/ports/anthropic_normalizer.py`, `src/core/ports/gemini_normalizer.py`
- `src/core/ports/streaming_orchestrator.py` (pipeline orchestration)
- Service-side processing: `src/core/services/streaming/stream_normalizer.py` (applies processors; uses `StreamingContent.from_raw`)
- Parsing helpers: `src/core/domain/streaming_data_parsers/raw_data_parser.py` (delegates back to `StreamingContent.from_raw`)

Implication: `StreamingContent.from_raw` is a keystone dependency; the refactor should preserve it as a thin wrapper while moving branching logic into parser strategies.

### Byte-Level Compatibility Requirements (Concrete Tests)

The codebase contains multiple tests that require **byte-stable SSE behavior**, not just semantic equivalence. These must be treated as “byte-identical” constraints during refactor:

- **Done marker exact bytes**: final marker must be exactly `b"data: [DONE]\\n\\n"` in multiple places, including:
  - `tests/unit/transport/test_streaming_done_marker.py`
  - `tests/unit/test_transport_adapters.py`
  - `tests/unit/test_streaming_normalizer.py`
  - `tests/unit/test_sse_assembler_unit.py`
  - `tests/unit/test_response_adapters_properties.py`
  - `tests/unit/core/services/streaming/test_stream_formatting_service.py`
  - `tests/property/core/test_stream_formatting_service_properties.py`

- **No duplicate done markers**: when upstream already emits `data: [DONE]\\n\\n`, the adapter must not append another marker:
  - `tests/unit/transport/test_streaming_done_marker.py`

- **StopChunkWithUsage produces payload + done**: stop chunks must serialize as an SSE `data:` payload that includes top-level usage, and the overall output must end with `data: [DONE]\\n\\n`:
  - `tests/unit/streaming/test_streaming_sse_serialization.py`
  - `tests/regression/test_stop_chunk_wrapper_preservation.py`
  - `tests/unit/core/ports/test_usage_chunk_leak_prevention.py`

- **Raw “data:” passthrough**: `StreamFormattingService.format_chunk_as_sse` must pass through any content already starting with `data:` unchanged, and must normalize raw `[DONE]` / `["DONE"]` to `data: [DONE]\\n\\n`:
  - `tests/unit/core/services/streaming/test_stream_formatting_service.py`

Implementation implication (Option B): the new transport-layer serializer must reproduce these byte-level semantics exactly, and any legacy entry points (`StreamingContent.to_bytes`, `StreamFormattingService.format_chunk_as_sse`, `SSEAssembler`) should delegate to it rather than duplicating framing rules.

### Two “Stream Normalizer” Abstractions (Known Integration Challenge)

There are two distinct interfaces in the current codebase that share the name `IStreamNormalizer`:

1. **Ports/contracts normalizer** (provider-specific): `src/core/ports/streaming_contracts.py:IStreamNormalizer` with `normalize_stream(...) -> AsyncIterator[StreamingContent]`.
2. **Services/processing normalizer** (middleware pipeline): `src/core/interfaces/streaming_response_processor_interface.py:IStreamNormalizer` with `process_stream(...) -> AsyncGenerator[StreamingContent | bytes, None]`.

Observed usage patterns:
- DI wiring and the unified response pipeline depend on the **services** interface (`src/core/di/services.py`, `src/core/services/response_pipeline.py`, `src/connectors/streaming_utils.py`).
- The ports “streaming orchestrator” depends on the **ports/contracts** interface (`src/core/ports/streaming_orchestrator.py`) and the provider normalizers under `src/core/ports/*_normalizer.py`.

Implementation implication (Option B): this refactor must keep the contracts layer stable and decomposed, but it does **not** need to unify these two interfaces immediately. Documentation and module boundaries should clearly label which interface is used where to prevent cross-layer coupling and circular imports.

### Error Mapping Reuse Assessment (IExceptionNormalizer vs StreamingErrorMapper)

The repo already has an exception normalization service:
- `src/core/services/exception_normalizer.py:ExceptionNormalizer` implementing `src/core/interfaces/exception_normalizer_interface.py:IExceptionNormalizer`

However, it is **not a drop-in replacement** for streaming error mapping because:
- It relies on `exc.status_code` (duck-typed). `httpx.HTTPStatusError` uses `exc.response.status_code` instead, so it will not be normalized by default.
- Streaming requires consistent mapping for `httpx.TimeoutException`, `httpx.ConnectError`, `httpx.HTTPStatusError`, and `json.JSONDecodeError` into `LLMProxyError` subclasses with `{provider, stream_id}` context and stable metadata (`finish_reason="error"`, `metadata.error.{type,message,code,retryable}`), as enforced by:
  - `tests/property/test_streaming_error_properties.py`
  - `tests/unit/core/ports/test_streaming_error_propagation.py`

Implementation implication (Option B): move `StreamingErrorMapper` + `handle_streaming_error` into a **services-layer streaming error mapping module** and keep facade re-exports for backward compatibility. Optional later work may integrate `IExceptionNormalizer` behind that mapper, but it is not required for this refactor.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|------|
| Facade + split modules | Keep `streaming_contracts.py` as re-export facade; move logic to smaller modules | Minimal churn; stable imports; meets size cap | Requires careful import ordering to avoid cycles | Recommended |
| Big move/rename | Rename module and update all imports | Cleaner end-state | High churn; risky; breaks tests/callers | Rejected |
| Partial split only | Only move `httpx` mapping out | Low effort | Leaves mega-method complexity intact | Insufficient |

Note: The table above reflects early evaluation. The approved design and this spec now commit to **Option B** (“Create New Components”), which is implemented as “Facade + correctly layered new modules” rather than a rename or a partial split.

## Design Decisions (Expanded Rationale)

### Decision: “No relocation” guardrails
- **Context**: The user explicitly requires that the refactor does not simply move the same complexity from one file to another.
- **Selected approach**: Enforce per-file (<600 LOC) and per-function (CC ≤ 50) targets and structure the design around strategies (parsers/serializers) rather than “lift and shift”.
- **Verification**: Use radon metrics (via existing script or an enhanced reporting step) as a measurable gate.

### Decision: Keep `StreamingContent.from_raw` and `.to_bytes` for compatibility, but delegate
- **Context**: Many modules call these methods directly.
- **Selected approach**: Keep method signatures stable; reduce them to delegators into dedicated parsing/serialization modules.
- **Rationale**: Allows incremental migration with a stable public API while the underlying logic becomes modular.

## Risks & Mitigations
- Risk: Subtle streaming regressions (SSE is sensitive) - Mitigation: keep behavior stable via existing tests + add focused characterization tests for edge cases.
- Risk: Circular imports via facade re-exports - Mitigation: keep facade “dumb”, move cross-layer logic outward, and avoid importing orchestrators/assemblers from domain modules.
- Risk: Metrics enforcement gap (script doesn’t cover new files by default) - Mitigation: extend `scripts/analyze_complexity.py` or add a dedicated check script in tasks phase.

## Open Questions (Defer to Implementation/Design Adjustments if Needed)
- Whether the transport serializer should become the **single** implementation used by:
  - `StreamingContent.to_bytes`
  - `src/core/services/stream_formatting_service.py`
  - `src/core/ports/sse_assembler.py`
  - `src/core/transport/fastapi/response_adapters.py`
  (recommended), or whether a phased migration is required to avoid large diff churn.
- Whether/how to add an enforceable CI gate for LOC/CC thresholds (new script vs extending `scripts/analyze_complexity.py`) without impacting unrelated files.
