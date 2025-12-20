# Research & Design Decisions

## Summary
- **Feature**: `streaming-contracts-god-object-refactoring`
- **Discovery Scope**: Extension
- **Key Findings**:
  - `src/core/ports/streaming_contracts.py` is a mixed-responsibility “God Object” (contracts + parsing + serialization + vendor error mapping).
  - The contracts layer imports `httpx`, violating boundary direction (2.1).
  - Multiple pipelines emit SSE and done markers; tests assert byte-level SSE invariants (`b"data: [DONE]\n\n"`), so refactoring must preserve exact bytes (3.3, 4.4).
  - The codebase contains two different interfaces named `IStreamNormalizer` (ports vs services); unification is out of scope but must be documented to prevent boundary confusion.

## Research Log

### Existing Codebase Analysis
- **Components Reviewed**:
  - `src/core/ports/streaming_contracts.py` (primary refactor target)
  - `src/core/ports/sse_assembler.py` (SSE assembly)
  - `src/core/transport/fastapi/response_adapters.py` (FastAPI streaming adapter)
  - `src/core/services/stream_formatting_service.py` and `src/core/services/backend_service.py` (wire-capture streaming adapter)
  - Provider normalizers: `src/core/ports/openai_normalizer.py`, `src/core/ports/gemini_normalizer.py`, `src/core/ports/anthropic_normalizer.py`
  - Streaming orchestration: `src/core/ports/streaming_orchestrator.py`, `src/core/ports/streaming_integration.py`
  - Streaming processing pipeline: `src/core/services/streaming/stream_normalizer.py`
- **Patterns Identified**:
  - Legacy import surface is widespread (`from src.core.ports.streaming_contracts import ...`) and must remain stable (3.1).
  - Done marker behavior is enforced at multiple layers and must not duplicate markers (4.4).
  - StopChunkWithUsage is intentionally hostile to implicit serialization; many call sites rely on `dict(chunk)` conversion while preserving wrapper semantics (3.2, 4.1).
  - Contracts and transports are currently entangled; multiple modules implement SSE framing rules (risk of drift).
- **Implications**:
  - A single transport serializer must become the canonical source of SSE bytes to prevent inconsistent framing across pipelines (3.3).
  - The contracts surface must become a facade to reduce circular dependency risk and enable modular decomposition (1.1).

### Byte-Level SSE Contracts
- **Context**: Tests assert exact SSE bytes and marker behavior, not just semantic equivalence.
- **Sources Consulted**:
  - `tests/unit/transport/test_streaming_done_marker.py`
  - `tests/unit/test_streaming_normalizer.py`
  - `tests/unit/test_sse_assembler_unit.py`
  - `tests/unit/core/services/streaming/test_stream_formatting_service.py`
  - `tests/property/core/test_stream_formatting_service_properties.py`
  - `tests/unit/streaming/test_streaming_sse_serialization.py`
  - `tests/regression/test_stop_chunk_wrapper_preservation.py`
- **Findings**:
  - Final done marker must be exactly `b"data: [DONE]\\n\\n"` in multiple places.
  - When upstream already emits `data: [DONE]\\n\\n`, adapters must not append another marker.
  - StopChunkWithUsage must serialize as an SSE payload containing top-level usage followed by done marker.
  - `format_chunk_as_sse` must pass through payloads already starting with `data:` and normalize raw `[DONE]` / `["DONE"]` to `data: [DONE]\\n\\n`.
- **Implications**:
  - Option B requires a dedicated transport serializer that implements these byte-level rules and is used (directly or via delegation) by legacy entry points (3.3, 4.4).

### Interface Naming Collision: `IStreamNormalizer` x2
- **Context**: The same name is used for two distinct abstractions with different methods and roles.
- **Sources Consulted**:
  - `src/core/ports/streaming_contracts.py` (ports ABI: `normalize_stream`)
  - `src/core/interfaces/streaming_response_processor_interface.py` (services ABI: `process_stream`)
  - DI usage: `src/core/di/services.py`, `src/core/services/response_pipeline.py`, `src/connectors/streaming_utils.py`
  - Ports pipeline usage: `src/core/ports/streaming_orchestrator.py`
- **Findings**:
  - Ports interface is provider-normalizer oriented.
  - Services interface is middleware-pipeline oriented and DI-registered.
- **Implications**:
  - The refactor must avoid “crossing the streams” (ports components importing the services interface or vice versa) to prevent boundary violations and circular imports.
  - The decision is to document the distinction and keep unification out of scope for this spec.

### Error Mapping Reuse: `IExceptionNormalizer` is not a drop-in replacement
- **Context**: The project already has `ExceptionNormalizer`, but streaming tests enforce `httpx`-specific mappings.
- **Sources Consulted**:
  - `src/core/services/exception_normalizer.py`
  - `src/core/interfaces/exception_normalizer_interface.py`
  - Streaming error mapping tests: `tests/property/test_streaming_error_properties.py`, `tests/unit/core/ports/test_streaming_error_propagation.py`
- **Findings**:
  - `ExceptionNormalizer` relies on `exc.status_code` duck-typing; `httpx.HTTPStatusError` exposes status via `exc.response.status_code`.
  - Streaming requires deterministic mapping of `httpx.TimeoutException`, `httpx.ConnectError`, `httpx.HTTPStatusError`, and `json.JSONDecodeError` into `LLMProxyError` subclasses with stable metadata envelope keys.
- **Implications**:
  - Streaming error mapping must remain `httpx`-aware and live in the services layer to satisfy 2.1 while preserving behavior (3.3, 4.4).

