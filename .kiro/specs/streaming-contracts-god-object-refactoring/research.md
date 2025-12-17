# Research & Design Decisions: Streaming Contracts God Object Refactoring

## Summary
- **Feature**: `streaming-contracts-god-object-refactoring`
- **Discovery Scope**: Refactor / architecture hardening
- **Key Findings**:
  - `src/core/ports/streaming_contracts.py` is a mixed-responsibility module (contracts + parsing + serialization + error mapping).
  - The “ports” layer currently imports `httpx` and embeds vendor error mapping, violating boundary direction.
  - `StreamingContent` includes complex multi-provider parsing (`from_raw`) and transport serialization (`to_bytes`), inflating complexity and making unit testing difficult.

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

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|------|
| Facade + split modules | Keep `streaming_contracts.py` as re-export facade; move logic to smaller modules | Minimal churn; stable imports; meets size cap | Requires careful import ordering to avoid cycles | Recommended |
| Big move/rename | Rename module and update all imports | Cleaner end-state | High churn; risky; breaks tests/callers | Rejected |
| Partial split only | Only move `httpx` mapping out | Low effort | Leaves mega-method complexity intact | Insufficient |

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

