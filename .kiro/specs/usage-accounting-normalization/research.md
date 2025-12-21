# Research & Design Decisions

---
**Purpose**: Capture discovery findings, architectural investigations, and rationale that inform the technical design.

**Usage**:
- Log research activities and outcomes during the discovery phase.
- Document design decision trade-offs that are too detailed for `design.md`.
- Provide references and evidence for future audits or reuse.

**Project Context**: Universal LLM Proxy - FastAPI async, DI containers, staged initialization, adapter pattern.
---

## Summary
- **Feature**: `usage-accounting-normalization`
- **Discovery Scope**: Extension
- **Key Findings**:
  - Usage normalization is duplicated across translators, response adapters, and services, creating drift risk.
  - Streaming usage is captured, but incomplete outcomes are not represented explicitly.
  - Canonical usage data is not consistently available to wire capture or structured logging.

## Research Log
Document notable investigation steps and their outcomes. Group entries by topic for readability.

### Existing Codebase Analysis
- **Components Reviewed**:
  - `src/core/domain/usage_summary.py` and `src/core/domain/openrouter_usage.py`
  - `src/core/domain/translation_utils/usage_utils.py`
  - `src/core/services/usage_calculation_service.py`
  - `src/core/transport/fastapi/adapters/response/json_response_builder.py`
  - `src/core/services/backend_completion_flow/usage_accounting_orchestrator.py`
  - `src/core/services/usage_tracking_service.py`
  - `src/core/services/usage_tracking_wrapper.py`
  - `src/core/ports/usage_processor.py`
- **Patterns Identified**:
  - Multiple normalization entry points with overlapping responsibilities.
  - Usage data flows as `UsageSummary` or dicts depending on layer.
  - Streaming usage is derived from final chunks and wrappers but lacks an explicit outcome marker.
  - Logging favors fail-open behavior with warnings on failures.
- **Implications**: Introduce a single normalization service and a typed canonical usage contract to reduce drift and ensure downstream consistency.

### Usage Normalization Duplication
- **Context**: Requirements demand consistent canonical usage across protocols and backends.
- **Sources Consulted**:
  - `src/core/domain/translation_utils/usage_utils.py`
  - `src/core/transport/fastapi/adapters/usage/normalizer.py`
  - `src/core/transport/fastapi/adapters/response/json_response_builder.py`
  - `src/connectors/mixins/usage_calculation_mixin.py`
- **Findings**:
  - Multiple modules normalize usage with slightly different rules.
  - Provider extensions are sometimes flattened or dropped.
- **Implications**: Centralize normalization logic behind a single DI service and preserve extensions in a dedicated container.

### Streaming Outcome Handling
- **Context**: Requirement 3.4 mandates explicit incomplete reasons.
- **Sources Consulted**:
  - `src/core/services/usage_tracking_wrapper.py`
  - `src/core/ports/usage_processor.py`
  - `src/core/services/backend_completion_flow/usage_accounting_orchestrator.py`
- **Findings**:
  - Streaming usage is captured on stream completion but does not capture early termination reasons.
- **Implications**: Add outcome and reason fields to the canonical usage record and set them at streaming completion or error handling boundaries.

### Wire Capture and Logging Surface
- **Context**: Requirement 5.1 requires canonical usage exposure to wire capture and logs.
- **Sources Consulted**:
  - `src/core/services/backend_completion_flow/service.py`
  - `src/core/services/backend_completion_flow/wire_capture_orchestrator.py`
  - `src/core/domain/wire_capture.py`
- **Findings**:
  - Wire capture has a typed payload but no explicit canonical usage slot.
  - Logging for usage failures lacks standardized context keys.
- **Implications**: Add canonical usage to response metadata that wire capture can serialize; standardize warning context keys.

## Architecture Pattern Evaluation
| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Extend existing services | Add normalization logic to `UsageCalculationService` and adapters | Minimal new surface area | Risk of continued drift between adapters and services | Partial improvement |
| New normalization service | Introduce `UsageNormalizationService` with explicit contract | Single source of truth, clear DI boundary | New interface and wiring | Recommended |
| Hybrid approach | New service plus adapter-level shims for legacy callers | Safer migration, explicit compatibility | Temporary duplication during transition | Acceptable if phased |