### Complexity and LOC Guardrails
- **Context**: Requirements specify hard limits for LOC and cyclomatic complexity for the refactor surface area.
- **Sources Consulted**:
  - `scripts/analyze_complexity.py`
  - `.kiro/specs/streaming-contracts-god-object-refactoring/requirements.md`
- **Findings**:
  - Baseline: `src/core/ports/streaming_contracts.py` is 1858 LOC; max CC 111; total CC 396.
  - The repo contains other high-CC files; gates must be scoped to streaming-contracts surface area to avoid unrelated failures.
- **Implications**:
  - Add scoped enforcement for 1.1–1.5 rather than broad “whole-repo” enforcement.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|------|
| Extend existing components | Split code within existing ports modules | Lower churn | High risk of “relocating” complexity; boundaries remain blurry | Not chosen |
| Create new components | New layered modules + facade re-exports | Enforces boundaries; supports measurable gates | Requires careful migration to avoid circular imports | Chosen (Option B) |
| Hybrid incremental | Facade + delegated methods + phased extraction | Lower regression risk | Temporary duplication; more steps | Used as sequencing technique within Option B |

## Design Decisions

### Decision: Commit to Option B (Create New Components)
- **Context**: The target file violates hard LOC/CC constraints and boundary rules.
- **Alternatives Considered**:
  1. Extend existing components in place
  2. Create new layered modules (Option B)
- **Selected Approach**: Create domain/ports/transport/services modules and convert `src/core/ports/streaming_contracts.py` into a compatibility facade.
- **Rationale**: Enforces clear boundaries (2.1) and enables enforceable complexity constraints (1.1–1.5) without “moving the monolith”.
- **Trade-offs**: More files and careful import ordering required; mitigated by incremental migration and a facade.
- **Follow-up**: Ensure new serializer/parsers preserve byte-level invariants and that gates are scoped to streaming-contracts surface area.

### Decision: Keep `StreamingContent.from_raw` and `StreamingContent.to_bytes` as delegators
- **Context**: Many call sites and tests depend on these entry points (3.1).
- **Alternatives Considered**:
  1. Remove methods and update call sites
  2. Keep methods but delegate to extracted modules
- **Selected Approach**: Keep signatures stable and delegate to parsing and transport serialization modules.
- **Rationale**: Preserves compatibility while satisfying 1.3 and 1.4 through decomposition.
- **Trade-offs**: Requires careful API design for internal helpers to avoid circular imports.

### Decision: Streaming error mapping moves to services layer
- **Context**: Contracts layer must not import vendor libraries (2.1) but must preserve deterministic mapping behavior (tests).
- **Alternatives Considered**:
  1. Reuse `IExceptionNormalizer` directly
  2. Keep `httpx` mapping in a dedicated streaming error mapping module
- **Selected Approach**: Dedicated streaming error mapping module under `src/core/services/streaming/`.
- **Rationale**: Preserves existing behavior and supports vendor imports while restoring boundary direction.
- **Trade-offs**: Duplicates some normalization concepts; acceptable given differing input shapes and strict streaming metadata requirements.

### Decision: DI Lifetime Selection
- **Context**: Requirement 5.x prefers DI for new stateful collaborators.
- **Selected Approach**: Keep extracted parsing/serialization/error-mapping collaborators stateless; avoid introducing new DI registrations unless state is required.
- **Rationale**: Meets 5.1 and 5.2 by avoiding new state that would otherwise require DI.

### Decision: Error Handling Strategy
- **Context**: Streaming errors must yield structured terminal chunks.
- **Selected Approach**: Preserve the current error metadata envelope (`finish_reason="error"` and `metadata.error` keys) and keep mapping deterministic.
- **Rationale**: Existing tests enforce structure and determinism; regressions are high impact.

## Testing Strategy Research

### Existing Test Patterns
- Unit tests for serialization/done markers and streaming content behavior.
- Property tests for streaming contracts invariants and error mapping consistency.
- Regression tests for StopChunkWithUsage wrapper preservation.

### Coverage Requirements
- Critical paths: done marker emission/deduplication (4.4), StopChunkWithUsage serialization and leak prevention (3.2, 4.1), tool-call sanitization (4.3), structured error chunks (4.4).
- New tests expected: scoped complexity/LOC enforcement for refactor surface area (1.1–1.5).

## Risks & Mitigations
- Risk: Subtle SSE regressions due to multiple existing framing implementations - Mitigation: centralize byte-level rules in a single transport serializer and delegate legacy entry points (3.3, 4.4).
- Risk: Circular imports via facade re-exports - Mitigation: keep facade re-export-only and ensure extracted modules do not import the facade.
- Risk: Complexity gates fail due to unrelated modules - Mitigation: scope gates to streaming-contracts surface area only.

## Performance Considerations
- The serializer and parsers are in the hot path; the decomposition must not introduce per-chunk I/O or unbounded allocations.
- Prefer small strategy functions over large conditional blocks to reduce cyclomatic complexity while keeping runtime behavior stable.

## References
- `.kiro/specs/streaming-contracts-god-object-refactoring/design.md` - Architecture and contracts
- `src/core/ports/streaming_contracts.py` - Current “God Object” module
- `scripts/analyze_complexity.py` - Complexity reporting tool used for enforcement
- `tests/unit/transport/test_streaming_done_marker.py` - Done marker byte-level invariants
- `tests/unit/streaming/test_streaming_sse_serialization.py` - StopChunkWithUsage serialization invariants