## Design Decisions

### Decision: Canonical usage record model
- **Context**: Requirements need consistent usage representation with explicit unavailable fields.
- **Alternatives Considered**:
  1. Extend `UsageSummary` to add identifiers and outcomes.
  2. Create a new `CanonicalUsageRecord` model and map from existing usage types.
- **Selected Approach**: Create a new `CanonicalUsageRecord` Pydantic model that wraps canonical fields plus extensions.
- **Rationale**: Avoids breaking changes to existing `UsageSummary` usage while providing a clear contract.
- **Trade-offs**: Additional mapping step between canonical record and protocol usage payloads.
- **Follow-up**: Ensure adapters use canonical record for headers and payload projection.

### Decision: Normalization service boundary
- **Context**: Multiple normalization paths produce inconsistent outputs.
- **Alternatives Considered**:
  1. Keep logic in adapters and connectors with shared helper functions.
  2. Centralize normalization in a new DI service used by orchestrators and adapters.
- **Selected Approach**: Centralize normalization in `UsageNormalizationService`.
- **Rationale**: Aligns with DI patterns and avoids drift.
- **Trade-offs**: Requires integration updates at call sites.
- **Follow-up**: Ensure adapters and streaming wrapper call through the new service.

### Decision: DI Lifetime Selection
- **Context**: Usage normalization should be stateless and reusable.
- **Guidelines**:
  - **Singleton**: Stateless services, caches, configuration holders
  - **Scoped**: Per-request state, session-bound data
  - **Transient**: Stateful per-use, lightweight factories
- **Selected Approach**: Singleton.
- **Rationale**: Normalization logic is stateless and safe to reuse.

### Decision: Error Handling Strategy
- **Context**: Usage normalization must fail open and log context.
- **Guidelines**:
  - Extend `LLMProxyError` for domain errors
  - Use appropriate HTTP status codes
  - Never catch bare `Exception`
  - Log with `exc_info=True`
- **Selected Approach**: No new error types; log structured warnings and continue response flow.

## Testing Strategy Research

### Existing Test Patterns
- Unit tests in `tests/unit/` with mocked dependencies
- Integration tests in `tests/integration/` with DI container
- Property tests in `tests/property/` using Hypothesis
- Behavior tests in `tests/behavior/` for scenarios

### Test Infrastructure
- Fixtures in `tests/conftest.py`
- Mock backends in `tests/mocks/`
- Test utilities in `tests/utils/`

### Coverage Requirements
- Target: Focus on normalization correctness and regression coverage.
- Critical paths: Protocol response adapters, streaming completion, wire capture payloads.
- Edge cases: Missing usage, malformed usage, streaming aborts, extension preservation.

## Risks & Mitigations
- Risk 1: Breaking response compatibility by overwriting usage fields with zeros - Mitigation: merge canonical usage only when values are present.
- Risk 2: Incomplete streaming outcomes not detected consistently - Mitigation: define outcome resolution in backend completion flow error paths.
- Risk 3: Drift across legacy adapters during migration - Mitigation: introduce adapter shims that call the normalization service.

## Performance Considerations
- Async I/O impact: No new I/O; normalization remains in-process.
- Memory footprint: Small increase for canonical usage records per request.
- Wire capture overhead: Additional payload fields; ensure optional inclusion when enabled.

## References
- `src/core/domain/usage_summary.py` - Canonical usage summary
- `src/core/domain/openrouter_usage.py` - Provider usage details
- `src/core/domain/translation_utils/usage_utils.py` - Protocol normalization helpers
- `src/core/services/usage_calculation_service.py` - Recalculation logic
- `src/core/transport/fastapi/adapters/response/json_response_builder.py` - Response usage injection
- `src/core/services/backend_completion_flow/usage_accounting_orchestrator.py` - Orchestration and tracking
- `src/core/services/usage_tracking_service.py` - Usage persistence
- `src/core/services/usage_tracking_wrapper.py` - Streaming tracking
- `src/core/domain/wire_capture.py` - Capture model
